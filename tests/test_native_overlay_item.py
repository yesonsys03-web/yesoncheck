"""B 키 오버레이 — 네이티브 프레임일 때 (Apple Silicon 네이티브 재생 — 계획 Task 12·B7).

네이티브 프레임(IOSurface 위 BGRX 뷰, 읽기 전용)에는 B 키 글자("File: <이름>, Frame: n/N")를 굽지 않는다: prepare_frame_for_display가 프레임을
그대로 돌려주고(복사·cv2 굽기 없음 — 예전에는 frame.copy()가 손잡이 없는 4채널 배열이라 updateFrame이 RGB 길로 떨어져 GL set_frame이 ValueError),
CustomVideoWidget이 가진 오버레이 아이템 한 쌍(흰 QGraphicsRectItem — z 13: ROI 10 위, 주석 미리보기 14·편집 핸들 16 아래 — 과 그 자식인 검정
QGraphicsSimpleTextItem — 자식이라 늘 상자 위, 영상 아이템 좌표 = 프레임 픽셀)이 글자를 보인다. 아이템은 updateFrame의 네이티브 분기가 플레이어가 등록한 공급자(_overlay_text_for_native)에게
글자를 물어 갱신 — prepare_frame_for_display를 거치지 않는 _minimal_preview_seek에서도 새 프레임 번호. 크기·자리·굵기는 굽는 길(overlay_text)과 같은
규칙(overlay_metrics): 상자의 왼쪽·위는 구운 흰 상자와 같은 픽셀, 글자는 Qt 글꼴(모양은 Hershey와 다름 — 사용자 결정)의 대문자 높이를 cv2 글자
높이에 맞춤, 기준선은 같은 자리.
비네이티브(Intel·Windows) 굽기는 tests/test_overlay_text_size.py의 무수정 통과와 글자 그대로 옮긴 배치 계산(overlay_text_layout.overlay_layout)이
지킨다 — ci/screenshot_check.py에는 B를 켜는 장면이 없어 그것은 updateFrame의 RGB 길(숨은 아이템이 그림을 바꾸지 않음)만 지킴(Ruling 4 — 갈음 시험 없음).
"""

import math

import cv2
import numpy as np
import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QFontMetricsF, QKeyEvent
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsSimpleTextItem

from tests.native_fakes import (  # noqa: F401 (픽스처 — new_player는 native_fakes의 픽스처가 요청함)
    FAKE_FRAME_COUNT,
    FAKE_HEIGHT,
    FAKE_WIDTH,
    fake_native_player,
    new_player,
    player_with_fake_native,
)
from yesoncheck.overlay_text_layout import overlay_metrics, overlay_reserve_text, widest_digit

TOTAL = FAKE_FRAME_COUNT
OVERLAY_Z = 13
FONT = cv2.FONT_HERSHEY_SIMPLEX


def assert_untouched(rig):
    """연 뒤로 네이티브 프레임의 픽셀을 CPU가 만진 적이 없음 — 파이썬 쪽 접근 0, cv2.cvtColor 0."""
    assert rig.reads == [], f"네이티브 프레임의 픽셀을 파이썬에서 읽음: {rig.reads}"
    assert rig.cvt_calls == [], f"네이티브 프레임을 cv2.cvtColor로 변환함 (code {rig.cvt_calls})"


def overlay_candidates(widget):
    """장면의 B 키 오버레이 아이템 후보 (상자들, 글자들) — z 13의 QGraphicsRectItem, 그리고 그 상자의 자식이거나 z 13인(맨 위 단계)
    QGraphicsSimpleTextItem. 글자를 자식이 아닌 형제로 두는 구현도 찾아서 쌓임 순서 단언이 그것을 잡게 함."""
    boxes = [item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem) and item.zValue() == OVERLAY_Z]
    texts = [item for item in widget.scene.items() if isinstance(item, QGraphicsSimpleTextItem)
             and (item.parentItem() in boxes or (item.parentItem() is None and item.zValue() == OVERLAY_Z))]
    return boxes, texts


