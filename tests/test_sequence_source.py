"""이미지 시퀀스 프레임 디코더(sequence_source.decode_frame): 확장자별 디코딩, BGR uint8 연속 배열, 오류는 ValueError."""

import io
import struct
import zlib

import cv2
import numpy as np
import pytest
from PIL import Image

from yesoncheck.sequence_source import decode_frame


def _encode(fmt, w=8, h=4, color=(10, 200, 30), mode="RGB", **save_args):
    img = Image.new(mode, (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_args)
    return buf.getvalue()


def _tga_bytes(w=8, h=4, color=(10, 200, 30)):
    """PIL로 RLE TGA 생성 (cv2·Qt는 RLE TGA를 못 읽는다)."""
    return _encode("TGA", w, h, color, compression="tga_rle")


def test_decode_tga_rle_bgr_contiguous():
    arr = decode_frame(_tga_bytes(), "tga")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (30, 200, 10)  # BGR


def test_decode_png():
    arr = decode_frame(_encode("PNG"), "png")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (30, 200, 10)


@pytest.mark.parametrize("fmt, ext", [("JPEG", "jpg"), ("JPEG", "jpeg"), ("TIFF", "tif"), ("TIFF", "tiff")])
def test_decode_other_pil_extensions(fmt, ext):
    arr = decode_frame(_encode(fmt, w=16, h=16), ext)
    assert arr.shape == (16, 16, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    b, g, r = (int(v) for v in arr[8, 8])  # JPEG는 손실 압축이라 근사값으로 비교
    assert abs(b - 30) <= 3 and abs(g - 200) <= 3 and abs(r - 10) <= 3


def test_decode_rgba_drops_alpha():
    arr = decode_frame(_encode("PNG", color=(10, 200, 30, 128), mode="RGBA"), "png")
    assert arr.shape == (4, 8, 3)
    assert tuple(arr[0, 0]) == (30, 200, 10)


def test_decode_grayscale_expands_to_three_channels():
    arr = decode_frame(_encode("PNG", color=77, mode="L"), "png")
    assert arr.shape == (4, 8, 3)
    assert tuple(arr[0, 0]) == (77, 77, 77)


def test_decode_exr_clips_to_uint8_without_tonemapping():
    # 0~1 밖의 값은 잘라내기만 한다 (톤매핑 없음): BGR = (0.0, 1.0, 2.0) -> (0, 255, 255)
    src = np.empty((4, 8, 3), np.float32)
    src[:, :] = (0.0, 1.0, 2.0)
    ok, buf = cv2.imencode(".exr", src)
    assert ok
    arr = decode_frame(buf.tobytes(), "exr")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (0, 255, 255)


def test_decode_exr_grayscale_expands_to_bgr():
    # 단일 채널 EXR을 IMREAD_COLOR로 읽으면 cv2 4.6.0은 오류 없이 쓰레기 값(검정)을 준다
    ok, buf = cv2.imencode(".exr", np.full((4, 8), 0.5, np.float32))
    assert ok
    arr = decode_frame(buf.tobytes(), "exr")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (127, 127, 127)


def test_decode_exr_alpha_dropped():
    src = np.empty((4, 8, 4), np.float32)
    src[:, :] = (0.25, 0.5, 0.75, 1.0)  # BGRA
    ok, buf = cv2.imencode(".exr", src)
    assert ok
    arr = decode_frame(buf.tobytes(), "exr")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (63, 127, 191)


def test_decode_unsupported_ext_raises():
    with pytest.raises(ValueError):
        decode_frame(_encode("PNG"), "dpx")


def test_decode_corrupt_raises():
    with pytest.raises(ValueError):
        decode_frame(b"junk", "tga")


def test_decode_truncated_raises():
    data = _encode("PNG", w=64, h=64)
    with pytest.raises(ValueError):
        decode_frame(data[: len(data) // 2], "png")


def test_decode_absurd_dimensions_raises():
    """깨진 헤더가 터무니없는 크기를 주장하면 PIL은 DecompressionBombError를 낸다 -> 역시 ValueError."""
    data = bytearray(_encode("PNG"))
    ihdr = struct.pack(">II", 1 << 16, 1 << 16) + bytes(data[24:29])  # 너비·높이 + 나머지 IHDR 필드
    data[16:29] = ihdr
    data[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    with pytest.raises(ValueError):
        decode_frame(bytes(data), "png")


def test_decode_corrupt_exr_raises():
    with pytest.raises(ValueError):
        decode_frame(b"junk", "exr")
