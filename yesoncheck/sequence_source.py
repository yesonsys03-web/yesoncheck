"""이미지 시퀀스의 프레임 읽기: 한 장 디코딩(decode_frame)과 cv2.VideoCapture 자리에 꽂는 캡처(ImageSequenceCapture).

tga·png·jpg·jpeg·tif·tiff는 PIL로 읽는다: 번들된 cv2 4.6.0과 Qt는 RLE 압축 TGA를 못 읽는다.
exr은 자리만 잡아 둔 경로(OpenCV, 0~1 잘라내기만 하고 톤매핑은 하지 않음).
"""

import bisect
import io
import os
import re

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


class ImageSequenceCapture:
    """이미지 시퀀스를 cv2.VideoCapture 자리에 꽂는 캡처 — read·isOpened·release·get·set의 의미가 cv2와 같다.

    read()는 다음 프레임을 돌려주고 pos를 1 올림(끝이면 (False, None), pos 그대로), set(CAP_PROP_POS_FRAMES, n)은 0부터 센
    n번째 프레임 직전에 위치(0~프레임 수로 잘라냄), get(CAP_PROP_POS_FRAMES)는 다음에 읽을 인덱스. 못 연 캡처·release한
    캡처는 cv2처럼 isOpened False, read (False, None), get 0.0, set False.

    identity_path는 시퀀스의 가상 경로(`<폴더>/<base>.seq`). 폴더를 한 번 읽어 그 base의 프레임을 다시 찾는다 (파일 목록·
    빠진 번호는 이 객체 안에만 있고 release하면 버림). 폴더를 읽지 못하면 OSError가 그대로 올라간다 (base가 없을 때만 못 연 캡처).
    인덱스 i는 파일 번호 first+i (시작 번호가 0001이 아니어도 됨). 파일이 빠진 인덱스는 그 앞의 가장 가까운 있는 프레임을 돌려줌.
    있는 파일을 디코드하지 못하면 ValueError(어떤 파일인지 포함)가 그대로 올라간다.
    """

    def __init__(self, identity_path):
        if not is_sequence_path(identity_path):
            raise ValueError(f"시퀀스의 가상 경로(.seq)가 아닙니다: {identity_path!r}")
        self._dir, filename = os.path.split(identity_path)
        self._base = filename[:-len(SEQ_SUFFIX)]
        self._reset()
        self._open()

    def _reset(self):
        """닫힌 상태로 (파일 목록도 비움)."""
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
        self._last = None  # 마지막으로 돌려준 정상 크기 프레임 (해상도가 다른 프레임 대신 줌)
        self._logged_missing = False
        self._logged_mismatch = False

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
        self._opened = True

    def _decode(self, name):
        with open(os.path.join(self._dir, name), "rb") as f:
            data = f.read()
        try:
            return decode_frame(data, self._ext)
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc

    def isOpened(self):
        return self._opened

    def read(self):
        if not self._opened or self._pos >= self._count:
            return False, None
        number = self._first + self._pos
        k = bisect.bisect_right(self._numbers, number) - 1  # 번호 이하에서 가장 큰, 폴더에 있는 번호
        name = self._names[k]
        if self._numbers[k] != number and not self._logged_missing:
            self._logged_missing = True
            _log(f"{self._base}: 빠진 프레임이 있어 직전 프레임을 유지합니다 (처음 만난 번호 {number}): {self._dir}")
        frame = self._decode(name)
        if frame.shape[:2] != (self._height, self._width):
            if not self._logged_mismatch:
                self._logged_mismatch = True
                _log(f"{self._base}: {name}의 해상도 {frame.shape[1]}x{frame.shape[0]}가 첫 프레임 "
                     f"{self._width}x{self._height}와 달라 직전 프레임을 유지합니다: {self._dir}")
            frame = self._last.copy()
        else:
            self._last = frame
        self._pos += 1
        return True, frame

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
        if not self._opened or prop != cv2.CAP_PROP_POS_FRAMES:
            return False
        self._pos = min(max(int(value), 0), self._count)  # cv2처럼 소수는 버리고 0~프레임 수로 잘라냄
        return True

    def release(self):
        self._reset()


def open_any_capture(path):
    """시퀀스의 가상 경로(.seq)면 ImageSequenceCapture, 아니면 cv2.VideoCapture."""
    if is_sequence_path(path):
        return ImageSequenceCapture(path)
    return cv2.VideoCapture(path)
