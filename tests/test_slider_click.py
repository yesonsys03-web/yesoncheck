"""Windows 전용 버그 회귀 시험: 시간 슬라이더의 핸들을 드래그·클릭할 수 없던 문제.

근본 원인 (컨트롤러가 macOS에서 offscreen으로, 실제 스타일시트를 적용해 측정):
player_base.py의 positionScroll(QSlider, 약 646줄)에 최종 스타일시트(약 1070줄)가
"QSlider::handle:horizontal { min-width: 80px; max-width: 80px; ... }"로 적용되면
style().subControlRect(CC_Slider, opt, SC_SliderHandle)의 폭이 macintosh/Fusion/
Windows 스타일 전부에서 -1이 된다 — 잡을 핸들이 없다.

macOS는 QStyle.SH_Slider_AbsoluteSetButtons가 5(Qt.LeftButton | Qt.MiddleButton)라서
왼쪽 클릭이 그 위치로 바로 이동하고 그 자리에서 드래그가 이어지므로 버그가 가려진다.
Fusion/Windows는 4(Qt.MiddleButton만)라서 왼쪽 클릭은 pageStep(positionScroll은 1)만큼만
움직인다 — 거의 안 움직이는 것처럼 보이고, 드래그도 할 수 없다.

고치는 방법(yesoncheck.slider_style.jump_to_click): QProxyStyle로
SH_Slider_AbsoluteSetButtons 힌트만 Mac과 같게 바꿔 모든 플랫폼에서 '클릭 위치로 이동 +
드래그 계속'이 되게 한다. 스타일시트나 핸들 생김새는 그대로 둔다.

이 시험은 macOS 위에서도 app 스타일을 Fusion으로 강제해 Windows의 버그를 그대로
재현한다 (forced_fusion_style). QTest.mouseMove는 이 offscreen 테스트 환경에서 버튼
상태를 제대로 들고 다니지 않아 직접 QMouseEvent를 만들어 보낸다 (아래 _send_drag_move).
"""

import os

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QSlider, QStyle, QStyleFactory, QStyleOptionSlider

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.slider_style import jump_to_click


def _absolute_set_buttons(slider):
    opt = QStyleOptionSlider()
    slider.initStyleOption(opt)
    return int(slider.style().styleHint(QStyle.SH_Slider_AbsoluteSetButtons, opt, slider))


def _send_drag_move(slider, pos):
    """왼쪽 버튼을 누른 채로 pos로 움직이는 MouseMove를 직접 보냄.

    QTest.mouseMove()는 이 offscreen 하네스에서 버튼이 눌린 상태를 widget까지
    전달하지 못해(버튼 없이 움직인 것처럼 보여) QSlider가 드래그로 인식하지 못한다.
    """
    event = QMouseEvent(
        QMouseEvent.MouseMove, pos, slider.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(slider, event)
    QApplication.processEvents()


@pytest.fixture
def forced_fusion_style(qapp):
    """app 스타일을 Fusion으로 강제 — Windows처럼 SH_Slider_AbsoluteSetButtons가 Middle뿐인
    상태를 macOS에서도 그대로 재현한다. 다른 시험에 새지 않도록 끝나면 원래 스타일로 되돌림."""
    original = QApplication.style().objectName()
    QApplication.setStyle(QStyleFactory.create("Fusion"))
    yield
    QApplication.setStyle(QStyleFactory.create(original))


@pytest.fixture
def real_position_scroll_stylesheet(new_player, dialogs, tmp_path):
    """player_base.py가 positionScroll에 실제로 적용하는 최종 스타일시트(약 1070줄) 원문을
    그대로 가져온다 (베껴 쓰면 나중에 실제 코드와 어긋날 수 있으므로 실제 플레이어에서 읽음)."""
    player = new_player(make_config(str(tmp_path), {}))
    css = player.positionScroll.styleSheet()
    assert "QSlider::handle:horizontal" in css and "80px" in css  # 버그 재현 조건(핸들 폭 고정) 확인
    return css


@pytest.fixture
def bare_slider(forced_fusion_style, real_position_scroll_stylesheet):
    """1000px 너비, 범위 0-34, 실제 positionScroll 스타일시트 + singleStep/pageStep=1
    (player_base.py와 동일) 로 Windows의 버그를 그대로 가진 슬라이더를 만든다."""
    slider = QSlider(Qt.Horizontal)
    slider.setMinimum(0)
    slider.setMaximum(34)
    slider.setSingleStep(1)
    slider.setPageStep(1)
    slider.setStyle(QStyleFactory.create("Fusion"))
    slider.setStyleSheet(real_position_scroll_stylesheet)
    slider.resize(1000, 30)
    slider.show()
    QTest.qWaitForWindowExposed(slider)
    yield slider
    slider.close()


def test_without_fix_left_click_barely_moves_the_value(bare_slider):
    """고치기 전 상태(증거): Fusion에서는 AbsoluteSetButtons가 Middle뿐이라 왼쪽 클릭이
    그 위치로 가지 않고 pageStep(1)만큼만 움직인다 — Windows에서 보고된 '10 -> 11' 그대로."""
    slider = bare_slider
    assert _absolute_set_buttons(slider) == int(Qt.MiddleButton)
    slider.setValue(10)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(900, slider.height() // 2))
    QApplication.processEvents()
    assert slider.value() == 11  # pageStep=1: 거의 안 움직임 (버그 그대로, 고치기 전 증거)


def test_jump_to_click_makes_left_click_jump_to_position(bare_slider):
    """RED -> GREEN: jump_to_click 적용 후에는 x=900/1000, 범위 0-34에서 31 근처로 바로 이동."""
    slider = bare_slider
    jump_to_click(slider)
    assert _absolute_set_buttons(slider) == int(Qt.LeftButton | Qt.MiddleButton)

    slider.setValue(10)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(900, slider.height() // 2))
    QApplication.processEvents()
    assert abs(slider.value() - 31) <= 1


def test_without_fix_press_and_move_do_not_drag(bare_slider):
    """고치기 전 상태(증거): press해도 handle을 잡지 못해(isSliderDown=False) 움직여도
    sliderMoved가 전혀 발생하지 않는다 — '드래그가 안 됨' 그대로."""
    slider = bare_slider
    moved_values = []
    slider.sliderMoved.connect(moved_values.append)

    y = slider.height() // 2
    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.5), y))
    QApplication.processEvents()
    assert slider.isSliderDown() is False
    _send_drag_move(slider, QPoint(int(slider.width() * 0.8), y))
    QTest.mouseRelease(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.8), y))
    QApplication.processEvents()

    assert moved_values == []  # 드래그가 전혀 안 됨 (고치기 전 증거)


