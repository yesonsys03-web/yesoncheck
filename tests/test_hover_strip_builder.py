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

거친 띠(키프레임만 — 스펙 2026-11-11 §3)는 GOP 12의 번호 H.264(prores_clips.make_numbered_h264 — 키프레임 번호가 range(0, n, 12)이고 그림에서
번호가 읽힘)에 MAX_THUMBS를 줄여 간격 > 1로 본다. 워커 하나가 프로세스를 여럿(ffprobe → 거친 ffmpeg → 정확한 ffmpeg) 띄우므로 make_builder는
pids 전부가 끝났는지 확인한다. coarse_done·done 순간의 상태는 직접 연결로 받아 워커 스레드에서 그대로 적는다.
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
from tests.prores_clips import frame_number, make_numbered_clip, make_numbered_h264, make_truncated, run_ffmpeg
from yesoncheck import external_tools, hover_keyframes, hover_strip, hover_strip_builder, movie_pipe_source
from yesoncheck.hover_keyframes import StreamHeader
from yesoncheck.hover_strip import LOG_PREFIX, HoverStrip, StripPlan, plan_for
from yesoncheck.hover_strip_builder import STOP_WAIT_MS, HoverStripBuilder, build_coarse_command, build_command

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


@pytest.fixture(scope="session")
def h264_gop12(tmp_path_factory):
    """번호 H.264 200장, 키프레임 0·12·…·192 (17장 — 200 ≥ 17 × 4라 거친 띠 조건을 넘음)."""
    path = str(tmp_path_factory.mktemp("hover_strip_builder") / "numbered_gop12.mp4")
    make_numbered_h264(path, count=200, gop=12)
    return path


H264_KEYFRAMES = list(range(0, 200, 12))


@pytest.fixture(scope="session")
def h264_gop12_cut(tmp_path_factory, h264_gop12):
    """h264_gop12를 편집 목록으로 앞을 자른 클립(-ss 1.3 -c copy): 1.0초(24번)의 키프레임부터 복사하고 앞 8장(24~31번)은 버림(D) — 그 키프레임은
    'KD_'라 -skip_frame nokey가 내지 않음. 남는 장의 그림 번호는 원래 번호(32 + 새 번호)."""
    path = str(tmp_path_factory.mktemp("hover_strip_builder") / "numbered_gop12_cut.mp4")
    run_ffmpeg(["-ss", "1.3", "-i", h264_gop12, "-c", "copy", path], "편집 목록 클립")
    return path


CUT_OFFSET = 32  # 잘린 클립의 새 0번 = 원래 32번


@pytest.fixture
def make_builder():
    """워커를 만들고, 시험이 끝나면(실패해도) stop — 스레드가 끝나고 띄운 프로세스(ffprobe·거친 ffmpeg·정확한 ffmpeg) 모두 거둬졌는지 확인."""
    made = []

    def make(path, strip, **kwargs):
        worker = HoverStripBuilder(path, strip, **kwargs)
        made.append(worker)
        return worker

    yield make
    for worker in made:
        worker.stop()
        assert not worker.isRunning()
        assert worker.pid is None or not psutil.pid_exists(worker.pid)
        assert [pid for pid in worker.pids if psutil.pid_exists(pid)] == [], f"남은 프로세스: {worker.pids}"


class _Signals:
    """워커의 세 신호를 리스트로 받음 (GUI 스레드 — processEvents가 전달)."""

    def __init__(self, worker):
        self.progress, self.done, self.failed, self.coarse = [], [], [], []
        worker.progress.connect(lambda filled: self.progress.append(filled))
        worker.done.connect(lambda filled, seconds: self.done.append((filled, seconds)))
        worker.failed.connect(lambda text: self.failed.append(text))
        worker.coarse_done.connect(lambda filled, seconds: self.coarse.append((filled, seconds)))

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
    """4K 원본(720p보다 큼)의 명령 — 1코어로 묶은 지금 명령과 글자 그대로 (측정된 4K 설정이 바뀌지 않음, hover_strip.thread_limits).
    1080p 원본도 같은 옵션 (Ruling 24)."""
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
    full_hd = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=1920, source_height=1080)
    assert build_command("/opt/ffmpeg", "/clips/a b.mov", full_hd) == build_command("/opt/ffmpeg", "/clips/a b.mov", every)  # 코덱 모름
    assert build_command("/opt/ffmpeg", "/clips/a b.mov", full_hd, "prores") == build_command("/opt/ffmpeg", "/clips/a b.mov", every)
    assert build_command("/opt/ffmpeg", "/clips/a b.mov", every, "h264") == build_command("/opt/ffmpeg", "/clips/a b.mov", every)  # 4K
    inter = build_command("/opt/ffmpeg", "/clips/a b.mov", full_hd, "h264")  # 1080p 이하 long-GOP (Ruling 25)
    assert "-threads" not in inter and "-filter_threads" not in inter


