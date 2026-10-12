#!/bin/bash
# YesonCheck 빌드 환경(Python 3.10 가상환경) 생성. Intel/Apple Silicon 공통
# 필요: uv (brew install uv)
set -e
cd "$(dirname "$0")"
VENV="${VENV:-$HOME/coding/p310}"
if ! command -v uv >/dev/null 2>&1; then
    echo "uv가 필요합니다: brew install uv"
    exit 1
fi
if [ -e "$VENV" ]; then
    echo "이미 있습니다: $VENV"
    echo "기존 환경을 지우고 다시 만들려면 직접 삭제하거나, VENV=다른경로 로 지정하세요."
    exit 1
fi
# uv가 관리하는 Python만 사용 (Homebrew Python은 그 Mac의 macOS 버전 이상에서만 실행돼 몬터레이 검사에 걸림)
uv venv "$VENV" --python 3.10 --managed-python
# 아키텍처는 터미널(uname)이 아니라 실제 venv Python 기준 (Rosetta 터미널 대비)
ARCH="$("$VENV/bin/python" -c 'import platform; print(platform.machine())')"
case "$ARCH" in
    x86_64) PLATFORM="x86_64-apple-darwin" ;;
    arm64)  PLATFORM="aarch64-apple-darwin" ;;
    *) echo "지원하지 않는 아키텍처: $ARCH"; exit 1 ;;
esac
LOCK="requirements-build-$ARCH.lock"
echo "아키텍처 $ARCH → $LOCK 설치"
# 빌드하는 Mac이 최신 macOS여도 몬터레이(12.0)용 휠을 고르도록 지정
# (지정하지 않으면 scipy 등이 macOS 14 전용 휠로 설치됨)
export MACOSX_DEPLOYMENT_TARGET=12.0
uv pip install --python "$VENV/bin/python" --python-platform "$PLATFORM" -r "$LOCK"
# opencv 세 패키지가 같은 cv2 폴더를 씀 → 기존 앱과 같은 contrib 판이 최종으로 남도록 재설치
uv pip install --python "$VENV/bin/python" --python-platform "$PLATFORM" --reinstall-package opencv-contrib-python opencv-contrib-python==4.6.0.66
"$VENV/bin/python" -c "
import cv2
from cv2 import version
assert version.contrib and not version.headless, f'cv2가 contrib 판이 아닙니다: contrib={version.contrib} headless={version.headless}'
print('cv2', cv2.__version__, 'contrib 확인')
import paddle
print('paddle', paddle.__version__)
paddle.utils.run_check()
"
echo "완료: $VENV ($ARCH)"
echo "다음: ./build_app.sh  (PY=$VENV/bin/python ./build_app.sh)"
