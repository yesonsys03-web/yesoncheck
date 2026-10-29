"""ProRes 파이프 스파이크: 클립 공장 자가 검증 + 가정 확정 (앱 코드 없이 ffmpeg subprocess 직접).

확정할 것 (계획서 Task 1 Step 7): ① ffmpeg 파이프(-fps_mode passthrough) 대 cv2 바이트 동일성, ② -ss 착지가 K=0에서도
정확한지(아니면 K=2), ③ 세션 재시작 시간. 수치는 print("SPIKE ...")로 남는다 (ASCII만 —
Windows 러너 콘솔 인코딩 대비) — 통과한 시험의 print는 pytest -s 또는 -rP 로 봄.
시간은 단언하지 않고(러너마다 다름) 디코드 결과의 정확성(프레임 번호·장수)만 단언한다.
"""

import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import time
from fractions import Fraction

import cv2
import numpy as np
import pytest

from tests.prores_clips import (
    HEIGHT, WIDTH, ffmpeg_exe, frame_number, make_audio_first, make_held, make_neg, make_numbered_clip, make_rot,
    make_truncated, make_vfr_h264, make_voff, read_all_frames,
)

FRAME_BYTES = WIDTH * HEIGHT * 3
COUNT = 120
SEED = 20261029


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 12비트 120장 24fps 번호 클립 (프레임 i = BGR (i, i, i))."""
    path = str(tmp_path_factory.mktemp("prores_clip") / "numbered_4444.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuv444p12le")
    return path


@pytest.fixture(scope="session")
def prores_422_clip(tmp_path_factory):
    """422 HQ 10비트 120장 23.976fps(24000/1001) 번호 클립."""
    path = str(tmp_path_factory.mktemp("prores_422") / "numbered_422.mov")
    make_numbered_clip(path, count=COUNT, fps="24000/1001", profile="3", pix_fmt="yuv422p10le")
    return path


@pytest.fixture(scope="session")
def prores_alpha_clip(tmp_path_factory):
    """알파 트랙이 있는 4444 12비트 120장 24fps 번호 클립."""
    path = str(tmp_path_factory.mktemp("prores_alpha") / "numbered_alpha.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuva444p12le")
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
    result = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, f"ffprobe 실패: {result.stderr.decode('utf-8', 'replace')}"
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
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, f"ffmpeg 실패: {result.stderr.decode('utf-8', 'replace')}"
    data = result.stdout
    assert len(data) % FRAME_BYTES == 0, f"파이프 출력 {len(data)}바이트는 프레임 크기 {FRAME_BYTES}의 배수가 아닙니다"
    return np.frombuffer(data, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)


def pipe_restart(path, n, k_back, fps, start_offset):
    """목표 n으로 세션 재시작: -ss (n-k)/fps (+영상 start 보정) 뒤 k+1장 읽음. (읽은 프레임 목록, 걸린 초) — 앱 설계와 같은 모양."""
    k = min(k_back, n)
    t = float((n - k) / fps) + start_offset
    cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", f"{t:.6f}", "-i", path, "-map", "0:V:0",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    started = time.perf_counter()
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    try:
        for _ in range(k + 1):
            buf = proc.stdout.read(FRAME_BYTES)
            if len(buf) < FRAME_BYTES:
                break
            frames.append(np.frombuffer(buf, np.uint8).reshape(HEIGHT, WIDTH, 3))
        elapsed = time.perf_counter() - started
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    return frames, elapsed


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
    """422 10비트와 알파 4444도 전 프레임 번호가 정확하고 이웃 프레임이 서로 다름 (자가 검증이 통과해야 클립이 만들어짐)."""
    info_422 = video_stream(ffprobe_json(prores_422_clip))
    info_alpha = video_stream(ffprobe_json(prores_alpha_clip))
    assert (info_422["profile"], info_422["pix_fmt"], info_422["r_frame_rate"]) == ("HQ", "yuv422p10le", "24000/1001")
    assert (info_alpha["profile"], info_alpha["pix_fmt"]) == ("4444", "yuva444p12le")
    for path in (prores_422_clip, prores_alpha_clip):
        frames = read_all_frames(path)
        assert [frame_number(f) for f in frames] == list(range(COUNT))
        assert all(frames[i].tobytes() != frames[i + 1].tobytes() for i in range(COUNT - 1))


def test_numbered_clip_rejects_too_many_frames(tmp_path):
    with pytest.raises(ValueError, match="count"):
        make_numbered_clip(str(tmp_path / "too_many.mov"), count=201)


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

def test_spike_byte_identity(prores_clip, prores_422_clip, prores_alpha_clip):
    """4444·422·알파: ffmpeg 파이프(-fps_mode passthrough) 전 프레임 == cv2 전 프레임 (바이트)."""
    ffmpeg_line = subprocess.run([ffmpeg_exe(), "-version"], stdout=subprocess.PIPE).stdout.decode().splitlines()[0]
    print(f"\nSPIKE env: {platform.system()} {platform.machine()} | cv2 {cv2.__version__} | {ffmpeg_line}")
    mismatches = []
    for name, path in (("4444", prores_clip), ("422", prores_422_clip), ("alpha", prores_alpha_clip)):
        cv2_frames = np.stack(read_all_frames(path))
        pipe_frames = pipe_all(path)
        assert pipe_frames.shape == cv2_frames.shape, f"{name}: 파이프 {pipe_frames.shape} cv2 {cv2_frames.shape}"
        same = [i for i in range(len(cv2_frames)) if np.array_equal(cv2_frames[i], pipe_frames[i])]
        diff = np.abs(cv2_frames.astype(int) - pipe_frames.astype(int))
        print(f"SPIKE byte_identity {name}: identical {len(same)}/{len(cv2_frames)} max_abs_diff {int(diff.max())}")
        if len(same) != len(cv2_frames):
            mismatches.append((name, [i for i in range(len(cv2_frames)) if i not in set(same)][:5]))
    assert not mismatches, f"cv2와 파이프 픽셀 불일치 (클립, 처음 어긋난 프레임): {mismatches}"


def test_spike_passthrough_frame_count(voff_clip, held_clip):
    """voff·held: passthrough가 있으면 cv2와 장수·바이트 일치, 없으면 복제 프레임으로 장수가 어긋남."""
    for name, path in (("voff", voff_clip), ("held", held_clip)):
        cv2_frames = np.stack(read_all_frames(path))
        with_pass = pipe_all(path, passthrough=True)
        without = pipe_all(path, passthrough=False)
        print(f"SPIKE passthrough_count {name}: cv2 {len(cv2_frames)} passthrough {len(with_pass)} default {len(without)}")
        assert len(cv2_frames) == COUNT
        assert len(with_pass) == len(cv2_frames), f"{name}: passthrough 파이프 {len(with_pass)}장 ≠ cv2 {len(cv2_frames)}장"
        assert np.array_equal(with_pass, cv2_frames), f"{name}: passthrough인데 cv2와 바이트가 다름"
        assert len(without) > len(cv2_frames), f"{name}: passthrough 없이도 장수가 같음 — 명령 차이 재확인 필요 ({len(without)}장)"


def test_spike_seek_landing(prores_clip, prores_422_clip, voff_clip):
    """무작위 40목표 × K∈{0,2}: -ss (n-K)/fps 뒤 K장 버림 → frame_number == n (voff는 영상 start 보정 포함).

    K=2는 전부 정확해야 통과. K=0은 측정만(print) — 전부 정확하면 SEEK_BACK_K = 0, 아니면 2 (Step 7 판정).
    """
    k2_failures = []
    for name, path in (("4444@24", prores_clip), ("422@23.976", prores_422_clip), ("voff@24+0.5s", voff_clip)):
        fps, start_offset = clip_timing(path)
        targets = seek_targets(COUNT, SEED)
        assert len(targets) == 40
        for k_back in (0, 2):
            wrong = []
            for n in targets:
                k = min(k_back, n)
                frames, _ = pipe_restart(path, n, k_back, fps, start_offset)
                landed = frame_number(frames[k]) if len(frames) == k + 1 else None
                if landed != n:
                    wrong.append((n, landed))
            print(f"SPIKE seek_landing {name} K={k_back}: exact {len(targets) - len(wrong)}/{len(targets)}"
                  + (f" wrong(target, landed) {wrong}" if wrong else ""))
            if k_back == 2 and wrong:
                k2_failures.append((name, wrong))
    assert not k2_failures, f"K=2 착지 어긋남 (클립, [(목표, 착지)]): {k2_failures}"


def test_spike_restart_timing(prores_clip):
    """세션 재시작 10회(K=2·K=0)의 시간은 print만 — 단언은 디코드 결과: K=2는 목표 번호 정확, 둘 다 k+1장 도착."""
    fps, start_offset = clip_timing(prores_clip)
    rng = random.Random(SEED)
    targets = rng.sample(range(2, COUNT), 10)
    medians = {}
    for k_back in (2, 0):
        times = []
        for n in targets:
            frames, elapsed = pipe_restart(prores_clip, n, k_back, fps, start_offset)
            k = min(k_back, n)
            assert len(frames) == k + 1, f"재시작 n={n} K={k_back}: {len(frames)}장만 도착 (기대 {k + 1})"
            if k_back == 2:
                assert frame_number(frames[k]) == n, f"재시작 n={n} K=2: 착지 {frame_number(frames[k])}"
            times.append(elapsed * 1000)
        medians[k_back] = statistics.median(times)
        print(f"SPIKE restart_ms K={k_back}: " + " ".join(f"{t:.0f}" for t in times)
              + f" | median {medians[k_back]:.0f} max {max(times):.0f}")
    # 비교용: 이미 돌아가는 세션에서 순차로 한 장 읽는 값 (같은 320x180 — 4K 수치는 이 Mac 실측 기록 참고)
    proc = subprocess.Popen([ffmpeg_exe(), "-nostdin", "-v", "error", "-i", prores_clip, "-map", "0:V:0", "-fps_mode",
                             "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        first = proc.stdout.read(FRAME_BYTES)
        started = time.perf_counter()
        sequential = 0
        while len(proc.stdout.read(FRAME_BYTES)) == FRAME_BYTES:
            sequential += 1
        per_frame_ms = (time.perf_counter() - started) * 1000 / max(sequential, 1)
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    assert len(first) == FRAME_BYTES and sequential == COUNT - 1
    print(f"SPIKE sequential_read_ms_per_frame: {per_frame_ms:.2f} (over {sequential} frames)")