def visible_overlay(widget):
    """보이는 B 키 오버레이 아이템(상자·글자)."""
    boxes, texts = overlay_candidates(widget)
    return [item for item in boxes + texts if item.isVisible()]


def overlay_items(widget):
    """B 키 오버레이 아이템 (상자, 글자) — 하나씩."""
    boxes, texts = overlay_candidates(widget)
    assert len(boxes) == 1 and len(texts) == 1, f"B 키 오버레이 아이템: z {OVERLAY_Z} 상자 {len(boxes)}개, 글자 {len(texts)}개"
    return boxes[0], texts[0]


def press_b(player):
    """B 키 — keyPressEvent가 show_overlay를 뒤집고 update_frame."""
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier, "b"))


def box_rect(box):
    """상자 아이템의 장면 좌표 사각형 (장면 원점 = 영상 아이템 원점 = 프레임 픽셀 (0, 0))."""
    return box.mapRectToScene(box.rect())


def burned_box(player, width, height):
    """같은 플레이어 상태로 굽는 길(overlay_text)이 width×height 검정 프레임에 구운 흰 상자 — (왼쪽, 위, 오른쪽 끝, 아래 끝) 픽셀 번호(끝 포함)."""
    frame = np.zeros((height, width, 3), np.uint8)
    player.overlay_text(frame)
    ys, xs = np.where(np.all(frame == 255, axis=2))
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ---------------------------------------------------------------- 보이기·숨기기·갱신

def test_overlay_item_shown_only_when_show_overlay(player_with_fake_native):
    """B를 누르기 전에는 오버레이 아이템이 보이지 않고, 누르면 흰 상자·검정 글자가 보이며 글자는 굽는 길과 같은 "File: clip_a.mov, Frame: 1/64"
    (열 때 seek_to_frame(1) → 캡처 위치 1), 글자가 상자 위에 쌓임, 재생 틱마다 새 번호, 다시 누르면 숨음 — 그동안 네이티브 픽셀 접근 0.

    깨지는 변경: 플레이어가 공급자를 등록하지 않거나(set_overlay_provider) updateFrame의 네이티브 분기가 공급자를 부르지 않으면 B를 눌러도 아이템이
    안 보임; 공급자가 show_overlay를 보지 않으면 다시 눌러도 남음; 상자를 z 13 사각형으로 만들지 않으면 찾지 못함; 글자를 상자의 자식이 아닌 형제로
    상자보다 먼저 넣거나 부모 뒤로 쌓으면(ItemStacksBehindParent) 상자가 글자를 가림."""
    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    assert visible_overlay(widget) == []

    press_b(player)

    box, text = overlay_items(widget)
    assert player.show_overlay and box.isVisible() and text.isVisible()
    order = widget.scene.items(Qt.DescendingOrder)
    assert order.index(text) < order.index(box), "글자가 흰 상자 아래 — 상자가 글자를 가림"
    assert text.text() == f"File: clip_a.mov, Frame: 1/{TOTAL}"
    assert box.brush().color().getRgb() == (255, 255, 255, 255) and box.pen().style() == Qt.NoPen
    assert text.brush().color().getRgb() == (0, 0, 0, 255)

    player.next_frame_playback()
    assert text.isVisible() and text.text() == f"File: clip_a.mov, Frame: 2/{TOTAL}"

    press_b(player)
    assert not player.show_overlay and visible_overlay(widget) == []
    assert_untouched(rig)


def test_overlay_item_updates_on_minimal_preview_seek(player_with_fake_native):
    """OCR 검토 창 미리보기(_minimal_preview_seek — prepare_frame_for_display를 거치지 않고 updateFrame(frame_a, None)을 바로 부름)도 글자를 새
    번호로: 61번(0부터 60)으로 뛰면 "Frame: 61/64"(read 뒤 캡처 위치), 픽셀 접근 0.

    깨지는 변경: 아이템 갱신을 prepare_frame_for_display(또는 update_frame)에 두고 updateFrame에서 하지 않으면 앞 번호 "Frame: 1/64"가 남음."""
    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    player.show_overlay = True
    player.update_frame()

    player._minimal_preview_seek(60, TOTAL)

    assert player.frame_a is rig.cap_a.frames[60]
    _box, text = overlay_items(widget)
    assert text.isVisible() and text.text().endswith(f"Frame: 61/{TOTAL}"), text.text()
    assert_untouched(rig)


