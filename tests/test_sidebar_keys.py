"""사이드바 우클릭 메뉴의 키 — C 파일 복사·J 합치기·M 미디어 정보·R 썸네일 다시 만들기·[ ] 비디오 A·B로 열기 (사용자 요청 2026-11-18).

키는 지금 보는 탭을 따름: Mov 탭은 Mov 목록의 선택, All 탭은 그 탭에서 고른 것(C·J는 mov만 — 선택 재생과 같은 규칙),
Seq 탭은 시퀀스 메뉴에 있는 일([ ] R M)만 하고 없는 일(C·J)은 알림. 우클릭 메뉴의 글자 끝에 그 키 — [ ]는 와이프의 왼쪽(A)·
오른쪽(B) (B 키는 파일 이름 글자라 못 씀, O는 메뉴 막대의 파일 고르기 창이라 헷갈림 — 사용자 결정). 폴더 고르기 창·병합·미디어 정보 창은 바꿔 끼워 띄우지 않고 부른 것을 셈 — 복사는 진짜 파일로 봄.
"""

import os
import re

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFileDialog, QMenu

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


@pytest.fixture
def calls(player, monkeypatch):
    """합치기·미디어 정보·썸네일의 실제 일을 바꿔 끼우고 받은 것을 적음."""
    got = []
    monkeypatch.setattr(player, "_merge_files", lambda paths: got.append(("merge", [os.path.basename(p) for p in paths])))
    monkeypatch.setattr(player, "show_media_info", lambda path: got.append(("info", os.path.basename(path))))
    monkeypatch.setattr(player, "show_seq_info", lambda item: got.append(("seq_info", item.data(Qt.UserRole).base)))
    monkeypatch.setattr(player, "regenerate_selected_thumbnails",
                        lambda: got.append(("thumbs", sorted(i.text() for i in player.sidebar.selectedItems()))))
    monkeypatch.setattr(player, "regenerate_seq_thumbnails",
                        lambda items: got.append(("seq_thumbs", [i.data(Qt.UserRole).base for i in items])))
    return got


def key_event(key, text, modifiers=Qt.NoModifier, repeat=False):
    return QKeyEvent(QEvent.KeyPress, key, modifiers, text, repeat)


def select(widget, items, current=None):
    widget.clearSelection()
    for item in items:
        item.setSelected(True)
    if current is not None:
        widget.setCurrentItem(current, widget.selectionModel().NoUpdate)


def copied(folder_path):
    return sorted(os.listdir(folder_path))


def seq_tab(player, qapp):
    player.sidebar_tabs.setCurrentWidget(player.seq_sidebar)
    qapp.processEvents()


def menu_texts(player, widget, item, monkeypatch):
    shown = []
    monkeypatch.setattr(QMenu, "exec_", lambda menu, *args: shown.append([a.text() for a in menu.actions()]))
    show = {player.sidebar: player.show_sidebar_context_menu, player.seq_sidebar: player.show_seq_context_menu}[widget]
    show(widget.visualItemRect(item).center())
    return [text for text in shown[-1] if text]


# ---------------------------------------------------------------- 메뉴 글자

def test_item_texts_name_their_shortcut_keys():
    """키가 있는 우클릭 항목의 글자 끝에 그 키 — 메뉴 막대 항목처럼 (사용자 지적 2026-11-18 '여기 단축키 빠져있어')."""
    assert [(chr(key), hangul) for key, hangul, _text_key, _name in player_menus.ITEM_KEY_SHORTCUTS] == [
        ("C", "ㅊ"), ("J", "ㅓ"), ("M", "ㅡ"), ("R", "ㄱ"), ("[", "["), ("]", "]")]  # [ ]는 한글 자판에서도 같은 글자
    for key, _hangul, text_key, _name in player_menus.ITEM_KEY_SHORTCUTS:
        for code in ui_text.LANGUAGES:
            assert ui_text.TEXTS[text_key][code].endswith(f" ({chr(key)})"), (text_key, code)


@pytest.mark.parametrize("text_key, key", [
    ("side_menu.seq.open_a", "["), ("side_menu.seq.open_b", "]"),
    ("side_menu.seq.thumbnails", "R"), ("side_menu.seq.info", "M"),
])
def test_seq_menu_texts_name_their_keys(text_key, key):
    for code in ui_text.LANGUAGES:
        assert ui_text.TEXTS[text_key][code].endswith(f" ({key})"), (text_key, code)


