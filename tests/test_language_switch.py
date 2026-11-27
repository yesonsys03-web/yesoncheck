"""화면 언어 바꾸기 — Settings → 언어 (Language) (UI 개편 PR 3, `player_language.PlayerLanguageMixin`).

고르면 이 창에 바로 적용되고(`retranslate_ui` — 영역마다의 다시 그리기 함수를 차례로) 이 PC의 prefs.json에 저장된다.
이미 열린 다른 창(프로세스)은 다음에 켤 때부터. 환경 변수 `YESONCHECK_LANGUAGE`가 정한 창에서는 메뉴가 꺼져 있다.

이 파일의 시험은 그 환경 변수를 지우고 돈다(보통 사용자의 창처럼) — conftest는 다른 시험을 위해 `ko`로 고정해 둔다.
"""

import os
import sys

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from tests import ui_texts
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import (app as app_module, default_app, file_associations, gl_video_item, hover_strip, mac_native_gate,
                        mac_native_source, mac_prefs, player_base, player_language, ui_language, ui_text, windows_display)

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="Mac에서만 만드는 메뉴(재생 디코더)")


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


def test_choosing_the_fallback_language_fixes_an_unknown_value_in_the_file(shown, dialogs):
    """시작 때 모르는 값(jp)으로 이 세션만 한국어가 된 창: 경고 창이 약속한 대로 메뉴에서 '한국어'를 고르면 — 이미 한국어로
    보이고 있어도 — 파일을 그 값으로 고침(다음에 켤 때 같은 경고가 다시 뜨지 않게). 다른 키는 그대로."""
    import os

    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"ui_language": "jp", "other": 1}')
    app_module.load_language()
    assert ui_text.language() == "ko" and ui_language.source() == ui_language.SOURCE_FALLBACK
    shown.language_actions["ko"].trigger()
    assert mac_prefs.read_prefs(path) == {"ui_language": "ko", "other": 1}
    assert ui_text.language() == "ko" and ui_language.source() == ui_language.SOURCE_MENU
    assert checks(shown) == {"ko": True, "en": False}


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
    # 영상 칸이 최소 너비 가까이 가는 것은 도구 패널을 연 좁은 창에서 (패널이 닫힌 창은 재생 줄의 최소 너비가 먼저 막음)
    shown.show_tool_panel("annotation")
    splitter = shown.mainSplitter
    shown.set_ui_language("en")
    QApplication.processEvents()
    wanted, panel_english = shown.sidebar_start_width(), splitter.widget(2).minimumSizeHint().width()
    shown.set_ui_language("ko")
    QApplication.processEvents()
    start = shown.sidebar_start_width()
    if wanted == start:
        pytest.skip("이 글꼴에서는 English 단추 글이 한국어의 처음 폭에 다 들어감")
    video = splitter.widget(1).minimumSizeHint().width() + (wanted - start) - 1  # 줄 자리가 1px 모자람
    # 패널은 두 언어 중 넓은 쪽의 최소 너비로 — 글꼴 없는 환경(영문 글자도 한글만큼 넓게 잼)에서는 English 패널이 더 넓어
    # 언어를 바꿀 때 패널이 영상·사이드바의 몫을 가져가면 이 시험이 보려는 것(영상 칸의 자리)이 흐려짐
    panel = max(splitter.widget(2).minimumSizeHint().width(), panel_english)
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


# ---------------------------------------------------------------- Settings·Help 메뉴 (Task 4)

LANGUAGE_NAMES = ["언어 (Language)", "한국어"]  # 두 언어에서 같은 글 — English 화면의 메뉴 막대에 남는 한글은 이것뿐
ENV_TIP_KO = "환경 변수 YESONCHECK_MAC_NATIVE={value}{josa} 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
ENV_TIP_EN = ("The environment variable YESONCHECK_MAC_NATIVE={value} takes precedence — remove it and restart the app to use "
              "this setting")


def test_english_menubar_keeps_only_the_language_names(shown):
    shown.set_ui_language("en")
    assert ui_texts.hangul(ui_texts.menubar_texts(shown)) == LANGUAGE_NAMES


def test_help_and_settings_items_are_not_moved_to_the_mac_app_menu(player):
    """English 글('About'·'… settings…')을 보고 macOS가 항목을 앱 메뉴로 옮기지 않게 — 두 메뉴의 항목은 모두 NoRole."""
    from PyQt5.QtWidgets import QAction

    def items(menu):
        for action in menu.actions():
            if action.isSeparator():
                continue
            yield action
            if action.menu() is not None:
                yield from items(action.menu())

    for title in ("&Settings", "&Help"):
        menu = next(action.menu() for action in player.menuBar().actions() if action.text() == title)
        assert [action.text() for action in items(menu) if action.menuRole() != QAction.NoRole] == [], title


