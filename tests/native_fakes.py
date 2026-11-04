"""가짜 네이티브 프레임·캡처와 그것을 꽂은 플레이어 픽스처 — VideoToolbox·PyObjC 없이(어느 플랫폼에서나) 플레이어의 네이티브 분기를 시험한다.

- SpyNativeArray: frame_handles.wrap_native로 작은 진짜 버퍼(기본 16×8 BGRX, 행 끝 패딩 — IOSurface처럼 strided 뷰, 읽기 전용)에 가짜 손잡이를 단
  NativeFrameArray 하위 클래스. 파이썬 쪽에서 픽셀 값에 닿는 길 — 원소·조각 인덱싱(__getitem__), 반복, __array__, ufunc(산술·비교·sum 등),
  numpy 함수(np.copy·np.zeros_like 등 — 메모리 바운드만 보는 may_share_memory·shares_memory는 뺌: frame_handles의 손잡이 전파가 부름),
  tobytes·tolist·item·copy·astype·.data·.flat·쓰기 — 를 지날 때마다 공유 기록(list)에 그 길의 이름을 남긴다. C 확장이 버퍼를 직접 읽는 것
  (cv2 함수·memoryview·QImage)과 np.asarray(ndarray 하위 클래스는 __array__를 부르지 않음)는 파이썬에서 가로챌 수 없다 — 그래서 픽스처가
  cv2.cvtColor를 바꿔치기해 네이티브 프레임을 받은 호출을 따로 센다(플레이어가 쓰는 cv2 픽셀 함수는 재생·탐색 길에서 cvtColor뿐).
- FakeNativeCapture: cv2.VideoCapture 계약(read/get/set/isOpened/release) — mac_native_source.NativeVTCapture와 같은 낱말.
- 픽스처: fake_native_player(만드는 함수), player_with_fake_native(A만), player_with_fake_native_ab(A·B, 와이프 체크 켬 — 축은 시험이 고름).
  셋 다 NativeRig(SimpleNamespace)를 돌려준다: player, cap_a, cap_b, reads(파이썬 픽셀 접근), cvt_calls(네이티브 프레임을 받은 cvtColor),
  sides(스트림 아이템의 set_sides 호출 — 진짜 set_sides로 그대로 넘기며 기록; 픽스맵 아이템이면 늘 빈 목록).

다른 시험 파일에서 쓸 때: `from tests.native_fakes import new_player, player_with_fake_native  # noqa: F401` — 픽스처가 요청하는 new_player도
함께 가져와야 한다(pytest는 픽스처 이름을 시험 모듈의 이름 공간·conftest에서 찾음; dialogs·qapp은 conftest에 있음).
"""

import math
import os
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PyQt5.QtCore import QTimer

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: 픽스처 — 위 docstring)
from yesoncheck.frame_handles import BYTES_PER_PIXEL, NativeFrameArray, NativeHandle, wrap_native
from yesoncheck.gl_video_item import VIDEO_ITEM_ENV
from yesoncheck.video_widget import VIEWPORT_ENV

FAKE_WIDTH, FAKE_HEIGHT = 16, 8
FAKE_FPS = 24.0
FAKE_FRAME_COUNT = 64  # OCR 검토 창 미리보기의 건너뜀 문턱(frame_skip_threshold 10 × 5 = 50)보다 멀리 탐색할 수 있게
SIDE_TAGS = {"A": 0, "B": 128}  # 프레임 G 값에 더하는 면 표시 — 화면 그림에서 A·B를 가름
IDLE_TIMER_MS = 600000  # 재생 타이머 간격 — 저절로는 울리지 않고 시험이 next_frame_playback을 직접 부름
_NOT_PIXEL_READS = frozenset({np.may_share_memory, np.shares_memory})  # 메모리 바운드만 비교 — 픽셀을 읽지 않음


def fake_bgr(index, x, y, side="A"):
    """가짜 프레임 index의 (x, y) 픽셀 (B, G, R) — B = 번호, G = 행·면 표시, R = 열 (행 간격·바이트 순서가 어긋나면 다른 값이 나옴)."""
    return index % 256, (y * 16 + SIDE_TAGS[side]) % 256, (x * 8) % 256


