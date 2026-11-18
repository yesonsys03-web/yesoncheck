"""시험 도우미 process_checks.gone — '그 프로세스가 끝났다'를 보는 한 곳.

psutil.pid_exists 한 번은 Windows에서 끝난 프로세스에도 참일 수 있다: 프로세스가 끝나(WaitForSingleObject가 돌아옴) 거둔 뒤에도 PID가
잠깐 시스템 목록에 남는다 (psutil 7.2.2 _pswindows.Process.wait의 주석 — 그래서 psutil 자신도 pid_exists를 다시 폴링함). 2026-11-18 배포
CI에서 test_opening_next_file_pauses_old_builder_while_opening이 이 순간에 걸려 실패했다. gone은 정해진 시간까지 사라지기를 기다리고,
정말 살아 있는 프로세스와 (POSIX) 거두지 않은 좀비는 그 시간이 지나도 거짓 — 시험이 잡으려던 것은 그대로 잡는다.
"""

import subprocess
import sys
import time

import psutil
import pytest

from tests import process_checks
from tests.process_checks import gone

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_running_process_is_not_gone():
    process = subprocess.Popen(SLEEPER)
    try:
        started = time.monotonic()
        assert gone(process.pid, timeout_s=0.3) is False
        assert time.monotonic() - started >= 0.3  # 기다린 뒤에 거짓 (바로 거짓이 아님)
        assert process.poll() is None  # 기다리는 동안 건드리지 않음
    finally:
        process.kill()
        process.wait()


def test_killed_and_reaped_process_is_gone():
    process = subprocess.Popen(SLEEPER)
    process.kill()
    process.wait()
    assert gone(process.pid) is True


def test_pid_still_listed_for_a_moment_after_the_end_is_gone(monkeypatch):
    """끝났지만 PID가 잠깐 목록에 남는 경우(Windows): 처음 몇 번은 pid_exists가 참이어도 사라지면 참."""
    answers = [True, True, True, False]
    asked = []

    def fake_pid_exists(pid):
        asked.append(pid)
        return answers.pop(0)

    monkeypatch.setattr(process_checks.psutil, "pid_exists", fake_pid_exists)
    assert gone(4321, timeout_s=5) is True
    assert asked == [4321] * 4


def test_pid_listed_past_the_deadline_is_not_gone(monkeypatch):
    monkeypatch.setattr(process_checks.psutil, "pid_exists", lambda pid: True)
    started = time.monotonic()
    assert gone(4321, timeout_s=0.2) is False
    assert 0.2 <= time.monotonic() - started < 2


@pytest.mark.skipif(sys.platform == "win32", reason="좀비(죽었지만 거두지 않은 자식)는 POSIX의 것")
def test_unreaped_zombie_is_not_gone():
    """kill했지만 거두지 않은 자식은 POSIX에서 좀비로 남음 — '거둠' 단언이 이를 잡아야 함."""
    process = subprocess.Popen(SLEEPER)
    process.kill()
    try:
        deadline = time.monotonic() + 5
        while psutil.Process(process.pid).status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < deadline, "kill한 자식이 좀비가 되지 않았습니다"
            time.sleep(0.01)
        assert gone(process.pid, timeout_s=0.3) is False
    finally:
        process.wait()
    assert gone(process.pid) is True
