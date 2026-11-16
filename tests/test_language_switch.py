"""화면 언어 바꾸기 — Settings → 언어 (Language) (UI 개편 PR 3, `player_language.PlayerLanguageMixin`).

고르면 이 창에 바로 적용되고(`retranslate_ui` — 영역마다의 다시 그리기 함수를 차례로) 이 PC의 prefs.json에 저장된다.
이미 열린 다른 창(프로세스)은 다음에 켤 때부터. 환경 변수 `YESONCHECK_LANGUAGE`가 정한 창에서는 메뉴가 꺼져 있다.

이 파일의 시험은 그 환경 변수를 지우고 돈다(보통 사용자의 창처럼) — conftest는 다른 시험을 위해 `ko`로 고정해 둔다.
"""

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from tests import ui_texts
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import hover_strip, mac_prefs, player_language, ui_language, ui_text


@pytest.fixture(autouse=True)
def _no_language_override(monkeypatch):
    monkeypatch.delenv(ui_language.ENV, raising=False)
    ui_language.set_source(ui_language.SOURCE_OS)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path / "config"), {}))


@pytest.fixture
def shown(player, qapp):
    player.resize(1400, 860)
    player.show()
    QApplication.setActiveWindow(player)
    QTest.qWait(250)
    return player


def settings_menu(player):
    return next(action.menu() for action in player.menuBar().actions() if action.text() == "&Settings")


def checks(player):
    return {code: action.isChecked() for code, action in player.language_actions.items()}


# ---------------------------------------------------------------- 메뉴

def test_language_menu_is_the_last_settings_item_with_two_choices(player):
    actions = settings_menu(player).actions()
    assert actions[-1].menu() is player.language_menu and actions[-2].isSeparator()
    assert player.language_menu.title() == "언어 (Language)"
    assert [action.text() for action in player.language_menu.actions()] == ["한국어", "English"]
    assert list(player.language_actions) == ["ko", "en"]
    assert all(action.isCheckable() and action.isEnabled() for action in player.language_actions.values())
    assert checks(player) == {"ko": True, "en": False}
    assert player.language_menu.toolTipsVisible()
    assert player.language_actions["en"].toolTip() == ui_text.text("settings.language.tip")


def test_menu_shows_the_language_the_window_started_in(new_player, dialogs, tmp_path):  # noqa: F811
    ui_text.set_language("en")
    player = new_player(make_config(str(tmp_path / "config"), {}))
    assert checks(player) == {"ko": False, "en": True}


# ---------------------------------------------------------------- 고르기

def test_choosing_english_changes_this_window_at_once_and_is_saved(shown, capsys):
    shown.show_tool_panel("annotation")
    shown.language_actions["en"].trigger()
    assert ui_text.language() == "en" and ui_language.source() == ui_language.SOURCE_MENU
    assert shown.transportBar.playButton.toolTip() == "Play (Space)"
    assert shown.openFolderButton.text() == "Open folder"
    assert shown.menu_actions["menu.playback.loop"].text() == "Loop playback (L)"
    assert shown.toolPanel.findChild(type(shown.workLabel), "toolPanelTitle").text() == "Annotations"
    assert mac_prefs.read_prefs(hover_strip.prefs_path())["ui_language"] == "en"
    assert checks(shown) == {"ko": False, "en": True}
    assert shown.language_actions["ko"].toolTip() == ui_text.text("settings.language.tip")  # 툴팁도 새 언어로
    assert "[언어] 설정: English (Settings 메뉴)" in capsys.readouterr().out


