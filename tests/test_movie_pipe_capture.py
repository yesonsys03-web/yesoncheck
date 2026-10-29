"""ffmpeg 파이프 캡처 코어 (yesoncheck/movie_pipe_source.py 2부): 실제 ffmpeg 프로세스로 클립 공장 클립을 읽는다 (mock 없음 —
오류 창 호출만 바꿔치기). 순차 읽기의 cv2 의미, cv2와 바이트 동일, 도중 실패의 자체 완결(스펙 §5.5), 프로세스 수명(§5.6).

내부 세션(`cap._session` — 프로세스·스레드)은 수명 단언에만 들여다본다. 오류 창은 `error_window.show_window`를 바꿔치기해
기록한다 — movie_pipe_source가 error_window 모듈에서 그 이름을 읽으므로 그 모듈에서 바꾼다 (CLAUDE.md 바꿔치기 규칙).
"""

import dataclasses
import gc
import sys
import threading
import time
import weakref
from fractions import Fraction
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.prores_clips import (
    BYTE_EXACT, HEIGHT, TOLERANCE_422, WIDTH, byte_diff_stats, frame_alignment_problem, frame_number, make_audio_first,
    make_chroma_clip, make_numbered_clip, make_truncated, read_all_frames, stats_summary,
)
from yesoncheck import error_window, external_tools, movie_pipe_source
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, READAHEAD_FRAMES, FFmpegPipeCapture, MovieProbe, PipeCaptureError, probe_movie,
)

