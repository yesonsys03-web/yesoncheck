"""ffmpeg 파이프 캡처의 탐색 (yesoncheck/movie_pipe_source.py 3부, 스펙 §5.4): 지연 set → 다음 read가 실행 — 그대로·링 버퍼·
앞으로 버리기·-ss 재시작(트랙 시작 오프셋 보정). 실제 ffmpeg 프로세스로 클립 공장 클립을 읽는다 (mock 없음).

정답은 프레임에 그려 넣은 번호(frame_number)다 — cv2 픽셀에 기대지 않는다 (플랫폼 픽셀 차와 탐색 버그를 가르려고). cv2는 겉모습
(get·set·read의 ok)과 4:4:4 클립의 바이트 대조에만 쓴다. 어느 이동 경로를 탔는지는 시간이 아니라 세션(ffmpeg 프로세스)의 수와
pid로 실증한다 — 시간 단언 없음. 세션 수는 movie_pipe_source._PipeSession을 기록 하위 클래스로 바꿔치기해 센다 (캡처가 그 이름을
모듈에서 읽으므로 그 모듈에서 바꾼다). 오류 창은 error_window.show_window를 바꿔치기해 기록한다.
"""

import gc
import random
import threading
import time
import weakref
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.prores_clips import frame_number, make_numbered_clip, make_truncated, make_voff
from yesoncheck import error_window, external_tools, movie_pipe_source
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, KEEP_BEHIND, SEEK_BACK_K, SEEK_FORWARD_MAX, FFmpegPipeCapture, probe_movie,
)

