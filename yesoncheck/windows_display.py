# -*- coding: utf-8 -*-
"""(Windows) 화면 그리기 설정 — CPU(raster, 기본) 또는 GPU(GL 뷰포트). Qt 없음.

왜: Windows 4K를 CPU로 그리면(변환 + 부드러운 축소가 GUI 스레드) 재생이 끊기는 구간이 있고 GL은 줄어듦(사용자 확인 2026-11-05, 스튜디오 PC 한 대). 다만 PC마다
그래픽 카드·드라이버가 달라 끄는 길이 필요하고, 와이프·주석·고DPI를 확인하기 전이라 기본은 CPU(사용자 결정). Settings 메뉴에서 고르고 %LOCALAPPDATA%\\YesonCheck\\prefs.json에
저장하며 다음에 여는 창부터 적용(뷰포트는 창을 만들 때 정함). 환경 변수 YESONCHECK_VIEWPORT가 있으면 그쪽이 우선.

GPU를 골라도 그리기 코드(gl_video_item — 고정 기능 GL)와 맞지 않는 GL이면 쓰지 않음: ES(ANGLE)는 그리기가 실패하고, 소프트웨어 GL은 오류 없이 CPU보다 느릴 수 있음.
Mac의 재생 디코더 메뉴와 달리 파일 읽기 실패 때 설정을 지어내지 않는 규칙은 같음 (app.load_display_renderer).
"""

import os

from yesoncheck import mac_prefs

PREF_KEY = "display_renderer"
RENDERERS = ("cpu", "gpu")
DEFAULT_RENDERER = "cpu"
MENU_TEXT = "화면 그리기 (Windows)"
ACTION_TEXTS = {"cpu": "CPU (기본)", "gpu": "GPU"}
MIN_GL_VERSION = (2, 0)
SOFTWARE_RENDERER_WORDS = ("llvmpipe", "softpipe", "swiftshader", "microsoft basic render", "gdi generic")

_preferred = DEFAULT_RENDERER  # 프로세스 캐시 — app.load_display_renderer가 시작 때 정하고 메뉴가 바꿈 (mac_native_gate와 같은 모양)


def set_preferred(name) -> None:
    """RENDERERS 밖의 값은 ValueError(키와 받은 값을 글에) — 조용히 기본으로 넘기지 않으며 캐시는 그대로."""
    global _preferred
    if name not in RENDERERS:
        raise ValueError(f"{PREF_KEY}는 {', '.join(RENDERERS)} 중 하나여야 합니다: {name!r}")
    _preferred = name


def preferred() -> str:
    return _preferred


def prefs_path() -> str:
    """%LOCALAPPDATA%\\YesonCheck\\prefs.json — 이 PC의 설정 (창 기록·앱 기록과 같은 곳)."""
    return os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", mac_prefs.PREFS_FILE_NAME)


def read() -> str:
    """저장된 값 (없으면 기본). 깨진 파일은 UserFileError, 나쁜 값은 부른 쪽이 set_preferred로 걸러 ValueError."""
    return mac_prefs.read_prefs(prefs_path()).get(PREF_KEY, DEFAULT_RENDERER)


def save(name) -> None:
    """파일에 저장 (그 키만 고침). 깨진 파일은 덮지 않고 UserFileError."""
    mac_prefs.update_pref(PREF_KEY, name, prefs_path())


def gl_problem(info):
    """이 GL을 그리기 코드가 쓸 수 없는 이유 — 쓸 수 있으면 None. info: gl_bindings.GLInfo, 컨텍스트를 못 만들었으면 None."""
    if info is None:
        return "OpenGL 컨텍스트를 만들지 못했습니다"
    if info.is_es:
        return f"OpenGL ES(ANGLE) 컨텍스트입니다 ({info.renderer}) — 그리기 코드는 데스크톱 OpenGL만 씁니다"
    renderer = info.renderer.lower()
    if any(word in renderer for word in SOFTWARE_RENDERER_WORDS):
        return f"소프트웨어 OpenGL입니다 ({info.renderer}) — CPU 그리기보다 나을 것이 없습니다"
    if info.version < MIN_GL_VERSION:
        return f"OpenGL {info.version[0]}.{info.version[1]}입니다 ({info.renderer}) — {MIN_GL_VERSION[0]}.{MIN_GL_VERSION[1]} 이상이 필요합니다"
    return None


def fallback_text(problem) -> str:
    """GPU를 골랐는데 쓸 수 없을 때 창에 보일 글."""
    return f"GPU 화면 그리기를 쓸 수 없어 CPU로 계속합니다.\n{problem}\n\nSettings → {MENU_TEXT} → {ACTION_TEXTS['cpu']}를 고르면 이 알림이 뜨지 않습니다."
