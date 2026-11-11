"""슬라이더 호버 썸네일의 키프레임 거친 띠 (yesoncheck/hover_keyframes.py) — Qt 없이 본다.

헤더 읽기(코덱·속도·시작 — 패킷 없이)와 그것으로 건너뛰는 규칙(all-intra 코덱·가변 속도), 키프레임 목록 읽기(패킷 JSON 해석 — pts → 프레임 번호,
버림(D) 패킷 제외), 만들지의 판단(coarse_wanted), 장수 줄이기(subsample), 거친 띠 저장소(KeyframeStrip — put 뒤에만 has/image, 가장 가까운 키프레임
nearest). ffprobe는 가짜 run(명령 → 종료 코드·stdout·stderr)으로 바꿔 끼우고, 진짜 ffprobe로는 짧은 GOP의 번호 H.264·그것을 편집 목록으로 자른
클립·ProRes 하나를 읽는다.
"""

import json
import subprocess
from fractions import Fraction

import pytest

from tests.prores_clips import make_numbered_clip, make_numbered_h264, run_ffmpeg
from yesoncheck import hover_keyframes
from yesoncheck.external_tools import ffprobe_path
from yesoncheck.hover_keyframes import (KeyframeStrip, StreamHeader, coarse_wanted, header_from_probe, header_skip_reason,
                                        probe_header, scan_keyframes, subsample)

H264 = StreamHeader(codec="h264", rate_text="24/1", rate=Fraction(24), start=Fraction(0))


def _packets_json(packets):
    return json.dumps({"packets": packets}).encode()


def _with_fillers(packets, total):
    """packets 뒤에 키프레임이 아닌 패킷을 붙여 모두 total개로 — 진짜 파일처럼 패킷 수가 전체 장수와 같게 (번호는 [0, 패킷 수 − 1]로 잘림)."""
    return packets + [{"pts_time": "0.041667", "flags": "___"}] * (total - len(packets))


def _fake_run(output, returncode=0, stderr=""):
    """probe_header·scan_keyframes의 run 대역 — 받은 명령을 calls에 적고 (종료 코드, stdout 바이트, stderr 글)."""
    calls = []

    def run(command):
        calls.append(command)
        return returncode, output, stderr

    return run, calls


@pytest.fixture(scope="module")
def gop12_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hover_keyframes") / "gop12.mp4")
    make_numbered_h264(path, count=60, gop=12)
    return path


# ---------------------------------------------------------------- 헤더 (패킷 없이 — 파일을 다 읽지 않음)


def test_header_command_and_parse():
    """헤더 명령은 영상 트랙 V:0의 코덱·속도·시작만 (패킷 없음). 속도는 분수 그대로, 시작이 없거나 N/A면 0."""
    run, calls = _fake_run(json.dumps({"streams": [{"codec_name": "h264", "r_frame_rate": "24000/1001",
                                                    "start_time": "0.500000"}]}).encode())
    header = probe_header("/opt/ffprobe", "/clips/a b.mp4", run=run)
    assert header == StreamHeader(codec="h264", rate_text="24000/1001", rate=Fraction(24000, 1001), start=Fraction(1, 2))
    assert calls == [["/opt/ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries",
                      "stream=codec_name,r_frame_rate,start_time", "-of", "json", "/clips/a b.mp4"]]
    for start in (None, "N/A"):
        stream = {"codec_name": "h264", "r_frame_rate": "24/1"}
        if start is not None:
            stream["start_time"] = start
        assert header_from_probe({"streams": [stream]}).start == 0


@pytest.mark.parametrize("rate", ["0/0", "", "90000/1", "241/1"])
def test_header_unknown_or_variable_rate_is_none(rate):
    """속도를 모르거나(0/0·없음) MAX_FRAME_RATE(240)를 넘으면(VFR의 90000/1) rate None — 번호를 정할 수 없음 (실패가 아니라 건너뛸 사유)."""
    header = header_from_probe({"streams": [{"codec_name": "h264", "r_frame_rate": rate}]})
    assert header.rate is None and header.rate_text == rate
    reason = header_skip_reason(header)
    assert reason.startswith("가변 프레임") and (rate or "없음") in reason


