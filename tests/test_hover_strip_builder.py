"""hover_strip_builder — 실제 번들 ffmpeg로 띠를 만드는 워커 (스펙 §5.3·§5.7 ②).

번호 클립(prores_clips.make_numbered_clip — 320×180이라 띠 크기와 같아 frame_number로 번호를 그대로 읽음)으로 순서·간격, psutil 정지·재개,
stop(정지된 프로세스·읽기에서 막힌 스레드 포함), 실패 글, 계획보다 적거나 많은 장을 본다. 신호는 리스트에 connect하고 qapp.processEvents()로
받는다(워커 스레드의 신호는 GUI 스레드의 이벤트 루프가 전달). 모든 기다림에 한도가 있어 멈추면 실패로 끝나고, 만든 워커는 make_builder
픽스처가 끝에서(시험이 실패해도) stop한다 — ffmpeg 프로세스·스레드가 남지 않게.

320×180 200장은 이 Mac에서 첫 장부터 끝까지 약 30ms라 GUI 스레드가 progress를 받은 뒤 멈추면 이미 끝나 있다 — 도중 멈춤 시험은 progress를
직접 연결(Qt.DirectConnection)로 받아 워커 스레드 안에서 바로 paused를 세운다(끝나기 전에 멈춤이 걸림을 보장).

정지 확인: POSIX는 psutil status()가 STOPPED. Windows의 status()는 모든 스레드의 대기 사유가 Suspended일 때만 STOPPED라, 파이프가 차서
WriteFile에서 막힌 ffmpeg 스레드가 있으면 정지돼 있어도 running으로 보인다(CI run 42768144735 — 띄운 직후 정지는 모든 스레드가 Suspended라
맞게 보임). 그래서 도중 멈춤 시험은 확인 방법을 매개변수로 둘 다 둔다 — evidence="status"(psutil status — Windows에서는 틀린 확인이라
건너뜀)와 evidence="drain"(동작으로: 파이프를 비워 봐서(_drain_pipe) 한 장도 더 오지 않고, 비우는 도우미가 read1에서 막혀 살아 있음 — 정지된
ffmpeg는 어느 OS에서나 새 장을 주지 않으므로 모든 OS에서 돎).
"""

import socket
import sys
import threading
import time
import traceback

import psutil
import pytest
from PyQt5.QtCore import Qt

from tests.conftest import write_test_video
from tests.prores_clips import frame_number, make_numbered_clip, make_truncated
from yesoncheck import hover_strip, hover_strip_builder, movie_pipe_source
from yesoncheck.hover_strip import LOG_PREFIX, HoverStrip, StripPlan, plan_for
from yesoncheck.hover_strip_builder import STOP_WAIT_MS, HoverStripBuilder, build_command

WAIT_MS = 10_000  # 스레드 끝·신호를 기다리는 한도 — 넘으면 멈춘 것으로 보고 실패
WAIT_S = WAIT_MS / 1000


@pytest.fixture(scope="session")
def numbered_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hover_strip_builder") / "numbered_48.mov")
    make_numbered_clip(path, count=48)
    return path


@pytest.fixture(scope="session")
def truncated_clip(tmp_path_factory, numbered_clip):
    """번호 클립 48장을 faststart로 다시 담고 꼬리를 자른 파일 (prores_clips.make_truncated — 헤더는 48장, 데이터는 70%에서 끊김)."""
    path = str(tmp_path_factory.mktemp("hover_strip_builder") / "truncated_48.mov")
    make_truncated(numbered_clip, path)
    return path


