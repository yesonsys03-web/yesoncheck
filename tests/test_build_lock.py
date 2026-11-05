"""빌드 의존성 lock: PyObjC(네이티브 재생 — mac_native_source)는 Mac 두 lock(arm64·x86_64)에 모두 들어가고 Windows lock에는 없어야 한다
(Intel Mac도 VideoToolbox로 ProRes를 디코드하므로 네이티브 경로를 쓴다 — 스펙 2026-11-04 §5.6). 직접 고정 목록(requirements-build.txt)의
PyObjC 줄은 모두 `sys_platform == "darwin"` 마커만 달고(arm64 한정 마커 없음), 하드웨어 디코드 확인은 ctypes로 하므로(Ruling 15)
VideoToolbox 래퍼는 고정하지 않는다.

lock은 requirements-build.txt 맨 위 명령(uv pip compile — 아키텍처별 --python-platform)으로 만든 결과라 마커 없이 그 플랫폼에서 풀린
패키지만 적힌다. 고정 목록을 고치고 lock을 다시 만들지 않으면 이 시험이 잡는다."""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYOBJC_VERSION = "12.2.2"
DARWIN_MARKER = 'sys_platform == "darwin"'
# 직접 고정하는 PyObjC (이름은 requirements-build.txt에 적은 그대로) — 나머지(Cocoa·CoreAudio·CoreMedia)는 AVFoundation이 끌어옴
DIRECT_PYOBJC = ("pyobjc-core", "pyobjc-framework-AVFoundation", "pyobjc-framework-Quartz")
# lock에 실제로 풀리는 여섯 (AVFoundation이 Cocoa·CoreAudio·CoreMedia를 끌어옴)
MAC_PYOBJC = DIRECT_PYOBJC + ("pyobjc-framework-Cocoa", "pyobjc-framework-CoreAudio", "pyobjc-framework-CoreMedia")


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def pinned(text):
    """lock·고정 목록의 패키지 줄(주석·들여쓴 '# via' 줄 제외) → {소문자 이름: 줄 전체}."""
    pins = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name = re.split(r"[=<>!~;\s\[]", line, maxsplit=1)[0]
        pins[name.lower()] = line.strip()
    return pins


@pytest.mark.parametrize("lock", ["requirements-build-arm64.lock", "requirements-build-x86_64.lock"])
def test_both_mac_locks_have_pyobjc_pinned(lock):
    """Mac 두 lock(Apple Silicon·Intel) 모두에 직접 고정한 셋이 12.2.2로 있고, 함께 끌려온 pyobjc 패키지(Cocoa·CoreAudio·CoreMedia)도 모두
    같은 판 (판이 섞이면 PyObjC가 깨짐). 여섯 개가 정확히 이 이름들이어야 함 (VideoToolbox 래퍼는 없음)."""
    pins = pinned(read(lock))
    for name in DIRECT_PYOBJC:
        assert pins.get(name.lower()) == f"{name.lower()}=={PYOBJC_VERSION}", f"{lock}에 {name}=={PYOBJC_VERSION}이 없습니다"
    pyobjc = {name: line for name, line in pins.items() if name.startswith("pyobjc")}
    assert all(line.endswith(f"=={PYOBJC_VERSION}") for line in pyobjc.values()), pyobjc
    assert sorted(pyobjc) == sorted(name.lower() for name in MAC_PYOBJC), pyobjc
    assert "pyobjc-framework-videotoolbox" not in pyobjc, "VideoToolbox 래퍼는 넣지 않음 — 하드웨어 디코드 확인은 ctypes (Ruling 15)"


def test_windows_lock_has_no_pyobjc():
    assert "pyobjc" not in read("requirements-build-windows.lock").lower(), "requirements-build-windows.lock에 PyObjC가 있습니다 — Windows에는 넣지 않음"


def test_direct_pyobjc_pins_carry_the_darwin_marker():
    """requirements-build.txt의 PyObjC 줄은 직접 고정한 셋뿐이고, 모두 '== 12.2.2; sys_platform == "darwin"' 정확히 — arm64 한정 마커가 남으면
    Intel lock이 PyObjC를 빼고, darwin 마커가 빠지면 Windows lock이 PyObjC를 끌어옴 (위 시험과 짝: 고정 목록과 lock 둘 다 봄)."""
    lines = [line.strip() for line in read("requirements-build.txt").splitlines()
             if "pyobjc" in line.lower() and not line.lstrip().startswith("#")]
    assert lines == [f"{name}=={PYOBJC_VERSION}; {DARWIN_MARKER}" for name in DIRECT_PYOBJC]
