import json
import os
import signal
import subprocess
import sys

import pytest

from tests.conftest import ROOT

SMOKE_TIMEOUT_S = 900
SIGNAL_NAMES = {s.value: s.name for s in signal.Signals}


def run_capturing(cmd, env, timeout):
    """cmd를 실행 → (종료 코드, stdout, stderr, 시간 초과했는지).

    시간이 지나면 SIGABRT를 보냄: PYTHONFAULTHANDLER=1이면 멈춘 곳(모든 스레드의 파이썬 스택)을 stderr에 남기고 끝남.
    """
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGABRT)
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return proc.returncode, out, err, True


def tail(text, count):
    lines = text.replace("\r", "\n").splitlines()  # 내려받기 진행 표시(\r)도 줄로
    return "\n".join(lines[-count:])


def describe_run(returncode, out, err, timed_out, timeout):
    """실패 메시지: 종료 코드(음수면 신호 이름)와 출력 끝부분. faulthandler가 남긴 스택이 있으면 그 앞부터 끝까지."""
    how = f"종료 코드 {returncode}"
    if returncode < 0:
        how += f" (신호 {SIGNAL_NAMES.get(-returncode, '알 수 없는 신호')})"
    if timed_out:
        how = f"{timeout}초 안에 끝나지 않아 SIGABRT로 멈춤 — {how}"
    fatal = err.rfind("Fatal Python error")
    err_tail = tail(err[:fatal], 15) + "\n" + err[fatal:] if fatal >= 0 else tail(err, 60)
    return f"{how}\n----- stdout 끝 -----\n{tail(out, 40)}\n----- stderr 끝 -----\n{err_tail}"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows는 CI가 빌드된 exe로 실행 (ci/run_smoke_test.ps1)")
def test_smoke_from_source(tmp_path):
    share = tmp_path / "share"
    workdir = tmp_path / "work"
    subprocess.run([sys.executable, os.path.join(ROOT, "ci", "make_test_data.py"),
                    "--share-root", str(share), "--mac-root", str(share), "--workdir", str(workdir)], check=True)
    # PYTHONFAULTHANDLER: 앱이 네이티브 코드에서 죽으면(SIGSEGV 등) 그때의 파이썬 스택을 stderr에 남김
    env = dict(os.environ, YESONCHECK_CONFIG_DIR=str(share / ".yesoncheck"), QT_QPA_PLATFORM="offscreen",
               PYTHONFAULTHANDLER="1")
    returncode, out, err, timed_out = run_capturing(
        [sys.executable, "-m", "yesoncheck.app", "--smoke-test", str(workdir)], env, SMOKE_TIMEOUT_S)
    sys.stdout.write(out)  # 예전처럼 실패하면 pytest가 앱 출력 전체를 보여 줌
    sys.stderr.write(err)
    result_path = workdir / "smoke_result.json"
    assert not timed_out and result_path.exists(), (
        "앱이 smoke_result.json을 남기지 않고 끝남 — " + describe_run(returncode, out, err, timed_out, SMOKE_TIMEOUT_S))
    report = json.loads(result_path.read_text(encoding="utf-8"))
    failed = [c for c in report["checks"] if not c["ok"]]
    assert returncode == 0 and not failed and not report["dialogs"], (
        f"종료 코드 {returncode}\n" + json.dumps(report, ensure_ascii=False, indent=2))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 신호 (Windows에는 SIGABRT를 보낼 수 없음) — 소스 실행 시험도 Mac만")
@pytest.mark.parametrize("code, timeout, expected", [
    ("import faulthandler; faulthandler._sigsegv()", 60, ["종료 코드 -11 (신호 SIGSEGV)", "Fatal Python error: Segmentation fault"]),
    ("import time; print('멈춤 흉내', flush=True); time.sleep(60)", 2,
     ["2초 안에 끝나지 않아 SIGABRT로 멈춤 — 종료 코드 -6 (신호 SIGABRT)", "Fatal Python error: Aborted", "멈춤 흉내"]),
])
def test_failed_run_shows_signal_and_python_stack(code, timeout, expected):
    """소스 실행 시험이 결과 없이 끝나면 실패 메시지에 종료 코드·신호와 faulthandler의 파이썬 스택이 보임 (CI 진단용)."""
    env = dict(os.environ, PYTHONFAULTHANDLER="1")
    returncode, out, err, timed_out = run_capturing([sys.executable, "-c", code], env, timeout)
    message = describe_run(returncode, out, err, timed_out, timeout)
    assert all(text in message for text in expected), message
    assert 'File "<string>", line 1' in message, message


