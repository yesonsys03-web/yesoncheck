#!/bin/bash
# YesonCheck macOS 앱 번들 원클릭 빌드 (PyInstaller)
# 빌드하는 Mac의 아키텍처용 앱이 만들어짐 (지원: macOS 12 몬터레이 이상)
#   Intel Mac         → dist/YesonCheck_Autocut_Intel.app
#   Apple Silicon Mac → dist/YesonCheck_Autocut_AppleSilicon.app
set -e
cd "$(dirname "$0")"
PY="${PY:-$HOME/coding/p310/bin/python}"
if [ ! -x "$PY" ]; then
    echo "Python not found: $PY"
    echo "먼저 ./setup_build_env.sh 로 빌드 환경을 만들거나 PY=... 로 지정하세요."
    exit 1
fi
ARCH="$("$PY" -c 'import platform; print(platform.machine())')"
case "$ARCH" in
    x86_64) LABEL="Intel" ;;
    arm64)  LABEL="AppleSilicon" ;;
    *) echo "지원하지 않는 아키텍처: $ARCH"; exit 1 ;;
esac
echo "빌드 시작 (YesonCheck_Autocut.spec, $ARCH)..."
"$PY" -m PyInstaller --clean -y YesonCheck_Autocut.spec
OUT="dist/YesonCheck_Autocut_${LABEL}.app"
rm -rf "$OUT"
mv dist/YesonCheck_Autocut.app "$OUT"
echo "번들 바이너리 검사 (아키텍처·최소 macOS·외부 dylib)..."
"$PY" check_min_macos.py "$OUT" "$ARCH"
echo "번들 모듈 검사 (OCR·씬 감지 실행 경로의 모듈이 앱에 모두 있는지)..."
"$PY" check_frozen_imports.py "$OUT"
# 배포용 디스크 이미지: .app 안에는 심볼릭 링크가 수백 개 있어 폴더째 NAS·메신저로 옮기면 링크가 깨지고
# 실행 시 "No module named 'encodings'"로 멈춤 → 파일 하나(.dmg)로 묶어서 옮김
DMG="dist/YesonCheck_Autocut_${LABEL}.dmg"
STAGE="build/dmg_stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
ditto "$OUT" "$STAGE/$(basename "$OUT")"
ln -s /Applications "$STAGE/Applications"
echo "배포용 디스크 이미지 생성: $DMG"
hdiutil create -volname "YesonCheck_Autocut_${LABEL}" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
rm -rf "$STAGE"
echo "완료. 앱 위치: $OUT"
echo "      배포 파일: $DMG (다른 Mac에는 이 .dmg를 옮겨서 설치)"
