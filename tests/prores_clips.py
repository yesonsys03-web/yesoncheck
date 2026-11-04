"""ProRes 시험 클립 공장 — numpy 프레임을 stdin 파이프로 prores_ks에 넣어 만든다 (drawtext 금지: 글꼴 의존).

번호 클립: 프레임 i를 회색 블록 두 개의 밝기로 인코딩 (아래 frame_number 참고) — 디코더마다 밝기가 몇 레벨 어긋나도 번호는
정확히 복호된다. 유채색 클립: 시드 고정 무작위 블록 색 (chroma 경로 시험용).
경계 클립(voff·held·neg·rot·audio_first·truncated·vfr_h264)은 실제로 겪은 문제 파일의 재현 (설계 때 실측한 ffprobe
성질에 맞춤: 영상 start 오프셋·정지 프레임·편집 목록·회전 메타·트랙 순서·꼬리 잘림). 전부 320x180, 번호/경계 120장(5초).
번호·유채색 클립은 width·height(기본 320x180)와 color 태그(기본 없음, "bt709"), 유채색 클립은 알파(alpha=True)도 고를 수 있다.
번호 그림의 블록 자리는 크기에 비례(frame_number가 비율로 읽음) — 4K 클립도 같은 번호로 복호된다.
ffmpeg는 PATH에서 찾는다 (tests/conftest.py가 저장소의 정적 빌드를 PATH 맨 앞에 둠).
색 기준은 pipe_frames(앱의 ffmpeg 파이프와 같은 명령의 bgr24) — read_all_frames(cv2)는 색 태그를 무시해(709 클립도 601로 읽음)
번호·장수 기준일 뿐 색 기준이 아니다.

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
# 파이프 대 cv2 허용 오차 (최대 |차이|, 8비트 값). 4:4:4 계열(4444·알파·HQ 4:4:4)은 바이트 완전 동일, 4:2:2는 5까지.
# 422 허용 오차는 사용자 결정(2026-10-29) — 스펙 §5.4. 근거: CI 실측 — Apple Silicon에서 422 단색 +1~+2, 유채색 -3~+4
# (swscale SIMD 경로 차이), 4:4:4와 Windows는 전부 동일. 프레임 정렬은 허용 오차와 무관하게 늘 완벽해야 한다.
BYTE_EXACT = 0
TOLERANCE_422 = 5
# 번호 인코딩: i = hi * RADIX + lo. 회색 두 블록의 밝기(8비트 눈금)가 hi * STEP, lo * STEP — 바깥(전체 바탕) 블록이 hi,
# 가운데 직사각형(프레임의 가운데 절반)이 lo. 한 값에 번호를 그대로 싣던 처음 방식은 CI Mac의 cv2 디코드가 밝기를 1~2 레벨
# 틀어 버려(위치 1~10 → 0,1,2,2,3,4,5,6,8,9) 자가 검증이 깨졌다. 레벨 간격 STEP이면 복호가 +-(STEP/2 - 0.5) 레벨 드리프트까지
# 정확하다 (STEP 18 -> +-8). MAX_COUNT 200까지: hi 최대 14*18 = 252, lo 최대 13*18 = 234가 255 안에 든다.
RADIX = 14
STEP = 18
assert (MAX_COUNT - 1) // RADIX * STEP <= 255 and (RADIX - 1) * STEP <= 255
AUDIO_SECONDS = 6
# color= 인자별 ffmpeg 출력 옵션(COLOR_TAG_ARGS)과 유채색 클립의 YCbCr 행렬 계수 (Kr, Kb)(YCBCR_MATRIX). 태그가 없으면(None)
# 디코더(ffmpeg swscale·cv2)가 601로 읽으므로 601 행렬로 만든다.
COLOR_TAG_ARGS = {"bt709": ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]}
YCBCR_MATRIX = {None: (0.299, 0.114), "bt709": (0.2126, 0.0722)}
# 유채색 블록: 색차 평면 기준 가로 5 x 세로 6 칸. RGB 채널은 이 여백 안(24~231)에서 뽑는다 — 0·255에 가까우면 블록 가장자리의
# 손실 인코드 링잉(실측 최대 ~20 레벨, HQ 4:4:4)으로 영역 밖에 나가 디코더마다 잘라 내는 방식이 갈린다 (여백 8은 0.17% 화소가 잘림).
CHROMA_BLOCK_W = 5
CHROMA_BLOCK_H = 6
RGB_MARGIN = 24
_HELD_FPS = "24"
_PLANAR = re.compile(r"yuv(a?)(420|422|444)p(\d*)(?:le)?")


class ToolTimeout(RuntimeError):
    """외부 프로세스가 timeout 안에 끝나지 않아 죽였음."""


def ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError("ffmpeg를 PATH에서 찾지 못했습니다 (tests/conftest.py가 vendor/ffmpeg를 PATH에 올려야 함)")
    return found


def ffprobe_exe():
    found = shutil.which("ffprobe")
    if not found:
        raise FileNotFoundError("ffprobe를 PATH에서 찾지 못했습니다 (tests/conftest.py가 vendor/ffmpeg를 PATH에 올려야 함)")
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


def _digit(level_mean):
    return int(round(float(level_mean) / STEP))


def frame_number(arr):
    """번호 클립 프레임의 번호 = hi * RADIX + lo.

    lo: 가운데 상자의 안쪽(프레임의 3/8~5/8) 평균 / STEP 반올림, hi: 네 모서리 조각(가로·세로 1/8) 평균 / STEP 반올림.
    위치가 모두 90도 회전에 대해 닫혀 있어서 회전 메타 클립(cv2가 180x320으로 돌려 줌)도 같은 번호로 복호된다.
    번호 클립이 아닌 프레임(유채색 클립 등)에는 뜻이 없다.
    """
    h, w = arr.shape[:2]
    lo = arr[3 * h // 8:5 * h // 8, 3 * w // 8:5 * w // 8].mean()
    hi = np.mean([arr[:h // 8, :w // 8].mean(), arr[:h // 8, w - w // 8:].mean(),
                  arr[h - h // 8:, :w // 8].mean(), arr[h - h // 8:, w - w // 8:].mean()])
    return _digit(hi) * RADIX + _digit(lo)


def _layout(pix_fmt, width=WIDTH, height=HEIGHT):
    """평면 YUV pix_fmt 해석 → (알파 여부, 서브샘플링, 비트 수, dtype, 색차 가로, 색차 세로)."""
    match = _PLANAR.fullmatch(pix_fmt)
    if not match:
        raise ValueError(f"평면 YUV pix_fmt만 지원합니다: {pix_fmt}")
    alpha, subsampling, depth = bool(match.group(1)), match.group(2), int(match.group(3) or 8)
    dtype = np.uint8 if depth == 8 else np.dtype("<u2")
    chroma_w = width if subsampling == "444" else width // 2
    chroma_h = height // 2 if subsampling == "420" else height
    return alpha, subsampling, depth, dtype, chroma_w, chroma_h


def _check_count(count):
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count는 1~{MAX_COUNT}: {count}")


def _check_color(color):
    if color not in YCBCR_MATRIX:
        raise ValueError(f"color는 None 또는 {tuple(COLOR_TAG_ARGS)} 중 하나: {color!r}")


def number_levels(i):
    """번호 i의 두 블록 밝기(8비트 눈금): (바탕 hi * STEP, 가운데 상자 lo * STEP)."""
    if not 0 <= i < MAX_COUNT:
        raise ValueError(f"번호는 0~{MAX_COUNT - 1}: {i}")
    hi, lo = divmod(i, RADIX)
    return hi * STEP, lo * STEP


def ideal_frame(i):
    """번호 i를 레벨 오차 0으로 디코드했을 때의 BGR 프레임 — 복호 견고성 시험이 여기에 교란(이동·이득)을 얹는다."""
    background, center = number_levels(i)
    frame = np.full((HEIGHT, WIDTH, 3), background, np.uint8)
    frame[HEIGHT // 4:HEIGHT * 3 // 4, WIDTH // 4:WIDTH * 3 // 4] = center
    return frame


def _luma_code(level, depth):
    """8비트 눈금 밝기 level(0~255) -> depth비트 제한 범위 Y 코드."""
    return round((16 + 219 * level / 255) * 2 ** (depth - 8))


def _numbered_raw(count, pix_fmt, width=WIDTH, height=HEIGHT):
    """번호 count장의 원시 프레임 바이트, pix_fmt(평면 YUV) 그대로. 번호 인코딩은 위 RADIX·STEP 설명.
    가운데 상자는 프레임의 가운데 절반(크기에 비례) — frame_number가 비율로 읽으므로 크기가 달라도 같은 번호로 복호된다.

    인코더 앞에서 색 변환(swscale)을 거치면 변환 쪽 오차가 밝기를 흔들어서, 목표 pix_fmt의 평면을 직접 만든다.
    색차는 중립 → 디코드하면 B=G=R. 알파(yuva)는 가로 그라데이션 — 알파가 비어 있지 않아야 알파 트랙 시험이 됨.
    """
    _check_count(count)
    alpha, _, depth, dtype, chroma_w, chroma_h = _layout(pix_fmt, width, height)
    neutral = 2 ** (depth - 1)
    chunks = []
    for i in range(count):
        background, center = number_levels(i)
        luma = np.full((height, width), _luma_code(background, depth), dtype)
        luma[height // 4:height * 3 // 4, width // 4:width * 3 // 4] = _luma_code(center, depth)
        planes = [luma, np.full((chroma_h, chroma_w), neutral, dtype), np.full((chroma_h, chroma_w), neutral, dtype)]
        if alpha:
            planes.append(np.tile(np.linspace(0, 2 ** depth - 1, width).astype(dtype), (height, 1)))
        chunks.extend(plane.tobytes() for plane in planes)
    return b"".join(chunks)


def _rgb_to_ycbcr_codes(rgb, kr, kb):
    """8비트 RGB (..., 3) -> 제한 범위 8비트 (Y, Cb, Cr) 코드 (행렬 계수 Kr·Kb: 601 / 709). 반올림은 8비트 눈금에서."""
    red, green, blue = (rgb[..., i] / 255 for i in range(3))
    luma = kr * red + (1 - kr - kb) * green + kb * blue
    cb, cr = (blue - luma) / (2 * (1 - kb)), (red - luma) / (2 * (1 - kr))
    return np.rint(16 + 219 * luma), np.rint(128 + 224 * cb), np.rint(128 + 224 * cr)


def _chroma_raw(count, pix_fmt, seed, width=WIDTH, height=HEIGHT, color=None, half_transparent=False):
    """시드 고정 무작위 블록 색 count장 — 색은 RGB 영역 안에서 뽑아 제한 범위 YCbCr로 바꾼 값 (color: None=601, "bt709"=709).

    블록은 색차 평면 기준 가로 5 x 세로 6 칸 (4:4:4는 화소 5x6, 4:2:2는 화소 10x6, 4:2:0은 10x12) — 색차 한 칸을 같이 쓰는
    화소들이 같은 RGB 색에서 나와야 (Y, Cb, Cr) 모두가 영역 안이기 때문. YCbCr 코드값을 따로 무작위로 뽑으면 RGB 영역 밖 색이
    대부분이라 디코더마다 잘라 내는 방식(ffmpeg 대 Apple)이 달라 비교가 최대 255까지 어긋난다.
    블록 가장자리에서 색차 서브샘플링·업샘플링 경로(swscale)가 실제로 일하게 하려는 것. 결정적(같은 시드면 같은 바이트).
    알파 pix_fmt는 half_transparent면 왼쪽 절반 알파 0·오른쪽 절반 최대(색은 그대로 둠), 아니면 알파도 블록마다 무작위.
    """
    _check_count(count)
    _check_color(color)
    alpha, subsampling, depth, dtype, chroma_w, chroma_h = _layout(pix_fmt, width, height)
    if half_transparent and not alpha:
        raise ValueError(f"half_transparent는 알파 pix_fmt(yuva...)에서만: {pix_fmt}")
    sub_x, sub_y = (1 if subsampling == "444" else 2), (2 if subsampling == "420" else 1)
    block_w, block_h = CHROMA_BLOCK_W * sub_x, CHROMA_BLOCK_H * sub_y  # 화소 단위
    if width % block_w or height % block_h:
        raise ValueError(f"{width}x{height} {pix_fmt}는 색 블록({block_w}x{block_h} 화소)으로 나눠떨어지지 않습니다")
    kr, kb = YCBCR_MATRIX[color]
    rng = np.random.default_rng(seed)
    scale = 2 ** (depth - 8)

    def paint(grid, block_h, block_w):
        return np.repeat(np.repeat(grid, block_h, axis=0), block_w, axis=1)

    chunks = []
    for _ in range(count):
        rgb = rng.integers(RGB_MARGIN, 255 - RGB_MARGIN + 1, size=(chroma_h // CHROMA_BLOCK_H, chroma_w // CHROMA_BLOCK_W, 3))
        luma, cb, cr = (code * scale for code in _rgb_to_ycbcr_codes(rgb, kr, kb))
        planes = [paint(luma, block_h, block_w), paint(cb, CHROMA_BLOCK_H, CHROMA_BLOCK_W),
                  paint(cr, CHROMA_BLOCK_H, CHROMA_BLOCK_W)]
        if alpha and half_transparent:
            planes.append(np.where(np.arange(width) < width // 2, 0, 2 ** depth - 1)[None, :].repeat(height, axis=0))
        elif alpha:
            planes.append(paint(rng.integers(0, 2 ** depth, size=(height // CHROMA_BLOCK_H, width // CHROMA_BLOCK_W)),
                                CHROMA_BLOCK_H, CHROMA_BLOCK_W))
        chunks.extend(plane.astype(dtype).tobytes() for plane in planes)
    return b"".join(chunks)


def _encode(path, raw, *, fps="24", profile="3", pix_fmt="yuv422p10le", width=WIDTH, height=HEIGHT, color=None,
            itsoffset=None, vf=None, fps_mode=None, audio=False, audio_first=False, purpose="ProRes 클립 인코드"):
    """원시 평면 프레임 raw(pix_fmt·width x height 그대로)를 ProRes로 인코드. color="bt709"면 색 태그를 붙임. 검증은 호출자 몫."""
    _check_color(color)
    if pix_fmt not in PRORES_PIX_FMTS:
        raise ValueError(f"prores_ks가 그대로 받는 pix_fmt만 지원합니다 {PRORES_PIX_FMTS}: {pix_fmt} "
                         "(다른 값은 ffmpeg가 경고만 내고 몰래 변환함)")
    args = []
    if itsoffset is not None:
        args += ["-itsoffset", str(itsoffset)]
    args += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{width}x{height}", "-framerate", fps, "-i", "pipe:0"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={AUDIO_SECONDS}"]
        args += ["-map", "1:a:0", "-map", "0:v:0"] if audio_first else ["-map", "0:v:0", "-map", "1:a:0"]
    if vf:
        args += ["-vf", vf]
    args += ["-c:v", "prores_ks", "-profile:v", profile, "-pix_fmt", pix_fmt]
    if color:
        args += COLOR_TAG_ARGS[color]
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


def pipe_frames(path):
    """앱의 ffmpeg 파이프(movie_pipe_source._pipe_command)와 같은 명령 — -map 0:V:0 -fps_mode passthrough, bgr24 — 으로 끝까지
    디코드한 BGR 프레임 목록 ((높이, 너비, 3) uint8, 읽기 전용). 크기는 ffprobe로(같은 트랙 V:0). 색 기준으로 쓴다 — ffmpeg는 색 태그를
    따르고(709 클립은 709 행렬) cv2는 따르지 않는다. 바이트 수가 한 장 크기로 나눠떨어지지 않으면 ValueError (조용히 자르지 않음)."""
    size = run_tool([ffprobe_exe(), "-v", "error", "-select_streams", "V:0", "-show_entries", "stream=width,height",
                     "-of", "csv=p=0", path], "ffprobe 크기 읽기", TIMEOUT_PROBE)
    width, height = (int(v) for v in size.stdout.decode("ascii").strip().split(","))
    result = run_tool([ffmpeg_exe(), "-nostdin", "-v", "error", "-i", path, "-map", "0:V:0", "-fps_mode", "passthrough",
                       "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], "ffmpeg 파이프 명령으로 bgr24 디코드", TIMEOUT_PIPE)
    frame_bytes = width * height * 3
    if not result.stdout or len(result.stdout) % frame_bytes:
        raise ValueError(f"bgr24 출력 {len(result.stdout)}바이트가 {width}x{height} 한 장({frame_bytes}바이트)으로 나눠떨어지지 "
                         f"않습니다: {path}")
    return list(np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 3))


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


def stats_summary(stats):
    return (f"differing frames {len(stats['differing'])}/{stats['frames']}, max |diff| {stats['max_abs']}, "
            f"differing pixels {stats['pixel_pct']:.4f}%, diff histogram (pipe-cv2) {stats['histogram']}")


def make_numbered_clip(path, count=120, fps="24", profile="3", pix_fmt="yuv444p10le", width=WIDTH, height=HEIGHT, color=None):
    """프레임 i를 회색 블록 두 개로 인코딩한 번호 클립(count <= 200, frame_number로 복호). 만든 뒤 cv2로 읽어 복호한 번호열이
    range(count)인지 검증 (실패하면 ValueError) — 밝기 레벨 정확도는 요구하지 않음.

    profile은 prores_ks 번호(0 proxy, 1 lt, 2 standard, 3 hq, 4 4444, 5 4444xq). 진짜 4444는 profile="4"
    (profile="3"에 4:4:4 pix_fmt를 주면 HQ 표지의 4:4:4 10비트가 나옴). pix_fmt는 PRORES_PIX_FMTS 중 하나이고,
    yuva...면 알파 트랙이 있는 클립. width x height는 기본 320x180 (4K는 3840x2160), color="bt709"면 색 태그를 붙임 (기본 없음).
    """
    _encode(path, _numbered_raw(count, pix_fmt, width, height), fps=fps, profile=profile, pix_fmt=pix_fmt, width=width,
            height=height, color=color)
    _verify_numbered(path, count)


def make_chroma_clip(path, count=48, fps="24", profile=None, pix_fmt=None, seed=7, width=WIDTH, height=HEIGHT, color=None,
                     alpha=False):
    """시드 고정 무작위 블록 색 클립 (유채색, 색은 RGB 영역 안 — _chroma_raw) — 바이트 동일성 시험에서 색차 경로까지 보려는 것.
    만든 뒤 cv2로 유채색·장수 검증.

    profile·pix_fmt 기본값은 "3"·"yuv422p10le"(HQ 4:2:2), alpha=True면 "4"·"yuva444p10le" (알파는 4444 프로파일만 실음 —
    알파 없는 pix_fmt나 4444가 아닌 프로파일을 같이 주면 ffmpeg가 알파를 몰래 버리므로 ValueError). alpha=True는 왼쪽 절반 알파 0·
    오른쪽 절반 알파 최대 (투명한 쪽의 색도 그대로 살아 있음). color="bt709"면 709 행렬로 만들고 색 태그를 붙임 (기본 601·태그 없음).
    """
    profile = profile or ("4" if alpha else "3")
    pix_fmt = pix_fmt or ("yuva444p10le" if alpha else "yuv422p10le")
    if alpha and not (_layout(pix_fmt)[0] and profile in ("4", "5")):
        raise ValueError(f"alpha=True는 알파 pix_fmt(yuva...)와 4444 프로파일(4·5)이 필요합니다: {pix_fmt}, profile {profile}")
    raw = _chroma_raw(count, pix_fmt, seed, width, height, color, half_transparent=alpha)
    _encode(path, raw, fps=fps, profile=profile, pix_fmt=pix_fmt, width=width, height=height, color=color)
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
