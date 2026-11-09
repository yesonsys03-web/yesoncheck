"""B 키 오버레이의 흰 상자 오른쪽 끝을 고정 (사용자 보고 2026-11-09 — "프레임 카운트가 1·2·3 자리로 바뀌면 흰 상자 오른쪽 끝이 계속 움직여
떨려 보여, 고정해 줘").

예전에는 두 그리기 길 모두 상자 너비를 지금 글자의 너비로 정함: 굽는 길(cv2 Hershey — 숫자 폭은 모두 같지만 자릿수 1 → 119로 바뀜)과 네이티브
아이템 길(Qt 글꼴 — Mac 시스템 글꼴은 숫자 폭이 다름: '1' 29.6px 대 '0' 40.1px, 60px Bold). 좁은 프레임에서는 글자를 들어갈 만큼 줄이는데 그 배율도
지금 글자로 정해 글자 크기까지 떨렸음. 이제 상자 너비·배율·글꼴 크기는 '자리 잡을 글'(overlay_reserve_text — 'Frame: n/N'의 n을 N의 자릿수만큼
가장 넓은 숫자로)로 정함. 글자는 예전처럼 왼쪽 맞춤 — 상자 오른쪽 끝만 고정.
"""

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtGui import QFontMetricsF

from tests.native_fakes import fake_native_player, new_player, player_with_fake_native  # noqa: F401 (픽스처)
from yesoncheck.overlay_text_layout import overlay_layout, overlay_reserve_text, widest_digit
from yesoncheck.player_playback import PlayerPlaybackMixin

LABELS = [f"File: 1604_623_v001.mov, Frame: {n}/166" for n in (1, 7, 9, 10, 11, 44, 99, 100, 111, 119, 166)]
SIZES = [(3840, 2160), (1920, 1080), (640, 360), (600, 1080)]  # 600×1080: 글자가 너비를 넘쳐 줄이는 갈래


# ---------------------------------------------------------------- 자리 잡을 글


def test_reserve_text_uses_the_widest_digit_for_the_frame_number():
    assert overlay_reserve_text("File: a.mov, Frame: 1/166", "0") == "File: a.mov, Frame: 000/166"
    assert overlay_reserve_text("File: a.mov, Frame: 119/166", "8") == "File: a.mov, Frame: 888/166"


def test_reserve_text_leaves_the_file_name_and_total_alone():
    """파일 이름의 숫자(1604_623_v001)·전체 장 수는 그대로 — 바뀌는 것은 지금 번호뿐."""
    assert overlay_reserve_text("File: 1604_623_v001.mov, Frame: 7/166", "0") == "File: 1604_623_v001.mov, Frame: 000/166"


def test_reserve_text_keeps_a_longer_current_number():
    """지금 번호가 전체보다 길면(끝을 넘은 위치 등) 그 자릿수 — 상자가 글자보다 좁아지지 않게."""
    assert overlay_reserve_text("File: a.mov, Frame: 1000/999", "0") == "File: a.mov, Frame: 0000/999"


def test_reserve_text_without_a_frame_counter_is_the_text():
    assert overlay_reserve_text("File: a.mov", "0") == "File: a.mov"


def test_widest_digit_picks_by_the_given_width():
    widths = {"0": 40.1, "1": 29.6, "4": 39.6, "8": 39.7}
    assert widest_digit(lambda d: widths.get(d, 30.0)) == "0"


# ---------------------------------------------------------------- 굽는 길 (cv2)


@pytest.mark.parametrize("size", SIZES)
def test_layout_box_and_scale_do_not_follow_the_frame_number(size):
    layouts = [overlay_layout(label, *size) for label in LABELS]
    assert len({layout.box_width for layout in layouts}) == 1
    assert len({(layout.scale, layout.thickness, layout.text_height, layout.baseline) for layout in layouts}) == 1
    assert all(layout.text_width <= layout.box_width <= layout.room for layout in layouts)


def burned_extent(label, width, height):
    """굽는 길(PlayerPlaybackMixin.overlay_text)이 검정 프레임에 구운 것 — (흰 상자 오른쪽 끝 열, 검정 글자 잉크의 오른쪽 끝 열)."""
    frame = np.zeros((height, width, 3), np.uint8)
    PlayerPlaybackMixin.overlay_text(SimpleNamespace(overlay_label=lambda: label), frame)
    white = np.all(frame == 255, axis=2)
    ys, xs = np.where(white)
    box = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ink_cols = np.where(np.any(np.all(box < 128, axis=2), axis=0))[0]
    return int(xs.max()), int(xs.min() + ink_cols.max())


@pytest.mark.parametrize("size", SIZES)
def test_burned_box_right_edge_is_fixed(size):
    extents = [burned_extent(label, *size) for label in LABELS]
    assert len({right for right, _ink in extents}) == 1
    assert all(ink < right for right, ink in extents)  # 글자는 늘 상자 안


# ---------------------------------------------------------------- 네이티브 아이템 길 (Qt 글꼴)


@pytest.mark.parametrize("size", SIZES)
def test_native_item_box_right_edge_and_font_are_fixed(player_with_fake_native, size):
    widget = player_with_fake_native.player.videoWidget
    rights, pixel_sizes = set(), set()
    for label in LABELS:
        widget.set_overlay_text(label, *size)
        box, text = widget.overlay_box_item, widget.overlay_text_item
        rect = box.mapRectToScene(box.rect())
        rights.add(round(rect.right(), 3))
        pixel_sizes.add(text.font().pixelSize())
        assert text.scenePos().x() + QFontMetricsF(text.font()).horizontalAdvance(label) < rect.right()  # 글자는 늘 상자 안
    assert len(rights) == 1
    assert len(pixel_sizes) == 1
