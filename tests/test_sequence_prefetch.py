"""이미지 시퀀스 선읽기 캐시: 동작은 선읽기 유무와 무관하게 같고, 버퍼는 예산 안에서만 차며,
풀 스레드는 데몬이고, release 뒤에는 어떤 스레드도 그 캡처를 건드리지 않는다.

스레드 시험은 이벤트·세마포어·join으로 맞춘다 (sleep만으로 맞추지 않음). 파일 읽기 실패는 파일을 지우지 않고
읽기 함수(_read_frame_file)에 예외를 주입해 만든다 (Windows에서 열린 파일 삭제는 WinError 32).
"""

import gc
import os
import threading

import cv2
import numpy as np
import pytest
from PIL import Image

from tests.test_sequence_capture import POS, PALETTE, SIZE, color_for, identify, make_seq
from yesoncheck import sequence_source
from yesoncheck.sequence_source import ImageSequenceCapture

WAIT = 10  # 기다림의 상한(초) — 이벤트가 오면 바로 끝나므로 정상일 때는 걸리지 않는다


@pytest.fixture
def opened():
    """open(identity) -> 캡처. 시험이 끝나면 전부 release하고 풀이 비는 것까지 확인."""
    gc.collect()
    assert len(sequence_source._LIVE) == 0, "앞선 시험이 release하지 않은 캡처가 남아 있음"
    captures = []

    def open_capture(identity):
        capture = ImageSequenceCapture(identity)
        captures.append(capture)
        return capture

    yield open_capture
    for capture in captures:
        capture.release()
    assert sequence_source._POOL.wait_idle(WAIT)
    assert len(sequence_source._LIVE) == 0


class Reads:
    """_read_frame_file 호출을 기록하고, 원하면 풀 스레드의 읽기를 gate가 열릴 때까지 붙잡는다 (메인 스레드는 안 막음)."""

    def __init__(self, monkeypatch, hold_pool=False):
        self.open = threading.Event()
        self.entered = threading.Semaphore(0)  # 붙잡힌 풀 스레드가 하나 생길 때마다 +1
        self.calls = []  # (스레드 이름, 파일 이름)
        self.hold_pool = hold_pool
        real = sequence_source._read_frame_file

        def read(path):
            thread = threading.current_thread().name
            self.calls.append((thread, os.path.basename(path)))
            if self.hold_pool and thread.startswith(sequence_source.POOL_THREAD_NAME):
                self.entered.release()
                self.open.wait(WAIT)
            return real(path)

        monkeypatch.setattr(sequence_source, "_read_frame_file", read)

    def by_pool(self):
        return [name for thread, name in self.calls if thread.startswith(sequence_source.POOL_THREAD_NAME)]

    def by_caller(self):
        return [name for thread, name in self.calls if not thread.startswith(sequence_source.POOL_THREAD_NAME)]

    def wait_held(self, count):
        for _ in range(count):
            assert self.entered.acquire(timeout=WAIT), "풀 스레드가 읽기에 들어오지 않음"


def total_buffered(*captures):
    with sequence_source._LOCK:
        return sum(len(capture._buffer) for capture in captures)


def log_entries(text):
    """로그 한 건은 `[시퀀스]`로 시작하는 줄 하나 + 이어지는 스택 트레이스 줄들 (예외 사슬이면 Traceback이 여러 번 나온다)."""
    return [line for line in text.splitlines() if line.startswith(sequence_source.LOG_PREFIX)]


def pool_threads(prefix):
    return [t for t in threading.enumerate() if t.name.startswith(prefix)]


def test_prefetch_fills_ahead_and_read_hits_buffer(tmp_path, monkeypatch, opened):
    """열자마자 앞쪽을 채우고(첫 프레임은 다시 디코드하지 않음), 채운 뒤의 read는 디코드를 하지 않는다."""
    decodes = []
    real = sequence_source.decode_frame
    monkeypatch.setattr(sequence_source, "decode_frame", lambda data, ext: decodes.append(ext) or real(data, ext))
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 31)))
    assert cap._wait_prefetch_idle(WAIT)
    assert len(cap._buffer) == 30
    assert len(decodes) == 30  # 파일마다 정확히 한 번 (열 때 디코드한 첫 프레임이 버퍼의 씨앗)
    for number in range(1, 31):
        ok, frame = cap.read()
        assert ok and identify(frame) == number % len(PALETTE)
    assert len(decodes) == 30  # 읽기는 모두 버퍼 적중


