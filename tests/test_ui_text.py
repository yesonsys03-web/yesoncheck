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
