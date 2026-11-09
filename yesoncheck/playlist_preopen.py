"""선택 재생 — 다음 파일 미리 열기 (2026-11-09, 사용자 요청: 4K에서 다음 파일로 넘어갈 때의 딜레이를 최소로).

왜: Windows 4K ProRes 선택 재생의 전환 평균 1.10초 중 1.04초가 open_file이고 그 대부분이 캡처 열기였음 (a652652 로그 9번 평균 — ffprobe 0.12 ·
ffmpeg 시작 0.01 · 첫 프레임 0.74). 지금 파일을 재생하는 동안 뒤 스레드가 다음 파일의 캡처를 열어 두면 넘어갈 때 그 몫을 기다리지 않음.
(첫 프레임을 줄이려던 ffmpeg 조각 스레드는 재생 중 끊김이 늘어 되돌림 — CLAUDE.md 2026-11-09.)

Preopen 하나 = 파일 하나의 미리 열기. 만들면 곧바로 뒤 스레드(데몬)가 파일의 크기·수정 시각을 적고 opener(path, cancelled)를 부름 → 캡처 또는
None(파이프로 여는 파일이 아님 — 또는 닫혀서 그만둠: opener는 cancelled()로 닫혔는지 보고 ffmpeg를 띄우기 전에 그만둘 수 있음). 부른 쪽(GUI 스레드)은 기다리지 않음. 넘어갈 때 take()로 받음 — 아직 여는 중이면 끝날 때까지 기다림(처음부터 다시
여는 것보다 짧음). 받을 것이 없으면 None이고 부른 쪽이 예전 방법으로 엶:
- 파일이 바뀜(크기·수정 시각 — 다시 렌더해 덮어씀)·지금 확인하지 못함 → 연 캡처를 놓고 기록 한 줄
- 파일 쪽 실패(OSError·PipeCaptureError)는 뒤 스레드가 그때 기록(트레이스백 전문)에 남김 → 예전 방법이 다시 열며 같은 오류 창을 냄
- 그 밖의 예외(ToolNotFoundError·코드 버그)는 삼키지 않고 take()가 그대로 다시 냄 — 미리 열지 않았을 때 open_file이 내던 것과 같은 길
cancel(reason): 받지 않을 미리 열기를 닫음 — 이미 열렸으면 바로 놓고, 아직 여는 중이면 뒤 스레드가 다 연 즉시 놓음 (기다리지 않음 — 창을
닫을 때처럼 끝나기를 볼 곳은 wait(timeout)). 닫힌 미리 열기의 그 밖의 예외는 낼 곳이 없어 기록(트레이스백)에만 남는다고 적음.
뒤 스레드의 기록 쓰기가 실패해도(꽉 찬 디스크·닫힌 스트림) 끝 표시는 늘 남김 — 그 글은 원래 stderr에 한 번(_log); 끝 표시가 없으면 넘어갈 때
take()가 영원히 기다림(코드 검토에서 재현).
take·cancel은 GUI 스레드(한 스레드)에서 부름. opener는 뒤 스레드에서 돌므로 Qt를 건드리지 않는 것이어야 함. Qt 없음.
"""

import os
import sys
import threading
import traceback

from yesoncheck.movie_pipe_source import PipeCaptureError

LOG_PREFIX = "[미리 열기]"
EXPECTED_ERRORS = (OSError, PipeCaptureError)  # 파일 쪽 실패 — 넘어갈 때 예전 방법이 같은 오류를 창으로 냄


def _log(text, with_traceback=False):
    """기록 한 줄(with_traceback이면 처리 중인 예외의 트레이스백도) — 쓰다 실패하면 원래 stderr(sys.__stderr__ — 기록 파일로 바꾸기 전)에 그 글과
    실패의 트레이스백(처리 중이던 예외가 이어 붙음)을 한 번. 거기도 못 쓰면 더 남길 곳이 없음(movie_pipe_source._last_resort와 같은 규칙 — 이 실패를
    올리면 뒤 스레드가 끝 표시를 남기지 못함)."""
    try:
        print(text, flush=True)
        if with_traceback:
            traceback.print_exc()
    except Exception:
        stream = sys.__stderr__
        if stream is None:
            return
        try:
            stream.write(f"{LOG_PREFIX} 기록에 쓰지 못했습니다 — {text}\n{traceback.format_exc()}\n")
            stream.flush()
        except Exception:  # 남길 곳이 없음 (위 docstring)
            pass


