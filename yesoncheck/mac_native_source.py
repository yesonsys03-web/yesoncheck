"""(스파이크 — spike/mac-native, 버리는 브랜치) VideoToolbox(AVAssetReader) 32BGRA IOSurface 캡처 — cv2.VideoCapture 자리에 꽂음.

M1 측정 1회차용 최소판: 읽기 스레드 하나가 copyNextSampleBuffer(PyObjC는 이 호출 동안 GIL을 놓음)로 프레임을 받아 선읽기 큐(READAHEAD장)에
넣고, GUI 스레드의 read()는 큐에서 꺼낼 뿐(복사·변환 없음). 프레임은 CVPixelBuffer 바탕 주소(읽기 잠금) 위의 (h, w, 4) BGRA 배열
(frame_handles.NativeFrameArray — .native 손잡이가 IOSurface를 쥠). 최근 KEEP_BEHIND장은 링에 두어 뒤로 한 칸이 재시작 없이, 앞으로
SEEK_FORWARD_MAX장까지는 큐에서 버리며, 그 밖의 탐색은 그 프레임 시각부터 timeRange로 새 AVAssetReader. 프레임 번호는 PTS에서.
실패하면 트레이스백을 한 번 찍고 죽은 캡처가 됨(read → (False, None)).

PyObjC는 함수 안에서만 import한다 — 이 모듈은 PyObjC가 없는 Intel·Windows CI에서도 import됨(모듈 검사).

[측정] 줄(모두 print, 기록 파일로 감):
- 읽기 스레드 1초마다 `[측정] 공급 <fps>fps …` — 그 1초에 큐에 넣은 장 수(재생 중에는 소비 속도 ≈ 24로 묶임), copyNextSampleBuffer에서
  기다린 장당 평균, 큐가 가득 차 기다린 비율, GUI의 read()가 빈 큐를 기다린 횟수·시간.
- 재시작마다 `[측정] 재시작 …ms`.
- decode_bench(): 재생과 따로 리더 1개·2개로 파일 전체를 디코드만 — Stage 0-a 처리량(단일 ≥ 40·두 리더 각 ≥ 28)과 재시작 20회.
"""

import collections
import ctypes
import itertools
import os
import random
import sys
import threading
import time
import traceback
import weakref

import cv2
import numpy as np

from yesoncheck.frame_handles import NativeHandle, wrap_native

READAHEAD = 4
KEEP_BEHIND = 8
SEEK_FORWARD_MAX = 24
READ_TIMEOUT_S = 30.0
FIRST_FRAME_TIMEOUT_S = 60.0
LOG = "[측정]"
VIDEOTOOLBOX_FRAMEWORK = "/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox"
READER_STATUS = {0: "unknown", 1: "reading", 2: "completed", 3: "failed", 4: "cancelled"}

_SERIAL = itertools.count(1)
_IMPORT_LOCK = threading.Lock()  # 두 스레드가 처음으로 동시에 PyObjC 프레임워크를 import하면 멈춤(이 Mac 실측 — 디코드만 측정의 두 리더)


def _say(text):
    print(text, flush=True)


def _pyobjc():
    """PyObjC 모듈 묶음 (처음 부를 때 import — Apple Silicon 빌드·p310_native venv에만 있음)."""
    with _IMPORT_LOCK:
        import objc
        import AVFoundation
        import CoreMedia
        import Foundation
        import Quartz

    return objc, AVFoundation, CoreMedia, Foundation, Quartz


def hw_decode_supported(codec_type):
    """VTIsHardwareDecodeSupported(codec_type) → "yes"·"no", 부르지 못하면 "?" (이유를 찍음). PyObjC VideoToolbox 래퍼 없이 ctypes로."""
    try:
        lib = ctypes.CDLL(VIDEOTOOLBOX_FRAMEWORK)
        fn = lib.VTIsHardwareDecodeSupported
        fn.restype = ctypes.c_ubyte
        fn.argtypes = [ctypes.c_uint32]
        return "yes" if fn(codec_type) else "no"
    except Exception:
        traceback.print_exc()
        return "?"


