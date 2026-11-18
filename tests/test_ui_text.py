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
    assert ui_text.text("playlist.end") == "이어 재생 끝내기"
    ui_text.set_language("en")
    assert ui_text.language() == "en"
    assert ui_text.text("playlist.end") == "End playlist"
    ui_text.set_language("ko")
    assert ui_text.text("playlist.end") == "이어 재생 끝내기"


def test_transport_texts_name_their_shortcuts():
    expected = {
        "transport.first": "처음으로 (Home)",
        "transport.prev": "한 장 뒤로 (←, ,)",  # 키 처리는 ←와 쉼표를 받음 (→와 마침표)
        "transport.play": "재생 (Space)",
        "transport.pause": "일시정지 (Space)",
        "transport.next": "한 장 앞으로 (→, .)",
        "transport.last": "끝으로 (End)",
        "playlist.end": "이어 재생 끝내기",
    }
    for key, value in expected.items():
        assert ui_text.text(key) == value
    ui_text.set_language("en")
    for key, shortcut in (("transport.first", "(Home)"), ("transport.prev", "(←, ,)"), ("transport.play", "(Space)"),
                          ("transport.pause", "(Space)"), ("transport.next", "(→, .)"), ("transport.last", "(End)")):
        assert ui_text.text(key).endswith(shortcut)


MENU_TITLES = ("menu.file", "menu.view", "menu.playback", "menu.compare", "menu.tools")