COUNT = 120
SEED = 20261030
WAIT_S = 10  # 프로세스·스레드가 끝나기를 기다리는 한도 (보통 수십 ms)
POS = cv2.CAP_PROP_POS_FRAMES
PROPS = (cv2.CAP_PROP_FPS, cv2.CAP_PROP_FRAME_COUNT, POS, cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """기본 번호 클립: 4:4:4 10비트(HQ 표지) 120장 24fps — 4:4:4는 세 플랫폼 모두 cv2와 바이트 동일 (Task 1 Step 7)."""
    path = str(tmp_path_factory.mktemp("seek_444") / "numbered_444.mov")
    make_numbered_clip(path, count=COUNT)
    return path


@pytest.fixture(scope="session")
def ntsc_clip(tmp_path_factory):
    """23.976fps(24000/1001) 120장 — -ss 시각이 정수 마이크로초로 떨어지지 않는 속도."""
    path = str(tmp_path_factory.mktemp("seek_ntsc") / "numbered_23976.mov")
    make_numbered_clip(path, count=COUNT, fps="24000/1001")
    return path


@pytest.fixture(scope="session")
def voff_clip(tmp_path_factory):
    """영상 트랙 start 0.5s, 형식 start 0 (소리 트랙이 0부터) — 422 HQ 120장 24fps."""
    path = str(tmp_path_factory.mktemp("seek_voff") / "voff.mov")
    make_voff(path)
    return path


@pytest.fixture(scope="session")
def two_frame_clip(tmp_path_factory):
    """2장짜리 번호 클립 (count=2)."""
    path = str(tmp_path_factory.mktemp("seek_two") / "two_frames.mov")
    make_numbered_clip(path, count=2)
    return path


@pytest.fixture(scope="session")
def truncated_clip(tmp_path_factory, prores_clip):
    """헤더(faststart)는 멀쩡해 ffprobe는 120장이라 하지만 데이터가 70%에서 끊긴 클립."""
    path = str(tmp_path_factory.mktemp("seek_truncated") / "truncated.mov")
    make_truncated(prores_clip, path, cut_ratio=0.7)
    return path


@pytest.fixture
def sessions(monkeypatch):
    """캡처가 띄운 세션(ffmpeg 프로세스)을 차례로 기록 — 재시작 횟수의 실증."""
    created = []

    class RecordingSession(movie_pipe_source._PipeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(movie_pipe_source, "_PipeSession", RecordingSession)
    return created


@pytest.fixture
def windows(monkeypatch, qapp):
    """오류 창(error_window.show_window)을 띄우지 않고 (글, 부른 스레드)로 기록. 끝날 때 남은 Qt 이벤트를 비움."""
    shown = []
    monkeypatch.setattr(error_window, "show_window",
                        lambda text: shown.append(SimpleNamespace(text=text, thread=threading.current_thread())))
    yield shown
    qapp.processEvents()


# ---------------------------------------------------------------- 도구

def open_capture(path):
    return FFmpegPipeCapture(path, probe_movie(path))


def read_number(cap):
    """read 한 번 → 그 프레임의 번호 (실패하면 단언 실패)."""
    ok, frame = cap.read()
    assert ok and frame is not None, "read가 프레임을 주지 않았습니다"
    return frame_number(frame)


def read_until_false(cap):
    """(False, None)이 나올 때까지 읽은 프레임들의 번호."""
    numbers = []
    while True:
        ok, frame = cap.read()
        if not ok:
            assert frame is None
            return numbers
        numbers.append(frame_number(frame))


def read_until_false_or(cap, limit):
    """최대 limit장 읽은 번호 (그 전에 (False, None)이면 거기까지)."""
    numbers = []
    for _ in range(limit):
        ok, frame = cap.read()
        if not ok:
            break
        numbers.append(frame_number(frame))
    return numbers


def pid(cap):
    return cap._session.proc.pid


def wait_for(condition, timeout=WAIT_S):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def assert_session_gone(session):
    """ffmpeg가 끝나 거둬졌고(종료 코드 있음), 전송 소켓과 stderr 파이프가 닫혔고, 두 스레드가 끝남."""
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


def random_targets(seed, count, size):
    """무작위 목표 size개 — 0과 마지막 두 프레임은 늘 포함 (-ss 착지가 끝에 몰릴 때의 한 칸 어긋남 감시)."""
    rng = random.Random(seed)
    forced = [0, count - 2, count - 1]
    targets = rng.sample(range(1, count - 2), size - len(forced)) + forced
    rng.shuffle(targets)
    return targets


def check_random_seeks(path, seed, sessions):
    """한 캡처에서 무작위 30목표: set(n) → get == n → read 번호 == n → 이어 읽기 n+1 (끝이면 (False, None)). 끝으로 경계 세
    목표는 멀리서 와서 재시작 경로로 한 번 더, 마지막엔 재시작한 세션으로 끝까지 읽어 정상 EOF (EOF 기준이 재시작 위치로 갱신됨)."""
    cap = open_capture(path)
    try:
        for n in random_targets(seed, COUNT, 30):
            assert cap.set(POS, n) is True
            assert cap.get(POS) == float(n)
            assert read_number(cap) == n, f"목표 {n}"
            assert cap.get(POS) == float(n + 1)
            if n + 1 < COUNT:
                assert read_number(cap) == n + 1, f"목표 {n} 다음"
            else:
                assert cap.read() == (False, None)
                assert cap.get(POS) == float(COUNT) and cap.isOpened()
        for n in (0, COUNT - 2, COUNT - 1):  # 멀리(60)에서 → 링·버리기 범위 밖이라 재시작
            assert cap.set(POS, 60) and read_number(cap) == 60
            before = len(sessions)
            assert cap.set(POS, n) and read_number(cap) == n, f"재시작 목표 {n}"
            assert len(sessions) == before + 1, f"목표 {n}이 재시작 경로를 타지 않았습니다"
        assert cap.set(POS, 50)
        assert read_until_false(cap) == list(range(50, COUNT))
        assert cap.isOpened() and cap.get(POS) == float(COUNT)  # 수 불일치 가짜 실패 없음
    finally:
        cap.release()


# ---------------------------------------------------------------- 무작위 탐색 — 정답은 번호 그림

def test_random_seek_frame_exact(prores_clip, sessions, capsys):
    """무작위 30목표(0·마지막 두 프레임 포함): read한 프레임의 번호 == 목표, 이어 읽기도 연속, 끝까지 읽으면 정상 EOF."""
    check_random_seeks(prores_clip, SEED, sessions)
    assert FAILURE_HEADLINE not in capsys.readouterr().err


def test_random_seek_ntsc_rate(ntsc_clip, sessions, capsys):
    """23.976fps: -ss 시각(n*1001/24000 초)이 마이크로초로 나누어떨어지지 않아도 같은 착지 (r의 정확한 분수 계산)."""
    check_random_seeks(ntsc_clip, SEED + 7, sessions)
    assert FAILURE_HEADLINE not in capsys.readouterr().err


def test_seek_matches_cv2_bytes(prores_clip):
    """무작위 10목표: 파이프가 탐색해 준 프레임 == cv2가 같은 목표로 탐색해 준 프레임 (바이트, 4:4:4 클립)."""
    rng = random.Random(SEED + 1)
    cap, ref = open_capture(prores_clip), cv2.VideoCapture(prores_clip)
    try:
        for n in rng.sample(range(COUNT), 10):
            assert cap.set(POS, n) is True and ref.set(POS, n) is True
            ok, frame = cap.read()
            ref_ok, ref_frame = ref.read()
            assert ok and ref_ok, n
            assert frame_number(frame) == n
            assert np.array_equal(frame, ref_frame), f"목표 {n}: cv2와 바이트가 다름"
    finally:
        cap.release()
        ref.release()


def test_voff_seek_offset_corrected(voff_clip, sessions, capsys):
    """영상 start 0.5s 파일: 재시작 -ss에 트랙 시작 오프셋을 더해 목표 그대로 착지 (빼먹으면 12프레임 앞 — §3b 회귀 방지).
    목표마다 앞 위치에서 멀어 늘 재시작 경로 (세션 수로 실증), 마지막엔 재시작 세션으로 끝까지 읽어 정상 EOF."""
    probe = probe_movie(voff_clip)
    assert probe.video_start - probe.format_start == pytest.approx(0.5)  # 전제: 오프셋이 있는 파일
    cap = open_capture(voff_clip)
    try:
        for n in (100, 0, 60, COUNT - 1, 30, COUNT - 2, 5, 90, 45, 2):
            before = len(sessions)
            assert cap.set(POS, n) is True
            assert read_number(cap) == n, f"목표 {n}"
            assert len(sessions) == before + 1, f"목표 {n}이 재시작 경로를 타지 않았습니다"
        assert cap.set(POS, 100)
        assert read_until_false(cap) == list(range(100, COUNT))
        assert cap.isOpened() and cap.get(POS) == float(COUNT)
    finally:
        cap.release()
    assert FAILURE_HEADLINE not in capsys.readouterr().err


# ---------------------------------------------------------------- 이동 경로

def test_backward_step_uses_ring_buffer(prores_clip, sessions):
    """순차 20장 뒤 set(18): 프로세스 그대로(pid 불변 — 재시작 없음) 번호 18, 이어 read가 19·20·21 (링 → 스트림으로 이어짐).
    링은 내준 배열과 독립인 복사본이라 호출자가 고쳐도 멀쩡하고, 깊이는 KEEP_BEHIND장 — 그보다 뒤는 재시작."""
    cap = open_capture(prores_clip)
    try:
        for i in range(20):
            ok, frame = cap.read()
            assert ok and frame_number(frame) == i
            frame[:] = 0  # 호출자가 받은 배열을 고침 — 링의 보관본에 새면 안 됨
        first_pid = pid(cap)
        assert cap.set(POS, 18) is True and cap.get(POS) == 18.0
        ok, frame = cap.read()
        assert ok and frame_number(frame) == 18 and pid(cap) == first_pid
        assert cap.get(POS) == 19.0
        frame[:] = 0  # 링에서 받은 배열도 호출자 것
        assert cap.set(POS, 18) and read_number(cap) == 18  # 같은 프레임을 다시 — 고친 배열과 무관
        assert [read_number(cap) for _ in range(3)] == [19, 20, 21]
        assert pid(cap) == first_pid and len(sessions) == 1

        oldest = 22 - KEEP_BEHIND  # 지금 링: 14..21
        assert cap.set(POS, oldest) and read_number(cap) == oldest
        assert pid(cap) == first_pid and len(sessions) == 1
        assert cap.set(POS, oldest - 1) and read_number(cap) == oldest - 1  # 링 밖 → 재시작
        assert pid(cap) != first_pid and len(sessions) == 2
        assert read_number(cap) == oldest
    finally:
        cap.release()


def test_forward_skip_within_limit(prores_clip, sessions):
    """pos < n ≤ pos + SEEK_FORWARD_MAX → 큐·스트림에서 버림 (재시작 없음). 버린 프레임도 링에 남아 뒤로 갈 재료가 됨.
    한 장이라도 더 멀면 재시작."""
    cap = open_capture(prores_clip)
    try:
        assert [read_number(cap) for _ in range(10)] == list(range(10))
        first_pid = pid(cap)
        far = 10 + SEEK_FORWARD_MAX
        assert cap.set(POS, far) and read_number(cap) == far
        assert pid(cap) == first_pid and len(sessions) == 1
        assert cap.set(POS, far - 1) and read_number(cap) == far - 1  # 버린 프레임 — 링에서
        oldest = far + 1 - KEEP_BEHIND  # 링: 버린 프레임들 + far
        assert cap.set(POS, oldest) and read_number(cap) == oldest
        assert pid(cap) == first_pid and len(sessions) == 1
        assert [read_number(cap) for _ in range(far - oldest)] == list(range(oldest + 1, far + 1))  # 링 → 스트림
        here = far + 1
        assert cap.set(POS, here + SEEK_FORWARD_MAX + 1) and read_number(cap) == here + SEEK_FORWARD_MAX + 1
        assert pid(cap) != first_pid and len(sessions) == 2
    finally:
        cap.release()


def test_release_frees_ring(prores_clip):
    """링 메모리 상한: 끝까지 읽어도 보관본은 KEEP_BEHIND장뿐이고 그 어느 것도 내준 배열과 메모리를 나누지 않음 (내부 들여다봄).
    release하면 링도 비움 (닫은 캡처가 4K 8장을 붙들지 않게)."""
    cap = open_capture(prores_clip)
    try:
        delivered = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            delivered.append(frame)
        assert len(delivered) == COUNT
        kept = list(cap._ring._frames)
        assert len(kept) == KEEP_BEHIND
        assert [frame_number(f) for f in kept] == list(range(COUNT - KEEP_BEHIND, COUNT))
        assert not any(np.shares_memory(k, d) for k in kept for d in delivered)
    finally:
        cap.release()
    assert len(cap._ring._frames) == 0


def test_lazy_set_coalesces(prores_clip, sessions):
    """set 5회 연속은 아무것도 띄우지 않고(지연) get(POS_FRAMES)는 마지막 목표, 다음 read 한 번이 마지막 목표로 한 번만 이동
    (재시작 1회 이하). release 직전의 set은 공짜 (ffmpeg를 띄우지 않음)."""
    cap = open_capture(prores_clip)
    try:
        assert read_number(cap) == 0
        first_pid = pid(cap)
        for n in (70, 10, 100, 40, 90):
            assert cap.set(POS, n) is True
            assert cap.get(POS) == float(n)
        assert cap.get(POS) == 90.0
        assert len(sessions) == 1 and pid(cap) == first_pid  # set만으로는 이동하지 않음
        assert read_number(cap) == 90
        assert len(sessions) - 1 <= 1  # 재시작 1회 이하
        assert cap.get(POS) == 91.0
        assert read_number(cap) == 91
        assert cap.set(POS, 5) is True
    finally:
        cap.release()
    assert len(sessions) <= 2


def test_set_clamps_like_cv2(prores_clip):
    """cv2와 나란히: -3 → 0, count+5 → count, 119.7 → 119 (0~count로 자르고 소수는 버림). set의 결과·get·read·read 뒤 get이
    같은 파일의 cv2.VideoCapture와 같음 (번호는 그림으로)."""
    expected = {-3: 0, COUNT + 5: COUNT, 119.7: 119, -0.5: 0, 1.9: 1, COUNT: COUNT, 0: 0}
    cap, ref = open_capture(prores_clip), cv2.VideoCapture(prores_clip)
    try:
        for value, clamped in expected.items():
            for _ in range(3):  # 0이 아닌 곳에서 출발
                assert cap.set(POS, 40) is ref.set(POS, 40) is True
                assert cap.read()[0] and ref.read()[0]
            assert cap.set(POS, value) is ref.set(POS, value) is True
            assert cap.get(POS) == ref.get(POS) == float(clamped), value
            ok, frame = cap.read()
            ref_ok, ref_frame = ref.read()
            assert ok == ref_ok == (clamped < COUNT), value
            if ok:
                assert frame_number(frame) == frame_number(ref_frame) == clamped, value
            else:
                assert frame is None and ref_frame is None
            assert cap.get(POS) == ref.get(POS) == float(min(clamped + 1, COUNT)), value
            assert cap.isOpened() and ref.isOpened()
    finally:
        cap.release()
        ref.release()


@pytest.mark.parametrize("path_kind", ["ring", "restart"])
def test_two_frame_clip_boundaries(two_frame_clip, path_kind, monkeypatch, sessions, capsys):
    """2장 클립에서 0·1·EOF·뒤로: 한 걸음마다 cv2와 같은 set·get·read 결과. "restart"는 링·버리기를 끄고(KEEP_BEHIND 0·
    SEEK_FORWARD_MAX 0) 모든 이동을 -ss 재시작으로 — 마지막 프레임(1)과 끝(2)으로의 재시작 착지까지 본다."""
    if path_kind == "restart":
        monkeypatch.setattr(movie_pipe_source, "KEEP_BEHIND", 0)
        monkeypatch.setattr(movie_pipe_source, "SEEK_FORWARD_MAX", 0)
    steps = ["read", "read", "read", "read", 1, "read", "read", 0, "read", "read", "read", 2, "read", -1, "read",
             5, "read", 1, "read", 0, 1, "read", "read"]
    cap, ref = open_capture(two_frame_clip), cv2.VideoCapture(two_frame_clip)
    try:
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == ref.get(cv2.CAP_PROP_FRAME_COUNT) == 2.0
        for index, step in enumerate(steps):
            if step == "read":
                ok, frame = cap.read()
                ref_ok, ref_frame = ref.read()
                assert ok == ref_ok, (index, step)
                if ok:
                    assert frame_number(frame) == frame_number(ref_frame), (index, step)
                else:
                    assert frame is None and ref_frame is None
            else:
                assert cap.set(POS, step) is ref.set(POS, step) is True
            assert cap.get(POS) == ref.get(POS), (index, step)
            assert cap.isOpened() and ref.isOpened()
    finally:
        cap.release()
        ref.release()
    if path_kind == "restart":
        assert len(sessions) > 3  # 실제로 재시작 경로를 탔음
    else:
        assert len(sessions) == 1  # 링·버리기만으로 — 처음 세션 하나 (프로세스는 끝까지 읽고 끝나 있어도 됨)
    assert FAILURE_HEADLINE not in capsys.readouterr().err


def test_ab_independent(prores_clip, sessions):
    """같은 파일의 캡처 2개(A/B 와이프): 서로 다른 위치 탐색·순차 읽기·재시작·release가 서로의 위치·프로세스에 새지 않음."""
    a, b = open_capture(prores_clip), open_capture(prores_clip)
    try:
        assert pid(a) != pid(b)
        assert a.set(POS, 10) and b.set(POS, 100)
        assert (a.get(POS), b.get(POS)) == (10.0, 100.0)
        assert read_number(a) == 10  # 버리기
        b_pid = pid(b)
        assert read_number(b) == 100  # 재시작
        assert pid(b) != b_pid
        a_pid, b_pid = pid(a), pid(b)
        for i in range(3):
            assert (read_number(a), read_number(b)) == (11 + i, 101 + i)
        assert b.set(POS, 101) and read_number(b) == 101  # 링 (B의 링: 재시작한 100부터 103까지)
        assert a.set(POS, 80) and read_number(a) == 80  # A만 재시작
        assert pid(a) != a_pid and pid(b) == b_pid
        assert (read_number(a), read_number(b)) == (81, 102)
        a.release()
        assert read_until_false(b) == list(range(103, COUNT))
        assert b.set(POS, 0) and read_number(b) == 0
        assert b.isOpened() and not a.isOpened()
    finally:
        a.release()
        b.release()


# ---------------------------------------------------------------- 세션 교체·실패 (§5.5·§5.6)

def test_restart_replaces_session_and_finalizer(prores_clip, capsys):
    """재시작: 옛 ffmpeg는 끝나 거둬지고(일부러 끝냄 — 실패 아님), 새 세션이 GC 안전망(weakref.finalize)을 넘겨받음 — release
    없이 버려도, release해도 새 ffmpeg가 끝남."""
    cap = open_capture(prores_clip)
    assert read_number(cap) == 0
    old = cap._session
    assert cap.set(POS, 100) and read_number(cap) == 100
    new = cap._session
    assert new is not old
    assert_session_gone(old)
    assert old.failure is None
    assert new.proc.poll() is None
    alive = weakref.ref(cap)
    del cap
    gc.collect()
    assert alive() is None
    assert_session_gone(new)

    cap = open_capture(prores_clip)
    assert cap.set(POS, 70) and read_number(cap) == 70
    new = cap._session
    cap.release()
    assert_session_gone(new)
    assert FAILURE_HEADLINE not in capsys.readouterr().err


@pytest.mark.parametrize("path_kind", ["restart", "skip"])
def test_seek_past_truncation_dies_without_raising(truncated_clip, path_kind, qapp, windows, capsys):
    """꼬리 잘린 클립에서 잘린 곳 너머로 탐색: 재시작 직후·버리는 도중의 이른 끝은 도중 실패 — read는 예외 없이 (False, None),
    죽은 cv2 캡처 겉모습, 기록 1회, 오류 창 1회(Qt 루프). 더 읽어도 다시 알리지 않음."""
    cap = open_capture(truncated_clip)
    try:
        if path_kind == "skip":
            delivered = read_until_false_or(cap, 70)
            assert delivered == list(range(70))
            target = 70 + SEEK_FORWARD_MAX  # 잘린 곳(약 83장)을 넘는 버리기
        else:
            target = 110
        assert cap.set(POS, target) is True
        assert cap.read() == (False, None)
        assert_dead(cap)
        log = capsys.readouterr().err
        assert log.count(FAILURE_HEADLINE) == 1, log
        assert truncated_clip in log
        qapp.processEvents()
        assert len(windows) == 1 and FAILURE_HEADLINE in windows[0].text
        assert windows[0].thread is threading.main_thread()
        for _ in range(2):
            assert cap.read() == (False, None)
        qapp.processEvents()
        assert len(windows) == 1
        assert FAILURE_HEADLINE not in capsys.readouterr().err
    finally:
        cap.release()


@pytest.mark.parametrize("cause", ["popen_oserror", "ffmpeg_not_found"])
def test_restart_spawn_failure_dies_without_raising(prores_clip, cause, monkeypatch, qapp, windows, capsys):
    """재시작에서 새 ffmpeg를 못 띄움(실행 파일 없음 OSError / ToolNotFoundError): read는 예외 없이 (False, None) — 죽음 겉모습,
    옛 세션 정리, 기록 1회(원인 예외의 트레이스백 포함), 오류 창 1회."""
    cap = open_capture(prores_clip)
    try:
        assert read_number(cap) == 0
        old = cap._session

        def broken_command(path, output, seek_seconds=None):
            if cause == "ffmpeg_not_found":
                raise external_tools.ToolNotFoundError("ffmpeg를 찾지 못했습니다 (시험)")
            return [str(prores_clip) + ".no-such-ffmpeg", "-ss", f"{seek_seconds:.6f}", "-i", path]

        monkeypatch.setattr(movie_pipe_source, "_pipe_command", broken_command)
        assert cap.set(POS, 100) is True
        assert cap.read() == (False, None)
        assert_dead(cap)
        assert_session_gone(old)
        log = capsys.readouterr().err
        assert log.count(FAILURE_HEADLINE) == 1, log
        assert ("ToolNotFoundError" if cause == "ffmpeg_not_found" else "FileNotFoundError") in log
        assert "100번 프레임" in log
        qapp.processEvents()
        assert len(windows) == 1 and prores_clip in windows[0].text
    finally:
        cap.release()


def test_restart_logs_unsurfaced_failure_of_old_session(prores_clip, qapp, windows, capsys):
    """멈춰 둔 사이 죽은 ffmpeg(선읽기 큐가 차 있어 아직 드러나지 않은 실패)를 재시작이 버릴 때: 새 세션으로 정상 착지하되 옛
    실패는 기록에 한 번 남김 (조용히 삼키지 않음 — 창은 없음, 캡처는 살아 있음)."""
    cap = open_capture(prores_clip)
    try:
        assert read_number(cap) == 0
        old = cap._session
        old.proc.kill()
        assert wait_for(lambda: old.proc.poll() is not None)
        assert cap.set(POS, 100) and read_number(cap) == 100
        assert cap.isOpened()
        log = capsys.readouterr().err
        assert log.count("탐색") == 1 and prores_clip in log and FAILURE_HEADLINE not in log
        qapp.processEvents()
        assert windows == []
    finally:
        cap.release()


def test_constants_are_the_spike_values():
    """Task 1 Step 7 확정값 (CI 세 플랫폼 단언 증명): K=0(목표 시각을 직접 겨냥), 앞으로 버리기 24장, 링 8장."""
    assert (SEEK_BACK_K, SEEK_FORWARD_MAX, KEEP_BEHIND) == (0, 24, 8)
