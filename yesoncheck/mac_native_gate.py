"""(스파이크 — spike/mac-native, 버리는 브랜치) Mac 네이티브 재생(VideoToolbox → IOSurface → GL) 토글.

YESONCHECK_MAC_NATIVE = auto(기본) | on | off. auto는 Apple Silicon Mac에서만 켜짐, on은 Intel Mac에서도 켬(개발용 —
PyObjC가 있는 venv), off는 늘 끔(1.6.1의 ffmpeg 파이프 경로). 그 밖의 값은 ValueError(조용한 폴백 금지).
"""

import os
import platform
import sys

NATIVE_MODE_ENV = "YESONCHECK_MAC_NATIVE"
NATIVE_MODES = ("auto", "on", "off")


def native_mode(env=None):
    """환경 변수 값 — 없거나 비면 "auto", 대소문자 무시, 그 밖은 ValueError."""
    env = os.environ if env is None else env
    given = env.get(NATIVE_MODE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in NATIVE_MODES:
        raise ValueError(f"{NATIVE_MODE_ENV}는 {', '.join(NATIVE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
    return mode


def native_wanted(env=None):
    """네이티브 경로를 쓸지: off → False, on → True, auto → Apple Silicon Mac(darwin·arm64)."""
    mode = native_mode(env)
    if mode == "off":
        return False
    if mode == "on":
        return True
    return sys.platform == "darwin" and platform.machine() == "arm64"