class SpyNativeArray(NativeFrameArray):
    """픽셀 접근을 기록하는 가짜 네이티브 프레임 (모듈 설명). reads: 접근 기록(list) — spy_frames가 붙이고 같은 메모리의 뷰가 물려받는다."""

    reads = None

    def __array_finalize__(self, obj):
        super().__array_finalize__(obj)
        self.reads = getattr(obj, "reads", None)

    def _read(self, kind):
        if self.reads is not None:
            self.reads.append(kind)

    def __getitem__(self, key):
        self._read(f"[{key!r}]")
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self._read(f"[{key!r}] =")
        return super().__setitem__(key, value)

    def __iter__(self):
        self._read("iter")
        return super().__iter__()

    def __array__(self, *args, **kwargs):
        self._read("__array__")
        return super().__array__(*args, **kwargs)

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        self._read(f"ufunc {ufunc.__name__}.{method}")
        plain = tuple(i.view(np.ndarray) if isinstance(i, SpyNativeArray) else i for i in inputs)
        if "out" in kwargs:
            kwargs["out"] = tuple(o.view(np.ndarray) if isinstance(o, SpyNativeArray) else o for o in kwargs["out"])
        return getattr(ufunc, method)(*plain, **kwargs)

    def __array_function__(self, func, types, args, kwargs):
        if func not in _NOT_PIXEL_READS:
            self._read(f"np.{func.__name__}")
        return super().__array_function__(func, types, args, kwargs)

    def tobytes(self, order="C"):
        self._read("tobytes")
        return super().tobytes(order)

    def tolist(self):
        self._read("tolist")
        return super().tolist()

    def item(self, *args):
        self._read("item")
        return super().item(*args)

    def copy(self, order="C"):
        self._read("copy")
        return super().copy(order)

    def astype(self, *args, **kwargs):
        self._read("astype")
        return super().astype(*args, **kwargs)

    @property
    def data(self):
        self._read(".data")
        return np.ndarray.data.__get__(self)

    @property
    def flat(self):
        self._read(".flat")
        return np.ndarray.flat.__get__(self)


def spy_frames(count, reads, side="A", width=FAKE_WIDTH, height=FAKE_HEIGHT):
    """가짜 네이티브 프레임 count장 — 프레임마다 자기 버퍼((높이, 행 바이트) uint8 — 행 바이트는 너비×4 + 16(패딩 0), 읽기 전용 — 진짜 캡처처럼
    쓰면 ValueError)와 가짜 손잡이(iosurface는 가짜 정수, keepalive는 그 버퍼). 픽셀은 fake_bgr, 넷째 바이트(X)는 255. reads: 모든 프레임이 함께
    쓰는 접근 기록. 4K 크기(너비 ≥ 3840 또는 높이 ≥ 2160 — optimize_for_4k의 4K 갈래와 같은 기준)면 메모리를 아끼려고 모든 행이 한 행을 함께 씀(행 간격 0 —
    모양·strides는 표면 전체 그대로라 whole_surface_handle이 통과; 픽셀 값은 0행의 것)."""
    row_bytes = width * BYTES_PER_PIXEL + 16
    shared_rows = width >= 3840 or height >= 2160
    ys, xs = np.mgrid[0:1 if shared_rows else height, 0:width]
    frames = []
    for index in range(count):
        rows = np.zeros((ys.shape[0], row_bytes), np.uint8)
        b, g, r = fake_bgr(index, xs, ys, side)
        pixels = rows[:, : width * BYTES_PER_PIXEL].reshape(ys.shape[0], width, BYTES_PER_PIXEL)
        pixels[..., 0], pixels[..., 1], pixels[..., 2], pixels[..., 3] = b, g, r, 255
        raw = np.lib.stride_tricks.as_strided(rows, (height, row_bytes), (0, 1)) if shared_rows else rows
        raw.flags.writeable = False
        handle = NativeHandle(iosurface=0x5EED0000 + index, width=width, height=height, index=index, keepalive=raw)
        frame = wrap_native(raw, handle).view(SpyNativeArray)
        frame.reads = reads
        frames.append(frame)
    return frames