def test_window_follows_playback_and_keeps_recent_frames_behind(tmp_path, monkeypatch, opened):
    """예산 안에서 현재 위치 뒤 KEEP_BEHIND장을 남겨 뒤로 한 장씩 갈 때는 디코드 없이 읽고, 그보다 먼 뒤는 동기 디코드 1회."""
    reads = Reads(monkeypatch)
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 101)))
    assert cap._wait_prefetch_idle(WAIT)
    assert set(cap._buffer) == set(range(0, sequence_source.PREFETCH_BUDGET_FRAMES))
    for _ in range(20):
        assert cap.read()[0]
    assert cap._wait_prefetch_idle(WAIT)
    low = 20 - sequence_source.KEEP_BEHIND
    assert set(cap._buffer) == set(range(low, low + sequence_source.PREFETCH_BUDGET_FRAMES))
    before = len(reads.by_caller())
    cap.set(POS, low + 1)  # 뒤로 간 위치가 남겨 둔 구간 안
    ok, frame = cap.read()
    assert ok and identify(frame) == (low + 2) % len(PALETTE)
    assert len(reads.by_caller()) == before  # 디코드 없이 버퍼에서
    cap.set(POS, 2)  # 남겨 둔 구간 밖
    ok, frame = cap.read()
    assert ok and identify(frame) == 3 % len(PALETTE)
    assert len(reads.by_caller()) == before + 1  # 호출 스레드가 동기 디코드 딱 한 번


def test_budget_cap_two_captures(tmp_path, opened):
    """캡처 둘이 살아 있어도 버퍼 길이의 합은 예산 이하 — 새 캡처가 열리는 순간에도, 재생 중 매 걸음에서도."""
    budget = sequence_source.PREFETCH_BUDGET_FRAMES
    a = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 101)))
    assert a._wait_prefetch_idle(WAIT)
    assert len(a._buffer) == budget  # 혼자일 때는 예산 전부
    b = opened(make_seq(str(tmp_path), "EX02_tk1", range(1, 101)))
    assert total_buffered(a, b) <= budget  # 열자마자 a를 줄여 둠
    assert a._wait_prefetch_idle(WAIT) and b._wait_prefetch_idle(WAIT)
    assert len(a._buffer) == len(b._buffer) == budget // 2
    for number in range(1, 101):
        for cap in (a, b):
            ok, frame = cap.read()
            assert ok and identify(frame) == number % len(PALETTE)
        assert total_buffered(a, b) <= budget
    b.release()
    a.set(POS, 0)
    assert a.read()[0]
    assert a._wait_prefetch_idle(WAIT)
    assert len(a._buffer) == budget  # 하나가 닫히면 남은 쪽이 예산을 다시 쓴다


def test_budget_split_with_small_odd_budget(tmp_path, monkeypatch, opened):
    """예산이 홀수여도(7 -> 캡처당 3) 합이 넘지 않고, 작은 창에서도 프레임은 맞게 나온다."""
    monkeypatch.setattr(sequence_source, "PREFETCH_BUDGET_FRAMES", 7)
    a = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 21)))
    b = opened(make_seq(str(tmp_path), "EX02_tk1", range(1, 21)))
    for number in range(1, 21):
        for cap in (a, b):
            ok, frame = cap.read()
            assert ok and identify(frame) == number % len(PALETTE)
        assert total_buffered(a, b) <= 7
    assert a._wait_prefetch_idle(WAIT) and b._wait_prefetch_idle(WAIT)
    assert total_buffered(a, b) <= 7


