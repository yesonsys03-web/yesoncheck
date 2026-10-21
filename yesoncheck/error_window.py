"""예상된 실패·예상 못 한 오류를 기록과 오류 창으로 — default_app(Mac 기본 앱)·file_associations(Windows 파일 연결)가 함께 씀.

오류 창은 빌드 앱이면 앱의 예외 창(app.make_excepthook가 sys.excepthook.dialog로 둔 app._ErrorDialog — 기록 파일 경로를 붙이고,
이미 떠 있으면 기록에만), 그 창이 없으면(소스 실행) 같은 제목(TITLE)의 QMessageBox.critical. GUI 스레드에서 부를 것.
"""

import sys
import traceback

from PyQt5.QtWidgets import QMessageBox

TITLE = "YesonCheck 오류"  # 앱의 예외 창(app._ErrorDialog)과 같은 제목


def show_error(prefix: str, text: str) -> None:
    """기록(stderr)에 "<prefix> <text>"를 남기고 text를 오류 창으로 (모듈 설명). prefix: 기록 줄의 머리 (예: "[기본 앱]")."""
    print(f"{prefix} {text}", file=sys.stderr, flush=True)
    dialog = getattr(sys.excepthook, "dialog", None)
    if dialog is not None:
        dialog.show_error(text)
    else:
        QMessageBox.critical(None, TITLE, text)


def show_unexpected(prefix: str, context: str) -> None:
    """예외 처리 중에(except 블록 안): context와 지금 처리 중인 예외의 트레이스백을 기록·오류 창으로 (show_error)."""
    show_error(prefix, f"{context}\n\n{traceback.format_exc()}")