def test_open_keys_are_brackets_not_o_or_b():
    """비디오 A·B 열기 = [ ] — O(메뉴 막대의 영상 A 열기 = 파일 고르기 창)는 헷갈리고 B는 파일 이름 글자 키 (사용자 결정 2026-11-18)."""
    keys = {text_key: chr(key) for key, _hangul, text_key, _name in player_menus.ITEM_KEY_SHORTCUTS}
    assert keys["side_menu.open_a"] == "[" and keys["side_menu.open_b"] == "]"
    assert not re.search(r"\((O|B)\)$", ui_text.TEXTS["side_menu.open_a"]["ko"] + ui_text.TEXTS["side_menu.open_b"]["ko"])


def test_mov_menu_shows_the_keys(player, folder, monkeypatch):
    drop_folder(player, "video", folder)
    texts = menu_texts(player, player.sidebar, mov_item(player, "tk1.mov"), monkeypatch)
    for wanted in ("비디오 A 열기 ([)", "비디오 B 열기 (])", "애니매틱 하나로 합치기 (J)", "파일 복사 (C)", "썸네일 재생성 (R)",
                   "미디어 정보 (M)"):
        assert wanted in texts, wanted


def test_seq_menu_shows_the_keys(player, folder, monkeypatch, qapp):
    drop_folder(player, "video", folder)
    seq_tab(player, qapp)
    texts = menu_texts(player, player.seq_sidebar, seq_item(player, "tk1"), monkeypatch)
    for wanted in ("비디오 A로 열기 ([)", "비디오 B로 열기 (])", "썸네일 다시 만들기 (R)", "정보 보기 (M)"):
        assert wanted in texts, wanted


def test_menu_copy_still_copies_the_mov_selection(player, folder, target, monkeypatch):
    """메뉴 길(copy_selected_files)도 그대로 — 우클릭 → 파일 복사 (C)."""
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")])

    def pick(menu, *args):
        next(a for a in menu.actions() if a.text() == "파일 복사 (C)").trigger()

    monkeypatch.setattr(QMenu, "exec_", pick)
    item = mov_item(player, "tk1.mov")
    player.show_sidebar_context_menu(player.sidebar.visualItemRect(item).center())
    assert len(target[1]) == 1
    assert copied(target[0]) == ["tk1.mov", "tk3.mov"]


# ---------------------------------------------------------------- C 파일 복사

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


def test_real_key_click_on_the_list_copies_once(player, folder, target, qapp):
    """진짜 키 입력 — 목록의 필터와 창의 keyPressEvent가 두 번 처리하지 않음."""
    drop_folder(player, "video", folder)
    player.show()
    QTest.qWait(250)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    player.sidebar.setFocus()
    qapp.processEvents()
    assert QApplication.focusWidget() is player.sidebar
    QTest.keyClick(player.sidebar, Qt.Key_C)
    assert len(target[1]) == 1
    assert copied(target[0]) == ["tk1.mov"]


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
    assert [(kind, title) for kind, title, _text in shown] == [("information", "파일 복사")]
    assert "mov" in shown[0][2]


def test_seq_tab_with_a_sequence_selected_says_copy_is_not_there(player, folder, target, dialogs, qapp):
    """Seq 탭에는 '파일 복사'가 없음 — 숨은 Mov 탭의 선택을 복사하지 않고, 고른 것이 있으면 창으로 알림 (리뷰 I-1)."""
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])  # 숨은 Mov 탭의 선택이 있어도
    seq_tab(player, qapp)
    select(player.seq_sidebar, [seq_item(player, "tk1")])
    before = len(dialogs.messages)
    assert player.eventFilter(player.seq_sidebar, key_event(Qt.Key_C, "c")) is True
    assert target[1] == []
    assert copied(target[0]) == []
    shown = dialogs.messages[before:]
    assert [(kind, title) for kind, title, _text in shown] == [("information", "파일 복사")]
    assert "Seq" in shown[0][2]


def test_seq_tab_with_nothing_selected_only_logs(player, folder, target, dialogs, qapp, capsys):
    drop_folder(player, "video", folder)
    seq_tab(player, qapp)
    player.seq_sidebar.clearSelection()
    before = len(dialogs.messages)
    capsys.readouterr()
    player.keyPressEvent(key_event(Qt.Key_C, "c"))
    assert target[1] == [] and dialogs.messages[before:] == []
    assert "[파일 복사]" in capsys.readouterr().out  # 조용히 넘기지 않음 — 기록 한 줄


def test_english_screen_quotes_the_english_name(player, folder, target, dialogs, qapp):
    """딸린 창이 인용하는 기능 이름은 지금 화면의 이름 (키 표시는 빼고)."""
    drop_folder(player, "video", folder)
    seq_tab(player, qapp)
    select(player.seq_sidebar, [seq_item(player, "tk1")])
    ui_text.set_language("en")
    try:
        before = len(dialogs.messages)
        player.keyPressEvent(key_event(Qt.Key_C, "c"))
        assert [title for _kind, title, _text in dialogs.messages[before:]] == ["Copy files"]
    finally:
        ui_text.set_language("ko")


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
    runs = []

    def broken():
        runs.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(player, "copy_files_for_key", broken)
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_C, "c")) is True
    assert runs == [1]
    assert len(reports) == 1 and "C" in reports[0][1]