def test_seek_invalidates_stale_prefetch(tmp_path, monkeypatch, opened):
    """워커가 옛 위치의 파일을 읽는 도중에 set -> read는 새 위치 프레임이고, 늦게 끝난 옛 결과는 버퍼에 들어가지 않는다."""
    reads = Reads(monkeypatch, hold_pool=True)
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 81)))
    reads.wait_held(sequence_source.PREFETCH_WORKERS)  # 슬롯 1~4를 읽는 도중에 붙잡힘
    assert set(cap._buffer) == {0}  # 열 때 디코드한 첫 프레임만
    cap.set(POS, 60)
    before = len(reads.by_caller())
    ok, frame = cap.read()  # 워커는 아직 붙잡혀 있다: 기다리지 않고 동기 디코드 한 번
    assert ok and identify(frame) == 61 % len(PALETTE)
    assert len(reads.by_caller()) == before + 1
    assert cap._inflight and min(cap._inflight) > 60  # 새 위치부터 다시 맡김: 옛 작업이 한도를 차지하고 있지 않다
    assert len(cap._inflight) <= sequence_source.PREFETCH_WORKERS
    reads.open.set()
    assert sequence_source._POOL.wait_idle(WAIT)
    assert cap._wait_prefetch_idle(WAIT)
    assert not {1, 2, 3, 4} & set(cap._buffer)  # 옛 세대 결과는 버려짐
    assert min(cap._buffer) == 60 and max(cap._buffer) == 79  # 동기로 읽은 60번 + 그 뒤 선읽기
    before = len(reads.by_caller())
    for number in range(62, 81):
        ok, frame = cap.read()
        assert ok and identify(frame) == number % len(PALETTE)
    assert len(reads.by_caller()) == before  # 새 위치부터 다시 채워 둠


def test_release_clears_buffer_and_cancels_inflight(tmp_path, monkeypatch, opened):
    """워커가 읽는 도중 release -> 버퍼·진행 목록 즉시 비움, 늦게 끝난 워커는 아무것도 하지 않고 새 작업도 안 만든다."""
    reads = Reads(monkeypatch, hold_pool=True)
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 41)))
    reads.wait_held(sequence_source.PREFETCH_WORKERS)
    assert cap._buffer and cap._inflight
    cap.release()  # 워커가 락 밖에서 읽는 중이어도 막히지 않는다
    assert cap._buffer == {} and not cap._inflight
    assert cap.isOpened() is False and cap not in sequence_source._LIVE
    reads.open.set()
    assert sequence_source._POOL.wait_idle(WAIT)
    assert cap._buffer == {} and not cap._inflight  # 풀 스레드가 해제된 캡처에 쓰지 않음
    assert cap.read() == (False, None)
    assert len(reads.by_pool()) == sequence_source.PREFETCH_WORKERS  # 이미 읽던 것뿐, 이어서 맡긴 작업 없음


def test_release_drops_queued_tasks_without_running_them(tmp_path, monkeypatch, opened):
    """풀이 꽉 차서 아직 시작 못 한 작업은 release 뒤 시작되면 파일을 읽지 않고 버려진다."""
    reads = Reads(monkeypatch, hold_pool=True)
    a = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 41)))
    b = opened(make_seq(str(tmp_path), "EX02_tk1", range(1, 41)))
    reads.wait_held(2 * sequence_source.PREFETCH_WORKERS)  # 풀 스레드 8개가 모두 붙잡힘
    c = opened(make_seq(str(tmp_path), "EX03_tk1", range(1, 41)))  # c의 작업은 줄을 선 채 시작 못 함
    assert c._inflight
    c.release()
    reads.open.set()
    assert sequence_source._POOL.wait_idle(WAIT)
    assert not [name for name in reads.by_pool() if name.startswith("EX03_")]
    assert c._buffer == {}
    assert a._wait_prefetch_idle(WAIT) and b._wait_prefetch_idle(WAIT)


def test_seek_drops_queued_tasks_without_running_them(tmp_path, monkeypatch, opened):
    """풀이 꽉 차서 시작 못 한 작업은 set으로 위치가 바뀐 뒤 시작되면 (새 창 안의 파일이라도) 읽지 않고 버려진다."""
    reads = Reads(monkeypatch, hold_pool=True)
    opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 41)))
    opened(make_seq(str(tmp_path), "EX02_tk1", range(1, 41)))
    reads.wait_held(2 * sequence_source.PREFETCH_WORKERS)
    c = opened(make_seq(str(tmp_path), "EX03_tk1", range(1, 41)))
    assert c._inflight
    c.set(POS, 2)  # 줄 선 작업의 슬롯 2~4는 새 위치의 창 안이지만, 옛 세대의 작업이다
    assert not c._inflight
    reads.open.set()
    assert sequence_source._POOL.wait_idle(WAIT)
    assert not [name for name in reads.by_pool() if name.startswith("EX03_")]


