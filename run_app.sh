#!/bin/bash
# YesonCheck 원클릭 실행 (개발 모드)
cd "$(dirname "$0")"
if [ -n "$VIRTUAL_ENV" ]; then
    # 이미 가상환경이 활성화된 경우
    exec python -m yesoncheck.app "$@"
fi
if [ -x "$HOME/coding/p310/bin/python" ]; then
    exec "$HOME/coding/p310/bin/python" -m yesoncheck.app "$@"
fi
# fallback: 시스템 python
exec python3 -m yesoncheck.app "$@"
