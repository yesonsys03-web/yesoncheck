"""OCR·컷 감지 워커(QThread)의 수명: 실행 중인 워커의 마지막 참조를 놓으면 GC가 실행 중인 스레드를 파괴해
프로세스가 죽는다 ("QThread: Destroyed while thread is still running", Windows 0xC0000409 — 예전 썸네일 스레드와 같은 종류).
애니매틱2(TransNetV2)는 TensorFlow 추론 중에는 멈출 수 없고 10초 넘게 걸릴 수 있어 위험이 커졌다.

- 영상을 바꿀 때(reset_ocr_state): 실행 중인 워커를 멈추라고 하고, 끝날 때까지 참조를 붙잡아 둔다
- 창을 닫을 때(closeEvent): 다른 작업처럼 멈추고 정해진 시간까지 기다리고, 그래도 안 끝나면 끝날 때까지 붙잡아 둔다

죽는 것(abort) 자체를 확인해야 하므로 새 파이썬 프로세스에서 실행한다 (pytest 프로세스가 죽지 않게).
"""

import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.test_work_paths_ui import make_config

_SCRIPT = r"""
import gc
import sys
import time

sys.path.insert(0, sys.argv[1])
scenario = sys.argv[2]
from PyQt5.QtWidgets import QApplication

app = QApplication([])
from yesoncheck import player_base, workers
from yesoncheck.main_window import VideoPlayer


class SlowWorker(workers.TransNetV2Worker):
    # TensorFlow 추론처럼 stop()을 무시하고 seconds 동안 도는 가짜 워커
    def __init__(self, seconds):
        super().__init__("unused.mp4")
        self.seconds = seconds

    def run(self):
        time.sleep(self.seconds)
        self.completed.emit({"segments": [], "fps": 24.0, "total_frames": 0, "cancelled": True})


def pump_until(condition, timeout):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout}초 안에 조건이 이루어지지 않았습니다")
        app.processEvents()
        time.sleep(0.01)


player = VideoPlayer()
if scenario == "reset":
    worker = SlowWorker(1.0)
    player.ocr_worker = worker
    worker.start()
    del worker
    player.reset_ocr_state()  # 영상이 바뀜
    assert player.ocr_worker is None
    gc.collect()
    assert len(player_base._RELEASED_WORKERS) == 1, player_base._RELEASED_WORKERS
    # 끝나면(finished) 붙잡아 둔 목록에서 빠짐
    pump_until(lambda: not player_base._RELEASED_WORKERS, 10)
    player.close()
    print("RESET OK")
elif scenario == "close_waits":
    worker = SlowWorker(0.5)
    player.ocr_worker = worker
    worker.start()
    player.close()  # 멈추라고 하고 기다림 (0.5초면 끝남)
    assert worker.isFinished(), "창을 닫은 뒤에도 워커가 실행 중입니다 (기다리지 않음)"
    assert not player_base._RELEASED_WORKERS
    print("CLOSE WAITED OK")
elif scenario == "close_timeout":
    player.JOB_CLOSE_WAIT_MS = 200  # 실제는 10초 — 그보다 오래 걸리는 추론을 흉내 냄
    worker = SlowWorker(1.5)
    player.ocr_worker = worker
    worker.start()
    del worker
    player.close()  # 0.2초 안에 안 끝남 → 끝날 때까지 붙잡아 둠
    assert len(player_base._RELEASED_WORKERS) == 1, player_base._RELEASED_WORKERS
    del player
    gc.collect()  # 창이 사라져도 워커는 남아 있어야 함
    player_base.wait_for_released_workers()  # app.launch가 이벤트 루프가 끝난 뒤 하는 것
    assert not player_base._RELEASED_WORKERS
    print("CLOSE TIMEOUT OK")
"""


@pytest.mark.parametrize("scenario, marker", [
    ("reset", "RESET OK"),
    ("close_waits", "CLOSE WAITED OK"),
    ("close_timeout", "CLOSE TIMEOUT OK"),
])
def test_running_ocr_worker_is_not_destroyed(tmp_path, scenario, marker):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               YESONCHECK_CONFIG_DIR=make_config(str(tmp_path), {}))
    result = subprocess.run([sys.executable, "-c", _SCRIPT, ROOT, scenario], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=180)
    output = f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Destroyed while thread is still running" not in result.stderr, output
    assert result.returncode == 0, output
    assert marker in result.stdout, output
