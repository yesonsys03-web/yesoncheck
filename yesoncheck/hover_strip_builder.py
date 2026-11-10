# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 띠를 만드는 워커 (HoverStripBuilder — QThread 하나와 그 ffmpeg 프로세스 하나). 화면(위젯) 없음.

번들 ffmpeg가 파일 전체를 띠 크기(hover_strip.StripPlan)의 rgb24 원시 프레임으로 줄여 stdout으로 내보내고, 이 워커가 한 장씩 받아 띠 저장소
(hover_strip.HoverStrip)에 넣는다. 재생 캡처(cap_a)는 건드리지 않는다 — 따로 띄운 프로세스가 파일을 따로 연다. 띄우는 때·멈추는 때는 부르는
쪽(플레이어의 쉬는 때 판정)이 정하고, 워커는 띄워진 뒤 paused 표지만 본다.

왜 stdout 파이프로 충분한가 (스펙 §5.3): 전송은 stdout 파이프로 충분하다 — 장당 173KB(320×180×3; 어떤 비율이든 320×320 상자 안이라 최대
307KB)이고 쉴 때만 읽는다. 파이프 소스(movie_pipe_source)가 소켓으로 옮긴 까닭은 4K 한 장 25MB가 64KB씩 수백 번의 read로 들어오며 재생 중인
GUI 스레드와 GIL을 다투던 것(공급 기아)인데, 여기는 장당 read가 몇 번뿐이고 재생 중에는 읽지 않으므로 해당 없다 — 소켓·전송 계층 없이
Popen(stdout=PIPE) 하나다.

왜 멈춤이 psutil 프로세스 정지인가 (스펙 §5.3): 파이프를 읽지 않는 것만으로는 ffmpeg가 바로 멈추지 않는다 — 프레임 스레드들이 이미 디코드
중인 장(스레드 수만큼 — 4K 4444면 8코어로 수백 ms)을 마저 디코드해 재생의 첫 틱들과 겹친다. 그래서 paused가 참이 되면
psutil.Process(pid).suspend()(POSIX SIGSTOP·Windows NtSuspendProcess), 거짓이 되면 resume() — CPU가 즉시 0이 된다. 정지된 프로세스에도 kill은
그대로 먹는다(SIGKILL·TerminateProcess) — stop()은 정지 여부와 상관없이 kill한다. 정지·재개가 실패하면(psutil.NoSuchProcess·AccessDenied)
기록 한 줄을 남기고 읽기만 멈추는(또는 잇는) 방식으로 둔다 — 조용히 넘기지 않는다.
띠 ffmpeg의 스레드는 2개로 제한한다(FFMPEG_THREADS, -threads 2): 4K 재생을 띠 워커를 띄운 지 0.5초 안에 시작하면 Play+0.5초에 69~78ms
끊김이 한 번 났다(끔 최대간격 43~58ms, 정지는 그때 이미 걸려 있음). 기본 프레임 스레딩이 이 Mac에서 16스레드라 Play 직전에 4K 장 16개를
한꺼번에 디코드하는 버스트가 원인으로 의심되어, 스레드를 줄여 버스트를 누그러뜨린다(스펙 §5.3).

수명: 생성자는 띄우지 않는다 — start()가 run에서 Popen(stdout=PIPE, stderr=PIPE)하고, 띄운 직후 잠금 안에서 paused면 바로 정지한다. stderr는
데몬 스레드가 끝까지 모은다(안 비우면 파이프가 차서 ffmpeg가 멈춤 — movie_pipe_source._PipeSession과 같은 모양). 끝은 셋 중 하나다.
- done(채운 장수, 띄운 때부터 초 — 멈춘 시간 포함): 종료 코드 0이고 stderr가 비었을 때(-v error라 무엇이든 적혀 있으면 오류). 계획보다 적게
  와도(잘린 파일·VFR) done이고 남은 샘플은 빈 채로, 많이 오면 남는 장은 읽어 버리고 done(기록에 '넘침 n장' 한 줄).