# 글 끝에 단축키를 적는 항목 — 두 언어가 같은 표기로 끝나야 함 (메뉴는 QAction 단축키 없이 글자로만 알림)
SHORTCUT_TEXTS = {
    "sidebar.bookmark.manage": "(P)",
    "sidebar.refresh.tip": "(F5)",
    "playlist.play.tip": "(Enter)",
    "panel.close.tip": "(N)",
    "menu.file.bookmark_manage": "(P)",
    "menu.file.open_a": "(O)",  # O·I·L·W — 사용자 요청 2026-11-16 (한글 자판 ㅐ·ㅑ·ㅣ·ㅈ도 받음 — player_menus.KEY_SHORTCUTS)
    "menu.file.open_folder": "(I)",
    "menu.playback.loop": "(L)",
    "menu.compare.wipe": "(W)",
    "transport.loop": "(L)",
    "transport.wipe.tip": "(W)",
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
    "menu.playback.prev": "(←, ,)",  # 키 처리는 ←·쉼표, →·마침표를 받음 (사용자 요청 2026-11-16 — 빠뜨린 키를 적음)
    "menu.playback.next": "(→, .)",
    "menu.playback.first": "(Home)",
    "menu.playback.last": "(End)",
    "menu.playback.playlist": "(Enter)",
    "menu.tools.toggle": "(N)",
    # 사이드바 우클릭 메뉴 — 사용자 요청 2026-11-18 (player_menus.ITEM_KEY_SHORTCUTS; 비디오 A·B 열기는 [ ] — 사용자 결정)
    "side_menu.open_a": "([)",
    "side_menu.open_b": "(])",
    "side_menu.seq.open_a": "([)",
    "side_menu.seq.open_b": "(])",
    "side_menu.merge": "(J)",
    "side_menu.copy": "(C)",
    "side_menu.thumbnails": "(R)",
    "side_menu.info": "(M)",
    "side_menu.seq.thumbnails": "(R)",
    "side_menu.seq.info": "(M)",
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


# ---------------------------------------------------------------- 조사 (리뷰 M-8 — 2026-11-17)

@pytest.mark.parametrize("word, pair, expected", [
    ("항목", "을/를", "을"), ("메뉴", "을/를", "를"), ("썸네일", "은/는", "은"), ("필터", "은/는", "는"),
    ("설정", "으로/로", "으로"), ("썸네일", "으로/로", "로"), ("메뉴", "으로/로", "로"), ("항목", "이/가", "이"),
    ("단추", "과/와", "와"),
])
def test_particle_follows_the_final_syllable(word, pair, expected):
    assert ui_text.particle(word, pair) == expected


@pytest.mark.parametrize("version, ga, ro", [
    ("1.10.0", "이", "으로"), ("1.9.1", "이", "로"), ("1.9.2", "가", "로"), ("1.9.3", "이", "으로"),
    ("1.9.4", "가", "로"), ("1.9.5", "가", "로"), ("1.9.6", "이", "으로"), ("1.9.7", "이", "로"),
    ("1.9.8", "이", "로"), ("9.9.9", "가", "로"),
])
def test_particle_after_a_version_reads_the_last_digit(version, ga, ro):
    """숫자는 읽는 소리로: 0 영·1 일·2 이·3 삼·4 사·5 오·6 육·7 칠·8 팔·9 구 (ㄹ 받침 뒤는 '로')."""
    assert ui_text.particle(version, "이/가") == ga
    assert ui_text.particle(version, "으로/로") == ro


def test_particle_after_an_unreadable_ending_writes_both_forms():
    assert ui_text.particle("Update", "을/를") == "을(를)"
    assert ui_text.particle("Mac)", "으로/로") == "(으)로"


def test_particle_rejects_an_unknown_pair():
    with pytest.raises(ValueError):
        ui_text.particle("항목", "에서")


def test_name_with_particle_keeps_the_korean_text_and_adds_a_noun_in_english():
    """딸린 창(한글 문장)이 화면 이름을 인용할 때: 한국어 화면이면 예전 글 그대로, English 화면이면 이름 뒤에 한국어 명사를 붙여
    그 명사의 조사로 — 영어 낱말의 받침은 읽기 따라 달라 고를 수 없음."""
    assert ui_text.with_particle("슬라이더 썸네일", "을") == "슬라이더 썸네일을"
    assert ui_text.with_particle("ffmpeg (예전 방식)", " 으로") == "ffmpeg (예전 방식) 으로"
    ui_text.set_language("en")
    assert ui_text.with_particle("Slider thumbnails", "을") == "Slider thumbnails 항목을"
    assert ui_text.with_particle("Slider thumbnails", "은") == "Slider thumbnails 항목은"
    assert ui_text.with_particle("ffmpeg (legacy)", " 으로") == "ffmpeg (legacy) 항목으로"
    assert ui_text.with_particle("CPU (default)", "를") == "CPU (default) 항목을"
    assert ui_text.with_particle("CPU (default)", "로", noun="설정") == "CPU (default) 설정으로"
    assert ui_text.with_particle("'Update'", "를", noun="단추") == "'Update' 단추를"


def test_update_texts_pick_the_particle_for_the_version():
    """알림 띠: '1.10.0으로 업데이트했습니다'·'새 버전 1.9.4가 나왔습니다' (예전 글은 늘 '로'·'이'였음)."""
    assert ui_text.version_values("1.10.0") == {"version": "1.10.0", "ga": "이", "ro": "으로"}
    assert ui_text.version_values("1.9.4", name="new") == {"new": "1.9.4", "ga": "가", "ro": "로"}
    assert ui_text.text("update.updated", **ui_text.version_values("1.10.0")) == "1.10.0으로 업데이트했습니다"
    assert ui_text.text("update.updated", **ui_text.version_values("1.9.4")) == "1.9.4로 업데이트했습니다"
    offer = ui_text.text("update.offer", current="1.9.3", **ui_text.version_values("1.9.4", name="new"))
    assert offer == "⬆ 새 버전 1.9.4가 나왔습니다 · 지금 1.9.3"


# ---------------------------------------------------------------- Message 복사 (리뷰 M-3)

def test_message_survives_copy_deepcopy_and_pickle():
    import copy
    import pickle

    message = ui_text.Message("update.updated", **ui_text.version_values("1.9.4"))
    for again in (copy.copy(message), copy.deepcopy(message), pickle.loads(pickle.dumps(message))):
        assert isinstance(again, ui_text.Message)
        assert again == message == "1.9.4로 업데이트했습니다"
        assert again.key == message.key and again.values == message.values
        ui_text.set_language("en")
        assert again.shown() == "Updated to 1.9.4"
        ui_text.set_language("ko")
