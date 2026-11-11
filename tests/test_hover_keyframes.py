"""슬라이더 호버 썸네일의 키프레임 거친 띠 (yesoncheck/hover_keyframes.py) — Qt 없이 본다.

키프레임 목록 읽기(ffprobe JSON 해석 — pts → 프레임 번호), 만들지의 판단(coarse_wanted), 장수 줄이기(subsample), 거친 띠 저장소(KeyframeStrip —
put 뒤에만 has/image, 가장 가까운 키프레임 nearest). ffprobe는 가짜 run(명령 → 종료 코드·stdout·stderr)으로 바꿔 끼우고, 진짜 ffprobe로는
짧은 GOP의 H.264 하나만 읽는다(번호 목록이 GOP 계산과 같은지).
"""

import json
import subprocess

import pytest

from tests.prores_clips import make_numbered_h264
from yesoncheck import hover_keyframes
from yesoncheck.external_tools import ffprobe_path
from yesoncheck.hover_keyframes import KeyframeStrip, coarse_wanted, scan_keyframes, subsample


def _probe_json(packets, rate="24/1", start="0.000000"):
    stream = {"r_frame_rate": rate}
    if start is not None:
        stream["start_time"] = start
    return json.dumps({"packets": packets, "streams": [stream]}).encode()


def _with_fillers(packets, total):
    """packets 뒤에 키프레임이 아닌 패킷을 붙여 모두 total개로 — 진짜 파일처럼 패킷 수가 전체 장수와 같게 (번호는 [0, 패킷 수 − 1]로 잘림)."""
    return packets + [{"pts_time": "0.041667", "flags": "___"}] * (total - len(packets))


def _fake_run(output, returncode=0, stderr=""):
    """scan_keyframes의 run 대역 — 받은 명령을 calls에 적고 (종료 코드, stdout 바이트, stderr 글)."""
    calls = []

    def run(command):
        calls.append(command)
        return returncode, output, stderr

    return run, calls


# ---------------------------------------------------------------- 키프레임 목록 (ffprobe JSON)


def test_scan_command_and_keyframe_flags_only():
    """K 플래그가 있는 패킷만 (패킷은 디코드 순서 — B 프레임이면 pts가 뒤섞임 → 정렬). 명령은 영상 트랙 V:0(attached_pic 제외)의 패킷 pts·플래그와
    스트림의 시작·속도를 JSON으로. 두 번째 값은 영상 패킷 수 (전체 장수의 짐작)."""
    packets = _with_fillers([{"pts_time": "0.000000", "flags": "K__"}, {"pts_time": "0.166667", "flags": "___"},
                             {"pts_time": "0.083333", "flags": "___"}, {"pts_time": "1.000000", "flags": "K_D"},
                             {"pts_time": "0.500000", "flags": "K__"}, {"pts_time": "0.541667", "flags": "_D_"}], 30)
    run, calls = _fake_run(_probe_json(packets))
    assert scan_keyframes("/opt/ffprobe", "/clips/a b.mp4", run=run) == ([0, 12, 24], 30)
    assert calls == [["/opt/ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries",
                      "stream=start_time,r_frame_rate:packet=pts_time,flags", "-of", "json", "/clips/a b.mp4"]]


def test_scan_subtracts_stream_start_and_uses_exact_rate():
    """프레임 번호 = round((pts − start_time) × r) — r은 분수 그대로(23.976 = 24000/1001), start_time은 스트림의 첫 시각."""
    packets = _with_fillers([{"pts_time": "0.500000", "flags": "K__"}, {"pts_time": "2.501833", "flags": "K__"}], 60)
    run, _ = _fake_run(_probe_json(packets, rate="24000/1001", start="0.500000"))
    frames, packets_seen = scan_keyframes("ffprobe", "x.mov", run=run)
    assert frames == [0, 48] and packets_seen == 60  # (2.501833 − 0.5) × 23.976… = 48.00


@pytest.mark.parametrize("start", [None, "N/A"])
def test_scan_without_start_time_counts_from_zero(start):
    packets = _with_fillers([{"pts_time": "0.000000", "flags": "K__"}, {"pts_time": "0.500000", "flags": "K__"}], 24)
    run, _ = _fake_run(_probe_json(packets, start=start))
    assert scan_keyframes("ffprobe", "x.mov", run=run) == ([0, 12], 24)


