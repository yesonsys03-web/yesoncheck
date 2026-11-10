"""슬라이더 호버 썸네일의 화면 쪽 (yesoncheck/slider_preview.py) — 마우스 x → 슬라이더 값 변환·커서 위 창·필터.

슬라이더는 실제 시트(메인 POSITION_SCROLL_INITIAL_STYLE·오버레이 OVERLAY_SLIDER_STYLE)와 jump_to_click을 적용해 핸들 폭 -1 같은
실제 지오메트리를 그대로 재현한다 (test_slider_click.py와 같은 방법). 마우스 이벤트는 offscreen 하네스라 QTest.mouseMove 대신
QMouseEvent·QEnterEvent를 직접 만들어 QApplication.sendEvent로 보낸다 (QTest.mouseMove는 버튼 상태를 들고 가지 않음).
"""

import numpy as np
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QEnterEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMainWindow, QSlider

from yesoncheck import error_window, slider_preview
from yesoncheck.hover_strip import LOG_PREFIX
from yesoncheck.main_window_styles import (
    DARK_STYLESHEET,
    LIGHT_STYLESHEET,
    OVERLAY_SLIDER_STYLE,
    POSITION_SCROLL_INITIAL_STYLE,
)
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


def test_popup_with_parent_is_a_tooltip_window_owned_by_it(qapp):
    """parent를 주면 그 창이 가지지만(창이 지워지면 함께 지워짐 — 종료 순서) 여전히 따로 뜨는 ToolTip 최상위 창이고, place_above는 그대로
    화면 좌표로 놓는다 (커서 x에 가로 가운데, 아래 끝은 슬라이더 위 끝에서 GAP 위)."""
    window = QMainWindow()
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, MAX_VALUE)
    window.setCentralWidget(slider)
    window.resize(700, 120)
    window.move(40, 400)
    window.show()
    QTest.qWaitForWindowExposed(window)
    popup = SliderPreviewPopup(320, 180, parent=window)
    assert popup.parent() is window and popup.isWindow() and popup.windowFlags() & Qt.ToolTip

    popup.show_frame("7", None)
    popup.place_above(slider, 350)
    popup.show()
    qapp.processEvents()
    slider_top_left = slider.mapToGlobal(QPoint(0, 0))
    assert popup.x() == slider.mapToGlobal(QPoint(350, 0)).x() - popup.width() // 2
    assert popup.y() == slider_top_left.y() - GAP - popup.height()

    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(window) and sip.isdeleted(popup)


@pytest.mark.parametrize("sheet", [DARK_STYLESHEET, LIGHT_STYLESHEET], ids=["dark", "light"])
def test_popup_keeps_its_look_under_a_themed_parent(qapp, sheet):
    """parent 창의 테마 시트가 내려와도 창의 모양(배경·테두리·번호의 색·크기·굵기)은 이 창의 시트 그대로 — 어두운·밝은 테마 모두 같은 어두운 창."""
    window = QMainWindow()
    window.setStyleSheet(sheet)
    window.show()
    QTest.qWaitForWindowExposed(window)
    popup = SliderPreviewPopup(320, 180, parent=window)
    try:
        popup.show_frame("12", None)
        popup.show()
        qapp.processEvents()
        image = popup.grab().toImage()
        assert (image.pixelColor(0, 0).name(), image.pixelColor(3, 3).name()) == ("#8a8a8a", "#1e1e1e")  # 테두리·배경
        number = popup.number_label
        assert number.palette().color(number.foregroundRole()).name() == "#ffffff"
        assert number.font().pixelSize() == 22 and number.font().bold()
    finally:
        window.close()


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


