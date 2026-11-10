"""슬라이더 호버 썸네일의 화면 쪽 (yesoncheck/slider_preview.py) — 마우스 x → 슬라이더 값 변환·커서 위 창·필터.

슬라이더는 실제 시트(메인 POSITION_SCROLL_INITIAL_STYLE·오버레이 OVERLAY_SLIDER_STYLE)와 jump_to_click을 적용해 핸들 폭 -1 같은
실제 지오메트리를 그대로 재현한다 (test_slider_click.py와 같은 방법). 마우스 이벤트는 offscreen 하네스라 QTest.mouseMove 대신
QMouseEvent·QEnterEvent를 직접 만들어 QApplication.sendEvent로 보낸다 (QTest.mouseMove는 버튼 상태를 들고 가지 않음).
"""

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QEnterEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QSlider

from yesoncheck import error_window
from yesoncheck.main_window_styles import OVERLAY_SLIDER_STYLE, POSITION_SCROLL_INITIAL_STYLE
from yesoncheck.slider_preview import GAP, SliderHoverFilter, SliderPreviewPopup, slider_value_at
from yesoncheck.slider_style import jump_to_click

SHEETS = {"main": POSITION_SCROLL_INITIAL_STYLE, "overlay": OVERLAY_SLIDER_STYLE}
SLIDER_WIDTH = 900
MAX_VALUE = 333


@pytest.fixture
def styled_slider(qapp):
    """styled_slider("main" | "overlay") → 실제 시트 + jump_to_click + 범위 0..333 + 폭 900으로 띄운 독립 슬라이더. 시험이 끝나면 닫음."""
    made = []

    def make(name):
        slider = QSlider(Qt.Horizontal)
        slider.setStyleSheet(SHEETS[name])
        jump_to_click(slider)
        slider.setRange(0, MAX_VALUE)
        slider.resize(SLIDER_WIDTH, 40)
        slider.show()
        QTest.qWaitForWindowExposed(slider)
        qapp.processEvents()
        assert slider.width() == SLIDER_WIDTH  # 지오메트리가 진짜인지 (offscreen 화면 800보다 넓어도 그대로)
        made.append(slider)
        return slider

    yield make
    for slider in made:
        slider.close()


@pytest.fixture
def popup(qapp):
    window = SliderPreviewPopup(320, 180)
    yield window
    window.close()


def _y(slider):
    return slider.height() // 2


def _send_enter(slider, x):
    pos = QPointF(x, _y(slider))
    QApplication.sendEvent(slider, QEnterEvent(pos, pos, QPointF(slider.mapToGlobal(pos.toPoint()))))
    QApplication.processEvents()


def _send_move(slider, x):
    pos = QPoint(x, _y(slider))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(slider.mapToGlobal(pos)), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(slider, event)
    QApplication.processEvents()


def _send_plain(widget, event_type):
    QApplication.sendEvent(widget, QEvent(event_type))
    QApplication.processEvents()


# ---------------------------------------------------------------- 마우스 x → 슬라이더 값


@pytest.mark.parametrize("style_name", ["main", "overlay"])
def test_value_at_matches_click_landing(qapp, styled_slider, style_name):
    """모든 x(3칸 간격)에서 slider_value_at이 Qt가 클릭으로 착지시키는 값과 같다 (핸들 폭 -1 보정 없이 Qt 식 그대로의 증거)."""
    slider = styled_slider(style_name)
    mismatches = []
    for x in range(0, slider.width(), 3):
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(x, slider.height() // 2))
        qapp.processEvents()
        if slider_value_at(slider, x) != slider.value():
            mismatches.append(x)
    assert mismatches == []


@pytest.mark.parametrize("style_name", ["main", "overlay"])
def test_value_at_clamps_outside_and_never_goes_back(qapp, styled_slider, style_name):
    slider = styled_slider(style_name)
    assert slider_value_at(slider, -500) == 0
    assert slider_value_at(slider, SLIDER_WIDTH + 500) == MAX_VALUE
    values = [slider_value_at(slider, x) for x in range(0, SLIDER_WIDTH)]
    assert values == sorted(values)
    assert len(set(values)) > MAX_VALUE // 2  # 전부 한 값이 아님 — 폭에 걸쳐 고르게 퍼짐


# ---------------------------------------------------------------- 커서 위 창


def test_popup_shows_number_and_image(qapp, popup):
    popup.show_frame("12", np.full((180, 320, 3), 200, np.uint8))
    assert popup.number_label.text() == "12"
    pixmap = popup.image_label.pixmap()
    assert (pixmap.width(), pixmap.height()) == (320, 180)
    color = pixmap.toImage().pixelColor(5, 5)
    assert (color.red(), color.green(), color.blue()) == (200, 200, 200)

    popup.show_frame("13", None)  # 빈 상자: 그림만 비우고 크기·번호는 그대로
    assert popup.number_label.text() == "13"
    assert popup.image_label.pixmap() is None or popup.image_label.pixmap().isNull()
    assert (popup.image_label.width(), popup.image_label.height()) == (320, 180)


def test_popup_copies_the_array_before_another_thread_overwrites_it(qapp, popup):
    array = np.full((180, 320, 3), 200, np.uint8)
    popup.show_frame("1", array)
    array[:] = 0  # 띠 워커가 같은 버퍼에 쓰는 경우
    color = popup.image_label.pixmap().toImage().pixelColor(5, 5)
    assert (color.red(), color.green(), color.blue()) == (200, 200, 200)


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((180, 320), np.uint8),  # 채널 없음
        np.zeros((180, 320, 4), np.uint8),  # RGBA
        np.zeros((180, 320, 3), np.float32),  # uint8 아님
        np.zeros((180, 640, 3), np.uint8)[:, ::2],  # 연속이 아닌 보기
    ],
)
def test_popup_rejects_arrays_that_are_not_contiguous_rgb_uint8(qapp, popup, bad):
    popup.show_frame("keep", np.full((180, 320, 3), 50, np.uint8))
    with pytest.raises(ValueError):
        popup.show_frame("1", bad)
    assert popup.number_label.text() == "keep"  # 검사가 먼저: 거부된 호출은 번호도 그림도 바꾸지 않음
    assert popup.image_label.pixmap().toImage().pixelColor(5, 5).red() == 50