class _Movie:
    """AVURLAsset 첫 영상 트랙과 번호 계산 값 (Stage 0 스파이크 yc_vt_decode_spike.Movie와 같음)."""

    def __init__(self, path):
        objc, AVF, CM, Foundation, Q = _pyobjc()
        self.path = path
        with objc.autorelease_pool():
            url = Foundation.NSURL.fileURLWithPath_(path)
            self.asset = AVF.AVURLAsset.URLAssetWithURL_options_(url, {AVF.AVURLAssetPreferPreciseDurationAndTimingKey: True})
            tracks = self.asset.tracksWithMediaType_(AVF.AVMediaTypeVideo)
            if tracks is None or len(tracks) == 0:
                raise RuntimeError(f"영상 트랙이 없습니다 (AVFoundation): {path}")
            self.track = tracks[0]
            size = self.track.naturalSize()
            self.width, self.height = int(size.width), int(size.height)
            self.fps = float(self.track.nominalFrameRate())
            if not self.fps > 0:
                raise RuntimeError(f"nominalFrameRate가 0입니다: {path}")
            self.start = self.track.timeRange().start
            self.frame_duration = self.track.minFrameDuration()
            if not (self.frame_duration.flags & CM.kCMTimeFlags_Valid and self.frame_duration.value > 0):
                raise RuntimeError(f"minFrameDuration이 유효하지 않습니다: {self.frame_duration}")
            description = self.track.formatDescriptions()[0]
            self.codec_type = int(CM.CMFormatDescriptionGetMediaSubType(description))
            self.fourcc = self.codec_type.to_bytes(4, "big").decode("ascii", "replace")

    def time_of(self, index):
        _objc, _AVF, CM, _F, _Q = _pyobjc()
        offset = CM.CMTimeMake(index * self.frame_duration.value, self.frame_duration.timescale)
        return CM.CMTimeAdd(self.start, offset)

    def index_of(self, pts):
        _objc, _AVF, CM, _F, _Q = _pyobjc()
        if not pts.flags & CM.kCMTimeFlags_Valid:
            raise RuntimeError(f"PTS가 유효하지 않습니다: {pts}")
        return int(round(CM.CMTimeGetSeconds(CM.CMTimeSubtract(pts, self.start)) * self.fps))


def _start_reader(movie, start_index):
    """새 AVAssetReader + 트랙 출력(32BGRA, IOSurface, alwaysCopiesSampleData=False). start_index > 0이면 그 프레임 시각부터."""
    objc, AVF, CM, _F, Q = _pyobjc()
    with objc.autorelease_pool():
        reader, error = AVF.AVAssetReader.assetReaderWithAsset_error_(movie.asset, None)
        if reader is None:
            raise RuntimeError(f"AVAssetReader를 만들지 못했습니다: {error}")
        settings = {Q.kCVPixelBufferPixelFormatTypeKey: Q.kCVPixelFormatType_32BGRA, Q.kCVPixelBufferIOSurfacePropertiesKey: {}}
        output = AVF.AVAssetReaderTrackOutput.assetReaderTrackOutputWithTrack_outputSettings_(movie.track, settings)
        output.setAlwaysCopiesSampleData_(False)
        if not reader.canAddOutput_(output):
            raise RuntimeError("AVAssetReader가 트랙 출력을 받지 않습니다")
        reader.addOutput_(output)
        if start_index > 0:
            reader.setTimeRange_(CM.CMTimeRangeMake(movie.time_of(start_index), CM.kCMTimePositiveInfinity))
        if not reader.startReading():
            raise RuntimeError(f"startReading 실패: status={READER_STATUS.get(reader.status())} error={reader.error()}")
    return reader, output


