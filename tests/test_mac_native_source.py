"""네이티브(VideoToolbox) 캡처 (yesoncheck/mac_native_source.py): 실제 AVAssetReader로 클립 공장(tests/prores_clips.py)의 320×180
클립을 읽는다 (mock 없음 — 오류 창 호출과 멈춤 시험의 copyNextSampleBuffer 자리만 바꿔치기). 게이트(ProRes·HDR 등 — mac_native_gate)는 거치지 않는다 —
게이트는 플레이어가 보고(Task 14), 캡처는 받은 파일을 그대로 읽는다.

정답은 늘 프레임에 그려 넣은 번호(frame_number)와 ffmpeg 파이프 명령의 bgr24(prores_clips.pipe_frames — 색 기준; cv2는 색 태그를
무시해 기준이 못 됨)이다. 어느 탐색 경로를 탔는지는 시간이 아니라 restart_count(리더를 새로 띄운 횟수)로 본다.
내부(`cap._session` — 리더·읽기 스레드, `mac_native_source._pyobjc`·`_start_reader`·`_copy_next_sample`)는 수명·소유 계약 단언에만
들여다본다. 오류 창은 `error_window.show_window`를 바꿔치기해 기록한다 (mac_native_source가 movie_pipe_source의 전달자를 거쳐 그
모듈에서 이 이름을 읽으므로 그 모듈에서 바꾼다 — CLAUDE.md 바꿔치기 규칙).

PyObjC(AVFoundation)가 없는 환경(Windows CI·Mac lock을 설치하지 않은 환경)에서는 모듈 전체를 건너뛴다.
"""

import ctypes
import dataclasses
import gc
import math
import re
import threading
import time
import weakref
from fractions import Fraction
from types import SimpleNamespace

import pytest

AVFoundation = pytest.importorskip("AVFoundation", reason="PyObjC 없음 — 네이티브 캡처 시험은 Mac lock을 설치한 환경(두 Mac CI job)에서")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from tests import prores_clips  # noqa: E402
from yesoncheck import error_window, mac_native_source  # noqa: E402
from yesoncheck.frame_handles import native_surface_of, whole_surface_handle  # noqa: E402
from yesoncheck.mac_native_gate import native_ineligible_reason  # noqa: E402
from yesoncheck.mac_native_source import (  # noqa: E402
    NATIVE_FAILURE_HEADLINE, NATIVE_KEEP_BEHIND, NATIVE_LOG_PREFIX, NATIVE_READ_TIMEOUT_S, NATIVE_READAHEAD,
    NATIVE_READER_THREAD, NATIVE_SEEK_FORWARD_MAX, NativeCaptureError, NativeVTCapture, open_native_capture,
)
from yesoncheck.movie_pipe_source import probe_movie  # noqa: E402

POS = cv2.CAP_PROP_POS_FRAMES
COLOR_TOLERANCE = 4  # 사용자 허용 폭 (스펙 — 4:4:4는 Stage 0 실측 최대 1)
WAIT_S = 10  # 읽기 스레드가 끝나기를 기다리는 한도 (보통 수 ms)
STACK_MARK = "읽던 곳 (가장 최근 호출이 마지막):"  # 죽음 기록의 호출 스택 머리 — 트레이스백이 한 번 찍혔는지 셈
# 300장 동안 본 서로 다른 IOSurface 수의 상한 (Ruling 13): 샘플이 새면 VT 풀이 표면을 돌려받지 못해 장마다 새 표면(300),
# 고치면 선읽기 + 링 + 손에 든 장 근처(Intel 실측 12~13)에서 돌려 씀
DISTINCT_SURFACES_MAX = 2 * (NATIVE_READAHEAD + NATIVE_KEEP_BEHIND) + 8
assert DISTINCT_SURFACES_MAX == 32


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def clip30(tmp_path_factory):
    """번호 클립 30장 24fps, 4:4:4 HQ, bt709 태그 (이름 n.mov — 기록 줄 시험이 이름을 봄)."""
    path = str(tmp_path_factory.mktemp("native30") / "n.mov")
    prores_clips.make_numbered_clip(path, count=30, color="bt709")
    return path


@pytest.fixture(scope="session")
def clip60(tmp_path_factory):
    """번호 클립 60장 — 탐색·재시작 시험 (링 8장·앞으로 24장 규칙이 여러 번 돌 만큼)."""
    path = str(tmp_path_factory.mktemp("native60") / "n60.mov")
    prores_clips.make_numbered_clip(path, count=60, color="bt709")
    return path