def test_switching_back_restores_every_text(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    before = ui_texts.collect(shown)
    shown.set_ui_language("en")
    assert ui_texts.collect(shown) != before
    shown.set_ui_language("ko")
    assert ui_texts.collect(shown) == before


def test_choice_keeps_the_other_settings(shown):
    mac_prefs.update_pref("slider_thumbnails", False, hover_strip.prefs_path())
    shown.set_ui_language("en")
    assert mac_prefs.read_prefs(hover_strip.prefs_path()) == {"slider_thumbnails": False, "ui_language": "en"}


def test_clicking_the_checked_language_keeps_it_checked_and_writes_nothing(shown, monkeypatch):
    saves = []
    monkeypatch.setattr(player_language.ui_language, "save", lambda code, path=None: saves.append(code))
    shown.language_actions["ko"].trigger()  # Qt는 체크된 항목을 누르면 체크를 끔 — 되맞춰야 함
    assert checks(shown) == {"ko": True, "en": False} and saves == [] and ui_text.language() == "ko"


def test_unknown_code_is_rejected_before_anything_changes(shown, monkeypatch):
    saves = []
    monkeypatch.setattr(player_language.ui_language, "save", lambda code, path=None: saves.append(code))
    with pytest.raises(ValueError):
        shown.set_ui_language("jp")
    assert saves == [] and ui_text.language() == "ko" and checks(shown) == {"ko": True, "en": False}


@pytest.mark.parametrize("error", [OSError("disk"), TimeoutError("lock")])
def test_failed_save_keeps_the_language_and_tells(shown, monkeypatch, capsys, error):
    shown_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text, *rest: shown_boxes.append((title, text)))

    def failing_save(code, path=None):
        raise error

    monkeypatch.setattr(player_language.ui_language, "save", failing_save)
    shown.language_actions["en"].trigger()
    assert ui_text.language() == "ko" and checks(shown) == {"ko": True, "en": False}
    assert shown.openFolderButton.text() == "폴더 열기"
    assert len(shown_boxes) == 1 and shown_boxes[0][0] == ui_language.SETTINGS_TITLE
    assert "Traceback" in capsys.readouterr().err


def test_broken_prefs_file_is_not_overwritten(shown, monkeypatch):
    import os

    shown_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text, *rest: shown_boxes.append(title))
    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{")
    shown.language_actions["en"].trigger()
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "{"
    assert ui_text.language() == "ko" and shown_boxes == [ui_language.SETTINGS_TITLE]


def test_unknown_value_in_the_file_is_replaced_by_the_choice(shown):
    import os

    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"ui_language": "jp", "other": 1}')
    shown.language_actions["en"].trigger()
    assert mac_prefs.read_prefs(path) == {"ui_language": "en", "other": 1} and ui_text.language() == "en"


def test_environment_override_disables_the_menu(shown, monkeypatch):
    """환경 변수가 언어를 정한 창: 두 항목이 꺼져 있고 툴팁이 까닭을 말함 — 꺼진 항목을 실행해도(trigger) 바뀌지 않음."""
    monkeypatch.setenv(ui_language.ENV, "ko")
    shown._sync_language_menu()
    assert not any(action.isEnabled() for action in shown.language_actions.values())
    assert "YESONCHECK_LANGUAGE" in shown.language_actions["en"].toolTip()
    shown.language_actions["en"].trigger()
    assert ui_text.language() == "ko" and checks(shown) == {"ko": True, "en": False}


# ---------------------------------------------------------------- 다시 그리기

def test_retranslate_ui_calls_every_area_once_in_order(shown, monkeypatch):
    calls = []
    for name in shown.RETRANSLATORS:
        monkeypatch.setattr(shown, name, lambda name=name: calls.append(name))
    monkeypatch.setattr(shown.transportBar, "retranslate", lambda: calls.append("transportBar"))
    monkeypatch.setattr(shown.toolPanel, "retranslate", lambda: calls.append("toolPanel"))
    shown.retranslate_ui()
    assert calls == ["transportBar", "toolPanel", *shown.RETRANSLATORS]


def test_every_retranslator_is_a_real_method(player):
    assert len(set(player.RETRANSLATORS)) == len(player.RETRANSLATORS)
    assert all(callable(getattr(player, name)) for name in player.RETRANSLATORS)


# ---------------------------------------------------------------- 최소 너비는 언어와 무관 (ShrinkButton)

def sidebar_minimums(player):
    QApplication.processEvents()
    return player.mainSplitter.widget(0).minimumSizeHint().width(), player.minimumSizeHint().width()


def sidebar_buttons(player):
    return (player.openFolderButton, player.bookmarkMenuButton, player.refreshListButton, player.listModeButton,
            player.thumbnailModeButton, player.playlistButton)


def cut_texts(player):
    """글이 줄어(…) 그려지는 사이드바 단추의 (온 글, 그려지는 글)."""
    QApplication.processEvents()
    return [(button.text(), button.drawn_text()) for button in sidebar_buttons(player) if button.drawn_text() != button.text()]


