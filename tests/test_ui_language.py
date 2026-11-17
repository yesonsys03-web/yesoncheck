"""화면 언어 설정(`ui_language` — 2026-11-16 UI 개편 PR 3): 한국어 / English.

우선순위: 환경 변수 `YESONCHECK_LANGUAGE` > 이 PC의 prefs.json(`ui_language`) > OS 언어. 시작 때 `app.load_language()`가 한 번
읽어 글자 표(`ui_text`)의 언어를 정한다. 깨진 설정은 한국어로 치지 않고 알린 뒤 그 세션만 한국어 — 파일은 그대로.
시험은 `tests/conftest.py`가 환경 변수를 `ko`로 고정하고(시험 프로세스·CI 러너의 OS 언어와 무관하게), 다른 길을 보는 시험이
그 변수를 지운다.
"""

import os

import pytest

from yesoncheck import app as app_module
from yesoncheck import hover_strip, mac_prefs, ui_language, ui_text, user_files


def write_prefs(text):
    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv(ui_language.ENV, raising=False)


@pytest.fixture
def warnings(monkeypatch):
    """경고 창을 띄우지 않고 (제목, 글)을 적음."""
    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda parent, title, text, *rest: shown.append((title, text)))
    return shown


# ---------------------------------------------------------------- 값·저장 (Qt 없음)

def test_names_cover_the_languages_of_the_text_table():
    assert tuple(ui_language.NAMES) == ui_text.LANGUAGES == ("ko", "en")
    assert ui_language.NAMES == {"ko": "한국어", "en": "English"}
    assert ui_language.PREF_KEY == "ui_language" and ui_language.ENV == "YESONCHECK_LANGUAGE"


def test_from_locale_follows_the_first_ui_language():
    assert ui_language.from_locale(["ko-KR", "en-US"]) == "ko"
    assert ui_language.from_locale(["ko"]) == "ko"
    assert ui_language.from_locale(["KO_kr"]) == "ko"
    assert ui_language.from_locale(["en-KR", "ko-KR"]) == "en"
    assert ui_language.from_locale(["ja-JP"]) == "en"
    assert ui_language.from_locale([]) == "en"


def test_env_language_values():
    assert ui_language.env_language({}) is None
    assert ui_language.env_language({"YESONCHECK_LANGUAGE": ""}) is None
    assert ui_language.env_language({"YESONCHECK_LANGUAGE": "  "}) is None
    assert ui_language.env_language({"YESONCHECK_LANGUAGE": "EN"}) == "en"
    assert ui_language.env_language({"YESONCHECK_LANGUAGE": "ko"}) == "ko"
    with pytest.raises(ValueError, match="YESONCHECK_LANGUAGE"):
        ui_language.env_language({"YESONCHECK_LANGUAGE": "jp"})


def test_save_and_read_keep_other_keys(tmp_path):
    path = str(tmp_path / "prefs.json")
    mac_prefs.update_pref("slider_thumbnails", False, path)
    assert ui_language.read(path) is None
    ui_language.save("en", path)
    assert ui_language.read(path) == "en"
    assert mac_prefs.read_prefs(path) == {"slider_thumbnails": False, "ui_language": "en"}
    ui_language.save("ko", path)
    assert ui_language.read(path) == "ko"


def test_save_rejects_an_unknown_language_before_writing(tmp_path):
    path = str(tmp_path / "prefs.json")
    with pytest.raises(ValueError):
        ui_language.save("jp", path)
    assert not os.path.exists(path)


