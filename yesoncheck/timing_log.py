"""시간 기록 줄: [<태그> HH:MM:SS.mmm] … — 시작이 어디서 멈추는지 로그로 알 수 있게.

느릴 수 있는 단계는 앞("… 중…")과 뒤("… (n초)")에 모두 찍는다: 멈추면 로그의 마지막 줄이 그 단계를 가리킨다.
빌드 앱(Windows·Mac)은 stdout이 창(프로세스)마다의 기록 파일 yesoncheck_<날짜>_<pid>.log(줄 단위 버퍼 — Windows
%LOCALAPPDATA%\\YesonCheck\\logs, Mac ~/Library/Logs/YesonCheck, app.setup_app_logging)이다.
여러 스레드(공유 설정 백그라운드 읽기, 공유별 동시 확인)에서 불러도 줄이 섞이지 않게 잠근다.
"""

import datetime
import threading
import time

_lock = threading.Lock()


def log(tag, message):
    now = datetime.datetime.now()
    line = f"[{tag} {now:%H:%M:%S}.{now.microsecond // 1000:03d}] {message}"
    with _lock:
        print(line, flush=True)


def startup(message):
    """시작 과정의 줄: [시작 HH:MM:SS.mmm] …"""
    log("시작", message)


def since(started):
    """time.perf_counter()로 잰 시작 시각부터 지난 시간 (예: '0.12초')."""
    return f"{time.perf_counter() - started:.2f}초"