def test_popup_set_thumb_size_resizes_for_a_new_plan(qapp, popup):
    popup.show()
    wide = (popup.width(), popup.height())
    popup.set_thumb_size(180, 320)  # 세로 영상 계획
    assert (popup.image_label.width(), popup.image_label.height()) == (180, 320)
    assert popup.width() < wide[0] and popup.height() > wide[1]
    popup.show_frame("5", np.zeros((320, 180, 3), np.uint8))
    assert (popup.image_label.pixmap().width(), popup.image_label.pixmap().height()) == (180, 320)


def test_popup_resizes_to_fit_a_wider_number_text(qapp, styled_slider):
    """번호 글이 그림 폭보다 넓으면 show_frame에서 창이 늘고 (place_above·show 사이에 크기가 안 변해 가운데 맞춤이 유지됨), 짧은 글이면 다시 줄어든다."""
    slider = styled_slider("main")
    slider.move(0, 400)
    qapp.processEvents()
    window = SliderPreviewPopup(180, 320)  # 세로 영상 계획: 그림 폭 180
    try:
        narrow = window.width()
        window.show_frame("28800 / 28800 / 28800 / 28800", None)  # 그림 폭(180)보다 넓은 글
        assert window.width() > narrow
        window.place_above(slider, 450)
        placed = (window.x(), window.width())
        window.show()
        qapp.processEvents()
        assert (window.x(), window.width()) == placed  # 첫 show에서 창이 더 늘며 어긋나지 않음
        assert window.x() == slider.mapToGlobal(QPoint(450, 0)).x() - window.width() // 2  # 가운데 맞춤 유지

        window.show_frame("1", None)
        assert window.width() == narrow  # 한 번 늘어난 창이 줄지 않고 남지 않음
    finally:
        window.close()


def test_popup_never_takes_focus(qapp, popup):
    assert popup.windowType() == Qt.ToolTip
    assert popup.windowFlags() & Qt.FramelessWindowHint
    assert popup.testAttribute(Qt.WA_ShowWithoutActivating)
    assert popup.focusPolicy() == Qt.NoFocus
    popup.show()
    qapp.processEvents()
    assert qapp.activeWindow() is not popup


def test_place_above_clamps_to_screen(qapp, styled_slider, popup):
    slider = styled_slider("main")
    slider.move(0, 400)  # 위에 창이 들어갈 만큼 아래로
    qapp.processEvents()
    available = slider.screen().availableGeometry()
    slider_top = slider.mapToGlobal(QPoint(0, 0)).y()

    popup.place_above(slider, 450)  # 가운데: 커서 x에 가로 가운데, 아래 끝 = 슬라이더 위 − GAP
    cursor_x = slider.mapToGlobal(QPoint(450, 0)).x()
    assert popup.x() == cursor_x - popup.width() // 2
    assert popup.y() + popup.height() == slider_top - GAP

    popup.place_above(slider, 0)
    assert popup.x() >= available.left()
    popup.place_above(slider, slider.width())
    assert popup.x() + popup.width() - 1 <= available.right()
    assert popup.x() > available.left()  # 오른쪽 끝에서 밀렸을 뿐 왼쪽 끝으로 날아가지 않음
    assert popup.y() + popup.height() - 1 < slider_top  # 슬라이더 위에 있음


def test_place_below_when_there_is_no_room_above(qapp, styled_slider, popup):
    slider = styled_slider("main")
    slider.move(0, 0)  # 화면 맨 위: 위가 모자람
    qapp.processEvents()
    slider_top = slider.mapToGlobal(QPoint(0, 0)).y()

    popup.place_above(slider, 450)
    assert popup.y() == slider_top + slider.height() + GAP


