"""ffmpeg 파이프 캡처의 전체 프레임 캐시 (yesoncheck/movie_pipe_source.py — 스펙 §6): opt-in(full_cache=True)한 캡처가 첫 read에서
예산을 판정해 파일의 모든 프레임을 보관하면 되감기·탐색이 재시작 없이 보관본에서 나온다. 판정·장부(_LEDGER)·기록 한 줄·킬 스위치
(YESONCHECK_FRAME_CACHE=ring)·release/죽음/GC의 장부 반환을 본다.

conftest가 YESONCHECK_FRAME_CACHE=ring을 두므로 전체 보관을 보는 시험은 auto를 명시한다(auto_mode). 어느 경로를 탔는지는 시간이 아니라
세션(ffmpeg 프로세스) 수·pid로 실증한다 (클립·세션 도우미는 test_movie_pipe_seek에서). 장부 단언은 시험 시작 때의 값(base) 대비 —
다른 시험이 남긴 캡처가 잠깐 살아 있어도 흔들리지 않게.
"""

import os
import threading
import traceback
from types import SimpleNamespace

import pytest
from tests.test_movie_pipe_seek import prores_clip, sessions, windows, pid, read_number, random_targets, assert_dead  # noqa: F401
from tests.test_movie_pipe_seek import assert_session_gone, voff_clip  # noqa: F401 (voff_clip: fixture)
from yesoncheck import external_tools, frame_cache_budget, movie_pipe_source, sequence_source
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, FRAME_CACHE_ENV, KEEP_BEHIND, FFmpegPipeCapture, probe_movie,
)

ESCAPE_HINT = "탈출구: YESONCHECK_FRAME_CACHE=ring (psutil을 부르지 않음)"  # 판정 실패 사유 끝 (FRAME_CACHE_ESCAPE_HINT — 글 그대로 고정)

GB = 1024**3

@pytest.fixture
def auto_mode(monkeypatch):
    monkeypatch.setenv(FRAME_CACHE_ENV, "auto")
    monkeypatch.setattr(frame_cache_budget, "memory_snapshot", lambda: (128 * GB, 100 * GB))

def open_full(path):
    return FFmpegPipeCapture(path, probe_movie(path), full_cache=True)

def test_decision_happens_on_first_read_not_in_constructor(auto_mode, prores_clip):
    cap = open_full(prores_clip)
    assert cap.cache_mode is None
    assert read_number(cap) == 0 and cap.cache_mode == "full"
    cap.release()