COUNT = 120
WAIT_S = 10  # 프로세스·스레드가 끝나기를 기다리는 한도 (보통 수십 ms)
KILL_SLACK = 20  # ffmpeg를 죽인 뒤 전송에 남아 더 나올 수 있는 정상 프레임 수의 상한 (큐 밖 — 실측 macOS TCP ~2장)
POS = cv2.CAP_PROP_POS_FRAMES
PROPS = (cv2.CAP_PROP_FPS, cv2.CAP_PROP_FRAME_COUNT, POS, cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)
# ffmpeg 명령의 출력 대상 (_Transport.output): POSIX는 stdout(= socketpair의 한 끝), Windows는 127.0.0.1 TCP 리스너
OUTPUT_MARK = "tcp://127.0.0.1:" if sys.platform == "win32" else "pipe:1"
# ffmpeg 대역(파이썬 -c)의 머리말: open_output(출력 대상)이 쓸 곳을 연다 — "pipe:1"이면 stdout(POSIX: socketpair 끝), tcp://면 접속
STAND_IN_PRELUDE = (
    "import socket, sys\n"
    "def open_output(target):\n"
    "    if target == 'pipe:1':\n"
    "        return sys.stdout.buffer\n"
    "    host, port = target.removeprefix('tcp://').split('?')[0].rsplit(':', 1)\n"
    "    return socket.create_connection((host, int(port))).makefile('wb')\n"
)


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 120장 24fps 번호 클립 (프레임 i는 회색 블록 두 개로 인코딩, frame_number로 복호)."""
    path = str(tmp_path_factory.mktemp("capture_4444") / "numbered_4444.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


@pytest.fixture(scope="session")
def prores_422_clip(tmp_path_factory):
    """422 HQ 120장 23.976fps(24000/1001) 번호 클립."""
    path = str(tmp_path_factory.mktemp("capture_422") / "numbered_422.mov")
    make_numbered_clip(path, count=COUNT, fps="24000/1001", profile="3", pix_fmt="yuv422p10le")
    return path


@pytest.fixture(scope="session")
def chroma_clip(tmp_path_factory):
    """422 HQ 유채색(시드 고정 무작위 블록) 48장 — 회색 번호 클립으로는 못 보는 채널 순서(BGR)·색차 경로까지."""
    path = str(tmp_path_factory.mktemp("capture_chroma") / "chroma_422.mov")
    make_chroma_clip(path, count=48, fps="24", profile="3", pix_fmt="yuv422p10le", seed=7)
    return path


@pytest.fixture(scope="session")
def truncated_clip(tmp_path_factory, prores_clip):
    """헤더(faststart)는 멀쩡해 ffprobe는 120장이라 하지만 데이터가 70%에서 끊긴 클립."""
    path = str(tmp_path_factory.mktemp("capture_truncated") / "truncated.mov")
    make_truncated(prores_clip, path, cut_ratio=0.7)
    return path


@pytest.fixture(scope="session")
def audio_first(tmp_path_factory):
    """소리 트랙이 index 0, 영상이 index 1인 422 HQ 120장."""
    path = str(tmp_path_factory.mktemp("capture_audio_first") / "audio_first.mov")
    make_audio_first(path)
    return path


@pytest.fixture
def windows(monkeypatch, qapp):
    """오류 창(error_window.show_window)을 띄우지 않고 (글, 부른 스레드)로 기록. 끝날 때 남은 Qt 이벤트를 비워
    (바꿔치기가 살아 있는 동안) 다른 시험에서 진짜 창이 뜨지 않게."""
    shown = []
    monkeypatch.setattr(error_window, "show_window",
                        lambda text: shown.append(SimpleNamespace(text=text, thread=threading.current_thread())))
    yield shown
    qapp.processEvents()


# ---------------------------------------------------------------- 도구

def open_capture(path):
    return FFmpegPipeCapture(path, probe_movie(path))


def read_until_false(cap):
    """(False, None)이 나올 때까지 읽은 프레임들."""
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            assert frame is None
            return frames
        frames.append(frame)


def wait_for(condition, timeout=WAIT_S):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def use_tcp(monkeypatch):
    """Windows 경로(TCP 리스너)를 이 플랫폼에서: sys.platform을 "win32"로. ffmpeg·ffprobe 경로는 미리 찾아 고정한다 —
    shutil.which가 sys.platform을 보고 .exe(PATHEXT)를 찾으므로 바꾼 뒤에는 못 찾음. probe는 이 함수 전에 할 것."""
    ffmpeg, ffprobe = external_tools.ffmpeg_path(), external_tools.ffprobe_path()
    monkeypatch.setattr(movie_pipe_source, "ffmpeg_path", lambda: ffmpeg)
    monkeypatch.setattr(movie_pipe_source, "ffprobe_path", lambda: ffprobe)
    monkeypatch.setattr(sys, "platform", "win32")


def stand_in_command(script, *args):
    """_pipe_command 자리에 꽂는 ffmpeg 대역: [파이썬, -c, 머리말 + script, 출력 대상, *args] — script는 open_output(sys.argv[1])로
    출력을 열고, args는 sys.argv[2:]."""
    return lambda path, output, seek_seconds=None: [sys.executable, "-c", STAND_IN_PRELUDE + script, output, *args]


def assert_session_gone(session):
    """ffmpeg가 끝나 거둬졌고(종료 코드 있음), 전송 소켓(우리 끝·자식에게 넘긴 끝·리스너)과 stderr 파이프가 닫혔고, 두 스레드가
    끝남 — 좀비·FD·스레드 누수 없음."""
    proc = session.proc
    assert wait_for(lambda: proc.poll() is not None), f"ffmpeg(pid {proc.pid})가 {WAIT_S}초 안에 끝나지 않았습니다"
    assert proc.stdout is None  # ffmpeg 출력은 파이프가 아니라 전송 소켓
    assert wait_for(lambda: session.transport.closed and proc.stderr.closed), "전송 소켓·stderr 파이프가 닫히지 않았습니다"
    for thread in (session.reader, session.stderr_reader):
        thread.join(WAIT_S)
        assert not thread.is_alive(), f"{thread.name} 스레드가 끝나지 않았습니다"


def assert_dead(cap):
    """죽은 cv2 캡처와 같은 겉모습."""
    assert not cap.isOpened()
    assert cap.read() == (False, None)
    assert cap.set(POS, 0) is False
    assert [cap.get(prop) for prop in PROPS] == [0.0] * len(PROPS)


# ---------------------------------------------------------------- cv2 의미

def test_cv2_semantics_parity(prores_clip):
    """열 때 pos 0, 순차 read마다 pos+1, 끝에서 (False, None)·pos 유지(열린 채), release 뒤 isOpened False·get 0.0 —
    같은 파일의 cv2.VideoCapture와 한 걸음씩 같은 값."""
    cap, ref = open_capture(prores_clip), cv2.VideoCapture(prores_clip)
    try:
        assert cap.isOpened() and ref.isOpened()
        assert cap.get(POS) == ref.get(POS) == 0.0
        for i in range(COUNT):
            ok, frame = cap.read()
            ref_ok, _ = ref.read()
            assert ok and ref_ok, i
            assert frame_number(frame) == i
            assert cap.get(POS) == ref.get(POS) == float(i + 1)
        for _ in range(2):  # 끝: 거듭 읽어도 같음
            assert cap.read() == ref.read() == (False, None)
            assert cap.get(POS) == ref.get(POS) == float(COUNT)
            assert cap.isOpened() and ref.isOpened()  # 정상 EOF는 죽음이 아님
    finally:
        cap.release()
        ref.release()
    assert not cap.isOpened() and not ref.isOpened()
    assert [cap.get(prop) for prop in PROPS] == [ref.get(prop) for prop in PROPS] == [0.0] * len(PROPS)
    assert cap.read() == ref.read() == (False, None)
    assert cap.set(POS, 0) is ref.set(POS, 0) is False
    cap.release()  # 두 번 release해도 됨


def test_all_frames_byte_equal_cv2(prores_clip, prores_422_clip, chroma_clip):
    """전 프레임이 cv2와 같은 그림 (스펙 §3b·§5.4 근거의 영구 고정): 4444·422(23.976)·유채색 422. 프레임끼리는 서로 다름.

    프레임 정렬은 늘 완벽, 값 기준은 4:4:4 계열 바이트 완전 동일(BYTE_EXACT) / 4:2:2 계열 최대 |차이| <= TOLERANCE_422.
    422 허용 오차는 사용자 결정(2026-10-29) — 스펙 §5.4.
    """
    # (경로, 번호 클립인가, 허용 최대 |차이|) — 4:4:4 계열 BYTE_EXACT, 4:2:2 계열 TOLERANCE_422
    for path, numbered, allowed in ((prores_clip, True, BYTE_EXACT), (prores_422_clip, True, TOLERANCE_422),
                                    (chroma_clip, False, TOLERANCE_422)):
        expected = read_all_frames(path)
        cap = open_capture(path)
        try:
            frames = read_until_false(cap)
        finally:
            cap.release()
        assert len(frames) == len(expected), path
        assert all(f.shape == (HEIGHT, WIDTH, 3) and f.dtype == np.uint8 for f in frames), path
        assert frame_alignment_problem(expected, frames, numbered) is None, path
        stats = byte_diff_stats(expected, frames)
        assert stats["max_abs"] <= allowed, f"{path}: cv2와의 차이가 허용 오차 {allowed} 초과 - {stats_summary(stats)}"
        assert all(frames[i].tobytes() != frames[i + 1].tobytes() for i in range(len(frames) - 1)), path


def test_read_returns_writable_copy(prores_clip):
    """read()가 준 배열은 호출자 것: 써도 되고, 고쳐도 다음 프레임이 멀쩡하며, 다음 read가 앞서 준 배열을 덮어쓰지 않음."""
    cap = open_capture(prores_clip)
    try:
        frames = []
        for i in range(COUNT):
            ok, frame = cap.read()
            assert ok and frame.flags.writeable and frame.flags.c_contiguous, i
            assert frame_number(frame) == i  # 앞에서 고친 배열이 이 프레임에 새지 않음
            frame[:] = (i * 7 + 3) % 256
            frames.append(frame)
    finally:
        cap.release()
    assert all(int(f.min()) == int(f.max()) == (i * 7 + 3) % 256 for i, f in enumerate(frames))


def test_get_props(prores_clip, prores_422_clip):
    """FPS = float(avg) (cv2와 같은 값 — 23.976도), FRAME_COUNT = nb_frames, 크기 = probe 값. set(POS_FRAMES)는 목표를
    기록해 get이 반영하고(실행은 Task 4), 다른 속성은 False. 모르는 속성은 0.0."""
    for path, rate in ((prores_clip, Fraction(24)), (prores_422_clip, Fraction(24000, 1001))):
        probe = probe_movie(path)
        cap, ref = FFmpegPipeCapture(path, probe), cv2.VideoCapture(path)
        try:
            assert cap.get(cv2.CAP_PROP_FPS) == float(probe.avg) == float(rate) == ref.get(cv2.CAP_PROP_FPS)
            assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == float(probe.nb_frames) == COUNT == ref.get(cv2.CAP_PROP_FRAME_COUNT)
            assert (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (WIDTH, HEIGHT)
            assert (ref.get(cv2.CAP_PROP_FRAME_WIDTH), ref.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (WIDTH, HEIGHT)
            assert cap.get(cv2.CAP_PROP_POS_MSEC) == 0.0
            assert cap.set(cv2.CAP_PROP_FPS, 30) is False
            assert cap.get(cv2.CAP_PROP_FPS) == float(rate)
            assert cap.set(POS, 5) is True
            assert cap.get(POS) == 5.0
        finally:
            cap.release()
            ref.release()


# ---------------------------------------------------------------- 실패 자체 완결 (§5.5)

def test_truncated_dies_loud(truncated_clip, qapp, windows, capsys):
    """꼬리 잘린 클립(ffmpeg는 종료 코드 0으로 일부만 줌): 끊기기 전 프레임은 정확히 주고, 모자란 끝에서 예외 없이 죽음 상태 +
    로그 1회(즉시 — 명령·stderr 전문) + 오류 창 1회(read 안이 아니라 Qt 루프에서). 더 읽어도 다시 알리지 않음."""
    cap = open_capture(truncated_clip)
    try:
        assert cap.isOpened()
        frames = read_until_false(cap)
        assert 0 < len(frames) < COUNT
        assert [frame_number(f) for f in frames] == list(range(len(frames)))
        assert_dead(cap)

        log = capsys.readouterr().err
        assert log.count(FAILURE_HEADLINE) == 1, log
        assert truncated_clip in log and OUTPUT_MARK in log  # 명령
        assert "partial file" in log  # ffmpeg stderr 전문
        assert "test_truncated_dies_loud" in log  # 읽던 곳의 호출 스택

        assert windows == []  # 창은 Qt 루프로 미룸 (read 안에서 모달을 열지 않음)
        qapp.processEvents()
        assert len(windows) == 1
        notice = windows[0]
        assert notice.thread is threading.main_thread()
        assert FAILURE_HEADLINE in notice.text and truncated_clip in notice.text
        assert f"{len(frames)}장" in notice.text  # 원인: 받은 장수
        assert "partial file" in notice.text  # stderr 끝부분
        assert len(notice.text) <= len(notice.text.split("\n\n", 1)[0]) + 2 + error_window.DETAILS_LIMIT

        for _ in range(3):
            assert cap.read() == (False, None)
        cap.release()
        qapp.processEvents()
        assert len(windows) == 1
        assert FAILURE_HEADLINE not in capsys.readouterr().err
    finally:
        cap.release()


@pytest.mark.parametrize("transport", ["native", "tcp"])
def test_kill_mid_read_is_failure_not_eof(prores_clip, transport, qapp, windows, capsys, monkeypatch):
    """밖에서 ffmpeg를 죽이면: 읽기 스레드가 실패를 먼저 알아도 큐에 남은 정상 프레임을 다 준 뒤에야 죽음 상태 — 영상 끝으로
    위장하지 않음. 읽기를 일꾼 스레드에서 해도(전달자 QObject도 거기서 처음 만들어져도) 오류 창은 GUI 스레드의 Qt 루프에서 한 번.

    죽인 뒤에도 전송 소켓에 이미 써 둔 정상 프레임이 몇 장 더 나올 수 있다 — 그 양은 전송·플랫폼마다 다르다(macOS TCP는 커널이
    버퍼를 키워 ~2장). 그래서 버퍼 양에 기대지 않는다: 한 장씩 자리를 내 주며 번호가 끊김 없이 이어지는지 보다가(상한
    READAHEAD + KILL_SLACK장), 읽기 스레드가 끊김에 닿아 끝나는 순간의 큐가 READAHEAD−1~READAHEAD장인지 본다 — 읽기 스레드는 끊긴
    곳에서만 끝나고 그때 큐는 (방금 비운 자리를 들고 있던 장으로 채워) 차 있다. 그 큐를 다 준 뒤에야 죽음. "native"는 이 플랫폼의
    전송(POSIX socketpair), "tcp"는 Windows 경로(TCP 리스너)를 sys.platform 바꿔치기로."""
    monkeypatch.setattr(movie_pipe_source, "_RELAY", None)  # 앞 시험이 GUI 스레드에서 만든 전달자를 쓰지 않게
    probe = probe_movie(prores_clip)
    if transport == "tcp":
        use_tcp(monkeypatch)
    cap = FFmpegPipeCapture(prores_clip, probe)
    try:
        for i in range(10):
            ok, frame = cap.read()
            assert ok and frame_number(frame) == i
        session = cap._session
        assert wait_for(lambda: len(session._frames) == READAHEAD_FRAMES)  # 선읽기 큐가 참 (유한)
        session.proc.kill()
        assert wait_for(lambda: session.proc.poll() is not None)
        expected = 10
        while session.reader.is_alive():  # 전송에 남은 정상 프레임 — 한 장씩 자리를 내 줌
            assert expected < 10 + READAHEAD_FRAMES + KILL_SLACK, f"사망 뒤 {expected - 10}장을 받도록 읽기 스레드가 끝나지 않았습니다"
            ok, frame = cap.read()
            assert ok and frame_number(frame) == expected  # 끊김 없이 이어짐 — 영상 끝으로 위장하지 않음
            expected += 1
            # 읽기 스레드가 빈 자리를 채워 큐가 다시 차거나(살아 있음), 끊김에 닿아 끝날 때까지
            assert wait_for(lambda: len(session._frames) == READAHEAD_FRAMES or not session.reader.is_alive())
        queued = len(session._frames)  # 실패를 적어 둔 채 끝남 — 큐에는 정상 프레임이 남음
        assert READAHEAD_FRAMES - 1 <= queued <= READAHEAD_FRAMES

        result = {}
        worker = threading.Thread(target=lambda: result.update(frames=read_until_false(cap)))
        worker.start()
        worker.join(WAIT_S)
        assert not worker.is_alive()
        frames = result["frames"]
        assert [frame_number(f) for f in frames] == list(range(expected, expected + queued))  # 남은 정상 프레임을 다 받은 뒤 끝
        assert_dead(cap)
        assert capsys.readouterr().err.count(FAILURE_HEADLINE) == 1

        qapp.processEvents()
        assert len(windows) == 1
        assert windows[0].thread is threading.main_thread()
        assert prores_clip in windows[0].text
    finally:
        cap.release()


@pytest.mark.parametrize("claimed", [COUNT - 10, COUNT + 10], ids=["more_frames_than_claimed", "fewer_frames_than_claimed"])
def test_frame_count_mismatch_dies(prores_clip, claimed, qapp, windows, capsys):
    """EOF 불변식 (스펙 §5.3): 받은 수가 nb_frames와 다르면 넘치든 모자라든 정상 끝이 아니라 죽음 — 멀쩡한 스트림이어도.
    (게이트가 nb_frames를 믿을 수 있는 파일만 보내지만, 어긋나면 조용히 끝내지 않음.)"""
    probe = dataclasses.replace(probe_movie(prores_clip), nb_frames=claimed)
    cap = FFmpegPipeCapture(prores_clip, probe)
    try:
        frames = read_until_false(cap)
        assert [frame_number(f) for f in frames] == list(range(min(claimed, COUNT)))
        assert_dead(cap)
        assert capsys.readouterr().err.count(FAILURE_HEADLINE) == 1
        qapp.processEvents()
        assert len(windows) == 1
        assert f"파일의 프레임 수 {claimed}" in windows[0].text
    finally:
        cap.release()


@pytest.mark.parametrize("stderr_text", ["[prores @ 0x1] warning: something odd\n", ""], ids=["stderr", "no_stderr"])
def test_clean_eof_with_stderr_logged_once(tmp_path, monkeypatch, stderr_text, qapp, windows, capsys):
    """정상 끝(종료 코드 0·받은 수 == nb_frames)인데 ffmpeg가 stderr에 글을 남겼으면 그 글을 기록에 한 번 (창 없음, 상태 그대로 —
    가시화만). stderr가 비면 아무것도 남기지 않음. 실제 클립으로는 이 경우를 결정적으로 못 만들어 ffmpeg 대역 프로세스(파이썬:
    번호 프레임 3장 + stderr 글, 종료 코드 0)를 명령 자리에 꽂는다 — 세션·스레드·전송 소켓은 진짜."""
    width, height, count = 4, 2, 3
    script = ("sys.stderr.write(sys.argv[2]); sys.stderr.flush(); out = open_output(sys.argv[1]); "
              f"out.write(b''.join(bytes([i]) * {width * height * 3} for i in range({count}))); out.flush()")
    monkeypatch.setattr(movie_pipe_source, "_pipe_command", stand_in_command(script, stderr_text))
    probe = MovieProbe(codec="prores", width=width, height=height, r=Fraction(24), avg=Fraction(24), nb_frames=count,
                       duration_ts=count * 512, time_base=Fraction(1, 12288), video_start=0.0, format_start=0.0,
                       rotation=0, sar_ok=True)
    path = str(tmp_path / "stand_in.mov")
    cap = FFmpegPipeCapture(path, probe)
    try:
        frames = read_until_false(cap)
        assert [int(f.max()) for f in frames] == list(range(count))
        for _ in range(2):  # 끝에서 거듭 읽어도 한 번만
            assert cap.read() == (False, None)
        assert cap.isOpened() and cap.get(POS) == float(count)  # 정상 끝 — 죽음 아님
    finally:
        cap.release()
    log = capsys.readouterr().err
    if stderr_text:
        assert log.count("ffmpeg stderr:\n") == 1 and path in log  # (대역의 명령 줄에도 글이 있어 글 자체는 세지 않음)
        assert f"ffmpeg stderr:\n{stderr_text.strip()}" in log
    else:
        assert log == ""
    assert FAILURE_HEADLINE not in log
    qapp.processEvents()
    assert windows == []


def test_broken_file_raises_in_ctor(tmp_path, monkeypatch):
    """깨진 파일·없는 파일: 생성자가 PipeCaptureError(명령·stderr 전문)로 실패하고, 띄운 ffmpeg는 거둬지고 전송 소켓·stderr
    파이프도 닫힘. 명령의 출력 대상은 전송 소켓 (POSIX pipe:1 = stdout인 socketpair 끝, Windows tcp://127.0.0.1:<포트>)."""
    probe = MovieProbe(codec="prores", width=WIDTH, height=HEIGHT, r=Fraction(24), avg=Fraction(24), nb_frames=COUNT,
                       duration_ts=COUNT * 512, time_base=Fraction(1, 12288), video_start=0.0, format_start=0.0,
                       rotation=0, sar_ok=True)
    started = []

    class RecordingSession(movie_pipe_source._PipeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(movie_pipe_source, "_PipeSession", RecordingSession)
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    for path, cause in ((str(broken), "Invalid data"), (str(tmp_path / "missing.mov"), "No such file")):
        with pytest.raises(PipeCaptureError) as raised:
            FFmpegPipeCapture(path, probe)
        error = raised.value
        assert error.command[:-1] == [external_tools.ffmpeg_path(), "-nostdin", "-v", "error", "-i", path, "-map",
                                      "0:V:0", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24"]
        assert error.command[-1] == started[-1].transport.output and error.command[-1].startswith(OUTPUT_MARK)
        assert cause in error.stderr
        assert path in str(error) and cause in str(error)
        proc = started[-1].proc
        assert wait_for(lambda: proc.poll() is not None)
        assert proc.stdout is None
        assert wait_for(lambda: started[-1].transport.closed and proc.stderr.closed)
    assert len(started) == 2


def test_release_logs_unsurfaced_failure(prores_clip, windows, qapp, capsys):
    """read가 드러내기 전에 죽은 세션(멈춰 둔 사이 ffmpeg가 죽음 — 선읽기 큐가 차 있어 읽기 스레드는 아직 모름)을 release하면:
    로그 1회로 남기고(창은 없음 — 닫는 영상) 조용히 버리지 않음. 평범한 release는 아무것도 남기지 않음."""
    cap = open_capture(prores_clip)
    session = cap._session
    session.proc.kill()
    assert wait_for(lambda: session.proc.poll() is not None)
    cap.release()
    log = capsys.readouterr().err
    assert log.count("release") == 1 and prores_clip in log and OUTPUT_MARK in log
    assert_session_gone(session)
    cap.release()
    assert capsys.readouterr().err == ""

    cap = open_capture(prores_clip)
    assert cap.read()[0]
    cap.release()
    assert capsys.readouterr().err == ""
    qapp.processEvents()
    assert windows == []


class BrokenStream:
    """쓰기·비우기가 늘 OSError인 stderr 대역 (닫힌 콘솔·꽉 찬 디스크의 기록 파일). writes: 쓰려고 한 횟수."""

    def __init__(self):
        self.writes = 0

    def write(self, text):
        self.writes += 1
        raise OSError(28, "No space left on device")

    def flush(self):
        raise OSError(28, "No space left on device")


@pytest.mark.parametrize("breakage", ["streams", "streams_and_text"])
def test_failure_notice_that_fails_does_not_raise_from_read(tmp_path, monkeypatch, breakage, qapp, windows):
    """§5.5의 마지막 구멍: 도중 실패를 알리는 길마저 실패해도 read()는 예외 없이 (False, None) — 죽은 cv2 캡처 겉모습.
    streams: 기록(sys.stderr)도 원래 stderr(sys.__stderr__ — _last_resort가 쓰는 곳)도 쓰기에 실패. streams_and_text: 거기에 더해
    알릴 글(읽던 곳의 호출 스택)을 만들다 실패 (_die → _last_resort). 대역 ffmpeg는 3장이라던 영상에서 1장만 주고 끝남."""
    width, height, count = 4, 2, 3
    script = f"out = open_output(sys.argv[1]); out.write(bytes({width * height * 3})); out.flush()"
    monkeypatch.setattr(movie_pipe_source, "_pipe_command", stand_in_command(script))
    probe = MovieProbe(codec="prores", width=width, height=height, r=Fraction(24), avg=Fraction(24), nb_frames=count,
                       duration_ts=count * 512, time_base=Fraction(1, 12288), video_start=0.0, format_start=0.0,
                       rotation=0, sar_ok=True)
    cap = FFmpegPipeCapture(str(tmp_path / "stand_in.mov"), probe)
    session = cap._session
    try:
        assert cap.read()[0]
        log, original = BrokenStream(), BrokenStream()
        with monkeypatch.context() as broken:
            broken.setattr(sys, "stderr", log)
            broken.setattr(sys, "__stderr__", original)
            if breakage == "streams_and_text":
                def no_memory():
                    raise MemoryError("시험: 호출 스택 글을 만들 메모리 없음")

                broken.setattr(movie_pipe_source.traceback, "format_stack", no_memory)
            result = cap.read()
        assert result == (False, None)
        assert original.writes >= 1  # 알림 사슬의 끝(_last_resort)까지 갔다가 실패한 쓰기를 삼킴
        assert log.writes == (1 if breakage == "streams" else 0)  # streams_and_text는 기록에 닿기 전에 막힘
        assert_dead(cap)
    finally:
        cap.release()
    assert_session_gone(session)


# ---------------------------------------------------------------- 수명 (§5.6)

def test_release_and_gc_kill_process(prores_clip):
    """release 뒤에도, release 없이 버려 GC된 뒤에도 ffmpeg가 끝나 거둬지고 파이프·스레드가 정리됨."""
    cap = open_capture(prores_clip)
    assert cap.read()[0]
    session = cap._session
    assert session.proc.poll() is None  # 선읽기 큐가 차서 ffmpeg는 살아서 기다리는 중 (끝까지 혼자 가지 못함)
    cap.release()
    assert cap._session is None
    assert_session_gone(session)
    assert session.failure is None  # 일부러 끝낸 프로세스의 끊김은 실패가 아님 (정지 플래그)

    cap = open_capture(prores_clip)
    session = cap._session
    alive = weakref.ref(cap)
    assert session.proc.poll() is None
    del cap
    gc.collect()
    assert alive() is None
    assert_session_gone(session)


def test_audio_first_reads_video(audio_first):
    """소리 트랙이 index 0이어도 -map 0:V:0이 영상 트랙을 읽음 — 번호 순서 정상, 끝은 정상 EOF."""
    cap = open_capture(audio_first)
    try:
        frames = read_until_false(cap)
        assert [frame_number(f) for f in frames] == list(range(COUNT))
        assert cap.isOpened() and cap.get(POS) == float(COUNT)
    finally:
        cap.release()
