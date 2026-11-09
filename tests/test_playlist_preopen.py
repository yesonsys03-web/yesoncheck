"""선택 재생 — 다음 파일 미리 열기 (사용자 요청 2026-11-09: 4K에서 다음 파일로 넘어갈 때의 딜레이를 최소로).

Windows 4K ProRes 선택 재생의 전환 평균 1.10초 중 1.04초가 open_file이고 그 대부분이 캡처 열기(ffprobe 0.12 · 첫 프레임 0.74 — a652652
로그). 지금 파일을 재생하는 동안 뒤 스레드가 다음 파일의 캡처를 열어 두고, 넘어갈 때 그것을 그대로 씀.

① Preopen(yesoncheck/playlist_preopen) — 가짜 opener·가짜 캡처로 받기·기다리기·버리기·실패·닫기 ② 플레이어 — 진짜 VideoPlayer(offscreen)와 진짜
ffmpeg·ProRes 시험 클립으로 선택 재생이 미리 연 캡처를 그대로 쓰는지(넘어갈 때 캡처를 새로 만들지 않음), 멈춤·끝·창 닫기가 닫는지, 파일이
바뀌면 다시 여는지.
"""

import os
import re
import threading
import time

import pytest
from PyQt5.QtWidgets import QApplication

from tests.prores_clips import make_numbered_clip
from tests.test_pipe_player import pipe_log, player  # noqa: F401 (픽스처)
from tests.test_work_paths_ui import new_player  # noqa: F401 (픽스처 — player가 씀)
from yesoncheck import playlist_preopen
from yesoncheck.movie_pipe_source import FFmpegPipeCapture, PipeCaptureError
from yesoncheck.playlist_preopen import Preopen

WAIT_S = 30


class FakeCapture:
    def __init__(self):
        self.released = 0

    def isOpened(self):
        return self.released == 0

    def release(self):
        self.released += 1


def gated_opener(capture, gate):
    """gate가 열릴 때까지 기다렸다 capture를 주는 opener — 부른 경로를 opened에, 문이 열린 뒤 cancelled()를 seen_cancelled에 적음."""
    opened = []
    seen_cancelled = []

    def opener(path, cancelled):
        opened.append(path)
        assert gate.wait(WAIT_S)
        seen_cancelled.append(cancelled())
        return capture

    opener.seen_cancelled = seen_cancelled

    opener.opened = opened
    return opener


@pytest.fixture
def movie(tmp_path):
    path = tmp_path / "next.mov"
    path.write_bytes(b"not really a movie - the fake opener does not read it")
    return str(path)


# ---------------------------------------------------------------- ① Preopen


def test_take_returns_the_capture_opened_in_the_background(movie):
    capture = FakeCapture()
    gate = threading.Event()
    opener = gated_opener(capture, gate)
    preopen = Preopen(movie, opener)  # 만드는 쪽은 막히지 않음 — 문이 닫혀 있어도 곧바로 돌아옴
    assert preopen.wait(0.05) is False
    gate.set()
    assert preopen.wait(WAIT_S)
    assert preopen.take() is capture
    assert opener.opened == [movie]
    assert capture.released == 0  # 받은 쪽(플레이어)의 것


def test_opener_runs_off_the_calling_thread(movie):
    threads = []
    preopen = Preopen(movie, lambda path, cancelled: threads.append(threading.current_thread()) or FakeCapture())
    preopen.take()
    assert threads and threads[0] is not threading.current_thread()


def test_take_waits_for_an_open_still_in_progress(movie):
    """넘어갈 때 아직 열고 있으면(짧은 파일) 끝날 때까지 기다림 — 처음부터 다시 여는 것보다 짧음."""
    capture = FakeCapture()
    gate = threading.Event()
    preopen = Preopen(movie, gated_opener(capture, gate))
    got = []
    taker = threading.Thread(target=lambda: got.append(preopen.take()))
    taker.start()
    time.sleep(0.05)
    assert got == [] and taker.is_alive()  # 아직 여는 중이라 받지 못함
    gate.set()
    taker.join(WAIT_S)
    assert got == [capture]


