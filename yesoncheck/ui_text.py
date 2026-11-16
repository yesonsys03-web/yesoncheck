"""메인 창의 화면 글자 표 — 키 하나에 한국어·English 글 (Qt 없음).

화면에 보이는 글자(단추·툴팁·메뉴)는 코드에 직접 적지 않고 `text("키")`로 읽는다. 지금 언어는 이 프로세스에 하나
(`set_language` — 창마다 프로세스가 하나). 언어를 고르는 메뉴와 저장은 다음 단계라 지금은 늘 기본(한국어).

글을 더하거나 고칠 때는 **두 언어를 함께** — `missing()`이 빠진 키를 알려 주고 시험이 그것이 비었는지 본다.
글 안의 `{이름}`은 `text(키, 이름=값)`으로 채운다. 단추·메뉴 이름에 붙는 단축키 표기(`(Space)`)도 글에 적는다.
"""

LANGUAGES = ("ko", "en")
DEFAULT_LANGUAGE = "ko"

TEXTS = {
    # 재생 줄 (transport_bar)
    "transport.first": {"ko": "처음으로 (Home)", "en": "Go to start (Home)"},
    "transport.prev": {"ko": "한 장 뒤로 (←)", "en": "Step back one frame (←)"},
    "transport.play": {"ko": "재생 (Space)", "en": "Play (Space)"},
    "transport.pause": {"ko": "일시정지 (Space)", "en": "Pause (Space)"},
    "transport.next": {"ko": "한 장 앞으로 (→)", "en": "Step forward one frame (→)"},
    "transport.last": {"ko": "끝으로 (End)", "en": "Go to end (End)"},
    "transport.loop": {"ko": "반복 재생", "en": "Loop playback"},
    "transport.frame": {"ko": "프레임 번호 — 숫자를 치고 Enter", "en": "Frame number — type a number and press Enter"},
    "transport.volume": {"ko": "볼륨 {percent}%", "en": "Volume {percent}%"},
    # 고른 영상 이어 재생(선택 재생)
    "playlist.end": {"ko": "이어 재생 끝내기", "en": "End playlist"},
    "playlist.end.tip": {"ko": "고른 영상 이어 재생을 끝내고 처음으로 돌아갑니다",
                         "en": "Ends playing the selected videos in a row and returns to the start"},
}

_language = DEFAULT_LANGUAGE


def language():
    """지금 언어 (`LANGUAGES` 중 하나)."""
    return _language


def set_language(code):
    """지금 언어를 바꿈. 모르는 값은 ValueError — 지금 언어는 그대로."""
    global _language
    if code not in LANGUAGES:
        raise ValueError(f"모르는 언어: {code!r} (쓸 수 있는 값: {', '.join(LANGUAGES)})")
    _language = code


def text(key, **values):
    """키의 지금 언어 글. 모르는 키는 KeyError(글을 지어내지 않음). values는 글 안의 `{이름}`을 채움."""
    template = TEXTS[key][_language]
    return template.format(**values) if values else template


def missing():
    """한 언어라도 글이 없거나 빈 키 (키 이름순)."""
    return sorted(key for key, texts in TEXTS.items()
                  if any(not str(texts.get(code, "")).strip() for code in LANGUAGES))
