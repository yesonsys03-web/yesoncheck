"""ProRes 시험 클립 공장 — numpy 프레임을 stdin 파이프로 prores_ks에 넣어 만든다 (drawtext 금지: 글꼴 의존).

번호 클립: 프레임 i는 단색이고, cv2로 읽으면 BGR (i, i, i). 경계 클립(voff·held·neg·rot·audio_first·truncated·vfr_h264)은
실제로 겪은 문제 파일의 재현 (설계 때 실측한 ffprobe 성질에 맞춤: 영상 start 오프셋·정지 프레임·편집 목록·회전 메타·
트랙 순서·꼬리 잘림). 전부 320x180, 120장(5초). ffmpeg는 PATH에서 찾는다 (tests/conftest.py가 저장소의 정적 빌드를
PATH 맨 앞에 둠).
"""

import os
import re
import shutil
import subprocess

import cv2
import numpy as np

WIDTH = 320
HEIGHT = 180
MAX_COUNT = 200
# 번호 i의 밝기는 i + LEVEL_OFFSET (8비트 눈금). 정수 i 그대로 넣으면 10비트 4:2:2 디코드(swscale)의 내림 때문에 이웃 번호가
# 같은 값으로 합쳐지고(1→0, 3→2, ...), 반 칸 가까이 올리면 12비트 쪽이 올림으로 넘어간다. 실측(cv2 4.6/FFmpeg 4.4)으로
# 10비트는 +0.2~+0.8, 12비트는 -0.4~+0.4에서 0~199 전부 왕복 정확 — 둘 다 여유가 가장 큰 자리가 0.3.
LEVEL_OFFSET = 0.3
AUDIO_SECONDS = 6
_HELD_FPS = "24"
_PLANAR = re.compile(r"yuv(a?)(420|422|444)p(\d*)(?:le)?")


def ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError("ffmpeg를 PATH에서 찾지 못했습니다 (tests/conftest.py가 vendor/ffmpeg를 PATH에 올려야 함)")
    return found


