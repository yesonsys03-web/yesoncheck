"""이미지 시퀀스의 프레임 읽기: 한 장 디코딩(decode_frame)과 cv2.VideoCapture 자리에 꽂는 캡처(ImageSequenceCapture).

tga·png·jpg·jpeg·tif·tiff는 PIL로 읽는다: 번들된 cv2 4.6.0과 Qt는 RLE 압축 TGA를 못 읽는다.
exr은 자리만 잡아 둔 경로(OpenCV, 0~1 잘라내기만 하고 톤매핑은 하지 않음).

캡처는 안쪽에서 앞쪽 프레임을 미리 디코드해 두는(선읽기) 상한 있는 버퍼를 쓴다 — 겉으로 보이는 동작은 선읽기가 없을 때와 같다.
"""

import bisect
import collections
import functools
import io
import os
import re
import threading
import traceback
import weakref

# OpenCV는 이 값을 EXR을 처음 디코딩할 때 읽는다 (cv2를 먼저 불러왔어도 그 전에만 정해지면 된다)
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
from PIL import Image

from yesoncheck.sequence_scan import SEQ_EXTENSIONS, SEQ_SUFFIX, group_sequences, is_sequence_path

PIL_EXTENSIONS = frozenset({"tga", "png", "jpg", "jpeg", "tif", "tiff"})
PAIRED_MOVIE_EXTS = ("mov", "mp4")  # fps를 읽는 짝 영상 (<base>.mov가 있으면 그것, 없으면 <base>.mp4)
DEFAULT_FPS = 24.0
LOG_PREFIX = "[시퀀스]"

# 선읽기 (spec §5.2) — 상수는 여기 한 곳
PREFETCH_WORKERS = 4  # 캡처 하나가 동시에 풀에 맡겨 둘 수 있는 선읽기 작업 수
PREFETCH_BUDGET_FRAMES = 48  # 살아 있는 캡처 전체가 나눠 쓰는 디코드 프레임 상한 (약 300MB) — 하나면 48, 둘이면 24씩
KEEP_BEHIND = 8  # 현재 위치 뒤로 남겨 두는 프레임 (뒤로 한 장씩 갈 때 다시 디코드하지 않게)
POOL_MAX_THREADS = 2 * PREFETCH_WORKERS  # 와이프로 캡처 둘이 살아 있을 때의 합
POOL_THREAD_NAME = "seq-prefetch"


def decode_frame(data, ext):
    """프레임 파일 내용 `data`(bytes)를 (h, w, 3) BGR uint8 연속 배열로 디코딩.

    ext: 점 없는 소문자 확장자 ("tga"). 지원하지 않는 확장자나 깨진 데이터는 ValueError.
    """
    if ext in PIL_EXTENSIONS:
        return _decode_pil(data)
    if ext == "exr":
        return _decode_exr(data)
    raise ValueError(f"지원하지 않는 이미지 시퀀스 확장자: {ext!r}")


