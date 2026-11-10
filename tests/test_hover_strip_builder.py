"""hover_strip_builder — 실제 번들 ffmpeg로 띠를 만드는 워커 (스펙 §5.3·§5.7 ②).

번호 클립(prores_clips.make_numbered_clip — 320×180이라 띠 크기와 같아 frame_number로 번호를 그대로 읽음)으로 순서·간격, psutil 정지·재개,
stop(정지된 프로세스·읽기에서 막힌 스레드 포함), 실패 글, 계획보다 적거나 많은 장을 본다. 신호는 리스트에 connect하고 qapp.processEvents()로
받는다(워커 스레드의 신호는 GUI 스레드의 이벤트 루프가 전달). 모든 기다림에 한도가 있어 멈추면 실패로 끝나고, 만든 워커는 make_builder
픽스처가 끝에서(시험이 실패해도) stop한다 — ffmpeg 프로세스·스레드가 남지 않게.

320×180 200장은 이 Mac에서 첫 장부터 끝까지 약 30ms라 GUI 스레드가 progress를 받은 뒤 멈추면 이미 끝나 있다 — 도중 멈춤 시험은 progress를
직접 연결(Qt.DirectConnection)로 받아 워커 스레드 안에서 바로 paused를 세운다(끝나기 전에 멈춤이 걸림을 보장).
"""

import socket
import time

import psutil
import pytest
from PyQt5.QtCore import Qt

from tests.conftest import write_test_video
from tests.prores_clips import frame_number, make_numbered_clip
from yesoncheck import hover_strip
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
    return psutil.Process(pid).status() == psutil.STATUS_STOPPED


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
    every = StripPlan(total=48, step=1, count=48, width=320, height=180)
    assert build_command("/opt/ffmpeg", "/clips/a b.mov", every) == [
        "/opt/ffmpeg", "-nostdin", "-v", "error", "-i", "/clips/a b.mov", "-map", "0:V:0", "-fps_mode", "passthrough",
        "-vf", "scale=320:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    sampled = StripPlan(total=14_400, step=29, count=497, width=180, height=320)
    command = build_command("ffmpeg", "x.mov", sampled)
    vf = command[command.index("-vf") + 1]
    # 셸 없이 인자 하나 — 쉼표 앞의 역슬래시 하나는 필터 파서용(select 식 안의 쉼표가 필터 구분자가 아니게)
    assert vf == "select=not(mod(n\\,29)),scale=180:320" and vf.count("\\") == 1
    assert len(command) == len(build_command("ffmpeg", "x.mov", every))


def test_pause_suspends_process_and_resume_finishes(qapp, numbered_clip_200, make_builder):
    strip = HoverStrip(plan_for(200, 320, 180))
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
    assert _is_stopped(worker.pid)  # 읽기만 멈춘 것이 아니라 프로세스가 정지 (CPU 0)
    assert got.done == [] and got.failed == []
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


def test_stop_kills_process_and_thread(qapp, numbered_clip, make_builder):
    worker = make_builder(numbered_clip, HoverStrip(plan_for(48, 320, 180)))
    got = _Signals(worker)
    worker.start()
    worker.stop()
    assert not worker.isRunning()
    assert worker.pid is not None and not psutil.pid_exists(worker.pid)  # kill 뒤 거둠 — 좀비 없음
    worker.stop()  # 두 번 불러도 됨
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == []


def test_stop_while_paused_kills_process(qapp, numbered_clip_200, make_builder):
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


def test_stop_while_reading_kills_blocked_process(qapp, make_builder):
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


def test_suspend_failure_logs_and_only_stops_reading(qapp, numbered_clip_200, make_builder, monkeypatch, capsys):
    """psutil이 정지·재개를 못 하면(AccessDenied·NoSuchProcess) 기록 한 줄씩 — 읽기만 멈췄다가 이어서 끝까지."""

    class _Refuses:
        def __init__(self, pid):
            self.pid = pid

        def suspend(self):
            raise psutil.AccessDenied(self.pid)

        def resume(self):
            raise psutil.NoSuchProcess(self.pid)

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
    err = capsys.readouterr().err
    assert err.count(f"{LOG_PREFIX} 정지/재개 실패") == 2
    assert "AccessDenied" in err and "NoSuchProcess" in err
