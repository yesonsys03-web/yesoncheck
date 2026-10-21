"""yesoncheck/error_window.py 시험: 예상된 실패·예상 못 한 오류의 기록과 오류 창 (default_app·file_associations·mac_app_events가
함께 씀).

- 빌드 앱(sys.excepthook.dialog = app._ErrorDialog)이면 앱의 예외 창 — 기록 파일 경로가 붙고 한 번에 하나만. 없으면(소스 실행)
  같은 제목의 QMessageBox.critical. 창은 dialogs 픽스처가 기록.
- 트레이스백이 길어도 무엇이 실패했는지(앞의 글)는 그대로, 트레이스백만 끝 부분 (기록에는 전부).
"""

import sys

from yesoncheck import app as app_module
from yesoncheck import error_window

LONG = "긴 오류 " * 1000  # 트레이스백을 DETAILS_LIMIT보다 길게


def _raise_long():
    raise RuntimeError(f"{LONG}끝")


def test_show_unexpected_keeps_context_in_apps_error_window(qapp, dialogs, monkeypatch, tmp_path, capsys):
    log_path = str(tmp_path / "yesoncheck_20261022_123.log")
    monkeypatch.setattr(sys, "excepthook", app_module.make_excepthook(log_path))
    try:
        _raise_long()
    except RuntimeError:
        error_window.show_unexpected("[시험]", "무엇을 하다 실패함")
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and title == error_window.TITLE == "YesonCheck 오류"
    assert text.startswith("무엇을 하다 실패함\n\n")  # 긴 트레이스백에 잘리지 않음
    assert text.endswith(f"끝\n\n\n로그: {log_path}")  # 트레이스백의 끝(예외 글)과 기록 파일 경로
    assert len(text) < error_window.DETAILS_LIMIT + 200
    err = capsys.readouterr().err
    assert "[시험] 무엇을 하다 실패함" in err and LONG in err and "Traceback" in err  # 기록에는 전부


def test_show_unexpected_without_apps_error_window(qapp, dialogs, monkeypatch, capsys):
    """소스 실행(예외 창 없음): 같은 제목의 QMessageBox.critical, 무엇이 실패했는지는 그대로."""
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    try:
        _raise_long()
    except RuntimeError:
        error_window.show_unexpected("[시험]", "무엇을 하다 실패함")
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", error_window.TITLE)
    assert text.startswith("무엇을 하다 실패함\n\n") and text.endswith("끝\n")


def test_show_error_shows_text_as_is_with_log_path(qapp, dialogs, monkeypatch, tmp_path, capsys):
    log_path = str(tmp_path / "yesoncheck_20261022_123.log")
    monkeypatch.setattr(sys, "excepthook", app_module.make_excepthook(log_path))
    error_window.show_error("[시험]", "예상된 실패: 무엇이 왜")
    assert dialogs.messages == [("critical", error_window.TITLE, f"예상된 실패: 무엇이 왜\n\n로그: {log_path}")]
    assert "[시험] 예상된 실패: 무엇이 왜" in capsys.readouterr().err


def test_uncaught_exception_window_keeps_traceback_end(qapp, dialogs, monkeypatch, tmp_path, capsys):
    """잡히지 않은 예외(excepthook): 트레이스백만이므로 끝 DETAILS_LIMIT 글자 (예외 글이 끝에 있음) + 기록 파일 경로."""
    log_path = str(tmp_path / "yesoncheck_20261022_123.log")
    hook = app_module.make_excepthook(log_path)
    try:
        _raise_long()
    except RuntimeError:
        hook(*sys.exc_info())
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", error_window.TITLE)
    body, log_line = text.rsplit("\n\n", 1)
    assert log_line == f"로그: {log_path}" and len(body) == error_window.DETAILS_LIMIT and body.endswith("끝\n")