def test_header_without_video_track_raises():
    with pytest.raises(RuntimeError, match="영상 트랙"):
        header_from_probe({"streams": []})


@pytest.mark.parametrize("codec", ["prores", "dnxhd", "mjpeg", "rawvideo"])
def test_all_intra_codec_is_skipped_by_header(codec):
    """모든 장이 키프레임인 코덱은 패킷 스캔 없이 건너뜀 — 키프레임만 디코드해도 전부 디코드하는 꼴."""
    assert hover_keyframes.ALL_INTRA_CODECS == {"prores", "dnxhd", "mjpeg", "rawvideo"}
    reason = header_skip_reason(StreamHeader(codec=codec, rate_text="24/1", rate=Fraction(24), start=Fraction(0)))
    assert reason.startswith(f"all-intra 코덱 {codec}")


def test_long_gop_codec_is_not_skipped_by_header():
    assert header_skip_reason(H264) is None


def test_header_failure_raises_runtime_error_with_stderr():
    run, _ = _fake_run(b"", returncode=1, stderr="x.mov: No such file or directory\n")
    with pytest.raises(RuntimeError) as caught:
        probe_header("/opt/ffprobe", "x.mov", run=run)
    text = str(caught.value)
    assert "종료 코드 1" in text and "x.mov: No such file or directory" in text and "/opt/ffprobe -v error" in text
    assert text.startswith("ffprobe로 헤더를 읽지 못했습니다 ")


# ---------------------------------------------------------------- 키프레임 목록 (패킷 JSON)


def test_scan_command_and_keyframe_flags_only():
    """K 플래그가 있는 패킷만 (패킷은 디코드 순서 — B 프레임이면 pts가 뒤섞임 → 정렬). 명령은 영상 트랙 V:0의 패킷 pts·플래그만 (속도·시작은
    헤더에서). 두 번째 값은 버리지 않는 영상 패킷 수 (전체 장수의 짐작)."""
    packets = _with_fillers([{"pts_time": "0.000000", "flags": "K__"}, {"pts_time": "0.166667", "flags": "___"},
                             {"pts_time": "0.083333", "flags": "___"}, {"pts_time": "1.000000", "flags": "K__"},
                             {"pts_time": "0.500000", "flags": "K__"}], 30)
    run, calls = _fake_run(_packets_json(packets))
    assert scan_keyframes("/opt/ffprobe", "/clips/a b.mp4", H264, run=run) == ([0, 12, 24], 30)
    assert calls == [["/opt/ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries", "packet=pts_time,flags", "-of", "json",
                      "/clips/a b.mp4"]]


def test_scan_drops_discarded_packets():
    """둘째 플래그 D(버림 — 편집 목록으로 앞이 잘린 mp4의 'KD_')인 패킷은 -skip_frame nokey 출력에 나오지 않으므로 목록·패킷 수에서 뺌."""
    packets = _with_fillers([{"pts_time": "-0.333333", "flags": "KD_"}, {"pts_time": "-0.291667", "flags": "_D_"},
                             {"pts_time": "0.166667", "flags": "K__"}, {"pts_time": "0.666667", "flags": "K__"}], 32)
    run, _ = _fake_run(_packets_json(packets))
    assert scan_keyframes("ffprobe", "x.mp4", H264, run=run) == ([4, 16], 30)


def test_scan_subtracts_stream_start_and_uses_exact_rate():
    """프레임 번호 = round((pts − start_time) × r) — r은 분수 그대로(23.976 = 24000/1001), start_time은 헤더의 스트림 시작."""
    header = StreamHeader(codec="h264", rate_text="24000/1001", rate=Fraction(24000, 1001), start=Fraction(1, 2))
    packets = _with_fillers([{"pts_time": "0.500000", "flags": "K__"}, {"pts_time": "2.501833", "flags": "K__"}], 60)
    run, _ = _fake_run(_packets_json(packets))
    assert scan_keyframes("ffprobe", "x.mov", header, run=run) == ([0, 48], 60)  # (2.501833 − 0.5) × 23.976… = 48.00