@pytest.fixture
def windows_player(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    """Windows에서만 만드는 메뉴(화면 그리기·축소 필터·공유 설정 폴더·기본 앱 설정)를 가진 창 — 플랫폼 표지를 바꿔 끼움."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(file_associations, "IS_WINDOWS", True)
    monkeypatch.setattr(default_app, "IS_MAC", False)
    player = new_player(make_config(str(tmp_path / "config"), {}))
    if player.shared_config_action is None:  # 진짜 Windows에서는 창이 이미 만들었음 (paths.IS_WINDOWS)
        player._add_shared_config_action(settings_menu(player))
    return player


def test_windows_settings_and_help_follow_the_language(windows_player):
    player = windows_player
    korean = ui_texts.menubar_texts(player)
    for text in ("화면 그리기 (Windows)", "CPU (기본)", "GPU", "지금 이 창: CPU", "축소 필터 (Windows)", "Linear (기본)",
                 "고품질 (면적 평균)", "슬라이더 썸네일", "공유 설정 폴더 변경...", "사용법", "업데이트 확인…",
                 "동영상 기본 앱 설정 열기…", "정보", "이 PC의 설정 파일(prefs.json)에 저장합니다 — 다음에 여는 창부터 적용됩니다"):
        assert text in korean, text
    player.set_ui_language("en")
    english = ui_texts.menubar_texts(player)
    assert ui_texts.hangul(english) == LANGUAGE_NAMES
    assert "This window: CPU" in english and len(english) == len(korean)
    player.set_ui_language("ko")
    assert ui_texts.menubar_texts(player) == korean


def test_display_menu_env_tooltip_follows_the_language(windows_player, monkeypatch):
    monkeypatch.setenv(player_base.VIEWPORT_ENV, "raster")
    windows_player._sync_display_menu()
    tip = windows_player.display_actions["gpu"].toolTip()
    assert tip == "YESONCHECK_VIEWPORT=raster가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
    windows_player.set_ui_language("en")
    assert windows_player.display_actions["gpu"].toolTip() == (
        "YESONCHECK_VIEWPORT=raster takes precedence — remove it and restart the app to use this setting")


def test_every_decoder_source_shown_in_the_menu_has_a_text():
    """메뉴 툴팁에 보이는 출처(설정 파일·기본값·환경 변수가 아닌 것)마다 글자 표의 글이 있고, 한국어 글은 출처 글 그대로."""
    shown_sources = {value for name, value in vars(mac_native_gate).items() if name.startswith("SOURCE_")}
    shown_sources -= {mac_native_gate.SOURCE_PREFS, mac_native_gate.SOURCE_DEFAULT}
    assert set(player_base.DECODER_SOURCE_KEYS) == shown_sources
    for source, key in player_base.DECODER_SOURCE_KEYS.items():
        assert ui_text.TEXTS[key]["ko"] == source


@mac_only
@pytest.mark.parametrize("source", [mac_native_gate.SOURCE_FALLBACK, mac_native_gate.SOURCE_GL_FALLBACK])
def test_decoder_tooltip_names_the_source_in_the_current_language(new_player, dialogs, tmp_path, monkeypatch, source):  # noqa: F811
    monkeypatch.delenv(mac_native_gate.NATIVE_MODE_ENV, raising=False)
    mac_native_gate.set_preferred_decoder("ffmpeg", source=source)
    player = new_player(make_config(str(tmp_path / "config"), {}))
    key = player_base.DECODER_SOURCE_KEYS[source]
    assert player.decoder_actions["ffmpeg"].toolTip() == source
    player.set_ui_language("en")
    assert player.decoder_actions["ffmpeg"].toolTip() == ui_text.TEXTS[key]["en"]
    assert player.decoder_actions["videotoolbox"].toolTip() == ui_text.TEXTS["settings.decoder.tip"]["en"]
    assert [action.text() for action in player.decoder_action_group] == ["VideoToolbox (default)", "ffmpeg (legacy)"]


@mac_only
@pytest.mark.parametrize("value, josa", [("on", "이"), ("off", "가")])
def test_decoder_env_tooltip_in_both_languages(new_player, dialogs, tmp_path, monkeypatch, value, josa):  # noqa: F811
    monkeypatch.setenv(mac_native_gate.NATIVE_MODE_ENV, value)
    player = new_player(make_config(str(tmp_path / "config"), {}))
    assert player.decoder_actions["ffmpeg"].toolTip() == ENV_TIP_KO.format(value=value, josa=josa)
    player.set_ui_language("en")
    assert player.decoder_actions["ffmpeg"].toolTip() == ENV_TIP_EN.format(value=value)


@mac_only
def test_decoder_cv2_tooltip_in_both_languages(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("YESONCHECK_MOVIE_SOURCE", "cv2")
    player = new_player(make_config(str(tmp_path / "config"), {}))
    assert player.decoder_actions["ffmpeg"].toolTip() == (
        "YESONCHECK_MOVIE_SOURCE=cv2가 모든 빠른 디코더를 끕니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다")
    player.set_ui_language("en")
    assert player.decoder_actions["ffmpeg"].toolTip() == ui_text.TEXTS["settings.decoder.cv2_tip"]["en"]
    assert ui_texts.hangul([ui_text.TEXTS["settings.decoder.cv2_tip"]["en"]]) == []


def test_notices_quote_the_menu_name_that_is_on_screen():
    """메뉴 이름을 인용하는 알림 글(문장은 한글 그대로): 이름 자리는 지금 화면의 글 — 한국어 화면에서는 예전 글 그대로."""
    assert gl_video_item.decoder_menu_hint() == "Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식) 으로 바꾸면 예전 방식으로 재생합니다"
    assert gl_video_item.failure_menu_hint("win32") == (
        "Settings → 화면 그리기 (Windows) → CPU (기본)를 고르고 앱을 다시 켜면 CPU로 그립니다")
    assert mac_native_source.native_escape_hint() == (
        "탈출구(네이티브 재생을 끄고 ffmpeg 파이프로 엶): Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식) — 또는 환경 변수 "
        "YESONCHECK_MAC_NATIVE=off (그 실행만)")
    assert app_module.playback_decoder_fallback_note() == (
        "이 세션은 예전 방식(ffmpeg)으로 재생합니다 — Settings → 재생 디코더 (Mac)에서 바꿀 수 있습니다")
    assert windows_display.fallback_text("x").endswith("Settings → 화면 그리기 (Windows) → CPU (기본)를 고르면 이 알림이 뜨지 않습니다.")
    ui_text.set_language("en")
    assert "Settings → Playback decoder (Mac) → ffmpeg (legacy) " in gl_video_item.decoder_menu_hint()
    assert "Settings → Display rendering (Windows) → CPU (default)" in gl_video_item.failure_menu_hint("win32")
    assert "Settings → Playback decoder (Mac) → ffmpeg (legacy) " in mac_native_source.native_escape_hint()
    assert "Settings → Playback decoder (Mac)" in app_module.playback_decoder_fallback_note()
    assert "Settings → Display rendering (Windows) → CPU (default)" in windows_display.fallback_text("x")


def test_notices_in_english_put_a_korean_noun_before_the_particle():
    """한글 문장 안의 English 이름 뒤에는 조사를 고를 수 없음('Slider thumbnails을') — 이름 뒤에 한국어 명사를 붙여 그 명사의
    조사로 (리뷰 M-8). 한국어 화면의 글은 그대로 (위 시험)."""
    ui_text.set_language("en")
    assert gl_video_item.decoder_menu_hint() == (
        "Settings → Playback decoder (Mac) → ffmpeg (legacy) 항목으로 바꾸면 예전 방식으로 재생합니다")
    assert gl_video_item.failure_menu_hint("win32") == (
        "Settings → Display rendering (Windows) → CPU (default) 항목을 고르고 앱을 다시 켜면 CPU로 그립니다")
    assert windows_display.fallback_text("x").endswith(
        "Settings → Display rendering (Windows) → CPU (default) 항목을 고르면 이 알림이 뜨지 않습니다.")


def test_hover_failure_notice_in_english_puts_a_noun_before_the_particle(player, monkeypatch):
    from yesoncheck import error_window

    shown = []
    monkeypatch.setattr(error_window, "show_error", lambda prefix, text: shown.append(text))
    player._hover_path = "/a/clip.mov"
    player._hover_fail("x")
    ui_text.set_language("en")
    player._hover_path = "/a/other.mov"
    player._hover_fail("x")
    assert shown[0].endswith("Settings → 슬라이더 썸네일을 끄면 만들지 않습니다")
    assert shown[1].endswith("Settings → Slider thumbnails 항목을 끄면 만들지 않습니다")


@pytest.fixture
def startup_warnings(monkeypatch):
    texts = []
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda _parent, _title, text: texts.append(text))
    return texts


@pytest.mark.parametrize("code, ending", [
    ("ko", "Settings → 슬라이더 썸네일은 파일을 덮지 않습니다"),
    ("en", "Settings → Slider thumbnails 항목은 파일을 덮지 않습니다"),
])
def test_startup_warning_for_broken_thumbnail_setting_quotes_the_menu(startup_warnings, monkeypatch, code, ending):
    from yesoncheck import user_files

    def broken():
        raise user_files.UserFileError("깨진 설정 파일")

    monkeypatch.setattr(hover_strip, "read_enabled", broken)
    monkeypatch.setattr(hover_strip, "_enabled", True)
    ui_text.set_language(code)
    app_module.load_slider_thumbnails()
    assert startup_warnings[-1].endswith(ending)


@pytest.mark.parametrize("code, ending", [
    ("ko", "Settings → 축소 필터 (Windows)는 파일을 덮지 않습니다"),  # 예전 글은 '필터 (Windows)은'
    ("en", "Settings → Downscale filter (Windows) 항목은 파일을 덮지 않습니다"),
])
def test_startup_warning_for_broken_downscale_setting_quotes_the_menu(startup_warnings, monkeypatch, code, ending):
    from yesoncheck import downscale_filter, user_files

    def broken():
        raise user_files.UserFileError("깨진 설정 파일")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(downscale_filter, "read", broken)
    monkeypatch.setattr(downscale_filter, "_preferred", downscale_filter.DEFAULT_FILTER)
    ui_text.set_language(code)
    app_module.load_downscale_filter()
    assert startup_warnings[-1].endswith(ending)


def test_startup_warning_for_broken_language_setting_quotes_the_menu(startup_warnings, monkeypatch):
    """언어 메뉴의 이름은 두 언어에서 같은 글('언어 (Language)') — 조사는 '언어'에 맞춰 '는' (예전 글은 '은')."""
    from yesoncheck import user_files

    def broken():
        raise user_files.UserFileError("깨진 설정 파일")

    monkeypatch.setattr(ui_language, "read", broken)
    app_module.load_language()
    assert startup_warnings[-1].endswith("Settings → 언어 (Language)는 파일을 덮지 않습니다")


def test_launch_reads_the_language_before_the_other_settings(qapp, monkeypatch):
    """시작 때의 설정 경고 창(재생 디코더·화면 그리기 …)이 메뉴 이름을 화면의 언어로 인용하려면 언어를 가장 먼저 읽어야 함."""
    order = []
    for name in ("load_language", "load_playback_decoder", "load_display_renderer", "load_slider_thumbnails", "load_downscale_filter"):
        monkeypatch.setattr(app_module, name, lambda name=name: order.append(name))

    class Stop(Exception):
        pass

    def no_window(**_kwargs):
        raise Stop

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    with pytest.raises(Stop):
        app_module.launch(["yesoncheck"])
    assert order[0] == "load_language" and len(order) == 5


# ---------------------------------------------------------------- 사이드바 (Task 6)

def test_english_sidebar_has_no_hangul(shown, tmp_path):
    """English 화면의 사이드바: 안내 항목·개수 줄·정렬 단추·Seq 항목·진행 막대, 우클릭 메뉴(Mov·Seq·All·북마크·정렬), 창 제목 꼬리."""
    ui_texts.stage(shown, tmp_path)
    shown.set_ui_language("en")
    texts = ui_texts.collect(shown)
    for area in ("sidebar", "sidebar_menus", "title"):
        assert ui_texts.hangul(texts[area]) == [], area


def test_count_line_in_english():
    from yesoncheck import sidebar_counts, sidebar_take_colors

    ui_text.set_language("en")
    assert sidebar_counts.count_text("mov", ["a_TK1.mov"] * 2 + ["a_TK1_HD.mov"], []) == "3 items — Base 2 (TK1 2) · HD 1 (TK1 1)"
    assert sidebar_counts.count_text("mov", ["a.mov"], []) == "1 item"
    assert sidebar_counts.count_text("mov", [], []) == "0 items"
    assert sidebar_counts.count_text("seq", [], [("bg", "tga")] * 3) == "3 sequences"
    assert sidebar_counts.count_text("seq", [], [("bg", "tga")]) == "1 sequence"
    assert sidebar_counts.count_text("all", ["a.mov", "b.mp4"], [("bg", "tga")]) == "3 items — mov 1 · mp4 1 · tga 1"
    assert sidebar_counts.count_text("all", [], []) == "0 items"
    assert sidebar_counts.count_text("mov", ["s_TK1.mov", "s_TK2.mov", "s2.mov"], []) == "3 items — Base 3 (TK1 1 · TK2 1 · none 1)"
    # 버전·테이크 토막의 색(목록과 같은 색)은 영문 줄에서도 — 괄호 안의 'TK2 5' 꼴만 보고 칠함
    assert "<span" in sidebar_take_colors.count_line_html("5 items — Base 5 (TK2 5)", "dark")


def test_count_line_in_korean_is_what_it_was():
    from yesoncheck import sidebar_counts

    assert sidebar_counts.count_text("mov", ["a_TK1.mov"] * 2 + ["a_TK1_HD.mov"], []) == "3개 — 기본 2 (TK1 2) · HD 1 (TK1 1)"
    assert sidebar_counts.count_text("mov", ["a.mov"], []) == "1개"
    assert sidebar_counts.count_text("seq", [], [("bg", "tga")]) == "시퀀스 1개"
    assert sidebar_counts.count_text("all", [], []) == "0개"
    assert sidebar_counts.count_text("mov", ["s_TK1.mov", "s_TK2.mov", "s2.mov"], []) == "3개 — 기본 3 (TK1 1 · TK2 1 · 없음 1)"


def test_sort_texts_by_language():
    from yesoncheck import sidebar_sort

    assert sidebar_sort.button_texts("kind") == ("정렬: 종류 ▾", "종류 ▾", "↕")
    assert [sidebar_sort.label(mode) for mode in sidebar_sort.MODES] == ["이름", "종류", "버전", "시간"]
    ui_text.set_language("en")
    assert sidebar_sort.button_texts("kind") == ("Sort: Kind ▾", "Kind ▾", "↕")
    assert [sidebar_sort.label(mode) for mode in sidebar_sort.MODES] == ["Name", "Kind", "Version", "Time"]
    assert ui_texts.hangul([sidebar_sort.tip(mode) for mode in sidebar_sort.MODES] + [sidebar_sort.button_tip()]) == []


def test_sort_button_and_its_menu_follow_the_language(shown, capsys):
    from yesoncheck import sidebar_sort

    shown.set_ui_language("en")
    menu = shown.sidebar_sort_button.menu()
    assert [action.text() for action in menu.actions()] == ["Name", "Kind", "Version", "Time"]
    assert [action.toolTip() for action in menu.actions()] == [sidebar_sort.tip(mode) for mode in sidebar_sort.MODES]
    assert shown.sidebar_sort_button.toolTip() == f"Sort: Name ▾\n{sidebar_sort.button_tip()}"
    assert shown.sidebar_sort_button.text() in sidebar_sort.button_texts("name")
    capsys.readouterr()
    shown.set_sidebar_sort("kind")
    assert shown.sidebar_sort_button.toolTip().startswith("Sort: Kind ▾\n")
    assert "[정렬] 사이드바: 종류" in capsys.readouterr().out  # 기록 줄은 한글 그대로
    shown.set_ui_language("ko")
    assert [action.text() for action in menu.actions()] == ["이름", "종류", "버전", "시간"]
    assert shown.sidebar_sort_button.toolTip().startswith("정렬: 종류 ▾\n")


def test_placeholders_follow_the_language_without_reading_any_folder(new_player, dialogs, work_area, monkeypatch):  # noqa: F811
    """작품·시즌·job 콤보의 안내 항목만 글이 바뀜 — 고른 것·목록은 그대로이고 어떤 폴더도 다시 읽지 않음."""
    from tests.test_sidebar_refresh import choose, listed
    from tests.test_work_season_job import season_player
    from tests.test_work_paths_ui import combo_items
    from yesoncheck import video_list

    player = season_player(new_player, work_area)
    assert (player.workComboBox.itemText(0), player.seasonComboBox.itemText(0), player.jobComboBox.itemText(0)) == (
        "작품선택", "시즌선택", "job선택")
    player.workComboBox.setCurrentIndex(1)  # 시험용 작품의 첫 작품 → 첫 시즌 → 첫 job (이름은 도우미가 정함)
    player.seasonComboBox.setCurrentIndex(1)
    choose(player, player.jobComboBox.itemText(1))
    QApplication.processEvents()
    before = (combo_items(player.workComboBox)[1:], combo_items(player.seasonComboBox)[1:], combo_items(player.jobComboBox)[1:],
              player.workComboBox.currentIndex(), player.seasonComboBox.currentIndex(), player.jobComboBox.currentIndex(),
              listed(player))
    assert len(before[-1]) == 1 and before[3:6] == (1, 1, 1)  # job의 영상 하나가 목록에 — 세 콤보 모두 고른 상태
    scans, listings = [], []
    real_listdir = os.listdir
    monkeypatch.setattr(video_list, "scan_job", lambda *args: scans.append(args))
    monkeypatch.setattr(os, "listdir", lambda path=".": listings.append(path) or real_listdir(path))
    player.set_ui_language("en")
    QApplication.processEvents()
    assert (player.workComboBox.itemText(0), player.seasonComboBox.itemText(0), player.jobComboBox.itemText(0)) == (
        "Select show", "Select season", "Select job")
    after = (combo_items(player.workComboBox)[1:], combo_items(player.seasonComboBox)[1:], combo_items(player.jobComboBox)[1:],
             player.workComboBox.currentIndex(), player.seasonComboBox.currentIndex(), player.jobComboBox.currentIndex(),
             listed(player))
    assert after == before and scans == [] and listings == []
    player.set_ui_language("ko")
    assert (player.workComboBox.itemText(0), player.seasonComboBox.itemText(0), player.jobComboBox.itemText(0)) == (
        "작품선택", "시즌선택", "job선택")
    assert scans == [] and listings == []


def test_unpicked_placeholders_are_translated_too(shown):
    """아무것도 고르지 않은 콤보(안내 항목이 보이는 채) — 보이는 글과 그 툴팁이 지금 언어."""
    shown.set_ui_language("en")
    assert shown.workComboBox.currentText() == "Select show" and shown.seasonComboBox.currentText() == "Select season"
    assert shown.jobComboBox.currentText() == "Select job"
    assert ui_texts.hangul([combo.toolTip() for combo in (shown.workComboBox, shown.seasonComboBox, shown.jobComboBox)]) == []


def test_job_selection_does_not_carry_the_placeholder_texts(shown):
    """'읽은 job'의 표지(_job_selection)는 고르지 않은 칸을 글이 아니라 None으로 — 언어가 바뀌어도 같은 값."""
    korean = shown._job_selection()
    shown.set_ui_language("en")
    assert shown._job_selection() == korean and korean[1:] == (None, None)


def test_seq_items_are_relabelled_in_the_language(shown, tmp_path):
    from yesoncheck.sidebar_sequences import seq_label, seq_tooltip

    ui_texts.stage(shown, tmp_path)
    item = shown.seq_sidebar.item(0)
    seq = item.data(Qt.UserRole)
    korean = (item.text(), item.toolTip())
    assert korean == (seq_label(seq), seq_tooltip(seq)) and "프레임" in korean[0] and "폴더: " in korean[1]
    shown.set_ui_language("en")
    assert (item.text(), item.toolTip()) == (seq_label(seq), seq_tooltip(seq))
    assert " frames)" in item.text() and "Folder: " in item.toolTip() and "Range: " in item.toolTip()
    assert shown.seq_sidebar.item(0) is item  # 항목은 그대로 — 글만 바뀜
    shown.set_ui_language("ko")
    assert (item.text(), item.toolTip()) == korean


def test_seq_label_with_missing_frames_in_both_languages():
    from yesoncheck.sequence_scan import group_sequences
    from yesoncheck.sidebar_sequences import seq_label, seq_tooltip

    [seq] = group_sequences("/x", [f"bg-{n:04d}.tga" for n in (1, 2, 4, 7)])
    assert seq_label(seq) == "bg (0001–0007, 4프레임), 빠짐 3"
    assert seq_tooltip(seq).splitlines()[1:] == ["폴더: /x", "범위: 0001–0007 (4프레임)", "빠짐 3프레임"]
    ui_text.set_language("en")
    assert seq_label(seq) == "bg (0001–0007, 4 frames), 3 missing"
    assert seq_tooltip(seq).splitlines()[1:] == ["Folder: /x", "Range: 0001–0007 (4 frames)", "3 frames missing"]


def test_thumbnail_bar_texts_by_language(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    assert ui_texts._thumbnail_bar_texts(shown) == [
        "썸네일 모두 디스크에 저장됨", "썸네일 생성 중: %v/%m", "썸네일 생성 완료", "썸네일 생성 멈춤 (목록이 바뀜)",
        "썸네일 생성 멈춤 (목록 모드로 바꿈)", "썸네일 생성 멈춤 (창을 닫음)"]
    shown.set_ui_language("en")
    assert ui_texts._thumbnail_bar_texts(shown) == [
        "All thumbnails are saved on disk", "Making thumbnails: %v/%m", "Thumbnails done", "Thumbnails stopped (list changed)",
        "Thumbnails stopped (switched to list mode)", "Thumbnails stopped (window closed)"]


def test_window_title_tail_follows_the_language(shown):
    korean = ui_texts._title_texts(shown)
    # 공유 설정 문제는 제목에 적지 않음 (2026-11-27): 문제만 있는 제목은 보통 제목과 같고, 변환표 문제와 함께면 변환표 꼬리만
    assert [title.partition(" — ")[2] for title in korean] == [
        "", "공유 설정 불러오는 중…", "", korean[3].partition(" — ")[2], korean[3].partition(" — ")[2]]
    assert korean[3].partition(" — ")[2].startswith("변환표 오류")
    shown.set_ui_language("en")
    english = ui_texts._title_texts(shown)
    assert ui_texts.hangul(english) == [] and len(set(english)) == 3
    assert [title.partition(" — ")[0] for title in english] == [title.partition(" — ")[0] for title in korean]  # 머리는 같음
    # 변환표 문제가 있는 채 언어를 바꾸면 창 제목의 꼬리도 따라 바뀜
    saved = shown.shared_config_problem, shown.path_map_problem
    shown.shared_config_problem, shown.path_map_problem = None, "y"
    try:
        shown._update_shared_config_title()
        assert shown.windowTitle() == english[3]
        shown.set_ui_language("ko")
        assert shown.windowTitle() == korean[3]
    finally:
        shown.shared_config_problem, shown.path_map_problem = saved
        shown._update_shared_config_title()


# ---------------------------------------------------------------- 주석 쪽과 뷰어의 배지 (Task 7)

def annotation_combos(player):
    return (player.annotationToolCombo, player.annotationColorCombo)


def test_english_annotation_page_and_badge_have_no_hangul(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    shown.show_tool_panel("annotation")
    shown.annotationModeButton.setChecked(True)  # 배지가 보임
    shown.set_ui_language("en")
    texts = ui_texts.collect(shown)
    assert ui_texts.hangul(texts["annotation"]) == [] and ui_texts.hangul(texts["viewer"]) == []
    assert shown.videoWidget.annotation_mode_label.text() == "Annotation mode"
    shown.annotationModeButton.setChecked(False)


def test_annotation_choices_keep_their_values(shown):
    """도구·색 콤보: 글만 바뀌고 고른 번호·값(itemData)은 그대로, 고른 것이 바뀌었다는 신호도 없음."""
    shown.annotationToolCombo.setCurrentIndex(3)
    shown.annotationColorCombo.setCurrentIndex(2)
    changes = []
    for combo in annotation_combos(shown):
        combo.currentIndexChanged.connect(changes.append)
    before = [(combo.currentData(), combo.currentIndex(), [combo.itemData(i) for i in range(combo.count())])
              for combo in annotation_combos(shown)]
    korean = [[combo.itemText(i) for i in range(combo.count())] for combo in annotation_combos(shown)]
    assert korean == [["텍스트", "사각형", "타원", "선", "화살표"], ["빨강", "노랑", "초록", "하늘", "흰색"]]
    shown.set_ui_language("en")
    assert [[combo.itemText(i) for i in range(combo.count())] for combo in annotation_combos(shown)] == [
        ["Text", "Rectangle", "Ellipse", "Line", "Arrow"], ["Red", "Yellow", "Green", "Sky blue", "White"]]
    assert [(combo.currentData(), combo.currentIndex(), [combo.itemData(i) for i in range(combo.count())])
            for combo in annotation_combos(shown)] == before and changes == []
    shown.set_ui_language("ko")
    assert [[combo.itemText(i) for i in range(combo.count())] for combo in annotation_combos(shown)] == korean


def test_annotation_badge_is_refitted_to_the_new_text(shown, tmp_path):
    """뷰어 오른쪽 위의 '주석 모드' 배지: 글이 바뀌면 크기를 다시 재고 오른쪽 위에 다시 놓음(글이 잘리지 않게)."""
    ui_texts.stage(shown, tmp_path)  # 주석 모드는 영상 A가 열려 있어야 켜짐
    shown.annotationModeButton.setChecked(True)
    badge = shown.videoWidget.annotation_mode_label
    for code, text in (("en", "Annotation mode"), ("ko", "주석 모드")):
        shown.set_ui_language(code)
        assert badge.text() == text and badge.isVisible()
        assert badge.width() >= badge.sizeHint().width()
        assert badge.x() + badge.width() == shown.videoWidget.width() - 10 and badge.y() == 10
    shown.annotationModeButton.setChecked(False)


def test_annotation_status_messages_are_redrawn_in_the_new_language(shown, tmp_path):
    """상태 줄의 한 번짜리 글(주석 n개 자동 로드·주석 추가 …)은 다시 만드는 코드가 없음 — 만든 때의 뜻을 기억했다가 다시 그림."""
    ui_texts.stage(shown, tmp_path)
    label = shown.annotationStatusLabel
    shown.on_annotation_shape_finished({"type": "rect", "norm_x1": 0.1, "norm_y1": 0.1, "norm_x2": 0.4, "norm_y2": 0.4,
                                        "color": "#ff3333", "id": "probe-rect"})
    korean = label.text()
    assert korean.startswith("프레임 ") and korean.endswith("에 rect 주석 추가 (자동 저장)")  # 한국어 글은 예전 그대로(내부 이름째)
    shown.set_ui_language("en")
    assert label.text().startswith("Added: rectangle annotation on frames ") and ui_texts.hangul([label.text()]) == []
    shown.set_ui_language("ko")
    assert label.text() == korean


def test_annotation_list_items_are_relabelled(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    shown.annotation_store.add(0, {"type": "text", "norm_x1": 0.2, "norm_y1": 0.2, "norm_x2": 0.2, "norm_y2": 0.2, "text": "fix this",
                                   "color": "#ff3333", "font_size": 24, "id": "probe-text"}, start_frame=0, end_frame=2)
    shown.refresh_annotation_ui(redraw=False)
    rows = shown.annotationListWidget
    korean = [rows.item(i).text() for i in range(rows.count())]
    assert "[F1~3 텍스트 24px] fix this" in korean and any(text.startswith("[F") and " rect " in text for text in korean)
    rows.setCurrentRow(0)
    chosen = rows.currentItem().data(Qt.UserRole)
    shown.set_ui_language("en")
    english = [rows.item(i).text() for i in range(rows.count())]
    assert "[F1~3 text 24px] fix this" in english and any(" rectangle " in text for text in english)
    assert ui_texts.hangul(english) == [] and rows.currentItem().data(Qt.UserRole) == chosen  # 고른 주석은 그대로
    shown.set_ui_language("ko")
    assert [rows.item(i).text() for i in range(rows.count())] == korean


def test_storage_warning_is_redrawn_in_the_new_language(shown, tmp_path, monkeypatch):
    """⚠ 저장 불가·저장 실패 같은 글은 그 상태가 다시 오지 않으면 다시 만들어지지 않음 — 언어를 바꾸면 같은 뜻의 글로."""
    from yesoncheck import player_annotations

    ui_texts.stage(shown, tmp_path)
    label = shown.annotationStorageLabel
    monkeypatch.setattr(player_annotations, "is_annotation_storage_writable", lambda _path: False)
    assert shown.auto_save_annotations() is False
    korean = label.text()
    assert korean.startswith("⚠ 주석 저장 불가 (쓰기 권한 없음): ")
    shown.set_ui_language("en")
    assert label.text() == "⚠ Cannot save annotations (no write permission): " + korean.partition(": ")[2]
    shown.set_ui_language("ko")
    assert label.text() == korean

    monkeypatch.setattr(player_annotations, "is_annotation_storage_writable", lambda _path: True)
    monkeypatch.setattr(shown.annotation_store, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(shown, "_show_annotation_problem_once", lambda *args: None)
    assert shown.auto_save_annotations() is False
    assert label.text() == "⚠ 주석 저장 실패: OSError: disk full"
    shown.set_ui_language("en")
    assert label.text() == "⚠ Saving annotations failed: OSError: disk full"


def test_export_folder_label_follows_the_language(shown, tmp_path):
    label = shown.annotationExportDirLabel
    shown.annotation_export_dir = ""
    shown._update_annotation_export_dir_label()
    assert label.text() == "보내기 저장 폴더: 미지정 (선택 필요)"
    shown.set_ui_language("en")
    assert label.text() == "Export folder: not set (choose one)"
    shown.annotation_export_dir = str(tmp_path)
    shown._update_annotation_export_dir_label()
    assert label.text() == f"Export folder: {tmp_path}"
    shown.set_ui_language("ko")
    assert label.text() == f"보내기 저장 폴더: {tmp_path}"


def test_tool_panel_minimum_width_in_english_stays_within_the_panel_width(shown):
    """도구 패널의 최소 너비(두 쪽 중 넓은 쪽)는 English에서도 패널의 처음 너비(340) 이하 — 패널을 열어도 창이 더 넓어지지 않게.
    실제 글꼴에서만 봄: 글꼴 없는 환경(Windows CI·그 흉내)은 영문 글자도 한글만큼 넓게 재 영문 라벨이 한글 라벨보다 길어짐."""
    from yesoncheck import tool_panel

    metrics = shown.annotationDeleteButton.fontMetrics()
    if metrics.horizontalAdvance("a") * 10 >= metrics.horizontalAdvance("가") * 9:
        pytest.skip("이 글꼴은 영문 글자를 한글만큼 넓게 잼 — 실제 글꼴이 아님")
    korean = shown.toolPanel.minimumSizeHint().width()
    shown.set_ui_language("en")
    for key in ("annotation", "ocr"):
        shown.show_tool_panel(key)
        QApplication.processEvents()
        assert shown.toolPanel.minimumSizeHint().width() <= max(korean, tool_panel.PANEL_WIDTH), key


# ---------------------------------------------------------------- OCR 쪽 (Task 8)

def test_english_ocr_page_has_no_hangul(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    shown.show_tool_panel("ocr")
    shown.set_ui_language("en")
    assert ui_texts.hangul(ui_texts.collect(shown)["ocr"]) == []


def test_switching_language_leaves_the_ocr_mode_and_roi_alone(shown, tmp_path):
    """방식 콤보는 글만 바뀜 — 고른 방식(itemData)·ROI·단추의 켜짐은 그대로이고 '방식이 바뀜' 신호도 없음(그 처리기는 ROI 상태를 건드림)."""
    ui_texts.stage(shown, tmp_path)
    combo = shown.ocrModeComboBox
    combo.setCurrentIndex(combo.findData("all"))
    changes, calls = [], []
    combo.currentIndexChanged.connect(changes.append)
    shown.on_ocr_mode_changed = lambda *args: calls.append(args)  # 다시 그리기가 부르면 안 됨
    buttons = (shown.ocrSelectRoiButton, shown.ocrClearRoiButton, shown.ocrTrackingCheckBox, shown.ocrAnalyzeButton,
               shown.ocrAnalyzeRangeButton, shown.ocrReopenResultButton, shown.ocrSaveResultButton, shown.ocrLoadResultButton)
    before = (combo.currentData(), combo.currentIndex(), [combo.itemData(i) for i in range(combo.count())], shown.ocr_roi,
              [button.isEnabled() for button in buttons], shown.ocrPatternLineEdit.isVisibleTo(shown.toolPanel))
    korean = [combo.itemText(i) for i in range(combo.count())]
    assert korean[:5] == ["Titmouse", "King", "Bento", "All (사용자 패턴)", "애니매틱 (Auto Cut)"]
    shown.set_ui_language("en")
    english = [combo.itemText(i) for i in range(combo.count())]
    assert english[:5] == ["Titmouse", "King", "Bento", "All (custom pattern)", "Animatic (Auto Cut)"]
    if combo.findData("animatic2") >= 0:
        assert (korean[5], english[5]) == ("애니매틱2 (TransNetV2)", "Animatic 2 (TransNetV2)")
    assert (combo.currentData(), combo.currentIndex(), [combo.itemData(i) for i in range(combo.count())], shown.ocr_roi,
            [button.isEnabled() for button in buttons], shown.ocrPatternLineEdit.isVisibleTo(shown.toolPanel)) == before
    assert changes == [] and calls == []
    shown.set_ui_language("ko")
    assert [combo.itemText(i) for i in range(combo.count())] == korean and changes == [] and calls == []
    del shown.on_ocr_mode_changed


def test_roi_button_tooltip_follows_the_mode_and_the_language(shown, tmp_path):
    """ROI 단추의 툴팁은 방식·영상 종류에 따라 바뀜 — 언어를 바꾸면 지금 상태의 글이 새 언어로."""
    ui_texts.stage(shown, tmp_path)
    combo, button = shown.ocrModeComboBox, shown.ocrSelectRoiButton
    combo.setCurrentIndex(combo.findData("king"))
    assert button.toolTip() == "영상에서 OCR 분석에 사용할 영역을 드래그하여 지정합니다."
    shown.set_ui_language("en")
    assert button.toolTip() == "Drag on the video to set the area used for OCR analysis."
    combo.setCurrentIndex(combo.findData("animatic"))
    assert button.toolTip() == "Animatic mode does not need an ROI."
    shown.set_ui_language("ko")
    assert button.toolTip() == "애니매틱 모드는 ROI가 필요 없습니다."
    shown._ocr_blocked_by_sequence = lambda: True  # 이미지 시퀀스가 열려 있음
    shown.on_ocr_mode_changed()
    assert button.toolTip() == "이미지 시퀀스에서는 OCR·컷 감지를 쓸 수 없습니다."
    shown.set_ui_language("en")
    assert button.toolTip() == "OCR and cut detection cannot be used on image sequences."
    del shown._ocr_blocked_by_sequence


def test_ocr_mode_tooltip_lists_the_modes_that_exist(shown):
    """방식 콤보의 툴팁: 애니매틱2 줄은 그 항목이 있을 때만 — 두 언어 모두."""
    combo = shown.ocrModeComboBox
    has_animatic2 = combo.findData("animatic2") >= 0
    assert ("애니매틱2: TransNetV2" in combo.toolTip()) is has_animatic2 and "- 애니매틱: PySceneDetect" in combo.toolTip()
    shown.set_ui_language("en")
    assert ("Animatic 2: " in combo.toolTip()) is has_animatic2 and "- Animatic: " in combo.toolTip()
    assert ui_texts.hangul([combo.toolTip()]) == []


# ---------------------------------------------------------------- V 모드 오버레이와 업데이트 알림 띠 (Task 9)

BANNER_BUTTONS_KO = ["바뀐 점", "업데이트", "나중에", "취소"]
BANNER_BUTTONS_EN = ["What's new", "Update", "Later", "Cancel"]


def banner_buttons(player):
    banner = player.update_banner
    return [button.text() for button in (banner.notes_button, banner.update_button, banner.later_button, banner.cancel_button)]


def test_english_banner_and_overlay_have_no_hangul(shown, tmp_path):
    ui_texts.stage(shown, tmp_path)
    shown.set_ui_language("en")
    texts = ui_texts.collect(shown)
    assert ui_texts.hangul(texts["banner"]) == [] and ui_texts.hangul(texts["overlay"]) == []
    assert banner_buttons(shown) == BANNER_BUTTONS_EN


@pytest.mark.parametrize("shape, korean, english", [
    ("offer", "⬆ 새 버전 9.9.9가 나왔습니다 · 지금 1.0.0", "⬆ Version 9.9.9 is available · now 1.0.0"),
    ("download", "9.9.9 받는 중 (NAS)… 1.0 / 2.0 MB", "Downloading 9.9.9 (NAS)… 1.0 / 2.0 MB"),
    ("staging", "준비 중…", "Preparing…"),
    ("checking", "다른 창 확인 중…", "Checking other windows…"),
    ("closing", "다른 창을 닫는 중…", "Closing other windows…"),
    ("cancelling", "취소하는 중…", "Cancelling…"),
    ("helper", "업데이트 도우미를 시작하는 중…", "Starting the update helper…"),
    ("updated", "9.9.9로 업데이트했습니다", "Updated to 9.9.9"),
])
def test_banner_shown_before_the_switch_is_redrawn(shown, shape, korean, english):
    """띠가 떠 있는 채 언어를 바꾸면 같은 뜻의 글로 다시 그림(모양·단추의 보임은 그대로) — 띠의 글은 그 일이 다시 일어나야 다시 옴."""
    banner = shown.update_banner
    dict(ui_texts.banner_shapes(shown))[shape]()
    visible = [button.isVisibleTo(banner) for button in (banner.notes_button, banner.update_button, banner.later_button,
                                                           banner.cancel_button, banner.progress_bar)]
    mode = banner.mode()
    assert banner.full_text() == korean and banner.text_label.toolTip() == korean and banner_buttons(shown) == BANNER_BUTTONS_KO
    shown.set_ui_language("en")
    assert banner.full_text() == english and banner.text_label.toolTip() == english and banner_buttons(shown) == BANNER_BUTTONS_EN
    assert banner.mode() == mode and [button.isVisibleTo(banner) for button in (
        banner.notes_button, banner.update_button, banner.later_button, banner.cancel_button, banner.progress_bar)] == visible
    shown.set_ui_language("ko")
    assert banner.full_text() == korean and banner_buttons(shown) == BANNER_BUTTONS_KO
    banner.hide_banner()


def test_banner_shown_in_english_from_the_start(shown):
    shown.set_ui_language("en")
    shown.update_banner.show_offer("1.1.1", "1.1.0")
    assert shown.update_banner.full_text() == "⬆ Version 1.1.1 is available · now 1.1.0"
    shown.update_banner.hide_banner()


def test_banner_keeps_a_plain_text_as_it_is(shown):
    """글자 표의 글이 아닌 그냥 글자를 받으면 언어가 바뀌어도 그대로 보임(지어내지 않음)."""
    banner = shown.update_banner
    banner.show_progress(1, 4, "1.1.1 받는 중…")
    shown.set_ui_language("en")
    assert banner.full_text() == "1.1.1 받는 중…" and banner.mode() == "progress"
    banner.hide_banner()


def test_update_messages_are_korean_as_values_and_follow_the_language_when_shown():
    """알림 띠에 넘기는 글(ui_text.Message): 값은 늘 한국어 글(기록 줄·비교용), 보일 때의 글은 지금 언어."""
    from yesoncheck import player_update

    message = player_update.download_text("1.1.1", "NAS", 1_500_000, 3_000_000)
    assert message == "1.1.1 받는 중 (NAS)… 1.5 / 3.0 MB" and ui_text.shown(message) == message
    assert player_update.updated_message("1.1.1") == "1.1.1로 업데이트했습니다"
    ui_text.set_language("en")
    assert ui_text.shown(message) == "Downloading 1.1.1 (NAS)… 1.5 / 3.0 MB" and message == "1.1.1 받는 중 (NAS)… 1.5 / 3.0 MB"
    again = player_update.download_text("1.1.1", "NAS", 1_500_000, 3_000_000)
    assert again == message  # English 화면에서 만들어도 값은 한국어 (기록 줄은 언어와 무관)
    assert ui_text.shown(player_update.STAGING_TEXT) == "Preparing…" and player_update.STAGING_TEXT == "준비 중…"
    assert ui_text.shown("그냥 글자") == "그냥 글자"


def test_download_progress_from_the_worker_is_worded_in_the_window_language(shown, monkeypatch):
    """받기 스레드는 진행 신호에 글이 아니라 단계만 실음 — 띠의 글은 창(GUI 쪽)이 지금 언어로 만듦."""
    from types import SimpleNamespace

    from yesoncheck import player_update

    run = SimpleNamespace(version="1.1.1", source="NAS", download=SimpleNamespace(is_cancelled=lambda: False))
    monkeypatch.setattr(shown, "_update_run", run)
    shown.set_ui_language("en")
    shown._on_update_progress(1_000_000, 4_000_000, player_update.STAGE_DOWNLOAD)
    assert shown.update_banner.full_text() == "Downloading 1.1.1 (NAS)… 1.0 / 4.0 MB"
    shown._on_update_progress(0, 0, player_update.STAGE_STAGING)
    assert shown.update_banner.full_text() == "Preparing…"
    shown.set_ui_language("ko")
    assert shown.update_banner.full_text() == "준비 중…"
    shown.update_banner.hide_banner()


def test_overlay_help_follows_the_language(shown):
    label = shown.overlayHelpLabel
    assert label.text() == "드래그로 이동, 테두리로 크기조절, Ctrl+휠로 확대/축소, Ctrl+O로 리셋"
    shown.set_ui_language("en")
    assert label.text() == "Drag to move, drag the border to resize, Ctrl+wheel to zoom, Ctrl+O to reset"
    shown.set_ui_language("ko")
    assert label.text() == "드래그로 이동, 테두리로 크기조절, Ctrl+휠로 확대/축소, Ctrl+O로 리셋"


def test_english_screen_keeps_only_the_language_names(shown, tmp_path):
    """모든 영역을 옮긴 뒤: English 화면에 남는 한글은 언어 메뉴의 두 글(두 언어에서 같은 이름)뿐."""
    ui_texts.stage(shown, tmp_path)
    shown.set_ui_language("en")
    texts = ui_texts.collect(shown)
    left = {area: ui_texts.hangul(found) for area, found in texts.items() if ui_texts.hangul(found)}
    assert left == {"menubar": LANGUAGE_NAMES}


# ---------------------------------------------------------------- 전체 (Task 10)

def test_playback_tick_does_the_same_work_in_both_languages(shown, tmp_path, monkeypatch):
    """재생 틱 한 번이 글자 표에서 읽는 글(= 틱마다 다시 만드는 화면 글)이 두 언어에서 같고 몇 개뿐 — English라고 틱이 더
    무겁지 않게. (Qt 클래스의 메서드를 바꿔 끼워 setText를 세지는 않음 — sip 클래스에 되돌려 놓으면 묶이지 않은 함수가 됨)"""
    ui_texts.stage(shown, tmp_path)
    real_text = ui_text.text
    work = {}
    for code in ("ko", "en"):
        shown.set_ui_language(code)
        shown.seek_to_frame(1)
        QApplication.processEvents()
        lookups = []
        monkeypatch.setattr(ui_text, "text", lambda key, **values: (lookups.append(key), real_text(key, **values))[1])
        shown.timer.start(600000)  # 재생 중 상태 — 간격이 길어 저절로는 울리지 않고 여기서 틱을 직접 부름
        try:
            for _ in range(3):
                shown.next_frame_playback()
        finally:
            shown.timer.stop()
            monkeypatch.setattr(ui_text, "text", real_text)
        work[code] = lookups
    assert work["ko"] == work["en"]
    per_tick = len(work["ko"]) / 3
    assert 0 < per_tick <= 6, work["ko"]  # 틱마다: 주석 상태 줄 한 번 + 주석 목록의 항목 글 정도


# ---------------------------------------------------------------- 줄여 그리는 단추의 실패 알림은 한 번만 (리뷰 M-2)

def test_shrink_button_failures_show_one_window_then_log_a_line_each(qapp, monkeypatch, capsys):
    """그리기·툴팁은 자주 불림 — 같은 실패가 오류 창을 쌓지 않게: 이 프로세스에서 처음 한 번만 창(트레이스백), 그 뒤로는
    단추가 달라도 기록 한 줄씩 (슬라이더 호버 필터와 같은 규칙)."""
    from PyQt5.QtCore import QEvent, QPoint
    from PyQt5.QtGui import QHelpEvent, QPaintEvent
    from yesoncheck import window_layout

    monkeypatch.setattr(window_layout, "_shrink_failure_shown", False)
    windows = []
    monkeypatch.setattr(window_layout.error_window, "report_from_handler", lambda prefix, context: windows.append(context))

    def broken():
        raise RuntimeError("그리기 시험")

    first, second = window_layout.ShrinkButton(), window_layout.ShrinkToolButton()
    for button in (first, second):
        button.set_text_key("sidebar.open_folder")
        monkeypatch.setattr(button, "drawn_text", broken)
    first.paintEvent(QPaintEvent(first.rect()))
    first.paintEvent(QPaintEvent(first.rect()))
    second.paintEvent(QPaintEvent(second.rect()))
    spot = QPoint(3, 3)
    QApplication.sendEvent(second, QHelpEvent(QEvent.ToolTip, spot, second.mapToGlobal(spot)))
    assert windows == ["단추의 글을 그리다가 오류가 났습니다."]
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith(window_layout.SHRINK_LOG_PREFIX)]
    assert len(lines) == 3 and all("RuntimeError: 그리기 시험" in line for line in lines)
    assert "툴팁" in lines[-1]


# ---------------------------------------------------------------- 숨은·썸네일 사이드바에서 언어를 바꿀 때 (리뷰 M-5)

def settle():
    for _ in range(3):
        QApplication.processEvents()


def needs_different_start_widths(player):
    """두 언어의 처음 폭이 같은 글꼴(글꼴 없는 Windows CI 등)에서는 아래 시험이 아무것도 가리지 못함 — 건너뜀 (리뷰 m-2)."""
    korean = player.sidebar_start_width()
    ui_text.set_language("en")
    player.retranslate_ui()
    english = player.sidebar_start_width()
    ui_text.set_language("ko")
    player.retranslate_ui()
    settle()
    if english == korean:
        pytest.skip("이 글꼴에서는 두 언어의 사이드바 처음 폭이 같음")


def test_language_changed_while_the_controls_are_hidden_moves_the_sidebar_when_they_return(shown):
    """V 모드(사이드바가 숨음)에서 언어를 바꾸면 그때는 폭을 알 수 없음 — 되돌아올 때 옛 언어의 처음 폭 그대로면 새 언어의 처음 폭으로."""
    needs_different_start_widths(shown)
    korean = shown.mainSplitter.sizes()
    shown.toggle_controls()
    settle()
    shown.set_ui_language("en")
    shown.toggle_controls()
    settle()
    english = shown.mainSplitter.sizes()
    assert english[0] == shown.sidebar_start_width() and cut_texts(shown) == []
    assert sum(english) == sum(korean) and english[2] == korean[2]
    shown.toggle_controls()
    settle()
    shown.set_ui_language("ko")
    shown.toggle_controls()
    settle()
    assert shown.mainSplitter.sizes() == korean


def test_language_changed_and_changed_back_while_hidden_keeps_the_width(shown):
    """숨은 동안 바꿨다 되돌리면 폭은 그대로. (언어가 둘뿐이라 '처음 언어의 폭으로 견줌'과 '나중 언어의 폭으로 견줌'을 이 시험이
    가르지는 못함 — 리뷰 m-2; 결과가 같으므로 동작으로는 같음)"""
    needs_different_start_widths(shown)
    korean = shown.mainSplitter.sizes()
    shown.toggle_controls()
    settle()
    shown.set_ui_language("en")
    shown.set_ui_language("ko")
    shown.toggle_controls()
    settle()
    assert shown.mainSplitter.sizes() == korean


def test_hand_set_width_is_kept_when_the_language_changes_while_hidden(shown):
    needs_different_start_widths(shown)
    sizes = shown.mainSplitter.sizes()
    shown.mainSplitter.setSizes([sizes[0] + 31, sizes[1] - 31, sizes[2]])
    by_hand = shown.mainSplitter.sizes()
    shown.toggle_controls()
    settle()
    shown.set_ui_language("en")
    shown.toggle_controls()
    settle()
    assert shown.mainSplitter.sizes() == by_hand


def test_language_changed_in_thumbnail_mode_sets_the_list_width_to_come_back_to(shown):
    """썸네일 모드에서 바꾸면 썸네일 폭은 그대로 두고, 목록 모드로 돌아올 폭을 새 언어의 처음 폭으로 (되돌리면 돌아옴)."""
    QTest.qWait(250)  # 켠 뒤 200ms에 기본 목록 폭을 적음 (initialize_sidebar_width)
    needs_different_start_widths(shown)
    korean = shown.mainSplitter.sizes()
    shown.switch_to_thumbnail_mode()
    settle()
    thumbnails = shown.mainSplitter.sizes()
    shown.set_ui_language("en")
    settle()
    assert shown.mainSplitter.sizes() == thumbnails
    shown.switch_to_list_mode()
    settle()
    assert shown.mainSplitter.sizes()[0] == shown.sidebar_start_width() and cut_texts(shown) == []
    shown.switch_to_thumbnail_mode()
    settle()
    shown.set_ui_language("ko")
    shown.switch_to_list_mode()
    settle()
    assert shown.mainSplitter.sizes() == korean


def test_list_width_other_than_the_start_width_is_kept_when_the_language_changes_in_thumbnail_mode(shown):
    """썸네일 모드에서 돌아올 목록 폭(default_sidebar_width — 켤 때 한 번 적힘)이 처음 폭이 아니면 언어를 바꿔도 그대로."""
    QTest.qWait(250)
    needs_different_start_widths(shown)
    start = shown.mainSplitter.sizes()[0]
    shown.default_sidebar_width += 31  # 처음 폭이 아닌 목록 폭 (켠 직후에 손으로 맞춘 것처럼)
    shown.switch_to_thumbnail_mode()
    settle()
    shown.set_ui_language("en")
    shown.switch_to_list_mode()
    settle()
    assert shown.mainSplitter.sizes()[0] == start + 31


def test_screenshot_tool_language_check_catches_a_window_left_in_another_language(player):
    """매뉴얼 그림 도구의 창 언어 확인 — 한국어로 만든 창에서 언어만 English로 바꾸고 화면을 다시 그리지 않았으면 실패해야 함
    (English 그림에 한국어 메인 창 글자가 찍히는 경우 — Review Focus 1). 'File'은 두 언어에서 같은 글이라 그것만 보면 이 경우를
    잡지 못함 (UI 개편 PR 4 리뷰)."""
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    sys.path.insert(0, tools_dir)
    try:
        import make_manual_screenshots as tool
    finally:
        sys.path.remove(tools_dir)
    tool.check_window_language(player, "ko")
    ui_text.set_language("en")
    with pytest.raises(RuntimeError):
        tool.check_window_language(player, "en")
    player.retranslate_ui()
    tool.check_window_language(player, "en")