def test_jump_to_click_allows_drag_to_release_position(bare_slider):
    """RED -> GREEN: press 50% -> move 80% -> release. sliderMoved/sliderReleased 모두
    발생하고, 최종값은 80% 근처가 된다."""
    slider = bare_slider
    jump_to_click(slider)

    moved_values = []
    released = []
    slider.sliderMoved.connect(moved_values.append)
    slider.sliderReleased.connect(lambda: released.append(True))

    y = slider.height() // 2
    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.5), y))
    QApplication.processEvents()
    assert slider.isSliderDown() is True  # 클릭한 자리에서 바로 핸들을 잡은 상태가 돼야 함

    _send_drag_move(slider, QPoint(int(slider.width() * 0.8), y))
    QTest.mouseRelease(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.8), y))
    QApplication.processEvents()

    assert moved_values, "sliderMoved가 한 번도 발생하지 않음 — 드래그가 안 됨"
    assert released == [True]
    expected = round(0.8 * slider.maximum())
    assert abs(slider.value() - expected) <= 1


def test_jump_to_click_only_changes_absolute_set_buttons_hint(bare_slider):
    """다른 styleHint는 그대로 base style(Fusion)에 위임되는지 확인 (부작용 없음)."""
    slider = bare_slider
    before = int(slider.style().styleHint(QStyle.SH_Slider_PageSetButtons))
    jump_to_click(slider)
    after = int(slider.style().styleHint(QStyle.SH_Slider_PageSetButtons))
    assert before == after  # 건드리지 않은 힌트는 base style 값 그대로 유지


def test_jump_to_click_preserves_stylesheet(bare_slider):
    """스타일시트(핸들 생김새)는 손대지 않는지 확인 — 글자 그대로 동일해야 함."""
    slider = bare_slider
    css_before = slider.styleSheet()
    jump_to_click(slider)
    assert slider.styleSheet() == css_before


def test_real_video_player_position_scroll_click_seeks_and_updates_label(
    forced_fusion_style, new_player, dialogs, tmp_path
):
    """실제 VideoPlayer: positionScroll을 오른쪽 끝 근처로 클릭하면 실제로 그 프레임으로
    이동(seek)하고 화면의 'Current' 라벨이 바뀐다 — 수정 전에는 pageStep(1)만큼만 움직여서
    '안 움직이는 것처럼' 보였던 바로 그 경로. (프로덕션 배선: player_base.py가 __init__에서
    jump_to_click(self.positionScroll)을 호출해야 이 시험이 통과한다.)"""
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1200, 800)
    player.show()
    QTest.qWaitForWindowExposed(player)
    QApplication.processEvents()

    video = write_test_video(os.path.join(str(tmp_path), "v", "a.mp4"), frames=24)
    player.open_file("A", video)
    QApplication.processEvents()

    slider = player.positionScroll
    assert slider.maximum() == 23  # 24프레임 -> 0-based 최댓값
    assert player.labelFrameCount.text() == "Current: 1"

    QTest.mouseClick(
        slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.95), slider.height() // 2)
    )
    QApplication.processEvents()

    assert slider.value() == slider.maximum()
    assert player.labelFrameCount.text() == "Current: 24"


def test_real_video_player_overlay_and_review_sliders_also_get_the_fix(
    forced_fusion_style, new_player, dialogs, tmp_path
):
    """overlaySlider(player_base.py)와 OCR 검토창의 frame_slider(player_review.py)에도
    같은 수정이 적용돼 있는지 확인 (styleHint로 확인; 무거운 영상·세그먼트 준비는 생략)."""
    player = new_player(make_config(str(tmp_path), {}))
    assert _absolute_set_buttons(player.overlaySlider) == int(Qt.LeftButton | Qt.MiddleButton)

    from yesoncheck.player_review import OCRReviewDialog

    dialog = OCRReviewDialog(player, [], fps=24.0, total_frames=10)
    try:
        assert _absolute_set_buttons(dialog.frame_slider) == int(Qt.LeftButton | Qt.MiddleButton)
    finally:
        dialog.close()