def test_stuck_file_read_does_not_block_other_calls(tmp_path, monkeypatch, opened):
    """한 읽기가 (끊긴 NAS처럼) 멈춰 있어도 락을 쥐고 있지 않아서, 다른 캡처의 read·set·get과 그 캡처의 release(closeEvent)가
    막히지 않는다. 읽던 쪽은 그 사이 release됐음을 (False, None)으로 알고 끝난다."""
    a = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 41)))
    b = opened(make_seq(str(tmp_path), "EX02_tk1", range(1, 41)))
    assert a._wait_prefetch_idle(WAIT) and b._wait_prefetch_idle(WAIT)
    entered, resume = threading.Event(), threading.Event()
    real = sequence_source._read_frame_file

    def read(path):
        if path.endswith("EX01_tk1-0035.tga") and threading.current_thread().name == "stuck-reader":
            entered.set()
            resume.wait(WAIT)
        return real(path)

    monkeypatch.setattr(sequence_source, "_read_frame_file", read)
    result = []

    def stuck():
        a.set(POS, 34)  # a의 창(0~23) 밖이라 버퍼 미스 -> 동기 읽기
        result.append(a.read())

    reader = threading.Thread(target=stuck, name="stuck-reader", daemon=True)
    reader.start()
    try:
        assert entered.wait(WAIT)

        def soon(fn):
            """fn을 다른 스레드에서 불러, 락에 막혀 끝나지 않으면 시험을 실패시킨다 (그냥 부르면 시험이 멈춘다)."""
            box = []
            caller = threading.Thread(target=lambda: box.append(fn()), daemon=True)
            caller.start()
            caller.join(WAIT)
            assert not caller.is_alive(), "호출이 락에 막혔다"
            return box[0]

        ok, frame = soon(b.read)
        assert ok and identify(frame) == 1
        assert soon(lambda: b.set(POS, 5)) is True
        assert soon(lambda: a.get(POS)) == 34.0
        soon(a.release)
    finally:
        resume.set()
    reader.join(WAIT)
    assert not reader.is_alive()
    assert result == [(False, None)]


def test_shared_pool_threads_are_daemon_and_at_most_eight(tmp_path, monkeypatch, opened):
    """캡처가 셋이어도 풀 스레드는 8개를 넘지 않고, 모두 데몬(끊긴 SMB 읽기가 종료를 막지 않음)."""
    reads = Reads(monkeypatch, hold_pool=True)
    for base in ("EX01_tk1", "EX02_tk1", "EX03_tk1"):
        opened(make_seq(str(tmp_path), base, range(1, 41)))
    reads.wait_held(2 * sequence_source.PREFETCH_WORKERS)
    threads = pool_threads(sequence_source.POOL_THREAD_NAME)
    assert len(threads) == 2 * sequence_source.PREFETCH_WORKERS
    assert all(t.daemon for t in threads)
    reads.open.set()


def test_daemon_pool_is_bounded_and_survives_failing_tasks(capsys):
    pool = sequence_source._DaemonPool(max_threads=3, name="test-pool")
    started = threading.Semaphore(0)
    release = threading.Event()
    done = []

    def work(n):
        started.release()
        release.wait(WAIT)
        done.append(n)

    for n in range(10):
        pool.submit(lambda n=n: work(n))
    for _ in range(3):
        assert started.acquire(timeout=WAIT)
    threads = pool_threads("test-pool")
    assert len(threads) == 3 and all(t.daemon for t in threads)  # 작업이 열 개여도 스레드는 상한까지만
    release.set()
    assert pool.wait_idle(WAIT)
    assert sorted(done) == list(range(10))

    def boom():
        raise RuntimeError("simulated task bug")

    pool.submit(boom)
    pool.submit(lambda: done.append("after"))
    assert pool.wait_idle(WAIT)
    assert done[-1] == "after"  # 작업 하나가 터져도 풀은 계속 일한다
    assert len(pool_threads("test-pool")) <= 3
    assert "simulated task bug" in capsys.readouterr().err  # 삼키지 않고 스택 트레이스를 낸다