@pytest.fixture(scope="session")
def clip200(tmp_path_factory):
    """번호 클립 200장(공장 최대) — 300장 읽기 누수 시험 (200장 + 처음으로 돌아가 100장)."""
    path = str(tmp_path_factory.mktemp("native200") / "n200.mov")
    prores_clips.make_numbered_clip(path, count=200, color="bt709")
    return path


@pytest.fixture(scope="session")
def chroma444(tmp_path_factory):
    """유채색 4444(ap4h) bt709 24장 — 4:4:4의 색 경로 (4:2:2도 게이트를 통과하지만 VideoToolbox는 빠진 색차를 보간하고 파이프는
    복사해 색 가장자리가 달라지므로 파이프 bgr24 기준의 색 시험은 4:4:4만)."""
    path = str(tmp_path_factory.mktemp("native_chroma") / "chroma_4444.mov")
    prores_clips.make_chroma_clip(path, count=24, profile="4", pix_fmt="yuv444p10le", color="bt709")
    return path


@pytest.fixture(scope="session")
def alpha_clip(tmp_path_factory):
    """유채색 4444 알파 bt709 24장 — 왼쪽 절반 알파 0(색은 그대로), 오른쪽 절반 알파 최대."""
    path = str(tmp_path_factory.mktemp("native_alpha") / "alpha_4444.mov")
    prores_clips.make_chroma_clip(path, count=24, alpha=True, color="bt709")
    return path


@pytest.fixture
def windows(monkeypatch, qapp):
    """오류 창(error_window.show_window)을 띄우지 않고 글로 기록. 끝날 때 남은 Qt 이벤트를 비워 진짜 창이 뜨지 않게."""
    shown = []
    monkeypatch.setattr(error_window, "show_window", lambda text: shown.append(text))
    yield shown
    qapp.processEvents()


# ---------------------------------------------------------------- 도구

def open_capture(path, **probe_changes):
    probe = probe_movie(path)
    if probe_changes:
        probe = dataclasses.replace(probe, **probe_changes)
    return NativeVTCapture(path, probe)


def number_of(frame):
    """프레임의 손잡이 번호와 그림 번호가 같은지 보고 그 번호."""
    index = native_surface_of(frame).index
    assert prores_clips.frame_number(frame[..., :3]) == index
    return index


def read_until_false(cap):
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            assert frame is None
            return frames
        frames.append(frame)


def seek_read(cap, n):
    """set(n) 뒤 read → 프레임 번호 (손잡이 번호 = 그림 번호 단언)."""
    assert cap.set(POS, n)
    ok, frame = cap.read()
    assert ok, f"{n}번 프레임을 읽지 못했습니다"
    return number_of(frame)


def reader_threads():
    return [t for t in threading.enumerate() if t.name.startswith(NATIVE_READER_THREAD)]


def wait_for(condition, timeout=WAIT_S):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def assert_dead(cap):
    assert cap.is_dead and not cap.isOpened()
    assert cap.read() == (False, None)
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 0.0 and cap.get(POS) == 0.0
    assert cap.set(POS, 0) is False


def max_color_diff(frames, reference):
    assert len(frames) == len(reference)
    return max(int(np.abs(f[..., :3].astype(np.int16) - r.astype(np.int16)).max()) for f, r in zip(frames, reference))


_IOSURFACE = ctypes.CDLL("/System/Library/Frameworks/IOSurface.framework/IOSurface")
_IOSURFACE.IOSurfaceGetID.restype = ctypes.c_uint32
_IOSURFACE.IOSurfaceGetID.argtypes = [ctypes.c_void_p]


def surface_id(frame):
    """프레임 표면의 IOSurface ID (프레임이 살아 있는 동안만 불러야 함 — 손잡이의 포인터)."""
    return _IOSURFACE.IOSurfaceGetID(native_surface_of(frame).iosurface)


# ---------------------------------------------------------------- 순차 읽기 · 번호 · 색

def test_read_sequence_matches_pipe_numbers_and_colors(clip30):
    """깨지는 변경: PTS → 번호 계산이 어긋남(트랙 시작을 빼지 않음·속도를 거꾸로 곱함) / 손잡이 번호 대신 받은 순서를 씀 /
    BGRA가 아닌 출력 형식(색 채널 순서)·행 여백을 무시한 reshape — 번호와 파이프 대비 색이 어긋남. 끝에서 pos가 30이 아님."""
    cap = NativeVTCapture(clip30, probe_movie(clip30))
    pipe = prores_clips.pipe_frames(clip30)
    got, frames = [], []
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            assert native_surface_of(f) is not None and f.shape == (180, 320, 4) and f.dtype == np.uint8
            got.append((native_surface_of(f).index, prores_clips.frame_number(f[..., :3])))
            frames.append(f)
        assert got == [(i, i) for i in range(30)] and cap.get(POS) == 30
        assert max_color_diff(frames, pipe) <= COLOR_TOLERANCE
    finally:
        cap.release()


