"""ProRes 파이프 스파이크: 클립 공장 자가 검증 + 가정 확정 (앱 코드 없이 ffmpeg subprocess 직접).

확정할 것 (계획서 Task 1 Step 7): ① ffmpeg 파이프(-fps_mode passthrough) 대 cv2 — 먼저 프레임 정렬(같은 그림끼리 같은
위치인가), 그다음 바이트 동일성(회색 번호 클립 + 유채색 클립), ② -ss 착지가 K=0·K=2 각각 정확한지, ③ 세션 재시작 시간.
수치는 print("SPIKE ...")로 남는다 (ASCII만 — Windows 러너 콘솔 인코딩 대비) — 바이트 동일성은 단언 직전에 클립별 통계
(다른 프레임 수·최대 차이·다른 화소 %·부호 있는 차이 분포)를 찍어서, 실패해도 pytest가 보여 주는 captured stdout에 수치가 남는다.
통과한 시험의 print는 pytest -s 또는 -rP 로 봄. 시간은 단언하지 않고(러너마다 다름) 디코드 결과의 정확성(프레임 번호·장수)만 단언한다. 모든 외부 프로세스에 timeout이 있고,
파이프 읽기가 모자라면 kill 뒤 stderr를 읽어 예외 메시지에 싣는다.
"""

import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
from fractions import Fraction

import cv2
import numpy as np
import pytest

from tests.prores_clips import (
    HEIGHT, MAX_COUNT, TIMEOUT_PIPE, TIMEOUT_PROBE, WIDTH, ToolTimeout, ffmpeg_exe, frame_number, ideal_frame,
    make_audio_first, make_chroma_clip, make_held, make_neg, make_numbered_clip, make_rot, make_truncated,
    make_vfr_h264, make_voff, read_all_frames, run_tool,
)

