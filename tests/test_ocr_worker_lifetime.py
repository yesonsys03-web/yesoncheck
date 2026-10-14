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
    assert player_base.wait_for_released_workers() == []  # 끝날 때까지 기다림 (시간 제한 없음)
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


# ---------------------------------------------------------------------------
# 앱 종료: 창을 닫은 뒤 붙잡아 둔 작업을 정해진 시간(app.EXIT_WAIT_S, 실제 30초)까지만 기다리고,
# 그래도 안 끝나면 로그를 남기고 os._exit(0)로 끝냄 (창 없이 프로세스가 오래 남지 않게, 실행 중인
# QThread가 파이썬 종료 정리 중에 파괴돼 0xC0000409로 죽지 않게)
# ---------------------------------------------------------------------------

EXIT_WAIT_S = 1  # 시험용 (실제 30초)

_LAUNCH_SCRIPT = r"""
import sys
import time

sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QTimer

from yesoncheck import app as app_module, workers

app_module.EXIT_WAIT_S = float(sys.argv[2])


class StubbornWorker(workers.TransNetV2Worker):
    # stop()을 무시하고 45초 동안 도는 가짜 워커 (멈출 수 없는 TensorFlow 추론 흉내)
    def __init__(self):
        super().__init__("unused.mp4")

    def run(self):
        time.sleep(45)


class Player(app_module.VideoPlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        QTimer.singleShot(500, self._start_and_close)

    def _start_and_close(self):
        self.ocr_worker = StubbornWorker()
        self.ocr_worker.start()
        self.JOB_CLOSE_WAIT_MS = 200  # 창 닫기의 기다림(실제 10초)도 줄임
        print(f"CLOSING {time.time():.3f}", flush=True)
        self.close()


app_module.VideoPlayer = Player
code = app_module.launch(["yesoncheck"])
print(f"LAUNCH RETURNED {code}", flush=True)  # 강제 종료면 여기까지 오지 않음
"""


def test_exit_does_not_wait_forever_for_stubborn_worker(tmp_path):
    import time

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               YESONCHECK_CONFIG_DIR=make_config(str(tmp_path), {}))
    result = subprocess.run([sys.executable, "-c", _LAUNCH_SCRIPT, ROOT, str(EXIT_WAIT_S)], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=40)
    ended = time.time()
    output = f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    closing = [line for line in result.stdout.splitlines() if line.startswith("CLOSING ")]
    assert len(closing) == 1, output
    # 창 닫기 기다림 0.2초 + 종료 기다림 1초 + 여유 (워커는 45초 동안 돌므로 기다렸다면 훨씬 늦음)
    assert ended - float(closing[0].split()[1]) < EXIT_WAIT_S + 10, output
    assert result.returncode == 0, output
    assert "[닫기] 작업 1개가 1초 안에 끝나지 않아 강제로 종료합니다: OCR 분석·컷 감지" in result.stdout, output
    assert "LAUNCH RETURNED" not in result.stdout, output
    assert "Destroyed while thread is still running" not in result.stderr, output


def test_finish_released_workers_returns_when_all_finished(monkeypatch):
    from yesoncheck import app as app_module

    waited = []
    monkeypatch.setattr(app_module, "wait_for_released_workers", lambda timeout_s: waited.append(timeout_s) or [])
    monkeypatch.setattr(app_module.os, "_exit", lambda code: pytest.fail(f"강제 종료하면 안 됨 ({code})"))
    app_module.finish_released_workers(30)
    assert waited == [30]


def test_finish_released_workers_forces_exit_with_log(monkeypatch, capsys):
    from yesoncheck import app as app_module

    class Exited(Exception):
        pass

    def fake_exit(code):
        raise Exited(code)

    monkeypatch.setattr(app_module, "wait_for_released_workers", lambda timeout_s: ["OCR 분석·컷 감지", "영상 병합"])
    monkeypatch.setattr(app_module.os, "_exit", fake_exit)
    with pytest.raises(Exited) as info:
        app_module.finish_released_workers(30)
    assert info.value.args == (0,)
    assert "[닫기] 작업 2개가 30초 안에 끝나지 않아 강제로 종료합니다: OCR 분석·컷 감지, 영상 병합" in capsys.readouterr().out