def test_scan_clamps_to_packet_range():
    """시작보다 앞(음수)은 0, 패킷 수를 넘는 번호는 마지막 장 — [0, 패킷 수 − 1]로 자름 (편집 목록·반올림의 어긋남)."""
    packets = [{"pts_time": "-0.083333", "flags": "K__"}, {"pts_time": "0.041667", "flags": "___"},
               {"pts_time": "5.000000", "flags": "K__"}]
    run, _ = _fake_run(_probe_json(packets))
    assert scan_keyframes("ffprobe", "x.mov", run=run) == ([0, 2], 3)


def test_scan_failure_raises_runtime_error_with_stderr():
    """ffprobe가 0이 아닌 코드로 끝나면 RuntimeError — 파일·명령·종료 코드·stderr 전문 (부른 쪽이 거친 띠만 건너뛰고 기록)."""
    run, _ = _fake_run(b"", returncode=1, stderr="x.mov: No such file or directory\n")
    with pytest.raises(RuntimeError) as caught:
        scan_keyframes("/opt/ffprobe", "x.mov", run=run)
    text = str(caught.value)
    assert "종료 코드 1" in text and "x.mov: No such file or directory" in text and "/opt/ffprobe -v error" in text


@pytest.mark.parametrize("info, needle", [
    ({"packets": [{"pts_time": "0.0", "flags": "K__"}], "streams": []}, "영상 트랙"),
    ({"packets": [{"pts_time": "0.0", "flags": "K__"}], "streams": [{"r_frame_rate": "0/0"}]}, "프레임 속도"),
    ({"packets": [{"pts_time": "0.0", "flags": "K__"}], "streams": [{"r_frame_rate": "90000/1"}]}, "프레임 속도"),
    ({"packets": [{"flags": "K__"}], "streams": [{"r_frame_rate": "24/1"}]}, "pts"),
    ({"packets": [{"pts_time": "N/A", "flags": "K__"}], "streams": [{"r_frame_rate": "24/1"}]}, "pts"),
])
def test_scan_rejects_what_it_cannot_place(info, needle):
    """번호를 정할 수 없는 경우는 지어내지 않고 RuntimeError — 영상 트랙 없음·프레임 속도를 모름(VFR의 90000/1 포함)·키프레임 패킷에 pts 없음
    (그 장을 빼면 ffmpeg 출력과 장수가 어긋남)."""
    run, _ = _fake_run(json.dumps(info).encode())
    with pytest.raises(RuntimeError, match=needle):
        scan_keyframes("ffprobe", "x.mov", run=run)


def test_scan_real_ffprobe_on_short_gop_h264(tmp_path):
    """진짜 ffprobe (기본 run) — GOP 12의 번호 H.264 60장(B 프레임 포함): 키프레임 0·12·24·36·48, 영상 패킷 60."""
    path = str(tmp_path / "gop12.mp4")
    make_numbered_h264(path, count=60, gop=12)
    assert scan_keyframes(ffprobe_path(), path) == ([0, 12, 24, 36, 48], 60)


def test_default_run_uses_no_shell_and_decodes_stderr(monkeypatch):
    """기본 run은 셸 없이 인자 리스트 그대로 subprocess.run (stdin 없음) — stderr는 UTF-8 글로."""
    seen = {}

    def fake_subprocess_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 3, b"", "한글 오류".encode())

    monkeypatch.setattr(hover_keyframes.subprocess, "run", fake_subprocess_run)
    with pytest.raises(RuntimeError, match="한글 오류"):
        scan_keyframes("ffprobe", "x.mov")
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
    assert coarse_wanted(1000, 2, 1000) is not None  # all-intra (ProRes) — 키프레임만 디코드해도 전부
    assert "키프레임 없음" in coarse_wanted(1000, 2, 0)


def test_subsample():
    """MAX_COARSE를 넘으면 m = ceil(K / 최대)마다 하나 — 목록은 frames[::m] (ffmpeg의 select=not(mod(n,m))와 같은 규칙)."""
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
