"""빌드 정보: 빌드가 앱에 넣은 build_info.json(버전·커밋·빌드 시각·플랫폼)을 읽어 창 제목·정보 창에 보임.

tools/write_build_info.py가 PyInstaller 앞에 build/build_info.json을 만들고, spec이 앱 맨 위(sys._MEIPASS —
Mac: Contents/Resources, Windows: _internal)에 넣음. 소스에서 실행하면 파일이 없음 → 버전 "개발(소스)".
버전 형식: 배포판 X.Y.Z, 배포가 아닌 빌드 X.Y.Z+<커밋 7자리>(커밋 안 된 변경이 있었으면 끝에 .dirty).
"""

import functools
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, fields

FILE_NAME = "build_info.json"
APP_NAME = "Yeson Checker"
SOURCE_VERSION = "개발(소스)"  # 소스 실행의 버전 (빌드 정보 없음)
TEST_BUILD_MARK = " (시험 빌드)"  # 배포가 아닌 빌드(버전에 + 있음)의 표시
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(\+[0-9a-f]{7}(\.dirty)?)?")
PLATFORM_KEYS = ("windows", "mac-x86_64", "mac-arm64")


@dataclass(frozen=True)
class BuildInfo:
    version: str  # "1.1.0"(배포판) 또는 "1.1.0+0f4d3d7"(배포가 아닌 빌드)
    commit: str  # 빌드한 커밋 (git rev-parse HEAD)
    built: str  # 빌드 시각 (ISO 8601, 시간대 포함: 2026-10-20T10:00:00+09:00)
    platform_key: str  # PLATFORM_KEYS 중 하나

    @property
    def is_release(self):
        """배포판(태그 vX.Y.Z가 붙은 커밋을 깨끗한 작업 폴더에서 빌드)인지."""
        return "+" not in self.version


def load(base_dir):
    """base_dir의 build_info.json을 읽음. 파일이 없거나 형식이 다르면 RuntimeError (경로 포함)."""
    path = os.path.join(base_dir, FILE_NAME)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"빌드 정보를 읽지 못했습니다: {path}\n{exc}") from exc
    names = [f.name for f in fields(BuildInfo)]
    if not isinstance(data, dict) or not all(isinstance(data.get(name), str) for name in names):
        raise RuntimeError(f"빌드 정보 형식이 다릅니다 (문자열 {', '.join(names)}가 있어야 함): {path}\n{data!r}")
    if not VERSION_PATTERN.fullmatch(data["version"]):
        raise RuntimeError(f"빌드 정보의 버전 형식이 다릅니다 (X.Y.Z 또는 X.Y.Z+<커밋 7자리>): {path}\n{data['version']!r}")
    return BuildInfo(**{name: data[name] for name in names})


@functools.lru_cache(maxsize=None)
def _frozen_info():
    return load(sys._MEIPASS)


def current():
    """이 앱의 빌드 정보. 소스 실행이면 None, 빌드된 앱이면 sys._MEIPASS의 파일(처음 한 번 읽고 기억)."""
    if not getattr(sys, "frozen", False):
        return None
    return _frozen_info()


def platform_key():
    """이 파이썬이 도는 플랫폼의 키: Windows "windows", Mac "mac-x86_64"·"mac-arm64"."""
    if sys.platform == "win32":
        key = "windows"
    elif sys.platform == "darwin":
        key = "mac-" + platform.machine()
    else:
        key = sys.platform
    if key not in PLATFORM_KEYS:
        raise RuntimeError(f"지원하지 않는 플랫폼입니다: {key} (지원: {', '.join(PLATFORM_KEYS)})")
    return key


def title_base():
    """창 제목의 앞부분: 빌드된 앱 "Yeson Checker 1.1.0", 소스 실행 "Yeson Checker"."""
    info = current()
    return APP_NAME if info is None else f"{APP_NAME} {info.version}"


def display_version():
    """보여 줄 버전: "1.1.0", 배포가 아닌 빌드 "1.1.0+0f4d3d7 (시험 빌드)", 소스 실행 "개발(소스)"."""
    info = current()
    if info is None:
        return SOURCE_VERSION
    return info.version if info.is_release else info.version + TEST_BUILD_MARK
