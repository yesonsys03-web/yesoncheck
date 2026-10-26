"""이미지 시퀀스 프레임 디코더(sequence_source.decode_frame): 확장자별 디코딩, BGR uint8 연속 배열, 오류는 ValueError."""

import io
import struct
import sys
import zlib

import cv2
import numpy as np
import pytest
from PIL import Image

from yesoncheck import sequence_source
from yesoncheck.sequence_source import decode_frame, exr_supported

# 이 플랫폼의 cv2 휠에 OpenEXR 코덱이 꺼져 있으면(Windows 휠의 기본, 환경 변수로 켜지지 않는 경우) 실제 EXR 시험은 건너뜀.
# Mac처럼 켜지는 곳에서는 그대로 돎 (아래 '꺼진 코덱' 시험들은 어디서나 돎)
needs_exr = pytest.mark.skipif(not exr_supported(), reason="cv2 OpenEXR 비활성(이 플랫폼 휠)")

# OpenEXR이 꺼진 cv2가 EXR을 인코딩할 때 내는 오류의 글 (Windows CI의 오류에서 줄인 것)
EXR_DISABLED_MESSAGE = (
    "grfmt_exr.cpp:103: error: (-213:The function/feature is not implemented) imgcodecs: OpenEXR codec is disabled. "
    "You can enable it via 'OPENCV_IO_ENABLE_OPENEXR' option. in function 'cv::initOpenEXR'")


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


@needs_exr
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


@needs_exr
def test_decode_exr_grayscale_expands_to_bgr():
    # 단일 채널 EXR을 IMREAD_COLOR로 읽으면 cv2 4.6.0은 오류 없이 쓰레기 값(검정)을 준다
    ok, buf = cv2.imencode(".exr", np.full((4, 8), 0.5, np.float32))
    assert ok
    arr = decode_frame(buf.tobytes(), "exr")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (127, 127, 127)


@needs_exr
def test_decode_exr_alpha_dropped():
    src = np.empty((4, 8, 4), np.float32)
    src[:, :] = (0.25, 0.5, 0.75, 1.0)  # BGRA
    ok, buf = cv2.imencode(".exr", src)
    assert ok
    arr = decode_frame(buf.tobytes(), "exr")
    assert arr.shape == (4, 8, 3) and arr.dtype == np.uint8
    assert arr.flags["C_CONTIGUOUS"]
    assert tuple(arr[0, 0]) == (63, 127, 191)


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac의 cv2 휠은 환경 변수만으로 EXR이 켜짐")
def test_exr_is_supported_on_mac():
    """Mac에서는 EXR 시험이 조용히 건너뛰어지지 않게: 코덱이 꺼져 있으면 (환경 변수를 정하는 자리가 틀어진 것) 여기서 실패."""
    assert exr_supported()


@pytest.fixture
def fresh_exr_probe():
    """EXR 가능 여부는 한 번 시험해 기억함: 이 시험의 흉내 cv2가 다른 시험에 남거나 남의 결과를 쓰지 않게 앞뒤로 비움."""
    sequence_source._exr_probe_error.cache_clear()
    yield
    sequence_source._exr_probe_error.cache_clear()


def raise_exr_disabled(*args, **kwargs):
    raise cv2.error(EXR_DISABLED_MESSAGE)


def test_exr_decode_with_a_disabled_codec_raises_a_clear_chained_error(monkeypatch, fresh_exr_probe):
    """OpenEXR 코덱이 꺼진 cv2는 cv2.error를 그대로 새게 하지 않고, 이유가 보이는 ValueError(원인은 이어서)로 크게 실패함."""
    monkeypatch.setattr(sequence_source.cv2, "imencode", raise_exr_disabled)
    assert exr_supported() is False
    with pytest.raises(ValueError, match="OpenEXR 코덱이 비활성") as caught:
        decode_frame(b"not even looked at", "exr")
    assert isinstance(caught.value.__cause__, cv2.error)
    assert "OPENCV_IO_ENABLE_OPENEXR" in str(caught.value) and "initOpenEXR" in str(caught.value)


def test_a_disabled_exr_codec_leaves_the_pil_formats_alone(monkeypatch, fresh_exr_probe):
    monkeypatch.setattr(sequence_source.cv2, "imencode", raise_exr_disabled)
    assert tuple(decode_frame(_tga_bytes(), "tga")[0, 0]) == (30, 200, 10)
    assert tuple(decode_frame(_encode("PNG"), "png")[0, 0]) == (30, 200, 10)


def test_exr_probe_does_not_swallow_other_cv2_errors(monkeypatch, fresh_exr_probe):
    """코덱이 꺼졌다는 오류만 '지원 안 함'으로 받음: 다른 cv2.error는 그대로 올라오고 기억되지도 않음."""
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        raise cv2.error("some other imgcodecs failure")

    monkeypatch.setattr(sequence_source.cv2, "imencode", broken)
    for _ in range(2):
        with pytest.raises(cv2.error, match="some other imgcodecs failure"):
            exr_supported()
    assert len(calls) == 2


def test_exr_probe_treats_a_failed_encode_as_unsupported(monkeypatch, fresh_exr_probe):
    monkeypatch.setattr(sequence_source.cv2, "imencode", lambda *a, **k: (False, None))
    assert exr_supported() is False
    with pytest.raises(ValueError, match="OpenEXR 코덱이 비활성"):
        decode_frame(b"x", "exr")


def test_exr_probe_runs_once(monkeypatch, fresh_exr_probe):
    real, calls = cv2.imencode, []
    monkeypatch.setattr(sequence_source.cv2, "imencode", lambda *a, **k: calls.append(1) or real(*a, **k))
    first = exr_supported()
    assert [exr_supported() for _ in range(5)] == [first] * 5
    assert len(calls) == 1


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
