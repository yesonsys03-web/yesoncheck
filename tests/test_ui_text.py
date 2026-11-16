"""메인 창의 글자 표(`ui_text`): 키 하나에 한국어·English 글 — 재생 줄부터 여기서 읽는다(언어 고르기는 다음 단계).

두 언어의 키가 같고 빈 글이 없음을 지킨다(매뉴얼의 두 언어 대조와 같은 생각 — 한쪽만 고치면 실패).
"""

import subprocess
import sys

import pytest

from yesoncheck import ui_text


@pytest.fixture(autouse=True)
def _default_language():
    yield
    ui_text.set_language(ui_text.DEFAULT_LANGUAGE)


def test_every_key_has_both_languages():
    assert ui_text.missing() == []
    assert ui_text.LANGUAGES == ("ko", "en")
    assert ui_text.DEFAULT_LANGUAGE == "ko"


def test_missing_reports_absent_and_empty_texts(monkeypatch):
    monkeypatch.setitem(ui_text.TEXTS, "probe.absent", {"ko": "글"})
    monkeypatch.setitem(ui_text.TEXTS, "probe.empty", {"ko": "글", "en": "  "})
    assert ui_text.missing() == ["probe.absent", "probe.empty"]


def test_text_follows_language():
    assert ui_text.language() == "ko"
    assert ui_text.text("transport.loop") == "반복 재생"
    ui_text.set_language("en")
    assert ui_text.language() == "en"
    assert ui_text.text("transport.loop") == "Loop playback"
    ui_text.set_language("ko")
    assert ui_text.text("transport.loop") == "반복 재생"


def test_transport_texts_name_their_shortcuts():
    expected = {
        "transport.first": "처음으로 (Home)",
        "transport.prev": "한 장 뒤로 (←)",
        "transport.play": "재생 (Space)",
        "transport.pause": "일시정지 (Space)",
        "transport.next": "한 장 앞으로 (→)",
        "transport.last": "끝으로 (End)",
        "playlist.end": "이어 재생 끝내기",
    }
    for key, value in expected.items():
        assert ui_text.text(key) == value
    ui_text.set_language("en")
    for key, shortcut in (("transport.first", "(Home)"), ("transport.prev", "(←)"), ("transport.play", "(Space)"),
                          ("transport.pause", "(Space)"), ("transport.next", "(→)"), ("transport.last", "(End)")):
        assert ui_text.text(key).endswith(shortcut)


MENU_TITLES = ("menu.file", "menu.view", "menu.playback", "menu.compare", "menu.tools")

# 글 끝에 단축키를 적는 항목 — 두 언어가 같은 표기로 끝나야 함 (메뉴는 QAction 단축키 없이 글자로만 알림)
SHORTCUT_TEXTS = {
    "sidebar.bookmark.manage": "(P)",
    "sidebar.refresh.tip": "(F5)",
    "playlist.play.tip": "(Enter)",
    "panel.close.tip": "(N)",
    "menu.file.bookmark_manage": "(P)",
    "menu.view.fit": "(3)",
    "menu.view.original": "(4)",
    "menu.view.zoom_in": "(2, +)",  # 키 처리는 2·+·= 를 받음 — 숫자 키(1 축소·2 확대·3 맞춤·4 원본)가 한 벌 (사용자 지적 2026-11-16)
    "menu.view.zoom_out": "(1, -)",
    "menu.view.fullscreen": "(F)",
    "menu.view.video_only": "(Shift+F)",
    "menu.view.controls": "(V)",
    "menu.view.theme": "(T)",
    "menu.view.overlay_text": "(B)",
    "menu.playback.play": "(Space)",
    "menu.playback.prev": "(←)",
    "menu.playback.next": "(→)",
    "menu.playback.first": "(Home)",
    "menu.playback.last": "(End)",
    "menu.playback.playlist": "(Enter)",
    "menu.tools.toggle": "(N)",
}