def _reader_end(reader):
    """copyNextSampleBuffer가 None을 준 뒤: 정상 끝이면 None, 아니면 RuntimeError."""
    _objc, AVF, _CM, _F, _Q = _pyobjc()
    status = reader.status()
    if status == AVF.AVAssetReaderStatusCompleted:
        return None
    raise RuntimeError(f"AVAssetReader가 정상 끝이 아닙니다: status={READER_STATUS.get(status, status)} error={reader.error()}")


def _wrap_sample(movie, sample):
    """샘플 → NativeFrameArray: IOSurface·BGRA·크기 확인, 바탕 주소 읽기 잠금(손잡이가 GC되면 풂), 그 위의 (h, w, 4) 뷰. 픽셀 일 없음."""
    objc, _AVF, CM, _F, Q = _pyobjc()
    buffer = CM.CMSampleBufferGetImageBuffer(sample)
    if buffer is None:
        raise RuntimeError("CMSampleBufferGetImageBuffer가 None입니다")
    surface = Q.CVPixelBufferGetIOSurface(buffer)
    if surface is None:
        raise RuntimeError("CVPixelBufferGetIOSurface가 None입니다 (IOSurface 아님)")
    pixel_format = Q.CVPixelBufferGetPixelFormatType(buffer)
    if pixel_format != Q.kCVPixelFormatType_32BGRA:
        raise RuntimeError(f"픽셀 형식이 BGRA가 아닙니다: {pixel_format:#x}")
    width, height = Q.CVPixelBufferGetWidth(buffer), Q.CVPixelBufferGetHeight(buffer)
    if (width, height) != (movie.width, movie.height):
        raise RuntimeError(f"크기 {width}x{height} != 트랙 {movie.width}x{movie.height}")
    index = movie.index_of(CM.CMSampleBufferGetPresentationTimeStamp(sample))
    lock = Q.kCVPixelBufferLock_ReadOnly
    if Q.CVPixelBufferLockBaseAddress(buffer, lock) != 0:
        raise RuntimeError("CVPixelBufferLockBaseAddress 실패")
    row = Q.CVPixelBufferGetBytesPerRow(buffer)
    memory = Q.CVPixelBufferGetBaseAddress(buffer).as_buffer(height * row)
    view = np.ndarray((height, width, 4), np.uint8, buffer=memory, strides=(row, 4, 1))
    handle = NativeHandle(buffer, objc.pyobjc_id(surface), width, height, row, view.ctypes.data, index,
                          lambda: Q.CVPixelBufferUnlockBaseAddress(buffer, lock))
    return wrap_native(view, handle)


class _Stats:
    """한 캡처의 공급 통계 (읽기 스레드가 쓰고 1초마다 찍음; GUI 쪽 빈 큐 대기는 read가 더함 — GIL 아래 단순 덧셈)."""

    def __init__(self, label):
        self.label = label
        self.reset(None)
        self.empty_waits = 0
        self.empty_wait_s = 0.0

    def reset(self, now):
        self.window_start = now
        self.delivered = 0
        self.busy_s = 0.0
        self.full_wait_s = 0.0

    def delivered_one(self, busy_s, full_wait_s):
        now = time.perf_counter()
        if self.window_start is None:
            self.reset(now)
        self.delivered += 1
        self.busy_s += busy_s
        self.full_wait_s += full_wait_s
        elapsed = now - self.window_start
        if elapsed < 1.0:
            return
        if elapsed <= 3.0:  # 그보다 길면 쉬던 구간(일시정지)이 든 창 — 찍지 않음
            waits, wait_ms = self.empty_waits, self.empty_wait_s * 1000
            # copyNext: 읽기 스레드가 copyNextSampleBuffer(+손잡이 만들기)에서 기다린 장당 평균 — AVAssetReader가 앞서 디코드해 두므로
            # 디코드 시간이 아님(Intel 실측 0.7~1ms). 이 값이 1000/fps에 가까우면 디코더가 못 따라옴. 디코드만의 속도는 decode_bench 줄.
            _say(f"{LOG} 공급 {self.delivered / elapsed:.1f}fps (copyNext 평균 {1000 * self.busy_s / self.delivered:.1f}ms, "
                 f"큐 가득 대기 {100 * self.full_wait_s / elapsed:.0f}%, 빈 큐 read 대기 {waits}회 {wait_ms:.0f}ms) — {self.label}")
        self.empty_waits = 0
        self.empty_wait_s = 0.0
        self.reset(now)


