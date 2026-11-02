"""ffmpeg 파이프 캡처의 전체 프레임 캐시 (yesoncheck/movie_pipe_source.py — 스펙 §6·§6.5): opt-in(full_cache=True)한 캡처가 첫 read에서
예산을 판정해 전체 모드가 되면, 읽는 동안은 링(8장)만 두고 read가 IDLE_FILL_DELAY_S 동안 없을 때 채움기(_Filler — 자기 ffmpeg 세션)가
처음부터 전체 저장소(_full)를 채운다 — 다 차면 되감기·탐색이 재시작 없이 보관본에서 나온다. 판정·장부(_LEDGER)·기록 한 줄·킬 스위치
(YESONCHECK_FRAME_CACHE=ring)·release/죽음/GC의 장부 반환과 채움기 정지·채움기는 쉬는 때만·채움 실패는 기록만을 본다.

conftest가 YESONCHECK_FRAME_CACHE=ring을 두므로 전체 보관을 보는 시험은 auto를 명시한다(auto_mode). 어느 경로를 탔는지는 시간이 아니라
세션(ffmpeg 프로세스) 수·pid로 실증한다 (클립·세션 도우미는 test_movie_pipe_seek에서) — 재시작 횟수는 주 세션(main_sessions)으로, 채움기
세션(is_filler)은 따로 센다. 채움 전의 동작은 채움기를 붙잡아 두고(hold_fill — 쉬는 때 기준을 한 시간으로) 보고, 채우는 도중의 동작은
채움기의 _keep 앞에 문을 달아(fill_gate) 정해진 장에서 멈춰 세워 본다 — 시간에 기대지 않게. 장부 단언은 시험 시작 때의 값(base) 대비 —
다른 시험이 남긴 캡처가 잠깐 살아 있어도 흔들리지 않게.
"""

import contextlib
import gc
import os
import threading
import time
import traceback
from types import SimpleNamespace

import numpy as np
import pytest
from tests.test_movie_pipe_seek import prores_clip, sessions, windows, pid, read_number, random_targets, assert_dead  # noqa: F401
from tests.test_movie_pipe_seek import assert_session_gone, main_sessions, voff_clip, wait_for  # noqa: F401 (voff_clip: fixture)
from tests.test_movie_pipe_seek import COUNT, WAIT_S
from yesoncheck import external_tools, frame_cache_budget, movie_pipe_source, sequence_source
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, FILL_FAILURE_HEADLINE, FRAME_CACHE_ENV, IDLE_FILL_DELAY_S, KEEP_BEHIND, FFmpegPipeCapture, probe_movie,
)

ESCAPE_HINT = "탈출구: YESONCHECK_FRAME_CACHE=ring (psutil을 부르지 않음)"  # 판정 실패 사유 끝 (FRAME_CACHE_ESCAPE_HINT — 글 그대로 고정)

GB = 1024**3
FILL_WAIT_S = 15  # 채움(작은 클립 120장 — 보통 1초 안)을 기다리는 한도: ML 배치 부하 아래의 ffmpeg 띄우기까지 견디게 넉넉히

@pytest.fixture
def auto_mode(monkeypatch):
    monkeypatch.setenv(FRAME_CACHE_ENV, "auto")
    monkeypatch.setattr(frame_cache_budget, "memory_snapshot", lambda: (128 * GB, 100 * GB))

@pytest.fixture
def hold_fill(monkeypatch):
    """채움기를 붙잡아 둠: 쉬는 때 기준(IDLE_FILL_DELAY_S — 채움기가 확인할 때마다 모듈에서 읽음)을 한 시간으로 → 채움 세션도 안 띄움.
    release()가 원래 값(0.3초)으로 되돌림 — 그 뒤 쉬는 때가 오면 채우기 시작."""
    monkeypatch.setattr(movie_pipe_source, "IDLE_FILL_DELAY_S", 3600.0)
    return SimpleNamespace(release=lambda: monkeypatch.setattr(movie_pipe_source, "IDLE_FILL_DELAY_S", IDLE_FILL_DELAY_S))