def test_unrelated_keys_do_not_look_up_handlers(player, monkeypatch):
    """처리기는 키가 맞을 때만 찾음 — 다른 키(Space·화살표 …)마다 찾다가 실패해 가상 함수 밖으로 새지 않게 (리뷰 M-1)."""
    def boom():
        raise AssertionError("찾지 말아야 함")

    monkeypatch.setattr(player, "_menu_handlers", boom)
    assert player.run_key_shortcut(key_event(Qt.Key_Z, "z")) is False


# ---------------------------------------------------------------- J 합치기

def test_j_key_merges_the_selected_movs(player, folder, calls):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk3.mov"), mov_item(player, "tk1.mov")])
    player.keyPressEvent(key_event(Qt.Key_J, "j"))
    player.keyPressEvent(key_event(0, "ㅓ"))
    assert calls == [("merge", ["tk1.mov", "tk3.mov"])] * 2  # 이름순 — 메뉴와 같음


def test_menu_merge_uses_the_same_merge(player, folder, calls):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")])
    player.merge_videos()
    assert calls == [("merge", ["tk1.mov", "tk3.mov"])]


def test_j_key_on_all_tab_merges_only_the_movs_selected_there(player, folder, calls, qapp):
    drop_folder(player, "video", folder)
    show_all_tab(player, qapp)
    select(player.all_sidebar, [all_item(player, "mov", "tk1"), all_item(player, "mov", "tk3"), all_item(player, "seq", "tk1")])
    player.keyPressEvent(key_event(Qt.Key_J, "j"))
    assert calls == [("merge", ["tk1.mov", "tk3.mov"])]


def test_j_key_on_seq_tab_says_merge_is_not_there(player, folder, calls, dialogs, qapp):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")])  # 숨은 선택은 쓰지 않음
    seq_tab(player, qapp)
    select(player.seq_sidebar, [seq_item(player, "tk1")])
    before = len(dialogs.messages)
    player.keyPressEvent(key_event(Qt.Key_J, "j"))
    assert calls == []
    assert [(kind, title) for kind, title, _text in dialogs.messages[before:]] == [("information", "애니매틱 하나로 합치기")]


# ---------------------------------------------------------------- M 미디어 정보

def test_m_key_shows_media_info_of_the_current_selected_video(player, folder, calls):
    drop_folder(player, "video", folder)
    tk1, tk3 = mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")
    select(player.sidebar, [tk1, tk3], current=tk3)
    player.keyPressEvent(key_event(Qt.Key_M, "m"))
    select(player.sidebar, [tk1], current=tk3)  # 현재 항목이 고른 것 밖이면 고른 것의 첫 줄
    player.keyPressEvent(key_event(0, "ㅡ"))
    assert calls == [("info", "tk3.mov"), ("info", "tk1.mov")]


def test_m_key_on_seq_tab_shows_sequence_info(player, folder, calls, qapp):
    drop_folder(player, "video", folder)
    seq_tab(player, qapp)
    item = seq_item(player, "tk2")
    select(player.seq_sidebar, [item], current=item)
    assert player.eventFilter(player.seq_sidebar, key_event(Qt.Key_M, "m")) is True
    assert calls == [("seq_info", "tk2")]


def test_m_key_on_all_tab_follows_the_kind(player, folder, calls, qapp):
    drop_folder(player, "video", folder)
    show_all_tab(player, qapp)
    movie = all_item(player, "mov", "tk3")
    select(player.all_sidebar, [movie], current=movie)
    player.keyPressEvent(key_event(Qt.Key_M, "m"))
    sequence = all_item(player, "seq", "tk2")
    select(player.all_sidebar, [sequence], current=sequence)
    player.keyPressEvent(key_event(Qt.Key_M, "m"))
    assert calls == [("info", "tk3.mov"), ("seq_info", "tk2")]


def test_m_key_with_nothing_selected_only_logs(player, folder, calls, capsys):
    drop_folder(player, "video", folder)
    player.sidebar.clearSelection()
    capsys.readouterr()
    player.keyPressEvent(key_event(Qt.Key_M, "m"))
    assert calls == []
    assert "[미디어 정보]" in capsys.readouterr().out


# ---------------------------------------------------------------- R 썸네일 다시 만들기

def test_r_key_on_mov_tab_regenerates_the_mov_selection(player, folder, calls):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    player.keyPressEvent(key_event(Qt.Key_R, "r"))
    player.keyPressEvent(key_event(0, "ㄱ"))
    assert calls == [("thumbs", ["tk1.mov"])] * 2


