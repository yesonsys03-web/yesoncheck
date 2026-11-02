"""ffmpeg 파이프 캡처의 전체 프레임 캐시 (yesoncheck/movie_pipe_source.py — 스펙 §6): opt-in(full_cache=True)한 캡처가 첫 read에서
예산을 판정해 파일의 모든 프레임을 보관하면 되감기·탐색이 재시작 없이 보관본에서 나온다. 판정·장부(_LEDGER)·기록 한 줄·킬 스위치
(YESONCHECK_FRAME_CACHE=ring)·release/죽음/GC의 장부 반환을 본다.

conftest가 YESONCHECK_FRAME_CACHE=ring을 두므로 전체 보관을 보는 시험은 auto를 명시한다(auto_mode). 어느 경로를 탔는지는 시간이 아니라
세션(ffmpeg 프로세스) 수·pid로 실증한다 (클립·세션 도우미는 test_movie_pipe_seek에서). 장부 단언은 시험 시작 때의 값(base) 대비 —
다른 시험이 남긴 캡처가 잠깐 살아 있어도 흔들리지 않게.
"""

import os
import pytest
from tests.prores_clips import frame_number
from tests.test_movie_pipe_seek import prores_clip, two_frame_clip, sessions, windows, pid, read_number, random_targets, assert_dead  # noqa: F401
from yesoncheck import frame_cache_budget, movie_pipe_source, sequence_source
from yesoncheck.movie_pipe_source import FRAME_CACHE_ENV, KEEP_BEHIND, FFmpegPipeCapture, maybe_pipe_capture, probe_movie

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

def test_ring_mode_when_not_opted_in(auto_mode, prores_clip, sessions):
    cap = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip))  # full_cache 기본 False
    for _ in range(KEEP_BEHIND + 5):
        cap.read()
    assert cap.cache_mode == "ring"
    cap.set(1, 0)
    cap.read()
    assert len(sessions) == 2  # 링 밖 → 재시작 (지금과 같음)
    cap.release()

def test_open_any_capture_is_ring(auto_mode, prores_clip):
    cap = sequence_source.open_any_capture(prores_clip)
    cap.read()
    assert isinstance(cap, FFmpegPipeCapture) and cap.cache_mode == "ring"
    cap.release()

def test_kill_switch_forces_ring(monkeypatch, prores_clip):
    monkeypatch.setenv(FRAME_CACHE_ENV, "ring")
    cap = open_full(prores_clip)
    cap.read()
    assert cap.cache_mode == "ring"
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

def test_restart_in_full_mode_keeps_store(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    for _ in range(20):
        cap.read()
    cap.set(1, 100); cap.read()  # 재시작
    assert len(sessions) == 2 and cap._store.has(5)
    cap.set(1, 5)
    assert read_number(cap) == 5 and len(sessions) == 2
    cap.release()
