"""예상된 실패·예상 못 한 오류를 기록과 오류 창으로 — default_app(Mac 기본 앱)·file_associations(Windows 파일 연결)·
mac_app_events(파일 열기·앱 다시 열기)·player_base(GL 뷰포트 폴백 알림 show_viewport_fallback)가 함께 씀.

오류 창(show_window)은 빌드 앱이면 앱의 예외 창(app.make_excepthook가 sys.excepthook.dialog로 둔 app._ErrorDialog — 기록 파일
경로를 붙이고, 이미 떠 있으면 기록에만 — 같은 실패가 되풀이돼도 창이 쌓이지 않음), 그 창이 없으면(소스 실행) 같은 제목(TITLE)의
QMessageBox.critical. 트레이스백은 창에 끝 DETAILS_LIMIT 글자만(무엇이 실패했는지 — 앞의 글 — 는 그대로), 기록에는 전부.
GUI 스레드에서 부를 것.
"""

import sys
import traceback

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

TITLE = "YesonCheck 오류"  # 앱의 예외 창(app._ErrorDialog)과 같은 제목
DETAILS_LIMIT = 3000  # 오류 창에 보이는 트레이스백의 끝 글자 수 (예외 글이 끝에 있음 — 기록에는 전부)


def show_error(prefix: str, text: str) -> None:
    """기록(stderr)에 "<prefix> <text>"를 남기고 text를 오류 창으로 (모듈 설명). prefix: 기록 줄의 머리 (예: "[기본 앱]")."""
    print(f"{prefix} {text}", file=sys.stderr, flush=True)
    show_window(text)


def show_unexpected(prefix: str, context: str) -> None:
    """예외 처리 중에(except 블록 안): context와 지금 처리 중인 예외의 트레이스백을 기록(전부)·오류 창(with_details)으로."""
    details = traceback.format_exc()
    print(f"{prefix} {context}\n\n{details}", file=sys.stderr, flush=True)
    show_window(with_details(context, details))


def with_details(context: str, details: str) -> str:
    """오류 창의 글: context(무엇이 실패했는지)는 그대로, 트레이스백 details는 끝 DETAILS_LIMIT 글자만."""
    return f"{context}\n\n{details[-DETAILS_LIMIT:]}"


def show_window(text: str) -> None:
    """text를 오류 창으로만 (기록은 부른 쪽이 — 모듈 설명). 자르지 않음."""
    dialog = getattr(sys.excepthook, "dialog", None)
    if dialog is not None:
        dialog.show_text(text)
    else:
        QMessageBox.critical(None, TITLE, text)


def report_from_handler(prefix: str, context: str) -> None:
    """(except 블록 안에서) PyQt5 가상 함수(eventFilter·done·paint 등)에서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음) —
    그 except 블록용: 지금 처리 중인 예외의 트레이스백을 바로 기록하고, 오류 창은 Qt 루프에서(이벤트 처리 안에서 모달을 열지 않게).
    예외를 내보내지 않는다: 알리다 또 실패하면 _last_resort(원래 stderr). (mac_app_events._report_error와 같은 모양.)"""
    try:
        details = traceback.format_exc()
        print(f"{prefix} {context}\n\n{details}", file=sys.stderr, flush=True)
        text = with_details(context, details)
        QTimer.singleShot(0, lambda: _show_window_guarded(prefix, text))
    except BaseException:
        _last_resort(prefix, context)


def _show_window_guarded(prefix: str, text: str) -> None:
    """(Qt 루프에서) 오류 창 — 실패해도 Qt 루프로 내보내지 않음 (_last_resort)."""
    try:
        show_window(text)
    except BaseException:
        _last_resort(prefix, text)


def _last_resort(prefix: str, message: str) -> None:
    """(except 블록 안에서) 오류를 알리다 또 실패함: 원래 stderr(sys.__stderr__ — 기록 파일로 바꾸기 전)에 message와 지금 처리 중인
    예외를 씀. 원래 stderr가 없으면(Windows 창 앱) 그 예외를 그대로 올림 — 조용히 삼키지 않음."""
    stream = sys.__stderr__
    if stream is None:
        raise
    stream.write(f"{prefix} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
    stream.flush()