@pytest.mark.parametrize("source", [(1280, 720), (720, 1280), (640, 360), (320, 180)])
def test_720p_or_smaller_source_has_no_thread_options(source):
    """원본이 720p 이하면 스레드 옵션을 넣지 않음(ffmpeg 기본 — 이 Mac은 CPU 수만큼): 긴 720p 애니매틱의 띠가 1코어로 67초 걸리던 것
    (스펙 2026-11-11 §2, 임계는 Ruling 24 — 1080p는 측정에서 불통과라 1코어 그대로). 나머지 명령은 4K의 것에서 그 네 토큰만 빠진 것."""
    plan = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=source[0], source_height=source[1])
    command = build_command("ffmpeg", "x.mov", plan)
    assert "-threads" not in command and "-filter_threads" not in command
    assert build_command("ffmpeg", "x.mov", plan, "prores") == command  # 720p 이하는 all-intra도
    assert build_coarse_command("ffmpeg", "x.mov", plan, "h264") == build_coarse_command("ffmpeg", "x.mov", plan)
    big = StripPlan(total=48, step=1, count=48, width=320, height=180, source_width=3840, source_height=2160)
    assert command == [arg for i, arg in enumerate(build_command("ffmpeg", "x.mov", big)) if i not in (4, 5, 6, 7)]


@pytest.mark.parametrize("clip, total, codec_known, expect_threads", [
    ("h264_gop12", 200, True, False),  # 긴 1080p H.264 — 헤더로 코덱을 알아 두 명령 모두 옵션 없음 (Ruling 25)
    ("numbered_clip_200", 200, True, True),  # 긴 1080p ProRes — all-intra라 1코어 (거친 띠도 건너뜀)
    ("numbered_clip", 48, False, True),  # 짧은 1080p — 헤더를 읽지 않아 코덱을 모름 → 1코어
])
def test_worker_picks_threads_from_header_codec(qapp, request, make_builder, monkeypatch, clip, total, codec_known, expect_threads):
    """워커는 긴 파일(간격 > 1)이면 거친 띠 조건과 상관없이 헤더 ffprobe로 코덱을 알아내 정확한 띠·거친 띠 명령의 스레드를 정함 (Ruling 25).
    계획의 원본 크기만 1920×1080으로 둠(스레드 규칙은 계획을 봄 — 클립 자체는 320×180)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    path = request.getfixturevalue(clip)
    strip = HoverStrip(plan_for(total, 1920, 1080))
    worker = make_builder(path, strip)
    assert "-threads" in worker.command  # 띄우기 전 — 코덱을 모름
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and len(got.done) == 1
    assert worker.codec == ({"h264_gop12": "h264", "numbered_clip_200": "prores"}.get(clip) if codec_known else None)
    for command in (worker.command, worker.coarse_command):
        if command is not None:
            assert ("-threads" in command and "-filter_threads" in command) == expect_threads, command
    assert (worker.coarse_command is not None) == (clip == "h264_gop12")


def test_header_failure_keeps_single_thread(qapp, tmp_path, h264_gop12, make_builder, monkeypatch, capsys):
    """헤더 ffprobe가 실패하면 코덱을 모르므로 720p보다 큰 원본은 1코어 그대로 (거친 띠 실패 기록 한 줄, 정확한 띠는 끝까지)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    strip = HoverStrip(plan_for(200, 1920, 1080))
    worker = make_builder(h264_gop12, strip, ffprobe=str(tmp_path / "no_such_ffprobe"))
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and worker.codec is None
    assert "-threads" in worker.command and "-filter_threads" in worker.command
    assert len(_log_lines(capsys.readouterr().err, "거친 띠를 만들지 못했습니다(정확한 띠는 계속)")) == 1


