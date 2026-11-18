"""시험 도우미: 띄운 프로세스가 끝났는지 (시험이 아님 — test_process_checks가 이 도우미를 시험함).

kill한 ffmpeg·ffprobe가 '거둬졌다'를 psutil.pid_exists 한 번으로 보지 않는다: Windows에서는 프로세스가 끝나 거둔 뒤에도(Popen.wait —
WaitForSingleObject가 돌아옴) PID가 잠깐 시스템 목록에 남을 수 있어 그 순간에는 참이다(psutil 7.2.2 _pswindows.Process.wait의 주석 —
psutil 자신도 그래서 pid_exists를 다시 폴링함). 2026-11-18 배포 CI의 Windows 작업이 이 순간에 걸려 실패했다.
"""

import time

import psutil

GONE_WAIT_S = 5.0  # 끝난 프로세스의 PID가 목록에서 사라지기를 기다리는 최대 시간
POLL_S = 0.01


def gone(pid: int, timeout_s: float = GONE_WAIT_S) -> bool:
    """pid의 프로세스가 끝나 시스템 목록에서도 사라졌으면 True — timeout_s까지 기다린다.

    정말 살아 있는 프로세스, POSIX에서 거두지 않은 좀비(pid_exists가 계속 참)는 timeout_s가 지나도 False라 '끝나고 거둠' 단언이 잡으려던
    것은 그대로 잡는다. 기다리는 동안 프로세스를 건드리지 않는다(거두지 않음 — psutil.Process.wait는 POSIX에서 자식을 거둬 버려 쓰지 않음)."""
    deadline = time.monotonic() + timeout_s
    while psutil.pid_exists(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)
    return True