@pytest.mark.parametrize("annotated", [False, True], ids=["b_overlay", "b_overlay_and_annotation"])
def test_native_prepare_does_not_burn(player_with_fake_native, annotated):
    """B가 켜져 있어도(주석이 있는 프레임이어도) 네이티브 프레임은 prepare_frame_for_display가 그 객체 그대로 돌려줌 — 복사·굽기 없음(픽셀 접근 0),
    그리고 update_frame이 GL 아이템에 네이티브 프레임 자체를 set_sides로 넘김.

    깨지는 변경: prepare_frame_for_display의 네이티브 첫 줄 가드를 빼면 frame.copy()(reads에 "copy")에 굽고, 그 복사본(손잡이 없는 4채널 배열)이
    updateFrame의 RGB 길로 가서 GL set_frame이 ValueError — 예전 결함(재생 타이머 슬롯 안). 가드를 B 키 글자에만 두면 주석 갈래가 복사함."""
    rig = player_with_fake_native
    player = rig.player
    player.show_overlay = True
    frame = player.frame_a
    if annotated:
        player.annotation_store.add(player.get_current_frame_index(), {
            "type": "rect", "norm_x1": 0.25, "norm_y1": 0.25, "norm_x2": 0.75, "norm_y2": 0.75, "color": "#ff3333", "stroke_width": 3})
        assert player.current_frame_has_annotations()

    assert player.prepare_frame_for_display(frame) is frame
    rig.sides.clear()
    player.update_frame()

    assert rig.sides and rig.sides[-1].a is frame and player.frame_a is frame
    assert_untouched(rig)


@pytest.mark.parametrize("next_frame", ["rgb", "cleared"])
def test_rgb_frame_hides_native_overlay(player_with_fake_native, next_frame):
    """네이티브 프레임에 B 글자 아이템이 보이는 뒤에 RGB 프레임(굽는 길 — 글자는 프레임에 구움)이 오거나 화면을 비우면(frame None) 아이템을 숨김 —
    앞 네이티브 프레임의 글자가 남지 않음, 예외 없음.

    깨지는 변경: updateFrame의 RGB 길(또는 frame None 갈래)에서 set_overlay_text(None, …)를 빼면 아이템이 남아 구운 글자와 겹치거나 빈 화면에 남음."""
    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    player.show_overlay = True
    player.update_frame()
    assert len(visible_overlay(widget)) == 2

    widget.updateFrame(np.zeros((FAKE_HEIGHT, FAKE_WIDTH, 3), np.uint8) if next_frame == "rgb" else None, None)

    assert visible_overlay(widget) == []


@pytest.mark.parametrize("viewport, video_item", [("gl", "pixmap"), ("raster", None)], ids=["pixmap_kill_switch", "raster_viewport"])
def test_pixmap_path_shows_overlay_item_too(fake_native_player, viewport, video_item):
    """픽스맵 아이템 길(킬 스위치 YESONCHECK_VIDEO_ITEM=pixmap·raster 뷰포트)도 같은 아이템: B를 누르면 글자가 보이고 다음 틱에 번호가 바뀜, 픽셀 접근 0.

    깨지는 변경: 아이템 갱신을 스트림 아이템(set_sides) 갈래에만 두면 픽스맵 길에서는 B 글자가 안 보임."""
    rig = fake_native_player(viewport=viewport, video_item=video_item)
    player, widget = rig.player, rig.player.videoWidget
    assert widget.video_item_stream is False

    press_b(player)
    _box, text = overlay_items(widget)
    assert text.isVisible() and text.text() == f"File: clip_a.mov, Frame: 1/{TOTAL}"
    player.next_frame_playback()
    assert text.text() == f"File: clip_a.mov, Frame: 2/{TOTAL}"
    assert widget._pixmap_backing is player.frame_a
    assert_untouched(rig)