def test_scan_clamps_to_packet_range():
    """시작보다 앞(음수)은 0, 패킷 수를 넘는 번호는 마지막 장 — [0, 패킷 수 − 1]로 자름 (반올림·편집 목록의 어긋남)."""
    packets = [{"pts_time": "-0.083333", "flags": "K__"}, {"pts_time": "0.041667", "flags": "___"},
               {"pts_time": "5.000000", "flags": "K__"}]
    run, _ = _fake_run(_packets_json(packets))
    assert scan_keyframes("ffprobe", "x.mov", H264, run=run) == ([0, 2], 3)


def test_scan_failure_raises_runtime_error_with_stderr():
    run, _ = _fake_run(b"", returncode=1, stderr="x.mov: No such file or directory\n")
    with pytest.raises(RuntimeError) as caught:
        scan_keyframes("/opt/ffprobe", "x.mov", H264, run=run)
    assert "종료 코드 1" in str(caught.value) and "x.mov: No such file or directory" in str(caught.value)
    assert str(caught.value).startswith("ffprobe로 키프레임을 읽지 못했습니다 ")


@pytest.mark.parametrize("packet", [{"flags": "K__"}, {"pts_time": "N/A", "flags": "K__"}])
def test_scan_rejects_keyframe_without_pts(packet):
    """키프레임 패킷에 pts가 없으면 지어내지 않고 RuntimeError (그 장을 빼면 ffmpeg 출력과 장수가 어긋남)."""
    run, _ = _fake_run(_packets_json([packet]))
    with pytest.raises(RuntimeError, match="pts"):
        scan_keyframes("ffprobe", "x.mov", H264, run=run)


def test_scan_needs_known_rate():
    """헤더의 속도가 None인데 스캔을 부르면(건너뛰기 사유를 보지 않은 버그) 크게 실패."""
    run, _ = _fake_run(_packets_json([{"pts_time": "0.0", "flags": "K__"}]))
    with pytest.raises(ValueError, match="속도"):
        scan_keyframes("ffprobe", "x.mov", StreamHeader(codec="h264", rate_text="0/0", rate=None, start=Fraction(0)), run=run)


def test_real_ffprobe_on_short_gop_h264(gop12_clip):
    """진짜 ffprobe (기본 run) — GOP 12의 번호 H.264 60장(B 프레임 포함): 헤더는 h264 24fps, 키프레임 0·12·24·36·48, 영상 패킷 60."""
    header = probe_header(ffprobe_path(), gop12_clip)
    assert (header.codec, header.rate, header.start) == ("h264", 24, 0) and header_skip_reason(header) is None
    assert scan_keyframes(ffprobe_path(), gop12_clip, header) == ([0, 12, 24, 36, 48], 60)


def test_real_ffprobe_on_edit_list_cut_h264(tmp_path, gop12_clip):
    """편집 목록으로 앞이 잘린 클립(-ss 1.3 -c copy — 1.0초(24번)의 키프레임부터 36장을 복사하고 그중 앞 8장(24~31번)은 버림(D)으로 표시):
    버림 키프레임(KD_)은 목록에 없고 패킷 수도 버림을 뺀 28. 남은 키프레임 36·48번은 잘린 클립에서 4·16번."""
    cut = str(tmp_path / "cut.mp4")
    run_ffmpeg(["-ss", "1.3", "-i", gop12_clip, "-c", "copy", cut], "편집 목록 클립")
    header = probe_header(ffprobe_path(), cut)
    assert scan_keyframes(ffprobe_path(), cut, header) == ([4, 16], 28)


def test_real_ffprobe_header_of_prores(tmp_path):
    path = str(tmp_path / "numbered.mov")
    make_numbered_clip(path, count=12)
    header = probe_header(ffprobe_path(), path)
    assert header.codec == "prores" and header_skip_reason(header).startswith("all-intra 코덱 prores")


def test_default_run_uses_no_shell_and_decodes_stderr(monkeypatch):
    """기본 run은 셸 없이 인자 리스트 그대로 subprocess.run (stdin 없음) — stderr는 UTF-8 글로."""
    seen = {}

    def fake_subprocess_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 3, b"", "한글 오류".encode())

    monkeypatch.setattr(hover_keyframes.subprocess, "run", fake_subprocess_run)
    with pytest.raises(RuntimeError, match="한글 오류"):
        probe_header("ffprobe", "x.mov")
    assert seen["command"][0] == "ffprobe" and seen["stdin"] == subprocess.DEVNULL and "shell" not in seen


