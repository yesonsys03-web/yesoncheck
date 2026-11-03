"""시험 클립 공장(tests/prores_clips.py)의 크기·색 태그·알파·색 영역 인자: 만든 클립을 실제 ffprobe·cv2·ffmpeg로 다시 읽어 확인한다.

기본 인자(320x180, 태그 없음, 알파 없음)의 클립이 예전과 같다는 것은 이 파일이 아니라 그 클립을 쓰는 기존 시험들이 지킨다.
"""

import numpy as np
import pytest

from tests import prores_clips
from tests.prores_clips import run_ffmpeg
from yesoncheck.movie_pipe_source import probe_movie

# in-gamut 시험: 모서리(0·255)에 닿는 화소 비율 상한 — 색을 gamut 안에서 뽑으면 사실상 0, 무작위 YCbCr 코드를 그대로 쓰면 수십 %
CLAMPED_FRACTION_LIMIT = 0.001
# 8비트 YCbCr 코드 반올림(각 +-0.5)이 RGB에서 만드는 오차의 상한 (실측 1.4 안쪽)
RGB_ROUNDING_SLACK = 2


def test_factory_size_and_color_tag(tmp_path):
    clip = str(tmp_path / "k.mov")
    prores_clips.make_numbered_clip(clip, count=3, width=3840, height=2160, color="bt709")
    frames = prores_clips.read_all_frames(clip)
    assert frames[0].shape[:2] == (2160, 3840)
    assert [prores_clips.frame_number(f) for f in frames] == [0, 1, 2]
    probe = probe_movie(clip)
    assert (probe.width, probe.height, probe.color_space, probe.color_range) == (3840, 2160, "bt709", "tv")


def test_factory_defaults_are_320x180_untagged(tmp_path):
    clip = str(tmp_path / "d.mov")
    prores_clips.make_numbered_clip(clip, count=3)
    probe = probe_movie(clip)
    assert (probe.width, probe.height, probe.color_space) == (320, 180, "")


def test_factory_rejects_unknown_color_tag(tmp_path):
    with pytest.raises(ValueError, match="bt709"):
        prores_clips.make_numbered_clip(str(tmp_path / "x.mov"), count=1, color="bt2020")


def test_factory_rejects_chroma_size_that_does_not_fit_the_blocks(tmp_path):
    """색 블록(색차 5x6 칸)이 안 나눠떨어지는 크기는 조용히 잘라 쓰지 않고 막는다."""
    with pytest.raises(ValueError, match="블록"):
        prores_clips.make_chroma_clip(str(tmp_path / "x.mov"), count=1, width=322, height=180)


def decode_bgra(path):
    """ffmpeg로 알파를 살려 BGRA 8비트 프레임열 (장수, 높이, 너비, 4)로 읽는다 (cv2는 알파를 버림)."""
    probe = probe_movie(path)
    result = run_ffmpeg(["-i", path, "-f", "rawvideo", "-pix_fmt", "bgra", "pipe:1"], "알파 클립 BGRA 디코드")
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, probe.height, probe.width, 4)


def test_factory_alpha_clip_has_alpha_plane(tmp_path):
    """alpha=True: 왼쪽 절반 알파 0·오른쪽 절반 알파 최대인 알파 트랙, 투명한 쪽의 색은 검정이 아니라 원래 색."""
    clip, plain = str(tmp_path / "alpha.mov"), str(tmp_path / "plain.mov")
    prores_clips.make_chroma_clip(clip, count=4, alpha=True)
    prores_clips.make_chroma_clip(plain, count=4, profile="4", pix_fmt="yuv444p10le")  # 같은 색, 알파 평면만 없는 4444
    assert probe_movie(clip).pix_fmt.startswith("yuva444p")  # 4444의 디코더 쪽 값은 12비트(yuva444p12le)로 나옴
    assert not probe_movie(plain).pix_fmt.startswith("yuva")

    alpha = decode_bgra(clip)[..., 3]
    half = prores_clips.WIDTH // 2
    assert alpha.shape == (4, prores_clips.HEIGHT, prores_clips.WIDTH)
    assert alpha[:, :, :half].max() == 0
    assert alpha[:, :, half:].min() == 255

    frames, plain_frames = prores_clips.read_all_frames(clip), prores_clips.read_all_frames(plain)
    assert len(frames) == 4
    for frame, plain_frame in zip(frames, plain_frames):
        left = frame[:, :half]
        assert left.mean() > 50  # 검정으로 지워지지 않음
        # 알파 0 아래의 색이 알파 없는 같은 클립의 색과 인코더 양자화 오차(평균 ~2.6) 안에서 같음 — 검정으로 지웠다면 차이가 ~127
        assert np.abs(left.astype(np.int16) - plain_frame[:, :half].astype(np.int16)).mean() < 5