- failed(글): 띄우지 못함·한 장 도중 끊김·종료 코드 ≠ 0·stderr에 글·읽기 오류. 글은 파일·명령·종료 코드·stderr 전문(·트레이스백). 이미 넣은
  장은 그대로 둔다(그 구간은 보임). 한 장 도중 끊김(몇 바이트만 오고 EOF)은 브리프의 '짧게 끝나면 EOF'보다 보수적으로 failed로 본다 — 스펙
  §5.3의 실패 목록('한 장 도중 EOF')을 따름. 0바이트에서의 EOF만 정상 끝이다.
- stop(): 표지를 둔 뒤의 끊김(kill의 종료 코드·끊긴 읽기)은 신호도 기록도 내지 않는다 — done·failed는 잠금 안에서 표지를 보고 내므로
  stop()이 표지를 둔 뒤에는 나가지 않는다. 단 트레이스백이 있는 문제(예상 못 한 예외 — 정리 단계·put의 버그 등)는 stop 뒤라도 신호 없이
  기록(stderr)에 LOG_PREFIX 머리 한 줄과 트레이스백을 남긴다(조용히 사라지지 않게). 끝 신호 두 개를 직접 연결(Qt.DirectConnection)로 받아
  그 안에서 paused·stop을 부르면 안 된다(잠금을 다시 잡음) — 플레이어는 GUI 스레드의 대기열 연결로 받는다. progress는 잠금 밖에서 낸다(묶음
  알림일 뿐 — stop 직후 하나가 더 올 수 있음).
샘플 i(ffmpeg가 낸 i번째 장 — select면 원본 i×step)는 한 번만 put한다 (HoverStrip.put은 행을 다 쓴 뒤 표시하므로, 같은 행을 다시 쓰면 GUI가
덮어쓰는 중인 행을 읽을 수 있음).