# ---------------------------------------------------------------- 만들지의 판단


def test_coarse_wanted_rules():
    """거친 띠는 정확한 띠보다 싸게 먼저 보일 때만: 간격 > 1(긴 파일)이고 키프레임이 전체의 1/4 이하. keyframes를 주지 않으면 간격만 봄(스캔 전)."""
    assert "간격 1" in coarse_wanted(300, 1)
    assert "간격 1" in coarse_wanted(300, 1, 10)  # 간격이 먼저
    assert coarse_wanted(32_553, 66) is None  # 스캔 전 — 간격만 통과
    assert coarse_wanted(32_553, 66, 558) is None  # FL106 애니매틱
    assert coarse_wanted(1000, 2, 250) is None  # 경계: K × 4 == 전체
    reason = coarse_wanted(1000, 2, 251)
    assert reason is not None and "251" in reason and "1000" in reason
    assert coarse_wanted(1000, 2, 1000) is not None  # 거의 모든 장이 키프레임
    assert "키프레임 없음" in coarse_wanted(1000, 2, 0)


def test_subsample():
    """MAX_COARSE를 넘으면 m = ceil(K / 최대)마다 하나 — 목록은 frames[::m] (워커가 받은 i번째 장 중 i % m == 0만 넣는 규칙과 짝)."""
    frames = list(range(0, 2500 * 10, 10))  # 2500장
    picked, every = subsample(frames, 1000)
    assert every == 3 and picked == frames[::3] and len(picked) == 834
    assert subsample(frames[:1000], 1000) == (frames[:1000], 1)
    assert subsample(frames[:1001], 1000) == (frames[:1001:2], 2)
    assert subsample([5], 1000) == ([5], 1)
    assert hover_keyframes.MAX_COARSE == 1000


# ---------------------------------------------------------------- 거친 띠 저장소


def test_keyframe_strip_put_has_image():
    strip = KeyframeStrip([0, 12, 24], 320, 180)
    assert strip.frames == (0, 12, 24) and strip.count == 3 and strip.frame_bytes == 320 * 180 * 3
    assert strip.filled_count == 0 and not strip.has(1) and strip.nbytes == 3 * 320 * 180 * 3
    with pytest.raises(LookupError):
        strip.image(1)
    buffer = bytearray([7]) * strip.frame_bytes
    strip.put(1, memoryview(buffer))
    buffer[0] = 99  # 넣은 뒤 원본을 고쳐도 그대로 (복사)
    assert strip.has(1) and strip.filled_count == 1 and strip.image(1).shape == (180, 320, 3) and int(strip.image(1)[0, 0, 0]) == 7
    with pytest.raises(ValueError):
        strip.put(2, b"\x00" * (strip.frame_bytes - 1))
    assert not strip.has(2) and strip.filled_count == 1  # 길이가 틀린 put은 표시를 남기지 않음


@pytest.mark.parametrize("frames", [[], [12, 0], [0, 12, 5]])
def test_keyframe_strip_rejects_empty_or_unsorted(frames):
    with pytest.raises(ValueError):
        KeyframeStrip(frames, 320, 180)


@pytest.mark.parametrize("frame, expected", [
    (0, 0), (-5, 0),  # 앞 끝
    (300, 3), (36, 3), (999, 3),  # 뒤 끝
    (12, 1), (17, 1), (19, 2), (24, 2),  # 중간 — 가까운 쪽
    (6, 0), (18, 1),  # 같은 거리면 앞쪽
])
def test_keyframe_strip_nearest(frame, expected):
    strip = KeyframeStrip([0, 12, 24, 36], 320, 180)
    assert strip.nearest(frame) == expected


def test_keyframe_strip_nearest_with_repeated_number_picks_first():
    """반올림으로 같은 번호가 둘이면(가변 프레임 등) 첫 번째 — 출력의 j번째와 목록의 j번째가 짝이므로 목록은 그대로 둠."""
    strip = KeyframeStrip([0, 12, 12, 24], 320, 180)
    assert strip.count == 4 and strip.nearest(12) == 1 and strip.nearest(13) == 1 and strip.nearest(23) == 3
