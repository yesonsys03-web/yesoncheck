"""N 키(한글 자판 ㅜ)로 가운데 컨트롤 열(middleScrollArea — Open Video A/B·OCR·주석·재생 설정·작품 콤보)을
보이고 숨긴다. V 키(컨트롤 전체 숨김/복원)나 전체화면 해제가 컨트롤을 복원해도 N으로 숨긴 열은 숨김을 유지한다.
키는 창(keyPressEvent)과 사이드바 목록이 포커스를 가질 때(eventFilter) 모두 먹어야 한다."""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def press(player, key, text=""):
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))


def test_n_key_toggles_middle_panel(player):
    assert not player.middleScrollArea.isHidden()
    press(player, Qt.Key_N, "n")
    assert player.middleScrollArea.isHidden()
    press(player, Qt.Key_N, "n")
    assert not player.middleScrollArea.isHidden()


def test_korean_u_text_toggles_middle_panel(player):
    press(player, Qt.Key_unknown, "ㅜ")  # 한글 자판의 N
    assert player.middleScrollArea.isHidden()
    press(player, Qt.Key_unknown, "ㅜ")
    assert not player.middleScrollArea.isHidden()


def test_n_key_works_when_sidebar_has_focus(player):
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_N, Qt.NoModifier, "n")
    assert player.eventFilter(player.sidebar, ev) is True
    assert player.middleScrollArea.isHidden()
    ev2 = QKeyEvent(QEvent.KeyPress, Qt.Key_N, Qt.NoModifier, "n")
    assert player.eventFilter(player.seq_sidebar, ev2) is True
    assert not player.middleScrollArea.isHidden()


def test_v_restore_keeps_hidden_middle_panel(player):
    press(player, Qt.Key_N, "n")  # 가운데 열 숨김
    press(player, Qt.Key_V, "v")  # 컨트롤 전체 숨김
    assert player.middleScrollArea.isHidden()
    press(player, Qt.Key_V, "v")  # 컨트롤 복원 — 가운데 열은 N 상태를 따름
    assert player.middleScrollArea.isHidden()
    press(player, Qt.Key_N, "n")
    assert not player.middleScrollArea.isHidden()


def test_fullscreen_restore_keeps_hidden_middle_panel(player):
    press(player, Qt.Key_N, "n")
    player.hide_all_ui_elements()
    player.restore_ui_elements()
    assert player.middleScrollArea.isHidden()


def test_other_control_widgets_untouched_by_n(player):
    press(player, Qt.Key_N, "n")
    assert not player.sidebar_tabs.isHidden()  # 왼쪽 파일 목록은 그대로
    assert not player.videoWidget.isHidden()