def test_sidebar_and_window_minimum_widths_do_not_depend_on_language(shown):
    """English 글이 더 길어도 사이드바·창의 최소 너비가 같음 — 안 그러면 언어를 바꿀 때 창이 저절로 넓어질 수 있음."""
    korean = sidebar_minimums(shown)
    shown.set_ui_language("en")
    assert sidebar_minimums(shown) == korean
    shown.set_ui_language("ko")
    assert sidebar_minimums(shown) == korean


def test_sidebar_at_its_start_width_follows_the_language_and_comes_back(shown):
    """처음 폭 그대로인 사이드바: 언어를 바꾸면 그 언어의 단추 글이 다 들어가는 처음 폭으로(영상 칸에서 가져옴), 되돌리면 돌아옴."""
    korean = shown.mainSplitter.sizes()
    assert korean[0] == shown.sidebar_start_width() and cut_texts(shown) == []
    shown.set_ui_language("en")
    english = shown.mainSplitter.sizes()
    assert english[0] == shown.sidebar_start_width() >= korean[0] and cut_texts(shown) == []
    assert sum(english) == sum(korean) and english[2] == korean[2]  # 창·도구 패널은 그대로 — 차이는 영상 칸이 냄
    shown.set_ui_language("ko")
    assert shown.mainSplitter.sizes() == korean and cut_texts(shown) == []