@pytest.fixture
def fill_gate(monkeypatch):
    """fill_gate(at, block=True, on_reach=None) → 문: 채움기가 at번 프레임을 전체 저장소에 넣기 직전(_keep 앞 — 0..at−1은 이미 들어 있음)에
    on_reach(채움기)를 부르고 reached를 켠 뒤, block이면 시험이 opened를 켤 때까지(최대 WAIT_S) 멈춰 섬. 채움기를 정해진 장에서 세워
    '채우는 도중'을 시간에 기대지 않고 만든다. 끝날 때 열지 않은 문은 열어 막힌 채움 스레드를 풀어 줌."""
    gates = []
    original = movie_pipe_source._Filler._keep

    def install(at, block=True, on_reach=None):
        gate = SimpleNamespace(reached=threading.Event(), opened=threading.Event(), filler=None)

        def keep(filler, frame):
            if filler.index == at and not gate.reached.is_set():
                gate.filler = filler
                if on_reach is not None:
                    on_reach(filler)
                gate.reached.set()
                if block:
                    gate.opened.wait(WAIT_S)
            return original(filler, frame)

        monkeypatch.setattr(movie_pipe_source._Filler, "_keep", keep)
        gates.append(gate)
        return gate

    yield install
    for gate in gates:
        gate.opened.set()

def join_filler(filler):
    filler.thread.join(WAIT_S)
    assert not filler.thread.is_alive(), "채움 스레드가 끝나지 않았습니다"

@contextlib.contextmanager
def read_in_progress(cap):
    """cap.read() 하나가 진행 중인 상태를 시간에 기대지 않고 만듦: 그 캡처의 _read(read 본체)를 문에서 멈추는 것으로 바꿔 다른 스레드에서
    read()를 부름 — read()가 들어올 때 하는 기록(이 캡처의 시계·프로세스 시계 busy)은 진짜. 나갈 때 문을 열어 read가 끝나기를 기다리고
    _read를 되돌림 (그 read는 (False, None) — 시험이 쓰지 않음)."""
    entered, opened = threading.Event(), threading.Event()

    def blocked_read():
        entered.set()
        opened.wait(WAIT_S)
        return False, None

    cap._read = blocked_read
    reader = threading.Thread(target=cap.read, name="test-read-in-progress", daemon=True)
    reader.start()
    try:
        assert entered.wait(WAIT_S), "read가 들어오지 않았습니다"
        yield
    finally:
        opened.set()
        reader.join(WAIT_S)
        del cap._read
    assert not reader.is_alive()

def frame_bytes(path):
    probe = probe_movie(path)
    return probe.width * probe.height * 3

def open_full(path):
    return FFmpegPipeCapture(path, probe_movie(path), full_cache=True)

def test_decision_happens_on_first_read_not_in_constructor(auto_mode, prores_clip):
    cap = open_full(prores_clip)
    assert cap.cache_mode is None
    assert read_number(cap) == 0 and cap.cache_mode == "full"
    cap.release()

def test_full_mode_replays_every_seen_frame_without_restart(auto_mode, prores_clip, sessions):
    """한 바퀴 읽은 뒤 쉬는 동안 채움기가 전체 저장소를 채우면(wait_fill) 어디로 탐색해도 보관본 — 주 세션 하나 그대로."""
    cap = open_full(prores_clip)
    count = int(cap.get(7))  # CAP_PROP_FRAME_COUNT
    numbers = [read_number(cap) for _ in range(count)]
    assert numbers == list(range(count)) and len(main_sessions(sessions)) == 1
    first = pid(cap)
    assert cap.wait_fill(FILL_WAIT_S)
    for n in random_targets(11, count, 40):  # (seed, 프레임 수, 목표 수) — test_movie_pipe_seek의 시그니처
        cap.set(1, n)  # CAP_PROP_POS_FRAMES
        assert read_number(cap) == n
    assert len(main_sessions(sessions)) == 1 and pid(cap) == first
    cap.release()