def test_not_a_pipe_file_gives_none(movie, capsys):
    """opener가 None(파이프로 여는 파일이 아님 — cv2 줄)이면 받을 것이 없음 → 부른 쪽이 예전 방법으로 엶."""
    preopen = Preopen(movie, lambda path, cancelled: None)
    assert preopen.take() is None
    assert f"[미리 열기] 파이프로 여는 파일이 아님 — 넘어갈 때 예전 방법으로 엽니다: next.mov" in capsys.readouterr().out


@pytest.mark.parametrize("error", [PipeCaptureError("ffmpeg가 첫 프레임을 주지 않았습니다", ["ffmpeg"], "stderr"),
                                   FileNotFoundError(2, "No such file")])
def test_expected_failure_is_logged_and_gives_none(movie, capsys, error):
    """파일 쪽 실패(PipeCaptureError·OSError)는 뒤 스레드가 그때 트레이스백째 기록 → 받을 때 None, 넘어갈 때 예전 방법이 같은 오류 창을 냄."""
    def opener(path, cancelled):
        raise error

    preopen = Preopen(movie, opener)
    assert preopen.take() is None
    captured = capsys.readouterr()
    assert "[미리 열기] 열지 못함 — 넘어갈 때 예전 방법으로 다시 엽니다: next.mov" in captured.out
    assert "Traceback" in captured.err and type(error).__name__ in captured.err


def test_unexpected_failure_is_raised_again_by_take(movie, capsys):
    """그 밖의 예외(ToolNotFoundError·코드 버그)는 삼키지 않음 — 받을 때 그 예외를 그대로 냄 (미리 열지 않았을 때 open_file이 내던 길)."""
    error = KeyError("probe에 없는 열쇠")

    def opener(path, cancelled):
        raise error

    preopen = Preopen(movie, opener)
    with pytest.raises(KeyError) as raised:
        preopen.take()
    assert raised.value is error
    captured = capsys.readouterr()
    assert "[미리 열기] 예상하지 못한 오류 — 넘어갈 때 그대로 냅니다: next.mov" in captured.out
    assert "Traceback" in captured.err