잠금(_lock)이 지키는 것: _paused·_stopped·_process·_suspendable. _suspendable은 프로세스를 정지·재개해도 되는 동안(띄운 직후부터 읽기가
끝날 때까지)만 참이다 — 읽기가 끝난 뒤(EOF·실패·stop)에는 정지·재개하지 않아, 끝나 가는 프로세스를 정지해 거두기(wait)가 막히거나 거둔 뒤
다른 프로세스가 물려받은 PID를 건드리지 않는다. 정상 EOF인데 멈춤 표지가 서 있으면(마지막 장을 받는 사이 정지됨) 거두기 전에 재개한다.
"""

import subprocess
import sys
import threading
import time
import traceback

import psutil
from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck.external_tools import decode_output, ffmpeg_path, subprocess_kwargs
from yesoncheck.hover_strip import LOG_PREFIX, HoverStrip, StripPlan

POLL_S = 0.05  # 멈춘 동안 표지를 다시 보는 간격 (초)
BATCH_S = 0.05  # progress 묶음 간격 (초) — 또는 BATCH_FRAMES장마다, 먼저 오는 쪽 (GUI 신호 폭주 방지)
BATCH_FRAMES = 10
STOP_WAIT_MS = 2000  # stop()이 kill한 프로세스를 거두고, 스레드 끝을 기다리는 최대 시간 (각각)
_STDERR_CHUNK = 65536
# 띠 ffmpeg의 디코더 프레임 스레드 수 (-threads, 입력 옵션). 기본값(None)이면 ffmpeg 기본 — 이 Mac에서 16스레드라 4K 재생을 띠 워커를
# 띄운 직후(~0.5초 안)에 시작하면 Play 직전 디코드 버스트로 Play+0.5초에 69~78ms 끊김이 한 번 났다(끔 43~58ms). 2로 줄여 완화(스펙 §5.3).
FFMPEG_THREADS: int | None = 2


def build_command(ffmpeg: str, path: str, plan: StripPlan) -> list[str]:
    """띠 하나를 만드는 ffmpeg 명령 (인자 리스트 그대로 — 셸 없음). -map 0:V:0(대문자 — attached_pic 제외)·-fps_mode passthrough(복제
    금지)는 파이프 소스와 같은 이유. 간격이 1이면 scale만, 아니면 select로 step장마다 하나 — 쉼표 앞의 역슬래시는 select 식의 쉼표가 필터
    구분자로 읽히지 않게 하는 필터 파서용 (셸 따옴표 아님)."""
    scale = f"scale={plan.width}:{plan.height}"
    vf = scale if plan.step == 1 else f"select=not(mod(n\\,{plan.step})),{scale}"
    threads = [] if FFMPEG_THREADS is None else ["-threads", str(FFMPEG_THREADS)]  # 호출 때 읽음 — 입력 옵션이라 -i 앞
    return [ffmpeg, "-nostdin", "-v", "error", *threads, "-i", path, "-map", "0:V:0", "-fps_mode", "passthrough", "-vf", vf,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def _read_full(stream, view: memoryview) -> int:
    """view를 다 채울 때까지 stream에서 읽음 → 읽은 바이트 수 (EOF면 len(view)보다 적음)."""
    filled = 0
    while filled < len(view):
        count = stream.readinto(view[filled:])
        if not count:
            break
        filled += count
    return filled


def _drain(stream, chunks: list) -> None:
    """stderr를 EOF까지 chunks에 모으고 닫음 (데몬 스레드 — 안 비우면 파이프가 차서 ffmpeg가 멈춤)."""
    try:
        for chunk in iter(lambda: stream.read1(_STDERR_CHUNK), b""):
            chunks.append(chunk)
    finally:
        stream.close()


class HoverStripBuilder(QThread):
    """ffmpeg 하나로 띠 저장소를 채우는 워커. 생성·start·paused·stop은 GUI 스레드, run은 워커 스레드.

    path: 영상 파일, strip: 채울 저장소(계획은 strip.plan), ffmpeg: 실행 파일(None이면 external_tools.ffmpeg_path() — 없으면 생성자가
    ToolNotFoundError). command·pid(띄운 뒤)는 기록·시험용."""

    progress = pyqtSignal(int)  # 채운 장수 (BATCH_S마다 또는 BATCH_FRAMES장마다)
    done = pyqtSignal(int, float)  # 채운 장수, 띄운 때부터 초
    failed = pyqtSignal(str)  # 파일·명령·종료 코드·stderr 전문·트레이스백

    def __init__(self, path: str, strip: HoverStrip, ffmpeg: str | None = None, parent=None):
        super().__init__(parent)
        self.path = path
        self.strip = strip
        self.command = build_command(ffmpeg if ffmpeg is not None else ffmpeg_path(), path, strip.plan)
        self.pid: int | None = None
        self._lock = threading.Lock()
        self._paused = False
        self._stopped = False
        self._process: subprocess.Popen | None = None
        self._suspendable = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        """멈춤 표지. 바뀔 때만 — 프로세스가 돌고 있으면 바로 정지·재개 (플레이어가 50ms마다 같은 값을 넣어도 psutil은 부르지 않음)."""
        with self._lock:
            if value == self._paused:
                return
            self._paused = value
            if self._suspendable:
                self._signal_process(value)

    def stop(self) -> None:
        """일부러 끝냄 (GUI 스레드, 여러 번 불러도 됨): 표지 → kill(정지돼 있어도 먹힘) → 거두기 → 스레드 끝 대기.

        거두기와 스레드 끝은 각각 STOP_WAIT_MS까지만 기다린다 — 넘으면 기록을 남기고 돌아간다(GUI를 막지 않음; 워커 스레드가 프로세스를
        끝까지 기다려 거두고, 부른 쪽은 worker_lifecycle.release_worker로 붙잡아 둔다). stdout은 여기서 닫지 않고 워커 스레드가 닫는다(브리프의
        'stdout 닫기'와 다름): 프로세스가 죽으면 읽기는 EOF로 바로 끝나므로 닫을 까닭이 없고, 여기서 닫으면 ① 읽기 스레드가 readinto 안에
        있을 때 닫기가 그 읽기를 기다리고 ② 표지 검사와 readinto 사이에 닫히면 정상 중단이 ValueError 트레이스백이 되어 '예상 못 한 오류'
        기록으로 섞인다. 표지를 둔 뒤로는 done·failed를 내지 않는다(그 전에 낸 신호가 GUI의 대기열에 남아 있을 수는 있음 — 부른 쪽 몫)."""
        with self._lock:
            self._stopped = True
            self._suspendable = False
            process = self._process
        if process is not None:
            process.kill()  # 이미 거둔 프로세스면 아무것도 안 함
            try:
                process.wait(STOP_WAIT_MS / 1000)
            except subprocess.TimeoutExpired:
                print(f"{LOG_PREFIX} kill한 ffmpeg가 {STOP_WAIT_MS}ms 안에 끝나지 않았습니다 (pid {process.pid}) — 워커 스레드가 끝까지 "
                      f"기다려 거둡니다: {self.path}", file=sys.stderr, flush=True)
                return  # 안 죽는 프로세스면 읽기 스레드도 막혀 있음 — 스레드를 더 기다리지 않음
        if not self.wait(STOP_WAIT_MS):
            print(f"{LOG_PREFIX} 띠 워커 스레드가 {STOP_WAIT_MS}ms 안에 끝나지 않았습니다: {self.path}", file=sys.stderr, flush=True)

    def run(self) -> None:
        """워커 스레드 본문. 예외를 밖으로 내지 않는다(QThread.run에서 새면 PyQt5가 프로세스를 끝냄) — 모두 failed의 글로."""
        started = time.monotonic()
        try:
            self._build(started)
        except Exception:  # 정리 단계의 예상 못 한 오류 (_build가 프로세스는 이미 거둠) — 삼키지 않고 failed로 (stop 뒤면 기록으로)
            self._report("띠 워커가 예외로 끝났습니다.", None, "", 0, started, trace=traceback.format_exc())

    def _build(self, started: float) -> None:
        try:
            process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       **subprocess_kwargs())
        except OSError:
            self._report("ffmpeg를 띄우지 못했습니다.", None, "", 0, started, trace=traceback.format_exc())
            return
        stderr_chunks = []
        stderr_reader = threading.Thread(target=_drain, args=(process.stderr, stderr_chunks), name="hover-strip-stderr",
                                         daemon=True)
        received, problem, trace = 0, None, None
        try:
            stderr_reader.start()
            self._attach(process)
            received, problem = self._read_frames(process.stdout)
        except Exception:  # 읽기·넣기 오류 (예상 못 한 예외 — stop 뒤라도 기록에 남음)
            problem, trace = "ffmpeg 출력을 읽다 오류가 났습니다.", traceback.format_exc()
        try:
            self._end_reading(clean=problem is None)
        except Exception:  # 재개 중 예상 못 한 오류 — 정지된 채 거두기를 기다리지 않게 아래에서 kill
            problem, trace = "ffmpeg를 재개하지 못했습니다.", traceback.format_exc()
        finally:
            if problem is not None:
                process.kill()  # 실패면 남은 출력을 기다리지 않음 (정지돼 있어도 먹힘). stop()이면 stop()·_attach가 이미 kill
            process.stdout.close()
            process.wait()
            stderr_reader.join()
        self._report(problem, process.returncode, decode_output(b"".join(stderr_chunks)), received, started, trace=trace)

    def _attach(self, process: subprocess.Popen) -> None:
        """띄운 직후 (잠금 안): 프로세스를 붙임. 이미 stop()이 불렸으면 바로 kill, 멈춤 표지가 서 있으면 바로 정지."""
        with self._lock:
            self._process = process
            self.pid = process.pid
            if self._stopped:
                process.kill()
                return
            self._suspendable = True
            if self._paused:
                self._signal_process(True)

    def _read_frames(self, stdout) -> tuple[int, str | None]:
        """EOF까지 한 장(plan.frame_bytes)씩 읽어 샘플 0, 1, 2…에 넣음 → (ffmpeg가 낸 장수, 문제 글 또는 None). 계획 장수를 넘는 장은
        읽어 버림. 멈춤 표지가 서 있는 동안은 읽지 않음(POLL_S마다 다시 봄), stop()이면 바로 끝."""
        plan = self.strip.plan
        view = memoryview(bytearray(plan.frame_bytes))
        received = 0
        reported, reported_at = 0, time.monotonic()
        while not self._stopped:
            if self._paused:
                time.sleep(POLL_S)
                continue
            got = _read_full(stdout, view)
            if got < plan.frame_bytes:
                if got:
                    return received, f"한 장 도중에 출력이 끊겼습니다 ({got}/{plan.frame_bytes}바이트 — {received}장을 받은 뒤)"
                return received, None
            if received < plan.count:
                self.strip.put(received, view)
            received += 1
            filled = min(received, plan.count)
            now = time.monotonic()
            if filled > reported and (filled - reported >= BATCH_FRAMES or now - reported_at >= BATCH_S):
                self.progress.emit(filled)
                reported, reported_at = filled, now
        return received, None

    def _end_reading(self, clean: bool) -> None:
        """읽기 끝 (잠금 안): 이제부터 정지·재개하지 않음. 정상 EOF인데 멈춤 표지가 서 있으면 재개 — 마지막 장을 받는 사이 정지된 ffmpeg가
        정지된 채 남아 거두기(wait)가 막히지 않게."""
        with self._lock:
            resume = clean and self._suspendable and self._paused
            self._suspendable = False
            if resume:
                self._signal_process(False)

    def _signal_process(self, pause: bool) -> None:
        """(잠금 안, _suspendable일 때만) 프로세스를 정지(pause) 또는 재개. psutil이 못 하면 기록 한 줄 — 표지는 그대로라 읽기만 멈추거나 이어짐."""
        pid = self._process.pid
        try:
            process = psutil.Process(pid)
            if pause:
                process.suspend()
            else:
                process.resume()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            action, fallback = ("정지", "읽기만 멈춤") if pause else ("재개", "읽기를 이어 감")
            print(f"{LOG_PREFIX} 정지/재개 실패 — {action}, pid {pid}: {type(exc).__name__}: {exc} ({fallback}): {self.path}",
                  file=sys.stderr, flush=True)

    def _report(self, problem: str | None, returncode: int | None, stderr: str, received: int, started: float,
                trace: str | None = None) -> None:
        """끝 신호 하나 (잠금 안). 문제 글이 없고 종료 코드 0·stderr 빔이면 done, 아니면 failed. trace: 예상 못 한 예외의 트레이스백.
        stop()이 표지를 둔 뒤면 신호를 내지 않는다 — 정상 중단(kill로 끊긴 읽기·종료 코드)은 조용히, trace가 있는 문제는 기록(stderr)에 남김."""
        plan = self.strip.plan
        if trace is not None:
            problem = f"{problem}\n{trace.rstrip()}"
        with self._lock:
            if self._stopped:
                if trace is not None:
                    print(f"{LOG_PREFIX} 멈춘 띠 워커에서 예상 못 한 오류가 났습니다 (stop 뒤라 신호 없음) — {self.path}\n{problem}",
                          file=sys.stderr, flush=True)
                return
            if problem is None and returncode == 0 and not stderr:
                if received > plan.count:
                    print(f"{LOG_PREFIX} 계획보다 많은 장을 받아 버림: 넘침 {received - plan.count}장 (계획 {plan.count}장) — {self.path}",
                          flush=True)
                self.done.emit(self.strip.filled_count, time.monotonic() - started)
                return
            if problem is None:
                problem = (f"ffmpeg가 비정상 종료했습니다 (종료 코드 {returncode})" if returncode != 0
                           else "ffmpeg가 stderr에 오류를 냈습니다 (종료 코드 0)")
            code = "없음" if returncode is None else str(returncode)
            self.failed.emit(f"{problem}\n파일: {self.path}\n명령: {' '.join(self.command)}\n종료 코드: {code}\n"
                             f"stderr:\n{stderr.rstrip() or '(없음)'}")