@pytest.mark.parametrize("clip_name", ["chroma444", "alpha_clip"])
def test_colors_within_4_of_pipe(clip_name, request):
    """깨지는 변경: 출력 설정이 32BGRA가 아님(RGBA·ARGB면 채널이 섞임) / [..., :3]이 BGR이 아님 / 알파 클립을 premultiplied로
    받음(알파 0 쪽이 검정) — 유채색 4:4:4·알파 클립의 BGR이 ffmpeg 파이프 bgr24와 ±4를 넘게 다름."""
    clip = request.getfixturevalue(clip_name)
    cap = NativeVTCapture(clip, probe_movie(clip))
    try:
        frames = read_until_false(cap)
        assert max_color_diff(frames, prores_clips.pipe_frames(clip)) <= COLOR_TOLERANCE
    finally:
        cap.release()


def test_alpha_clip_draws_opaque_or_is_ineligible(alpha_clip):
    """알파 클립(왼쪽 절반 알파 0): VideoToolbox BGRA가 straight(Stage 0)라 알파를 무시하고 불투명하게 그리면 파이프와 같은 그림 —
    그래서 게이트는 알파 4:4:4를 받는다(크기·크로마 조건이 없고 HDR만 거름). 깨지는 변경: 출력이 premultiplied로 바뀜(알파 0 아래 BGR이 0) —
    그때는 이 시험이 실패하고 게이트가 알파를 음성으로 돌려야 한다."""
    probe = probe_movie(alpha_clip)
    assert probe.pix_fmt.startswith("yuva444p")
    assert native_ineligible_reason(probe) is None  # (이 클립은 4K가 아니어도 통과 — 알파 클립이 게이트 밖으로 밀리지 않음)
    cap = NativeVTCapture(alpha_clip, probe)
    try:
        frames = read_until_false(cap)
    finally:
        cap.release()
    half = probe.width // 2
    pipe = prores_clips.pipe_frames(alpha_clip)
    for frame, reference in zip(frames, pipe):
        transparent = frame[:, :half, :3]
        assert transparent.mean() > 50  # 검정(premultiplied)으로 지워지지 않음
        assert int(np.abs(transparent.astype(np.int16) - reference[:, :half].astype(np.int16)).max()) <= COLOR_TOLERANCE
    assert len(frames) == len(pipe) == 24


def test_frames_are_whole_surface_handles(clip30):
    """깨지는 변경: 쓰기 가능한 memoryview로 감쌈(읽기 잠금 버퍼에 쓸 수 있게 됨) / 링에서 내줄 때 조각·복사본을 줌 / wrap_native에
    (높이, bytesPerRow) 전체가 아닌 뷰를 넘김 — GPU 쪽이 whole_surface_handle로 표면을 꺼내지 못함."""
    cap = NativeVTCapture(clip30, probe_movie(clip30))
    try:
        frames = [cap.read()[1] for _ in range(5)]
        frames.append(cap.read()[1] if cap.set(POS, 2) else None)  # 링에서 내준 프레임도
        for frame in frames:
            handle = whole_surface_handle(frame)
            assert handle is not None and handle is native_surface_of(frame)
            assert frame.flags.writeable is False
            with pytest.raises(ValueError):
                frame[0, 0, 0] = 1
        assert native_surface_of(frames[-1]).index == 2 and frames[-1] is frames[2]  # 링은 같은 프레임 그대로 (복사 없음)
    finally:
        cap.release()


# ---------------------------------------------------------------- 탐색