def test_rewind_after_eof_replays_from_store(auto_mode, prores_clip, sessions):
    cap = open_full(prores_clip)
    count = int(cap.get(7))
    for _ in range(count):
        cap.read()
    assert cap.read() == (False, None) and int(cap.get(1)) == count  # EOF: cv2 계약 그대로
    assert cap.wait_fill(FILL_WAIT_S)
    cap.set(1, 0)
    assert [read_number(cap) for _ in range(count)] == list(range(count)) and len(main_sessions(sessions)) == 1
    cap.release()

def test_stream_first_keeps_lockstep_after_rewind(auto_mode, hold_fill, prores_clip, sessions):
    """100~200 격인 구간을 본 뒤 앞으로 되감아 재생: 보관 구간을 지나도 재시작이 없다 (스트림 우선 — 채움 전에도)."""
    cap = open_full(prores_clip)
    cap.set(1, 40)
    for _ in range(30):  # 40..69 링(마지막 8장), 스트림 70
        cap.read()
    restarts = len(main_sessions(sessions))
    cap.set(1, 0)  # 링 밖 뒤 → 재시작 1회
    for n in range(0, 90):
        assert read_number(cap) == n
    assert len(main_sessions(sessions)) == restarts + 1  # 70..89로 넘어갈 때 추가 재시작 없음
    cap.release()

def test_before_fill_full_mode_seeks_like_ring(auto_mode, hold_fill, prores_clip, sessions):
    """채움 전(채움기를 붙잡아 둠)의 전체 모드는 링 모드와 같다 — 내준 프레임은 링 8장에만 남으므로(재생 중 보관 없음 — 스펙 §6.5), 본 적
    있어도 링 밖이면 재시작: 0..59를 본 뒤 100(앞으로 재시작) → 30(본 구간이지만 링 밖 — 뒤로 재시작, 22에서) → 31..60은 새 스트림에서
    이어짐. 채움기는 세션도 띄우지 않고 한 장도 넣지 않음."""
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(60)] == list(range(60)) and cap.cache_mode == "full"
        assert cap._ring.indices() == list(range(60 - KEEP_BEHIND, 60)) and len(cap._full) == 0
        cap.set(1, 100)
        assert read_number(cap) == 100 and len(main_sessions(sessions)) == 2
        cap.set(1, 30)
        assert read_number(cap) == 30 and len(main_sessions(sessions)) == 3 and cap._session.start == 30 - KEEP_BEHIND
        assert [read_number(cap) for _ in range(31, 61)] == list(range(31, 61)) and len(main_sessions(sessions)) == 3
        assert cap.fill_index == 0 and cap.fill_session is None and len(cap._full) == 0 and not cap.fill_done
    finally:
        cap.release()

def test_after_fill_every_seek_is_a_store_hit(auto_mode, prores_clip, sessions):
    """채움이 끝나면 본 적 없는 구간도 보관본: 0..59만 본 뒤 채움을 기다려 100·30·마지막·0으로 뛰고 30부터 이어 읽어도 주 세션 하나 —
    30..59는 보관본, 60에서 제자리에 선 스트림을 다시 따라감(스트림 우선). 예전의 '보관 구간을 벗어날 때 재시작 한 번'은 채움 전의 일
    (test_before_fill_full_mode_seeks_like_ring)."""
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(60)] == list(range(60))
        assert cap.wait_fill(FILL_WAIT_S) and cap.fill_index == COUNT
        for n in (100, 30, COUNT - 1, 0):
            assert cap.set(1, n) and read_number(cap) == n, f"목표 {n}"
        assert cap.set(1, 30)
        assert [read_number(cap) for _ in range(30, 62)] == list(range(30, 62))
        assert len(main_sessions(sessions)) == 1
    finally:
        cap.release()