def test_window_started_in_english_shows_the_whole_button_texts(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    ui_text.set_language("en")
    player = new_player(make_config(str(tmp_path / "config"), {}))
    player.show()
    QTest.qWait(250)
    assert player.mainSplitter.sizes()[0] == player.sidebar_start_width() and cut_texts(player) == []


def test_sidebar_width_set_by_hand_is_kept(shown):
    """손으로 맞춘 폭(처음 폭이 아님)은 언어를 바꿔도 건드리지 않음 — 넓혀 둔 것도 좁혀 둔 것도."""
    for moved in (31, -6):
        sizes = shown.mainSplitter.sizes()
        shown.mainSplitter.setSizes([sizes[0] + moved, sizes[1] - moved, sizes[2]])
        by_hand = shown.mainSplitter.sizes()
        assert by_hand[0] != shown.sidebar_start_width()
        shown.set_ui_language("en")
        assert shown.mainSplitter.sizes() == by_hand
        shown.set_ui_language("ko")
        assert shown.mainSplitter.sizes() == by_hand


def test_sidebar_stays_when_the_video_column_has_no_room_to_give(shown):
    """영상 칸이 최소 너비 가까이면 사이드바를 넓히지 않음(영상 칸을 최소 너비 아래로 밀지 않음) — 단추 글은 줄여 그림."""
    shown.set_ui_language("en")
    wanted = shown.sidebar_start_width()
    shown.set_ui_language("ko")
    start = shown.sidebar_start_width()
    if wanted == start:
        pytest.skip("이 글꼴에서는 English 단추 글이 한국어의 처음 폭에 다 들어감")
    # 영상 칸이 최소 너비 가까이 가는 것은 도구 패널을 연 좁은 창에서 (패널이 닫힌 창은 재생 줄의 최소 너비가 먼저 막음)
    shown.show_tool_panel("annotation")
    QApplication.processEvents()
    splitter = shown.mainSplitter
    video = splitter.widget(1).minimumSizeHint().width() + (wanted - start) - 1  # 줄 자리가 1px 모자람
    panel = splitter.widget(2).minimumSizeHint().width()
    shown.resize(shown.width() + (start + video + panel) - sum(splitter.sizes()), shown.height())
    QApplication.processEvents()
    splitter.setSizes([start, video, panel])
    tight = splitter.sizes()
    assert tight == [start, video, panel]  # 전제: 사이드바는 처음 폭, 영상 칸은 최소 너비 + (필요한 폭 − 1)
    shown.set_ui_language("en")
    assert splitter.sizes() == tight and cut_texts(shown) != []
    shown.resize(shown.width() + 1, shown.height())  # 1px만 넓어도(그 1px은 영상 칸으로) 옮길 자리가 됨
    QApplication.processEvents()
    shown.set_ui_language("ko")
    assert splitter.sizes()[0] == start
    shown.set_ui_language("en")
    assert splitter.sizes()[0] == wanted and cut_texts(shown) == []


def test_list_mode_returns_to_the_width_of_the_language_in_use(shown):
    """언어를 바꿔 옮긴 처음 폭은 목록 모드로 돌아올 때의 폭이기도 함(썸네일 모드는 그 두 배)."""
    QTest.qWait(250)  # 켠 뒤 200ms에 기본 목록 폭을 적음 (initialize_sidebar_width)
    shown.set_ui_language("en")
    english = shown.mainSplitter.sizes()
    shown.switch_to_thumbnail_mode()
    QApplication.processEvents()
    assert shown.mainSplitter.sizes()[0] > english[0]
    shown.switch_to_list_mode()
    QApplication.processEvents()
    assert shown.mainSplitter.sizes() == english and cut_texts(shown) == []


def test_shrink_buttons_measure_a_text_the_way_qt_does(shown):
    """ShrinkButton이 '그 글을 넣은 단추가 바랄 너비'를 스스로 재는 계산 = Qt의 sizeHint (이 창의 시트 아래, 두 언어)."""
    for code in ("ko", "en"):
        shown.set_ui_language(code)
        for button in (*sidebar_buttons(shown), shown.endPlaylistButton):
            assert button._hint_width(button.text()) == button.sizeHint().width(), (code, button.text())


def test_cut_sidebar_button_tells_its_whole_text_in_a_tooltip(shown, monkeypatch):
    """손으로 좁힌 사이드바에서 줄어 그려지는 단추: 자기 툴팁이 없으면 온 글이 툴팁, 있으면(새로고침) 그 툴팁 그대로."""
    from PyQt5.QtCore import QEvent, QPoint
    from PyQt5.QtGui import QHelpEvent
    from yesoncheck import window_layout

    shown.set_ui_language("en")
    sizes = shown.mainSplitter.sizes()
    least = shown.mainSplitter.widget(0).minimumSizeHint().width()
    shown.mainSplitter.setSizes([least, sizes[1] + sizes[0] - least, sizes[2]])
    cut = dict(cut_texts(shown))
    if "Open folder" not in cut or "Refresh" not in cut:
        pytest.skip("이 글꼴에서는 최소 너비의 사이드바에도 English 단추 글이 다 들어감")
    tips = []
    monkeypatch.setattr(window_layout.QToolTip, "showText", lambda _pos, text, *_rest: tips.append(text))

    def hover(button):
        spot = QPoint(3, 3)
        return QApplication.sendEvent(button, QHelpEvent(QEvent.ToolTip, spot, button.mapToGlobal(spot)))

    hover(shown.openFolderButton)
    assert tips == ["Open folder"]
    hover(shown.refreshListButton)  # 자기 툴팁(목록 다시 읽기 (F5))이 있음 — 온 글로 덮지 않음
    assert tips == ["Open folder"] and shown.refreshListButton.toolTip() == ui_text.text("sidebar.refresh.tip")
    shown.mainSplitter.setSizes(sizes)
    assert cut_texts(shown) == []
    hover(shown.openFolderButton)  # 다 보이면 툴팁 없음
    assert tips == ["Open folder"]


def test_end_playlist_button_follows_the_language_without_widening_the_sidebar(shown):
    """'이어 재생 끝내기' 단추(선택 재생 중에만 보임): 글·툴팁이 언어를 따르고, 보이는 동안에도 최소 너비가 언어와 무관."""
    shown.is_playlist_playing = True  # setter가 단추를 보임
    try:
        assert shown.endPlaylistButton.isVisible()
        korean = sidebar_minimums(shown)
        shown.set_ui_language("en")
        assert shown.endPlaylistButton.text() == "End playlist"
        assert shown.endPlaylistButton.toolTip() == ui_text.TEXTS["playlist.end.tip"]["en"]
        assert sidebar_minimums(shown) == korean
        shown.set_ui_language("ko")
        assert shown.endPlaylistButton.text() == "이어 재생 끝내기"
        assert shown.endPlaylistButton.toolTip() == ui_text.TEXTS["playlist.end.tip"]["ko"]
        assert sidebar_minimums(shown) == korean
    finally:
        shown.is_playlist_playing = False


def test_shrink_button_minimum_is_the_narrowest_text_of_any_language(qapp, monkeypatch):
    from yesoncheck.window_layout import ShrinkButton

    monkeypatch.setitem(ui_text.TEXTS, "probe.short_ko", {"ko": "가", "en": "A much longer English label"})
    button = ShrinkButton()
    button.set_text_key("probe.short_ko")
    korean = (button.minimumSizeHint().width(), button.sizeHint().width())
    ui_text.set_language("en")
    button.set_text_key("probe.short_ko")
    english = (button.minimumSizeHint().width(), button.sizeHint().width())
    assert english[0] == korean[0] == korean[1]  # 최소 너비는 두 언어에서 같고, 짧은 쪽(한국어) 글의 바라는 너비
    assert english[1] > english[0]  # 바라는 너비는 지금 글 전체
    button.deleteLater()


def test_shrink_tool_button_follows_the_same_rule(qapp, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMenu, QToolButton
    from yesoncheck.window_layout import ShrinkToolButton

    monkeypatch.setitem(ui_text.TEXTS, "probe.short_ko", {"ko": "가", "en": "A much longer English label"})
    button = ShrinkToolButton()
    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    button.setPopupMode(QToolButton.InstantPopup)
    button.setMenu(QMenu(button))
    button.set_text_key("probe.short_ko")
    korean = (button.minimumSizeHint().width(), button.sizeHint().width())
    assert button._hint_width(button.text()) == korean[1]  # 스스로 잰 너비 = Qt의 sizeHint
    ui_text.set_language("en")
    button.set_text_key("probe.short_ko")
    english = (button.minimumSizeHint().width(), button.sizeHint().width())
    assert button._hint_width(button.text()) == english[1]
    assert english[0] == korean[0] == korean[1] and english[1] > english[0]
    button.resize(english[0] + 30, button.sizeHint().height())
    assert button.drawn_text().endswith("…") and button.text() == "A much longer English label"
    button.show()
    button.repaint()  # 그리기가 예외 없이 돎
    button.deleteLater()


def test_shrink_button_hint_is_the_plain_button_hint(qapp):
    """글이 다 들어가는 폭에서는 보통 단추와 같은 크기 — 한국어 화면의 배치가 달라지지 않게."""
    from PyQt5.QtWidgets import QPushButton
    from yesoncheck.window_layout import ShrinkButton

    plain = QPushButton(ui_text.text("sidebar.open_folder"))
    button = ShrinkButton()
    button.set_text_key("sidebar.open_folder")
    assert button.sizeHint() == plain.sizeHint() and button.text() == plain.text()
    plain.deleteLater()
    button.deleteLater()


def test_shrink_button_draws_an_elided_text_when_it_is_too_narrow(qapp, monkeypatch):
    from yesoncheck.window_layout import ShrinkButton

    monkeypatch.setitem(ui_text.TEXTS, "probe.long_en", {"ko": "가", "en": "A much longer English label"})
    ui_text.set_language("en")
    button = ShrinkButton()
    button.set_text_key("probe.long_en")
    button.resize(button.sizeHint())
    assert button.drawn_text() == button.text() == "A much longer English label"
    button.resize(button.minimumSizeHint().width() + 30, button.sizeHint().height())
    assert button.drawn_text() != button.text() and button.drawn_text().endswith("…")
    assert button.text() == "A much longer English label"  # 글 자체는 그대로 — 그릴 때만 줄임
    button.show()
    button.repaint()  # 그리기가 예외 없이 돎
    button.deleteLater()


def test_shrink_button_counts_the_other_states_of_the_same_button(qapp):
    """선택 재생 단추처럼 글이 상태에 따라 바뀌는 단추: 최소 너비가 상태를 따라 움직이지 않음."""
    from yesoncheck.window_layout import ShrinkButton

    button = ShrinkButton()
    button.set_text_key("playlist.play", also=("playlist.pause",))
    playing = button.minimumSizeHint().width()
    button.set_text_key("playlist.pause", also=("playlist.play",))
    assert button.minimumSizeHint().width() == playing
    button.deleteLater()
