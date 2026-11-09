"""Qt(C++)의 메시지(qWarning 등)를 기록으로 (2026-11-09 — Windows 11에서 소리가 나오지 않는다는 보고를 조사하다 찾음).

빌드 앱은 setup_app_logging이 파이썬의 stdout·stderr만 기록 파일로 보냄 — Qt가 C++에서 쓰는 메시지는 C 런타임의 stderr로 가서 콘솔 없는
Windows 앱에서는 어디에도 남지 않았음. 소리 백엔드(DirectShow·Windows Media Foundation)가 '파일을 열지 못함'·'코덱 없음'을 알리는 길이
이것이라, 소리가 안 나와도 기록이 비어 있었음. install()이 Qt 메시지 처리기를 걸어 한 줄씩 sys.stderr(빌드 앱은 기록 파일)에 씀.
처리기는 Qt 콜백이라 예외를 밖으로 내지 않음 — 쓰다 실패하면 원래 stderr(sys.__stderr__)에 한 번, 거기도 못 쓰면 버림.
"""

import sys
import traceback

from PyQt5.QtCore import QtMsgType, qInstallMessageHandler

LEVELS = {
    QtMsgType.QtDebugMsg: "디버그",
    QtMsgType.QtInfoMsg: "정보",
    QtMsgType.QtWarningMsg: "경고",
    QtMsgType.QtCriticalMsg: "심각",
    QtMsgType.QtFatalMsg: "치명",
}

_handler = None  # 건 처리기 — 파이썬 쪽 참조를 붙잡아 둠


def qt_message_line(kind, message):
    """Qt 메시지 한 줄 — `[Qt 경고] <메시지>`."""
    return f"[Qt {LEVELS.get(kind, int(kind))}] {message}"


def _handle(kind, _context, message):
    line = qt_message_line(kind, message)
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:  # Qt 콜백 밖으로 내보내지 않음 — 원래 stderr에 한 번
        stream = sys.__stderr__
        if stream is None:
            return
        try:
            stream.write(f"{line}\n(기록에 쓰지 못함)\n{traceback.format_exc()}\n")
            stream.flush()
        except Exception:  # 남길 곳이 없음
            pass


def install():
    """Qt 메시지 처리기를 검 — 그 뒤의 Qt 메시지는 sys.stderr(빌드 앱은 기록 파일)로."""
    global _handler
    _handler = _handle
    qInstallMessageHandler(_handler)