def test_place_above_uses_the_screen_under_the_cursor(qapp, styled_slider, popup, monkeypatch):
    """모니터가 둘이면 창은 커서가 있는 화면 안으로 밈 — slider.screen()은 앱 창이 속한 화면 하나라, 창이 두 화면에 걸쳐 있으면 커서 쪽 화면과
    다를 수 있음. offscreen은 화면이 하나라 QGuiApplication.screenAt을 바꿔치기: 커서 자리(슬라이더 세로 가운데)를 받아 다른 화면을 돌려주면 그
    화면의 쓸 수 있는 영역으로, None(어느 화면에도 없음)이면 slider.screen()으로."""
    slider = styled_slider("main")
    slider.move(0, 400)
    qapp.processEvents()
    asked = []

    class _LeftScreen:  # 슬라이더 왼쪽의 다른 화면 (가로 -1000..-1)
        @staticmethod
        def availableGeometry():
            return QRect(-1000, 0, 1000, 2000)

    answer = {"screen": _LeftScreen()}

    class _Gui:
        @staticmethod
        def screenAt(point):
            asked.append(QPoint(point))
            return answer["screen"]

    monkeypatch.setattr(slider_preview, "QGuiApplication", _Gui)
    popup.place_above(slider, 450)
    assert asked == [slider.mapToGlobal(QPoint(450, slider.height() // 2))]
    assert popup.x() + popup.width() == 0  # 그 화면의 오른쪽 끝(-1)까지 밀림 — slider.screen()의 영역이 아님

    answer["screen"] = None
    popup.place_above(slider, 450)
    assert popup.x() == slider.mapToGlobal(QPoint(450, 0)).x() - popup.width() // 2  # slider.screen() 안 — 커서에 가운데 맞춤


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


def test_filter_redraws_only_when_the_frame_changes(qapp, styled_slider, popup, monkeypatch):
    """MouseMove마다 다시 그리지 않음 — (번호 글, 그림 데이터의 주소)가 앞과 같고 창이 떠 있으면 show_frame(QImage 복사·adjustSize)을 건너뛰고
    자리만 옮김. 띠의 image(i)는 부를 때마다 새 뷰 객체라 객체가 아니라 데이터 주소로 비교. 빈 상자 → 그림(그 장이 채워짐)·다른 프레임·창이
    숨은 뒤에는 다시 그림."""
    slider = styled_slider("main")
    frames = np.zeros((MAX_VALUE // 10 + 1, 180, 320, 3), np.uint8)
    filled = set()

    def lookup(value):  # 슬라이더 값 10칸이 한 프레임 — 띠처럼 부를 때마다 새 뷰 (같은 행이면 같은 주소)
        frame = value // 10
        return str(frame + 1), (frames[frame] if frame in filled else None)

    drawn, placed = [], []
    real_show_frame, real_place_above = popup.show_frame, popup.place_above

    def counting_show_frame(number_text, image):
        drawn.append(number_text)
        real_show_frame(number_text, image)

    def counting_place_above(target, x):
        placed.append(x)
        real_place_above(target, x)

    monkeypatch.setattr(popup, "show_frame", counting_show_frame)
    monkeypatch.setattr(popup, "place_above", counting_place_above)
    hover = SliderHoverFilter(slider, lookup, popup, slider)
    x = 450
    frame = slider_value_at(slider, x) // 10

    _send_move(slider, x)
    _send_move(slider, x)
    assert drawn == [str(frame + 1)] and placed == [x, x] and popup.isVisible()  # 두 번째는 자리만

    filled.add(frame)  # 띠가 그 장을 채움 → 같은 x라도 그림이 생겼으니 다시 그림
    _send_move(slider, x)
    _send_move(slider, x)
    assert drawn == [str(frame + 1)] * 2 and popup.image_label.pixmap().width() == 320

    far = 100
    _send_move(slider, far)  # 다른 프레임
    assert len(drawn) == 3 and drawn[-1] == str(slider_value_at(slider, far) // 10 + 1)

    _send_plain(slider, QEvent.Leave)  # 숨은 뒤에는 같은 자리라도 다시 그림 (그동안 다른 쪽이 창을 바꿨을 수 있음)
    _send_move(slider, far)
    assert len(drawn) == 4 and popup.isVisible()
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


def test_filter_reports_lookup_exception(qapp, styled_slider, popup, monkeypatch, capsys):
    """lookup이 던지면 창을 숨기고 처음 한 번은 report_from_handler(트레이스백 기록 + 오류 창), 그 뒤로는 창 없이 기록 한 줄씩 — 호버는 마우스가
    움직일 때마다 불려 lookup 버그 하나로 창이 쌓이면 안 되지만, 조용히 넘기지도 않음. 예외는 밖으로 나가지 않음(qFatal 회피)."""
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
    assert reports == [(LOG_PREFIX, "슬라이더 호버 처리 중 오류", boom)]
    assert popup.isVisible() is False  # 낡은 그림이 남지 않음
    capsys.readouterr()

    _send_move(slider, 460)  # Qt 이벤트 경로로도 프로세스가 죽지 않음
    _send_move(slider, 470)
    assert len(reports) == 1  # 창은 처음 한 번만
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith(LOG_PREFIX)]
    assert len(lines) == 2 and all("슬라이더 호버 처리 중 오류" in line and "RuntimeError: lookup 실패" in line for line in lines)
    assert popup.isVisible() is False
    del hover
