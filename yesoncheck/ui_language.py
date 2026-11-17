"""화면 언어 설정 — 한국어 / English (2026-11-16 UI 개편 PR 3). Qt 없음.

메인 창의 글자는 글자 표(`ui_text`)에서 읽고, 어느 언어로 읽을지는 이 프로세스에 하나(`ui_text.set_language`). 그 값을 어디서
정하는지가 이 모듈:

1. 환경 변수 `YESONCHECK_LANGUAGE=ko|en` — 시험·진단용 고정(없거나 비면 다음으로, 그 밖의 값은 ValueError: 다른 토글과 같음)
2. 이 PC의 prefs.json의 `"ui_language"` — Settings → 언어 (Language)가 씀
3. OS의 화면 언어 — 첫 언어가 한국어면 한국어, 아니면 English

읽는 일은 `app.load_language()`가 시작 때 한 번(창을 만들기 전), 바꾸는 일은 `player_language.PlayerLanguageMixin`.
창마다 프로세스가 하나라 고르면 그 창에 바로, 이미 열린 다른 창은 다음에 켤 때부터.

값을 지어내지 않는다: 깨진 파일은 `UserFileError`, 모르는 값은 ValueError — 부르는 쪽이 알리고 그 세션만 한국어로(파일은 그대로).
"""

import os

from yesoncheck import hover_strip, mac_prefs, ui_text

PREF_KEY = "ui_language"
ENV = "YESONCHECK_LANGUAGE"
NAMES = {"ko": "한국어", "en": "English"}  # 메뉴 항목의 글 — 두 언어에서 같음(자기 언어로 적은 이름)
MENU_TEXT = "언어 (Language)"  # 두 언어에서 같음 — 어느 화면에서도 찾을 수 있게
SETTINGS_TITLE = "언어 설정"  # 알림 창의 제목 (딸린 창 — 한글)
LOG_PREFIX = "[언어]"

# 지금 언어를 어디서 정했는지 (기록 줄·메뉴의 툴팁)
SOURCE_ENV = f"환경 변수 {ENV}"
SOURCE_PREFS = "prefs.json"
SOURCE_OS = "OS 언어"
SOURCE_MENU = "Settings 메뉴"
SOURCE_FALLBACK = "설정 읽기 실패 — 이 세션만 한국어"

_source = SOURCE_OS


def _checked(code, where):
    if code not in ui_text.LANGUAGES:
        raise ValueError(f"{where}는 {' 또는 '.join(ui_text.LANGUAGES)} 중 하나여야 합니다: {code!r}")
    return code


def env_language(environ=None):
    """환경 변수가 정한 언어. 없거나 비면 None, 대소문자·앞뒤 공백 무시, 그 밖의 값은 ValueError."""
    value = (os.environ if environ is None else environ).get(ENV, "").strip().lower()
    if not value:
        return None
    return _checked(value, ENV)


def read(path=None):
    """저장된 언어. 키가 없으면 None, 모르는 값은 ValueError, 깨진 파일은 UserFileError 그대로."""
    value = mac_prefs.read_prefs(path or hover_strip.prefs_path()).get(PREF_KEY)
    if value is None:
        return None
    return _checked(value, PREF_KEY)


def save(code, path=None):
    """파일에 저장 (그 키만 — 다른 키는 그대로). 모르는 값은 쓰기 전에 ValueError, 깨진 파일은 덮지 않고 UserFileError."""
    mac_prefs.update_pref(PREF_KEY, _checked(code, PREF_KEY), path or hover_strip.prefs_path())


def from_locale(names):
    """OS의 화면 언어 목록(앞이 먼저 — 예 ['ko-KR', 'en-US'])에서: 첫 언어가 한국어면 "ko", 아니면(비어도) "en"."""
    first = names[0] if names else ""
    language = first.replace("_", "-").split("-")[0].lower()  # 언어 부분만 — 'kok'(콘칸어)는 한국어가 아님 (리뷰 M-6)
    return "ko" if language == "ko" else "en"


def set_source(text):
    global _source
    _source = text


def source():
    """이 프로세스가 지금 언어를 어디서 정했는지 (`SOURCE_*`)."""
    return _source
