"""C 키(한글 자판 ㅊ) — 사이드바 우클릭 '파일 복사'와 같은 일 (사용자 요청 2026-11-18).

지금 보는 탭의 고른 영상: Mov 탭은 Mov 목록의 선택, All 탭은 All 목록의 선택 중 mov만(시퀀스는 건너뜀 — 선택 재생과 같은 규칙),
Seq 탭은 복사할 영상이 없음. 폴더 고르기 창은 바꿔 끼워 띄우지 않고 부른 수를 셈 — 복사는 진짜 파일로 봄.
"""

import os

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QFileDialog, QMenu

from tests.test_sidebar_all_tab import all_item, show_all_tab
from tests.test_sidebar_open_with import folder, mov_item  # noqa: F401 (folder: fixture)
from tests.test_sidebar_seq_tab import seq_item
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import player_menus, ui_text


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def target(tmp_path, monkeypatch):
    """폴더 고르기 창이 고르는 폴더 — asked는 창을 띄운 수."""
    folder_path = tmp_path / "copied"
    folder_path.mkdir()
    asked = []

    def choose(*args, **kwargs):
        asked.append(args)
        return str(folder_path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose)
    return folder_path, asked


def key_event(key, text, modifiers=Qt.NoModifier, repeat=False):
    return QKeyEvent(QEvent.KeyPress, key, modifiers, text, repeat)


def select(widget, items):
    widget.clearSelection()
    for item in items:
        item.setSelected(True)


def copied(folder_path):
    return sorted(os.listdir(folder_path))


def test_item_texts_name_their_shortcut_keys():
    """우클릭 메뉴의 '파일 복사' 글자 끝에 그 키 — 메뉴 막대 항목처럼 (사용자 지적 2026-11-18 '여기 단축키 빠져있어')."""
    for key, _hangul, text_key, _name in player_menus.ITEM_KEY_SHORTCUTS:
        for code in ui_text.LANGUAGES:
            assert ui_text.TEXTS[text_key][code].endswith(f" ({chr(key)})"), (text_key, code)


def test_right_click_menu_shows_the_copy_key(player, folder, monkeypatch):
    drop_folder(player, "video", folder)
    shown = []
    monkeypatch.setattr(QMenu, "exec_", lambda menu, *args: shown.append([a.text() for a in menu.actions()]))
    item = mov_item(player, "tk1.mov")
    player.show_sidebar_context_menu(player.sidebar.visualItemRect(item).center())
    assert "파일 복사 (C)" in shown[-1]


def test_c_key_copies_the_selected_mov_files_like_the_menu(player, folder, target):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")])
    player.keyPressEvent(key_event(Qt.Key_C, "c"))
    folder_path, asked = target
    assert len(asked) == 1
    assert copied(folder_path) == ["tk1.mov", "tk3.mov"]


def test_hangul_and_capital_c_work_too(player, folder, target):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    player.keyPressEvent(key_event(0, "ㅊ"))
    player.keyPressEvent(key_event(Qt.Key_C, "C", Qt.ShiftModifier))
    assert len(target[1]) == 2
    assert copied(target[0]) == ["tk1.mov"]


def test_list_filters_take_the_c_key(player, folder, target):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk3.mov")])
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_C, "c")) is True
    assert copied(target[0]) == ["tk3.mov"]


def test_all_tab_copies_only_the_movs_selected_there(player, folder, target, qapp):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk3.mov")])  # 숨은 Mov 탭의 선택은 쓰지 않음
    show_all_tab(player, qapp)
    select(player.all_sidebar, [all_item(player, "mov", "tk1"), all_item(player, "seq", "tk2")])
    assert player.eventFilter(player.all_sidebar, key_event(Qt.Key_C, "c")) is True
    assert copied(target[0]) == ["tk1.mov"]
    assert [item.text() for item in player.sidebar.selectedItems()] == ["tk3.mov"]  # 다른 탭의 선택은 그대로


def test_all_tab_with_only_sequences_selected_says_so(player, folder, target, dialogs, qapp):
    drop_folder(player, "video", folder)
    show_all_tab(player, qapp)
    select(player.all_sidebar, [all_item(player, "seq", "tk1")])
    before = len(dialogs.messages)  # 폴더를 끌어다 놓을 때의 알림은 빼고
    player.keyPressEvent(key_event(Qt.Key_C, "c"))
    assert target[1] == []
    assert copied(target[0]) == []
    shown = dialogs.messages[before:]
    assert [kind for kind, _title, _text in shown] == ["information"]
    assert "mov" in shown[0][2]


def test_seq_tab_copies_nothing(player, folder, target, dialogs, qapp, capsys):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])  # 숨은 Mov 탭의 선택이 있어도
    player.sidebar_tabs.setCurrentWidget(player.seq_sidebar)
    qapp.processEvents()
    select(player.seq_sidebar, [seq_item(player, "tk1")])
    before = len(dialogs.messages)  # 폴더를 끌어다 놓을 때의 알림은 빼고
    capsys.readouterr()
    assert player.eventFilter(player.seq_sidebar, key_event(Qt.Key_C, "c")) is True
    assert target[1] == []
    assert copied(target[0]) == []
    assert dialogs.messages[before:] == []
    assert "[파일 복사]" in capsys.readouterr().out  # 조용히 넘기지 않음 — 기록 한 줄


def test_nothing_selected_asks_for_no_folder(player, folder, target):
    drop_folder(player, "video", folder)
    player.sidebar.clearSelection()
    player.keyPressEvent(key_event(Qt.Key_C, "c"))
    assert target[1] == []


@pytest.mark.parametrize("modifier", [Qt.ControlModifier, Qt.AltModifier, Qt.MetaModifier])
def test_c_with_ctrl_alt_or_meta_is_not_the_copy_key(player, folder, target, modifier):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_C, "c", modifier)) is False
    assert target[1] == []


def test_held_c_key_does_not_open_the_folder_window_again(player, folder, target):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_C, "c", repeat=True)) is True
    player.keyPressEvent(key_event(Qt.Key_C, "c", repeat=True))
    assert target[1] == []


def test_copy_error_is_reported_once_and_the_key_is_taken(player, folder, monkeypatch):
    drop_folder(player, "video", folder)
    reports = []
    monkeypatch.setattr(player_menus.error_window, "report_from_handler",
                        lambda prefix, context: reports.append((prefix, context)))
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(player, "copy_files_for_key", broken)
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_C, "c")) is True
    assert calls == [1]
    assert len(reports) == 1 and "C" in reports[0][1]
