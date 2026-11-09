"""B 키 오버레이가 프레임마다 떨리지 않게 (사용자 보고 2026-11-09 — "프레임 카운트가 1·2·3 자리로 바뀌면 흰 상자 오른쪽 끝이 계속 움직여
떨려 보여").

원인은 Mac 네이티브 아이템 길의 글꼴: Mac 시스템 글꼴(SF)은 숫자 폭이 달라('1' 29.3px 대 '0' 39.9px, 60px Bold) 프레임 번호가 바뀔 때마다 글자
폭이 달라져 '/전체'와 상자 끝이 프레임마다 움직였음. 첫 고침(PR #30)은 상자 너비를 가장 넓은 번호에 맞춰 고정했는데, 상자는 멈췄지만 글자 안의
'/전체'는 여전히 떨렸고 번호가 짧으면 오른쪽에 빈자리가 남았음. 이제(사용자 결정 '상자를 글자에 딱 맞춤'): 아이템 글꼴을 숫자 폭이 같은 글꼴
(Helvetica Neue, 없으면 Arial)로 하고 상자는 글자에 딱 맞춤 — 같은 자릿수 안에서는 글자 폭·상자 끝이 그대로, 자릿수가 바뀌는 순간(9→10·99→100)에만
한 칸씩 늘어남. 굽는 길(cv2 Hershey)은 원래 숫자 폭이 같음. 좁은 프레임에서 들어갈 만큼 줄이는 글자 크기는 '자리 잡을 글'(overlay_reserve_text —
'Frame: n/N'의 n을 N의 자릿수만큼 가장 넓은 숫자로)로 정해 번호에 따라 글자 크기가 바뀌지 않음.
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


def digits(label):
    """'Frame: n/N'의 n 자릿수 — 같은 자릿수끼리 묶어 봄."""
    return len(label.rsplit("Frame: ", 1)[1].split("/")[0])


def by_digits(values):
    """[(자릿수, 값)] → {자릿수: 값들의 집합}."""
    groups = {}
    for count, value in values:
        groups.setdefault(count, set()).add(value)
    return groups


@pytest.mark.parametrize("size", SIZES)
def test_layout_scale_does_not_follow_the_frame_number(size):
    """글자 크기(배율·굵기·높이)는 번호와 상관없이 같음, 글자 폭은 같은 자릿수 안에서 같음(Hershey는 숫자 폭이 같음)."""
    layouts = [(digits(label), overlay_layout(label, *size)) for label in LABELS]
    assert len({(layout.scale, layout.thickness, layout.text_height, layout.baseline) for _d, layout in layouts}) == 1
    assert all(len(widths) == 1 for widths in by_digits((d, layout.text_width) for d, layout in layouts).values())
    assert all(layout.text_width <= layout.room for _d, layout in layouts)


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
def test_burned_box_hugs_the_text_and_holds_within_a_digit_count(size):
    """구운 상자: 글자에 딱 맞춤 — 상자 끝과 글자 잉크 끝 사이는 pad와 마지막 글자 자체의 뒤 간격뿐(숫자 반 칸이 안 됨; 자리를 잡던 PR #30은 번호가
    짧으면 숫자 한 칸 이상 비었음), 같은 자릿수 안에서는 끝이 제자리."""
    import cv2

    from yesoncheck.overlay_text_layout import OVERLAY_FONT

    extents = [(digits(label), burned_extent(label, *size)) for label in LABELS]
    layout = overlay_layout(LABELS[0], *size)
    digit = cv2.getTextSize("0", OVERLAY_FONT, layout.scale, layout.thickness)[0][0]
    assert all(len(rights) == 1 for rights in by_digits((d, right) for d, (right, _ink) in extents).values())
    assert all(0 < right - ink < layout.pad + digit / 2 for _d, (right, ink) in extents)


# ---------------------------------------------------------------- 네이티브 아이템 길 (Qt 글꼴)


@pytest.mark.parametrize("size", SIZES)
def test_native_item_box_hugs_the_text_and_font_is_fixed(player_with_fake_native, size):
    """아이템 상자: 오른쪽 끝 = 글자 끝 + pad (빈자리 없음), 글꼴 크기는 번호와 상관없이 같음."""
    widget = player_with_fake_native.player.videoWidget
    pixel_sizes = set()
    for label in LABELS:
        widget.set_overlay_text(label, *size)
        box, text = widget.overlay_box_item, widget.overlay_text_item
        rect = box.mapRectToScene(box.rect())
        pad = overlay_layout(label, *size).pad
        end = text.scenePos().x() + QFontMetricsF(text.font()).horizontalAdvance(label)
        assert rect.right() == pytest.approx(end + pad + 1, abs=0.01)
        pixel_sizes.add(text.font().pixelSize())
    assert len(pixel_sizes) == 1


# ---------------------------------------------------------------- 글자 안의 숫자 (Qt 글꼴)


def test_overlay_font_asks_for_tabular_digit_families():
    """B 키 아이템 글꼴은 숫자 폭이 같은 글꼴로 (사용자 보고 2026-11-09 — PR #30으로 상자는 고정됐지만 재생 중 프레임 숫자가 떨림: Mac 시스템
    글꼴(SF)은 숫자 폭이 달라 '/97'이 프레임마다 좌우로 움직였음). Helvetica Neue(모든 Mac), 없으면 Arial."""
    from yesoncheck.overlay_text_layout import overlay_layout
    from yesoncheck.video_widget import OVERLAY_FONT_FAMILIES, overlay_font

    label = "File: FL_106_A002_TK1.mov, Frame: 47/97"
    font = overlay_font(label, overlay_layout(label, 1920, 1080))
    assert font.families()[:len(OVERLAY_FONT_FAMILIES)] == OVERLAY_FONT_FAMILIES


def _resolved_tabular_font(widget):
    from PyQt5.QtGui import QFontInfo

    from yesoncheck.video_widget import OVERLAY_FONT_FAMILIES

    font = widget.overlay_text_item.font()
    family = QFontInfo(font).family()
    if family not in OVERLAY_FONT_FAMILIES:
        pytest.skip(f"이 시험 환경에 {OVERLAY_FONT_FAMILIES} 글꼴이 없음({family}) — Mac CI·이 Mac에서 봄")
    return font


def test_native_item_digits_all_have_the_same_width(player_with_fake_native):
    widget = player_with_fake_native.player.videoWidget
    widget.set_overlay_text("File: FL_106_A002_TK1.mov, Frame: 47/97", 1920, 1080)
    metrics = QFontMetricsF(_resolved_tabular_font(widget))
    assert len({round(metrics.horizontalAdvance(d), 3) for d in "0123456789"}) == 1


def test_native_item_count_does_not_move_within_the_same_digit_count(player_with_fake_native):
    """같은 자릿수 안에서는 글자 전체 폭이 같음 = '/97'이 제자리 (프레임마다 떨리지 않음)."""
    widget = player_with_fake_native.player.videoWidget
    widths = set()
    for n in (10, 11, 17, 41, 47, 88, 97):
        label = f"File: FL_106_A002_TK1.mov, Frame: {n}/97"
        widget.set_overlay_text(label, 1920, 1080)
        widths.add(round(QFontMetricsF(_resolved_tabular_font(widget)).horizontalAdvance(label), 3))
    assert len(widths) == 1