def test_filler_only_runs_when_idle(auto_mode, prores_clip, sessions):
    """채움기는 read()가 IDLE_FILL_DELAY_S(0.3초) 동안 없을 때만 꺼낸다: 그보다 촘촘히(~20ms 간격) 1초쯤 읽는 동안은 채움 세션도 띄우지 않고
    한 장도 넣지 않음 → 읽기를 멈추면 채우기 시작해 끝까지 (한도는 ML 배치 부하를 견디게 넉넉히 — 시간 단언 없이 채운 수·세션으로).
    **이 파일에서 일부러 남긴, 진짜 시간에 기대는 쉬는 때 시험**(read 사이 간격으로 판정하는 길 그대로 — 시험 스레드가 0.3초 넘게 멈추지 않는다는
    전제; 부하 ~18에서도 통과). 나머지는 hold_fill·fill_gate·read_in_progress로 시간에 기대지 않음 (A/B 시험의 고른 간격 읽기 단계만 같은 전제)."""
    cap = open_full(prores_clip)
    try:
        assert read_number(cap) == 0 and cap.cache_mode == "full"
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            assert cap.read()[0]
            time.sleep(0.02)
            assert cap.fill_index == 0 and cap.fill_session is None, "읽는 중에 채움기가 돌았습니다"
        assert wait_for(lambda: cap.fill_index > 0, FILL_WAIT_S), "읽기를 멈췄는데 채우지 않습니다"
        assert cap.wait_fill(FILL_WAIT_S) and cap.fill_index == COUNT and cap.fill_failed is None
        assert cap._full.indices() == list(range(COUNT))
        assert [session.is_filler for session in sessions] == [False, True]  # 주 세션 하나 + 채움 세션 하나
        assert_session_gone(cap.fill_session)  # 다 채우면 채움 세션을 스스로 정리
    finally:
        cap.release()

def test_read_pauses_filler_mid_fill(auto_mode, prores_clip, fill_gate):
    """채우는 도중에 read가 오면 채움기는 다음 장부터 멈춘다(꺼내지 않음 — ffmpeg는 소켓에서 저절로 멈춤): 40번 앞에 문을 세워 두고
    read 하나를 진행 중으로 만든 뒤(read_in_progress — 시간에 기대지 않음) 문을 열면, 40을 넣고(41) 그 read가 끝날 때까지 더 꺼내지 않음
    (쉬는 때 기준의 두 배를 기다려도 41) → read가 끝나면 다시 채워 끝까지."""
    gate = fill_gate(40)
    cap = open_full(prores_clip)
    try:
        assert read_number(cap) == 0
        assert gate.reached.wait(WAIT_S), "쉬는 동안 채움기가 40번에 닿지 않았습니다"
        assert cap.fill_index == 40 and cap._full.indices() == list(range(40))
        with read_in_progress(cap):  # 이제 쉬는 때가 아님
            gate.opened.set()  # 40을 넣고 다음 장 앞에서 쉬는 때를 봄 → 멈춤
            assert wait_for(lambda: cap.fill_index == 41)
            time.sleep(2 * IDLE_FILL_DELAY_S)
            assert cap.fill_index == 41 and not cap.fill_done, "read 중에 채움기가 더 꺼냈습니다"
        assert cap.wait_fill(FILL_WAIT_S) and cap._full.indices() == list(range(COUNT))
    finally:
        cap.release()