def test_file_changed_after_opening_is_discarded(movie, capsys):
    """미리 연 뒤 파일이 바뀌면(다시 렌더해 덮어씀 — 크기·수정 시각) 연 캡처를 놓고 None → 넘어갈 때 새로 엶."""
    capture = FakeCapture()
    preopen = Preopen(movie, lambda path, cancelled: capture)
    assert preopen.wait(WAIT_S)
    stat = os.stat(movie)
    os.utime(movie, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert preopen.take() is None
    assert capture.released == 1
    assert "[미리 열기] 버림 — 미리 연 뒤 파일이 바뀜 (크기·수정 시각): next.mov" in capsys.readouterr().out


def test_file_gone_after_opening_is_discarded(movie, capsys):
    capture = FakeCapture()
    preopen = Preopen(movie, lambda path, cancelled: capture)
    assert preopen.wait(WAIT_S)
    os.remove(movie)
    assert preopen.take() is None
    assert capture.released == 1
    assert "[미리 열기] 버림 — 파일을 확인하지 못함 (FileNotFoundError" in capsys.readouterr().out


def test_cancel_after_opening_releases_at_once(movie, capsys):
    capture = FakeCapture()
    preopen = Preopen(movie, lambda path, cancelled: capture)
    assert preopen.wait(WAIT_S)
    preopen.cancel("선택 재생을 멈춤")
    assert capture.released == 1
    assert "[미리 열기] 닫음 — 선택 재생을 멈춤: next.mov" in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        preopen.take()


def test_cancel_while_opening_releases_when_the_open_finishes(movie):
    """닫는 쪽(GUI 스레드)은 기다리지 않음 — 뒤 스레드가 다 연 즉시 놓음."""
    capture = FakeCapture()
    gate = threading.Event()
    preopen = Preopen(movie, gated_opener(capture, gate))
    started = time.perf_counter()
    preopen.cancel("창을 닫음")
    assert time.perf_counter() - started < 0.5
    assert capture.released == 0
    gate.set()
    assert preopen.wait(WAIT_S)
    assert capture.released == 1


def test_opener_can_see_the_cancel(movie):
    """opener는 cancelled()로 닫혔는지 볼 수 있음 — ffmpeg를 띄우기 전에 보고, 닫혔으면 띄우지 않음(창을 닫은 뒤 일을 하지 않게)."""
    gate = threading.Event()
    opener = gated_opener(None, gate)
    preopen = Preopen(movie, opener)
    preopen.cancel("창을 닫음")
    gate.set()
    assert preopen.wait(WAIT_S)
    assert opener.seen_cancelled == [True]


def test_cancelled_quietly_when_the_opener_gives_up(movie, capsys):
    """닫힌 뒤 opener가 None으로 그만두면 '파이프로 여는 파일이 아님'이라 적지 않음."""
    gate = threading.Event()
    preopen = Preopen(movie, lambda path, cancelled: None if gate.wait(WAIT_S) and cancelled() else FakeCapture())
    preopen.cancel("창을 닫음")
    gate.set()
    assert preopen.wait(WAIT_S)
    assert "파이프로 여는 파일이 아님" not in capsys.readouterr().out


def test_unexpected_error_of_a_cancelled_preopen_says_it_is_dropped(movie, capsys):
    """닫힌 미리 열기의 그 밖의 예외는 넘어갈 때 낼 곳이 없음 — '그대로 냅니다'가 아니라 기록에만 남는다고 적음 (트레이스백은 그대로)."""
    gate = threading.Event()

    def opener(path, cancelled):
        assert gate.wait(WAIT_S)
        raise KeyError("코드 버그")

    preopen = Preopen(movie, opener)
    preopen.cancel("선택 재생을 멈춤")
    gate.set()
    assert preopen.wait(WAIT_S)
    captured = capsys.readouterr()
    assert "[미리 열기] 닫음 — 선택 재생을 멈춤 (예상하지 못한 오류는 위 트레이스백으로만 남음): next.mov" in captured.out
    assert "KeyError" in captured.err


def test_logging_failure_does_not_hang_take(movie, monkeypatch):
    """뒤 스레드가 기록을 쓰다 실패해도(꽉 찬 디스크·닫힌 스트림) 끝 표시는 남겨 take()가 멈추지 않음 — 그 글은 원래 stderr에 한 번
    (코드 검토에서 재현: 예전에는 _done이 서지 않아 넘어갈 때 GUI가 영원히 기다림)."""
    import builtins
    import io
    import sys

    real_print = builtins.print

    def failing_print(*args, **kwargs):
        if threading.current_thread().name.startswith("playlist-preopen"):
            raise OSError(28, "No space left on device")
        return real_print(*args, **kwargs)

    original_stderr = io.StringIO()
    monkeypatch.setattr(builtins, "print", failing_print)
    monkeypatch.setattr(sys, "__stderr__", original_stderr)

    def opener(path, cancelled):
        raise PipeCaptureError("ffmpeg가 첫 프레임을 주지 않았습니다", ["ffmpeg"], "")

    preopen = Preopen(movie, opener)
    assert preopen.wait(5)
    assert preopen.take() is None
    assert "[미리 열기] 기록에 쓰지 못했습니다 — [미리 열기] 열지 못함" in original_stderr.getvalue()
    assert "No space left on device" in original_stderr.getvalue()


def test_cancel_after_take_leaves_the_capture_alone(movie):
    capture = FakeCapture()
    preopen = Preopen(movie, lambda path, cancelled: capture)
    assert preopen.take() is capture
    preopen.cancel("선택 재생이 끝남")
    assert capture.released == 0


def test_take_twice_is_an_error(movie):
    preopen = Preopen(movie, lambda path, cancelled: FakeCapture())
    preopen.take()
    with pytest.raises(RuntimeError):
        preopen.take()


def test_module_has_no_qt():
    """뒤 스레드에서 도는 모듈 — Qt를 불러오지 않음 (opener도 Qt를 건드리지 않는 것을 넘겨야 함)."""
    source = open(playlist_preopen.__file__, encoding="utf-8").read()
    assert "PyQt5" not in source


# ---------------------------------------------------------------- ② 플레이어


SHORT_COUNT = 12


@pytest.fixture(scope="session")
def short_clips(tmp_path_factory):
    """선택 재생용 짧은 ProRes 셋 (12장 24fps — 0.5초씩). 번호 클립이라 파이프 게이트 양성."""
    folder = tmp_path_factory.mktemp("preopen")
    paths = []
    for name in ("s0", "s1", "s2"):
        path = str(folder / f"{name}.mov")
        make_numbered_clip(path, count=SHORT_COUNT, fps="24")
        paths.append(path)
    return paths


def wait_until(predicate, limit_s=WAIT_S):
    start = time.perf_counter()
    while not predicate() and time.perf_counter() - start < limit_s:
        QApplication.processEvents()
        time.sleep(0.0005)
    assert predicate(), "기다린 일이 일어나지 않음"


def start_paused(player, clips):
    """선택 재생을 시작하고 곧바로 Selected Pause — 첫 차례(0.5초)가 미리 열기보다 먼저 끝나 넘어가지 않게 → 다 연 Preopen.
    일시 정지는 미리 연 것을 그대로 둠 (resume으로 이어 재생)."""
    player.add_files_to_sidebar(clips)
    player.sidebar.selectAll()
    player.play_selected_files()
    assert player.is_playlist_playing
    player.toggle_play_pause_selected()
    assert not player.timer.isActive()
    preopen = player._playlist_preopen
    assert preopen is not None and preopen.wait(WAIT_S)
    return preopen


def resume(player):
    player.toggle_play_pause_selected()
    assert player.timer.isActive()


def test_preopen_wanted_only_for_pipe_movies(player, short_clips, monkeypatch):
    """미리 여는 것은 ffmpeg 파이프로 열 영상뿐 — Mac 기본(VideoToolbox — 이미 빠름)·킬 스위치 cv2·시퀀스는 아님."""
    from yesoncheck import player_playback

    assert player._preopen_wanted(short_clips[0]) is True  # conftest: YESONCHECK_MAC_NATIVE=off
    assert player._preopen_wanted("/clips/A001.seq") is False
    monkeypatch.setattr(player_playback, "native_wanted", lambda: True)
    assert player._preopen_wanted(short_clips[0]) is False
    monkeypatch.setattr(player_playback, "native_wanted", lambda: False)
    monkeypatch.setenv("YESONCHECK_MOVIE_SOURCE", "cv2")
    assert player._preopen_wanted(short_clips[0]) is False


def test_play_selected_uses_the_preopened_capture(player, pipe_log, short_clips, capsys, dialogs):  # noqa: F811
    """첫 차례를 재생하기 시작하면 다음 차례를 뒤에서 미리 열고, 넘어갈 때 그 캡처가 그대로 A가 됨 — 넘어갈 때 캡처를 새로 만들지 않음
    (파일 셋 = 캡처 셋). 마지막 차례 뒤에는 미리 열지 않음. 미리 연 캡처도 처음부터 끝까지 바르게 읽힘(EOF 불변식 — 어긋나면 죽음)."""
    capsys.readouterr()
    preopen = start_paused(player, short_clips)
    assert preopen.path == short_clips[1]
    second = preopen._capture
    assert isinstance(second, FFmpegPipeCapture) and second.isOpened()
    resume(player)

    wait_until(lambda: player.current_playlist_index == 1)
    assert player.cap_a is second
    assert player._playlist_preopen is not None and player._playlist_preopen.path == short_clips[2]
    wait_until(lambda: player.current_playlist_index == 2)
    assert player._playlist_preopen is None  # 마지막 차례 — 다음이 없음
    wait_until(lambda: not player.is_playlist_playing)

    assert len(pipe_log.captures) == 3
    out = capsys.readouterr().out
    preopen_lines = [line for line in out.splitlines() if line.startswith("[측정] 미리 열기 ")]
    assert [line.rsplit(" — ", 1)[1] for line in preopen_lines] == ["s1.mov", "s2.mov"]
    assert all(re.search(r"ffprobe [\d.]+ · ffmpeg 시작 [\d.]+ · 첫 프레임 [\d.]+", line) for line in preopen_lines)
    open_lines = [line for line in out.splitlines() if line.startswith("[측정] 열기 ")]
    assert len(open_lines) == 3
    assert "미리 연 캡처 기다림" not in open_lines[0] and "ffprobe" in open_lines[0]  # 첫 차례는 예전처럼 엶
    assert all("미리 연 캡처 기다림" in line and "ffprobe" not in line for line in open_lines[1:])
    played = [line.rsplit(" — ", 1)[1] for line in out.splitlines() if line.startswith(f"[측정] {SHORT_COUNT - 1}장 ")]
    assert played[-2:] == ["s1.mov", "s2.mov"]  # 미리 연 두 파일은 처음부터 끝까지 (첫 파일은 멈춘 때에 따라 장수가 적을 수 있음)
    assert "도중에 실패" not in out


def test_stopping_closes_the_preopened_capture(player, pipe_log, short_clips, dialogs):  # noqa: F811
    second = start_paused(player, short_clips)._capture
    player.stop_video()
    assert player._playlist_preopen is None
    assert not second.isOpened()


def test_closing_the_window_closes_the_preopened_capture(player, pipe_log, short_clips, dialogs):  # noqa: F811
    second = start_paused(player, short_clips)._capture
    player.close()
    assert not second.isOpened()


def test_finishing_the_playlist_leaves_nothing_open(player, pipe_log, short_clips, dialogs):  # noqa: F811
    start_paused(player, short_clips[:2])
    resume(player)
    wait_until(lambda: not player.is_playlist_playing)
    assert player._playlist_preopen is None
    opened = [capture for capture in pipe_log.captures if capture.isOpened()]
    assert opened == [player.cap_a]  # 마지막에 본 영상만 (멈춘 채 열려 있음 — 예전과 같음)


def test_changed_next_file_is_opened_again(player, pipe_log, short_clips, tmp_path, capsys, dialogs):  # noqa: F811
    """미리 연 뒤 다음 파일이 바뀌면(덮어씀) 미리 연 캡처를 버리고 넘어갈 때 새로 엶."""
    clips = [short_clips[0], str(tmp_path / "t_changing.mov")]  # 사이드바가 이름 순으로 정렬 — s0 다음
    with open(short_clips[1], "rb") as source, open(clips[1], "wb") as target:
        target.write(source.read())
    stale = start_paused(player, clips)._capture
    stat = os.stat(clips[1])
    os.utime(clips[1], ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    resume(player)

    wait_until(lambda: player.current_playlist_index == 1)
    assert not stale.isOpened()
    assert player.cap_a is not stale and player.cap_a.isOpened()
    assert len(pipe_log.captures) == 3  # 첫 파일 + 버린 미리 열기 + 다시 연 것
    out = capsys.readouterr().out
    assert "[미리 열기] 버림 — 미리 연 뒤 파일이 바뀜 (크기·수정 시각): t_changing.mov" in out
    wait_until(lambda: not player.is_playlist_playing)


def test_preopen_dropped_when_it_is_no_longer_wanted(player, pipe_log, short_clips, capsys, monkeypatch, dialogs):  # noqa: F811
    """미리 연 뒤 디코더 설정이 바뀌어(Mac 메뉴) 이제 파이프로 열지 않으면 버리고 넘어갈 때 예전 방법으로 엶."""
    stale = start_paused(player, short_clips[:2])._capture
    monkeypatch.setattr(player, "_preopen_wanted", lambda path: False)
    resume(player)

    wait_until(lambda: player.current_playlist_index == 1)
    assert not stale.isOpened()
    assert player.cap_a is not stale
    assert "[미리 열기] 닫음 — 이제 미리 열 파일이 아님 (디코더 설정이 바뀜): s1.mov" in capsys.readouterr().out
    wait_until(lambda: not player.is_playlist_playing)


def gate_background(monkeypatch, name):
    """player_playback의 name(probe_for_open·maybe_pipe_capture)을 뒤 스레드에서만 문 앞에 세움 (GUI 스레드의 열기는 그대로) → 문.
    gate.arrived: 뒤 스레드가 문 앞에 왔음."""
    from yesoncheck import player_playback

    real = getattr(player_playback, name)
    gate = threading.Event()
    gate.arrived = threading.Event()

    def gated(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            gate.arrived.set()
            assert gate.wait(WAIT_S)
        return real(*args, **kwargs)

    monkeypatch.setattr(player_playback, name, gated)
    return gate


def start_running(player, clips):
    """선택 재생을 시작하고 곧바로 멈춤 — 미리 열기는 기다리지 않음(아직 여는 중) → 그 Preopen."""
    player.add_files_to_sidebar(clips)
    player.sidebar.selectAll()
    player.play_selected_files()
    player.toggle_play_pause_selected()
    preopen = player._playlist_preopen
    assert preopen is not None
    return preopen


def test_stop_while_still_opening_releases_when_the_open_finishes(player, pipe_log, short_clips, capsys, monkeypatch, dialogs):  # noqa: F811
    gate = gate_background(monkeypatch, "maybe_pipe_capture")
    preopen = start_running(player, short_clips)
    assert gate.arrived.wait(WAIT_S)  # ffprobe를 마치고 ffmpeg를 띄우러 감 (닫혔는지 본 뒤)
    player.stop_video()
    gate.set()
    assert preopen.wait(WAIT_S)
    assert len(pipe_log.captures) == 2  # 띄운 ffmpeg가 있음 — 다 연 뒤 놓았는지 봄
    assert [capture for capture in pipe_log.captures if capture.isOpened()] == [player.cap_a]
    assert "[미리 열기] 닫음 — 선택 재생을 멈춤: s1.mov" in capsys.readouterr().out


def test_cancel_before_ffmpeg_starts_does_not_start_it(player, pipe_log, short_clips, monkeypatch, dialogs):  # noqa: F811
    """ffprobe 동안 닫히면 ffmpeg를 띄우지 않음 (캡처는 첫 차례 하나뿐)."""
    gate = gate_background(monkeypatch, "probe_for_open")
    preopen = start_running(player, short_clips)
    assert gate.arrived.wait(WAIT_S)
    player.stop_video()
    gate.set()
    assert preopen.wait(WAIT_S)
    assert len(pipe_log.captures) == 1


def test_closing_the_window_waits_briefly_for_an_open_in_progress(player, pipe_log, short_clips, dialogs, monkeypatch):  # noqa: F811
    """창을 닫을 때 여는 중이면 잠깐 기다림 — 끝난 뒤 캡처를 놓아 닫힌 창 뒤에 ffmpeg가 남지 않게."""
    gate = gate_background(monkeypatch, "maybe_pipe_capture")
    preopen = start_running(player, short_clips)
    assert gate.arrived.wait(WAIT_S)
    timer = threading.Timer(0.3, gate.set)
    timer.start()
    player.close()
    timer.join()
    assert preopen.wait(0)
    assert not any(capture.isOpened() for capture in pipe_log.captures)


def test_no_new_preopen_after_the_window_closed(player, short_clips, dialogs):  # noqa: F811
    """창을 닫은 뒤(닫기 중 떠 있던 창의 이벤트 처리 뒤에 선택 재생이 이어져도) 새로 미리 열지 않음."""
    player.close()
    player.playlist = list(short_clips)
    player.current_playlist_index = 0
    player.is_playlist_playing = True
    player._start_playlist_preopen()
    assert player._playlist_preopen is None
    player.is_playlist_playing = False


def test_no_preopen_once_the_playlist_stopped(player, short_clips, dialogs):  # noqa: F811
    player.playlist = list(short_clips)
    player.current_playlist_index = 0
    player.is_playlist_playing = False
    player._start_playlist_preopen()
    assert player._playlist_preopen is None


def test_unexpected_preopen_error_shows_at_the_switch(player, pipe_log, short_clips, monkeypatch, dialogs):  # noqa: F811
    """미리 열기의 그 밖의 예외는 넘어갈 때 그대로 — 예전처럼 'Play Error' 창을 띄우고 다음 차례로 (그 차례는 미리 연 것이 없어 예전처럼 엶)."""
    from yesoncheck import player_playback

    def broken(path, cancelled):
        raise KeyError("코드 버그")

    monkeypatch.setattr(player_playback, "preopen_movie_capture", broken)
    start_paused(player, short_clips)
    resume(player)
    wait_until(lambda: not player.is_playlist_playing)
    errors = [(title, text) for kind, title, text in dialogs.messages if kind == "warning"]
    assert [title for title, _text in errors] == ["Play Error"]  # s1 — s1을 열지 못해 s2는 미리 열리지 않고 예전처럼 열림
    assert "s1.mov" in errors[0][1] and "코드 버그" in errors[0][1]
    assert os.path.basename(player.filename_a) == "s2.mov"


def test_h264_next_file_opens_the_old_way(player, pipe_log, short_clips, tmp_path, capsys, dialogs):  # noqa: F811
    """다음 차례가 파이프로 여는 파일이 아니면(h264 등) 미리 연 것이 없음 → 넘어갈 때 예전처럼 cv2."""
    import cv2

    from tests.conftest import write_test_video

    clips = [short_clips[0], write_test_video(str(tmp_path / "t_h264.mp4"), frames=6)]
    preopen = start_paused(player, clips)
    assert preopen._capture is None
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1)
    assert isinstance(player.cap_a, cv2.VideoCapture)
    assert len(pipe_log.captures) == 1
    assert "[미리 열기] 파이프로 여는 파일이 아님 — 넘어갈 때 예전 방법으로 엽니다: t_h264.mp4" in capsys.readouterr().out
    wait_until(lambda: not player.is_playlist_playing)


@pytest.mark.skipif(os.name == "nt", reason="Windows는 ffmpeg가 연 파일을 지울 수 없음 — 미리 연 다음 파일도 그대로 (알고 둔 비용)")
def test_deleted_next_file_is_skipped_and_its_preopen_closed(player, pipe_log, short_clips, tmp_path, dialogs):  # noqa: F811
    import shutil

    clips = []
    for index, source in enumerate(short_clips):
        clips.append(str(tmp_path / f"d{index}.mov"))
        shutil.copyfile(source, clips[-1])
    stale = start_paused(player, clips)._capture
    os.remove(clips[1])
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1 and os.path.basename(player.filename_a) == "d2.mov")
    assert not stale.isOpened()
    wait_until(lambda: not player.is_playlist_playing)


def test_open_file_returning_before_take_closes_the_preopen(player, pipe_log, short_clips, capsys, monkeypatch, dialogs):  # noqa: F811
    """open_file이 미리 연 것을 받기 전에 돌아가면(프레임 폴더를 읽지 못함 등) 그 캡처를 닫음 — 주인 없이 남지 않게."""
    stale = start_paused(player, short_clips)._capture
    real = player._frame_to_sequence_path
    monkeypatch.setattr(player, "_frame_to_sequence_path",
                        lambda path: None if path.endswith("s1.mov") else real(path))
    resume(player)
    wait_until(lambda: not player.is_playlist_playing)
    assert not stale.isOpened()
    assert "[미리 열기] 닫음 — 이 차례를 열지 못함: s1.mov" in capsys.readouterr().out
