"""놓아 준 QThread 워커를 끝날 때까지 붙잡아 두는 모듈 (release_worker 등). 기존 경로 `yesoncheck.player_base`에서도 불러올 수 있음."""

import time

from PyQt5.QtCore import QTimer

from yesoncheck import timing_log


# 실행 중에 놓아 준 QThread 워커 (끝날 때까지 참조를 붙잡아 둠). 실행 중인 QThread의 마지막 참조가 사라지면
# GC가 실행 중인 스레드를 파괴해 프로세스가 죽음 ("QThread: Destroyed while thread is still running",
# Windows 0xC0000409). 애니매틱2(TensorFlow 추론)는 중간에 멈출 수 없어 영상을 바꾸거나 창을 닫은 뒤에도 돌 수 있음
_RELEASED_WORKERS = {}  # 워커 → 이름(로그용)
_released_sweep_timer = None
RELEASED_SWEEP_INTERVAL_MS = 200
# 창을 닫은 뒤 끝나지 않은 작업(예: TensorFlow 추론 중인 애니매틱2)을 기다리는 최대 시간 (초) — app.launch가 이벤트 루프가
# 끝난 뒤 wait_for_released_workers로 (넘으면 로그를 남기고 프로세스를 강제로 끝냄 — app.finish_released_workers).
# 다른 창의 업데이트가 닫히는 창을 기다리는 한도(player_update.CLOSE_OTHERS_TIMEOUT_S)도 이 값으로 셈
EXIT_WAIT_S = 30


def _sweep_released_workers():
    """붙잡아 둔 워커 중 끝난 것을 놓음 (메인 스레드 타이머)."""
    for worker in [w for w in _RELEASED_WORKERS if not w.isRunning()]:
        del _RELEASED_WORKERS[worker]
        worker.deleteLater()
        print(f"[작업] 붙잡아 둔 작업이 끝나 놓음 (남은 작업 {len(_RELEASED_WORKERS)}개)")
    if not _RELEASED_WORKERS and _released_sweep_timer is not None:
        _released_sweep_timer.stop()


def release_worker(worker, label, block_signals=True):
    """더 쓰지 않는 QThread 워커를 놓음: 이미 끝났으면 바로 deleteLater, 아직 실행 중이면 끝날 때까지
    _RELEASED_WORKERS에 붙잡아 두고 메인 스레드 타이머가 끝난 것을 놓음 (finished 신호는 blockSignals로 막히므로 쓰지 않음).
    block_signals: 놓은 뒤의 진행·완료·오류 신호가 창의 새 상태(새 영상·새 분석)를 건드리지 않게 막음."""
    global _released_sweep_timer
    if block_signals:
        worker.blockSignals(True)
    if not worker.isRunning():
        worker.deleteLater()
        return
    _RELEASED_WORKERS[worker] = label
    print(f"[작업] {label}: 아직 실행 중 — 끝날 때까지 붙잡아 둠 (멈추라고 알렸지만 중간에 멈출 수 없는 작업일 수 있음)")
    if _released_sweep_timer is None:
        _released_sweep_timer = QTimer()
        _released_sweep_timer.setInterval(RELEASED_SWEEP_INTERVAL_MS)
        _released_sweep_timer.timeout.connect(_sweep_released_workers)
    _released_sweep_timer.start()


def wait_for_released_workers(timeout_s=None):
    """붙잡아 둔 워커가 끝날 때까지 기다림 (timeout_s: 전체 최대 초, None이면 끝날 때까지).
    끝난 워커는 놓고, 시간 안에 끝나지 않은 워커의 이름 목록을 돌려줌 (그 워커들은 계속 붙잡아 둠).
    app.launch가 이벤트 루프가 끝난 뒤 부름 (파이썬이 끝나며 모듈을 정리할 때 실행 중인 QThread가 파괴되지 않게)."""
    running = [(worker, label) for worker, label in _RELEASED_WORKERS.items() if worker.isRunning()]
    if running:
        started = time.perf_counter()
        limit = "끝날 때까지" if timeout_s is None else f"최대 {timeout_s:g}초"
        names = ", ".join(label for _worker, label in running)
        print(f"[닫기] 끝나지 않은 작업 {len(running)}개를 {limit} 기다리는 중…: {names}", flush=True)
        deadline = None if timeout_s is None else started + timeout_s
        for worker, _label in running:
            if deadline is None:
                worker.wait()
            else:
                worker.wait(max(0, int((deadline - time.perf_counter()) * 1000)))
        print(f"[닫기] 기다림 끝 ({timing_log.since(started)})", flush=True)
    still_running = []
    for worker, label in list(_RELEASED_WORKERS.items()):
        if worker.isRunning():
            still_running.append(label)
        else:
            del _RELEASED_WORKERS[worker]
    if not _RELEASED_WORKERS and _released_sweep_timer is not None:
        _released_sweep_timer.stop()
    return still_running