def test_idle_is_judged_across_captures(auto_mode, prores_clip, sessions):
    """쉬는 때는 프로세스 전체의 read로 본다 (Ruling 11 — A/B에서 와이프를 끄면 플레이어는 A만 read): 둘 다 전체 모드로 연 뒤 B는 놔두고
    ① A의 read 하나를 진행 중으로(read_in_progress — 시간에 기대지 않음, 그동안 이 캡처·프로세스 시계 둘 다 busy) 쉬는 때 기준의 두 배 →
    B는 채움 세션도 안 띄움 ② A를 ~20ms 간격으로 1초 읽음(이 단계만 시험 스레드가 0.3초 넘게 멈추지 않는다는 시간 전제) → B 그대로
    ③ A를 멈추면 B·A 모두 채워 끝까지."""
    a, b = open_full(prores_clip), open_full(prores_clip)
    try:
        assert read_number(b) == 0 and read_number(a) == 0
        assert a.cache_mode == b.cache_mode == "full"
        with read_in_progress(a):
            assert a._reads.busy == 1 and movie_pipe_source._PROCESS_READS.busy >= 1  # read()가 두 시계를 다 올림
            time.sleep(2 * IDLE_FILL_DELAY_S)  # B 자기 시계로는 쉬는 때가 지났음
            assert b.fill_index == 0 and b.fill_session is None, "A가 read 중인데 B가 채웠습니다"
        assert a._reads.busy == 0  # 나갈 때 내림
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            assert a.read()[0]
            time.sleep(0.02)
            assert b.fill_index == 0 and b.fill_session is None, "A를 재생하는 중에 B가 채웠습니다"
        assert b.wait_fill(FILL_WAIT_S) and a.wait_fill(FILL_WAIT_S)
        assert b._full.indices() == list(range(COUNT)) and a._full.indices() == list(range(COUNT))
        assert [session.is_filler for session in sessions].count(True) == 2
    finally:
        a.release()
        b.release()

def test_filler_does_not_write_ring_and_ring_keeps_1_5_1_shape(auto_mode, hold_fill, prores_clip, sessions):
    """읽는 동안은 링만(1.5.1 모양 — 최근 꺼낸 8장, 전체 저장소는 비어 있음 — 채움기는 붙잡아 둠). 채움기를 놓으면 전체 저장소만 쓰고 링은
    건드리지 않으며(자기 세션의 배열 — 링 보관본과 메모리를 나누지 않음), 보관본에서 내준 프레임도 링에 넣지 않음."""
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(40)] == list(range(40))
        ring = list(range(40 - KEEP_BEHIND, 40))
        assert cap._ring.indices() == ring and len(cap._full) == 0
        hold_fill.release()
        assert cap.wait_fill(FILL_WAIT_S)
        assert cap._full.indices() == list(range(COUNT)) and cap._ring.indices() == ring
        assert not any(np.shares_memory(r, f) for r in cap._ring._frames.values() for f in cap._full._frames.values())
        for n in (100, 5, 39, 0):
            assert cap.set(1, n) and read_number(cap) == n, f"목표 {n}"
        assert cap._ring.indices() == ring and len(main_sessions(sessions)) == 1
    finally:
        cap.release()

def test_wait_fill_on_ring_mode_returns_true_immediately(prores_clip):
    """채울 것이 없는 링 모드(opt-in 안 함·킬 스위치)는 판정(첫 read) 뒤 곧바로 fill_done — wait_fill(0)이 참, 채움기 없음. 판정 전은 아직 거짓."""
    plain = FFmpegPipeCapture(prores_clip, probe_movie(prores_clip))  # opt-in 안 함
    killed = open_full(prores_clip)  # conftest의 YESONCHECK_FRAME_CACHE=ring — 킬 스위치
    try:
        for cap in (plain, killed):
            assert cap.wait_fill(0) is False and not cap.fill_done  # 첫 read 전 — 판정 전
            assert read_number(cap) == 0 and cap.cache_mode == "ring"
            assert cap.wait_fill(0) is True and cap.fill_done
            assert cap.fill_index == 0 and cap.fill_failed is None and cap.fill_session is None
    finally:
        plain.release()
        killed.release()
    assert not plain.fill_done  # 닫은 캡처에는 채운 것이 없음

