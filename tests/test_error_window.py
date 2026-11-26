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


def test_show_notice_keeps_the_body_short_and_puts_details_behind_the_button(qapp, dialogs, monkeypatch):
    """알림 창(소스 실행): 경고 아이콘, 본문은 쉬운 말 + 'Show Details…' 안내, 기술 정보는 자세히에 전부(자르지 않음 — 스크롤되는 칸).
    왜: 오류 창은 트레이스백을 본문에 넣어 창이 화면만큼 길어짐 — 사용자가 할 일이 있는 알림(열어 둔 영상이 다시 렌더링됨)은 그 글이 먼저 보여야 함."""
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)

    error_window.show_notice("무슨 일인지 쉬운 말", f"기술 정보 {LONG}끝")

    [box] = dialogs.boxes
    assert (box.kind, box.title) == ("warning", error_window.TITLE)
    assert box.text == f"무슨 일인지 쉬운 말\n\n{error_window.DETAILS_HINT}"
    assert box.details == f"기술 정보 {LONG}끝"
    [details_button] = [label for label in box.buttons if "Details" in label]
    assert f"'{details_button}'" in error_window.DETAILS_HINT  # 안내의 단추 이름은 Qt가 붙인 글자 그대로 (Show Details...)


def test_show_notice_clips_huge_details_keeping_both_ends(qapp, dialogs, monkeypatch):
    """자세히 칸의 글이 아주 길면(ffmpeg stderr는 길이 한도 없이 모임) 머리(머리말·원인)와 끝(stderr의 끝)을 남기고 가운데를 줄임 —
    창에 수 MB를 넣지 않음. 전체는 기록에 (부른 쪽이 남김)."""
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    limit, head = error_window.NOTICE_DETAILS_LIMIT, error_window.NOTICE_DETAILS_HEAD
    details = "머리말\n원인: 무엇\n" + "x" * (limit * 3) + "\nstderr의 끝"

    error_window.show_notice("쉬운 말", details)
    error_window.show_notice("쉬운 말", "y" * limit)  # 한도까지는 그대로

    clipped, whole = (box.details for box in dialogs.boxes)
    assert whole == "y" * limit
    assert clipped.startswith(details[:head]) and clipped.endswith(details[-(limit - head):])
    omitted = len(details) - limit
    assert f"(가운데 {omitted:,}자 생략 — 전체는 기록에)" in clipped and len(clipped) < limit + 100


def test_show_notice_in_built_app_adds_log_path(qapp, dialogs, monkeypatch, tmp_path):
    """빌드 앱: 앱의 예외 창 객체를 거쳐 — 기록 파일 경로가 본문에 붙음."""
    log_path = str(tmp_path / "yesoncheck_20261126_123.log")
    monkeypatch.setattr(sys, "excepthook", app_module.make_excepthook(log_path))

    error_window.show_notice("무슨 일인지 쉬운 말", "기술 정보")

    [box] = dialogs.boxes
    assert box.kind == "warning" and box.details == "기술 정보"
    assert box.text == f"무슨 일인지 쉬운 말\n\n로그: {log_path}\n\n{error_window.DETAILS_HINT}"
    assert sys.excepthook.dialog.is_open is False  # 닫힌 뒤에는 다음 창이 다시 뜸
    error_window.show_notice("다음 알림", "기술 정보 2")
    assert [shown.details for shown in dialogs.boxes] == ["기술 정보", "기술 정보 2"]


def test_show_notice_while_a_window_is_open_goes_to_log_only(qapp, dialogs, monkeypatch, tmp_path, capsys):
    """빌드 앱: 창이 이미 떠 있으면 쌓지 않고 기록에만 (오류 창과 같은 규칙 — 한 번에 하나)."""
    hook = app_module.make_excepthook(str(tmp_path / "yesoncheck.log"))
    monkeypatch.setattr(sys, "excepthook", hook)
    hook.dialog.is_open = True

    error_window.show_notice("무슨 일인지 쉬운 말\n둘째 줄", "기술 정보")

    assert dialogs.boxes == [] and dialogs.messages == []
    assert "오류 창이 이미 열려 있어 이 오류는 로그에만 남깁니다: 무슨 일인지 쉬운 말" in capsys.readouterr().err
    assert hook.dialog.is_open is True


def test_report_from_handler_logs_now_and_shows_window_from_qt_loop(qapp, monkeypatch, capsys):
    """가상 함수(eventFilter·done 등)의 except 블록용: 트레이스백은 바로 기록, 오류 창은 Qt 루프에서(이벤트 처리 안의 모달 금지)."""
    shown = []
    monkeypatch.setattr(error_window, "show_window", shown.append)
    try:
        raise ValueError("폭발")
    except ValueError:
        error_window.report_from_handler("[시험]", "무엇을 하다 실패함")
    err = capsys.readouterr().err
    assert "[시험] 무엇을 하다 실패함" in err and "ValueError: 폭발" in err
    assert shown == []
    qapp.processEvents()
    assert len(shown) == 1 and shown[0].startswith("무엇을 하다 실패함\n\n") and "ValueError: 폭발" in shown[0]


def test_report_from_handler_failure_goes_to_original_stderr(qapp, monkeypatch):
    """알리다 또 실패하면(오류 창이 터짐) 원래 stderr에 남기고 Qt 루프 밖으로 내보내지 않음."""
    import io

    def broken(text):
        raise RuntimeError("창 실패")

    monkeypatch.setattr(error_window, "show_window", broken)
    stream = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", stream)
    try:
        raise ValueError("폭발")
    except ValueError:
        error_window.report_from_handler("[시험]", "무엇을 하다 실패함")
    qapp.processEvents()
    assert "오류를 알리지 못했습니다" in stream.getvalue() and "RuntimeError: 창 실패" in stream.getvalue()