def test_factory_alpha_requires_an_alpha_pix_fmt(tmp_path):
    with pytest.raises(ValueError, match="알파"):
        prores_clips.make_chroma_clip(str(tmp_path / "x.mov"), count=1, alpha=True, pix_fmt="yuv444p10le")


@pytest.mark.parametrize("pix_fmt", ["yuv444p10le", "yuv422p10le"])
def test_chroma_clip_is_in_gamut(tmp_path, pix_fmt):
    """유채색 클립의 색은 전부 RGB 영역 안: 태그 없는 클립을 cv2(601)로 디코드했을 때 채널이 0·255로 잘린 화소가 거의 없다.

    예전 _chroma_raw는 YCbCr 코드값을 무작위로 뽑아 영역 밖 색이 수십 %였고, 디코더마다 잘라 내는 방식이 달라
    (ffmpeg 대 Apple) 파이프 대 cv2 비교가 255까지 어긋났다. _chroma_raw가 그 방식으로 되돌아가면 이 시험이 깨진다."""
    clip = str(tmp_path / "chroma.mov")
    prores_clips.make_chroma_clip(clip, count=6, pix_fmt=pix_fmt)
    frames = np.stack(prores_clips.read_all_frames(clip))
    clamped = ((frames == 0) | (frames == 255)).any(axis=-1)
    assert clamped.mean() < CLAMPED_FRACTION_LIMIT, f"0·255로 잘린 화소 {clamped.mean():.2%}"


def split_planes(raw, count, pix_fmt, width, height):
    """_chroma_raw 바이트 → 프레임별 (Y, Cb, Cr, 알파 or None) 평면 (정수 코드값)."""
    alpha, _, _, dtype, chroma_w, chroma_h = prores_clips._layout(pix_fmt, width, height)
    sizes = [(height, width), (chroma_h, chroma_w), (chroma_h, chroma_w)] + ([(height, width)] if alpha else [])
    flat = np.frombuffer(raw, dtype)
    frames, offset = [], 0
    for _ in range(count):
        planes = []
        for h, w in sizes:
            planes.append(flat[offset:offset + h * w].reshape(h, w).astype(np.float64))
            offset += h * w
        frames.append(planes)
    assert offset == flat.size
    return frames


@pytest.mark.parametrize("color, kr, kb", [(None, 0.299, 0.114), ("bt709", 0.2126, 0.0722)], ids=["601", "709"])
@pytest.mark.parametrize("pix_fmt", ["yuv444p10le", "yuv422p10le"])
def test_chroma_raw_planes_decode_inside_rgb_gamut(pix_fmt, color, kr, kb):
    """_chroma_raw의 평면을 태그에 맞는 행렬(태그 없음 601, bt709 709)로 클램프 없이 RGB로 되돌리면 뽑았던 구간
    (RGB_MARGIN ~ 255 - RGB_MARGIN, 8비트 코드 반올림 오차 RGB_ROUNDING_SLACK만 허용) 안에 든다.
    구간을 0~255가 아니라 생성 구간으로 좁혀야 행렬 선택이 고정된다: 709 클립을 601 행렬로 만들어도 되돌린 값은 약 5.9~248.4라
    0~255 안이라서 통과해 버리지만 생성 구간(약 22.6~232.4)은 벗어난다. YCbCr 코드를 무작위로 뽑은 경우도 마찬가지."""
    width, height, count = 640, 360, 2
    raw = prores_clips._chroma_raw(count, pix_fmt, 7, width, height, color)
    kg = 1 - kr - kb
    for y, cb, cr in (planes[:3] for planes in split_planes(raw, count, pix_fmt, width, height)):
        cb, cr = np.repeat(cb, y.shape[1] // cb.shape[1], axis=1), np.repeat(cr, y.shape[1] // cr.shape[1], axis=1)
        cb, cr = np.repeat(cb, y.shape[0] // cb.shape[0], axis=0), np.repeat(cr, y.shape[0] // cr.shape[0], axis=0)
        luma, pb, pr = (y / 4 - 16) / 219, (cb / 4 - 128) / 224, (cr / 4 - 128) / 224
        red, blue = luma + 2 * (1 - kr) * pr, luma + 2 * (1 - kb) * pb
        green = (luma - kr * red - kb * blue) / kg
        rgb = np.stack([red, green, blue]) * 255
        assert rgb.min() >= prores_clips.RGB_MARGIN - RGB_ROUNDING_SLACK, (rgb.min(), rgb.max())
        assert rgb.max() <= 255 - prores_clips.RGB_MARGIN + RGB_ROUNDING_SLACK, (rgb.min(), rgb.max())