def test_release_stops_filler_and_returns_ledger(auto_mode, prores_clip, fill_gate, capsys):
    """채우는 도중(20번 앞에 세움 — 채움 ffmpeg는 선읽기를 채우고 소켓에서 막혀 살아 있음)에 release: 채움 세션(프로세스·소켓·스레드)이
    끝나고 장부를 돌려주고 두 저장소를 비움. 그 뒤 문을 열어도 채움기는 닫힌 캡처에 넣지 않고 끝남 — release는 실패가 아님(기록 없음)."""
    ledger = movie_pipe_source._LEDGER
    base = ledger.committed()
    gate = fill_gate(20)
    cap = open_full(prores_clip)
    assert read_number(cap) == 0
    assert gate.reached.wait(WAIT_S)
    session = cap.fill_session
    assert session is not None and session.is_filler and session.proc.poll() is None
    assert ledger.committed() > base
    cap.release()
    assert_session_gone(session)
    assert ledger.committed() == base and len(cap._full) == 0 and len(cap._ring) == 0
    gate.opened.set()  # 막혀 있던 채움기가 20번을 넣으려 함 → 닫힌 캡처라 넣지 않고 끝
    join_filler(gate.filler)
    assert len(cap._full) == 0 and cap.fill_failed is None and not cap.fill_done
    assert FILL_FAILURE_HEADLINE not in capsys.readouterr().err

def test_gc_stops_filler(auto_mode, prores_clip, fill_gate):
    """release 없이 버려진 캡처도 채움 세션을 남기지 않음 — 캡처 단위 weakref.finalize 사슬에 채움기 정지가 있음 (채움기는 캡처를 붙잡지 않음)."""
    ledger = movie_pipe_source._LEDGER
    base = ledger.committed()
    gate = fill_gate(20)
    cap = open_full(prores_clip)
    assert read_number(cap) == 0
    assert gate.reached.wait(WAIT_S)
    session = cap.fill_session
    del cap
    gc.collect()
    assert_session_gone(session)
    assert ledger.committed() == base
    gate.opened.set()
    join_filler(gate.filler)

def test_death_stops_filler(auto_mode, prores_clip, fill_gate, windows, capsys):
    """주 세션의 도중 실패로 캡처가 죽으면(죽음 전이) 채움 세션도 끝나고 두 저장소를 비움 — 알림은 죽음 한 번뿐(채움 실패 기록 없음)."""
    ledger = movie_pipe_source._LEDGER
    base = ledger.committed()
    gate = fill_gate(20)
    cap = open_full(prores_clip)
    assert read_number(cap) == 0
    assert gate.reached.wait(WAIT_S)
    session = cap.fill_session
    cap._session.proc.kill()
    while cap.read()[0]:  # 큐에 남은 정상 프레임을 다 준 뒤 죽음
        pass
    assert_dead(cap)
    assert_session_gone(session)
    assert len(cap._full) == 0 and len(cap._ring) == 0 and ledger.committed() == base
    gate.opened.set()
    join_filler(gate.filler)
    assert len(cap._full) == 0 and not cap.fill_done
    log = capsys.readouterr().err
    assert log.count(FAILURE_HEADLINE) == 1 and FILL_FAILURE_HEADLINE not in log