def test_rgb_a_with_native_b_burns_the_overlay_once(fake_native_player):
    """혼합 비교(A = cv2 RGB, B = 네이티브, 와이프 X): A는 굽는 길 그대로 — prepare_frame_for_display가 A의 복사본에 글자를 구워 set_sides의 A로 넘기고,
    네이티브 분기지만 아이템은 숨김(A의 글자는 이미 구웠으므로 두 번 그리지 않음 — 와이프가 구운 글자를 자르는 것도 예전 RGB 길과 같음). B의 픽셀 접근 0.

    깨지는 변경: 네이티브 분기에서 A가 네이티브인지 보지 않고 아이템을 보이면 구운 글자 위에 Qt 글자가 한 번 더 보임."""
    rig = fake_native_player(ab=True, native="B", size=(32, 16), count=24)
    player, widget = rig.player, rig.player.videoWidget
    player.wipeXButton.setChecked(True)
    player.show_overlay = True
    rig.sides.clear()

    player.update_frame()

    call = rig.sides[-1]
    assert call.b is player.frame_b and call.axis == "x"
    assert call.a is not player.frame_a and np.all(call.a == 255, axis=2).any(), "A에 흰 상자가 구워지지 않음"
    assert visible_overlay(widget) == []
    assert_untouched(rig)


# ---------------------------------------------------------------- 기하 (overlay_metrics — 굽는 길과 같은 규칙)

@pytest.mark.parametrize("size", [(1920, 1080), (3840, 2160)], ids=["1080p", "4k"])
def test_overlay_item_geometry_follows_overlay_metrics(fake_native_player, size):
    """1080p·4K 네이티브 프레임: 상자의 왼쪽 = margin_x − pad, 위 = 기준선 − cv2 글자 높이 − pad, 아래 = 기준선 + max(pad, cv2 꼬리, Qt 꼬리) — 왼쪽·위·
    (Qt 꼬리가 cv2보다 짧으면) 아래가 구운 흰 상자와 같은 픽셀; 글자 기준선은 장면(= 프레임) 좌표 (margin_x, 높이 − margin_y), Qt 대문자 높이 ≈ cv2
    글자 높이(±1px),
    글자 잉크가 상자 안, 상자 오른쪽 = 글자 끝 + pad(빈자리 없음 — 숫자 폭이 같은 글꼴이라 같은 자릿수 안에서는 떨리지 않음), 굵기는 cv2 획이 3px 이상이라 Bold.

    깨지는 변경: margin_x·margin_y를 바꿔 쓰면 왼쪽·아래가 어긋남; 기준선 대신 글자 아이템 원점(글줄 위)을 높이 − margin_y에 두면 글자가 상자 밑으로;
    글꼴 크기를 cv2 높이에 맞추지 않으면(앱 기본 글꼴 13pt 그대로) 대문자 높이가 틀림; pad를 빼면 상자가 글자에 붙음."""
    width, height = size
    rig = fake_native_player(size=size, count=4)
    player, widget = rig.player, rig.player.videoWidget
    player.show_overlay = True
    player.update_frame()

    box, text = overlay_items(widget)
    label = text.text()
    assert label == "File: clip_a.mov, Frame: 1/4"
    m = overlay_metrics(width, height)
    (tw, th), base = cv2.getTextSize(label, FONT, m.scale, m.thickness)
    assert tw <= width - 2 * m.margin_x  # 이 크기에서는 줄이지 않음 — 줄이는 갈래는 아래 시험
    fm = QFontMetricsF(text.font())
    rect = box_rect(box)
    left, top, _right, bottom = burned_box(player, width, height)
    baseline = height - m.margin_y

    assert rect.left() == m.margin_x - m.pad == left
    assert rect.top() == baseline - th - m.pad == top
    assert rect.bottom() == baseline + max(m.pad, base, math.ceil(fm.descent())) + 1  # +1: cv2.rectangle처럼 끝 픽셀까지
    assert rect.bottom() >= bottom + 1
    if math.ceil(fm.descent()) <= max(m.pad, base):
        assert rect.bottom() == bottom + 1
    assert text.scenePos().x() == m.margin_x
    assert text.scenePos().y() + fm.ascent() == pytest.approx(baseline)
    assert fm.capHeight() == pytest.approx(th, abs=1)
    assert rect.contains(fm.tightBoundingRect(label).translated(m.margin_x, baseline)), "글자 잉크가 흰 상자 밖으로 나감"
    assert rect.right() == pytest.approx(m.margin_x + fm.horizontalAdvance(label) + m.pad + 1, abs=0.01)  # 글자에 딱 맞춤 (2026-11-09 사용자 결정)
    assert text.font().bold() is True and m.thickness >= 3
    assert_untouched(rig)