def test_seek_rules(clip60):
    """깨지는 변경: 링(8장)을 보지 않고 재시작 / 앞으로 24장 이내를 버리지 않고 재시작 / 먼 탐색에서 재시작하지 않고 끝까지 버림 /
    뒤로 재시작이 목표에서 바로 시작(미리 채우기 없음 — ←마다 재시작) / 앞으로 재시작도 미리 채움 / 링을 재시작에서 비우지 않음."""
    cap = NativeVTCapture(clip60, probe_movie(clip60))
    try:
        assert [number_of(cap.read()[1]) for _ in range(20)] == list(range(20))  # 스트림 20, 링 12..19
        assert cap.restart_count == 0
        assert seek_read(cap, 15) == 15 and cap.restart_count == 0  # 링 안 ←
        assert [number_of(cap.read()[1]) for _ in range(6)] == [16, 17, 18, 19, 20, 21]  # 링의 나머지 → 스트림으로 이어짐
        assert cap.restart_count == 0
        assert seek_read(cap, 22 + NATIVE_SEEK_FORWARD_MAX) == 46 and cap.restart_count == 0  # 앞으로 24장 — 버리기
        assert seek_read(cap, 30) == 30 and cap.restart_count == 1  # 링(39..46) 밖 ← — 재시작, 22부터 미리 채움
        for n in range(29, 30 - NATIVE_KEEP_BEHIND, -1):  # 이어지는 ← 7번은 링에서
            assert seek_read(cap, n) == n
        assert cap.restart_count == 1
        assert seek_read(cap, 30 - NATIVE_KEEP_BEHIND) == 22 and cap.restart_count == 2  # 8번째 ← 에 다음 재시작
        assert seek_read(cap, 50) == 50 and cap.restart_count == 3  # 먼 앞(28장) — 재시작, 미리 채우지 않음
        assert seek_read(cap, 49) == 49 and cap.restart_count == 4  # 그래서 바로 ← 는 재시작
        assert seek_read(cap, 3) == 3 and cap.restart_count == 5  # 0에서 자른 미리 채우기
        assert [seek_read(cap, n) for n in (2, 1, 0)] == [2, 1, 0] and cap.restart_count == 5
        assert [number_of(cap.read()[1]) for _ in range(5)] == [1, 2, 3, 4, 5] and cap.restart_count == 5
    finally:
        cap.release()


def test_backward_step_restarts_once_per_8(clip60):
    """뒤로 한 칸씩(set(n-1)·read) — 8번에 한 번만 재시작 (Ruling 11 ①, 파이프의 '뒤로 재시작 미리 채우기'와 같은 규칙: 착지 뒤
    링은 목표−7..목표). 깨지는 변경: 미리 채우는 장수가 KEEP_BEHIND가 아님 / 미리 채운 장을 링에 넣지 않음 / 링 FIFO가 8장이 아님."""
    cap = NativeVTCapture(clip60, probe_movie(clip60))
    try:
        assert len(read_until_false(cap)) == 60
        position, restarts = 59, []
        while position > 0:
            before = cap.restart_count
            assert seek_read(cap, position - 1) == position - 1
            position -= 1
            if cap.restart_count != before:
                restarts.append(position)
        assert restarts == [51, 43, 35, 27, 19, 11, 3]  # 52..59가 링이라 51부터 8장마다
        for start in range(0, 56, NATIVE_KEEP_BEHIND):  # 어느 8칸 묶음이든 +1 이하
            assert sum(start <= r < start + NATIVE_KEEP_BEHIND for r in restarts) <= 1
    finally:
        cap.release()


def test_rapid_restarts_do_not_kill_capture(clip60, capsys):
    """리더를 연달아 새로 띄워도(재시작 연타 — M1에서 -11821 Cannot Decode로 죽었던 상황, Ruling 11 ②) 캡처가 살아 있고 번호가
    정확하다. 깨지는 변경: 재시작 때 옛 리더를 cancelReading하지 않거나 옛 큐·리더 참조를 쥔 채 새 리더를 띄움(리더 churn) / 재시작
    착지 번호 단언이 빠짐. 1초에 10번 뒤로 한 칸(파일 끝 → 처음) + 쉬지 않고 먼 점프 120번."""
    cap = NativeVTCapture(clip60, probe_movie(clip60))
    try:
        assert len(read_until_false(cap)) == 60
        for n in range(59, -1, -1):
            assert seek_read(cap, n) == n
            time.sleep(0.1)
        rng = np.random.default_rng(11)
        before = cap.restart_count
        for jump in range(120):  # 앞쪽 [0, 15) ↔ 뒤쪽 [45, 60) 번갈아 — 앞으로는 24장 넘게, 뒤로는 링 밖이라 늘 재시작
            target = int(rng.integers(45, 60)) if jump % 2 == 0 else int(rng.integers(0, 15))
            assert seek_read(cap, target) == target
        assert cap.isOpened() and not cap.is_dead
        assert cap.restart_count - before == 120
        err = capsys.readouterr().err
        assert NATIVE_FAILURE_HEADLINE not in err
    finally:
        cap.release()


