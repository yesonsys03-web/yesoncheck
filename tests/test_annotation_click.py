"""주석 모드 클릭 동작: 텍스트 입력 요청은 '텍스트' 도구에서만 — 도형 도구(사각형·타원·선·화살표)에서
드래그 없는 클릭은 아무 주석도 만들지 않는다 (예전에는 사각형·타원 클릭이 텍스트 입력 폴백으로 갔음).
주석 모드 동안에는 비디오 영역 오른쪽 위에 '주석 모드' 배지가 보여, 접힌 주석 패널 밖에서도 모드가 켜진 것을 안다."""

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtTest import QTest

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.video_widget import CustomVideoWidget


@pytest.fixture
def widget(qapp):
    w = CustomVideoWidget()
    w.resize(400, 300)
    w.video_item.setPixmap(QPixmap(320, 240))
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def center_pos(widget):
    return widget.mapFromScene(widget.video_item.sceneBoundingRect().center())


def collect(signal):
    seen = []
    signal.connect(lambda *args: seen.append(args))
    return seen


# ---------------------------------------------------------------- 클릭 (드래그 없음)


@pytest.mark.parametrize("tool", ["rect", "ellipse", "line", "arrow"])
def test_shape_tool_click_adds_nothing(widget, tool):
    widget.enable_annotation_mode(True, tool=tool, color="#ff3333")
    texts = collect(widget.annotationTextRequested)
    shapes = collect(widget.annotationShapeFinished)

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, center_pos(widget))

    assert texts == []
    assert shapes == []


def test_shape_tool_click_with_jitter_adds_nothing(widget):
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    texts = collect(widget.annotationTextRequested)
    shapes = collect(widget.annotationShapeFinished)

    start = center_pos(widget)
    QTest.mousePress(widget.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseRelease(widget.viewport(), Qt.LeftButton, Qt.NoModifier, start + QPoint(1, 1))

    assert texts == []
    assert shapes == []


def test_text_tool_click_requests_text_input(widget):
    widget.enable_annotation_mode(True, tool="text", color="#ff3333")
    texts = collect(widget.annotationTextRequested)

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, center_pos(widget))

    assert len(texts) == 1
    norm_x, norm_y = texts[0]
    assert 0.0 <= norm_x <= 1.0 and 0.0 <= norm_y <= 1.0


def test_annotation_mode_off_click_adds_nothing(widget):
    texts = collect(widget.annotationTextRequested)
    shapes = collect(widget.annotationShapeFinished)

    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, center_pos(widget))

    assert texts == []
    assert shapes == []


# ---------------------------------------------------------------- 드래그 (실제 그리기는 그대로)


def test_shape_tool_drag_still_finishes_shape(widget):
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    shapes = collect(widget.annotationShapeFinished)

    start = center_pos(widget)
    end = start + QPoint(60, 40)
    QTest.mousePress(widget.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseRelease(widget.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    assert len(shapes) == 1
    payload = shapes[0][0]
    assert payload["type"] == "rect"
    assert abs(payload["norm_x2"] - payload["norm_x1"]) > 0.005


# ---------------------------------------------------------------- 주석 모드 버튼 켜짐 표시


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def mean_rgb(button):
    img = button.grab().toImage()
    r = g = b = n = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            r += c.red()
            g += c.green()
            b += c.blue()
            n += 1
    return (r // n, g // n, b // n)


def test_annotation_mode_button_turns_red_when_checked(player, qapp):
    btn = player.annotationModeButton
    player.filename_a = "dummy.mov"  # 파일 없음 경고가 모드를 되돌리지 않게
    base = mean_rgb(btn)

    btn.setChecked(True)
    qapp.processEvents()
    checked = mean_rgb(btn)
    # 켜짐: 빨강이 뚜렷이 우세 — 꺼진 모양과 한눈에 구분
    assert checked[0] - base[0] > 30
    assert checked[0] > checked[1] + 40 and checked[0] > checked[2] + 40

    # 밝은 테마에서도 같은 표시
    player.set_light_theme()
    qapp.processEvents()
    light_checked = mean_rgb(btn)
    assert light_checked[0] > light_checked[1] + 40 and light_checked[0] > light_checked[2] + 40
    player.set_dark_theme()
    qapp.processEvents()

    btn.setChecked(False)
    qapp.processEvents()
    assert mean_rgb(btn) == base


# ---------------------------------------------------------------- 주석 모드 배지


def test_badge_hidden_before_annotation_mode(widget):
    assert widget.annotation_mode_label.isHidden()


def test_badge_shown_while_annotation_mode_and_hidden_after(widget, qapp):
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    qapp.processEvents()
    assert not widget.annotation_mode_label.isHidden()
    assert widget.annotation_mode_label.text() == "주석 모드"

    widget.enable_annotation_mode(False)
    qapp.processEvents()
    assert widget.annotation_mode_label.isHidden()


def test_badge_sits_top_right_inside_widget(widget, qapp):
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    qapp.processEvents()
    label = widget.annotation_mode_label
    # 오른쪽 위 구석: 위젯 안에 있고, 오른쪽 절반에 10px 여백으로 붙어 있음 (10px 여백을 고정하려는 것은 아님)
    assert widget.rect().contains(label.geometry())
    assert label.geometry().left() > widget.width() // 2
    assert widget.width() - label.geometry().right() <= 20
    assert label.geometry().top() == 10

    widget.resize(600, 400)
    qapp.processEvents()
    assert widget.rect().contains(label.geometry())
    assert widget.width() - label.geometry().right() <= 20
    assert label.geometry().top() == 10


def test_badge_stays_after_tool_switch(widget, qapp):
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    widget.enable_annotation_mode(True, tool="ellipse", color="#ff3333")
    qapp.processEvents()
    assert not widget.annotation_mode_label.isHidden()


def test_badge_does_not_block_drawing_under_it(widget, qapp):
    widget.video_item.setPixmap(QPixmap(800, 600))
    widget.fit_to_window()
    widget.enable_annotation_mode(True, tool="rect", color="#ff3333")
    qapp.processEvents()
    shapes = collect(widget.annotationShapeFinished)

    # 창 핸들로 실제 이벤트를 보내 Qt의 히트 테스트까지 지킴 — 배지 위에서 시작한 드래그도 그려져야 함
    start = widget.annotation_mode_label.geometry().center()
    end = start + QPoint(-120, 120)
    win = widget.windowHandle()
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(win, end)
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, end)

    assert len(shapes) == 1