def test_threads_option_follows_constant(monkeypatch):
    """(720p보다 큰 원본) 디코더 스레드(-threads — 입력 옵션)·필터 스레드(-filter_threads — 전역 옵션)는 두 상수를 호출 때 읽음.
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


def test_stop_before_start_spawns_nothing(qapp, numbered_clip, h264_gop12, make_builder, monkeypatch, capsys):
    """start 전에 stop했으면 run은 프로세스를 하나도 띄우지 않음 — 짧은 파일(정확한 띠만)도, 긴 파일(헤더 ffprobe부터)도. 신호·기록 없음."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    for path, total in ((numbered_clip, 48), (h264_gop12, 200)):
        worker = make_builder(path, HoverStrip(plan_for(total, 320, 180)))
        got = _Signals(worker)
        worker.stop()
        worker.start()
        _finish(qapp, worker)
        assert worker.pids == [] and worker.pid is None, path
        assert got.done == [] and got.failed == [] and got.coarse == []
    assert _logged(capsys) == []


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
    """띄우자마자 stop: 스레드가 끝나고 띄운 프로세스가 있으면 거둠(좀비 없음). stop이 run의 검사보다 먼저면 ffmpeg를 아예 띄우지 않음(2026-11-11 —
    그래서 pid가 없을 수도 있음; 띄운 뒤의 kill은 test_stop_while_paused·test_stop_while_reading이 늘 봄)."""
    worker = make_builder(numbered_clip, HoverStrip(plan_for(48, 320, 180)))
    got = _Signals(worker)
    worker.start()
    worker.stop()
    assert not worker.isRunning()
    assert [pid for pid in worker.pids if psutil.pid_exists(pid)] == []  # kill 뒤 거둠 — 좀비 없음
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


# ---------------------------------------------------------------- 거친 띠 (키프레임만 — 스펙 2026-11-11 §3)


