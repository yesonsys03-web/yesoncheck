"""B로 열면 와이프까지 (사용자 결정 2026-11-20 — 사이드바 A·B 단추와 함께): B를 여는 길(] 키·Mov·Seq 우클릭·File 메뉴)이 모두
player.open_b_and_wipe 하나를 부르고, 연 경우에만 와이프를 켜고 X·Y가 둘 다 꺼져 있으면 X(좌우)를 켬 — 한 번에 A|B 비교 화면.
이미 켜 둔 와이프의 축은 그대로, 열지 못하면(없는 파일·파일 창 취소) 와이프를 켜지 않음, 와이프를 끄면 B를 닫는 규칙(11-18)은 그대로.
"""

import cv2
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog

from tests.test_sidebar_keys import key_event, select, seq_tab
from tests.test_sidebar_open_with import find_action, folder, menus, mov_item, right_click  # noqa: F401 (fixtures)
from tests.test_sidebar_seq_tab import seq_item
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import ui_text


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def loaded(player, folder, qapp):  # noqa: F811
    """tk1.mov를 A로 연 채 (목록에는 tk1.mov·tk3.mov와 시퀀스 tk1·tk2), 와이프는 꺼진 채."""
    drop_folder(player, "video", folder)
    assert player.open_file("A", str(folder / "tk1.mov"))
    player.wipeCheckBox.setChecked(False)
    qapp.processEvents()
    return player


def wipe_state(player):
    return player.wipeCheckBox.isChecked(), player.wipeXButton.isChecked(), player.wipeYButton.isChecked()


def test_open_b_turns_on_wipe_and_x(loaded, folder):  # noqa: F811
    assert loaded.open_b_and_wipe(str(folder / "tk3.mov")) is True
    assert wipe_state(loaded) == (True, True, False)
    assert loaded.videoWidget.wipe_enabled_x is True
    assert loaded.filename_b.endswith("tk3.mov") and loaded.cap_b is not None


def test_wipe_already_on_keeps_its_axes(loaded, folder):  # noqa: F811
    loaded.wipeCheckBox.setChecked(True)
    loaded.wipeYButton.setChecked(True)
    assert loaded.open_b_and_wipe(str(folder / "tk3.mov")) is True
    assert wipe_state(loaded) == (True, False, True)


def test_failed_open_leaves_wipe_off(loaded, folder, monkeypatch):  # noqa: F811
    assert loaded.open_b_and_wipe(str(folder / "없는.mov")) is False
    assert wipe_state(loaded) == (False, False, False) and not loaded.filename_b
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    assert loaded.open_b_and_wipe() is False
    assert wipe_state(loaded) == (False, False, False) and not loaded.filename_b


def test_mixed_kinds_do_not_turn_on_wipe(loaded, qapp):
    """A가 영상인데 시퀀스를 B로 열면 open_file이 A를 닫음(종류가 다른 쪽) — 볼 A가 없으니 와이프를 켜지 않음."""
    seq_tab(loaded, qapp)
    assert loaded.open_b_and_wipe(seq_item(loaded, "tk1").data(Qt.UserRole).identity) is True
    assert loaded.cap_a is None
    assert wipe_state(loaded) == (False, False, False)


@pytest.mark.parametrize("how", ["key", "mov_menu", "seq_menu", "file_menu"])
def test_every_b_path_turns_on_wipe(loaded, folder, menus, monkeypatch, qapp, how):  # noqa: F811
    if how == "key":
        tk3 = mov_item(loaded, "tk3.mov")
        select(loaded.sidebar, [tk3], current=tk3)
        assert loaded.eventFilter(loaded.sidebar, key_event(Qt.Key_BracketRight, "]")) is True
        expected = "tk3.mov"
    elif how == "mov_menu":
        loaded.open_video_b(loaded.sidebar.indexFromItem(mov_item(loaded, "tk3.mov")))
        expected = "tk3.mov"
    elif how == "seq_menu":
        seq_tab(loaded, qapp)
        assert loaded.open_file("A", seq_item(loaded, "tk2").data(Qt.UserRole).identity)
        loaded.wipeCheckBox.setChecked(False)
        menus.pick = (ui_text.text("side_menu.seq.open_b"),)
        right_click(loaded, loaded.seq_sidebar, seq_item(loaded, "tk1"), "darwin", monkeypatch)
        expected = "tk1.seq"
    else:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(folder / "tk3.mov"), ""))
        loaded.menu_actions["menu.file.open_b"].trigger()
        expected = "tk3.mov"
    qapp.processEvents()
    assert loaded.filename_b.endswith(expected)
    assert wipe_state(loaded) == (True, True, False)


def test_turning_wipe_off_still_closes_b(loaded, folder):  # noqa: F811
    assert loaded.open_b_and_wipe(str(folder / "tk3.mov"))
    loaded.wipeCheckBox.setChecked(False)
    assert loaded.cap_b is None and not loaded.filename_b


@pytest.mark.parametrize("how", ["call", "button", "key"])
def test_b_picture_shows_on_the_first_open(loaded, folder, qapp, monkeypatch, how):  # noqa: F811
    """와이프가 꺼진 채 B를 열면 seek_to_frame이 B 그림을 읽지 않음(와이프가 켜졌을 때만 읽음) — 그 뒤 와이프를 켜도 B 자리가 검게
    남아 한 번 더 눌러야 그림이 들어왔음(사용자 보고 2026-11-20). 처음 열 때 B가 A와 같은 프레임의 그림으로 보여야 함."""
    shown = []
    real_update = loaded.videoWidget.updateFrame
    monkeypatch.setattr(loaded.videoWidget, "updateFrame", lambda a, b: shown.append(b) or real_update(a, b))
    tk3 = mov_item(loaded, "tk3.mov")
    if how == "call":
        assert loaded.open_b_and_wipe(tk3.toolTip())
    elif how == "button":
        from tests.test_sidebar_ab_buttons import group, hover_item
        loaded.set_sidebar_ab_buttons(True)  # 처음에는 꺼져 있음
        hover_item(qapp, loaded.sidebar, tk3)
        group(loaded, loaded.sidebar).button_b.click()
    else:
        select(loaded.sidebar, [tk3], current=tk3)
        assert loaded.eventFilter(loaded.sidebar, key_event(Qt.Key_BracketRight, "]")) is True
    qapp.processEvents()
    assert wipe_state(loaded) == (True, True, False)
    assert loaded.frame_b is not None
    assert int(loaded.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == int(loaded.cap_a.get(cv2.CAP_PROP_POS_FRAMES))  # A와 같은 프레임
    assert shown and shown[-1] is not None  # 마지막 그림에 B가 있음