def test_filler_failure_logs_once_and_capture_keeps_working(auto_mode, prores_clip, sessions, fill_gate, qapp, windows, capsys):
    """채우는 도중 채움 ffmpeg가 죽으면(10번을 넣기 직전에 kill): fill_failed에 사유, 기록 한 번(사유·파일·명령·stderr), 채움 세션 정리,
    죽기 전에 받은 장은 그대로(처음부터 차례라 번호가 정확), 예산 장부의 몫은 곧바로 채운 만큼으로 줄어듦(release에서 나머지도 반환) —
    캡처는 그대로 읽힘(채운 구간은 보관본, 밖은 재시작, 순차도 정상)이고 오류 창은 없음 (보조 기능 — 스펙 §7-19)."""
    ledger = movie_pipe_source._LEDGER
    base = ledger.committed()
    fill_gate(10, block=False, on_reach=lambda filler: filler.session.proc.kill())
    cap = open_full(prores_clip)
    try:
        assert read_number(cap) == 0
        assert ledger.committed() == base + frame_bytes(prores_clip) * COUNT  # 판정 때 파일 전체 몫
        assert wait_for(lambda: cap.fill_failed is not None, FILL_WAIT_S), "채움 ffmpeg를 죽였는데 채움 실패가 적히지 않았습니다"
        filled = cap.fill_index
        assert 10 < filled < COUNT and not cap.fill_done and cap.wait_fill(0) is False
        assert ledger.committed() == base + frame_bytes(prores_clip) * filled  # 채우지 못한 몫은 돌려줌
        assert "종료 코드" in cap.fill_failed
        assert_session_gone(cap.fill_session)
        assert cap._full.indices() == list(range(filled))
        log = capsys.readouterr().err
        assert log.count(FILL_FAILURE_HEADLINE) == 1, log
        assert cap.fill_failed in log and prores_clip in log and FAILURE_HEADLINE not in log
        assert cap.set(1, filled - 1) and read_number(cap) == filled - 1 and len(main_sessions(sessions)) == 1  # 채운 구간 — 보관본
        assert cap.set(1, COUNT - 1) and read_number(cap) == COUNT - 1 and len(main_sessions(sessions)) == 2  # 밖 — 재시작
        assert cap.set(1, 50) and [read_number(cap) for _ in range(5)] == list(range(50, 55))
        qapp.processEvents()
        assert windows == [] and cap.isOpened()
        assert FILL_FAILURE_HEADLINE not in capsys.readouterr().err  # 다시 알리지 않음
        assert [session.is_filler for session in sessions].count(True) == 1  # 채움기는 다시 띄우지 않음
    finally:
        cap.release()
    assert ledger.committed() == base

def test_spawn_after_stop_launches_no_ffmpeg(prores_clip, sessions):
    """쉬는 때를 본 직후 release·죽음이 채움기를 세웠으면(stop) 채움 세션을 띄우지 않는다 — Popen 바로 앞에서 정지 플래그를 봄 (예전에는
    띄운 뒤에야 보고 곧바로 멈췄음 — 쓸모없는 ffmpeg 하나). 그 틈을 시간에 기대지 않고 만들려고 채움기를 직접 만들어 stop 뒤 _spawn을 부름."""
    filler = movie_pipe_source._Filler(threading.Lock(), movie_pipe_source._FrameStore(COUNT, keep_across_restart=True),
                                       movie_pipe_source._ReadClock(), prores_clip, COUNT, 180, 320, frame_bytes(prores_clip))
    filler.stop()
    assert filler._spawn() is None
    assert sessions == [] and filler.session is None and filler.failed is None

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
    assert len(cap._ring) == 0 and len(cap._full) == 0 and movie_pipe_source._LEDGER.committed() == base

