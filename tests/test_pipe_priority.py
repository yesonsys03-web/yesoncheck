"""미리 연 ffmpeg의 낮은 우선순위 (사용자 보고 2026-11-09 — 미리 열기로 넘어갈 때의 딜레이는 사라졌지만 재생 중 FPS가 떨어지고 잠깐
멈췄다 재생됨: Windows 4K 선택 재생 10개 중 미리 열기가 겹친 9개 파일이 0.1~2.2초 늦어지고 최대 간격 120~650ms, 미리 열지 않은 마지막
파일만 끊김 0 — 다음 파일의 ffmpeg가 재생 중인 ffmpeg·GUI와 같은 우선순위로 CPU를 다툼).

고침: 미리 여는 ffmpeg는 Windows에서 BELOW_NORMAL로 띄우고(재생이 쓰고 남는 CPU만), 넘어가는 순간 보통으로 되돌린 뒤 씀. 되돌리지 못하면
버리고 예전처럼 엶(낮은 우선순위로 재생하면 끊김). Windows 밖에서는 바꾸지 않음(POSIX는 낮춘 우선순위를 사용자 권한으로 되돌릴 수 없음).
탐색 재시작·채움기의 세션은 늘 보통. 진짜 Windows 우선순위는 Windows CI에서 psutil로 읽어 봄.
"""

import sys

import psutil
import pytest

from tests.test_pipe_player import pipe_log, player, prores_clip  # noqa: F401 (픽스처)
from tests.test_playlist_preopen import WAIT_S, resume, short_clips, start_paused, wait_until  # noqa: F401 (short_clips: 픽스처)
from tests.test_work_paths_ui import new_player  # noqa: F401 (픽스처 — player가 씀)
from yesoncheck import movie_pipe_source, player_playback
from yesoncheck.movie_pipe_source import (
    BELOW_NORMAL_PRIORITY_CLASS, NORMAL_PRIORITY_CLASS, FFmpegPipeCapture, PipeCaptureError, _popen_kwargs, probe_movie,
)

IS_WINDOWS = sys.platform == "win32"
REAL_PLATFORM = sys.platform
CREATE_NO_WINDOW = 0x08000000
FFMPEG = movie_pipe_source.ffmpeg_path()  # 플랫폼을 바꿔치기한 시험이 쓸 진짜 ffmpeg (찾기가 플랫폼을 봄)


# ---------------------------------------------------------------- 띄우는 옵션


def test_low_priority_flag_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(movie_pipe_source, "subprocess_kwargs", lambda: {"creationflags": CREATE_NO_WINDOW})
    assert _popen_kwargs(low_priority=True) == {"creationflags": CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS}
    assert _popen_kwargs(low_priority=False) == {"creationflags": CREATE_NO_WINDOW}


def test_no_priority_change_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(movie_pipe_source, "subprocess_kwargs", lambda: {})
    assert _popen_kwargs(low_priority=True) == {}


def test_win32_constants():
    assert BELOW_NORMAL_PRIORITY_CLASS == 0x4000 and NORMAL_PRIORITY_CLASS == 0x20
    if IS_WINDOWS:
        assert BELOW_NORMAL_PRIORITY_CLASS == psutil.BELOW_NORMAL_PRIORITY_CLASS
        assert NORMAL_PRIORITY_CLASS == psutil.NORMAL_PRIORITY_CLASS


# ---------------------------------------------------------------- 캡처 (진짜 ffmpeg)


def test_low_priority_capture_reads_and_restores(prores_clip):  # noqa: F811
    """낮은 우선순위로 연 캡처: Windows면 그 ffmpeg가 BELOW_NORMAL, restore_priority() 뒤 NORMAL (True — 바꿈) — 다시 부르면 아무것도 안 함
    (False). 그 밖의 OS는 우선순위를 바꾸지 않고 False. 프레임은 그대로 읽힘."""
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip), low_priority=True)
    try:
        proc = psutil.Process(cap._session.proc.pid)
        if IS_WINDOWS:
            assert proc.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
        else:
            assert proc.nice() == psutil.Process().nice()
        assert cap.restore_priority() is IS_WINDOWS
        if IS_WINDOWS:
            assert proc.nice() == psutil.NORMAL_PRIORITY_CLASS
        assert cap.restore_priority() is False
        ok, frame = cap.read()
        assert ok and frame is not None
    finally:
        cap.release()


def test_normal_capture_has_nothing_to_restore(prores_clip):  # noqa: F811
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip))
    try:
        assert cap.restore_priority() is False
    finally:
        cap.release()