@pytest.fixture(scope="session")
def numbered_clip_200(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hover_strip_builder") / "numbered_200.mov")
    make_numbered_clip(path, count=200)
    return path


@pytest.fixture
def make_builder():
    """워커를 만들고, 시험이 끝나면(실패해도) stop — 스레드가 끝나고 ffmpeg가 거둬졌는지 확인."""
    made = []

    def make(path, strip):
        worker = HoverStripBuilder(path, strip)
        made.append(worker)
        return worker

    yield make
    for worker in made:
        worker.stop()
        assert not worker.isRunning()
        assert worker.pid is None or not psutil.pid_exists(worker.pid)


class _Signals:
    """워커의 세 신호를 리스트로 받음 (GUI 스레드 — processEvents가 전달)."""

    def __init__(self, worker):
        self.progress, self.done, self.failed = [], [], []
        worker.progress.connect(lambda filled: self.progress.append(filled))
        worker.done.connect(lambda filled, seconds: self.done.append((filled, seconds)))
        worker.failed.connect(lambda text: self.failed.append(text))

    @property
    def done_counts(self):
        return [filled for filled, _seconds in self.done]


def _pump(qapp, seconds):
    """seconds 동안 이벤트를 돌림 (그동안 온 신호를 받음)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)


def _pump_until(qapp, condition, what):
    """condition()이 참이 될 때까지 이벤트를 돌림 — WAIT_S를 넘으면 실패."""
    deadline = time.monotonic() + WAIT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{WAIT_S:g}초 안에 오지 않음: {what}")
        qapp.processEvents()
        time.sleep(0.005)


def _finish(qapp, worker):
    """스레드 끝을 기다리고(한도 WAIT_MS) 남은 신호를 받음."""
    assert worker.wait(WAIT_MS), f"워커가 {WAIT_S:g}초 안에 끝나지 않음"
    qapp.processEvents()


def _numbers(strip, count):
    return [frame_number(strip.image(i)) for i in range(count)]


def _is_stopped(pid):
    """psutil이 보는 정지 상태. POSIX는 정확. Windows는 모든 스레드가 Suspended 대기일 때만 참 — 띄운 직후 정지에는 맞고, 파이프 쓰기에서
    막힌 스레드가 있는 도중 정지에는 거짓으로 나옴(그때는 _drain_pipe로 동작을 봄)."""
    return psutil.Process(pid).status() == psutil.STATUS_STOPPED


def _drain_pipe(stream, limit, seconds):
    """도우미 데몬 스레드가 stream(워커의 ffmpeg stdout)을 비워 가며 받은 바이트 수를 seconds 뒤에 봄 → (바이트 수, 스레드, 도우미의 예외 글).

    limit 바이트에 닿으면 그만 읽음(정지가 안 됐으면 ffmpeg가 계속 밀어 넣으므로 상한). read1에는 타임아웃이 없어 스레드가 막혀 있어도 시험은
    seconds 뒤 결과만 본다 — 뒤의 worker.stop()이 프로세스를 죽이면 read1이 EOF로 풀림. 워커가 stdout을 닫은 뒤의 ValueError는 끝으로 봄."""
    received = [0]
    errors = []

    def drain():
        try:
            while received[0] < limit:
                chunk = stream.read1(limit - received[0])
                if not chunk:
                    return
                received[0] += len(chunk)
        except ValueError:
            if not stream.closed:
                errors.append(traceback.format_exc())
        except Exception:
            errors.append(traceback.format_exc())

    thread = threading.Thread(target=drain, name="test-drain-pipe", daemon=True)
    thread.start()
    time.sleep(seconds)
    return received[0], thread, errors


def test_builds_every_frame_in_order(qapp, numbered_clip, make_builder):
    strip = HoverStrip(plan_for(48, 320, 180))
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    started = time.monotonic()
    worker.start()
    _finish(qapp, worker)
    assert got.failed == []
    assert got.done_counts == [48]
    assert 0 < got.done[0][1] <= time.monotonic() - started  # 띄운 때부터 초
    assert strip.filled_count == 48
    assert _numbers(strip, 48) == list(range(48))
    # progress: 채운 장수를 묶어서 (10장마다 또는 BATCH_S마다) — 늘기만 하고 계획 장수를 넘지 않음
    assert len(got.progress) >= 4
    assert got.progress == sorted(set(got.progress)) and got.progress[-1] <= 48


def test_sampled_plan_picks_every_step(qapp, numbered_clip, make_builder, monkeypatch):
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 12)  # 48/12 → 간격 4, 12장
    plan = plan_for(48, 320, 180)
    assert (plan.step, plan.count) == (4, 12)
    strip = HoverStrip(plan)
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [12]
    assert _numbers(strip, 12) == [plan.source_frame(i) for i in range(12)] == list(range(0, 48, 4))
    assert "select=not(mod(n\\,4)),scale=320:180" in worker.command


def test_command_shape():
    """4K 원본(Full HD보다 큼)의 명령 — 1코어로 묶은 지금 명령과 글자 그대로 (측정된 4K 설정이 바뀌지 않음, hover_strip.thread_limits)."""
    every = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=3840, source_height=2160)
    assert build_command("/opt/ffmpeg", "/clips/a b.mov", every) == [
        "/opt/ffmpeg", "-nostdin", "-v", "error", "-filter_threads", "1", "-threads", "1", "-i", "/clips/a b.mov", "-map", "0:V:0",
        "-fps_mode", "passthrough", "-vf", "scale=320:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    sampled = StripPlan(total=14_400, step=29, count=497, width=180, height=320, source_width=2160, source_height=3840)
    command = build_command("ffmpeg", "x.mov", sampled)
    vf = command[command.index("-vf") + 1]
    # 셸 없이 인자 하나 — 쉼표 앞의 역슬래시 하나는 필터 파서용(select 식 안의 쉼표가 필터 구분자가 아니게)
    assert vf == "select=not(mod(n\\,29)),scale=180:320" and vf.count("\\") == 1
    assert len(command) == len(build_command("ffmpeg", "x.mov", every))
    assert command[4:8] == ["-filter_threads", "1", "-threads", "1"]


@pytest.mark.parametrize("source", [(1920, 1080), (1280, 720), (1080, 1920), (320, 180)])
def test_full_hd_or_smaller_source_has_no_thread_options(source):
    """원본이 Full HD 이하면 스레드 옵션을 넣지 않음(ffmpeg 기본 — 이 Mac은 CPU 수만큼): 긴 720p 애니매틱의 띠가 1코어로 67초 걸리던 것
    (스펙 2026-11-11 §2). 나머지 명령은 4K의 것에서 그 네 토큰만 빠진 것."""
    plan = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=source[0], source_height=source[1])
    command = build_command("ffmpeg", "x.mov", plan)
    assert "-threads" not in command and "-filter_threads" not in command
    big = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=3840, source_height=2160)
    assert command == [arg for i, arg in enumerate(build_command("ffmpeg", "x.mov", big)) if i not in (4, 5, 6, 7)]


def test_threads_option_follows_constant(monkeypatch):
    """(Full HD보다 큰 원본) 디코더 스레드(-threads — 입력 옵션)·필터 스레드(-filter_threads — 전역 옵션)는 두 상수를 호출 때 읽음.
    None이면 그 옵션 자체가 없음."""
    every = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=3840, source_height=2160)
    monkeypatch.setattr(hover_strip_builder, "FFMPEG_THREADS", None)  # 끄면 ffmpeg 기본 — 옵션 자체가 없음
    monkeypatch.setattr(hover_strip_builder, "FFMPEG_FILTER_THREADS", None)
    command = build_command("ffmpeg", "x.mov", every)
    assert "-threads" not in command and "-filter_threads" not in command
    monkeypatch.setattr(hover_strip_builder, "FFMPEG_THREADS", 4)  # 입력 옵션이라 -i 바로 앞
    monkeypatch.setattr(hover_strip_builder, "FFMPEG_FILTER_THREADS", 3)  # 전역 옵션 — -i 앞
    command = build_command("ffmpeg", "x.mov", every)
    assert command.count("-threads") == 1 and command.count("-filter_threads") == 1
    assert command[command.index("-i") - 2:command.index("-i")] == ["-threads", "4"]
    assert command[command.index("-filter_threads") + 1] == "3" and command.index("-filter_threads") < command.index("-i")


@pytest.mark.parametrize("evidence", [
    pytest.param("status", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows의 psutil status()는 파이프 쓰기에서 막힌 스레드가 있으면 정지돼 있어도 running — drain 갈래가 동작으로 확인")),
    "drain",
])
def test_pause_suspends_process_and_resume_finishes(qapp, numbered_clip_200, make_builder, evidence):
    """도중 멈춤: 멈춘 뒤로는 한 장도 더 채우지 않고 프로세스가 정지. evidence는 정지를 확인하는 방법 (모듈 설명) — status는 psutil로 본 뒤
    재개해 끝까지 채우고(Windows는 건너뜀), drain은 파이프를 비워 동작으로 본 뒤 stop으로 끝냄(시험이 장을 먹었으므로)."""
    plan = plan_for(200, 320, 180)
    strip = HoverStrip(plan)
    worker = make_builder(numbered_clip_200, strip)
    got = _Signals(worker)
    paused_at = []

    def pause_on_first_progress(filled):  # 워커 스레드에서 (직접 연결) — 끝나기 전에 멈춤이 걸림을 보장
        if not paused_at:
            paused_at.append(filled)
            worker.paused = True

    worker.progress.connect(pause_on_first_progress, Qt.DirectConnection)
    worker.start()
    _pump_until(qapp, lambda: paused_at, "첫 progress")
    _pump(qapp, 0.3)
    n1 = strip.filled_count
    _pump(qapp, 0.5)
    assert strip.filled_count == n1 == paused_at[0] < 200  # 멈춘 뒤로는 한 장도 더 채우지 않음
    assert got.done == [] and got.failed == []
    if evidence == "drain":
        # 읽기만 멈춘 것이 아니라 프로세스가 정지 — 동작으로: 파이프를 0.5초 비워도 이미 버퍼에 있던 것(한 장 미만 — 이 Mac 98,304B)만 옴.
        # 정지가 안 됐으면 ffmpeg가 계속 밀어 넣어 상한(한 장)까지 옴. 시험이 장을 먹었으므로 끝까지 채우기는 보지 않고 stop으로 끝냄.
        pid = worker.pid
        drained, drainer, errors = _drain_pipe(worker._process.stdout, plan.frame_bytes, 0.5)
        assert drained < plan.frame_bytes, f"정지된 ffmpeg에서 {drained}바이트가 옴 (한 장 {plan.frame_bytes}바이트)"
        # 살아 있는 정지 프로세스면 도우미는 read1에서 막혀 있어야 함 — 끝났으면 EOF(프로세스가 죽음)·오류라 위 단언이 헛돈 것
        assert drainer.is_alive(), f"파이프를 비우는 도우미가 끝났습니다 (EOF 또는 오류 — {drained}바이트): {errors}"
        worker.stop()
        drainer.join(STOP_WAIT_MS / 1000)
        assert not worker.isRunning() and not psutil.pid_exists(pid)
        assert not drainer.is_alive() and errors == []
        _pump(qapp, 0.1)
        assert got.done == [] and got.failed == []
        return
    assert _is_stopped(worker.pid)  # 읽기만 멈춘 것이 아니라 프로세스가 정지 (CPU 0)
    worker.paused = False
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [200]
    assert _numbers(strip, 200) == list(range(200))


def test_paused_before_spawn_suspends_right_after_spawn(qapp, numbered_clip_200, make_builder):
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(numbered_clip_200, strip)
    got = _Signals(worker)
    worker.paused = True  # 띄우기 전 (프로세스 없음 — 표지만)
    worker.start()
    _pump_until(qapp, lambda: worker.pid is not None, "ffmpeg 띄움")
    _pump(qapp, 0.3)
    n1 = strip.filled_count
    _pump(qapp, 0.5)
    assert strip.filled_count == n1 == 0
    assert _is_stopped(worker.pid)
    assert got.done == [] and got.failed == []
    worker.paused = False
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [200]
    assert _numbers(strip, 200) == list(range(200))


def test_paused_same_value_takes_no_lock(make_builder):
    """paused setter는 값이 바뀔 때만 잠금을 잡고 psutil을 부름 — 같은 값이면 아무것도 하지 않음. 플레이어는 재생 중 틱(50ms)마다 True를
    넣으므로 그때마다 SIGSTOP을 다시 보내거나 워커 스레드(잠금 안에서 psutil·기록을 부를 수 있음)와 잠금을 다투지 않게. 띄우지 않은
    워커라 프로세스 없음 — 잠금 잡기만 셈."""
    worker = make_builder("not_started.mov", HoverStrip(plan_for(48, 320, 180)))
    acquired = []

    class _CountingLock:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            acquired.append(True)
            return self._inner.__enter__()

        def __exit__(self, *exc_info):
            return self._inner.__exit__(*exc_info)

    worker._lock = _CountingLock(worker._lock)
    worker.paused = False  # 처음 값과 같음
    assert acquired == []
    worker.paused = True
    worker.paused = True
    assert len(acquired) == 1 and worker.paused is True
    worker.paused = False
    worker.paused = False
    assert len(acquired) == 2 and worker.paused is False


def _logged(capsys):
    """기록(stdout·stderr) 중 이 기능의 머리로 시작하는 줄."""
    captured = capsys.readouterr()
    return [line for line in (captured.out + captured.err).splitlines() if line.startswith(LOG_PREFIX)]


def test_stop_kills_process_and_thread(qapp, numbered_clip, make_builder, capsys):
    worker = make_builder(numbered_clip, HoverStrip(plan_for(48, 320, 180)))
    got = _Signals(worker)
    worker.start()
    worker.stop()
    assert not worker.isRunning()
    assert worker.pid is not None and not psutil.pid_exists(worker.pid)  # kill 뒤 거둠 — 좀비 없음
    worker.stop()  # 두 번 불러도 됨
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == []
    assert _logged(capsys) == []  # 일부러 끊은 것(kill의 종료 코드·끊긴 읽기)은 조용히


def test_stop_while_paused_kills_process(qapp, numbered_clip_200, make_builder, capsys):
    worker = make_builder(numbered_clip_200, HoverStrip(plan_for(200, 320, 180)))
    got = _Signals(worker)
    worker.paused = True
    worker.start()
    _pump_until(qapp, lambda: worker.pid is not None and _is_stopped(worker.pid), "정지된 ffmpeg")
    pid = worker.pid
    worker.stop()  # 정지된 프로세스도 kill은 먹힘 (SIGKILL·TerminateProcess)
    assert worker.wait(STOP_WAIT_MS)
    assert not psutil.pid_exists(pid)
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == []
    assert _logged(capsys) == []


def test_stop_while_reading_kills_blocked_process(qapp, make_builder, capsys):
    """입력이 오지 않는 ffmpeg(받기만 하고 아무것도 보내지 않는 TCP 입력) — 읽기 스레드가 stdout에서 막힌 채(멈춤 아님) stop하면 kill로
    끊겨 스레드가 끝나고 프로세스는 거둬짐. GUI 스레드는 STOP_WAIT_MS를 넘게 막히지 않음."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        url = f"tcp://127.0.0.1:{server.getsockname()[1]}"
        strip = HoverStrip(plan_for(48, 320, 180))
        worker = make_builder(url, strip)
        got = _Signals(worker)
        worker.start()
        _pump_until(qapp, lambda: worker.pid is not None, "ffmpeg 띄움")
        _pump(qapp, 0.3)
        pid = worker.pid
        assert worker.isRunning() and psutil.pid_exists(pid) and not _is_stopped(pid)
        started = time.monotonic()
        worker.stop()
        assert time.monotonic() - started < STOP_WAIT_MS / 1000
        assert not worker.isRunning() and not psutil.pid_exists(pid)
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == [] and strip.filled_count == 0
    assert _logged(capsys) == []


def test_eof_while_paused_resumes_before_reaping(qapp, make_builder, monkeypatch):
    """읽기 스레드가 마지막 readinto에서 기다리는 사이 멈춤이 걸리고 그대로 EOF가 오면, 거두기 전에 재개한다(정지된 채 끝나 가는 프로세스를
    wait가 기다리지 않게). 같은 값을 거듭 넣으면 psutil은 한 번만 (플레이어는 50ms마다 넣음). psutil은 부름만 적는 대역 — 실제 ffmpeg는 그대로
    돌아, 입력(TCP)이 끊기면 오류로 끝남."""
    calls = []

    class _Records:
        def __init__(self, pid):
            self.pid = pid

        def suspend(self):
            calls.append(("suspend", self.pid))

        def resume(self):
            calls.append(("resume", self.pid))

    monkeypatch.setattr("yesoncheck.hover_strip_builder.psutil.Process", _Records)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        worker = make_builder(f"tcp://127.0.0.1:{server.getsockname()[1]}", HoverStrip(plan_for(48, 320, 180)))
        got = _Signals(worker)
        worker.start()
        _pump_until(qapp, lambda: worker.pid is not None, "ffmpeg 띄움")
        _pump(qapp, 0.3)  # 읽기 스레드는 첫 readinto에서 막힘 (멈춤 표지 전)
        worker.paused = True
        worker.paused = True
    # 받은 연결을 닫음 → ffmpeg가 입력 오류로 끝나고 stdout EOF — 멈춤 표지가 선 채로
    _finish(qapp, worker)
    assert calls == [("suspend", worker.pid), ("resume", worker.pid)]
    assert got.done == [] and len(got.failed) == 1  # 빈 입력은 ffmpeg 오류 (종료 코드 ≠ 0)


def test_unexpected_error_after_stop_is_logged_without_signal(qapp, numbered_clip, make_builder, monkeypatch, capsys):
    """stop() 뒤에 난 예상 못 한 예외(여기서는 put의 버그 흉내)는 신호는 내지 않되 기록(stderr)에 머리 한 줄과 트레이스백을 남긴다 —
    조용히 사라지지 않게."""
    strip = HoverStrip(plan_for(48, 320, 180))
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    entered = threading.Event()

    def put_failing_after_stop(i, data):  # 워커 스레드: stop()이 프로세스를 거둘 때까지 기다렸다가 예외 (공개된 상태만 봄 — pid)
        entered.set()
        deadline = time.monotonic() + WAIT_S
        while psutil.pid_exists(worker.pid) and time.monotonic() < deadline:
            time.sleep(0.005)
        raise RuntimeError("시험: stop 뒤 put 오류")

    monkeypatch.setattr(strip, "put", put_failing_after_stop)
    worker.start()
    _pump_until(qapp, entered.is_set, "첫 put")
    worker.stop()
    assert not worker.isRunning()
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == []
    err = capsys.readouterr().err
    log = [line for line in err.splitlines() if line.startswith(LOG_PREFIX)]
    assert len(log) == 1 and numbered_clip in log[0]
    assert "Traceback (most recent call last)" in err and "RuntimeError: 시험: stop 뒤 put 오류" in err


def test_missing_file_fails_with_stderr(qapp, tmp_path, make_builder):
    missing = str(tmp_path / "missing.mov")
    worker = make_builder(missing, HoverStrip(plan_for(48, 320, 180)))
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.done == [] and len(got.failed) == 1
    text = got.failed[0]
    assert missing in text and "ffmpeg" in text
    assert " ".join(worker.command) in text  # 명령
    stderr = text.split("\nstderr:\n", 1)[1]
    assert missing in stderr  # ffmpeg 자신의 오류 글 (Error opening input file <경로>)


def test_fewer_frames_than_planned_is_done(qapp, numbered_clip, make_builder):
    strip = HoverStrip(plan_for(60, 320, 180))  # 계획 60장, 파일은 48장 (잘린 파일·VFR처럼)
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [48]
    assert strip.has(47) and not strip.has(48)


def test_truncated_file_is_done_with_warning_log(qapp, truncated_clip, make_builder, capsys):
    """잘린 파일(복사·렌더가 진행 중인 NAS 파일처럼 — 헤더는 48장, 데이터는 중간에서 끊김): 번들 ffmpeg는 stderr에 오류 수준 글('partial
    file'·'wrong picture data size' 등)을 찍고도 종료 코드 0으로 끝난다. 장 경계의 EOF라 failed가 아니라 done(채운 장수 — 스펙 §5.3)이고,
    stderr 글은 삼키지 않고 기록(stderr)에 경고 머리 한 줄 + ffmpeg 글 전문 (창은 없음 — 신호는 done 하나뿐)."""
    total = movie_pipe_source.probe_movie(truncated_clip).nb_frames  # 파이프 캡처의 FRAME_COUNT와 같은 출처 (ffprobe — 헤더의 장수)
    assert total == 48
    strip = HoverStrip(plan_for(total, 320, 180))
    worker = make_builder(truncated_clip, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and len(got.done) == 1
    filled = got.done_counts[0]
    assert 1 <= filled < total and filled == strip.filled_count
    assert _numbers(strip, filled) == list(range(filled)) and not strip.has(filled)  # 채운 장은 앞에서부터 그 번호, 뒤는 빈 채
    err = capsys.readouterr().err
    head = f"{LOG_PREFIX} ffmpeg 경고 (종료 코드 0, {filled}장 채움) — {truncated_clip}"
    assert [line for line in err.splitlines() if line.startswith(LOG_PREFIX)] == [head]
    ffmpeg_text = err.split(head + "\n", 1)[1]
    assert "error" in ffmpeg_text.lower() and "prores" in ffmpeg_text  # ffmpeg 자신의 글 (디코더 오류 줄) — 줄이지 않음


def test_h264_builds(qapp, tmp_path, make_builder, make_video, capsys):
    """H.264 mp4 (conftest.make_video — libx264, 소리 트랙 포함, 2초 24fps = 48장 320×240) — 영상 트랙만 끝까지, 경고 기록 없음."""
    path = make_video(str(tmp_path / "clip_h264.mp4"))
    total = movie_pipe_source.probe_movie(path).nb_frames
    assert total == 48
    strip = HoverStrip(plan_for(total, 320, 240))
    worker = make_builder(path, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [48]
    assert strip.filled_count == 48 and strip.image(47).shape == (240, 320, 3)
    assert _logged(capsys) == []


def test_extra_frames_are_dropped(qapp, numbered_clip, make_builder, capsys):
    strip = HoverStrip(plan_for(40, 320, 180))  # 계획 40장, 파일은 48장 — 남는 8장은 읽어 버림
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [40]
    assert strip.filled_count == 40
    assert _numbers(strip, 40) == list(range(40))
    log = [line for line in capsys.readouterr().out.splitlines() if line.startswith(LOG_PREFIX)]
    assert len(log) == 1 and "넘침 8장" in log[0] and numbered_clip in log[0]


def test_mp4_builds(qapp, tmp_path, make_builder):
    """ProRes가 아닌 mp4 (conftest.write_test_video — cv2 mp4v, 즉 MPEG-4 Part 2). 장 i는 회색 (i*10) % 255 한 색."""
    path = write_test_video(str(tmp_path / "clip.mp4"), frames=30, size=(320, 240))
    plan = plan_for(30, 320, 240)
    assert (plan.width, plan.height) == (320, 240)
    strip = HoverStrip(plan)
    worker = make_builder(path, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [30]
    assert strip.image(0).shape == (240, 320, 3)
    assert all(abs(float(strip.image(i).mean()) - (i * 10) % 255) <= 6 for i in range(30))


@pytest.mark.parametrize("suspend_error, resume_error", [
    (psutil.AccessDenied, psutil.NoSuchProcess),
    # Windows에서 끝나 가는 프로세스의 NtSuspendProcess는 psutil이 감싸지 않은 OSError로 올 수 있음 — 그 밖의 psutil 오류는 psutil.Error
    (lambda pid: OSError(5, f"시험: NtSuspendProcess 실패 (pid {pid})"), lambda pid: psutil.Error()),
], ids=["psutil-denied-gone", "oserror-psutil-error"])
def test_suspend_failure_logs_and_only_stops_reading(qapp, numbered_clip_200, make_builder, monkeypatch, capsys, suspend_error,
                                                     resume_error):
    """psutil이 정지·재개를 못 하면(psutil.Error 전부 — AccessDenied·NoSuchProcess 등 — 와 OSError) 기록 한 줄씩 — 읽기만 멈췄다가 이어서
    끝까지 (예외가 GUI 틱 슬롯·워커 스레드로 올라가 실패가 되지 않음)."""

    class _Refuses:
        def __init__(self, pid):
            self.pid = pid

        def suspend(self):
            raise suspend_error(self.pid)

        def resume(self):
            raise resume_error(self.pid)

    monkeypatch.setattr("yesoncheck.hover_strip_builder.psutil.Process", _Refuses)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(numbered_clip_200, strip)
    got = _Signals(worker)
    worker.paused = True
    worker.start()
    _pump_until(qapp, lambda: worker.pid is not None, "ffmpeg 띄움")
    _pump(qapp, 0.5)
    assert strip.filled_count == 0  # 프로세스는 돌지만(파이프가 차서 막힘) 읽지 않음
    worker.paused = False
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [200]
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith(f"{LOG_PREFIX} 정지/재개 실패")]
    assert len(lines) == 2
    assert f"정지, pid {worker.pid}: {type(suspend_error(worker.pid)).__name__}: " in lines[0]
    assert f"재개, pid {worker.pid}: {type(resume_error(worker.pid)).__name__}: " in lines[1]