def failing_reads(monkeypatch, name_part, make_error, times=None):
    """파일 이름에 name_part가 든 읽기에 예외를 주입 (times번만, None이면 계속). 주입 횟수를 세는 리스트를 돌려줌."""
    real = sequence_source._read_frame_file
    raised = []

    def read(path):
        if name_part in os.path.basename(path) and (times is None or len(raised) < times):
            raised.append(path)
            raise make_error()
        return real(path)

    monkeypatch.setattr(sequence_source, "_read_frame_file", read)
    return raised


ERRORS = [
    pytest.param(lambda: OSError("simulated NAS blip"), id="OSError"),
    pytest.param(lambda: ValueError("simulated corrupt frame"), id="ValueError"),
    pytest.param(lambda: cv2.error("simulated decoder failure"), id="cv2.error"),
]


@pytest.mark.parametrize("prefetch", [True, False], ids=["prefetch", "sync-only"])
@pytest.mark.parametrize("make_error", ERRORS)
def test_read_failure_mid_play_holds_previous(tmp_path, monkeypatch, capsys, opened, make_error, prefetch):
    """재생 중 읽기 실패 -> 예외 없이 직전 프레임을 유지하고(위치는 전진), 전체 스택 트레이스를 프레임당 한 번 로그."""
    if not prefetch:
        monkeypatch.setattr(sequence_source, "PREFETCH_BUDGET_FRAMES", 0)
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 7))
    failing_reads(monkeypatch, "EX01_tk1-0003", make_error)
    capsys.readouterr()
    cap = opened(identity)
    if prefetch:
        assert cap._wait_prefetch_idle(WAIT)  # 선읽기 쪽 실패 로그도 아래 세는 범위에 든다
    results = [cap.read() for _ in range(6)]  # 예외가 올라오지 않는다
    assert all(ok for ok, _ in results)
    assert [identify(frame) for _, frame in results] == [1, 2, 2, 4, 5, 6]  # 3번째가 실패: 직전(2) 유지
    assert cap.get(POS) == 6.0  # 실패한 프레임도 지나가야 재생이 멈추지 않는다
    held_source = results[-1][1]
    cap.set(POS, 2)  # 같은 프레임을 다시 만나도
    ok, frame = cap.read()
    assert ok and np.array_equal(frame, held_source)  # 마지막으로 돌려준 프레임을 유지
    assert sequence_source._POOL.wait_idle(WAIT)  # 선읽기 쪽 실패 로그가 찍히는 것까지
    output = capsys.readouterr().out
    assert len(log_entries(output)) == 1  # 프레임당 한 건, 스택 트레이스째
    assert "Traceback" in output and "EX01_tk1-0003.tga" in output and "simulated" in output


def test_read_failures_are_logged_once_per_frame_number(tmp_path, monkeypatch, capsys, opened):
    monkeypatch.setattr(sequence_source, "PREFETCH_BUDGET_FRAMES", 0)
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 7))
    real = sequence_source._read_frame_file

    def read(path):
        if any(part in path for part in ("-0003.", "-0005.")):
            raise OSError("simulated NAS blip")
        return real(path)

    monkeypatch.setattr(sequence_source, "_read_frame_file", read)
    cap = opened(identity)
    capsys.readouterr()
    for _ in range(2):  # 두 번 훑어도
        cap.set(POS, 0)
        for _ in range(6):
            assert cap.read()[0]
    output = capsys.readouterr().out
    entries = log_entries(output)
    assert len(entries) == 2  # 실패한 프레임 번호 둘, 각 한 건
    assert "EX01_tk1-0003.tga" in entries[0] and "EX01_tk1-0005.tga" in entries[1] and "Traceback" in output