def test_restore_after_a_restart_leaves_the_new_session_alone(prores_clip, monkeypatch):  # noqa: F811
    """처음 세션을 탐색 재시작으로 버렸으면 되돌릴 것이 없음 — 재시작 세션은 늘 보통으로 띄움."""
    calls = []
    probe = probe_movie(prores_clip)  # 플랫폼을 바꾸기 전에 (ffprobe 찾기가 플랫폼을 봄)
    monkeypatch.setattr(movie_pipe_source, "_set_normal_priority", calls.append)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(movie_pipe_source, "_popen_kwargs", lambda low_priority: {})  # 이 OS에서 띄울 수 있게
    monkeypatch.setattr(movie_pipe_source, "ffmpeg_path", lambda: FFMPEG)
    cap = FFmpegPipeCapture(prores_clip, probe, low_priority=True)
    try:
        first = cap._session
        cap.set(movie_pipe_source.cv2.CAP_PROP_POS_FRAMES, 100)
        assert cap.read()[0]
        assert cap._session is not first
        assert cap.restore_priority() is False
        assert calls == []
    finally:
        cap.release()


def test_restore_failure_is_a_pipe_capture_error(prores_clip, monkeypatch):  # noqa: F811
    """되돌리지 못하면(ffmpeg가 이미 끝남·권한) PipeCaptureError(원인 체인) — 부른 쪽이 버리고 예전처럼 엶."""
    def refuse(pid):
        raise psutil.AccessDenied(pid)

    probe = probe_movie(prores_clip)
    monkeypatch.setattr(movie_pipe_source, "_set_normal_priority", refuse)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(movie_pipe_source, "_popen_kwargs", lambda low_priority: {})
    monkeypatch.setattr(movie_pipe_source, "ffmpeg_path", lambda: FFMPEG)
    cap = FFmpegPipeCapture(prores_clip, probe, low_priority=True)
    try:
        with pytest.raises(PipeCaptureError) as raised:
            cap.restore_priority()
        assert isinstance(raised.value.__cause__, psutil.AccessDenied)
    finally:
        cap.release()


# ---------------------------------------------------------------- 플레이어


def test_preopen_asks_for_low_priority(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(player_playback, "probe_for_open", lambda path, mode: object())
    monkeypatch.setattr(player_playback, "maybe_pipe_capture", lambda path, **kwargs: seen.append(kwargs))
    player_playback.preopen_movie_capture(str(tmp_path / "next.mov"), lambda: False)
    assert seen and seen[0]["low_priority"] is True and seen[0]["full_cache"] is True


def test_switch_restores_priority_before_use(player, pipe_log, short_clips, capsys, monkeypatch, dialogs):  # noqa: F811
    """넘어갈 때 미리 연 캡처의 우선순위를 되돌린 뒤 A로 씀 — '[측정] 열기' 줄에 '우선순위 되돌리기' 단계 (바꾼 때만)."""
    restored = []

    def fake_restore(self):
        assert self.cache_mode is None  # 아직 한 장도 읽지 않음 — 첫 화면(첫 read) 전에 되돌림
        restored.append(self)
        return True

    monkeypatch.setattr(FFmpegPipeCapture, "restore_priority", fake_restore)
    second = start_paused(player, short_clips[:2])._capture
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1)
    assert restored == [second] and player.cap_a is second
    open_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[측정] 열기 ")]
    assert "미리 연 캡처 기다림" in open_lines[-1] and "우선순위 되돌리기" in open_lines[-1]
    wait_until(lambda: not player.is_playlist_playing)


def test_switch_discards_a_capture_it_cannot_restore(player, pipe_log, short_clips, capsys, monkeypatch, dialogs):  # noqa: F811
    """되돌리지 못한 캡처로는 재생하지 않음(낮은 우선순위면 끊김) — 기록 뒤 놓고 예전처럼 새로 엶."""
    def refuse(self):
        raise PipeCaptureError("보통 우선순위로 되돌리지 못했습니다", [], "")

    monkeypatch.setattr(FFmpegPipeCapture, "restore_priority", refuse)
    stale = start_paused(player, short_clips[:2])._capture
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1)
    assert not stale.isOpened()
    assert player.cap_a is not stale and player.cap_a.isOpened()
    captured = capsys.readouterr()
    assert "[미리 열기] 버림 — 미리 연 ffmpeg를 보통 우선순위로 되돌리지 못함: s1.mov" in captured.out
    assert "PipeCaptureError" in captured.err
    wait_until(lambda: not player.is_playlist_playing)


def recording_popen_kwargs(monkeypatch):
    """_popen_kwargs의 low_priority 인자를 띄운 차례대로 적음 (진짜 값을 그대로 돌려줌) → 목록."""
    calls = []
    real = movie_pipe_source._popen_kwargs

    def record(low_priority):
        calls.append(low_priority)
        return real(low_priority)

    monkeypatch.setattr(movie_pipe_source, "_popen_kwargs", record)
    return calls