def test_wait_released_workers_waits_and_reports_leftovers(qapp):
    """실행 시험이 끝날 때(finish) 창을 닫으며 놓은 작업(업데이트 확인 등)이 끝나기를 기다림 — 시간 안에 안 끝나면 실패
    항목으로 남김 (실행 중인 QThread가 남은 채 파이썬이 끝나면 프로세스가 죽음)."""
    import threading

    from PyQt5.QtCore import QThread

    from yesoncheck.player_base import release_worker, wait_for_released_workers
    from yesoncheck.smoke_test import wait_released_workers

    class Waiting(QThread):
        def __init__(self, gate):
            super().__init__()
            self.gate = gate

        def run(self):
            self.gate.wait(10)

    soon = threading.Event()
    finishing = Waiting(soon)
    finishing.start()
    release_worker(finishing, "업데이트 확인")
    threading.Timer(0.2, soon.set).start()
    report = {"checks": []}
    assert wait_released_workers(report, 5) == [] and finishing.isFinished()
    assert report["checks"] == []

    gate = threading.Event()
    stuck = Waiting(gate)
    stuck.start()
    release_worker(stuck, "시험 작업")
    try:
        assert wait_released_workers(report, 0.1) == ["시험 작업"]
        [item] = report["checks"]
        assert item["name"] == "창을 닫은 뒤 남은 작업" and not item["ok"] and "시험 작업" in item["detail"]
    finally:
        gate.set()
    assert wait_for_released_workers(5) == []


def test_manifest_long_path_aware_needs_true():
    from yesoncheck.smoke_test import manifest_long_path_aware

    ns = b'xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings"'
    assert manifest_long_path_aware(b"<windowsSettings><longPathAware " + ns + b">true</longPathAware></windowsSettings>")
    assert manifest_long_path_aware(b"<ws2:longPathAware " + ns + b">\r\n  true\r\n</ws2:longPathAware>")
    assert not manifest_long_path_aware(b"<longPathAware " + ns + b">false</longPathAware>")
    assert not manifest_long_path_aware(b"... longPathAware ...")


def test_ocr_model_files(tmp_path):
    from yesoncheck.smoke_test import ocr_model_files

    with pytest.raises(AssertionError, match="OCR 모델 폴더가 없습니다"):
        ocr_model_files(str(tmp_path))
    (tmp_path / "whl" / "det" / "en").mkdir(parents=True)
    with pytest.raises(AssertionError, match="OCR 모델 폴더가 비어 있습니다"):
        ocr_model_files(str(tmp_path))
    (tmp_path / "whl" / "det" / "en" / "inference.pdmodel").write_bytes(b"x")
    assert ocr_model_files(str(tmp_path)) == [os.path.join("whl", "det", "en", "inference.pdmodel")]


def test_app_version_check(monkeypatch):
    """실행 시험의 '앱 버전': 빌드된 앱이 읽은 버전(build_info.json)이 기대 버전이고 창 제목에 보이는지."""
    from yesoncheck import build_info
    from yesoncheck.smoke_test import app_version

    with pytest.raises(AssertionError, match="소스 실행"):
        app_version("1.1.0", "Yeson Checker")
    monkeypatch.setattr(build_info, "current",
                        lambda: build_info.BuildInfo("1.1.0+0f4d3d7", "0f4d3d7" + "0" * 33, "2026-10-20T10:00:00+09:00", "windows"))
    assert app_version("1.1.0+0f4d3d7", "Yeson Checker 1.1.0+0f4d3d7")["version"] == "1.1.0+0f4d3d7"
    with pytest.raises(AssertionError, match="기대 1.1.0"):
        app_version("1.1.0", "Yeson Checker 1.1.0+0f4d3d7")
    with pytest.raises(AssertionError, match="창 제목"):
        app_version("1.1.0+0f4d3d7", "Yeson Checker")


@pytest.mark.parametrize("extra", [["--auto-connect", "--expect-version", "1.1.0"], ["--expect-version", ""]])
def test_make_test_data_rejects_unused_expect_version(tmp_path, extra):
    """기대 버전은 기본 시나리오만 확인 → 자동 연결 시험이나 빈 값이면 조용히 무시하지 않고 멈춤."""
    result = subprocess.run([sys.executable, os.path.join(ROOT, "ci", "make_test_data.py"), "--share-root", str(tmp_path),
                             "--mac-root", str(tmp_path), "--workdir", str(tmp_path / "work"), *extra],
                            capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert result.returncode == 2 and "--expect-version" in result.stderr, result.stderr
    assert not (tmp_path / "work").exists()