def test_read_rejects_unknown_value_and_broken_file(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text('{"ui_language": "jp"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ui_language"):
        ui_language.read(str(path))
    path.write_text('{"ui_language": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        ui_language.read(str(path))
    path.write_text("{", encoding="utf-8")
    with pytest.raises(user_files.UserFileError):
        ui_language.read(str(path))
    assert path.read_text(encoding="utf-8") == "{"


def test_default_prefs_path_is_the_shared_prefs_file():
    path = write_prefs('{"ui_language": "en"}')
    assert path == hover_strip.prefs_path()
    assert ui_language.read() == "en"


def test_source_is_remembered():
    ui_language.set_source(ui_language.SOURCE_OS)
    assert ui_language.source() == "OS 언어"


def test_module_has_no_qt():
    import subprocess
    import sys

    code = "import sys; from yesoncheck import ui_language; print(any(name.startswith('PyQt5') for name in sys.modules))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False"


# ---------------------------------------------------------------- 시작 때 읽기

@pytest.mark.parametrize("env, pref, system, expected, source", [
    ("en", "ko", ["ko-KR"], "en", ui_language.SOURCE_ENV),
    ("ko", "en", ["en-US"], "ko", ui_language.SOURCE_ENV),
    (None, "en", ["ko-KR"], "en", ui_language.SOURCE_PREFS),
    (None, "ko", ["en-US"], "ko", ui_language.SOURCE_PREFS),
    (None, None, ["ko-KR"], "ko", ui_language.SOURCE_OS),
    (None, None, ["en-US"], "en", ui_language.SOURCE_OS),
    (None, None, [], "en", ui_language.SOURCE_OS),
])
def test_load_language_precedence(monkeypatch, capsys, warnings, env, pref, system, expected, source):
    if env is None:
        monkeypatch.delenv(ui_language.ENV, raising=False)
    else:
        monkeypatch.setenv(ui_language.ENV, env)
    if pref is not None:
        write_prefs('{"ui_language": "%s"}' % pref)
    monkeypatch.setattr(app_module, "system_ui_languages", lambda: system)
    app_module.load_language()
    assert ui_text.language() == expected and ui_language.source() == source
    assert f"[언어] 설정: {ui_language.NAMES[expected]} ({source})" in capsys.readouterr().out
    assert warnings == []


def test_environment_value_wins_without_reading_the_prefs_file(monkeypatch, warnings):
    """환경 변수가 정하면 설정 파일을 읽지 않음 — 깨져 있어도 창이 없음(시험·진단용 고정)."""
    monkeypatch.setenv(ui_language.ENV, "en")
    write_prefs("{")
    app_module.load_language()
    assert ui_text.language() == "en" and warnings == []


@pytest.mark.parametrize("content, hint", [
    ('{"ui_language": "jp"}', "다시 고를 수 있습니다"),
    ("{", "고치거나 지운 뒤"),
])
def test_broken_prefs_warn_once_and_this_session_is_korean(monkeypatch, capsys, no_env, warnings, content, hint):
    path = write_prefs(content)
    monkeypatch.setattr(app_module, "system_ui_languages", lambda: ["en-US"])  # OS 언어로 넘어가지 않음 — 읽지 못했으면 한국어
    ui_text.set_language("en")
    app_module.load_language()
    assert ui_text.language() == "ko" and ui_language.source() == ui_language.SOURCE_FALLBACK
    assert len(warnings) == 1 and warnings[0][0] == ui_language.SETTINGS_TITLE
    assert "이 세션은 한국어" in warnings[0][1] and hint in warnings[0][1]
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == content  # 파일은 그대로
    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert f"[언어] 설정: 한국어 ({ui_language.SOURCE_FALLBACK})" in captured.out


def test_bad_environment_value_is_raised_at_startup(monkeypatch, warnings):
    """다른 토글처럼 — 조용히 다른 언어로 뜨지 않음."""
    monkeypatch.setenv(ui_language.ENV, "jp")
    with pytest.raises(ValueError, match="YESONCHECK_LANGUAGE"):
        app_module.load_language()
    assert warnings == []


class _StopLaunch(Exception):
    pass


def test_launch_loads_the_language_before_the_window(monkeypatch, no_env):
    seen = []

    def stop_at_window(**kwargs):
        seen.append(ui_text.language())
        raise _StopLaunch

    monkeypatch.setattr(app_module, "system_ui_languages", lambda: ["en-US"])
    monkeypatch.setattr(app_module, "VideoPlayer", stop_at_window)
    with pytest.raises(_StopLaunch):
        app_module.launch(["yesoncheck"])
    assert seen == ["en"]


def test_system_ui_languages_is_a_list_of_names(qapp):
    names = app_module.system_ui_languages()
    assert isinstance(names, list) and all(isinstance(name, str) for name in names)


def test_conftest_pins_korean():
    assert os.environ["YESONCHECK_LANGUAGE"] == "ko"
    assert ui_text.language() == "ko" and ui_language.source() == ui_language.SOURCE_ENV


def test_from_locale_reads_the_whole_language_subtag():
    """'ko'로 시작하는 다른 언어(콘칸어 kok)는 한국어가 아님 — 언어 부분이 정확히 ko일 때만 (리뷰 M-6)."""
    assert ui_language.from_locale(["kok-IN"]) == "en"
    assert ui_language.from_locale(["kok"]) == "en"
    assert ui_language.from_locale(["ko-Kore-KR"]) == "ko"
    assert ui_language.from_locale(["ko_KR"]) == "ko"


def test_bad_value_message_names_both_languages_without_a_particle_after_them():
    with pytest.raises(ValueError) as caught:
        ui_language._checked("jp", "prefs.json의 ui_language")
    assert "ko 또는 en 중 하나여야 합니다" in str(caught.value)