def test_r_key_on_seq_tab_regenerates_the_selected_sequences_not_the_hidden_movs(player, folder, calls, qapp):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    seq_tab(player, qapp)
    select(player.seq_sidebar, [seq_item(player, "tk2")])
    assert player.eventFilter(player.seq_sidebar, key_event(Qt.Key_R, "r")) is True
    assert calls == [("seq_thumbs", ["tk2"])]


def test_r_key_on_all_tab_regenerates_movs_and_sequences_selected_there(player, folder, calls, qapp):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])  # 다른 탭의 선택 — 끝난 뒤 그대로
    show_all_tab(player, qapp)
    select(player.all_sidebar, [all_item(player, "mov", "tk3"), all_item(player, "seq", "tk2")])
    player.keyPressEvent(key_event(Qt.Key_R, "r"))
    assert calls == [("thumbs", ["tk3.mov"]), ("seq_thumbs", ["tk2"])]
    assert [item.text() for item in player.sidebar.selectedItems()] == ["tk1.mov"]
    assert player.seq_sidebar.selectedItems() == []


def test_r_with_ctrl_is_not_the_thumbnail_key(player, folder, calls):
    drop_folder(player, "video", folder)
    select(player.sidebar, [mov_item(player, "tk1.mov")])
    player.keyPressEvent(key_event(Qt.Key_R, "r", Qt.ControlModifier))
    assert calls == []


# ---------------------------------------------------------------- [ ] 비디오 A·B로 열기

def watch_open(player, monkeypatch, calls):
    """open_file을 바꿔 끼워 적음 — 폴더를 불러올 때의 열기는 빼려고 준비 뒤에 부름."""
    monkeypatch.setattr(player, "open_file", lambda side, path: calls.append(("open", side, os.path.basename(path))))

def test_brackets_open_the_current_selected_video_in_a_and_b(player, folder, calls, monkeypatch):
    """와이프용 — [ = 비디오 A로, ] = 비디오 B로 (우클릭 '비디오 A 열기'·'비디오 B 열기'와 같은 일)."""
    drop_folder(player, "video", folder)
    watch_open(player, monkeypatch, calls)
    tk1, tk3 = mov_item(player, "tk1.mov"), mov_item(player, "tk3.mov")
    select(player.sidebar, [tk1], current=tk1)
    player.keyPressEvent(key_event(Qt.Key_BracketLeft, "["))
    select(player.sidebar, [tk1, tk3], current=tk3)
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_BracketRight, "]")) is True
    assert calls == [("open", "A", "tk1.mov"), ("open", "B", "tk3.mov")]


def test_brackets_on_seq_tab_open_the_sequence(player, folder, calls, qapp, monkeypatch):
    drop_folder(player, "video", folder)
    watch_open(player, monkeypatch, calls)
    seq_tab(player, qapp)
    item = seq_item(player, "tk2")
    select(player.seq_sidebar, [item], current=item)
    assert player.eventFilter(player.seq_sidebar, key_event(Qt.Key_BracketRight, "]")) is True
    assert calls == [("open", "B", "tk2.seq")]


def test_brackets_on_all_tab_follow_the_kind(player, folder, calls, qapp, monkeypatch):
    drop_folder(player, "video", folder)
    watch_open(player, monkeypatch, calls)
    show_all_tab(player, qapp)
    movie = all_item(player, "mov", "tk3")
    select(player.all_sidebar, [movie], current=movie)
    player.keyPressEvent(key_event(Qt.Key_BracketLeft, "["))
    sequence = all_item(player, "seq", "tk2")
    select(player.all_sidebar, [sequence], current=sequence)
    player.keyPressEvent(key_event(Qt.Key_BracketRight, "]"))
    assert calls == [("open", "A", "tk3.mov"), ("open", "B", "tk2.seq")]


def test_brackets_with_nothing_selected_only_log(player, folder, calls, capsys, monkeypatch):
    drop_folder(player, "video", folder)
    watch_open(player, monkeypatch, calls)
    player.sidebar.clearSelection()
    capsys.readouterr()
    player.keyPressEvent(key_event(Qt.Key_BracketRight, "]"))
    assert calls == []
    assert "[비디오 B 열기]" in capsys.readouterr().out


def test_ctrl_bracket_is_not_the_open_key(player, folder, calls, monkeypatch):
    drop_folder(player, "video", folder)
    watch_open(player, monkeypatch, calls)
    select(player.sidebar, [mov_item(player, "tk1.mov")], current=mov_item(player, "tk1.mov"))
    player.keyPressEvent(key_event(Qt.Key_BracketLeft, "[", Qt.ControlModifier))
    assert calls == []
