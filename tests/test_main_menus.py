"""메인 메뉴 — File · View · Playback · Compare · Tools (2026-11-16 UI 개편 PR 2, `player_menus`).

가운데 열을 없애며 단추가 사라진 기능과 단축키로만 닿던 기능을 메뉴에 올린다. 항목은 지금의 처리기를 그대로 부르고,
단축키는 글자로만 적는다(QAction 단축키 없음 — 키는 창의 키 처리가 받음). 체크·켜짐은 메뉴를 열 때 지금 상태로 맞춘다.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QAction, QApplication

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import player_menus, ui_text


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def shown(player, qapp):
    player.resize(1400, 860)
    player.show()
    QApplication.setActiveWindow(player)
    QTest.qWait(250)
    return player


def menu_titles(player):
    return [action.text() for action in player.menuBar().actions()]


def open_menu(player, key):
    """메뉴를 연 것처럼 — aboutToShow가 체크·켜짐을 맞춤."""
    player.main_menus[key].aboutToShow.emit()


def pick(player, text_key):
    menu_key = text_key.split(".")[1]
    open_menu(player, menu_key)
    player.menu_actions[text_key].trigger()


def press(player, key, text=""):
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))


# ---------------------------------------------------------------- 모양

def test_menu_bar_runs_file_view_playback_compare_tools_then_settings_help(player):
    assert menu_titles(player) == ["&File", "&View", "&Playback", "&Compare", "&Tools", "&Settings", "&Help"]
    assert list(player.main_menus) == ["file", "view", "playback", "compare", "tools"]
    for key, menu in player.main_menus.items():
        assert menu.title() == ui_text.text("menu." + key)


def test_every_item_reads_the_text_table_in_the_listed_order(player):
    for menu_key, items in player_menus.MENUS:
        actions = player.main_menus[menu_key].actions()
        assert len(actions) == len(items), menu_key
        for action, text_key in zip(actions, items):
            if text_key is player_menus.SEPARATOR:
                assert action.isSeparator()
            else:
                assert action is player.menu_actions[text_key]
                assert action.text() == ui_text.text(text_key)
    listed = {key for _menu, items in player_menus.MENUS for key in items if key is not player_menus.SEPARATOR}
    assert set(player.menu_actions) == listed
    assert listed == {key for key in ui_text.TEXTS if key.startswith("menu.") and key.count(".") == 2}  # 글자 표의 항목 전부


def test_file_menu_is_what_the_design_lists(player):
    assert [a.text() for a in player.main_menus["file"].actions() if not a.isSeparator()] == [
        "영상 A 열기… (O)", "영상 B 열기…", "폴더 열기… (I)", "북마크 추가", "북마크 관리… (P)"]
    assert [a.text() for a in player.main_menus["tools"].actions() if not a.isSeparator()] == [
        "주석 패널", "OCR 패널", "도구 패널 열고 닫기 (N)", "작품 경로 관리…"]


def test_items_carry_no_real_shortcuts_only_the_note_in_the_text(player):
    """단축키는 글자로만 — QAction에 걸면 같은 키가 두 번 처리되거나 Mac 메뉴 막대가 키를 가로챔."""
    for text_key, action in player.menu_actions.items():
        assert action.shortcut().isEmpty(), text_key
        assert action.menuRole() == QAction.NoRole, text_key  # Mac이 글자를 보고 앱 메뉴로 옮기지 않게
    for menu in player.menuBar().actions():
        for action in menu.menu().actions():
            if not action.shortcut().isEmpty():
                assert action.shortcut().toString() == "F1"  # 예전부터 있던 Help → 사용법만


def test_checkable_items_are_the_toggles(player):
    checkable = {key for key, action in player.menu_actions.items() if action.isCheckable()}
    assert checkable == {"menu.view.overlay_text", "menu.playback.loop", "menu.compare.wipe", "menu.compare.x",
                         "menu.compare.y", "menu.tools.annotation", "menu.tools.ocr"}


def test_retranslate_rereads_titles_and_items(player):
    ui_text.set_language("en")
    try:
        player.retranslate_main_menus()
        assert player.menu_actions["menu.playback.play"].text() == "Play/Pause (Space)"
        assert player.menu_actions["menu.tools.work_paths"].text() == "Manage show paths…"
        assert menu_titles(player)[:5] == ["&File", "&View", "&Playback", "&Compare", "&Tools"]
    finally:
        ui_text.set_language("ko")
        player.retranslate_main_menus()
    assert player.menu_actions["menu.playback.play"].text() == "재생/일시정지 (Space)"


# ---------------------------------------------------------------- 항목 = 지금의 처리기

SPIED = {
    "menu.file.open_folder": ("select_folder", ()),
    "menu.file.bookmark_add": ("add_bookmark", ()),
    "menu.file.bookmark_manage": ("show_bookmarks", ()),
    "menu.view.fullscreen": ("toggle_fullscreen", ()),
    "menu.view.video_only": ("toggle_video_only_fullscreen", ()),
    "menu.view.controls": ("toggle_controls", ()),
    "menu.view.theme": ("toggle_theme", ()),
    "menu.playback.play": ("toggle_play_pause", ()),
    "menu.playback.prev": ("prev_frame", ()),
    "menu.playback.next": ("next_frame", ()),
    "menu.playback.first": ("go_to_first", ()),
    "menu.playback.last": ("go_to_last", ()),
    "menu.playback.playlist": ("play_selected_files", ()),
    "menu.tools.toggle": ("toggle_tool_panel", ()),
    "menu.tools.work_paths": ("manage_work_paths", ()),
}


@pytest.mark.parametrize("text_key", sorted(SPIED))
def test_item_calls_the_existing_handler(player, monkeypatch, text_key):
    name, args = SPIED[text_key]
    calls = []
    monkeypatch.setattr(player, name, lambda *got: calls.append(got))
    player.menu_actions[text_key].trigger()
    assert calls == [args]


def test_open_video_items_open_a_and_b(player, monkeypatch):
    calls = []
    monkeypatch.setattr(player, "open_file", lambda *got: calls.append(got))
    player.menu_actions["menu.file.open_a"].trigger()
    player.menu_actions["menu.file.open_b"].trigger()
    assert calls == [("A",), ("B",)]


def test_view_items_drive_the_video_widget(player, monkeypatch):
    calls = []
    for name in ("reset_view", "show_original_size", "zoom_in", "zoom_out"):
        monkeypatch.setattr(player.videoWidget, name, lambda *got, name=name: calls.append((name, got)))
    for key in ("menu.view.fit", "menu.view.original", "menu.view.zoom_in", "menu.view.zoom_out"):
        player.menu_actions[key].trigger()
    center = player.videoWidget.rect().center()
    assert calls == [("reset_view", ()), ("show_original_size", ()), ("zoom_in", (center,)), ("zoom_out", (center,))]


def test_playback_items_move_the_real_player(shown, qapp, tmp_path):
    shown.open_file("A", write_test_video(str(tmp_path / "a.mp4"), frames=24))
    pick(shown, "menu.playback.last")
    assert shown.labelFrameCount.text() == "Current: 24"
    pick(shown, "menu.playback.first")
    assert shown.labelFrameCount.text() == "Current: 1"
    pick(shown, "menu.playback.next")
    assert shown.labelFrameCount.text() == "Current: 2"
    pick(shown, "menu.playback.prev")
    assert shown.labelFrameCount.text() == "Current: 1"
    pick(shown, "menu.playback.play")
    assert shown.timer.isActive()
    pick(shown, "menu.playback.play")
    assert not shown.timer.isActive()


# ---------------------------------------------------------------- 체크·켜짐

def checked(player, text_key):
    return player.menu_actions[text_key].isChecked()


def enabled(player, text_key):
    return player.menu_actions[text_key].isEnabled()


def test_loop_item_toggles_and_follows_the_button(shown):
    pick(shown, "menu.playback.loop")
    assert shown.loopEnabled and shown.loopCheckBox.isChecked() and checked(shown, "menu.playback.loop")
    shown.loopCheckBox.setChecked(False)  # 재생 줄의 단추로 끔
    open_menu(shown, "playback")
    assert not checked(shown, "menu.playback.loop") and not shown.loopEnabled
    pick(shown, "menu.playback.loop")
    pick(shown, "menu.playback.loop")
    assert not shown.loopEnabled and not checked(shown, "menu.playback.loop")


def test_compare_items_follow_the_wipe_switch(shown, qapp):
    open_menu(shown, "compare")
    assert not checked(shown, "menu.compare.wipe")
    assert not enabled(shown, "menu.compare.x") and not enabled(shown, "menu.compare.y")
    shown.menu_actions["menu.compare.x"].trigger()  # 꺼진 항목 — 아무 일도 없음
    assert not shown.wipeXButton.isChecked()
    pick(shown, "menu.compare.wipe")
    assert shown.wipeCheckBox.isChecked() and shown.videoWidget.wipeEnabled and checked(shown, "menu.compare.wipe")
    assert enabled(shown, "menu.compare.x") and enabled(shown, "menu.compare.y")
    pick(shown, "menu.compare.x")
    assert shown.wipeXButton.isChecked() and shown.videoWidget.wipe_enabled_x and checked(shown, "menu.compare.x")
    shown.wipeYButton.setChecked(True)  # 재생 줄의 단추로 켬
    open_menu(shown, "compare")
    assert checked(shown, "menu.compare.y")
    pick(shown, "menu.compare.wipe")  # 끄면 X·Y도 풀리고 꺼짐
    assert not shown.videoWidget.wipeEnabled
    assert not checked(shown, "menu.compare.x") and not checked(shown, "menu.compare.y")
    assert not enabled(shown, "menu.compare.x") and not enabled(shown, "menu.compare.y")


def test_tools_items_follow_the_panel(shown, qapp):
    pick(shown, "menu.tools.annotation")
    assert shown.tool_panel_key() == "annotation"
    assert checked(shown, "menu.tools.annotation") and not checked(shown, "menu.tools.ocr")
    pick(shown, "menu.tools.ocr")
    assert shown.tool_panel_key() == "ocr"
    assert checked(shown, "menu.tools.ocr") and not checked(shown, "menu.tools.annotation")
    press(shown, Qt.Key_N)  # 키로 닫음
    open_menu(shown, "tools")
    assert not checked(shown, "menu.tools.ocr") and not checked(shown, "menu.tools.annotation")
    pick(shown, "menu.tools.toggle")  # 마지막에 쓰던 쪽
    assert shown.tool_panel_key() == "ocr" and checked(shown, "menu.tools.ocr")
    pick(shown, "menu.tools.ocr")  # 열린 쪽의 항목을 다시 고르면 닫힘
    assert shown.tool_panel_key() is None and not checked(shown, "menu.tools.ocr")


def test_overlay_text_item_follows_the_b_key(shown):
    pick(shown, "menu.view.overlay_text")
    assert shown.show_overlay and checked(shown, "menu.view.overlay_text")
    press(shown, Qt.Key_B)
    open_menu(shown, "view")
    assert not shown.show_overlay and not checked(shown, "menu.view.overlay_text")


def test_controls_item_hides_and_restores_like_the_v_key(shown, qapp):
    pick(shown, "menu.view.controls")
    qapp.processEvents()
    assert not shown.controls_visible and shown.transportBar.isHidden()
    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert shown.controls_visible and not shown.transportBar.isHidden()


def test_theme_item_switches_the_theme(shown):
    assert shown.current_theme == "dark"
    pick(shown, "menu.view.theme")
    assert shown.current_theme == "light"
    pick(shown, "menu.view.theme")
    assert shown.current_theme == "dark"


def test_end_playlist_item_is_enabled_only_during_a_playlist(shown, qapp, tmp_path):
    open_menu(shown, "playback")
    assert not enabled(shown, "menu.playback.playlist_end") and enabled(shown, "menu.playback.playlist")
    clips = [write_test_video(str(tmp_path / f"c{i}.mp4"), frames=24) for i in range(2)]
    shown.add_files_to_sidebar(clips)
    shown.sidebar.selectAll()
    pick(shown, "menu.playback.playlist")
    assert shown.is_playlist_playing
    open_menu(shown, "playback")
    assert enabled(shown, "menu.playback.playlist_end")
    pick(shown, "menu.playback.playlist_end")
    assert not shown.is_playlist_playing
    assert not enabled(shown, "menu.playback.playlist_end")


def test_items_that_should_be_off_do_nothing_even_when_triggered(shown, monkeypatch):
    """켜짐은 메뉴를 열 때만 맞추고 QAction.trigger()는 꺼진 항목도 실행함 — 처리기도 같은 조건으로 막음."""
    calls = []
    monkeypatch.setattr(shown, "end_playlist", lambda: calls.append("end"))
    monkeypatch.setattr(shown, "play_selected_files", lambda: calls.append("play"))
    shown.menu_actions["menu.playback.playlist_end"].trigger()  # 선택 재생 중이 아님
    shown.sidebar_tabs.setCurrentWidget(shown.seq_sidebar)
    shown.menu_actions["menu.playback.playlist"].trigger()  # Seq 탭
    shown.menu_actions["menu.compare.y"].trigger()  # 와이프가 꺼져 있음
    assert calls == [] and not shown.wipeYButton.isChecked() and not shown.videoWidget.wipe_enabled_y


def test_playlist_item_is_off_on_the_seq_tab(shown, qapp):
    shown.sidebar_tabs.setCurrentWidget(shown.seq_sidebar)
    open_menu(shown, "playback")
    assert not enabled(shown, "menu.playback.playlist")
    shown.sidebar_tabs.setCurrentWidget(shown.all_sidebar)
    open_menu(shown, "playback")
    assert enabled(shown, "menu.playback.playlist")


def test_check_marks_are_put_right_even_when_the_handler_refuses(shown, monkeypatch):
    """Qt는 항목을 고르면 체크부터 뒤집음 — 처리기가 아무것도 하지 않았으면 원래대로 되맞춤."""
    monkeypatch.setattr(shown, "toggle_tool_page", lambda key: None)
    shown.menu_actions["menu.tools.annotation"].trigger()
    assert not checked(shown, "menu.tools.annotation") and shown.tool_panel_key() is None


# ---------------------------------------------------------------- 영상 영역의 우클릭 메뉴

def test_video_area_takes_right_clicks_for_a_menu(player):
    assert player.videoWidget.contextMenuPolicy() == Qt.CustomContextMenu


def test_right_click_menu_offers_every_top_menu_as_a_submenu(player):
    """영상 영역에서 우클릭하면 메뉴 막대의 메뉴 전부가 하위 메뉴로 — 같은 메뉴 객체라 항목·체크·처리기가 그대로."""
    menu = player.build_video_context_menu()
    try:
        assert [action.text() for action in menu.actions()] == menu_titles(player)
        assert [action.text() for action in menu.actions()] == ["&File", "&View", "&Playback", "&Compare", "&Tools",
                                                                "&Settings", "&Help"]
        for action, bar_action in zip(menu.actions(), player.menuBar().actions()):
            assert action is bar_action and action.menu() is not None
        assert menu.actions()[2].menu() is player.main_menus["playback"]
        assert player.menu_actions["menu.playback.play"] in menu.actions()[2].menu().actions()
    finally:
        menu.deleteLater()


def right_click(player, monkeypatch, point):
    """영상 영역의 그 자리에 우클릭(컨텍스트 메뉴 이벤트)을 보내고, 뜬 메뉴마다 (항목 글자, 뜬 자리)를 돌려줌 — 메뉴는 띄우지 않음."""
    from PyQt5.QtGui import QContextMenuEvent
    from PyQt5.QtWidgets import QMenu

    shown_menus = []
    monkeypatch.setattr(QMenu, "exec_", lambda menu, *args: shown_menus.append(
        ([action.text() for action in menu.actions()], args[0] if args else None)))
    viewport = player.videoWidget.viewport()
    event = QContextMenuEvent(QContextMenuEvent.Mouse, point, viewport.mapToGlobal(point))
    QApplication.sendEvent(viewport, event)
    return shown_menus


def test_right_click_on_the_video_pops_the_menu_at_the_cursor(shown, monkeypatch):
    from PyQt5.QtCore import QPoint

    point = QPoint(120, 90)
    menus = right_click(shown, monkeypatch, point)
    assert menus == [(menu_titles(shown), shown.videoWidget.viewport().mapToGlobal(point))]


def test_right_click_menu_works_while_the_controls_are_hidden(shown, qapp, monkeypatch):
    """V 키로 컨트롤을 숨긴 채(메뉴 막대가 안 보이는 영상만 전체 화면에서도) 우클릭 메뉴는 그대로 — 거기서 되돌릴 수 있음."""
    from PyQt5.QtCore import QPoint

    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert right_click(shown, monkeypatch, QPoint(40, 40)) == [
        (menu_titles(shown), shown.videoWidget.viewport().mapToGlobal(QPoint(40, 40)))]
    shown.menu_actions["menu.view.controls"].trigger()
    qapp.processEvents()
    assert shown.controls_visible and not shown.transportBar.isHidden()


def test_submenus_of_the_right_click_menu_show_the_current_state(shown):
    """하위 메뉴가 펼쳐질 때(aboutToShow)도 체크·켜짐을 맞춤 — 메뉴 막대에서 열 때와 같은 메뉴라서."""
    shown.show_tool_panel("ocr")
    menu = shown.build_video_context_menu()
    try:
        tools = next(action.menu() for action in menu.actions() if action.menu() is shown.main_menus["tools"])
        tools.aboutToShow.emit()
        assert shown.menu_actions["menu.tools.ocr"].isChecked()
    finally:
        menu.deleteLater()


# ---------------------------------------------------------------- 단축키 O·I·L·W (사용자 요청 2026-11-16)

KEY_CASES = (  # (Qt 키, 영문 글자, 한글 자판의 같은 자리 글자, 항목의 글자 표 키)
    (Qt.Key_O, "o", "ㅐ", "menu.file.open_a"),
    (Qt.Key_I, "i", "ㅑ", "menu.file.open_folder"),
    (Qt.Key_L, "l", "ㅣ", "menu.playback.loop"),
    (Qt.Key_W, "w", "ㅈ", "menu.compare.wipe"),
)


@pytest.fixture
def key_calls(player, monkeypatch):
    """파일·폴더 창을 띄우지 않게 그 처리기만 바꿔 끼우고 부른 것을 적음 (반복·와이프는 진짜 단추 상태로 봄)."""
    calls = []
    monkeypatch.setattr(player, "open_file", lambda *got: calls.append(("open_file",) + got))
    monkeypatch.setattr(player, "select_folder", lambda *got: calls.append(("select_folder",) + got))
    return calls


def key_event(key, text="", modifiers=Qt.NoModifier, repeat=False):
    return QKeyEvent(QEvent.KeyPress, key, modifiers, text, repeat)


def test_shortcut_table_is_the_four_keys_and_their_menu_items():
    assert player_menus.KEY_SHORTCUTS == tuple((key, hangul, text_key) for key, _latin, hangul, text_key in KEY_CASES)


def test_menu_texts_name_the_shortcut_keys():
    for key, _hangul, text_key in player_menus.KEY_SHORTCUTS:
        for code in ui_text.LANGUAGES:
            assert ui_text.TEXTS[text_key][code].endswith(f" ({chr(key)})"), (text_key, code)


def test_o_and_i_keys_open_video_a_and_a_folder(player, key_calls):
    press(player, Qt.Key_O, "o")
    press(player, 0, "ㅐ")
    assert key_calls == [("open_file", "A"), ("open_file", "A")]
    del key_calls[:]
    press(player, Qt.Key_I, "i")
    press(player, 0, "ㅑ")
    assert key_calls == [("select_folder",), ("select_folder",)]


def test_capital_letters_work_too(player, key_calls):
    """Caps Lock·Shift — 키 값은 같고 글자만 대문자."""
    player.keyPressEvent(key_event(Qt.Key_O, "O", Qt.ShiftModifier))
    assert key_calls == [("open_file", "A")]


def test_l_key_toggles_loop_like_the_button(shown):
    press(shown, Qt.Key_L, "l")
    assert shown.loopCheckBox.isChecked() and shown.loopEnabled
    open_menu(shown, "playback")
    assert checked(shown, "menu.playback.loop")
    press(shown, 0, "ㅣ")
    assert not shown.loopCheckBox.isChecked() and not shown.loopEnabled


def test_w_key_toggles_wipe_like_the_button(shown):
    press(shown, Qt.Key_W, "w")
    assert shown.wipeCheckBox.isChecked() and shown.videoWidget.wipeEnabled
    assert shown.wipeXButton.isEnabled() and shown.wipeYButton.isEnabled()
    open_menu(shown, "compare")
    assert checked(shown, "menu.compare.wipe")
    press(shown, 0, "ㅈ")
    assert not shown.wipeCheckBox.isChecked() and not shown.videoWidget.wipeEnabled


def test_shortcut_keys_are_taken_by_the_event_filter_from_every_list(player, key_calls):
    """목록(Mov·Seq·All)이 포커스를 가진 채 누른 키도 창의 필터가 받음 — 목록의 글자 찾기(타이핑으로 줄 고르기)로 가지 않음."""
    for source in (player.sidebar, player.seq_sidebar, player.all_sidebar):
        del key_calls[:]
        assert player.eventFilter(source, key_event(Qt.Key_O, "o")) is True
        assert player.eventFilter(source, key_event(0, "ㅑ")) is True
        assert key_calls == [("open_file", "A"), ("select_folder",)]
        loop, wipe = player.loopCheckBox.isChecked(), player.wipeCheckBox.isChecked()
        assert player.eventFilter(source, key_event(Qt.Key_L, "l")) is True
        assert player.eventFilter(source, key_event(0, "ㅈ")) is True
        assert player.loopCheckBox.isChecked() is not loop and player.wipeCheckBox.isChecked() is not wipe


def test_shortcut_keys_work_through_real_key_presses_on_a_focused_list(shown, qapp):
    shown.sidebar.setFocus()
    qapp.processEvents()
    QTest.keyClick(shown.sidebar, Qt.Key_L)
    assert shown.loopCheckBox.isChecked()
    QTest.keyClick(shown.sidebar, Qt.Key_W)
    assert shown.wipeCheckBox.isChecked()


@pytest.mark.parametrize("modifier", [Qt.ControlModifier, Qt.AltModifier, Qt.MetaModifier])
def test_keys_with_ctrl_alt_or_meta_are_not_these_shortcuts(player, key_calls, monkeypatch, modifier):
    """Ctrl+O는 오버레이 컨트롤 위치 되돌리기(예전 그대로) — 다른 조합 키도 이 단축키로 치지 않음."""
    resets = []
    monkeypatch.setattr(player, "reset_overlay_position", lambda: resets.append(True))
    monkeypatch.setattr(player, "force_focus", lambda: None)
    for key, latin, _hangul, _text_key in KEY_CASES:
        player.keyPressEvent(key_event(key, latin, modifier))
        player.eventFilter(player.sidebar, key_event(key, latin, modifier))
    assert key_calls == []
    assert not player.loopCheckBox.isChecked() and not player.wipeCheckBox.isChecked()
    assert bool(resets) is (modifier == Qt.ControlModifier)  # Ctrl+O만 — 목록 포커스의 필터가 받음


def test_a_held_key_does_not_repeat_the_action(player, key_calls):
    """누르고 있을 때의 자동 반복은 삼킴 — 반복·와이프가 깜빡이거나 파일 창이 거듭 뜨지 않게."""
    player.keyPressEvent(key_event(Qt.Key_L, "l", repeat=True))
    assert player.eventFilter(player.sidebar, key_event(Qt.Key_W, "w", repeat=True)) is True
    player.keyPressEvent(key_event(Qt.Key_O, "o", repeat=True))
    assert not player.loopCheckBox.isChecked() and not player.wipeCheckBox.isChecked() and key_calls == []


def test_typing_in_an_input_field_is_not_a_shortcut(shown, qapp, key_calls):
    """글자를 치는 칸(프레임 번호·OCR 패턴)에서 친 o·i·l·w는 그 칸의 것 — 창까지 오지 않음."""
    shown.show_tool_panel("ocr")
    shown.ocrPatternLineEdit.setVisible(True)  # 사용자 패턴 방식에서만 보이는 칸 — 여기서는 키가 어디로 가는지만 봄
    shown.ocrPatternLineEdit.setEnabled(True)
    qapp.processEvents()
    for field in (shown.transportBar.frameField, shown.ocrPatternLineEdit):
        field.setFocus()
        qapp.processEvents()
        assert field.hasFocus(), field.objectName()
        QTest.keyClicks(field, "oilw")
    assert key_calls == []
    assert not shown.loopCheckBox.isChecked() and not shown.wipeCheckBox.isChecked()
    assert shown.ocrPatternLineEdit.text().endswith("oilw")