def _decode_pil(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = np.asarray(image.convert("RGB"))
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        # PIL의 깨진 파일 신호: 못 알아보는·잘린 파일 -> UnidentifiedImageError(OSError)·OSError,
        # 일부 헤더 오류 -> SyntaxError, 헤더가 터무니없는 크기를 주장 -> DecompressionBombError
        raise ValueError(f"이미지 프레임을 디코딩하지 못했습니다: {exc}") from exc
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _decode_exr(data):
    # IMREAD_COLOR는 쓰지 않는다: cv2 4.6.0은 단일 채널 EXR을 그것으로 읽으면 오류 없이 쓰레기 값을 준다
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
    if frame is None:
        raise ValueError("EXR 프레임을 디코딩하지 못했습니다")
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.shape[2] == 4:
        frame = frame[:, :, :3]  # BGRA의 알파는 버린다
    elif frame.shape[2] != 3:
        raise ValueError(f"지원하지 않는 EXR 채널 수: {frame.shape[2]}")
    return np.ascontiguousarray((np.clip(frame, 0.0, 1.0) * 255).astype(np.uint8))


def _log(line):
    print(f"{LOG_PREFIX} {line}", flush=True)


def _list_folder(folder, base):
    """folder의 파일 중 프레임 후보 이름들과 짝 영상 {확장자: 이름} — 폴더를 한 번만 읽음 (정렬해서 순서가 늘 같게)."""
    with os.scandir(folder) as entries:
        names = sorted(entry.name for entry in entries if _may_matter(entry.name, base) and entry.is_file())
    frames = [name for name in names if os.path.splitext(name)[1][1:].lower() in SEQ_EXTENSIONS]
    paired = {}
    for name in names:
        stem, dot_ext = os.path.splitext(name)
        if stem == base and dot_ext[1:].lower() in PAIRED_MOVIE_EXTS:
            paired.setdefault(dot_ext[1:].lower(), name)
    return frames, paired


def _may_matter(name, base):
    """파일인지 확인할 가치가 있는 이름인지 (이미지 확장자이거나 base의 짝 영상) — 느린 폴더에서 확인 횟수를 줄이는 걸러내기."""
    stem, dot_ext = os.path.splitext(name)
    ext = dot_ext[1:].lower()
    return ext in SEQ_EXTENSIONS or (stem == base and ext in PAIRED_MOVIE_EXTS)


def _frames_by_number(seq, frame_names):
    """{프레임 번호: 폴더에 실제로 있는 파일 이름} — 이름을 합성하지 않으므로 `.TGA`처럼 확장자 대소문자가 달라도 찾음."""
    pattern = re.compile(re.escape(seq.base) + "-([0-9]{%d})" % seq.pad + r"\." + "(?i:" + re.escape(seq.ext) + ")")
    by_number = {}
    for name in frame_names:
        match = pattern.fullmatch(name)
        if match:
            by_number.setdefault(int(match.group(1)), name)
    return by_number


def _paired_fps(folder, paired):
    """짝 영상(.mov 먼저, 없으면 .mp4)의 fps를 cv2로 한 번 읽음. 짝이 없거나 못 읽으면 DEFAULT_FPS."""
    for ext in PAIRED_MOVIE_EXTS:
        if ext not in paired:
            continue
        path = os.path.join(folder, paired[ext])
        movie = cv2.VideoCapture(path)
        try:
            fps = movie.get(cv2.CAP_PROP_FPS) if movie.isOpened() else 0.0
        finally:
            movie.release()
        if fps > 0:
            return float(fps)
        _log(f"짝 영상의 fps를 읽지 못함 (다음 후보로): {path}")
    return DEFAULT_FPS


def _read_frame_file(path):
    with open(path, "rb") as f:
        return f.read()


# 프레임 하나를 읽다 생길 수 있는 실패: 파일이 없어짐·NAS 순단(OSError), 깨진 파일(ValueError), 디코더 내부 오류(cv2.error)
_READ_ERRORS = (OSError, ValueError, cv2.error)


def _load_frame(path, ext, name):
    """프레임 파일 하나를 읽고 디코드 — 선읽기 워커와 호출 스레드가 같이 쓰는 유일한 경로 (락 밖에서 부름).

    돌려주는 배열은 쓰기 금지: 버퍼와 `_last`가 같이 들고 있으므로 호출자에게는 사본을 준다."""
    data = _read_frame_file(path)
    try:
        frame = decode_frame(data, ext)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc
    frame.flags.writeable = False
    return frame


def _format_error(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()


class _DaemonPool:
    """데몬 스레드로 도는 작은 작업 풀: 일이 밀리는 만큼만 스레드를 늘려 max_threads까지, 만든 스레드는 놀 때 잠든다.

    concurrent.futures.ThreadPoolExecutor를 쓰지 않는 이유: 그 스레드는 데몬이 아니라서, 끊긴 SMB 읽기에 걸린 작업 하나가
    인터프리터 종료를 (Windows에서 최대 ~21초) 막는다. 여기 스레드는 데몬이라 읽다 만 채로 프로세스가 끝나도 된다.
    """

    def __init__(self, max_threads, name):
        self._max = max_threads
        self._name = name
        self._cond = threading.Condition()
        self._queue = collections.deque()
        self._threads = 0
        self._unfinished = 0  # 맡겨졌지만 끝나지 않은 작업 (줄 서 있는 것 + 도는 것)

    def submit(self, task):
        with self._cond:
            self._queue.append(task)
            self._unfinished += 1
            if self._threads < min(self._max, self._unfinished):
                self._threads += 1
                threading.Thread(target=self._work, name=f"{self._name}-{self._threads}", daemon=True).start()
            else:
                self._cond.notify_all()

    def wait_idle(self, timeout):
        """맡긴 작업이 모두 끝날 때까지 기다림 (시험용). 끝났으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: self._unfinished == 0, timeout)

    def _work(self):
        while True:
            with self._cond:
                while not self._queue:
                    self._cond.wait()
                task = self._queue.popleft()
            try:
                task()
            except Exception:
                traceback.print_exc()  # 작업이 스스로 처리하지 못한 버그: 삼키지 않고 스택 트레이스를 내되 스레드는 살려 둔다
            finally:
                with self._cond:
                    self._unfinished -= 1
                    self._cond.notify_all()


_POOL = _DaemonPool(POOL_MAX_THREADS, POOL_THREAD_NAME)  # 살아 있는 모든 캡처가 공유
# 살아 있는 캡처들의 버퍼·예산 장부를 지키는 락 하나. 락 안에서는 사전·집합만 만지고 파일 읽기·디코드·로그 출력은 하지 않는다
# (끊긴 NAS 읽기가 GUI 스레드의 read·set·release를 붙잡지 않게).
_LOCK = threading.Lock()
_LIVE = weakref.WeakSet()  # release하지 않고 버려진 캡처는 예산에서 저절로 빠진다


class ImageSequenceCapture:
    """이미지 시퀀스를 cv2.VideoCapture 자리에 꽂는 캡처 — read·isOpened·release·get·set의 의미가 cv2와 같다.

    read()는 다음 프레임을 돌려주고 pos를 1 올림(끝이면 (False, None), pos 그대로), set(CAP_PROP_POS_FRAMES, n)은 0부터 센
    n번째 프레임 직전에 위치(0~프레임 수로 잘라냄), get(CAP_PROP_POS_FRAMES)는 다음에 읽을 인덱스. 못 연 캡처·release한
    캡처는 cv2처럼 isOpened False, read (False, None), get 0.0, set False.

    identity_path는 시퀀스의 가상 경로(`<폴더>/<base>.seq`). 폴더를 한 번 읽어 그 base의 프레임을 다시 찾는다 (파일 목록·
    빠진 번호는 이 객체 안에만 있고 release하면 버림). 폴더를 읽지 못하면 OSError가 그대로 올라간다 (base가 없을 때만 못 연 캡처).
    인덱스 i는 파일 번호 first+i (시작 번호가 0001이 아니어도 됨). 파일이 빠진 인덱스는 그 앞의 가장 가까운 있는 프레임을 돌려줌.

    열 때의 실패(첫 프레임을 못 읽음 등)는 예외로 올라오지만, read() 도중 프레임 하나를 못 읽으면(OSError·ValueError·cv2.error)
    예외 없이 직전에 돌려준 프레임을 유지하고 위치는 전진하며, 스택 트레이스째 로그에 남긴다 (프레임 번호당 한 번).

    선읽기: 앞쪽 프레임을 공유 데몬 스레드 풀이 미리 디코드해 `_buffer`(파일 순번 -> 프레임)에 둔다. 버퍼에는 현재 위치 뒤
    KEEP_BEHIND장과 앞쪽이 들어가고, 살아 있는 캡처 전체의 합이 PREFETCH_BUDGET_FRAMES를 넘지 않는다. read()는 버퍼에 있으면
    디코드 없이, 없으면 호출 스레드가 한 번만 동기 디코드한다 (워커를 기다리지 않음). 해상도 불일치 검사와 `_last` 갱신은 늘 read()
    안에서 하므로, 선읽기가 있든 없든 같은 호출열이면 같은 결과다. 위치가 바뀌는 set()은 세대를 올려 이전 작업을 무효로 하고,
    release()는 버퍼·진행 중 작업을 비운다.
    """

    def __init__(self, identity_path):
        if not is_sequence_path(identity_path):
            raise ValueError(f"시퀀스의 가상 경로(.seq)가 아닙니다: {identity_path!r}")
        self._dir, filename = os.path.split(identity_path)
        self._base = filename[:-len(SEQ_SUFFIX)]
        self._gen = 0  # 세대 카운터: _reset이 되돌리지 않는다 (release 전 세대의 작업이 다시 유효해지면 안 됨)
        self._cond = threading.Condition(_LOCK)  # 선읽기 작업 수가 바뀔 때 알림 (시험용 대기)
        self._reset()
        self._open()

    def _reset(self):
        """닫힌 상태로 (파일 목록·버퍼도 비움). release()는 _LOCK을 잡고 부른다."""
        self._opened = False
        self._pos = 0
        self._count = 0
        self._first = 0
        self._ext = ""
        self._numbers = []  # 폴더에 있는 프레임 번호 (오름차순)
        self._names = []  # _numbers와 같은 순서의 실제 파일 이름
        self._fps = 0.0
        self._width = 0
        self._height = 0
        self._last = None  # 마지막으로 돌려준 정상 크기 프레임 (해상도가 다른·못 읽은 프레임 대신 줌). 버퍼와 같은 쓰기 금지 배열
        self._logged_missing = False
        self._logged_mismatch = False
        self._buffer = {}  # 슬롯(_numbers 안의 자리) -> 디코드된 프레임. 빠진 번호 구간은 앞 파일의 슬롯 하나를 같이 씀
        self._inflight = set()  # 지금 세대에서 풀에 맡겨 둔 슬롯
        self._failed = set()  # 선읽기가 실패한 슬롯 (같은 세대에서 되풀이해 맡기지 않음 — 재생이 닿으면 read가 다시 시도)
        self._failure_logged = set()  # 읽기 실패를 로그에 남긴 파일 번호 (프레임당 한 번)

    def _open(self):
        frame_names, paired = _list_folder(self._dir, self._base)
        found = [seq for seq in group_sequences(self._dir, frame_names) if seq.base == self._base]
        if not found:
            _log(f"시퀀스를 열 수 없음: {self._dir} 에 '{self._base}-<번호>' 프레임이 2장 이상 없음")
            return
        seq = found[0]
        if len(found) > 1:
            _log(f"같은 이름 '{self._base}'의 시퀀스가 여러 개({len(found)}) — 첫 묶음({seq.ext}, {seq.pad}자리)을 엶: {self._dir}")
        by_number = _frames_by_number(seq, frame_names)
        self._numbers = sorted(by_number)
        self._names = [by_number[number] for number in self._numbers]
        self._first = seq.first
        self._count = seq.last - seq.first + 1
        self._ext = seq.ext
        self._fps = _paired_fps(self._dir, paired)
        first_frame = self._decode(self._names[0])  # 인덱스 0 = 가장 작은 번호 (없는 번호일 수 없음)
        self._height, self._width = first_frame.shape[:2]
        self._last = first_frame
        with _LOCK:
            self._opened = True
            _LIVE.add(self)
            for capture in _LIVE:  # 몫이 줄어든 다른 캡처를 먼저 줄여, 합이 예산을 넘는 순간이 없게
                capture._trim_locked()
            self._store_locked(self._gen, 0, first_frame)  # 열 때 디코드한 첫 프레임이 버퍼의 씨앗 (read가 다시 디코드하지 않음)
            self._pump_locked()

    def _decode(self, name):
        return _load_frame(os.path.join(self._dir, name), self._ext, name)

    def isOpened(self):
        return self._opened

    def read(self):
        with _LOCK:
            if not self._opened or self._pos >= self._count:
                return False, None
            gen, index = self._gen, self._pos
            number = self._first + index
            slot = self._slot_of(index)
            file_number, name = self._numbers[slot], self._names[slot]
            path, ext = os.path.join(self._dir, name), self._ext
            frame = self._buffer.get(slot)
            announce_missing = file_number != number and not self._logged_missing
            if announce_missing:
                self._logged_missing = True
        if announce_missing:
            _log(f"{self._base}: 빠진 프레임이 있어 직전 프레임을 유지합니다 (처음 만난 번호 {number}): {self._dir}")
        error = None
        if frame is None:  # 버퍼 미스: 호출 스레드가 동기 디코드 한 번 (워커가 끝나길 기다리지 않음)
            try:
                frame = _load_frame(path, ext, name)
            except _READ_ERRORS as exc:
                error = exc
        announce_failure = announce_mismatch = False
        with _LOCK:
            if not self._opened:  # 읽는 사이 다른 스레드가 release했다
                return False, None
            if error is not None:
                shown = self._last
                announce_failure = file_number not in self._failure_logged
                self._failure_logged.add(file_number)
            else:
                if slot not in self._buffer:
                    self._store_locked(gen, slot, frame)
                if frame.shape[:2] != (self._height, self._width):
                    shown = self._last
                    announce_mismatch = not self._logged_mismatch
                    self._logged_mismatch = True
                else:
                    self._last = shown = frame
            if self._gen == gen:  # 읽는 사이 다른 스레드가 위치를 옮기지 않았을 때만 전진
                self._pos = index + 1
            self._pump_locked()
        if announce_failure:
            _log(f"{self._base}: {name} 읽기 실패 — 직전 프레임을 유지하고 이어갑니다 (프레임 {file_number}): {self._dir}\n"
                 f"{_format_error(error)}")
        if announce_mismatch:
            _log(f"{self._base}: {name}의 해상도 {frame.shape[1]}x{frame.shape[0]}가 첫 프레임 "
                 f"{self._width}x{self._height}와 달라 직전 프레임을 유지합니다: {self._dir}")
        return True, shown.copy()  # cv2처럼 읽을 때마다 새 배열 (버퍼의 배열은 호출자에게 주지 않음)

    def get(self, prop):
        if not self._opened:
            return 0.0
        values = {
            cv2.CAP_PROP_FPS: self._fps,
            cv2.CAP_PROP_FRAME_COUNT: self._count,
            cv2.CAP_PROP_POS_FRAMES: self._pos,
            cv2.CAP_PROP_FRAME_WIDTH: self._width,
            cv2.CAP_PROP_FRAME_HEIGHT: self._height,
        }
        return float(values.get(prop, 0.0))

    def set(self, prop, value):
        with _LOCK:
            if not self._opened or prop != cv2.CAP_PROP_POS_FRAMES:
                return False
            target = min(max(int(value), 0), self._count)  # cv2처럼 소수는 버리고 0~프레임 수로 잘라냄
            if target != self._pos:
                self._pos = target
                self._gen += 1  # 이전 위치 기준으로 맡긴 선읽기는 끝나도 버려진다
                self._inflight.clear()
                self._failed.clear()
                self._trim_locked()
                self._cond.notify_all()
            return True

    def release(self):
        with _LOCK:
            self._gen += 1  # 읽던 워커가 끝나도 이 객체에 아무것도 하지 않는다
            _LIVE.discard(self)
            self._reset()
            self._cond.notify_all()

    # --- 선읽기 (아래 _locked로 끝나는 메서드는 _LOCK을 잡은 채로만 부른다) ---

    def _wait_prefetch_idle(self, timeout):
        """맡겨 둔 선읽기가 모두 끝날 때까지 기다림 (시험용). 끝났으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._inflight, timeout)

    def _slot_of(self, index):
        """프레임 인덱스가 가리키는 파일의 슬롯 — 번호가 빠졌으면 그 앞의 가장 가까운 있는 파일."""
        return bisect.bisect_right(self._numbers, self._first + index) - 1

    def _window_locked(self):
        """(lo, anchor, hi): 버퍼에 둘 슬롯 범위 [lo, hi)와 다음에 읽을 슬롯 anchor.

        용량은 예산을 살아 있는 캡처 수로 나눈 몫(내림)이라 캡처들의 합이 예산을 넘지 않는다."""
        live = len(_LIVE)
        capacity = PREFETCH_BUDGET_FRAMES // live if live else 0
        behind = min(KEEP_BEHIND, capacity // 2)
        total = len(self._numbers)
        anchor = self._slot_of(self._pos) if self._pos < self._count else total
        lo = max(0, anchor - behind)
        return lo, anchor, min(total, lo + capacity)

    def _in_window_locked(self, slot):
        lo, _, hi = self._window_locked()
        return lo <= slot < hi

    def _trim_locked(self, window=None):
        lo, _, hi = window or self._window_locked()
        for slot in [s for s in self._buffer if not lo <= s < hi]:
            del self._buffer[slot]
        self._failed.intersection_update(range(lo, hi))

    def _store_locked(self, gen, slot, frame):
        """frame을 버퍼에 둔다 — 세대가 같고 창 안이고 아직 없을 때만 (늦게 끝난 옛 결과·예산 밖 결과는 버림)."""
        if gen != self._gen or not self._opened or slot in self._buffer or not self._in_window_locked(slot):
            return
        self._buffer[slot] = frame
        self._failed.discard(slot)

    def _pump_locked(self):
        """창 안에서 버퍼에도 작업에도 없는 슬롯을 다음에 읽을 것부터 풀에 맡긴다 (캡처당 PREFETCH_WORKERS개까지)."""
        if not self._opened:
            return
        window = self._window_locked()
        self._trim_locked(window)
        _, anchor, hi = window
        for slot in range(anchor, hi):
            if len(self._inflight) >= PREFETCH_WORKERS:
                break
            if slot in self._buffer or slot in self._inflight or slot in self._failed:
                continue
            self._inflight.add(slot)
            name = self._names[slot]
            _POOL.submit(functools.partial(self._prefetch, self._gen, slot, self._numbers[slot], name,
                                           os.path.join(self._dir, name), self._ext))

    def _prefetch(self, gen, slot, file_number, name, path, ext):
        """풀 스레드에서 도는 선읽기 한 건. 파일 읽기·디코드는 락 밖에서 하고, 결과는 세대가 맞을 때만 버퍼에 넣는다.

        읽기 실패는 삼키지 않고 스택 트레이스째 로그에 남긴다 (프레임당 한 번 — read의 실패 로그와 같은 장부).
        그 슬롯은 비워 두고, 재생이 거기 닿을 때 read가 다시 읽어 본다."""
        with _LOCK:
            if gen != self._gen:
                return  # 그 사이 seek·release로 무효가 됨: 이 객체에 아무것도 하지 않는다
            if not self._in_window_locked(slot):
                self._inflight.discard(slot)
                self._cond.notify_all()
                return
        frame = error = None
        try:
            frame = _load_frame(path, ext, name)
        except _READ_ERRORS as exc:
            error = exc
        except Exception:
            with _LOCK:  # 예상 밖의 버그: 장부만 정리하고 풀이 스택 트레이스를 내도록 올려보냄
                if gen == self._gen:
                    self._inflight.discard(slot)
                    self._failed.add(slot)
                    self._cond.notify_all()
            raise
        announce = False
        with _LOCK:
            if gen != self._gen:
                return
            self._inflight.discard(slot)
            if error is None:
                self._store_locked(gen, slot, frame)
                self._pump_locked()
            else:
                self._failed.add(slot)
                announce = file_number not in self._failure_logged
                self._failure_logged.add(file_number)
            self._cond.notify_all()
        if announce:
            _log(f"{self._base}: {name} 선읽기 실패 — 재생이 이 프레임에 닿으면 다시 읽어 보고, 안 되면 직전 프레임을 유지합니다 "
                 f"(프레임 {file_number}): {self._dir}\n{_format_error(error)}")


def open_any_capture(path):
    """시퀀스의 가상 경로(.seq)면 ImageSequenceCapture, 아니면 cv2.VideoCapture."""
    if is_sequence_path(path):
        return ImageSequenceCapture(path)
    return cv2.VideoCapture(path)
