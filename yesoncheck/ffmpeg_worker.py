"""영상 병합 백그라운드 워커 (FFmpegWorker). 기존 경로 `yesoncheck.workers`에서도 불러올 수 있음."""

import os
import traceback
from threading import Lock

from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck import external_tools


class FFmpegWorker(QThread):
    """영상 병합을 백그라운드에서. merge_function(worker)는 ffmpeg를 띄우면 worker.register_process(proc)로 알린다
    (stop()이 그 ffmpeg를 끝낼 수 있게). partial_output: 멈췄을 때 지울 미완성 출력 파일."""

    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, merge_function, partial_output=None):
        super().__init__()
        self.merge_function = merge_function
        self.partial_output = partial_output
        self._stopped = False
        self._process = None
        self._process_lock = Lock()

    def register_process(self, process):
        with self._process_lock:
            self._process = process
            stopped = self._stopped
        if stopped:  # stop()이 ffmpeg 시작 전에 불린 경우
            process.kill()

    def stop(self):
        """실행 중인 ffmpeg를 끝냄 (창을 닫을 때). Windows에서는 남은 ffmpeg가 보이지 않은 채 출력 파일을 잡고 있음."""
        with self._process_lock:
            self._stopped = True
            process = self._process
        if process is not None and process.poll() is None:
            process.kill()

    def run(self):
        try:
            self.merge_function(self)
        except Exception as e:
            if not self._stopped:
                # 병합이 만든 설명(RuntimeError)·ffmpeg가 없음(ToolNotFoundError)은 메시지 그대로,
                # 예상 못 한 오류는 무엇인지 + 스택 트레이스 (창의 자세한 글에)
                expected = isinstance(e, (RuntimeError, external_tools.ToolNotFoundError))
                self.error.emit(str(e) if expected else f"{e!r}\n\n{traceback.format_exc()}")
                return
            print(f"병합을 멈췄습니다 (창 닫기): {e}")
            if self.partial_output and os.path.exists(self.partial_output):
                try:
                    os.remove(self.partial_output)
                except OSError as exc:
                    print(f"멈춘 병합의 미완성 파일을 지우지 못했습니다: {self.partial_output}\n{exc}")
            return
        self.finished.emit()
