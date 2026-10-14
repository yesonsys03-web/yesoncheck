#!/bin/bash
# YesonCheck 원클릭 실행 (개발 모드)
cd "$(dirname "$0")"
if [ -n "$VIRTUAL_ENV" ]; then
    # 이미 가상환경이 활성화된 경우
    exec python -m yesoncheck.app "$@"
fi
# 빌드 환경(./setup_build_env.sh, TensorFlow 포함 — 애니매틱2)
if [ -x "$HOME/coding/p310_tf/bin/python" ]; then
    exec "$HOME/coding/p310_tf/bin/python" -m yesoncheck.app "$@"
fi
# fallback: 시스템 python
exec python3 -m yesoncheck.app "$@"