def test_voff_seek_full_mode_replays_from_store(auto_mode, hold_fill, voff_clip, sessions, capsys):
    """영상 트랙 start 0.5s 파일의 전체 모드 (test_movie_pipe_seek::test_voff_seek_offset_corrected의 전체 모드 갈래): 채움 전(붙잡아 둠)
    30장 재생 뒤 본 구간 밖으로의 탐색 하나는 트랙 오프셋을 보정한 -ss 재시작 한 번으로 정확히 착지하고 새 스트림에서 이어짐 → 채움기를
    놓아 다 채우면(채움 세션은 -ss 없이 처음부터 — 오프셋과 무관해야 함) 파일 어디로의 무작위 탐색도 번호가 정확하고 주 세션 수 불변."""
    probe = probe_movie(voff_clip)
    assert probe.video_start - probe.format_start == pytest.approx(0.5)  # 전제: 오프셋이 있는 파일
    cap = open_full(voff_clip)
    try:
        assert [read_number(cap) for _ in range(30)] == list(range(30))
        assert cap.cache_mode == "full" and len(main_sessions(sessions)) == 1
        assert cap.set(1, 100) is True  # 본 구간 밖이고 스트림(30)에서 24장보다 멀리 — 재시작
        assert read_number(cap) == 100 and len(main_sessions(sessions)) == 2
        assert [read_number(cap) for _ in range(3)] == [101, 102, 103] and len(main_sessions(sessions)) == 2
        hold_fill.release()
        assert cap.wait_fill(FILL_WAIT_S)
        for n in random_targets(7, COUNT, 40):  # 파일 전체 — 0과 마지막 두 장 포함
            assert cap.set(1, n) is True
            assert read_number(cap) == n, f"목표 {n}"
        assert len(main_sessions(sessions)) == 2, "채운 구간으로의 탐색이 ffmpeg를 다시 띄움"
    finally:
        cap.release()
    assert FAILURE_HEADLINE not in capsys.readouterr().err

def test_restart_in_full_mode_keeps_store(auto_mode, prores_clip, sessions, fill_gate):
    """주 세션의 재시작은 링만 비우고 전체 저장소는 그대로 (채움기만 씀): 채움기를 40번 앞에 세워 0..39가 든 채로 100으로 재시작 →
    전체 저장소 40장 그대로, 5로는 재시작 없이. 문을 열면 이어 채워 끝까지."""
    gate = fill_gate(40)
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(20)] == list(range(20))
        assert gate.reached.wait(WAIT_S)
        assert cap.set(1, 100) and read_number(cap) == 100  # 재시작
        assert len(main_sessions(sessions)) == 2 and cap._ring.indices() == [100]
        assert cap._full.indices() == list(range(40))
        assert cap.set(1, 5) and read_number(cap) == 5 and len(main_sessions(sessions)) == 2
        gate.opened.set()
        assert cap.wait_fill(FILL_WAIT_S) and cap._full.indices() == list(range(COUNT))
    finally:
        cap.release()

def test_backward_restart_prefill_writes_only_ring_in_full_mode(auto_mode, hold_fill, prores_clip, sessions):
    """주 세션의 뒤로 재시작 미리 채우기는 전체 모드에서도 링에만 쓴다(전체 저장소는 채움기만): 채움 전(붙잡아 둠) 0..9를 본 뒤
    100으로(앞으로 — 미리 채우지 않음) 갔다가 본 적 없는 80으로 ← 방향 재시작 → 시작 72, 링 8장 FIFO라 73..80 → ← 7번(79..73)은
    재시작 없이, 72는 재시작 (링 모드와 같은 모양 — test_movie_pipe_seek::test_backward_restart_prefills_ring)."""
    cap = open_full(prores_clip)
    try:
        assert [read_number(cap) for _ in range(10)] == list(range(10)) and cap.cache_mode == "full"
        cap.set(1, 100)
        assert read_number(cap) == 100 and len(main_sessions(sessions)) == 2 and cap._session.start == 100
        cap.set(1, 80)
        assert read_number(cap) == 80 and len(main_sessions(sessions)) == 3
        assert cap._session.start == 80 - KEEP_BEHIND
        assert cap._ring.indices() == list(range(81 - KEEP_BEHIND, 81)) and len(cap._full) == 0  # 73..80, 전체는 비어 있음
        for n in range(79, 80 - KEEP_BEHIND, -1):  # ← 7번: 79..73
            cap.set(1, n)
            assert read_number(cap) == n and len(main_sessions(sessions)) == 3, f"← {n}"
        cap.set(1, 80 - KEEP_BEHIND)  # 72: 링 밖 → 재시작
        assert read_number(cap) == 72 and len(main_sessions(sessions)) == 4 and cap._session.start == 72 - KEEP_BEHIND
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
