"""setup_app_logging: 빌드된 앱(frozen)의 기록 파일(이름에 pid)·30일 지난 기록 정리·예외 창 (Windows·Mac 모두)."""

import datetime
import os
import sys
import time

import pytest

from yesoncheck import app

DAY = 24 * 60 * 60


@pytest.fixture
def frozen_env(monkeypatch, tmp_path, qapp):
    """빌드된 앱처럼 보이게 하고(sys.frozen), 사용자 폴더(HOME·LOCALAPPDATA)를 tmp로. stdout·stderr·excepthook은 시험 뒤 원래대로,
    setup_app_logging이 연 기록 파일은 닫음."""
    home = tmp_path / "home"
    local = tmp_path / "local"
    home.mkdir()
    local.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows의 expanduser
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for name in ("stdout", "stderr", "excepthook"):
        monkeypatch.setattr(sys, name, getattr(sys, name))
    original = sys.stdout
    yield home, local
    if sys.stdout is not original:
        sys.stdout.close()


def _today():
    return f"{datetime.date.today():%Y%m%d}"


def _raise(message):
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


def _read(path):
    sys.stdout.flush()
    sys.stderr.flush()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _aged(path, days):
    path.write_text("옛 기록\n", encoding="utf-8")
    old = time.time() - days * DAY
    os.utime(path, (old, old))
    return path


def test_mac_frozen_logging_installs_excepthook_and_pid_file(frozen_env, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    home, _ = frozen_env
    log_path = app.setup_app_logging("darwin")

    assert log_path == str(home / "Library" / "Logs" / "YesonCheck" / f"yesoncheck_{_today()}_{os.getpid()}.log")
    assert os.path.isfile(log_path)
    # stdout·stderr가 기록 파일로 (Mac 앱은 콘솔이 없음)
    print("표준 출력 줄")
    print("표준 오류 줄", file=sys.stderr)
    text = _read(log_path)
    assert "YesonCheck 시작" in text and f"pid {os.getpid()}" in text
    assert "표준 출력 줄" in text and "표준 오류 줄" in text
    # 슬롯에서 새어 나온 예외: 앱이 죽지 않게 excepthook이 기록 + 오류 창
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, body, *a, **k: shown.append(body) or QMessageBox.Ok)
    assert getattr(sys.excepthook, "dialog", None) is not None  # make_excepthook의 것
    sys.excepthook(*_raise("Mac 슬롯 오류"))
    text = _read(log_path)
    assert "Traceback" in text and "Mac 슬롯 오류" in text
    assert len(shown) == 1 and "Mac 슬롯 오류" in shown[0] and log_path in shown[0]


def test_windows_log_name_has_pid(frozen_env, monkeypatch):
    _, local = frozen_env
    logs = local / "YesonCheck" / "logs"
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    first = app.setup_app_logging("win32")

    assert first == str(logs / f"yesoncheck_{_today()}_4242.log")
    assert os.path.isfile(first)
    assert "pid 4242" in _read(first)
    assert getattr(sys.excepthook, "dialog", None) is not None
    # 같은 날 켠 다른 창(다른 pid)은 다른 파일 — 기록이 섞이지 않음
    sys.stdout.close()
    monkeypatch.setattr(os, "getpid", lambda: 4243)
    second = app.setup_app_logging("win32")
    assert second == str(logs / f"yesoncheck_{_today()}_4243.log") and second != first
    assert os.path.isfile(first) and os.path.isfile(second)


def test_old_logs_removed_after_30_days(frozen_env):
    home, _ = frozen_env
    logs = home / "Library" / "Logs" / "YesonCheck"
    logs.mkdir(parents=True)
    old_a = _aged(logs / "yesoncheck_20200101_111.log", 31)
    old_b = _aged(logs / "yesoncheck_20200102.log", 400)  # pid 없던 옛 이름도 지움
    recent = _aged(logs / "yesoncheck_20260901_222.log", 29)
    update_log = _aged(logs / "update.log", 400)  # 업데이트 기록은 건드리지 않음
    other = _aged(logs / "other_20200101.log", 400)
    not_log = _aged(logs / "yesoncheck_20200101_333.txt", 400)
    (logs / "yesoncheck_dir.log").mkdir()  # 이름만 같은 폴더는 지우지 않음 (오류도 없이 건너뜀)

    log_path = app.setup_app_logging("darwin")

    assert not old_a.exists() and not old_b.exists()
    assert recent.exists() and update_log.exists() and other.exists() and not_log.exists()
    assert (logs / "yesoncheck_dir.log").is_dir()
    assert os.path.isfile(log_path)  # 방금 만든 이 창의 기록


def test_old_log_cleanup_failure_is_logged_and_startup_continues(frozen_env, monkeypatch):
    _, local = frozen_env
    logs = local / "YesonCheck" / "logs"
    logs.mkdir(parents=True)
    locked = _aged(logs / "yesoncheck_20200101_1.log", 40)  # Windows: 다른 창이 연 파일은 못 지움
    deletable = _aged(logs / "yesoncheck_20200102_2.log", 40)
    real_remove = os.remove

    def remove(path, *args, **kwargs):
        if os.fspath(path) == str(locked):
            raise PermissionError(13, "다른 프로세스가 사용 중", str(locked))
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", remove)

    log_path = app.setup_app_logging("win32")  # 예외 없이 끝남 (정리일 뿐, 시작을 막지 않음)

    assert log_path is not None and sys.excepthook.dialog is not None
    assert locked.exists() and not deletable.exists()  # 한 파일이 막혀도 나머지는 정리
    text = _read(log_path)
    assert str(locked) in text and "PermissionError" in text and "Traceback" in text  # 조용히 넘기지 않고 기록


def test_source_run_does_nothing(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    before = (sys.stdout, sys.stderr, sys.excepthook)

    for platform in ("darwin", "win32"):
        assert app.setup_app_logging(platform) is None

    assert (sys.stdout, sys.stderr, sys.excepthook) == before
    assert list(tmp_path.iterdir()) == []  # 폴더도 만들지 않음


def test_frozen_on_unsupported_platform_does_nothing(frozen_env):
    home, local = frozen_env
    before = (sys.stdout, sys.stderr, sys.excepthook)

    assert app.setup_app_logging("linux") is None

    assert (sys.stdout, sys.stderr, sys.excepthook) == before
    assert list(home.iterdir()) == [] and list(local.iterdir()) == []