def test_coarse_command_shape():
    """거친 패스 명령: -skip_frame nokey는 입력(디코더) 옵션이라 -i 앞(디코더 스레드 -threads 바로 앞), 스레드 규칙은 정확한 띠와 같음(1080p·4K는
    1코어, 720p 이하는 옵션 없음). select는 없음 — 키프레임 전부를 받아 워커가 m장마다 하나만 넣음(스펙 §3.2의 select와 다름)."""
    big = StripPlan(total=14_400, step=29, count=497, width=320, height=180, source_width=3840, source_height=2160)
    assert build_coarse_command("/opt/ffmpeg", "/clips/a b.mov", big) == [
        "/opt/ffmpeg", "-nostdin", "-v", "error", "-filter_threads", "1", "-skip_frame", "nokey", "-threads", "1", "-i", "/clips/a b.mov",
        "-map", "0:V:0", "-fps_mode", "passthrough", "-vf", "scale=320:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    small = StripPlan(total=32_553, step=66, count=494, width=320, height=180, source_width=1280, source_height=720)
    assert build_coarse_command("ffmpeg", "x.mp4", small) == [
        "ffmpeg", "-nostdin", "-v", "error", "-skip_frame", "nokey", "-i", "x.mp4", "-map", "0:V:0", "-fps_mode", "passthrough",
        "-vf", "scale=320:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]


def _coarse_snapshots(worker, strip):
    """coarse_done·done을 직접 연결로 받아(워커 스레드 — 신호를 낸 그 순간) 그때의 거친 띠·정확한 띠 상태를 적음."""
    seen = {}

    def on_coarse(filled, seconds):
        seen["coarse"] = (filled, worker.coarse_strip, strip.filled_count)

    def on_done(filled, seconds):
        seen["done"] = worker.coarse_strip

    worker.coarse_done.connect(on_coarse, Qt.DirectConnection)
    worker.done.connect(on_done, Qt.DirectConnection)
    return seen


def _log_lines(text, head):
    return [line for line in text.splitlines() if line.startswith(f"{LOG_PREFIX} {head}")]


def _put_then_pause(monkeypatch, worker, paused_at):
    """거친 띠의 첫 put 뒤에 워커 스레드에서 바로 멈춤을 세움 — 320×180 17장은 순식간이라 끝나기 전에 걸림을 보장."""
    real_put = hover_keyframes.KeyframeStrip.put

    def put_then_pause(self, j, data):  # 워커 스레드
        real_put(self, j, data)
        if not paused_at:
            paused_at.append(j)
            worker.paused = True

    monkeypatch.setattr(hover_keyframes.KeyframeStrip, "put", put_then_pause)


def test_coarse_strip_fills_keyframes_first_then_exact_strip(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """긴 H.264(간격 > 1): ffprobe로 키프레임을 읽어 거친 띠를 먼저 다 채우고(coarse_done — 그때 정확한 띠는 0장) 정확한 띠를 이어 채우며,
    done을 내기 전에 거친 띠를 버림. 거친 띠의 j번째 그림은 키프레임 frames[j] (그림에 실린 번호), 번호 목록은 GOP 12 그대로."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)  # 200장 → 간격 4, 50장
    plan = plan_for(200, 320, 180)
    assert (plan.step, plan.count) == (4, 50)
    strip = HoverStrip(plan)
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    seen = _coarse_snapshots(worker, strip)
    assert worker.coarse_strip is None and worker.coarse_command is None  # 띄우기 전
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and len(got.coarse) == 1
    filled, coarse, exact_then = seen["coarse"]
    assert coarse.frames == tuple(H264_KEYFRAMES) and filled == coarse.filled_count == coarse.count == 17
    assert exact_then == 0  # 거친 띠가 먼저
    assert [frame_number(coarse.image(j)) for j in range(coarse.count)] == H264_KEYFRAMES
    assert seen["done"] is None and worker.coarse_strip is None  # done 전에 버림
    assert _numbers(strip, 50) == list(range(0, 200, 4))
    assert 0 < got.coarse[0][1] <= got.done[0][1]  # 초는 둘 다 워커를 띄운 때부터
    assert worker.coarse_count == 17 and "-skip_frame" in worker.coarse_command and "-skip_frame" not in worker.command
    assert len(worker.pids) == 4  # 헤더 ffprobe → 패킷 ffprobe → 거친 ffmpeg → 정확한 ffmpeg
    captured = capsys.readouterr()
    assert _log_lines(captured.out, "거친 띠") == [f"{LOG_PREFIX} 거친 띠 먼저: 키프레임 17장 → 17장(간격 1, 전체 200장) — {h264_gop12}"]
    assert _log_lines(captured.err, "") == []  # 경고·실패 없음


def test_coarse_strip_subsamples_many_keyframes(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """키프레임이 MAX_COARSE를 넘으면 m = ceil(K / 최대)마다 하나 — ffmpeg는 키프레임 전부(K장)를 내고 워커가 i % m == 0인 장만 넣어 목록
    frames[::m]과 짝 (그림 번호로 확인). 장수 검사는 받은 수 == K(줄이기 전)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    monkeypatch.setattr(hover_keyframes, "MAX_COARSE", 5)  # 17장 → 간격 4, 5장
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    seen = _coarse_snapshots(worker, strip)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and len(got.coarse) == 1
    coarse = seen["coarse"][1]
    assert coarse.frames == tuple(H264_KEYFRAMES[::4]) == (0, 48, 96, 144, 192)
    assert [frame_number(coarse.image(j)) for j in range(5)] == [0, 48, 96, 144, 192]
    assert "select" not in " ".join(worker.coarse_command) and worker.coarse_count == 5
    assert f"{LOG_PREFIX} 거친 띠 먼저: 키프레임 17장 → 5장(간격 4, 전체 200장) — {h264_gop12}" in capsys.readouterr().out


def test_coarse_strip_on_h264_with_audio_track(qapp, tmp_path, make_builder, make_video, monkeypatch, capsys):
    """소리 트랙이 있는 H.264 mp4(conftest.make_video, 10초 240장, GOP 12): 키프레임 목록은 영상 패킷만(V:0) — 20장, 소리 패킷은 세지 않음."""
    path = make_video(str(tmp_path / "gop12_audio.mp4"), seconds=10,
                      video_args=["-g", "12", "-keyint_min", "12", "-sc_threshold", "0"])
    total = movie_pipe_source.probe_movie(path).nb_frames
    assert total == 240
    ffprobe = external_tools.ffprobe_path()
    header = hover_keyframes.probe_header(ffprobe, path)
    assert hover_keyframes.scan_keyframes(ffprobe, path, header) == (list(range(0, 240, 12)), 240)
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 48)  # 간격 5, 48장
    strip = HoverStrip(plan_for(total, 320, 240))
    worker = make_builder(path, strip)
    got = _Signals(worker)
    seen = _coarse_snapshots(worker, strip)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [48] and [filled for filled, _ in got.coarse] == [20]
    coarse = seen["coarse"][1]
    assert coarse.frames == tuple(range(0, 240, 12)) and coarse.image(19).shape == (240, 320, 3)
    assert _log_lines(capsys.readouterr().err, "") == []


def test_all_intra_prores_skips_coarse_strip(qapp, numbered_clip_200, make_builder, monkeypatch, capsys):
    """all-intra ProRes: 헤더만 읽고(패킷 스캔 없음 — 파일을 다 읽지 않음) 기록 한 줄 '거친 띠 건너뜀: all-intra 코덱 prores' 뒤 정확한 띠만
    (거친 ffmpeg 없음, coarse_strip은 늘 None)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(numbered_clip_200, strip)
    got = _Signals(worker)
    during = []
    worker.progress.connect(lambda filled: during.append(worker.coarse_strip), Qt.DirectConnection)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == []
    assert during and set(during) == {None} and worker.coarse_strip is None and worker.coarse_command is None
    assert _numbers(strip, 50) == list(range(0, 200, 4))
    assert len(worker.pids) == 2  # 헤더 ffprobe → 정확한 ffmpeg (패킷 ffprobe 없음)
    lines = _log_lines(capsys.readouterr().out, "거친 띠")
    assert len(lines) == 1 and lines[0].startswith(f"{LOG_PREFIX} 거친 띠 건너뜀: all-intra 코덱 prores")
    assert lines[0].endswith(f" — {numbered_clip_200}")


def test_dense_keyframes_skip_coarse_strip_after_scan(qapp, tmp_path, make_builder, monkeypatch, capsys):
    """all-intra 코덱이 아니어도 키프레임이 촘촘하면(GOP 2 — K × 4 > 전체) 패킷 스캔 뒤 '거친 띠 건너뜀' 한 줄, 정확한 띠만."""
    path = str(tmp_path / "gop2.mp4")
    make_numbered_h264(path, count=200, gop=2)
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(path, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == [] and worker.coarse_command is None
    assert len(worker.pids) == 3  # 헤더 ffprobe → 패킷 ffprobe → 정확한 ffmpeg
    lines = _log_lines(capsys.readouterr().out, "거친 띠")
    assert lines == [f"{LOG_PREFIX} 거친 띠 건너뜀: 키프레임 100장 × 4 > 전체 200장 — 키프레임만 디코드해도 거의 전부 디코드하는 꼴 — {path}"]


def test_variable_rate_header_skips_coarse_strip(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """헤더의 속도를 모르거나 240을 넘으면(VFR의 90000/1) 실패가 아니라 건너뜀 — stdout 한 줄, stderr 없음, 패킷 스캔 없음."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    vfr = StreamHeader(codec="h264", rate_text="90000/1", rate=None, start=hover_keyframes.Fraction(0))
    monkeypatch.setattr(hover_keyframes, "probe_header", lambda *args, **kwargs: vfr)
    monkeypatch.setattr(hover_keyframes, "scan_keyframes", lambda *args, **kwargs: pytest.fail("패킷 스캔을 부름"))
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == []
    captured = capsys.readouterr()
    lines = _log_lines(captured.out, "거친 띠")
    assert len(lines) == 1 and lines[0].startswith(f"{LOG_PREFIX} 거친 띠 건너뜀: 가변 프레임") and "90000/1" in lines[0]
    assert _log_lines(captured.err, "") == []


def test_edit_list_cut_h264_coarse_count_matches(qapp, h264_gop12_cut, make_builder, monkeypatch, capsys):
    """편집 목록으로 앞이 잘린 mp4: 버림(KD_) 키프레임은 목록에서 빠져 목록 장수 == -skip_frame nokey 출력 장수 == 거친 띠 채움 — 장수가 맞아
    거친 띠를 버리지 않음. 그림의 원래 번호 − 32 = 목록의 번호 (j번째 출력 = 목록의 j번째)."""
    total = movie_pipe_source.probe_movie(h264_gop12_cut).nb_frames
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 40)
    plan = plan_for(total, 320, 180)
    assert plan.step > 1
    strip = HoverStrip(plan)
    worker = make_builder(h264_gop12_cut, strip)
    got = _Signals(worker)
    seen = _coarse_snapshots(worker, strip)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and len(got.done) == 1 and len(got.coarse) == 1
    filled, coarse, _ = seen["coarse"]
    assert coarse.frames == tuple(range(4, 168, 12)) and filled == coarse.filled_count == coarse.count == 14
    assert [frame_number(coarse.image(j)) - CUT_OFFSET for j in range(coarse.count)] == list(coarse.frames)
    assert _log_lines(capsys.readouterr().err, "") == []


def test_short_file_runs_no_keyframe_scan(qapp, numbered_clip, make_builder, capsys):
    """간격 1(500장 이하)은 거친 띠를 생각하지 않음 — ffprobe도 띄우지 않고 기록 줄도 없음 (정확한 띠가 곧 모든 장)."""
    strip = HoverStrip(plan_for(48, 320, 180))
    worker = make_builder(numbered_clip, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.done_counts == [48] and got.coarse == [] and len(worker.pids) == 1 and worker.coarse_command is None
    assert _logged(capsys) == []


@pytest.mark.parametrize("ffprobe_kind", ["missing_file", "exits_nonzero", "not_found"])
def test_keyframe_scan_failure_logs_and_exact_strip_completes(qapp, tmp_path, h264_gop12, make_builder, monkeypatch, capsys,
                                                              ffprobe_kind):
    """ffprobe 실패(실행 파일이 없음 — OSError, 0이 아닌 종료 코드 — RuntimeError, 찾지 못함 — ToolNotFoundError — 셋 다 헤더 ffprobe에서): 거친
    띠만 건너뜀 — 기록(stderr) 한 줄 + 사유 전문, 실패 신호 없음(그래서 플레이어의 오류 창도 없음), 정확한 띠는 끝까지."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    kwargs = {}
    if ffprobe_kind == "missing_file":
        kwargs["ffprobe"] = str(tmp_path / "no_such_ffprobe")
    elif ffprobe_kind == "exits_nonzero":
        kwargs["ffprobe"] = external_tools.ffmpeg_path()  # ffmpeg는 ffprobe의 옵션(-select_streams)을 모름 → 0이 아닌 코드
    else:
        def no_ffprobe():
            raise external_tools.ToolNotFoundError("시험: ffprobe 없음")

        monkeypatch.setattr(hover_strip_builder, "ffprobe_path", no_ffprobe)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip, **kwargs)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == [] and worker.coarse_strip is None
    assert _numbers(strip, 50) == list(range(0, 200, 4))
    err = capsys.readouterr().err
    head = f"{LOG_PREFIX} 거친 띠를 만들지 못했습니다(정확한 띠는 계속) — {h264_gop12}"
    assert _log_lines(err, "") == [head]
    reason = err.split(head + "\n", 1)[1]
    expected = {"missing_file": "no_such_ffprobe", "exits_nonzero": "종료 코드", "not_found": "ToolNotFoundError: 시험: ffprobe 없음"}
    assert expected[ffprobe_kind] in reason and reason.startswith("헤더·키프레임 목록을 읽지 못했습니다 — ")


@pytest.mark.parametrize("change", ["extra", "missing", "far_fewer"])
def test_coarse_count_mismatch_discards_coarse_strip(qapp, h264_gop12, make_builder, monkeypatch, capsys, change):
    """키프레임 패스의 출력 장수가 목록과 다르면 번호를 믿을 수 없어 거친 띠를 버림 — coarse_done 없음, 기록(stderr) 한 줄 + 사유(두 장수),
    창 없음, 정확한 띠는 끝까지. 목록보다 적게 오면(extra — 목록이 하나 많음) EOF에서 알고, 목록을 넘으면(missing·far_fewer) 넘는 그 장에서 끊음
    (kill — EOF까지 디코드하지 않음; far_fewer는 목록 2장이라 3장째에서 끊기고 ffmpeg는 남은 장을 못 쓴 채 죽음)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    real_scan = hover_keyframes.scan_keyframes

    def changed_scan(*args, **kwargs):
        frames, packets = real_scan(*args, **kwargs)
        return {"extra": frames + [199], "missing": frames[:-1], "far_fewer": frames[:2]}[change], packets

    monkeypatch.setattr(hover_keyframes, "scan_keyframes", changed_scan)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    seen = _coarse_snapshots(worker, strip)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == [] and "coarse" not in seen
    assert worker.coarse_strip is None and seen["done"] is None
    err = capsys.readouterr().err
    head = f"{LOG_PREFIX} 거친 띠를 만들지 못했습니다(정확한 띠는 계속) — {h264_gop12}"
    assert _log_lines(err, "") == [head] and " ".join(worker.coarse_command) in err
    if change == "extra":
        assert "출력 17장 ≠ 키프레임 목록 18장" in err
    else:
        listed = {"missing": 16, "far_fewer": 2}[change]
        assert f"출력이 키프레임 목록 {listed}장을 넘었습니다 ({listed + 1}장째에서 끊음)" in err
    if change == "far_fewer":  # 남은 14장을 쓰지 못한 채 kill — 정상 종료(0)일 수 없음
        assert "종료 코드: 0\n" not in err


def test_coarse_ffmpeg_error_logs_and_exact_strip_completes(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """거친 ffmpeg가 0이 아닌 코드로 끝나면(여기서는 모르는 옵션) 기록(stderr) 한 줄 + 종료 코드·ffmpeg 글, 거친 띠는 버림, 정확한 띠는 끝까지."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    real_coarse = hover_strip_builder.build_coarse_command
    monkeypatch.setattr(hover_strip_builder, "build_coarse_command",
                        lambda *args: (lambda cmd: cmd[:2] + ["-no_such_option_for_test"] + cmd[2:])(real_coarse(*args)))
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == [] and worker.coarse_strip is None
    err = capsys.readouterr().err
    assert len(_log_lines(err, "거친 띠를 만들지 못했습니다(정확한 띠는 계속)")) == 1
    assert "종료 코드" in err and "no_such_option_for_test" in err


def test_unexpected_error_in_coarse_pass_logs_traceback_and_continues(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """거친 패스의 예상 못 한 예외(여기서는 subsample의 버그 흉내)는 트레이스백째 기록(stderr)하고 정확한 띠로 넘어감 — 실패 신호·창 없음."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)

    def broken_subsample(frames, max_count):
        raise KeyError("시험: subsample 버그")

    monkeypatch.setattr(hover_keyframes, "subsample", broken_subsample)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    worker.start()
    _finish(qapp, worker)
    assert got.failed == [] and got.done_counts == [50] and got.coarse == [] and worker.coarse_strip is None
    err = capsys.readouterr().err
    assert len(_log_lines(err, "거친 띠를 만들지 못했습니다(정확한 띠는 계속)")) == 1
    assert "Traceback (most recent call last)" in err and "KeyError: '시험: subsample 버그'" in err


@pytest.mark.parametrize("evidence", [
    pytest.param("status", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows의 psutil status()는 파이프 쓰기에서 막힌 스레드가 있으면 정지돼 있어도 running — drain 갈래가 동작으로 확인")),
    "drain",
])
def test_pause_during_coarse_pass_suspends_and_resume_finishes(qapp, h264_gop12, make_builder, monkeypatch, evidence):
    """거친 패스 도중의 멈춤: 그 패스의 ffmpeg(지금 프로세스)가 정지하고 더 채우지 않음(정확한 띠도 시작하지 않음). 정지 확인은 정확한 띠의
    도중 멈춤 시험과 같은 두 갈래(모듈 설명) — status는 psutil 상태 뒤 재개해 거친 띠 → 정확한 띠 끝까지(Windows는 건너뜀), drain은 파이프를
    비워 봐서 한 장도 더 오지 않음(모든 OS) 뒤 stop으로 끝냄(시험이 장을 먹었으므로)."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    paused_at = []
    _put_then_pause(monkeypatch, worker, paused_at)
    worker.start()
    _pump_until(qapp, lambda: paused_at, "거친 띠의 첫 장")
    _pump(qapp, 0.3)
    coarse = worker.coarse_strip
    n1 = coarse.filled_count
    _pump(qapp, 0.5)
    assert coarse.filled_count == n1 == 1 and strip.filled_count == 0 and got.coarse == [] and got.done == []
    assert worker.pid == worker.pids[2] and psutil.pid_exists(worker.pid)  # 지금 프로세스 = 거친 ffmpeg (헤더·패킷 ffprobe 다음)
    if evidence == "drain":
        pid, frame_bytes = worker.pid, strip.plan.frame_bytes
        drained, drainer, errors = _drain_pipe(worker._process.stdout, frame_bytes, 0.5)
        assert drained < frame_bytes, f"정지된 거친 ffmpeg에서 {drained}바이트가 옴 (한 장 {frame_bytes}바이트)"
        assert drainer.is_alive(), f"파이프를 비우는 도우미가 끝났습니다 (EOF 또는 오류 — {drained}바이트): {errors}"
        worker.stop()
        drainer.join(STOP_WAIT_MS / 1000)
        assert not worker.isRunning() and not psutil.pid_exists(pid)
        assert not drainer.is_alive() and errors == []
        _pump(qapp, 0.1)
        assert got.done == [] and got.failed == [] and got.coarse == []
        return
    assert _is_stopped(worker.pid)
    worker.paused = False
    _finish(qapp, worker)
    assert got.failed == [] and [filled for filled, _ in got.coarse] == [17] and got.done_counts == [50]


def test_pause_and_stop_during_keyframe_scan(qapp, make_builder, capsys):
    """키프레임 스캔(ffprobe) 도중에도 멈춤·stop이 지금 프로세스에 먹음: 받기만 하고 아무것도 보내지 않는 TCP 입력이라 ffprobe가 기다리는
    중 — 띄우기 전에 세운 멈춤은 띄운 직후 정지, stop은 kill·거두기 뒤 스레드 끝(정확한 ffmpeg는 띄우자마자 kill), 신호도 기록도 없음."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        strip = HoverStrip(plan_for(1000, 320, 180))  # 간격 2 — 거친 띠를 생각함
        worker = make_builder(f"tcp://127.0.0.1:{server.getsockname()[1]}", strip)
        got = _Signals(worker)
        worker.paused = True
        worker.start()
        _pump_until(qapp, lambda: worker.pid is not None, "ffprobe 띄움")
        _pump(qapp, 0.3)
        assert worker.pids == [worker.pid] and _is_stopped(worker.pid)  # 아직 ffprobe — 띄운 직후 정지
        started = time.monotonic()
        worker.stop()
        assert time.monotonic() - started < 2 * STOP_WAIT_MS / 1000
        assert not worker.isRunning() and [pid for pid in worker.pids if psutil.pid_exists(pid)] == []
        assert len(worker.pids) == 1  # 헤더 ffprobe뿐 — stop 뒤에는 정확한 ffmpeg를 띄우지 않음
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == [] and got.coarse == [] and worker.coarse_strip is None and strip.filled_count == 0
    assert _logged(capsys) == []


@pytest.mark.parametrize("case", ["partial_json", "traceback"])
def test_stop_right_after_keyframe_scan(qapp, h264_gop12, make_builder, monkeypatch, capsys, case):
    """패킷 ffprobe가 끝나는 순간 stop이 오면: 읽다 끊긴 JSON(partial_json — stop이 읽기를 멈춰 반쪽만 받음)을 해석하지 않고 조용히 빠져나옴
    ('예상 못 한 예외'로 거짓 기록하지 않음), 트레이스백이 있는 문제(traceback)는 정확한 띠와 같은 머리 '멈춘 띠 워커에서 예상 못 한 오류'로
    기록하고 신호는 없음. 어느 쪽이든 그 뒤 거친·정확한 ffmpeg를 띄우지 않음. 그 순간은 지금 프로세스를 띄우는 _run_pass를 감싸 만듦 —
    진짜 ffprobe가 끝난 뒤 다른 스레드의 stop()이 표지를 둘 때까지 기다렸다가, 반쪽 출력 또는 읽기 오류를 돌려줌."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    worker = make_builder(h264_gop12, HoverStrip(plan_for(200, 320, 180)))
    got = _Signals(worker)
    real_run_pass = worker._run_pass
    stoppers = []

    def run_pass_then_stop(command, consume, tool):  # 워커 스레드
        result = real_run_pass(command, consume, tool)
        if "packet=pts_time,flags" not in command:
            return result
        stopper = threading.Thread(target=worker.stop, name="test-stopper")
        stopper.start()
        stoppers.append(stopper)
        deadline = time.monotonic() + WAIT_S
        while not worker._stopped and time.monotonic() < deadline:  # stop()이 표지를 둘 때까지 (잠금 다음 첫 줄)
            time.sleep(0.001)
        problem, returncode, stderr, out, trace = result
        if case == "partial_json":
            return None, 0, stderr, out[:len(out) // 2], None
        return ("ffprobe 출력을 읽다 오류가 났습니다.", returncode, stderr, None,
                "Traceback (most recent call last):\n  File \"시험\"\nRuntimeError: 시험: 읽기 오류\n")

    monkeypatch.setattr(worker, "_run_pass", run_pass_then_stop)
    worker.start()
    _finish(qapp, worker)
    for stopper in stoppers:
        stopper.join(WAIT_S)
    assert len(stoppers) == 1 and not stoppers[0].is_alive()
    assert len(worker.pids) == 2  # 헤더·패킷 ffprobe뿐 — stop 뒤에 거친·정확한 ffmpeg를 띄우지 않음
    assert got.done == [] and got.failed == [] and got.coarse == [] and worker.coarse_strip is None
    err = capsys.readouterr().err
    logged = [line for line in err.splitlines() if line.startswith(LOG_PREFIX)]
    if case == "partial_json":
        assert logged == []
    else:
        assert logged == [f"{LOG_PREFIX} 멈춘 띠 워커에서 예상 못 한 오류가 났습니다 (stop 뒤라 신호 없음) — {h264_gop12}"]
        assert "RuntimeError: 시험: 읽기 오류" in err


def test_stop_during_coarse_pass_drops_coarse_strip(qapp, h264_gop12, make_builder, monkeypatch, capsys):
    """거친 패스 도중 stop: 프로세스·스레드가 끝나고 거친 띠를 놓음(coarse_strip None), 신호 없음 — 기록은 '거친 띠 먼저' 한 줄뿐."""
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 50)
    strip = HoverStrip(plan_for(200, 320, 180))
    worker = make_builder(h264_gop12, strip)
    got = _Signals(worker)
    paused_at = []
    _put_then_pause(monkeypatch, worker, paused_at)
    worker.start()
    _pump_until(qapp, lambda: paused_at, "거친 띠의 첫 장")
    assert worker.coarse_strip is not None
    worker.stop()
    assert not worker.isRunning() and [pid for pid in worker.pids if psutil.pid_exists(pid)] == []
    assert worker.coarse_strip is None
    assert len(worker.pids) == 3  # 헤더·패킷 ffprobe → 거친 ffmpeg — stop 뒤에는 정확한 ffmpeg를 띄우지 않음
    _pump(qapp, 0.1)
    assert got.done == [] and got.failed == [] and got.coarse == [] and strip.filled_count == 0
    logged = _logged(capsys)
    assert len(logged) == 1 and logged[0].startswith(f"{LOG_PREFIX} 거친 띠 먼저:")