def test_overlay_box_bottom_covers_qt_descent(player_with_fake_native, monkeypatch):
    """상자 아래 = 기준선 + max(pad, cv2 꼬리, Qt 꼬리) — Qt 글꼴의 꼬리(descent)가 pad·cv2 꼬리보다 길면 그만큼 내려가 g·p·_의 Qt 꼬리가 상자
    안에 남음. 배치를 pad 1·cv2 꼬리 0으로 바꿔(video_widget이 읽는 overlay_layout을 바꿔치기) Qt 꼬리 항만 남김 — 단언은 글꼴과 상관없음(꼬리가
    1px 이하인 글꼴 — 예: 상자 글꼴은 0 — 이면 pad 1이 이김).

    깨지는 변경: 상자 아래에서 Qt 꼬리 항(ceil(descent))을 빼면 cv2 배치만 보는 상자가 Qt 글자의 꼬리를 자름."""
    import yesoncheck.video_widget as video_widget

    real_layout = video_widget.overlay_layout
    monkeypatch.setattr(video_widget, "overlay_layout",
                        lambda text, width, height: real_layout(text, width, height)._replace(pad=1, baseline=0))
    widget = player_with_fake_native.player.videoWidget
    width, height = 1920, 1080

    widget.set_overlay_text(f"File: clip_a.mov, Frame: 1/{TOTAL}", width, height)

    box, text = overlay_items(widget)
    fm = QFontMetricsF(text.font())
    y = height - overlay_metrics(width, height).margin_y
    assert box_rect(box).bottom() == y + max(1, math.ceil(fm.descent())) + 1
    assert box_rect(box).bottom() >= y + fm.descent()


def test_overlay_item_scales_with_frame_size(player_with_fake_native):
    """같은 글자를 4K로 두면 상자 높이·글자 높이가 1080p의 2배(±10%) — 창에 맞춰 보면 같은 크기(굽는 길과 같은 비례).

    깨지는 변경: 글꼴 크기를 프레임 크기와 상관없이 정하면(고정 픽셀) 4K에서 반 크기."""
    widget = player_with_fake_native.player.videoWidget
    label = f"File: clip_a.mov, Frame: 1/{TOTAL}"

    def measure(width, height):
        widget.set_overlay_text(label, width, height)
        box, text = overlay_items(widget)
        return box_rect(box).height(), text.boundingRect().height(), QFontMetricsF(text.font()).capHeight()

    hd, uhd = measure(1920, 1080), measure(3840, 2160)
    for small, big in zip(hd, uhd):
        assert big == pytest.approx(2 * small, rel=0.1)


@pytest.mark.parametrize("width, height, bold", [(1280, 720, False), (1920, 1080, True), (3840, 2160, True)])
def test_overlay_item_weight_follows_stroke_thickness(player_with_fake_native, width, height, bold):
    """굵기: overlay_metrics의 cv2 획이 3px 이상(1080p 3·4K 8)이면 Bold, 그보다 가늘면(720p 2) 보통 — 굽는 길의 굵기 느낌.

    깨지는 변경: 늘 Bold(또는 늘 보통)로 두면 720p(또는 1080p·4K)에서 틀림."""
    widget = player_with_fake_native.player.videoWidget
    assert (overlay_metrics(width, height).thickness >= 3) is bold
    widget.set_overlay_text(f"File: clip_a.mov, Frame: 1/{TOTAL}", width, height)
    _box, text = overlay_items(widget)
    assert text.font().bold() is bold


