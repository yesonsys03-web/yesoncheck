#!/bin/bash
# 번들용 정적 ffmpeg/ffprobe 내려받기 (vendor/ffmpeg/{x86_64,arm64})
# 바이너리는 크기 때문에 git에 넣지 않음 → clone한 뒤 빌드 전에 한 번 실행
# 출처·버전은 vendor/ffmpeg/README.md, 받은 파일은 아래 sha256과 맞아야 함
set -e
cd "$(dirname "$0")"
BASE="https://ffmpeg.martin-riedl.de/download/macos"
# 미러: 이 저장소 Release(ci-ffmpeg-9.0.2)에 올려 둔 같은 zip — 원 서버가 GitHub 러너에서 간헐적으로
# 끊기거나(curl 56) 연결만 받고 멈춰(10KB/s 미만 스톨 9연속) 2026-10-28 CI가 4번 실패했음.
# 출처가 어디든 아래 sha256 고정 확인을 통과해야만 쓰임.
MIRROR="https://github.com/yesonsys03-web/yesoncheck/releases/download/ci-ffmpeg-9.0.2"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# 아키텍처 다운로드경로 도구 sha256
while read -r ARCH URLPATH TOOL SHA; do
    DEST="vendor/ffmpeg/$ARCH/$TOOL"
    if [ -f "$DEST" ] && [ "$(shasum -a 256 "$DEST" | cut -d' ' -f1)" = "$SHA" ]; then
        echo "있음: $DEST"
        continue
    fi
    echo "받는 중: $DEST"
    # 미러 먼저, 안 되면 원 서버. 멈춤 감지: 30초 동안 10KB/s 미만이면 그 시도를 끊고(curl 28) 재시도
    # (connect-timeout은 연결까지만 제한이라 스톨에는 무력), 시도당 5분·주소당 재시도 10분 상한.
    rm -f "$TMP/$TOOL.zip"
    for URL in "$MIRROR/${ARCH}_${TOOL}.zip" "$BASE/$URLPATH/$TOOL.zip"; do
        if curl -fL --retry 4 --retry-delay 5 --retry-all-errors --retry-max-time 600 \
            --connect-timeout 30 --max-time 300 --speed-limit 10240 --speed-time 30 \
            --progress-bar -o "$TMP/$TOOL.zip" "$URL"; then
            break
        fi
        echo "받지 못함 — 다음 주소로: $URL"
        rm -f "$TMP/$TOOL.zip"
    done
    [ -s "$TMP/$TOOL.zip" ] || { echo "모든 주소에서 받지 못함: $TOOL"; exit 1; }
    rm -f "$TMP/$TOOL"
    unzip -q -o "$TMP/$TOOL.zip" "$TOOL" -d "$TMP"
    GOT="$(shasum -a 256 "$TMP/$TOOL" | cut -d' ' -f1)"
    if [ "$GOT" != "$SHA" ]; then
        echo "sha256 불일치: $DEST"
        echo "  기대: $SHA"
        echo "  실제: $GOT"
        exit 1
    fi
    mkdir -p "vendor/ffmpeg/$ARCH"
    mv "$TMP/$TOOL" "$DEST"
    chmod +x "$DEST"
done <<'EOF'
x86_64 amd64/1789931006_9.0.2 ffmpeg b25689cf2211c0582d317e849912769a1f1c93904fe102c485b5364a425633d1
x86_64 amd64/1789931006_9.0.2 ffprobe b5df9964b0c2048318fafedcd4e3bbafbc561033cee77de8da1840685d8a9d0d
arm64 arm64/1789931890_9.0.2 ffmpeg 2e11c6f90993cdb79fff84d3f90044d28316b310e75b3e030cfc9a54f2c9d384
arm64 arm64/1789931890_9.0.2 ffprobe 2738aa46a7f9acbc8ab09a6715554c90f7de603171ac403726765685df6a0059
EOF
echo "완료: vendor/ffmpeg"
