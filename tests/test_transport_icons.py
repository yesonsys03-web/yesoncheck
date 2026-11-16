"""재생 줄의 아이콘(`transport_icons`): 글꼴·이모지에 기대지 않고 직접 그린 한 색 그림."""

import numpy as np
import pytest
from PyQt5.QtGui import QColor, QIcon, QImage

from yesoncheck import transport_icons


def pixels(pixmap):
    """(높이, 너비, 4) uint8 — B, G, R, A."""
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    bits = image.bits()
    bits.setsize(image.byteCount())
    return np.frombuffer(bits, np.uint8).reshape(image.height(), image.width(), 4).copy()


@pytest.mark.parametrize("kind", transport_icons.KINDS)
def test_each_kind_draws_in_the_given_colour_on_transparent(qapp, kind):
    data = pixels(transport_icons.pixmap(kind, QColor("#3366cc"), 18))
    assert data.shape == (18, 18, 4)
    solid = data[data[..., 3] == 255]
    assert len(solid) > 0, "불투명한 픽셀이 하나도 없음"
    assert (solid[:, :3] == (0xCC, 0x66, 0x33)).all()  # B, G, R
    assert (data[..., 3] == 0).any(), "바탕이 투명하지 않음"


def test_kinds_are_the_transport_and_tool_pictures():
    assert transport_icons.KINDS == ("first", "prev", "play", "pause", "next", "last", "loop", "volume",
                                     "wipe", "annotate", "ocr", "close")


def test_wipe_picture_is_split_into_a_filled_and_an_open_half(qapp):
    """와이프 = 세로로 나뉜 사각형: 왼쪽 반은 채우고 오른쪽 반은 테두리만 — 왼쪽이 더 진함."""
    alpha = pixels(transport_icons.pixmap("wipe", QColor("#ffffff"), 18))[..., 3].astype(int)
    assert alpha[:, :9].sum() > 1.5 * alpha[:, 9:].sum() > 0


def test_ocr_picture_has_marks_in_all_four_corners(qapp):
    """OCR = 모서리 표시(읽을 영역) 안의 글자 줄 — 네 모서리 모두에 그림이 있음."""
    alpha = pixels(transport_icons.pixmap("ocr", QColor("#ffffff"), 18))[..., 3]
    for rows, cols in ((slice(0, 6), slice(0, 6)), (slice(0, 6), slice(12, 18)),
                       (slice(12, 18), slice(0, 6)), (slice(12, 18), slice(12, 18))):
        assert (alpha[rows, cols] == 255).any()
    assert (alpha[7:11, 6:12] == 255).any()  # 가운데의 글자 줄


def test_annotate_picture_is_a_diagonal_pencil(qapp):
    """주석 = 연필: 오른쪽 위에서 왼쪽 아래로 — 그 대각선 위에만 그림이 있고 반대쪽 모서리는 비어 있음."""
    alpha = pixels(transport_icons.pixmap("annotate", QColor("#ffffff"), 18))[..., 3]
    assert (alpha[2:6, 11:16] == 255).any() and (alpha[11:16, 3:7] > 0).any()
    assert not alpha[:5, :5].any() and not alpha[13:, 13:].any()


def test_kinds_look_different_from_each_other(qapp):
    drawn = {kind: pixels(transport_icons.pixmap(kind, QColor("#ffffff"), 18)) for kind in transport_icons.KINDS}
    kinds = list(drawn)
    for i, one in enumerate(kinds):
        for other in kinds[i + 1:]:
            assert not np.array_equal(drawn[one], drawn[other]), (one, other)


@pytest.mark.parametrize("left,right", [("first", "last"), ("prev", "next")])
def test_back_and_forward_pictures_mirror_each_other(qapp, left, right):
    back = pixels(transport_icons.pixmap(left, QColor("#ffffff"), 36))[..., 3].astype(int)
    forward = pixels(transport_icons.pixmap(right, QColor("#ffffff"), 36))[..., 3].astype(int)
    assert np.abs(back - forward[:, ::-1]).mean() < 6  # 좌우로 뒤집으면 같은 그림 (가장자리 안티앨리어싱 차이만)
    assert np.abs(back - forward).mean() > 30  # 뒤집지 않으면 다른 그림


def test_first_has_its_bar_on_the_left_and_prev_on_the_right(qapp):
    """처음(|◀)은 막대가 바깥(왼쪽), 한 장 뒤(◀|)는 막대가 삼각형 뒤(오른쪽) — 둘을 가르는 표지."""
    def bar_column(kind):
        alpha = pixels(transport_icons.pixmap(kind, QColor("#ffffff"), 36))[..., 3]
        full = np.flatnonzero((alpha == 255).sum(axis=0) >= 20)  # 위아래로 꽉 찬 열 = 막대 (삼각형은 한 열만 그만큼 참)
        return full.min(), full.max()
    assert bar_column("first")[0] < 9
    assert bar_column("prev")[1] > 26


def test_device_pixel_ratio_scales_the_pixels(qapp):
    sharp = transport_icons.pixmap("play", QColor("#ffffff"), 18, dpr=2.0)
    assert (sharp.width(), sharp.height()) == (36, 36)
    assert sharp.devicePixelRatio() == 2.0


def test_icon_wraps_the_pixmap(qapp):
    icon = transport_icons.icon("pause", QColor("#d0d0d0"), 18)
    assert isinstance(icon, QIcon) and not icon.isNull()


def test_unknown_kind_raises(qapp):
    with pytest.raises(ValueError):
        transport_icons.pixmap("rewind", QColor("#ffffff"), 18)