# ---------------------------------------------------------------- 필터


def test_filter_shows_hides_and_calls_lookup(qapp, styled_slider, popup):
    slider = styled_slider("main")
    seen = []

    def lookup(value):
        seen.append(value)
        return (f"n{value}", np.full((180, 320, 3), 90, np.uint8))

    hover = SliderHoverFilter(slider, lookup, popup, slider)
    assert slider.hasMouseTracking()

    x = 450
    _send_enter(slider, x)
    _send_move(slider, x)
    assert popup.isVisible()
    assert seen and seen[-1] == slider_value_at(slider, x)  # 슬라이더 값을 받음 (프레임 변환은 부른 쪽)
    assert popup.number_label.text() == f"n{seen[-1]}"
    assert popup.image_label.pixmap().width() == 320

    _send_plain(slider, QEvent.Leave)
    assert not popup.isVisible()

    _send_move(slider, 600)
    assert popup.isVisible() and seen[-1] == slider_value_at(slider, 600)
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(600, _y(slider)))
    assert not popup.isVisible()
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(600, _y(slider)))
    qapp.processEvents()

    _send_move(slider, 300)
    assert popup.isVisible()
    slider.hide()  # 슬라이더가 숨으면 창도 (탭·창 전환)
    qapp.processEvents()
    assert not popup.isVisible()
    del hover


def test_filter_hides_popup_when_the_window_deactivates(qapp, styled_slider, popup):
    slider = styled_slider("main")
    hover = SliderHoverFilter(slider, lambda value: (str(value), None), popup, slider)
    _send_move(slider, 450)
    assert popup.isVisible()
    _send_plain(slider.window(), QEvent.WindowDeactivate)
    assert not popup.isVisible()
    del hover


def test_filter_lookup_none_means_hidden(qapp, styled_slider, popup):
    slider = styled_slider("main")
    answer = {"now": ("7", None)}
    hover = SliderHoverFilter(slider, lambda value: answer["now"], popup, slider)
    _send_move(slider, 450)
    assert popup.isVisible()  # 그림 없이 번호만 (빈 상자)
    answer["now"] = None
    _send_move(slider, 460)
    assert not popup.isVisible()
    _send_move(slider, 470)
    assert not popup.isVisible()  # 처음부터 None이어도 보이지 않음
    del hover


def test_filter_hides_while_slider_down(qapp, styled_slider, popup):
    slider = styled_slider("main")
    hover = SliderHoverFilter(slider, lambda value: (str(value), None), popup, slider)
    _send_move(slider, 450)
    assert popup.isVisible()
    slider.setSliderDown(True)
    _send_move(slider, 460)
    assert not popup.isVisible()
    _send_enter(slider, 470)
    assert not popup.isVisible()
    slider.setSliderDown(False)
    _send_move(slider, 480)
    assert popup.isVisible()
    del hover


def test_filter_returns_false_so_the_slider_still_handles_events(qapp, styled_slider, popup):
    slider = styled_slider("main")
    hover = SliderHoverFilter(slider, lambda value: ("1", None), popup, slider)
    pos = QPoint(450, _y(slider))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(slider.mapToGlobal(pos)), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    assert hover.eventFilter(slider, event) is False
    QTest.mouseClick(slider, Qt.LeftButton, pos=pos)  # 필터가 삼키지 않음: 클릭은 그대로 값을 옮김
    qapp.processEvents()
    assert slider.value() == slider_value_at(slider, 450)
    del hover


def test_filter_reports_lookup_exception(qapp, styled_slider, popup, monkeypatch):
    import sys

    slider = styled_slider("main")
    reports = []

    def fake_report(prefix, context):
        reports.append((prefix, context, sys.exc_info()[1]))  # except 블록 안에서 불렸는지(처리 중인 예외가 있는지)도 봄

    monkeypatch.setattr(error_window, "report_from_handler", fake_report)
    boom = RuntimeError("lookup 실패")

    failing = {"now": False}

    def lookup(value):
        if failing["now"]:
            raise boom
        return ("3", None)

    hover = SliderHoverFilter(slider, lookup, popup, slider)
    _send_move(slider, 440)
    assert popup.isVisible()  # 앞의 호버로 창이 떠 있는 상태에서 lookup이 실패
    failing["now"] = True
    pos = QPoint(450, _y(slider))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(slider.mapToGlobal(pos)), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    assert hover.eventFilter(slider, event) is False  # 예외가 밖으로 안 나가고 기본 처리 그대로
    assert reports == [("[슬라이더 썸네일]", "슬라이더 호버 처리 중 오류", boom)]
    assert popup.isVisible() is False  # 낡은 그림이 남지 않음

    _send_move(slider, 460)  # Qt 이벤트 경로로도 프로세스가 죽지 않음
    assert len(reports) == 2
    assert popup.isVisible() is False
    del hover
