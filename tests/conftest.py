"""pytest 공통 설정: 프로젝트 루트를 import 경로에, Qt는 화면 없이, ffmpeg는 저장소의 정적 빌드."""

import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# fetch_ffmpeg.sh / fetch_ffmpeg_windows.ps1로 받은 정적 ffmpeg를 PATH 맨 앞에 둠
_FFMPEG_DIR = os.path.join(
    ROOT, "vendor", "ffmpeg", "windows" if sys.platform == "win32" else platform.machine()
)
if os.path.isdir(_FFMPEG_DIR):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")
