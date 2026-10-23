"""이미지 시퀀스의 프레임 한 장을 BGR uint8 배열로 디코딩.

tga·png·jpg·jpeg·tif·tiff는 PIL로 읽는다: 번들된 cv2 4.6.0과 Qt는 RLE 압축 TGA를 못 읽는다.
exr은 자리만 잡아 둔 경로(OpenCV, 0~1 잘라내기만 하고 톤매핑은 하지 않음).
"""

import io
import os

# OpenCV는 이 값을 EXR을 처음 디코딩할 때 읽는다 (cv2를 먼저 불러왔어도 그 전에만 정해지면 된다)
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
from PIL import Image

PIL_EXTENSIONS = frozenset({"tga", "png", "jpg", "jpeg", "tif", "tiff"})


def decode_frame(data, ext):
    """프레임 파일 내용 `data`(bytes)를 (h, w, 3) BGR uint8 연속 배열로 디코딩.

    ext: 점 없는 소문자 확장자 ("tga"). 지원하지 않는 확장자나 깨진 데이터는 ValueError.
    """
    if ext in PIL_EXTENSIONS:
        return _decode_pil(data)
    if ext == "exr":
        return _decode_exr(data)
    raise ValueError(f"지원하지 않는 이미지 시퀀스 확장자: {ext!r}")


def _decode_pil(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = np.asarray(image.convert("RGB"))
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        # PIL의 깨진 파일 신호: 못 알아보는·잘린 파일 -> UnidentifiedImageError(OSError)·OSError,
        # 일부 헤더 오류 -> SyntaxError, 헤더가 터무니없는 크기를 주장 -> DecompressionBombError
        raise ValueError(f"이미지 프레임을 디코딩하지 못했습니다: {exc}") from exc
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _decode_exr(data):
    # IMREAD_COLOR는 쓰지 않는다: cv2 4.6.0은 단일 채널 EXR을 그것으로 읽으면 오류 없이 쓰레기 값을 준다
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
    if frame is None:
        raise ValueError("EXR 프레임을 디코딩하지 못했습니다")
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.shape[2] == 4:
        frame = frame[:, :, :3]  # BGRA의 알파는 버린다
    elif frame.shape[2] != 3:
        raise ValueError(f"지원하지 않는 EXR 채널 수: {frame.shape[2]}")
    return np.ascontiguousarray((np.clip(frame, 0.0, 1.0) * 255).astype(np.uint8))