# 이 PR(가운데 열 없애기)이 쓰는 키 — 빠지면 창을 만들 때 KeyError
LAYOUT_KEYS = (
    "sidebar.works", "sidebar.open_folder", "sidebar.bookmarks", "sidebar.bookmark.add", "sidebar.bookmark.manage",
    "sidebar.refresh", "sidebar.refresh.tip", "sidebar.mode.list", "sidebar.mode.thumb",
    "playlist.play", "playlist.pause", "playlist.play.tip",
    "transport.wipe", "transport.wipe.tip", "transport.wipe.x", "transport.wipe.x.tip", "transport.wipe.y",
    "transport.wipe.y.tip", "transport.annotate", "transport.annotate.tip", "transport.ocr", "transport.ocr.tip",
    "panel.annotation", "panel.ocr", "panel.close.tip", "ocr.section.roi", "ocr.section.analysis",
    "ocr.section.results",
    "menu.file.open_a", "menu.file.open_b", "menu.file.open_folder", "menu.file.bookmark_add",
    "menu.file.bookmark_manage",
    "menu.view.fit", "menu.view.original", "menu.view.zoom_in", "menu.view.zoom_out", "menu.view.fullscreen",
    "menu.view.video_only", "menu.view.controls", "menu.view.theme", "menu.view.overlay_text",
    "menu.playback.play", "menu.playback.prev", "menu.playback.next", "menu.playback.first", "menu.playback.last",
    "menu.playback.loop", "menu.playback.playlist", "menu.playback.playlist_end",
    "menu.compare.wipe", "menu.compare.x", "menu.compare.y",
    "menu.tools.annotation", "menu.tools.ocr", "menu.tools.toggle", "menu.tools.work_paths",
)


def test_layout_keys_exist_in_both_languages():
    for key in LAYOUT_KEYS + MENU_TITLES:
        for code in ui_text.LANGUAGES:
            assert ui_text.TEXTS[key][code].strip(), (key, code)


def test_menu_titles_are_the_same_english_word_in_both_languages():
    for key in MENU_TITLES:
        texts = ui_text.TEXTS[key]
        assert texts["ko"] == texts["en"], key
        assert texts["ko"].startswith("&") and texts["ko"][1:].isascii() and texts["ko"][1:].isalpha(), key
    # 단축 글자(Alt+글자)가 서로, 그리고 기존 &Settings·&Help와 겹치지 않음
    letters = [ui_text.TEXTS[key]["ko"][1].lower() for key in MENU_TITLES]
    assert len(set(letters)) == len(letters)
    assert not set(letters) & {"s", "h"}


def test_shortcut_notes_end_the_text_in_both_languages():
    for key, shortcut in SHORTCUT_TEXTS.items():
        for code in ui_text.LANGUAGES:
            assert ui_text.TEXTS[key][code].endswith(" " + shortcut), (key, code)


def test_playlist_button_texts_differ_between_states():
    for code in ui_text.LANGUAGES:
        ui_text.set_language(code)
        assert ui_text.text("playlist.play") != ui_text.text("playlist.pause")
        assert ui_text.text("playlist.play") != ui_text.text("playlist.end")


def test_format_values():
    assert ui_text.text("transport.volume", percent=50) == "볼륨 50%"
    ui_text.set_language("en")
    assert ui_text.text("transport.volume", percent=7) == "Volume 7%"


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        ui_text.text("no.such.key")


def test_unknown_language_raises_and_keeps_the_current_one():
    with pytest.raises(ValueError):
        ui_text.set_language("jp")
    assert ui_text.language() == "ko"


def test_english_texts_have_no_hangul():
    for key, texts in ui_text.TEXTS.items():
        assert not any("가" <= ch <= "힣" for ch in texts["en"]), key


def test_module_has_no_qt():
    code = "import sys; from yesoncheck import ui_text; print(any(name.startswith('PyQt5') for name in sys.modules))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False"