class _RecordingReader:
    """AVAssetReader·출력 대역 — 진짜 객체에 그대로 넘기되 cancelReading을 부른 스레드와 그때 copyNextSampleBuffer가 진행 중이었는지
    적는다. 복사는 진짜 호출 앞에서 잠깐 쉬어(진행 중 표지를 세운 채) 재시작이 그 틈에 겹치게 만든다 — 진짜 복사 전이라 옛 코드도
    여기서는 죽지 않고(취소된 리더의 복사는 None) 겹침만 기록된다."""

    def __init__(self, real, log, copying):
        self._real, self._log, self._copying = real, log, copying

    def __getattr__(self, name):
        return getattr(self._real, name)

    def cancelReading(self):  # noqa: N802 (AVFoundation 이름)
        self._log.append(SimpleNamespace(thread=threading.current_thread().name, during_copy=bool(self._copying)))
        return self._real.cancelReading()

    def copyNextSampleBuffer(self):  # noqa: N802
        self._copying.append(1)
        try:
            time.sleep(0.005)
            return self._real.copyNextSampleBuffer()
        finally:
            self._copying.pop()


def test_reader_is_cancelled_only_by_its_own_thread(clip60, monkeypatch):
    """리더를 만든 뒤로는 읽기 스레드만 그 리더를 만진다: cancelReading은 읽기 스레드가 하던 복사를 마친 뒤 스스로 하고, 재시작은 옛 읽기
    스레드가 리더를 놓고 끝난 뒤에야 새 리더를 만든다(Ruling 11 ② — 두 리더가 겹쳐 돌지 않음). 다른 스레드(재시작·release·죽음)가
    cancelReading하면 copyNextSampleBuffer 안의 읽기 스레드가 AVFoundation 안에서 죽는다(이 Mac 실측 SIGSEGV — 재시작 연타 2,000번에서
    확률적으로). 깨지는 변경: stop()이 그 자리에서 cancelReading / 재시작이 옛 읽기 스레드를 기다리지 않고 새 리더를 띄움."""
    sessions, old_closed_at_start, log = [], [], []
    real_init, real_start = mac_native_source._ReaderSession.__init__, mac_native_source._start_reader

    def recording_init(self, *args):
        sessions.append(self)
        real_init(self, *args)

    def recording_start(fw, movie, start_index):
        old_closed_at_start.append(all(s.closed.is_set() for s in sessions[:-1]))  # 옛 세션의 읽기 스레드는 다 끝났나
        reader, output = real_start(fw, movie, start_index)
        copying = []  # 이 리더의 복사 진행 표지 (리더·출력 대역이 같이 봄)
        return _RecordingReader(reader, log, copying), _RecordingReader(output, log, copying)

    monkeypatch.setattr(mac_native_source._ReaderSession, "__init__", recording_init)
    monkeypatch.setattr(mac_native_source, "_start_reader", recording_start)
    cap = NativeVTCapture(clip60, probe_movie(clip60))
    try:
        for jump in range(40):  # 큐를 채우는 도중(복사 중)에 곧바로 다음 재시작
            target = 50 if jump % 2 == 0 else 5
            assert seek_read(cap, target) == target
        assert cap.restart_count == 40
    finally:
        cap.release()
    assert wait_for(lambda: all(s.closed.is_set() for s in sessions))
    assert len(old_closed_at_start) == 41 and all(old_closed_at_start)
    assert log, "cancelReading이 한 번도 불리지 않음"
    wrong = [entry for entry in log if not entry.thread.startswith(NATIVE_READER_THREAD) or entry.during_copy]
    assert not wrong, wrong


def test_index_gap_dies(clip30, monkeypatch, qapp, windows, capsys):
    """PTS에서 계산한 번호가 기대 번호(+1씩, 빈틈 없음)와 다르면 죽음 — 번호를 믿을 수 없는 프레임을 내주지 않음.
    깨지는 변경: 받은 순서로 번호를 매김(번호 검사 없음) / 빈틈을 건너뛰고 계속 감."""
    real = mac_native_source._frame_index

    def skipping(*args):
        index = real(*args)
        return index + 1 if index >= 10 else index  # 10번부터 한 칸 밀림 = 10번이 빠진 것처럼

    monkeypatch.setattr(mac_native_source, "_frame_index", skipping)
    cap = NativeVTCapture(clip30, probe_movie(clip30))
    try:
        frames = read_until_false(cap)
        assert [number_of(f) for f in frames] == list(range(10))
        assert_dead(cap)
        err = capsys.readouterr().err
        assert err.count(NATIVE_FAILURE_HEADLINE) == 1 and "번호" in err
        qapp.processEvents()
        assert len(windows) == 1
    finally:
        cap.release()