def test_only_the_preopen_spawns_low_and_the_switch_restores_it(player, pipe_log, short_clips, monkeypatch, dialogs):  # noqa: F811
    """끝까지 이어진 길: 첫 차례는 보통, 미리 여는 다음 차례만 낮게 띄움(maybe_pipe_capture → FFmpegPipeCapture → _PipeSession로 플래그가 감).
    Windows면 진짜 우선순위도 — 미리 연 동안 BELOW_NORMAL, 넘어간 뒤 NORMAL (Windows CI)."""
    calls = recording_popen_kwargs(monkeypatch)
    second = start_paused(player, short_clips[:2])._capture
    assert calls == [False, True]
    proc = psutil.Process(second._session.proc.pid)
    if IS_WINDOWS:
        assert proc.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1)
    assert player.cap_a is second
    if IS_WINDOWS:
        assert proc.nice() == psutil.NORMAL_PRIORITY_CLASS
    wait_until(lambda: not player.is_playlist_playing)


def test_restart_sessions_spawn_at_normal_priority(prores_clip, monkeypatch):  # noqa: F811
    """낮게 연 캡처도 탐색 재시작이 띄우는 세션은 보통 (재시작은 플래그를 넘기지 않음)."""
    calls = recording_popen_kwargs(monkeypatch)
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip), low_priority=True)
    try:
        cap.set(movie_pipe_source.cv2.CAP_PROP_POS_FRAMES, 100)
        assert cap.read()[0]
        assert calls == [True, False]
    finally:
        cap.release()


def test_restore_skips_an_ffmpeg_that_already_finished(tmp_path, monkeypatch):
    """아주 짧은 파일은 미리 여는 동안 ffmpeg가 다 내보내고 끝남 — 되돌릴 것이 없음(False, 버리지 않음). 예전에는 psutil이 끝난 프로세스에서
    실패해 멀쩡한 캡처를 버리고 다시 열었을 것 (코드 검토)."""
    from tests.prores_clips import make_numbered_clip

    clip = str(tmp_path / "tiny.mov")
    make_numbered_clip(clip, count=3)
    cap = FFmpegPipeCapture(clip, probe_movie(clip), low_priority=True)
    try:
        cap._session.proc.wait(WAIT_S)  # 3장은 큐·소켓에 다 들어가 ffmpeg가 끝남
        calls = []
        monkeypatch.setattr(movie_pipe_source, "_set_normal_priority", calls.append)
        monkeypatch.setattr(sys, "platform", "win32")
        assert cap.restore_priority() is False
        assert calls == []
    finally:
        monkeypatch.setattr(sys, "platform", REAL_PLATFORM)  # 놓는 길(전송 소켓)은 연 플랫폼 그대로
        cap.release()


def test_restore_failure_after_ffmpeg_finished_is_not_an_error(prores_clip, monkeypatch):  # noqa: F811
    """되돌리는 사이에 ffmpeg가 끝나 psutil이 실패해도(NoSuchProcess) 끝났으면 되돌릴 것이 없을 뿐 — False."""
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip), low_priority=True)
    try:
        proc = cap._session.proc

        def vanish(pid):
            proc.kill()
            proc.wait(WAIT_S)
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(movie_pipe_source, "_set_normal_priority", vanish)
        monkeypatch.setattr(sys, "platform", "win32")
        assert cap.restore_priority() is False
    finally:
        monkeypatch.setattr(sys, "platform", REAL_PLATFORM)  # 놓는 길(전송 소켓)은 연 플랫폼 그대로
        cap.release()


def test_hold_idle_fill_marks_the_process_busy():
    """미리 연 것을 기다리는 동안 채움기가 쉬는 줄 알지 않게 — 프로세스 시계를 read 중으로."""
    clock = movie_pipe_source._PROCESS_READS
    before = clock.busy
    with movie_pipe_source.hold_idle_fill():
        assert clock.busy == before + 1
        assert clock.idle_for() == 0.0
    assert clock.busy == before


def test_switch_waiting_on_an_unfinished_preopen_holds_idle_fill(player, pipe_log, short_clips, monkeypatch, dialogs):  # noqa: F811
    """넘어갈 때 아직 여는 중이면 GUI가 기다림 — 그동안 나가는 파일의 채움기(보통 우선순위, 8스레드)가 '쉬는 때'로 보고 시작하면 낮은
    우선순위의 미리 열기를 굶김(코드 검토) → 기다리는 동안 프로세스 시계를 read 중으로 잡음."""
    import threading

    from tests.test_playlist_preopen import gate_background, start_running
    from yesoncheck import playlist_preopen

    gate = gate_background(monkeypatch, "maybe_pipe_capture")
    waiting = threading.Event()
    real_take = playlist_preopen.Preopen.take

    def take(self):
        waiting.set()
        return real_take(self)

    monkeypatch.setattr(playlist_preopen.Preopen, "take", take)
    seen = []

    def release_when_waiting():
        assert waiting.wait(WAIT_S)
        seen.append(movie_pipe_source._PROCESS_READS.busy)
        gate.set()

    start_running(player, short_clips[:2])
    helper = threading.Thread(target=release_when_waiting)
    helper.start()
    resume(player)
    wait_until(lambda: player.current_playlist_index == 1)
    helper.join(WAIT_S)
    assert seen and seen[0] >= 1
    wait_until(lambda: not player.is_playlist_playing)