def test_overlay_item_shrinks_to_fit_narrow_frame(player_with_fake_native):
    """좁은 프레임(300×1080 — cv2 글자가 너비를 넘침): 굽는 길처럼 들어갈 만큼 줄임 — 글자 높이는 줄인 cv2 높이에 맞추고(상자 위·아래가 구운
    상자와 같은 픽셀), 상자는 왼쪽 여백과 같은 만큼 오른쪽 끝 앞에서 끝남(글자가 너비 − 2·margin_x 안).

    깨지는 변경: 줄이기 전의 cv2 높이로 글꼴·상자를 정하면 상자 위·아래가 구운 상자와 어긋나고 글자가 큼(Qt 폭 줄이기로만 맞춰져 대문자 높이가
    줄인 cv2 높이보다 큼). 대문자 높이는 위 한도만 봄 — Qt 글꼴이 Hershey보다 넓으면(예: 글꼴이 없는 Windows offscreen의 상자 글꼴) 더 줄어듦."""
    player = player_with_fake_native.player
    widget = player.videoWidget
    label = player.overlay_label()
    assert label == f"File: clip_a.mov, Frame: 1/{TOTAL}"
    width, height = 300, 1080
    m = overlay_metrics(width, height)
    room = width - 2 * m.margin_x
    # 줄이는 배율은 자리 잡을 글(가장 넓은 숫자 — Hershey는 숫자 폭이 같아 '0')로 정함: 프레임 번호가 바뀌어도 글자 크기가 그대로 (2026-11-09)
    reserve = overlay_reserve_text(label, widest_digit(lambda d: cv2.getTextSize(d, FONT, m.scale, m.thickness)[0][0]))
    (tw, _th), _base = cv2.getTextSize(reserve, FONT, m.scale, m.thickness)
    assert tw > room
    shrunk = m.scale * room / tw
    (_tw, th), base = cv2.getTextSize(label, FONT, shrunk, max(1, round(m.thickness * room / tw)))

    widget.set_overlay_text(label, width, height)

    box, text = overlay_items(widget)
    fm = QFontMetricsF(text.font())
    rect = box_rect(box)
    _left, top, _right, bottom = burned_box(player, width, height)
    assert fm.horizontalAdvance(label) <= room
    assert fm.capHeight() <= th * 1.1  # 줄인 cv2 높이에 맞춘 뒤, Qt 글꼴이 더 넓으면(글꼴마다 다름) 더 줄일 뿐 — 커지지는 않음
    assert rect.top() == height - m.margin_y - th - m.pad == top
    assert rect.bottom() == height - m.margin_y + max(m.pad, base, math.ceil(fm.descent())) + 1 >= bottom + 1
    assert rect.right() <= width - (m.margin_x - m.pad) + 1


def test_overlay_font_shrinks_when_qt_text_is_wider_than_room():
    """cv2 글자는 들어가는데 Qt 글꼴이 더 넓은 경우(글꼴마다 폭이 다름 — 예: 글꼴이 없는 Windows offscreen의 상자 글꼴): 글꼴을 들어갈 만큼 더 줄임.

    깨지는 변경: Qt 폭을 재지 않고 cv2 배치만 믿으면 글자가 오른쪽 끝을 넘음."""
    from yesoncheck.overlay_text_layout import overlay_layout
    from yesoncheck.video_widget import overlay_font

    label = f"File: clip_a.mov, Frame: 1/{TOTAL}"
    layout = overlay_layout(label, 1920, 1080)
    roomy = overlay_font(label, layout)
    assert QFontMetricsF(roomy).horizontalAdvance(label) > 100
    tight = overlay_font(label, layout._replace(room=100))
    assert QFontMetricsF(tight).horizontalAdvance(label) <= 100
    assert tight.pixelSize() < roomy.pixelSize()