class FakeNativeCapture:
    """cv2.VideoCapture 계약의 가짜 네이티브 캡처 (NativeVTCapture와 같은 낱말): read()는 다음 프레임 — 같은 번호면 같은 객체(진짜의 링처럼) —
    을 주고 pos를 1 올리며, 끝에서는 (False, None)·pos 그대로. set(CAP_PROP_POS_FRAMES)은 목표만 기록(지연 — get은 곧바로 그 값, 0~알리는 장 수로
    자르고 소수 버림, NaN·무한은 0)하고 다음 read가 그 자리로. get: FPS·FRAME_COUNT·크기, 그 밖 0.0. release 뒤 isOpened False·read (False, None)·
    get 0.0·set False.

    frames: 내줄 프레임(spy_frames). reported_count: FRAME_COUNT로 알릴 값(기본 len(frames) — 더 크게 주면 프레임 수를 부풀려 알리는 cv2 영상처럼
    끝을 읽기 실패로 알게 됨). 시험용: restart_count(read가 스트림 위치가 아닌 곳으로 옮겨 간 횟수 — 탐색이 일어났는지)."""

    def __init__(self, frames, reported_count=None):
        self.frames = list(frames)
        self.reported_count = len(self.frames) if reported_count is None else reported_count
        self.restart_count = 0
        self._pos = 0
        self._target = None
        self._open = True
        height, width = self.frames[0].shape[:2]
        self._props = {cv2.CAP_PROP_FPS: FAKE_FPS, cv2.CAP_PROP_FRAME_COUNT: self.reported_count,
                       cv2.CAP_PROP_FRAME_WIDTH: width, cv2.CAP_PROP_FRAME_HEIGHT: height}

    def isOpened(self):  # noqa: N802 (cv2 이름)
        return self._open

    def read(self):
        if not self._open:
            return False, None
        n = self._pos if self._target is None else self._target
        self._target = None
        if n != self._pos:
            self.restart_count += 1
        if n >= len(self.frames):
            self._pos = n
            return False, None
        self._pos = n + 1
        return True, self.frames[n]

    def get(self, prop):
        if not self._open:
            return 0.0
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return float(self._pos if self._target is None else self._target)
        return float(self._props.get(prop, 0.0))

    def set(self, prop, value):
        number = float(value)
        if not self._open or prop != cv2.CAP_PROP_POS_FRAMES:
            return False
        self._target = min(max(int(number), 0), self.reported_count) if math.isfinite(number) else 0
        return True

    def release(self):
        self._open = False