def test_full_mode_replays_every_seen_frame_without_restart(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    count = int(cap.get(7))  # CAP_PROP_FRAME_COUNT
    numbers = [read_number(cap) for _ in range(count)]
    assert numbers == list(range(count)) and len(sessions) == 1
    first = pid(cap)
    for n in random_targets(11, count, 40):  # (seed, 프레임 수, 목표 수) — test_movie_pipe_seek의 시그니처
        cap.set(1, n)  # CAP_PROP_POS_FRAMES
        assert read_number(cap) == n
    assert len(sessions) == 1 and pid(cap) == first
    cap.release()

def test_rewind_after_eof_replays_from_store(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    count = int(cap.get(7))
    for _ in range(count):
        cap.read()
    assert cap.read() == (False, None) and int(cap.get(1)) == count  # EOF: cv2 계약 그대로
    cap.set(1, 0)
    assert [read_number(cap) for _ in range(count)] == list(range(count)) and len(sessions) == 1
    cap.release()

def test_stream_first_keeps_lockstep_after_rewind(auto_mode, prores_clip, sessions):
    """100~200 격인 구간을 본 뒤 앞으로 되감아 재생: 보관 구간을 지나도 재시작이 없다 (스트림 우선)."""
    cap = open_full(prores_clip)
    cap.set(1, 40)
    for _ in range(30):  # 40..69 보관, 스트림 70
        cap.read()
    restarts = len(sessions)
    cap.set(1, 0)  # 링 밖 뒤 → 재시작 1회
    for n in range(0, 90):
        assert read_number(cap) == n
    assert len(sessions) == restarts + 1  # 70..89로 넘어갈 때 추가 재시작 없음
    cap.release()

def test_leaving_a_cached_segment_restarts_exactly_once(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    for _ in range(60):  # 0..59 보관, 스트림 60
        cap.read()
    cap.set(1, 100)      # 재시작 → 100.., 스트림 101
    assert read_number(cap) == 100
    cap.set(1, 30)       # 보관본
    restarts = len(sessions)
    for n in range(30, 60):
        assert read_number(cap) == n
    assert read_number(cap) == 60 and len(sessions) == restarts + 1  # 60은 보관되지 않았고 스트림은 101 → 재시작 1회
    assert read_number(cap) == 61 and len(sessions) == restarts + 1
    cap.release()

def test_ring_mode_when_not_opted_in(auto_mode, prores_clip, sessions, capsys):
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip))  # full_cache 기본 False
    for _ in range(KEEP_BEHIND + 5):
        cap.read()
    assert cap.cache_mode == "ring"
    assert "프레임 캐시" not in capsys.readouterr().out  # opt-in하지 않은 캡처는 기록 없음 (스펙 §6 — 1.5.1과 같은 경로)
    cap.set(1, 0)
    cap.read()
    assert len(sessions) == 2  # 링 밖 → 재시작 (지금과 같음)
    cap.release()

def test_open_any_capture_is_ring(auto_mode, prores_clip):
    cap = sequence_source.open_any_capture(prores_clip)
    cap.read()
    assert isinstance(cap, FFmpegPipeCapture) and cap.cache_mode == "ring"
    cap.release()

def test_kill_switch_forces_ring(monkeypatch, prores_clip, capsys):
    monkeypatch.setenv(FRAME_CACHE_ENV, "ring")
    cap = open_full(prores_clip)
    cap.read()
    assert cap.cache_mode == "ring"
    assert "프레임 캐시" not in capsys.readouterr().out  # 킬 스위치도 기록 없음
    cap.release()

def test_full_mode_logs_one_line(auto_mode, prores_clip, capsys):
    cap = open_full(prores_clip)
    cap.read(); cap.read()
    out = capsys.readouterr().out
    assert out.count("[파이프] 프레임 캐시: 전체") == 1 and os.path.basename(prores_clip) in out
    cap.release()

def test_second_capture_falls_back_to_ring_when_budget_is_used(monkeypatch, prores_clip, capsys):
    monkeypatch.setenv(FRAME_CACHE_ENV, "auto")
    probe = probe_movie(prores_clip)
    one_file = probe.width * probe.height * 3 * probe.nb_frames
    base = movie_pipe_source._LEDGER.committed()  # 다른 시험이 잠깐 남긴 전체 보관만큼 예산을 얹음 (순서 무관)
    budget_ram = int((base + one_file * 1.5) / 0.20)  # 예산 = 파일 1.5개분 (+ base)
    monkeypatch.setattr(frame_cache_budget, "memory_snapshot", lambda: (budget_ram, 10**12))
    a = open_full(prores_clip); b = open_full(prores_clip)
    a.read(); b.read()
    assert a.cache_mode == "full" and b.cache_mode == "ring"
    assert "[파이프] 프레임 캐시: 링 8장 — 파일" in capsys.readouterr().out
    a.release()
    c = open_full(prores_clip); c.read()
    assert c.cache_mode == "full"  # a가 놓은 예산을 c가 씀
    b.release(); c.release()

def test_ledger_is_returned_on_release_death_and_gc(auto_mode, prores_clip):
    ledger = movie_pipe_source._LEDGER
    base = ledger.committed()
    a = open_full(prores_clip); a.read()
    assert ledger.committed() > base
    a.release()
    assert ledger.committed() == base
    b = open_full(prores_clip); b.read()
    del b
    import gc; gc.collect()
    assert ledger.committed() == base

def test_death_clears_store_and_keeps_dead_contract(auto_mode, prores_clip, windows, capsys):  # windows: test_movie_pipe_seek 픽스처
    base = movie_pipe_source._LEDGER.committed()
    cap = open_full(prores_clip)
    for _ in range(10):
        cap.read()
    cap._session.proc.kill()
    while cap.read()[0]:  # 큐에 남은 정상 프레임을 다 준 뒤 죽음
        pass
    assert_dead(cap)  # isOpened False·read (False, None)·get 0.0·set False
    assert len(cap._store) == 0 and movie_pipe_source._LEDGER.committed() == base

def test_voff_seek_full_mode_replays_from_store(auto_mode, voff_clip, sessions, capsys):
    """영상 트랙 start 0.5s 파일의 전체 모드 탐색 (test_movie_pipe_seek::test_voff_seek_offset_corrected의 전체 모드 갈래): 30장 재생한 뒤
    본 구간 안의 무작위 탐색은 전부 보관본(세션 수 불변)이고 번호가 정확, 본 구간 밖으로의 탐색 하나는 트랙 오프셋을 보정한 -ss
    재시작 한 번으로 정확히 착지하고 그 뒤는 새 스트림에서 이어짐."""
    probe = probe_movie(voff_clip)
    assert probe.video_start - probe.format_start == pytest.approx(0.5)  # 전제: 오프셋이 있는 파일
    cap = open_full(voff_clip)
    try:
        assert [read_number(cap) for _ in range(30)] == list(range(30))
        assert cap.cache_mode == "full" and len(sessions) == 1
        for n in random_targets(7, 30, 20):  # 0..29 — 0과 마지막 두 장(28·29) 포함
            assert cap.set(1, n) is True
            assert read_number(cap) == n, f"목표 {n}"
        assert len(sessions) == 1, "본 구간으로의 탐색이 ffmpeg를 다시 띄움"
        assert cap.set(1, 100) is True  # 본 구간 밖이고 스트림(30)에서 24장보다 멀리 — 재시작
        assert read_number(cap) == 100 and len(sessions) == 2
        assert [read_number(cap) for _ in range(3)] == [101, 102, 103] and len(sessions) == 2
    finally:
        cap.release()
    assert FAILURE_HEADLINE not in capsys.readouterr().err

def test_restart_in_full_mode_keeps_store(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    for _ in range(20):
        cap.read()
    cap.set(1, 100); cap.read()  # 재시작
    assert len(sessions) == 2 and cap._store.has(5)
    cap.set(1, 5)
    assert read_number(cap) == 5 and len(sessions) == 2
    cap.release()

def test_backward_restart_prefill_is_kept_in_full_mode(auto_mode, prores_clip, sessions):
    """전체 모드의 뒤로 재시작도 목표 8장 앞에서 띄우고, 미리 채운 8장이 링처럼 밀려나지 않고 모두 남는다: 0..9를 본 뒤 100으로(앞으로 —
    미리 채우지 않음) 갔다가 본 적 없는 80으로 ← 방향 재시작 → 시작 72, 72..80이 모두 보관 → ← 8번(79..72)은 재시작 없이, 71은 재시작."""
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(10)] == list(range(10)) and cap.cache_mode == "full"
        cap.set(1, 100)
        assert read_number(cap) == 100 and len(sessions) == 2 and cap._session.start == 100
        cap.set(1, 80)
        assert read_number(cap) == 80 and len(sessions) == 3
        assert cap._session.start == 80 - KEEP_BEHIND
        assert set(range(80 - KEEP_BEHIND, 81)) <= set(cap._store.indices())  # 72..80 모두 (밀려나지 않음)
        for n in range(79, 79 - KEEP_BEHIND, -1):  # ← 8번: 79..72
            cap.set(1, n)
            assert read_number(cap) == n and len(sessions) == 3, f"← {n}"
        cap.set(1, 80 - KEEP_BEHIND - 1)  # 71: 본 적 없음 → 재시작
        assert read_number(cap) == 71 and len(sessions) == 4 and cap._session.start == 71 - KEEP_BEHIND
    finally:
        cap.release()


def test_budget_failure_dies_loudly_instead_of_raising(monkeypatch, prores_clip, qapp, windows, capsys):
    """첫 read의 캐시 판정이 실패(psutil 오류)해도 read는 예외를 내지 않는다 (§5.5 — 재생 타이머 슬롯에는 try가 없어 PyQt5가 프로세스를
    끝냄): 도중 실패(B)와 같이 그 read가 (False, None), 죽은 cv2 캡처 겉모습, 기록 한 번(트레이스백째), 오류 창 한 번, 세션 정리, 장부 그대로.
    사유 끝의 탈출구 안내(킬 스위치)가 기록과 오류 창 둘 다에 실림."""
    monkeypatch.setenv(FRAME_CACHE_ENV, "auto")

    def broken_snapshot():
        raise OSError("psutil 시험용 실패")

    monkeypatch.setattr(frame_cache_budget, "memory_snapshot", broken_snapshot)
    base = movie_pipe_source._LEDGER.committed()
    cap = open_full(prores_clip)
    session = cap._session
    assert cap.read() == (False, None)
    assert_dead(cap)
    log = capsys.readouterr().err
    assert log.count(FAILURE_HEADLINE) == 1, log
    assert "프레임 캐시 예산을 정하지 못했습니다" in log and "Traceback" in log and "OSError: psutil 시험용 실패" in log
    assert prores_clip in log
    assert f"OSError: psutil 시험용 실패\n{ESCAPE_HINT}" in log  # 트레이스백 바로 다음 줄
    qapp.processEvents()
    assert len(windows) == 1 and FAILURE_HEADLINE in windows[0].text and ESCAPE_HINT in windows[0].text
    assert cap.read() == (False, None)  # 죽은 뒤의 read는 다시 알리지 않음
    qapp.processEvents()
    assert len(windows) == 1 and FAILURE_HEADLINE not in capsys.readouterr().err
    assert_session_gone(session)
    assert movie_pipe_source._LEDGER.committed() == base
    cap.release()

def format_exc_failing_on(thread):
    """movie_pipe_source.traceback.format_exc 자리에 꽂을 것: thread(read를 부르는 시험 스레드)에서만 실패하고 다른 스레드에서는 진짜
    format_exc — 바꿔치기는 모듈 전역이라 모든 스레드가 보는데, 죽음 전이가 멈추는 세션의 읽기 스레드는 소켓이 닫힌 뒤 recv가 EBADF를
    받아 실패 원인 글로 format_exc를 부를 수 있다(정지된 세션이라 그 실패는 버려짐). 거기서 터지면 읽기 스레드의 처리되지 않은 예외
    (PytestUnhandledThreadExceptionWarning, 25번에 2번꼴로 재현)가 되므로 겨누는 곳을 read 안의 사유 글로 좁힌다."""

    def format_exc():
        if threading.current_thread() is not thread:
            return traceback.format_exc()
        raise RuntimeError("사유 글 만들기 시험용 실패")

    return format_exc


def test_reason_assembly_failure_still_dies_without_raising(monkeypatch, prores_clip, qapp, windows, capsys):
    """판정 실패의 사유 글을 만들다(traceback.format_exc) 또 실패해도 — _die가 알릴 글을 지키는 것과 같이 — read는 예외를 내지 않고
    고정 사유 + 원래 예외 한 줄로 죽는다 (도중 실패 B와 같음: (False, None)·죽은 겉모습·기록 한 번·오류 창 한 번·세션 정리·장부 그대로)."""
    monkeypatch.setenv(FRAME_CACHE_ENV, "auto")

    def broken_snapshot():
        raise OSError("psutil 시험용 실패")

    broken_format_exc = format_exc_failing_on(threading.current_thread())
    monkeypatch.setattr(frame_cache_budget, "memory_snapshot", broken_snapshot)
    # traceback 모듈 전체가 아니라 movie_pipe_source가 읽는 이름만 바꿈 (format_stack은 _die가 씀)
    monkeypatch.setattr(movie_pipe_source, "traceback",
                        SimpleNamespace(format_exc=broken_format_exc, format_stack=traceback.format_stack))
    base = movie_pipe_source._LEDGER.committed()
    cap = open_full(prores_clip)
    session = cap._session
    assert cap.read() == (False, None)  # 예외가 read 밖으로 나가지 않음
    assert_dead(cap)
    log = capsys.readouterr().err
    assert log.count(FAILURE_HEADLINE) == 1, log
    assert "프레임 캐시 예산을 정하지 못했습니다 (원인 글을 만들지 못했습니다)" in log and prores_clip in log
    assert "OSError: psutil 시험용 실패" in log  # 고정 사유에 원래 예외 한 줄
    assert f"OSError: psutil 시험용 실패\n{ESCAPE_HINT}" in log  # 그 다음 줄에 탈출구 안내
    qapp.processEvents()
    assert len(windows) == 1 and FAILURE_HEADLINE in windows[0].text and ESCAPE_HINT in windows[0].text
    assert_session_gone(session)
    assert movie_pipe_source._LEDGER.committed() == base
    cap.release()


def test_restart_reason_assembly_failure_still_dies_without_raising(monkeypatch, prores_clip, qapp, windows, capsys):
    """탐색 재시작에서 새 ffmpeg를 못 띄운 사유 글을 만들다(traceback.format_exc) 또 실패해도 — 위 판정 실패의 지킴과 같이 — read는
    예외를 내지 않고 고정 사유 + 원래 예외 한 줄로 죽는다 (도중 실패 B: (False, None)·죽은 겉모습·옛 세션 정리·기록 한 번·오류 창 한 번).
    캐시 판정과 무관한 길이라 링(opt-in 안 함)으로 본다."""
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip))
    try:
        assert read_number(cap) == 0  # 첫 read(판정)는 바꿔치기 전에
        old = cap._session

        def broken_command(path, output, seek_seconds=None):
            raise external_tools.ToolNotFoundError("ffmpeg를 찾지 못했습니다 (시험)")

        broken_format_exc = format_exc_failing_on(threading.current_thread())
        monkeypatch.setattr(movie_pipe_source, "_pipe_command", broken_command)
        monkeypatch.setattr(movie_pipe_source, "traceback",
                            SimpleNamespace(format_exc=broken_format_exc, format_stack=traceback.format_stack))
        assert cap.set(1, 100) is True  # 링·앞 24장 밖 — 재시작
        assert cap.read() == (False, None)  # 예외가 read 밖으로 나가지 않음
        assert_dead(cap)
        assert_session_gone(old)
        log = capsys.readouterr().err
        assert log.count(FAILURE_HEADLINE) == 1, log
        assert "100번 프레임으로 탐색하려고 ffmpeg를 다시 띄우지 못했습니다 (원인 글을 만들지 못했습니다)" in log
        assert "ToolNotFoundError: ffmpeg를 찾지 못했습니다 (시험)" in log and prores_clip in log
        qapp.processEvents()
        assert len(windows) == 1 and FAILURE_HEADLINE in windows[0].text
    finally:
        cap.release()


def test_fallback_reason_appends_original_error_or_keeps_fixed_text():
    """고정 사유 + 원래 예외 한 줄; 그 한 줄마저 만들지 못하면(__str__ 실패) 고정 사유만 — 예외 없음."""
    assert movie_pipe_source._fallback_reason("고정 사유", OSError("원인")) == "고정 사유\nOSError: 원인"

    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError("글 만들기 실패")

    assert movie_pipe_source._fallback_reason("고정 사유", Unprintable()) == "고정 사유"
