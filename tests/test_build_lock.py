"""빌드 의존성 lock: PyObjC(Apple Silicon 네이티브 재생 — mac_native_source)는 arm64 lock에만 들어가고 Intel(x86_64)·Windows lock에는
없어야 한다 (스펙 §5.9 — Intel·Windows 빌드는 PyObjC를 넣지도 불러오지도 않음). 직접 고정 목록(requirements-build.txt)의 PyObjC 줄은
모두 darwin + arm64 마커를 달고, 하드웨어 디코드 확인은 ctypes로 하므로(Ruling 15) VideoToolbox 래퍼는 고정하지 않는다.

lock은 requirements-build.txt 맨 위 명령(uv pip compile — 아키텍처별 --python-platform)으로 만든 결과라 마커 없이 그 플랫폼에서 풀린
패키지만 적힌다. 고정 목록을 고치고 lock을 다시 만들지 않으면 이 시험이 잡는다."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYOBJC_VERSION = "12.2.2"
ARM64_MARKER = 'sys_platform == "darwin" and platform_machine == "arm64"'
# 직접 고정하는 PyObjC (이름은 requirements-build.txt에 적은 그대로) — 나머지(Cocoa·CoreAudio·CoreMedia)는 AVFoundation이 끌어옴
DIRECT_PYOBJC = ("pyobjc-core", "pyobjc-framework-AVFoundation", "pyobjc-framework-Quartz")


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


def test_arm64_lock_has_pyobjc_pinned():
    """arm64 lock에 직접 고정한 셋이 12.2.2로 있고, 함께 끌려온 pyobjc 패키지도 모두 같은 판 (판이 섞이면 PyObjC가 깨짐)."""
    pins = pinned(read("requirements-build-arm64.lock"))
    for name in DIRECT_PYOBJC:
        assert pins.get(name.lower()) == f"{name.lower()}=={PYOBJC_VERSION}", f"arm64 lock에 {name}=={PYOBJC_VERSION}이 없습니다"
    pyobjc = {name: line for name, line in pins.items() if name.startswith("pyobjc")}
    assert all(line.endswith(f"=={PYOBJC_VERSION}") for line in pyobjc.values()), pyobjc
    assert "pyobjc-framework-videotoolbox" not in pyobjc, "VideoToolbox 래퍼는 넣지 않음 — 하드웨어 디코드 확인은 ctypes (Ruling 15)"


def test_intel_and_windows_locks_have_no_pyobjc():
    for lock in ("requirements-build-x86_64.lock", "requirements-build-windows.lock"):
        assert "pyobjc" not in read(lock).lower(), f"{lock}에 PyObjC가 있습니다 — arm64 전용이어야 함 (스펙 §5.9)"


def test_direct_pyobjc_pins_carry_the_arm64_marker():
    """requirements-build.txt의 PyObjC 줄은 직접 고정한 셋뿐이고, 모두 '== 12.2.2; darwin + arm64' — 마커가 빠지면 Intel·Windows lock이
    PyObjC를 끌어옴 (위 시험과 짝: 고정 목록과 lock 둘 다 봄)."""
    lines = [line.strip() for line in read("requirements-build.txt").splitlines()
             if "pyobjc" in line.lower() and not line.lstrip().startswith("#")]
    assert lines == [f"{name}=={PYOBJC_VERSION}; {ARM64_MARKER}" for name in DIRECT_PYOBJC]