def test_frame_index_is_exact_over_10000_frames_at_23976():
    """번호 = round((PTS − 트랙 시작) × r)을 CMTime 분수 그대로(Fraction) 계산 — 23.976fps(24000/1001)에서 1만 장이 어긋나지 않음,
    시간 단위가 600·2997이라 PTS가 반올림된 파일(프레임마다 ±0.5틱)도. 깨지는 변경: 반올림 대신 버림(int — 반올림으로 앞당겨진
    PTS가 앞 번호로 감) / 트랙 시작을 빼지 않음 / 속도를 r이 아니라 1/r로 곱함."""
    rate = Fraction(24000, 1001)
    for timescale in (24000, 600, 2997):
        start_value = 7 * timescale  # 트랙이 7초에서 시작
        for i in range(10_000):
            exact = Fraction(i) / rate * timescale
            value = start_value + math.floor(exact + Fraction(1, 2))  # 파일이 시간 단위로 반올림해 둔 PTS
            assert mac_native_source._frame_index(value, timescale, Fraction(start_value, timescale), rate) == i


# ---------------------------------------------------------------- 끝 · 실패

def test_eof_invariants_and_get(clip30):
    """cv2 의미: FRAME_COUNT·FPS(float(avg))·크기는 probe 값, 끝에서 (False, None)이고 pos 그대로·열린 채, 끝 뒤 탐색도 됨, set은
    0~count로 자름. 깨지는 변경: 끝을 죽음으로 처리 / 끝에서 pos를 올림 / get이 AVFoundation 값(nominalFrameRate)을 씀 / set(count)
    뒤 read가 리더를 끝 너머로 띄움."""
    probe = probe_movie(clip30)
    cap = NativeVTCapture(clip30, probe)
    try:
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 30.0 and cap.get(cv2.CAP_PROP_FPS) == float(probe.avg) == 24.0
        assert (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (320.0, 180.0)
        assert cap.get(POS) == 0.0 and cap.get(cv2.CAP_PROP_BRIGHTNESS) == 0.0
        assert len(read_until_false(cap)) == 30
        for _ in range(2):
            assert cap.read() == (False, None) and cap.get(POS) == 30.0
        assert cap.isOpened() and not cap.is_dead
        assert seek_read(cap, 29) == 29 and cap.read() == (False, None)  # 링에서 마지막 장, 다시 끝
        assert cap.set(POS, 30) and cap.get(POS) == 30.0 and cap.read() == (False, None)
        restarts = cap.restart_count
        assert cap.set(POS, 0) and cap.get(POS) == 0.0  # 지연 — 아직 이동하지 않음
        assert cap.restart_count == restarts
        assert number_of(cap.read()[1]) == 0 and cap.restart_count == restarts + 1
        assert cap.set(POS, -3) and cap.get(POS) == 0.0
        assert cap.set(POS, 35) and cap.get(POS) == 30.0
        assert cap.set(POS, float("nan")) and cap.get(POS) == 0.0
        assert cap.set(POS, 7.9) and cap.get(POS) == 7.0
        assert cap.set(cv2.CAP_PROP_FPS, 10) is False
        assert number_of(cap.read()[1]) == 7
    finally:
        cap.release()
    assert not cap.isOpened() and not cap.is_dead
    assert cap.read() == (False, None) and cap.get(cv2.CAP_PROP_FPS) == 0.0 and cap.set(POS, 0) is False


@pytest.mark.parametrize("claimed, delivered", [(40, 30), (20, 20)], ids=["file_shorter_than_claimed", "file_longer_than_claimed"])
def test_short_file_is_failure_not_eof(clip30, claimed, delivered, qapp, windows, capsys):
    """EOF 불변식 (Ruling 11 ③): 받은 장 수가 nb_frames와 같을 때만 끝 — 리더가 일찍 끝나면(파일이 probe보다 짧음) 조용한 EOF가
    아니라 죽음 + 기록 1회 + 창 1회, 넘쳐도(파일이 더 김) 죽음. 깨지는 변경: 리더의 끝(None)을 그대로 EOF로 처리 / 넘친 프레임을 내줌."""
    cap = open_capture(clip30, nb_frames=claimed)
    try:
        frames = read_until_false(cap)
        assert [number_of(f) for f in frames] == list(range(delivered))
        assert_dead(cap)
        err = capsys.readouterr().err
        assert err.count(NATIVE_FAILURE_HEADLINE) == 1 and err.count(STACK_MARK) == 1
        assert f"프레임 수 {claimed}" in err and clip30 in err
        assert windows == []  # 창은 Qt 루프로 미룸
        qapp.processEvents()
        assert len(windows) == 1 and f"프레임 수 {claimed}" in windows[0]
        assert windows[0].rstrip().endswith("YESONCHECK_MAC_NATIVE=off")
    finally:
        cap.release()


def test_reader_stall_dies_with_one_window(clip30, monkeypatch, qapp, windows, capsys):
    """copyNextSampleBuffer가 멈추면(NAS hard mount 등) NATIVE_READ_TIMEOUT_S 뒤 죽음: 큐에 있던 정상 프레임을 다 준 뒤 read
    (False, None), isOpened False, 기록(트레이스백) 1회, 오류 창 1회(Qt 루프에서 — 끝 줄은 탈출구 안내), 죽음이 리더를 정리(큐 비움 ·
    cancelReading). 깨지는 변경: read가 무한히 기다림 / 시간 초과를 EOF로 처리 / 창을 read 안에서 바로 띄움 / 창이나 기록이 두 번."""
    monkeypatch.setattr(mac_native_source, "NATIVE_READ_TIMEOUT_S", 0.5)
    release_stall = threading.Event()
    real_copy = mac_native_source._copy_next_sample

    def stalled(output):
        release_stall.wait(WAIT_S)
        return None

    cap = NativeVTCapture(clip30, probe_movie(clip30))
    try:
        assert [number_of(cap.read()[1]) for _ in range(3)] == [0, 1, 2]
        assert wait_for(lambda: len(cap._session.frames) == NATIVE_READAHEAD)  # 선읽기 큐가 참 (읽기 스레드는 자리를 기다림)
        monkeypatch.setattr(mac_native_source, "_copy_next_sample", stalled)
        started = time.monotonic()
        frames = read_until_false(cap)
        assert [number_of(f) for f in frames] == list(range(3, 3 + NATIVE_READAHEAD))  # 큐의 정상 프레임은 다 받음
        assert time.monotonic() - started < WAIT_S
        assert_dead(cap)
        err = capsys.readouterr().err
        assert err.count(NATIVE_FAILURE_HEADLINE) == 1 and err.count(STACK_MARK) == 1
        assert "0.5초" in err and "test_reader_stall_dies_with_one_window" in err  # 원인 · 읽던 곳의 호출 스택
        assert windows == []
        qapp.processEvents()
        assert len(windows) == 1 and NATIVE_FAILURE_HEADLINE in windows[0] and clip30 in windows[0]
        assert windows[0].rstrip().endswith("YESONCHECK_MAC_NATIVE=off")
        for _ in range(3):
            assert cap.read() == (False, None)
        qapp.processEvents()
        assert len(windows) == 1
        assert NATIVE_FAILURE_HEADLINE not in capsys.readouterr().err
    finally:
        release_stall.set()
        monkeypatch.setattr(mac_native_source, "_copy_next_sample", real_copy)
        cap.release()
    assert wait_for(lambda: not reader_threads())


# ---------------------------------------------------------------- 열기 · 수명 · 메모리

def test_open_native_capture_logs_line(clip30, capsys):
    """열기 기록 한 줄 — 기록에 이 줄이 있으면 네이티브 경로. 깨지는 변경: 줄을 남기지 않음 / 형식이 바뀜(크기 ×·fps·프레임 수·
    32BGRA·hw)."""
    probe = probe_movie(clip30)
    cap = open_native_capture(clip30, probe)
    try:
        out = capsys.readouterr().out
        hw = {True: "yes", False: "no", None: "?"}[cap.hardware_decode_supported]
        assert f"{NATIVE_LOG_PREFIX} n.mov (prores 320×180 24fps, 프레임 30, 32BGRA, hw={hw})\n" in out
        assert re.search(r"^\[재생\] 네이티브\(VideoToolbox\): n\.mov \(prores 320×180 24fps, 프레임 30, 32BGRA, hw=(yes|no|\?)\)$",
                         out, re.M)
        assert cap.isOpened()
    finally:
        cap.release()


def test_open_failures_raise_native_capture_error(tmp_path, clip30):
    """열기 실패만 예외 — 생성자가 NativeCaptureError(원인·파일). 깨지는 변경: AVFoundation이 못 읽는 파일·크기가 probe와 다른
    파일을 열린 캡처로 돌려줌(그 뒤 read에서야 죽음) / 원인을 감춘 채 다른 예외."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"not a movie" * 100)
    with pytest.raises(NativeCaptureError, match="broken.mov"):
        NativeVTCapture(str(broken), probe_movie(clip30))
    with pytest.raises(NativeCaptureError, match="640"):
        open_capture(clip30, width=640)
    assert wait_for(lambda: not reader_threads())


def test_release_stops_reader_thread_and_frees(clip30):
    """release: 읽기 스레드가 끝나고(threading.enumerate에 없음) 링·큐가 쥔 프레임의 keepalive(잠금 주인)가 풀림 — 호출자가 쥔
    프레임은 그대로 읽힘. 두 번 불러도 됨. release 없이 버린 캡처도 GC 안전망(weakref.finalize)이 스레드를 끝냄.
    깨지는 변경: release가 리더를 멈추지 않음 / 링을 비우지 않음 / keepalive가 캡처·배열을 쥐는 순환 / finalize 안전망이 없음."""
    handles, owners = weakref.WeakSet(), weakref.WeakSet()
    cap = NativeVTCapture(clip30, probe_movie(clip30))
    for _ in range(12):
        frame = cap.read()[1]
        handles.add(native_surface_of(frame))
        owners.add(native_surface_of(frame).keepalive)
    kept = frame  # 호출자가 쥔 마지막 프레임 (11번)
    del frame
    assert reader_threads()
    cap.release()
    cap.release()
    assert wait_for(lambda: not reader_threads())
    gc.collect()
    assert len(handles) == 1 and len(owners) == 1  # 쥐고 있는 프레임 하나만
    assert number_of(kept) == 11
    del kept
    gc.collect()
    assert len(handles) == 0 and len(owners) == 0

    dropped = NativeVTCapture(clip30, probe_movie(clip30))
    assert dropped.read()[0] and reader_threads()
    del dropped
    gc.collect()
    assert wait_for(lambda: not reader_threads())


def test_sample_buffers_are_released(clip200):
    """샘플 버퍼가 새지 않음 (Ruling 13 — M1 83GB 누수): copyNextSampleBuffer의 +1(Copy 규칙)을 PyObjC가 갚게 메타데이터를 등록.
    300장을 읽는 동안 본 서로 다른 IOSurface가 32개 이하(새면 장마다 새 표면 — 300), 복사 직후 샘플의 참조 수 1, 샘플을 놓으면 버퍼는
    우리 쪽 하나. 깨지는 변경: registerMetaDataForSelector 줄을 지움(rc 2·표면 300) / 호출처마다 CFRelease를 더함(메타데이터와
    겹치면 이중 해제 — rc 0·크래시)."""
    fw = mac_native_source._pyobjc()
    retval = AVFoundation.AVAssetReaderTrackOutput.copyNextSampleBuffer.__metadata__()["retval"]
    assert retval.get("already_cfretained") is True

    import CoreFoundation

    movie = mac_native_source._Movie(fw, clip200, probe_movie(clip200).r)
    reader, output = mac_native_source._start_reader(fw, movie, 0)
    with fw.objc.autorelease_pool():
        sample = mac_native_source._copy_next_sample(output)
        assert CoreFoundation.CFGetRetainCount(sample) == 1
        buffer = fw.CoreMedia.CMSampleBufferGetImageBuffer(sample)
        del sample
    assert CoreFoundation.CFGetRetainCount(buffer) == 1
    reader.cancelReading()
    del buffer, reader, output, movie

    cap = NativeVTCapture(clip200, probe_movie(clip200))
    surfaces = set()
    try:
        for i in range(300):
            if i == 200:
                assert cap.set(POS, 0)
            ok, frame = cap.read()
            assert ok and native_surface_of(frame).index == i % 200
            surfaces.add(surface_id(frame))
            del frame
    finally:
        cap.release()
    assert len(surfaces) <= DISTINCT_SURFACES_MAX, f"서로 다른 IOSurface {len(surfaces)}개 (300장)"


def test_constants_match_the_brief():
    assert (NATIVE_READAHEAD, NATIVE_KEEP_BEHIND, NATIVE_SEEK_FORWARD_MAX, NATIVE_READ_TIMEOUT_S) == (4, 8, 24, 30.0)
    assert NATIVE_LOG_PREFIX == "[재생] 네이티브(VideoToolbox):"