class _Session:
    """AVAssetReader 하나 + 읽기 스레드 + 선읽기 큐. start_index부터 끝까지 차례로."""

    def __init__(self, movie, start_index, stats):
        self.movie = movie
        self.start_index = start_index
        self.next_index = start_index  # take()가 다음에 줄 프레임 번호
        self.stats = stats
        self.queue = collections.deque()
        self.cond = threading.Condition()
        self.stopped = False
        self.eof = False
        self.failure = None
        self.reader, self.output = _start_reader(movie, start_index)
        self.thread = threading.Thread(target=self._run, name=f"native-reader-{start_index}", daemon=True)
        self.thread.start()

    def _run(self):
        objc = _pyobjc()[0]
        try:
            while True:
                waited = 0.0
                with self.cond:
                    while len(self.queue) >= READAHEAD and not self.stopped:
                        t0 = time.perf_counter()
                        self.cond.wait()
                        waited += time.perf_counter() - t0
                    if self.stopped:
                        break
                started = time.perf_counter()
                with objc.autorelease_pool():
                    sample = self.output.copyNextSampleBuffer()
                    frame = None if sample is None else _wrap_sample(self.movie, sample)
                busy = time.perf_counter() - started
                if frame is None:
                    if self.stopped:
                        break
                    _reader_end(self.reader)
                    with self.cond:
                        self.eof = True
                        self.cond.notify_all()
                    return
                with self.cond:
                    if self.stopped:
                        break
                    self.queue.append(frame)
                    self.cond.notify_all()
                self.stats.delivered_one(busy, waited)
            self.reader.cancelReading()  # 멈춤: 이 스레드에서 (copyNextSampleBuffer와 겹치지 않게)
        except BaseException as exc:  # GUI의 take()가 받아 다시 올림 (트레이스백 그대로)
            with self.cond:
                self.failure = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                self.cond.notify_all()

    def wait_first(self, timeout):
        """첫 프레임이 큐에 들어올 때까지 (꺼내지 않음). 실패·시간 초과는 RuntimeError."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while not self.queue and not self.eof and self.failure is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"첫 프레임을 {timeout:.0f}초 안에 받지 못했습니다")
                self.cond.wait(remaining)
            if self.failure is not None:
                raise RuntimeError(f"읽기 스레드 실패:\n{self.failure}")
            if not self.queue:
                raise RuntimeError("프레임이 하나도 없습니다 (리더가 바로 끝남)")

    def take(self, timeout):
        """다음 프레임 (큐가 비면 기다림 — 그 시간은 stats에) — 파일 끝이면 None. 실패·시간 초과는 RuntimeError."""
        deadline = time.monotonic() + timeout
        with self.cond:
            if not self.queue and not self.eof and self.failure is None:
                t0 = time.perf_counter()
                while not self.queue and not self.eof and self.failure is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(f"읽기 스레드가 {timeout:.0f}초 동안 프레임을 주지 않았습니다")
                    self.cond.wait(remaining)
                self.stats.empty_waits += 1
                self.stats.empty_wait_s += time.perf_counter() - t0
            if self.queue:
                frame = self.queue.popleft()
                self.cond.notify_all()
                return frame
            if self.failure is not None:
                raise RuntimeError(f"읽기 스레드 실패:\n{self.failure}")
            return None

    def stop(self):
        """읽기 스레드를 멈춤 — 큐를 비우고 깨움 (리더 cancelReading은 스레드가 함)."""
        with self.cond:
            self.stopped = True
            self.queue.clear()
            self.cond.notify_all()


def _stop_sessions(holder):
    for session in holder:
        session.stop()
    holder.clear()


class NativeVTCapture:
    """cv2.VideoCapture 계약의 VideoToolbox 캡처 (모듈 설명). probe: movie_pipe_source.MovieProbe (프레임 수·fps를 파이프와 같게)."""

    def __init__(self, path, probe):
        self.path = path
        self.name = os.path.basename(path)
        self.serial = next(_SERIAL)
        self._movie = _Movie(path)
        if (self._movie.width, self._movie.height) != (probe.width, probe.height):
            raise RuntimeError(f"AVFoundation 크기 {self._movie.width}x{self._movie.height} != ffprobe {probe.width}x{probe.height}")
        self.width, self.height = probe.width, probe.height
        self._count = int(probe.nb_frames)
        self._fps = float(probe.avg)
        self.fourcc = self._movie.fourcc
        self.hw = hw_decode_supported(self._movie.codec_type)
        self._stats = _Stats(f"#{self.serial} {self.name}")
        self._ring = collections.OrderedDict()
        self._next = 0
        self._target = None
        self._dead = False
        self._released = False
        self._sessions = []  # 지금 세션 하나 (finalize 안전망이 같은 목록을 봄)
        weakref.finalize(self, _stop_sessions, self._sessions)
        self._sessions.append(_Session(self._movie, 0, self._stats))
        self._sessions[0].wait_first(FIRST_FRAME_TIMEOUT_S)

    # ------------------------------------------------------------ cv2 계약

    def isOpened(self):
        return not self._released

    def release(self):
        self._released = True
        _stop_sessions(self._sessions)
        self._ring.clear()

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(self._count)
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return float(self._target if self._target is not None else self._next)
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        return 0.0

    def set(self, prop, value):
        if prop != cv2.CAP_PROP_POS_FRAMES:
            return False
        self._target = max(0, int(value))  # 게으름: 다음 read가 이 프레임을 줌
        return True

    def read(self):
        if self._dead or self._released:
            return False, None
        n = self._target if self._target is not None else self._next
        self._target = None
        if n >= self._count:
            self._next = n
            return False, None
        try:
            frame = self._frame_at(n)
        except Exception:
            self._dead = True
            print(f"[재생] 네이티브 캡처가 죽었습니다 — 이 영상은 더 읽지 않습니다 (탈출구 YESONCHECK_MAC_NATIVE=off): {self.name}",
                  flush=True)
            traceback.print_exc()
            sys.stderr.flush()
            return False, None
        if frame is None:
            self._next = n
            return False, None
        self._next = n + 1
        return True, frame

    # ------------------------------------------------------------ 안

    def _frame_at(self, n):
        hit = self._ring.get(n)
        if hit is not None:
            return hit
        session = self._sessions[0] if self._sessions else None
        restarted_at = None
        if session is None or not (session.next_index <= n <= session.next_index + SEEK_FORWARD_MAX):
            restarted_at = time.perf_counter()
            _stop_sessions(self._sessions)
            session = _Session(self._movie, n, self._stats)
            self._sessions.append(session)
        while True:
            frame = session.take(READ_TIMEOUT_S)
            if frame is None:
                return None
            index = frame.native.index
            if index != session.next_index:
                raise RuntimeError(f"프레임 번호가 어긋났습니다: 기대 {session.next_index}, 받음 {index} (세션 시작 {session.start_index})")
            session.next_index = index + 1
            self._ring[index] = frame
            while len(self._ring) > KEEP_BEHIND:
                self._ring.popitem(last=False)
            if index == n:
                if restarted_at is not None:
                    _say(f"{LOG} 재시작 프레임 {n + 1}: {(time.perf_counter() - restarted_at) * 1000:.1f}ms — {self._stats.label}")
                return frame


# ---------------------------------------------------------------- 디코드만 (Stage 0-a, 재생과 따로)

def _decode_through(path, results, slot, barrier):
    """새 애셋·리더로 파일 전체를 디코드만 (copyNextSampleBuffer + IOSurface 확인, 잠금·배열 없음) → results[slot] = (장 수, 초) 또는 예외 글."""
    try:
        objc, _AVF, CM, _F, Q = _pyobjc()
        movie = _Movie(path)
        barrier.wait()
        started = time.perf_counter()
        reader, output = _start_reader(movie, 0)
        frames = 0
        while True:
            with objc.autorelease_pool():
                sample = output.copyNextSampleBuffer()
                if sample is None:
                    break
                buffer = CM.CMSampleBufferGetImageBuffer(sample)
                if buffer is None or Q.CVPixelBufferGetIOSurface(buffer) is None:
                    raise RuntimeError("IOSurface가 아닌 프레임")
                frames += 1
        _reader_end(reader)
        results[slot] = (frames, time.perf_counter() - started)
    except BaseException as exc:
        results[slot] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        barrier.abort()  # 아직 기다리는 다른 리더를 풀어 줌 (BrokenBarrierError로 끝남)


def decode_bench(paths, restarts=0):
    """paths의 파일마다 리더 하나씩(애셋도 따로) 스레드에서 동시에 처음부터 끝까지 디코드만 — 각 장 수·초·fps를 [측정] 줄로.
    restarts > 0이면 첫 파일에서 무작위 프레임(시드 고정) 재시작 ms도. 오래 걸림(4K 334장 ≈ 10초) — 부른 쪽이 GUI를 막지 않게
    스레드에서 부를 것. 실패는 트레이스백째 찍고 끝(예외를 올리지 않음)."""
    _pyobjc()  # 부르는 스레드에서 먼저 import (위 _IMPORT_LOCK 참고)
    readers = len(paths)
    name = " + ".join(dict.fromkeys(os.path.basename(p) for p in paths))
    results = [None] * readers
    barrier = threading.Barrier(readers)
    threads = [threading.Thread(target=_decode_through, args=(path, results, slot, barrier), daemon=True)
               for slot, path in enumerate(paths)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    parts, total_frames, longest = [], 0, 0.0
    for slot, result in enumerate(results):
        if isinstance(result, str):
            _say(f"{LOG} 디코드만 리더 {slot + 1} 실패 — {name}\n{result}")
            return
        frames, seconds = result
        total_frames += frames
        longest = max(longest, seconds)
        parts.append(f"#{slot + 1} {frames}장 {seconds:.2f}초 ({frames / seconds:.1f}fps)")
    combined = f", 합 {total_frames / longest:.1f}fps" if readers > 1 else ""
    _say(f"{LOG} 디코드만 리더 {readers}개 동시: {', '.join(parts)}{combined} — {name}")
    path = paths[0]
    if restarts <= 0:
        return
    try:
        objc = _pyobjc()[0]
        movie = _Movie(path)
        frames = results[0][0]
        rng = random.Random(20261103)
        times = []
        for target in [rng.randrange(frames) for _ in range(restarts)]:
            with objc.autorelease_pool():
                started = time.perf_counter()
                reader, output = _start_reader(movie, target)
                sample = output.copyNextSampleBuffer()
                elapsed = (time.perf_counter() - started) * 1000
                if sample is None:
                    raise RuntimeError(f"재시작 {target}: 첫 샘플이 없습니다")
                index = movie.index_of(_pyobjc()[2].CMSampleBufferGetPresentationTimeStamp(sample))
                if index != target:
                    raise RuntimeError(f"재시작 {target}: 첫 프레임 번호 {index}")
                reader.cancelReading()
            times.append(elapsed)
        ordered = sorted(times)
        _say(f"{LOG} 재시작 {len(times)}회(무작위 프레임, 번호 일치): mean={sum(times) / len(times):.1f}ms "
             f"median={ordered[len(ordered) // 2]:.1f}ms max={ordered[-1]:.1f}ms first={times[0]:.1f}ms — {name}")
    except Exception:
        _say(f"{LOG} 재시작 측정 실패 — {name}")
        traceback.print_exc()