def run_ffmpeg(args, stdin_bytes=None):
    """ffmpeg 실행. 실패하면 명령과 stderr 전문을 담아 RuntimeError (삼키지 않음)."""
    cmd = [ffmpeg_exe(), "-y", "-v", "error", *args]
    result = subprocess.run(cmd, input=stdin_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패 (exit {result.returncode}): {cmd}\n{result.stderr.decode('utf-8', 'replace')}")


def frame_number(arr):
    """번호 클립 프레임의 번호: 중앙 영역 평균을 반올림."""
    h, w = arr.shape[:2]
    return int(round(float(arr[h // 4:h * 3 // 4, w // 4:w * 3 // 4].mean())))


def _numbered_raw(count, pix_fmt):
    """번호 count장의 원시 프레임 바이트, pix_fmt(평면 YUV) 그대로.

    인코더 앞에서 색 변환(swscale)을 거치면 변환 쪽 오차가 번호를 흔들어서, 목표 pix_fmt의 평면을 직접 만든다.
    밝기(Y)는 제한 범위, 색차는 중립 → 디코드하면 B=G=R=i. 알파(yuva)는 가로 그라데이션 — 알파가 비어 있지 않아야
    알파 트랙 시험이 됨.
    """
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count는 1~{MAX_COUNT}: {count}")
    match = _PLANAR.fullmatch(pix_fmt)
    if not match:
        raise ValueError(f"평면 YUV pix_fmt만 지원합니다: {pix_fmt}")
    alpha, subsampling, depth = bool(match.group(1)), match.group(2), int(match.group(3) or 8)
    dtype = np.uint8 if depth == 8 else np.dtype("<u2")
    chroma_w = WIDTH if subsampling == "444" else WIDTH // 2
    chroma_h = HEIGHT // 2 if subsampling == "420" else HEIGHT
    neutral = 2 ** (depth - 1)
    chunks = []
    for i in range(count):
        luma = round((16 + 219 * (i + LEVEL_OFFSET) / 255) * 2 ** (depth - 8))
        planes = [np.full((HEIGHT, WIDTH), luma, dtype), np.full((chroma_h, chroma_w), neutral, dtype),
                  np.full((chroma_h, chroma_w), neutral, dtype)]
        if alpha:
            planes.append(np.tile(np.linspace(0, 2 ** depth - 1, WIDTH).astype(dtype), (HEIGHT, 1)))
        chunks.extend(plane.tobytes() for plane in planes)
    return b"".join(chunks)


def _encode(path, count, *, fps="24", profile="3", pix_fmt="yuv422p10le", itsoffset=None, vf=None, fps_mode=None,
            audio=False, audio_first=False):
    """번호 클립 인코드 (ProRes). 검증은 호출자 몫."""
    args = []
    if itsoffset is not None:
        args += ["-itsoffset", str(itsoffset)]
    args += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{WIDTH}x{HEIGHT}", "-framerate", fps, "-i", "pipe:0"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={AUDIO_SECONDS}"]
        args += ["-map", "1:a:0", "-map", "0:v:0"] if audio_first else ["-map", "0:v:0", "-map", "1:a:0"]
    if vf:
        args += ["-vf", vf]
    args += ["-c:v", "prores_ks", "-profile:v", profile, "-pix_fmt", pix_fmt]
    if fps_mode:
        args += ["-fps_mode", fps_mode]
    if audio:
        args += ["-c:a", "aac"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    run_ffmpeg(args + [path], stdin_bytes=_numbered_raw(count, pix_fmt))


def read_all_frames(path):
    """cv2로 끝까지 읽은 프레임 목록. 열지 못하면 ValueError."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"cv2가 클립을 열지 못했습니다: {path}")
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def _verify_numbered(path, count):
    frames = read_all_frames(path)
    numbers = [frame_number(f) for f in frames]
    if numbers != list(range(count)):
        bad = [(i, n) for i, n in enumerate(numbers) if i != n][:10]
        raise ValueError(f"번호 클립 왕복 불일치 {path}: 읽은 장수 {len(frames)} (기대 {count}), (위치, 읽은 번호) {bad}")


def make_numbered_clip(path, count=120, fps="24", profile="3", pix_fmt="yuv444p12le"):
    """프레임 i = BGR (i, i, i) 단색(count <= 200) 번호 클립. 만든 뒤 cv2로 전 프레임 왕복 검증 (실패하면 ValueError).

    profile은 prores_ks 번호(0 proxy, 1 lt, 2 standard, 3 hq, 4 4444, 5 4444xq). 진짜 4444는 profile="4"
    (profile="3"에 4:4:4 pix_fmt를 주면 HQ 표지의 4:4:4 10비트가 나옴). pix_fmt가 yuva...면 알파 트랙이 있는 클립.
    """
    _encode(path, count, fps=fps, profile=profile, pix_fmt=pix_fmt)
    _verify_numbered(path, count)


def make_voff(path):
    """영상 트랙 start 0.5s (-itsoffset), 소리 트랙은 0부터 → 형식 start 0. 422 HQ 120장 24fps."""
    _encode(path, 120, itsoffset=0.5, audio=True)


def make_held(path):
    """한 프레임(60번)이 2배 길이로 머무는 클립 (setpts) — nb_frames 120, avg_frame_rate가 r_frame_rate와 약간 다름."""
    _encode(path, 120, fps=_HELD_FPS, vf="setpts=PTS+if(gt(N\\,60)\\,1/(24*TB)\\,0)", fps_mode="passthrough")


def _remux(src, path, *args, input_args=()):
    run_ffmpeg([*input_args, "-i", src, "-map", "0", "-c", "copy", *args, path])


def _base_clip(path):
    """다른 경계 클립의 원본: 422 HQ 120장 번호 클립 (경로 옆 임시 파일, 쓰고 나면 지움)."""
    base = path + ".base.mov"
    _encode(base, 120)
    return base


def make_neg(path):
    """편집 목록으로 앞 2장이 잘린 클립 — nb_frames 120인데 실제 재생 장수는 118."""
    base = _base_clip(path)
    try:
        _remux(base, path, "-output_ts_offset", f"-{2 / 24:.6f}", "-avoid_negative_ts", "disabled")
    finally:
        os.remove(base)


def make_rot(path):
    """표시 회전 메타 90도 (display matrix) — ffprobe 320x180, cv2는 180x320."""
    base = _base_clip(path)
    try:
        _remux(base, path, input_args=["-display_rotation", "90"])
    finally:
        os.remove(base)


def make_audio_first(path):
    """소리 트랙이 index 0, 영상이 index 1."""
    _encode(path, 120, audio=True, audio_first=True)


def make_truncated(src, path, cut_ratio=0.7):
    """src를 faststart(moov 앞)로 다시 담은 뒤 파일 꼬리를 자름 — 헤더는 멀쩡하고 데이터가 중간에서 끊김."""
    whole = path + ".whole.mov"
    try:
        _remux(src, whole, "-movflags", "+faststart")
        with open(whole, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(whole):
            os.remove(whole)
    with open(path, "wb") as f:
        f.write(data[:int(len(data) * cut_ratio)])


def make_vfr_h264(path):
    """가변 프레임 레이트 H.264 (게이트 음성용) — 10장마다 한 프레임이 2배 길이로 머묾 (인코더 시간 단위가 1/24라 정수 프레임 간격)."""
    run_ffmpeg(["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{WIDTH}x{HEIGHT}", "-framerate", "24", "-i", "pipe:0",
                "-vf", "setpts=PTS+floor(N/10)/(24*TB)", "-fps_mode", "vfr", "-c:v", "libx264", path],
               stdin_bytes=_numbered_raw(120, "yuv420p"))