FRAME_BYTES = WIDTH * HEIGHT * 3
COUNT = 120
SEED = 20261029


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 120장 24fps 번호 클립 (frame_number로 복호). 인코더 입력 10비트, 디코더 출력은 12비트(yuv444p12le)."""
    path = str(tmp_path_factory.mktemp("prores_clip") / "numbered_4444.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


@pytest.fixture(scope="session")
def prores_422_clip(tmp_path_factory):
    """422 HQ 10비트 120장 23.976fps(24000/1001) 번호 클립."""
    path = str(tmp_path_factory.mktemp("prores_422") / "numbered_422.mov")
    make_numbered_clip(path, count=COUNT, fps="24000/1001", profile="3", pix_fmt="yuv422p10le")
    return path


@pytest.fixture(scope="session")
def prores_alpha_clip(tmp_path_factory):
    """알파 트랙이 있는 4444 120장 24fps 번호 클립. 인코더 입력 10비트, 디코더 출력은 yuva444p12le."""
    path = str(tmp_path_factory.mktemp("prores_alpha") / "numbered_alpha.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuva444p10le")
    return path


@pytest.fixture(scope="session")
def prores_422_chroma_clip(tmp_path_factory):
    """422 HQ 유채색(시드 고정 무작위 블록) 48장 — chroma 업샘플링 경로까지 보려는 클립."""
    path = str(tmp_path_factory.mktemp("prores_422_chroma") / "chroma_422.mov")
    make_chroma_clip(path, count=48, fps="24", profile="3", pix_fmt="yuv422p10le", seed=7)
    return path


@pytest.fixture(scope="session")
def prores_4444_chroma_clip(tmp_path_factory):
    """4444 유채색(시드 고정 무작위 블록) 48장."""
    path = str(tmp_path_factory.mktemp("prores_4444_chroma") / "chroma_4444.mov")
    make_chroma_clip(path, count=48, fps="24", profile="4", pix_fmt="yuv444p10le", seed=11)
    return path


@pytest.fixture(scope="session")
def voff_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("voff") / "voff.mov")
    make_voff(path)
    return path


@pytest.fixture(scope="session")
def held_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("held") / "held.mov")
    make_held(path)
    return path


@pytest.fixture(scope="session")
def neg_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("neg") / "neg.mov")
    make_neg(path)
    return path


@pytest.fixture(scope="session")
def rot_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("rot") / "rot.mov")
    make_rot(path)
    return path


@pytest.fixture(scope="session")
def audio_first_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("audio_first") / "audio_first.mov")
    make_audio_first(path)
    return path


@pytest.fixture(scope="session")
def truncated_clip(tmp_path_factory, prores_422_clip):
    path = str(tmp_path_factory.mktemp("truncated") / "truncated.mov")
    make_truncated(prores_422_clip, path, cut_ratio=0.7)
    return path


@pytest.fixture(scope="session")
def vfr_h264_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("vfr_h264") / "vfr.mp4")
    make_vfr_h264(path)
    return path


# ---------------------------------------------------------------- 도구

def ffprobe_json(path):
    exe = shutil.which("ffprobe")
    assert exe, "ffprobe를 PATH에서 찾지 못했습니다"
    result = run_tool([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path], "ffprobe", TIMEOUT_PROBE)
    return json.loads(result.stdout)


def video_stream(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def clip_timing(path):
    """(r_frame_rate, 영상 start − 형식 start 초)."""
    info = ffprobe_json(path)
    video = video_stream(info)
    start = Fraction(video["start_time"]) - Fraction(info["format"]["start_time"])
    return Fraction(video["r_frame_rate"]), float(start)


def pipe_all(path, passthrough=True):
    """처음부터 끝까지 한 번에 읽은 프레임 (n, H, W, 3) — 앱 코드 없이 ffmpeg 직접."""
    cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-i", path, "-map", "0:V:0"]
    if passthrough:
        cmd += ["-fps_mode", "passthrough"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    data = run_tool(cmd, f"ffmpeg 파이프 전체 읽기 ({os.path.basename(path)}, passthrough={passthrough})", TIMEOUT_PIPE).stdout
    assert len(data) % FRAME_BYTES == 0, f"파이프 출력 {len(data)}바이트는 프레임 크기 {FRAME_BYTES}의 배수가 아닙니다"
    return np.frombuffer(data, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)


class PipeSession:
    """ffmpeg 파이프 프로세스 하나. timeout 초 뒤에도 안 끝나면 감시 스레드가 죽여 막힌 read를 풀고, 나갈 때 항상 kill·정리."""

    def __init__(self, cmd, purpose, timeout=TIMEOUT_PIPE):
        self.cmd, self.purpose, self.timeout, self.timed_out = cmd, purpose, timeout, False
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._timer = threading.Timer(timeout, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self):
        self.timed_out = True
        self.proc.kill()

    def read_frame(self):
        return self.proc.stdout.read(FRAME_BYTES)

    def failure(self, what):
        """실패 원인 글: 프로세스를 죽이고 stderr 전문을 읽어 용도·명령·종료 상태와 함께 돌려줌."""
        self.proc.kill()
        self.proc.wait()
        stderr = self.proc.stderr.read().decode("utf-8", "replace")
        cause = f"{self.timeout}초 timeout으로 죽임" if self.timed_out else f"종료 코드 {self.proc.returncode}"
        return f"{self.purpose}: {what} ({cause})\n명령 {self.cmd}\nstderr: {stderr}"

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._timer.cancel()
        self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()
        self.proc.stderr.close()


def pipe_restart(path, n, k_back, fps, start_offset):
    """목표 n으로 세션 재시작: -ss (n-k)/fps (+영상 start 보정) 뒤 k+1장 읽음. (읽은 프레임 목록, 걸린 초) — 앱 설계와 같은 모양.

    k+1장이 안 오면 AssertionError (원인 stderr 포함).
    """
    k = min(k_back, n)
    t = float((n - k) / fps) + start_offset
    cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", f"{t:.6f}", "-i", path, "-map", "0:V:0",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    started = time.perf_counter()
    frames = []
    with PipeSession(cmd, f"세션 재시작 {os.path.basename(path)} n={n} K={k_back} -ss {t:.6f}") as session:
        for _ in range(k + 1):
            buf = session.read_frame()
            if len(buf) < FRAME_BYTES:
                raise AssertionError(session.failure(f"{len(frames)}장만 도착 (기대 {k + 1})"))
            frames.append(np.frombuffer(buf, np.uint8).reshape(HEIGHT, WIDTH, 3))
        elapsed = time.perf_counter() - started
    return frames, elapsed


def frame_alignment_problem(cv2_frames, pipe_frames, numbered):
    """프레임 i끼리 같은 그림인지. 같으면 None, 아니면 설명 글.

    번호 클립은 frame_number 수열이 같은지(이것이 프레임 정확도 계약의 본체). 유채색 클립은 번호가 없으므로 각 파이프 프레임에
    가장 가까운(블록 평균 거리) cv2 프레임이 같은 위치인지 본다. 설명 글은 print에도 쓰이므로 ASCII만.
    """
    if numbered:
        cv2_numbers = [frame_number(f) for f in cv2_frames]
        pipe_numbers = [frame_number(f) for f in pipe_frames]
        if pipe_numbers == cv2_numbers:
            return None
        first = next(i for i, (a, b) in enumerate(zip(cv2_numbers, pipe_numbers)) if a != b)
        return (f"frame_number sequences differ: first mismatch at index {first}, cv2 {cv2_numbers[first:first + 5]} "
                f"pipe {pipe_numbers[first:first + 5]}")

    def signature(frame):
        return frame.astype(np.float32).reshape(HEIGHT // 6, 6, WIDTH // 5, 5, 3).mean(axis=(1, 3)).ravel()

    cv2_sigs = np.stack([signature(f) for f in cv2_frames])
    wrong = []
    for i, frame in enumerate(pipe_frames):
        nearest = int(np.argmin(((cv2_sigs - signature(frame)) ** 2).sum(axis=1)))
        if nearest != i:
            wrong.append((i, nearest))
    return f"nearest cv2 frame is at a different index (pipe index, cv2 index) {wrong[:5]}" if wrong else None


def byte_diff_stats(cv2_frames, pipe_frames):
    """같은 장수의 두 프레임열 비교 통계 — 다른 프레임 수, 최대 |차이|(int16), 다른 화소·값 %, 부호 있는 차이(파이프-cv2) 분포."""
    differing, max_abs, pixels, samples, total_pixels, total_samples = [], 0, 0, 0, 0, 0
    histogram = {}
    for i, (cv2_frame, pipe_frame) in enumerate(zip(cv2_frames, pipe_frames)):
        delta = pipe_frame.astype(np.int16) - cv2_frame.astype(np.int16)
        changed = delta != 0
        if changed.any():
            differing.append(i)
        max_abs = max(max_abs, int(np.abs(delta).max()))
        pixels += int(changed.any(axis=2).sum())
        samples += int(changed.sum())
        total_pixels += changed.shape[0] * changed.shape[1]
        total_samples += changed.size
        values, counts = np.unique(delta[changed], return_counts=True)
        for value, count in zip(values, counts):
            histogram[int(value)] = histogram.get(int(value), 0) + int(count)
    return {"differing": differing, "frames": len(cv2_frames), "max_abs": max_abs,
            "pixel_pct": 100.0 * pixels / total_pixels, "sample_pct": 100.0 * samples / total_samples,
            "histogram": dict(sorted(histogram.items(), key=lambda kv: -kv[1])[:8])}


def report_pipe_vs_cv2(label, name, cv2_frames, pipe_frames, numbered):
    """정렬 문제와 바이트 통계를 계산해 단언보다 먼저 print. (문제 글 또는 None, 통계 또는 None) 반환.

    장수·모양이 다르면 통계를 낼 수 없으므로 그 사실을 문제 글로 돌려주고 통계는 None — 호출자는 루프가 끝난 뒤에 단언하므로
    다른 클립의 통계는 항상 출력된다. 문제 글은 print에도 쓰이므로 ASCII만.
    """
    if len(pipe_frames) != len(cv2_frames) or (len(cv2_frames) and pipe_frames[0].shape != cv2_frames[0].shape):
        problem = (f"frame count/shape mismatch: cv2 {len(cv2_frames)} frames {cv2_frames[0].shape if len(cv2_frames) else None}, "
                   f"pipe {len(pipe_frames)} frames {pipe_frames[0].shape if len(pipe_frames) else None}")
        print(f"SPIKE {label} {name}: aligned False ({problem})")
        return problem, None
    problem = frame_alignment_problem(cv2_frames, pipe_frames, numbered)
    stats = byte_diff_stats(cv2_frames, pipe_frames)
    print(f"SPIKE {label} {name}: aligned {problem is None}" + (f" ({problem})" if problem else ""))
    print(f"SPIKE {label} {name}: differing_frames {len(stats['differing'])}/{stats['frames']} max_abs_diff {stats['max_abs']}"
          f" differing_pixels {stats['pixel_pct']:.4f}% differing_samples {stats['sample_pct']:.4f}%"
          f" pipe_minus_cv2 {stats['histogram']} first_differing_frames {stats['differing'][:8]}")
    return problem, stats


def stats_summary(stats):
    return (f"differing frames {len(stats['differing'])}/{stats['frames']}, max |diff| {stats['max_abs']}, "
            f"differing pixels {stats['pixel_pct']:.4f}%, diff histogram (pipe-cv2) {stats['histogram']}")


def seek_targets(count, seed):
    """무작위 40목표: 0·1·마지막 2프레임 강제 포함."""
    rng = random.Random(seed)
    forced = [0, 1, count - 2, count - 1]
    rest = rng.sample([n for n in range(count) if n not in forced], 40 - len(forced))
    return forced + rest


# ---------------------------------------------------------------- 클립 공장 자가 검증

def test_numbered_clip_roundtrip(prores_clip):
    frames = read_all_frames(prores_clip)
    assert len(frames) == COUNT
    assert [frame_number(f) for f in frames] == list(range(COUNT))


def test_numbered_clip_frames_distinct(prores_clip):
    frames = read_all_frames(prores_clip)
    for i in range(len(frames) - 1):
        assert frames[i].tobytes() != frames[i + 1].tobytes(), f"프레임 {i}와 {i + 1}이 바이트까지 같습니다"


def test_numbered_clip_variants_roundtrip(prores_422_clip, prores_alpha_clip):
    """422 10비트와 알파 4444도 전 프레임 번호가 정확하고 이웃 프레임이 서로 다름 (자가 검증이 통과해야 클립이 만들어짐).

    ffprobe의 pix_fmt는 디코더 쪽 값: 4444는 인코더 입력이 10비트여도 12비트(yuva444p12le)로 나온다.
    """
    info_422 = video_stream(ffprobe_json(prores_422_clip))
    info_alpha = video_stream(ffprobe_json(prores_alpha_clip))
    assert (info_422["profile"], info_422["pix_fmt"], info_422["r_frame_rate"]) == ("HQ", "yuv422p10le", "24000/1001")
    assert (info_alpha["profile"], info_alpha["pix_fmt"]) == ("4444", "yuva444p12le")
    for path in (prores_422_clip, prores_alpha_clip):
        frames = read_all_frames(path)
        assert [frame_number(f) for f in frames] == list(range(COUNT))
        assert all(frames[i].tobytes() != frames[i + 1].tobytes() for i in range(COUNT - 1))


def test_frame_number_survives_level_drift():
    """복호 견고성: 합성 프레임(인코딩 산술로 직접 만든 이상적 디코드)에 밝기 이동·이득을 얹어도 번호가 그대로.

    플랫폼 디코더의 실제 드리프트(CI Mac cv2는 -1~-2)와 분리하려고 디코드한 프레임이 아니라 합성 프레임에 교란을 얹는다 —
    이 시험은 인코딩 자체의 복호 반올림 경계를 고정한다. 번호 0~199 전부(hi 최대 14*18=252 구간, 번호 182 이상 포함).
    """
    ideal = [ideal_frame(i) for i in range(MAX_COUNT)]
    assert [frame_number(f) for f in ideal] == list(range(MAX_COUNT))
    assert int(ideal[MAX_COUNT - 1].max()) == 252  # 마지막 번호는 hi = 14 구간(바탕 밝기 252)

    def perturb(frame, delta=0, gain=1.0):
        return np.clip(np.rint(frame.astype(np.float32) * gain) + delta, 0, 255).astype(np.uint8)

    for delta in (-8, -5, -2, 2, 5, 8):
        assert [frame_number(perturb(f, delta=delta)) for f in ideal] == list(range(MAX_COUNT)), f"밝기 {delta:+d}"
    for gain in (0.97, 1.03):
        assert [frame_number(perturb(f, gain=gain)) for f in ideal] == list(range(MAX_COUNT)), f"이득 {gain}"
    # 허용 폭(STEP 18 -> 8 레벨) 바로 밖에서는 실제로 깨짐 — 위 통과가 '교란이 없어서'가 아님을 보장
    for delta in (-10, 10):
        assert [frame_number(perturb(f, delta=delta)) for f in ideal] != list(range(MAX_COUNT)), f"밝기 {delta:+d}"


def test_numbered_clip_max_count_decodes(tmp_path):
    """상한 200장도 번호가 정확히 복호되고 이웃 프레임이 서로 다름 (hi 최대 14*18=252가 255 안에 듦)."""
    path = str(tmp_path / "max_count.mov")
    make_numbered_clip(path, count=200, fps="24", profile="4", pix_fmt="yuv444p10le")
    frames = read_all_frames(path)
    assert [frame_number(f) for f in frames] == list(range(200))
    assert all(frames[i].tobytes() != frames[i + 1].tobytes() for i in range(199))


def test_numbered_clip_rejects_too_many_frames(tmp_path):
    with pytest.raises(ValueError, match="count"):
        make_numbered_clip(str(tmp_path / "too_many.mov"), count=201)


def test_numbered_clip_rejects_non_native_pix_fmt(tmp_path):
    """prores_ks가 못 받는 pix_fmt(12비트)는 ffmpeg가 경고만 내고 몰래 변환하므로 만들기 전에 막는다."""
    with pytest.raises(ValueError, match="prores_ks"):
        make_numbered_clip(str(tmp_path / "twelve_bit.mov"), pix_fmt="yuv444p12le")


def test_chroma_clips_are_chromatic_and_deterministic(prores_422_chroma_clip, prores_4444_chroma_clip, tmp_path):
    """유채색 클립: 프로파일·장수, 색이 실제로 있음, 같은 시드는 같은 화면·다른 시드는 다른 화면."""
    video = video_stream(ffprobe_json(prores_422_chroma_clip))
    assert (video["profile"], video["pix_fmt"], int(video["nb_frames"])) == ("HQ", "yuv422p10le", 48)
    video = video_stream(ffprobe_json(prores_4444_chroma_clip))
    assert (video["profile"], video["pix_fmt"], int(video["nb_frames"])) == ("4444", "yuv444p12le", 48)
    frames = read_all_frames(prores_422_chroma_clip)
    assert len(frames) == 48
    assert float(np.abs(frames[0][..., 0].astype(np.int16) - frames[0][..., 2].astype(np.int16)).mean()) > 10
    same_seed = str(tmp_path / "same_seed.mov")
    other_seed = str(tmp_path / "other_seed.mov")
    make_chroma_clip(same_seed, count=48, profile="3", pix_fmt="yuv422p10le", seed=7)
    make_chroma_clip(other_seed, count=48, profile="3", pix_fmt="yuv422p10le", seed=8)
    assert np.array_equal(np.stack(read_all_frames(same_seed)), np.stack(frames))
    assert not np.array_equal(np.stack(read_all_frames(other_seed)), np.stack(frames))


def test_run_tool_reports_failure_and_timeout():
    """외부 프로세스 실패·스톨은 용도·명령·stderr를 담은 예외 (삼키지 않음)."""
    with pytest.raises(RuntimeError, match=r"시험 실패 용도.*exit 3.*boom") as failed:
        run_tool([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], "시험 실패 용도", 30)
    assert "-c" in str(failed.value)
    with pytest.raises(ToolTimeout, match=r"시험 스톨 용도.*1초") as stalled:
        run_tool([sys.executable, "-c", "import time; time.sleep(60)"], "시험 스톨 용도", 1)
    assert "time.sleep" in str(stalled.value)


def test_pipe_restart_failure_carries_stderr(tmp_path):
    """읽을 파일이 없으면 짧은 읽기 대신 ffmpeg stderr가 든 AssertionError."""
    with pytest.raises(AssertionError, match="No such file") as failed:
        pipe_restart(str(tmp_path / "missing.mov"), 5, 2, Fraction(24), 0.0)
    assert "0장만 도착" in str(failed.value)


def test_boundary_clips_have_their_traits(voff_clip, held_clip, neg_clip, rot_clip, audio_first_clip, truncated_clip,
                                          prores_422_clip, vfr_h264_clip):
    """경계 클립 7종이 각자 의도한 모양인지 — 이후 Task의 게이트·탐색 시험이 이 성질에 기댄다."""
    # voff: 영상 start 0.5초, 형식 start 0 (소리 트랙이 0부터), 장수는 그대로 120
    info = ffprobe_json(voff_clip)
    assert Fraction(video_stream(info)["start_time"]) == Fraction(1, 2)
    assert Fraction(info["format"]["start_time"]) == 0
    assert [frame_number(f) for f in read_all_frames(voff_clip)] == list(range(COUNT))

    # held: 한 프레임이 2배 길이 — 정확 등식 nb_frames/r == duration_ts*time_base가 깨짐 (120/24=5초 ≠ 121/24초)
    video = video_stream(ffprobe_json(held_clip))
    duration = int(video["duration_ts"]) * Fraction(video["time_base"])
    assert int(video["nb_frames"]) == COUNT
    assert Fraction(COUNT) / Fraction(video["r_frame_rate"]) != duration
    assert duration == Fraction(COUNT + 1, 24)
    assert Fraction(video["avg_frame_rate"]) != Fraction(video["r_frame_rate"])
    assert [frame_number(f) for f in read_all_frames(held_clip)] == list(range(COUNT))

    # neg: 편집 목록으로 앞 2장 잘림 — nb_frames 120인데 실제 재생 118장, 번호는 2부터
    video = video_stream(ffprobe_json(neg_clip))
    assert int(video["nb_frames"]) == COUNT
    assert int(video["duration_ts"]) * Fraction(video["time_base"]) == Fraction(COUNT - 2, 24)
    assert [frame_number(f) for f in read_all_frames(neg_clip)] == list(range(2, COUNT))

    # rot: ffprobe는 320x180에 회전 ±90, cv2는 돌려서 180x320
    video = video_stream(ffprobe_json(rot_clip))
    assert (video["width"], video["height"]) == (WIDTH, HEIGHT)
    rotations = [d["rotation"] for d in video.get("side_data_list", []) if "rotation" in d]
    assert [abs(r) for r in rotations] == [90]
    frames = read_all_frames(rot_clip)
    assert len(frames) == COUNT and frames[0].shape[:2] == (WIDTH, HEIGHT)
    assert [frame_number(f) for f in frames] == list(range(COUNT))  # 번호 위치가 회전에 닫혀 있어 돌아간 프레임도 복호됨

    # audio_first: 소리가 index 0, 영상이 index 1
    info = ffprobe_json(audio_first_clip)
    assert [s["codec_type"] for s in info["streams"]] == ["audio", "video"]
    assert [frame_number(f) for f in read_all_frames(audio_first_clip)] == list(range(COUNT))

    # truncated: 헤더(faststart)는 멀쩡해 ffprobe는 120장이라 하지만 데이터가 중간에서 끊겨 cv2는 일부만 읽음
    video = video_stream(ffprobe_json(truncated_clip))
    assert int(video["nb_frames"]) == COUNT
    frames = read_all_frames(truncated_clip)
    assert 0 < len(frames) < COUNT
    assert [frame_number(f) for f in frames] == list(range(len(frames)))
    assert os.path.getsize(truncated_clip) < os.path.getsize(prores_422_clip)

    # vfr_h264: ProRes가 아니고(게이트 ① 음성) 프레임 간격이 들쭉날쭉
    video = video_stream(ffprobe_json(vfr_h264_clip))
    assert video["codec_name"] == "h264"
    assert Fraction(video["avg_frame_rate"]) != Fraction(video["r_frame_rate"])
    assert int(video["nb_frames"]) == COUNT


# ---------------------------------------------------------------- 스파이크

def test_spike_byte_identity(prores_clip, prores_422_clip, prores_alpha_clip, prores_422_chroma_clip,
                             prores_4444_chroma_clip):
    """4444·422·알파(회색 번호 클립)와 422·4444 유채색 클립: ffmpeg 파이프(-fps_mode passthrough) 대 cv2.

    (a) 프레임 정렬(번호 클립은 frame_number 수열 동일) 먼저, (b) 그다음 전 프레임 바이트 동일. 클립별 통계는 단언 전에 모두 print.
    회색만으로는 chroma 경로 차이를 못 보므로 유채색 클립(시드 고정 무작위 블록 색)을 함께 본다.
    """
    ffmpeg_line = run_tool([ffmpeg_exe(), "-version"], "ffmpeg 버전", TIMEOUT_PROBE).stdout.decode().splitlines()[0]
    print(f"\nSPIKE env: {platform.system()} {platform.machine()} | cv2 {cv2.__version__} | {ffmpeg_line}")
    clips = (("4444", prores_clip, True), ("422", prores_422_clip, True), ("alpha", prores_alpha_clip, True),
             ("422_chroma", prores_422_chroma_clip, False), ("4444_chroma", prores_4444_chroma_clip, False))
    misaligned, not_identical = [], []
    for name, path, numbered in clips:
        problem, stats = report_pipe_vs_cv2("byte_identity", name, read_all_frames(path), pipe_all(path), numbered)
        if problem:
            misaligned.append((name, problem))
        if stats and stats["differing"]:
            not_identical.append((name, stats_summary(stats)))
    assert not misaligned, f"(a) 프레임 정렬 어긋남: {misaligned}"
    assert not not_identical, f"(b) cv2와 파이프 바이트 불일치 (클립, 통계): {not_identical}"


def test_spike_passthrough_frame_count(voff_clip, held_clip):
    """voff·held: passthrough가 있으면 cv2와 장수 일치 → 프레임 정렬(frame_number 수열) → 바이트 일치, 없으면 복제 프레임으로 장수가 어긋남.

    정렬과 바이트 통계는 단언 전에 print.
    """
    misaligned, not_identical = [], []
    for name, path in (("voff", voff_clip), ("held", held_clip)):
        cv2_frames = read_all_frames(path)
        with_pass = pipe_all(path, passthrough=True)
        without = pipe_all(path, passthrough=False)
        print(f"SPIKE passthrough_count {name}: cv2 {len(cv2_frames)} passthrough {len(with_pass)} default {len(without)}")
        if len(cv2_frames) != COUNT:
            misaligned.append((name, f"cv2 read {len(cv2_frames)} frames, expected {COUNT}"))
        if len(without) <= len(cv2_frames):
            misaligned.append((name, f"without passthrough the frame count is not larger ({len(without)} vs cv2 "
                                     f"{len(cv2_frames)}) - the command difference is gone"))
        problem, stats = report_pipe_vs_cv2("passthrough_bytes", name, cv2_frames, with_pass, numbered=True)
        if problem:
            misaligned.append((name, problem))
        if stats and stats["differing"]:
            not_identical.append((name, stats_summary(stats)))
    assert not misaligned, f"(a) passthrough 파이프와 cv2의 프레임 정렬 어긋남: {misaligned}"
    assert not not_identical, f"(b) passthrough인데 cv2와 바이트가 다름 (클립, 통계): {not_identical}"


def test_spike_seek_landing(prores_clip, prores_422_clip, voff_clip):
    """무작위 40목표 × K∈{0,2}: -ss (n-K)/fps 뒤 K장 버림 → frame_number == n (voff는 영상 start 보정 포함).

    K=0도 K=2도 전부 정확해야 통과 — K=0 통과가 세 플랫폼에서 나와야 SEEK_BACK_K = 0 채택 (Step 7 판정).
    """
    failures = []
    for name, path in (("4444@24", prores_clip), ("422@23.976", prores_422_clip), ("voff@24+0.5s", voff_clip)):
        fps, start_offset = clip_timing(path)
        targets = seek_targets(COUNT, SEED)
        assert len(targets) == 40
        for k_back in (0, 2):
            wrong = []
            for n in targets:
                frames, _ = pipe_restart(path, n, k_back, fps, start_offset)
                landed = frame_number(frames[min(k_back, n)])
                if landed != n:
                    wrong.append((n, landed))
            print(f"SPIKE seek_landing {name} K={k_back}: exact {len(targets) - len(wrong)}/{len(targets)}"
                  + (f" wrong(target, landed) {wrong}" if wrong else ""))
            if wrong:
                failures.append((name, f"K={k_back}", wrong))
    assert not failures, f"착지 어긋남 (클립, K, [(목표, 착지)]): {failures}"


def test_spike_restart_timing(prores_clip):
    """세션 재시작 10회(K=2·K=0)의 시간은 print만 — 단언은 디코드 결과: 둘 다 k+1장 도착하고 목표 번호 정확."""
    fps, start_offset = clip_timing(prores_clip)
    rng = random.Random(SEED)
    targets = rng.sample(range(2, COUNT), 10)
    medians = {}
    for k_back in (2, 0):
        times = []
        for n in targets:
            frames, elapsed = pipe_restart(prores_clip, n, k_back, fps, start_offset)
            k = min(k_back, n)
            assert len(frames) == k + 1
            assert frame_number(frames[k]) == n, f"재시작 n={n} K={k_back}: 착지 {frame_number(frames[k])}"
            times.append(elapsed * 1000)
        medians[k_back] = statistics.median(times)
        print(f"SPIKE restart_ms K={k_back}: " + " ".join(f"{t:.0f}" for t in times)
              + f" | median {medians[k_back]:.0f} max {max(times):.0f}")
    # 비교용: 이미 돌아가는 세션에서 순차로 한 장 읽는 값 (같은 320x180 — 4K 수치는 이 Mac 실측 기록 참고)
    cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-i", prores_clip, "-map", "0:V:0", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    with PipeSession(cmd, "이어 읽기 비교") as session:
        first = session.read_frame()
        started = time.perf_counter()
        sequential = 0
        while len(session.read_frame()) == FRAME_BYTES:
            sequential += 1
        per_frame_ms = (time.perf_counter() - started) * 1000 / max(sequential, 1)
        if len(first) != FRAME_BYTES or sequential != COUNT - 1:
            raise AssertionError(session.failure(f"첫 장 {len(first)}바이트, 이어 읽은 {sequential}장 (기대 {COUNT - 1})"))
    print(f"SPIKE sequential_read_ms_per_frame: {per_frame_ms:.2f} (over {sequential} frames)")