@pytest.fixture
def fake_native_player(new_player, dialogs, tmp_path, qapp, monkeypatch):  # noqa: F811 (new_player: 픽스처)
    """가짜 네이티브 캡처를 꽂은 VideoPlayer를 만드는 함수 → NativeRig (모듈 설명).

    make(ab=False, viewport="gl", video_item=None, count=FAKE_FRAME_COUNT, reported_count=None, size=(FAKE_WIDTH, FAKE_HEIGHT), native="AB"):
    - viewport·video_item: YESONCHECK_VIEWPORT·YESONCHECK_VIDEO_ITEM (None이면 지움). 기본은 GL 뷰포트 + 스트림 아이템(VideoFrameItem) —
      Apple Silicon 네이티브 재생의 기본 길(offscreen은 GL 컨텍스트가 없지만 창을 띄우지 않으므로 paint는 일어나지 않음).
      ("gl", "pixmap") = 킬 스위치(GL 뷰포트 + 픽스맵 아이템), ("raster", None) = raster 뷰포트(픽스맵 아이템).
    - 플레이어의 영상 캡처 열기 자리(_open_movie_capture)를 가짜 캡처로 바꿔 open_file로 엶 — 열기 뒤 첫 프레임 표시(display_first_frame →
      seek_to_frame(1))까지 진짜 길 그대로라 frame_a는 첫 read()의 프레임. 소리 재생기가 열 진짜 영상 파일을 하나 만들어 그 경로로 연다(프레임은 가짜).
    - ab=True: B도 같은 식으로 열고 와이프 체크를 켠 뒤 처음으로 다시 탐색(B의 0번까지 읽어 둠) — X·Y 축은 끈 채로.
    - size: 가짜 프레임 (너비, 높이) — 4K(3840×2160)면 행을 함께 쓰는 프레임(spy_frames). native: 가짜 네이티브로 열 면 — 빠진 면은 진짜 열기
      길(cv2 캡처 — 소리용으로 만든 같은 크기의 시험 영상, RGB 프레임; 혼합 비교 h264 대 ProRes 흉내).
    - 재생 중 상태: 타이머를 켜 둠 — timer.start를 바꿔치기해 어떤 간격으로 켜도(play_video·반복 재생) IDLE_TIMER_MS라 저절로 울리지 않음.
    - cv2.cvtColor 바꿔치기: 네이티브 프레임(SpyNativeArray)을 받은 호출을 cvt_calls에 (code) 기록하고 진짜로 부름."""
    real_cvt = cv2.cvtColor

    def make(ab=False, viewport="gl", video_item=None, count=FAKE_FRAME_COUNT, reported_count=None, size=(FAKE_WIDTH, FAKE_HEIGHT),
             native="AB"):
        monkeypatch.setenv(VIEWPORT_ENV, viewport)
        if video_item is None:
            monkeypatch.delenv(VIDEO_ITEM_ENV, raising=False)
        else:
            monkeypatch.setenv(VIDEO_ITEM_ENV, video_item)
        rig = SimpleNamespace(player=None, cap_a=None, cap_b=None, reads=[], cvt_calls=[], sides=[])

        def counting_cvt(src, code, *args, **kwargs):
            if isinstance(src, SpyNativeArray):
                rig.cvt_calls.append(code)
            return real_cvt(src, code, *args, **kwargs)

        monkeypatch.setattr(cv2, "cvtColor", counting_cvt)
        player = rig.player = new_player(make_config(str(tmp_path), {}))
        widget = player.videoWidget
        if widget.video_item_stream:
            real_sides = widget.video_item.set_sides

            def recording_sides(a, b, axis, ratio):
                rig.sides.append(SimpleNamespace(a=a, b=b, axis=axis, ratio=ratio))
                return real_sides(a, b, axis, ratio)

            monkeypatch.setattr(widget.video_item, "set_sides", recording_sides)
        sides = {}  # 파일 이름 → 면(A·B) — open_file이 경로를 정규화해 넘기므로 이름으로 가름

        real_open = player._open_movie_capture

        def open_capture(path):  # 플레이어의 영상 캡처 열기 자리 — 진짜 길에서는 여기서 네이티브 캡처가 열림
            side = sides[os.path.basename(path)]
            if side not in native:
                return real_open(path)
            return FakeNativeCapture(spy_frames(count, rig.reads, side, *size), reported_count)

        monkeypatch.setattr(player, "_open_movie_capture", open_capture)
        for side in ("A", "B") if ab else ("A",):
            frames = count if side not in native else 2  # 진짜로 열 면은 가짜와 같은 장 수·크기
            path = write_test_video(str(tmp_path / f"clip_{side.lower()}.mov"), frames=frames, size=size)
            sides[os.path.basename(path)] = side
            assert player.open_file(side, path) is True
        rig.cap_a, rig.cap_b = player.cap_a, player.cap_b
        for side, cap in (("A", rig.cap_a), ("B", rig.cap_b)) if ab else (("A", rig.cap_a),):
            assert isinstance(cap, FakeNativeCapture) == (side in native), (side, type(cap))
        if ab:
            player.wipeCheckBox.setChecked(True)
            assert widget.wipeEnabled and not (widget.wipe_enabled_x or widget.wipe_enabled_y)
            player.seek_to_frame(1)  # 와이프를 켠 뒤 처음으로 다시 — B도 읽어 둠(frame_b = B의 0번; 켜기만 하면 B는 다음 탐색까지 없음)
        monkeypatch.setattr(player.timer, "start", lambda *args: QTimer.start(player.timer, IDLE_TIMER_MS))
        player.timer.start()
        return rig

    return make


@pytest.fixture
def player_with_fake_native(fake_native_player):
    """A만 가짜 네이티브 캡처로 연 플레이어(GL 뷰포트 + 스트림 아이템, 재생 중, 첫 프레임 표시) → NativeRig."""
    return fake_native_player()


@pytest.fixture
def player_with_fake_native_ab(fake_native_player):
    """A·B를 가짜 네이티브 캡처로 열고 와이프 체크를 켠 플레이어(축은 꺼짐 — 시험이 wipeXButton·wipeYButton으로 고름) → NativeRig."""
    return fake_native_player(ab=True)
