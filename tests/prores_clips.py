"""ProRes 시험 클립 공장 — numpy 프레임을 stdin 파이프로 prores_ks에 넣어 만든다 (drawtext 금지: 글꼴 의존).

번호 클립: 프레임 i는 단색이고, cv2로 읽으면 BGR (i, i, i). 유채색 클립: 시드 고정 무작위 블록 색 (chroma 경로 시험용).
경계 클립(voff·held·neg·rot·audio_first·truncated·vfr_h264)은 실제로 겪은 문제 파일의 재현 (설계 때 실측한 ffprobe
성질에 맞춤: 영상 start 오프셋·정지 프레임·편집 목록·회전 메타·트랙 순서·꼬리 잘림). 전부 320x180, 번호/경계 120장(5초).
ffmpeg는 PATH에서 찾는다 (tests/conftest.py가 저장소의 정적 빌드를 PATH 맨 앞에 둠).

인코더 입력은 prores_ks가 받는 pix_fmt(PRORES_PIX_FMTS)의 평면을 그대로 만들어 넣는다 — 다른 pix_fmt를 주면 ffmpeg가 경고만
내고 몰래 변환하므로 ValueError로 막는다. (ProRes 4444 디코더는 12비트(yuv444p12le)로 내보내지만 인코더 입력은 10비트다.)
모든 외부 프로세스에는 timeout이 있다 — 스톨이 CI 잡을 워크플로 한도까지 붙잡지 않게.
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
PRORES_PIX_FMTS = ("yuv422p10le", "yuv444p10le", "yuva444p10le")
TIMEOUT_ENCODE = 120  # 초 — 320x180 120장 인코드는 1초 안쪽, 넉넉히
TIMEOUT_PROBE = 30
TIMEOUT_PIPE = 60
# 번호 i의 밝기는 i + 오프셋 (8비트 눈금). 정수 i 그대로 넣으면 10비트 4:2:2 디코드(swscale)의 내림 때문에 이웃 번호가 같은
# 값으로 합쳐지고(1→0, 3→2, ...), 4:4:4는 반올림이라 반 칸 가까이 올리면 올림으로 넘어간다. 실측(cv2 4.6/FFmpeg 4.4, 인코더
# 입력은 네이티브 10비트)으로 0~199 전부 왕복 정확한 범위: 4:2:2 +0.15~+0.85, 4:4:4(HQ·4444·알파 동일) -0.35~+0.35.
# 각 범위 안에서 내림/반올림 어느 디코더에도 여유가 남는 자리: 4:2:2 0.4, 4:4:4 0.1. (4:2:0은 H.264용이라 번호 검증 안 함)
_LEVEL_OFFSETS = {"422": 0.4, "444": 0.1, "420": 0.25}
AUDIO_SECONDS = 6
_HELD_FPS = "24"
_PLANAR = re.compile(r"yuv(a?)(420|422|444)p(\d*)(?:le)?")


class ToolTimeout(RuntimeError):
    """외부 프로세스가 timeout 안에 끝나지 않아 죽였음."""


def ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError("ffmpeg를 PATH에서 찾지 못했습니다 (tests/conftest.py가 vendor/ffmpeg를 PATH에 올려야 함)")
    return found


def run_tool(cmd, purpose, timeout, stdin_bytes=None):
    """외부 프로그램 실행. 실패(exit != 0)나 timeout 초과는 용도·명령·stderr 전문을 담은 예외 (삼키지 않음)."""
    try:
        result = subprocess.run(cmd, input=stdin_bytes, stdin=None if stdin_bytes is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        raise ToolTimeout(f"{purpose}: {timeout}초 안에 끝나지 않아 중단했습니다. 명령 {cmd}\nstderr: {stderr}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"{purpose} 실패 (exit {result.returncode}). 명령 {cmd}\nstderr: "
                           f"{result.stderr.decode('utf-8', 'replace')}")
    return result


def run_ffmpeg(args, purpose, stdin_bytes=None, timeout=TIMEOUT_ENCODE):
    """ffmpeg 실행. 경고(-v warning)까지 stderr로 받아 두되, 성공했으면 경고만으로는 실패시키지 않는다."""
    return run_tool([ffmpeg_exe(), "-y", "-v", "warning", *args], purpose, timeout, stdin_bytes)


def frame_number(arr):
    """번호 클립 프레임의 번호: 중앙 영역 평균을 반올림."""
    h, w = arr.shape[:2]
    return int(round(float(arr[h // 4:h * 3 // 4, w // 4:w * 3 // 4].mean())))


def _layout(pix_fmt):
    """평면 YUV pix_fmt 해석 → (알파 여부, 서브샘플링, 비트 수, dtype, 색차 가로, 색차 세로)."""
    match = _PLANAR.fullmatch(pix_fmt)
    if not match:
        raise ValueError(f"평면 YUV pix_fmt만 지원합니다: {pix_fmt}")
    alpha, subsampling, depth = bool(match.group(1)), match.group(2), int(match.group(3) or 8)
    dtype = np.uint8 if depth == 8 else np.dtype("<u2")
    chroma_w = WIDTH if subsampling == "444" else WIDTH // 2
    chroma_h = HEIGHT // 2 if subsampling == "420" else HEIGHT
    return alpha, subsampling, depth, dtype, chroma_w, chroma_h


def _check_count(count):
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count는 1~{MAX_COUNT}: {count}")


def _numbered_raw(count, pix_fmt):
    """번호 count장의 원시 프레임 바이트, pix_fmt(평면 YUV) 그대로.

    인코더 앞에서 색 변환(swscale)을 거치면 변환 쪽 오차가 번호를 흔들어서, 목표 pix_fmt의 평면을 직접 만든다.
    밝기(Y)는 제한 범위, 색차는 중립 → 디코드하면 B=G=R=i. 알파(yuva)는 가로 그라데이션 — 알파가 비어 있지 않아야
    알파 트랙 시험이 됨.
    """
    _check_count(count)
    alpha, subsampling, depth, dtype, chroma_w, chroma_h = _layout(pix_fmt)
    neutral = 2 ** (depth - 1)
    chunks = []
    for i in range(count):
        luma = round((16 + 219 * (i + _LEVEL_OFFSETS[subsampling]) / 255) * 2 ** (depth - 8))
        planes = [np.full((HEIGHT, WIDTH), luma, dtype), np.full((chroma_h, chroma_w), neutral, dtype),
                  np.full((chroma_h, chroma_w), neutral, dtype)]
        if alpha:
            planes.append(np.tile(np.linspace(0, 2 ** depth - 1, WIDTH).astype(dtype), (HEIGHT, 1)))
        chunks.extend(plane.tobytes() for plane in planes)
    return b"".join(chunks)


def _chroma_raw(count, pix_fmt, seed):
    """시드 고정 무작위 블록(가로 5 x 세로 6 화소) 색 count장 — 밝기·색차(·알파) 평면 모두 블록마다 다른 합법 값.

    블록 가장자리에서 색차 서브샘플링·업샘플링 경로(swscale)가 실제로 일하게 하려는 것. 결정적(같은 시드면 같은 바이트).
    """
    _check_count(count)
    alpha, _, depth, dtype, chroma_w, chroma_h = _layout(pix_fmt)
    rng = np.random.default_rng(seed)
    scale = 2 ** (depth - 8)

    def blocks(height, width, low, high):
        grid = rng.integers(low, high + 1, size=(height // 6, width // 5))
        return np.repeat(np.repeat(grid, 6, axis=0), 5, axis=1).astype(dtype)

    chunks = []
    for _ in range(count):
        planes = [blocks(HEIGHT, WIDTH, 16 * scale, 235 * scale), blocks(chroma_h, chroma_w, 16 * scale, 240 * scale),
                  blocks(chroma_h, chroma_w, 16 * scale, 240 * scale)]
        if alpha:
            planes.append(blocks(HEIGHT, WIDTH, 0, 2 ** depth - 1))
        chunks.extend(plane.tobytes() for plane in planes)
    return b"".join(chunks)


def _encode(path, raw, *, fps="24", profile="3", pix_fmt="yuv422p10le", itsoffset=None, vf=None, fps_mode=None,
            audio=False, audio_first=False, purpose="ProRes 클립 인코드"):
    """원시 평면 프레임 raw(pix_fmt 그대로)를 ProRes로 인코드. 검증은 호출자 몫."""
    if pix_fmt not in PRORES_PIX_FMTS:
        raise ValueError(f"prores_ks가 그대로 받는 pix_fmt만 지원합니다 {PRORES_PIX_FMTS}: {pix_fmt} "
                         "(다른 값은 ffmpeg가 경고만 내고 몰래 변환함)")
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
    run_ffmpeg(args + [path], purpose, stdin_bytes=raw)


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


def _verify_chromatic(path, count):
    frames = read_all_frames(path)
    if len(frames) != count:
        raise ValueError(f"유채색 클립 장수 불일치 {path}: 읽은 장수 {len(frames)} (기대 {count})")
    for i, frame in enumerate(frames):
        spread = float(np.abs(frame[..., 0].astype(np.int16) - frame[..., 2].astype(np.int16)).mean())
        if spread < 10:
            raise ValueError(f"유채색 클립인데 {i}번 프레임이 거의 회색입니다 (|B-R| 평균 {spread:.1f}): {path}")
        if i and frame.tobytes() == frames[i - 1].tobytes():
            raise ValueError(f"유채색 클립의 {i - 1}·{i}번 프레임이 바이트까지 같습니다: {path}")


def make_numbered_clip(path, count=120, fps="24", profile="3", pix_fmt="yuv444p10le"):
    """프레임 i = BGR (i, i, i) 단색(count <= 200) 번호 클립. 만든 뒤 cv2로 전 프레임 왕복 검증 (실패하면 ValueError).

    profile은 prores_ks 번호(0 proxy, 1 lt, 2 standard, 3 hq, 4 4444, 5 4444xq). 진짜 4444는 profile="4"
    (profile="3"에 4:4:4 pix_fmt를 주면 HQ 표지의 4:4:4 10비트가 나옴). pix_fmt는 PRORES_PIX_FMTS 중 하나이고,
    yuva...면 알파 트랙이 있는 클립.
    """
    _encode(path, _numbered_raw(count, pix_fmt), fps=fps, profile=profile, pix_fmt=pix_fmt)
    _verify_numbered(path, count)


def make_chroma_clip(path, count=48, fps="24", profile="3", pix_fmt="yuv422p10le", seed=7):
    """시드 고정 무작위 블록 색 클립 (유채색) — 바이트 동일성 시험에서 색차 경로까지 보려는 것. 만든 뒤 cv2로 유채색·장수 검증."""
    _encode(path, _chroma_raw(count, pix_fmt, seed), fps=fps, profile=profile, pix_fmt=pix_fmt)
    _verify_chromatic(path, count)


def _encode_numbered(path, **kwargs):
    _encode(path, _numbered_raw(120, kwargs.get("pix_fmt", "yuv422p10le")), **kwargs)


def make_voff(path):
    """영상 트랙 start 0.5s (-itsoffset), 소리 트랙은 0부터 → 형식 start 0. 422 HQ 120장 24fps."""
    _encode_numbered(path, itsoffset=0.5, audio=True)


def make_held(path):
    """한 프레임(60번)이 2배 길이로 머무는 클립 (setpts) — nb_frames 120, avg_frame_rate가 r_frame_rate와 약간 다름."""
    _encode_numbered(path, fps=_HELD_FPS, vf="setpts=PTS+if(gt(N\\,60)\\,1/(24*TB)\\,0)", fps_mode="passthrough")


def _remux(src, path, *args, input_args=()):
    run_ffmpeg([*input_args, "-i", src, "-map", "0", "-c", "copy", *args, path], "ffmpeg 스트림 복사 재포장")


def _base_clip(path):
    """다른 경계 클립의 원본: 422 HQ 120장 번호 클립 (경로 옆 임시 파일, 쓰고 나면 지움)."""
    base = path + ".base.mov"
    _encode_numbered(base)
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
    _encode_numbered(path, audio=True, audio_first=True)


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
               "H.264 가변 프레임 레이트 클립 인코드", stdin_bytes=_numbered_raw(120, "yuv420p"))