def test_transient_prefetch_failure_is_retried_when_playback_arrives(tmp_path, monkeypatch, capsys, opened):
    """선읽기 중 한 번 난 NAS 순단은 로그에 남지만, 재생이 그 프레임에 닿을 때 다시 읽어 정상 프레임을 돌려준다."""
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 7))
    raised = failing_reads(monkeypatch, "EX01_tk1-0003", lambda: OSError("simulated NAS blip"), times=1)
    cap = opened(identity)
    assert cap._wait_prefetch_idle(WAIT)
    assert len(raised) == 1 and 2 not in cap._buffer  # 선읽기는 실패, 그 칸만 비어 있음
    frames = [identify(cap.read()[1]) for _ in range(6)]
    assert frames == [1, 2, 3, 4, 5, 6]
    assert sequence_source._POOL.wait_idle(WAIT)
    out = capsys.readouterr().out
    assert len(log_entries(out)) == 1 and "Traceback" in out and "simulated NAS blip" in out


@pytest.mark.parametrize("prefetch", [True, False], ids=["prefetch", "sync-only"])
def test_read_failure_count_counts_substituted_frames_once_per_frame(tmp_path, monkeypatch, opened, prefetch):
    """read()가 읽지 못해 직전 프레임으로 대신한 프레임의 수 (내보내기가 납품용 mov의 대체 프레임을 알리는 데 씀):
    프레임 번호당 한 번 — 다시 훑어도 늘지 않고, release한 뒤에도 값이 남는다. 읽는 동작(돌려주는 프레임)은 그대로."""
    if not prefetch:
        monkeypatch.setattr(sequence_source, "PREFETCH_BUDGET_FRAMES", 0)
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 7))
    failing_reads(monkeypatch, "EX01_tk1-0003", lambda: OSError("simulated NAS blip"))
    failing_reads(monkeypatch, "EX01_tk1-0005", lambda: ValueError("simulated corrupt frame"))
    cap = opened(identity)
    if prefetch:
        assert cap._wait_prefetch_idle(WAIT)
    assert cap.read_failure_count == 0  # 읽기 전에는 없음 (선읽기가 실패해도 대신한 것이 아님)

    frames = [identify(cap.read()[1]) for _ in range(6)]
    assert frames == [1, 2, 2, 4, 4, 6]  # 읽는 동작은 예전 그대로: 직전 프레임 유지
    assert cap.read_failure_count == 2

    for _ in range(2):  # 다시 훑어도 같은 프레임 번호는 한 번만
        cap.set(POS, 0)
        for _ in range(6):
            cap.read()
    assert cap.read_failure_count == 2

    cap.release()
    assert cap.read_failure_count == 2


def test_read_failure_count_ignores_recovered_prefetch_failure_and_gap_fill(tmp_path, monkeypatch, opened):
    """선읽기에서 한 번 실패했지만 read()가 다시 읽어 낸 프레임, 그리고 빠진 번호를 메운 프레임(설계된 동작)은 대신한 프레임이 아님."""
    identity = make_seq(str(tmp_path), "EX01_tk1", [1, 2, 3, 5, 6])  # 4번이 빠짐
    raised = failing_reads(monkeypatch, "EX01_tk1-0003", lambda: OSError("simulated NAS blip"), times=1)
    cap = opened(identity)
    assert cap._wait_prefetch_idle(WAIT)
    assert len(raised) == 1 and 2 not in cap._buffer  # 선읽기는 실패

    frames = [identify(cap.read()[1]) for _ in range(6)]
    assert frames == [1, 2, 3, 3, 5, 6]  # 3번은 다시 읽어 정상, 4번은 빠진 번호라 직전(3) 유지
    assert cap.read_failure_count == 0


def test_read_failure_count_starts_at_zero_per_capture(tmp_path, monkeypatch, opened):
    """캡처마다 새로 시작 (항목마다 새 캡처를 여는 내보내기가 항목별로 셈)."""
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 5))
    failing_reads(monkeypatch, "EX01_tk1-0002", lambda: OSError("simulated NAS blip"))
    first = opened(identity)
    for _ in range(4):
        first.read()
    assert first.read_failure_count == 1
    assert sequence_source._POOL.wait_idle(WAIT)
    monkeypatch.undo()  # 읽기 실패가 사라진 뒤 새 캡처를 엶
    second = opened(identity)
    for _ in range(4):
        second.read()
    assert second.read_failure_count == 0 and first.read_failure_count == 1