def _signature(path):
    """파일이 그대로인지 볼 값 — 크기와 수정 시각(ns). OSError는 그대로."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns


class Preopen:
    """파일 하나의 미리 열기 — 위 모듈 설명."""

    def __init__(self, path, opener):
        self.path = path
        self._name = os.path.basename(path)
        self._opener = opener
        self._lock = threading.Lock()  # _capture·_cancelled·_finished (뒤 스레드와 GUI 스레드)
        self._done = threading.Event()
        self._capture = None  # 연 캡처 — 받거나 닫을 때까지 이것이 주인
        self._signature = None  # 열기 전에 적은 크기·수정 시각
        self._error = None  # 그 밖의 예외 — take()가 다시 냄
        self._cancelled = None  # 닫은 사유 (None = 닫지 않음)
        self._finished = False  # 뒤 스레드가 결과를 넘김 — 닫기와 어느 쪽이 먼저인지 잠금 안에서 정함 (뒷정리를 한쪽만 하게)
        self._taken = False
        self._thread = threading.Thread(target=self._run, name=f"playlist-preopen {self._name}", daemon=True)
        self._thread.start()

    def _is_cancelled(self):
        """opener가 부름(뒤 스레드) — 닫혔으면 True: ffmpeg를 띄우기 전에 그만둘 수 있게."""
        with self._lock:
            return self._cancelled is not None

    def _run(self):
        capture = None
        try:
            self._signature = _signature(self.path)
            capture = self._opener(self.path, self._is_cancelled)
            if capture is None and not self._is_cancelled():
                _log(f"{LOG_PREFIX} 파이프로 여는 파일이 아님 — 넘어갈 때 예전 방법으로 엽니다: {self._name}")
        except EXPECTED_ERRORS:
            _log(f"{LOG_PREFIX} 열지 못함 — 넘어갈 때 예전 방법으로 다시 엽니다: {self._name}", with_traceback=True)
        except BaseException as exc:  # 뒤 스레드에서 사라지지 않게 담아 두고 take()가 다시 냄
            self._error = exc
            _log(f"{LOG_PREFIX} 예상하지 못한 오류 — 넘어갈 때 그대로 냅니다: {self._name}", with_traceback=True)
        finally:
            try:
                with self._lock:
                    reason = self._cancelled
                    if reason is None:
                        self._capture = capture
                    self._finished = True
                if reason is not None:  # 여는 동안 닫힘 — 다 연 즉시 놓음
                    if capture is not None:
                        capture.release()
                        _log(f"{LOG_PREFIX} 닫음 — {reason}: {self._name}")
                    if self._error is not None:
                        _log(self._dropped_error_line(reason))
            finally:
                self._done.set()  # 무슨 일이 있어도 — 없으면 take()가 영원히 기다림

    def _dropped_error_line(self, reason):
        return f"{LOG_PREFIX} 닫음 — {reason} (예상하지 못한 오류는 위 트레이스백으로만 남음): {self._name}"

    def wait(self, timeout):
        """다 열었는지(성공·실패 모두) 최대 timeout초 기다림 → 끝났으면 True (시험·도구용 — take는 스스로 기다림)."""
        return self._done.wait(timeout)

    def take(self):
        """넘어갈 때 연 캡처를 받음(이제 부른 쪽의 것) → 캡처 또는 None(예전 방법으로 열 것 — 모듈 설명). 아직 여는 중이면 기다림.
        그 밖의 예외는 다시 냄. 한 번만, 닫은 뒤에는 부를 수 없음 (RuntimeError)."""
        if self._taken:
            raise RuntimeError(f"이미 받은 미리 열기입니다: {self.path}")
        if self._cancelled is not None:
            raise RuntimeError(f"닫은 미리 열기는 받을 수 없습니다 ({self._cancelled}): {self.path}")
        self._done.wait()
        self._taken = True
        if self._error is not None:
            raise self._error
        with self._lock:
            capture, self._capture = self._capture, None
        if capture is None:
            return None
        try:
            now = _signature(self.path)
        except OSError as exc:
            capture.release()
            _log(f"{LOG_PREFIX} 버림 — 파일을 확인하지 못함 ({type(exc).__name__}: {exc}): {self._name}")
            return None
        if now != self._signature:
            capture.release()
            _log(f"{LOG_PREFIX} 버림 — 미리 연 뒤 파일이 바뀜 (크기·수정 시각): {self._name}")
            return None
        return capture

    def cancel(self, reason):
        """받지 않을 미리 열기를 닫음 — 연 캡처가 있으면 바로 놓고, 여는 중이면 뒤 스레드가 다 연 즉시 놓음. 받은 뒤·이미 닫은 뒤에는 아무것도 안 함."""
        with self._lock:
            if self._taken or self._cancelled is not None:
                return
            self._cancelled = reason
            capture, self._capture = self._capture, None
            finished = self._finished
        if capture is not None:
            capture.release()
            _log(f"{LOG_PREFIX} 닫음 — {reason}: {self._name}")
        if finished and self._error is not None:  # 다 끝난 뒤 닫힘 — 여는 중이었으면 뒤 스레드가 적음
            _log(self._dropped_error_line(reason))