def test_first_frame_decode_failure_at_open_still_raises(tmp_path, monkeypatch):
    """생성자의 실패는 그대로 올라온다 (읽는 도중 실패만 직전 프레임 유지)."""
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 4))
    failing_reads(monkeypatch, "EX01_tk1-0001", lambda: OSError("simulated NAS blip"))
    with pytest.raises(OSError, match="simulated NAS blip"):
        ImageSequenceCapture(identity)
    assert len(sequence_source._LIVE) == 0  # 열지 못한 캡처는 예산을 차지하지 않는다


def make_unique_frame(path, number, size=SIZE):
    """번호마다 픽셀 하나가 다른 무손실 프레임 (프레임 바이트가 서로 다르다)."""
    image = Image.new("RGB", size, color_for(number))
    image.putpixel((number % size[0], number % size[1]), (number, 255 - number, 7))
    image.save(path, format="TGA")


def test_results_identical_with_and_without_prefetch(tmp_path, monkeypatch, opened):
    """같은 호출열(빠진 번호·해상도 다른 프레임·깨진 프레임·탐색·끝 너머 읽기 포함)의 결과가 선읽기 유무·타이밍과 무관하게 같다."""
    folder = str(tmp_path)
    for number in (1, 2, 3, 4, 7, 8, 9, 10, 12, 13):  # 5·6·11번 빠짐
        make_unique_frame(os.path.join(folder, f"EX01_tk1-{number:04d}.tga"), number)
    make_unique_frame(os.path.join(folder, "EX01_tk1-0009.tga"), 9, size=(32, 24))  # 해상도가 다른 프레임
    with open(os.path.join(folder, "EX01_tk1-0010.tga"), "wb") as f:
        f.write(b"garbage")  # 깨진 프레임
    identity = os.path.join(folder, "EX01_tk1.seq")

    def run(cap):
        log = []

        def read():
            ok, frame = cap.read()
            log.append(("read", ok, None if frame is None else (frame.shape, frame.tobytes()), cap.get(POS)))

        def seek(n):
            log.append(("set", n, cap.set(POS, n), cap.get(POS)))

        for _ in range(14):  # 처음부터 끝 너머까지
            read()
        for n in (3, 0, 8, 9, 5, 12, 100, -1, 2.7, 9, 3):
            seek(n)
            for _ in range(3):
                read()
        log.append(("props", cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        return log

    with monkeypatch.context() as patch:
        patch.setattr(sequence_source, "PREFETCH_BUDGET_FRAMES", 0)
        plain = opened(identity)
        assert plain._buffer == {}
        expected = run(plain)
        assert plain._buffer == {}  # 선읽기가 꺼져 있었다
    plain.release()

    waited = opened(identity)
    assert waited._wait_prefetch_idle(WAIT) and len(waited._buffer) > 1
    assert run(waited) == expected
    waited.release()

    racing = opened(identity)  # 채우는 도중에 바로 호출
    assert run(racing) == expected
    assert any(entry[0] == "read" and entry[1] for entry in expected)  # 빈 비교가 아님


def test_returned_frames_are_copies_of_read_only_buffer_entries(tmp_path, opened):
    """버퍼의 프레임은 쓰기 금지, 읽을 때마다 사본을 줘서 받은 쪽이 그려 넣어도 버퍼는 그대로."""
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", range(1, 5)))
    assert cap._wait_prefetch_idle(WAIT)
    assert all(not frame.flags.writeable for frame in cap._buffer.values())
    _, first = cap.read()
    assert first.flags.writeable and first.flags.c_contiguous
    first[:] = 0
    cap.set(POS, 0)
    _, again = cap.read()
    assert identify(again) == 1 and again is not first


def test_gap_frames_share_one_buffered_decode(tmp_path, monkeypatch, opened):
    """빠진 번호 구간은 앞 파일 하나를 가리키므로 파일은 한 번만 디코드한다."""
    decodes = []
    real = sequence_source.decode_frame
    monkeypatch.setattr(sequence_source, "decode_frame", lambda data, ext: decodes.append(ext) or real(data, ext))
    cap = opened(make_seq(str(tmp_path), "EX01_tk1", [1, 2, 9]))
    assert cap._wait_prefetch_idle(WAIT)
    assert [identify(cap.read()[1]) for _ in range(9)] == [1, 2, 2, 2, 2, 2, 2, 2, 9 % len(PALETTE)]
    assert len(decodes) == 3
