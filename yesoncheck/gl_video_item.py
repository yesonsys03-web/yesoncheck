"""GL 뷰포트용 영상 프레임 아이템 VideoFrameItem과 그 선택 규칙(YESONCHECK_VIDEO_ITEM).

왜: 4K 프레임을 numpy → QImage → QPixmap → QGraphicsPixmapItem으로 넘기면 QPixmap.fromImage와 Qt 내부 텍스처 변환·업로드에
프레임당 ~48ms가 든다(31차 실측). 스트림 모드의 이 아이템은 RGB 배열을 그대로 들고 있다가 paint() 안에서 beginNativePainting →
동기 glTexSubImage2D(GL_RGB) 한 번 → 고정 기능 텍스처 사각형 → endNativePainting으로 그린다 — 스파이크 G1 경로, 현재 경로의 약 1/3이고
픽셀은 같음(평균 차 0.001·최대 차 2; 내부 저장소 docs/superpowers/records/2026-11-02-gl-stream-design/findings.md).

왜 QGraphicsPixmapItem을 상속하나: 픽스맵 아이템 자리에 그대로 들어가 계약을 물려받는다 — video_widget의 pixmap().isNull() 검사·
pixmap().width()/height()·fitInView(self.video_item, …)·boundingRect()·shape()·setTransformationMode()와 시험의 setPixmap(QPixmap(w, h))가
수정 없이 돈다. stream=False면 QGraphicsPixmapItem 그대로(paint·setPixmap 모두 부모) — raster 경로는 한 줄도 바뀌지 않는다.

**스트림 모드의 pixmap()은 크기 자리표시자다** — 그림 내용이 아니다: set_frame이 프레임 크기가 바뀔 때만 내용 없는 QPixmap(w, h)를 둬서
boundingRect·isNull 검사가 맞게 할 뿐이다. 내용이 필요하면 frame()(마지막 RGB 배열)을 쓴다.

좌표 규칙(스파이크 실측, findings 해석 5): painter.combinedTransform()은 아이템 좌표를 **물리** 픽셀로 매핑하고
painter.device().width()/height()는 **논리** 픽셀이다 → pw, ph = qRound(논리 × devicePixelRatioF()) (.5 올림 — 파이썬 round 아님, Qt의 FBO·뷰포트 크기와 같아야 1px 이음매가 없음), glViewport(0, 0, pw, ph)와
glOrtho(0, pw, ph, 0, -1, 1)(y 아래 방향 — Qt와 같음), 정점은 매핑값 그대로. 정점에 dpr을 또 곱하거나 뷰포트를 논리 크기로 잡으면
레티나에서 왼쪽 아래 1/4에 2배로 그려진다(스파이크 첫 실행).

함정(findings 해석 6): 뷰포트로 쓰인 QOpenGLWidget은 grab()도 grabFramebuffer()도 내용을 못 찍는다(paintGL이 비어 흰 그림) —
흰 그림 둘을 견주면 "차이 0"이 나온다. 실제 화면 검증은 screencapture -R(뷰포트의 전역 좌표 영역)로만.

paint 가드: PyQt5 가상 함수(paint)에서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음 — CLAUDE.md 함정)이다. 그래서 스트림 모드의
paint 본문 전체를 except BaseException으로 받아 첫 실패만 기록(트레이스백 전문, [표시]) + 오류 창(Qt 루프에서 1회 — paint 안에서 모달 금지)으로
알리고, 그 뒤 paint는 아무것도 그리지 않는다(빈 영상 영역). 재생·UI는 계속되고 탈출구는 YESONCHECK_VIDEO_ITEM=pixmap(예전 QPixmap 경로),
Mac은 Setting → 재생 디코더 → ffmpeg (예전 방식)도(그 선택이 reset_failure로 걸쇠를 풀어 다음 paint가 다시 그림 — 창 글에 그 안내 한 줄).
실패를 알릴 때마다 창 예약 바로 뒤에 실패 콜백(set_failure_callback — 위젯이 등록해 streamPaintFailed 신호로 플레이어에)도 Qt 루프로 미뤄 부른다 —
값은 그리던 그림에 IOSurface 면이 있었는가(has_native_side). Mac의 플레이어는 네이티브 면 실패면 이 창만 ffmpeg로 바꿔(바꿔 끼움 + 걸쇠 풀기) 계속하므로
(스펙 2026-11-04 §5.8 — 큰 소리 폴백) 그때 창의 첫 줄은 NATIVE_FALLBACK_LINE(나머지 줄은 같음). RGB 면 실패는 위 규칙 그대로.

IOSurface 면 그리기(set_sides·set_surface — Apple Silicon 네이티브 재생 경로): 네이티브 프레임(frame_handles — IOSurface 위의 BGRX 뷰)은 CPU로
읽거나 올리지 않고 gl_surface.CGLTexImageIOSurface2D로 GL_TEXTURE_RECTANGLE_ARB 텍스처에 그대로 묶어 그린다(복사 0, 텍스처 좌표는 픽셀 단위).
A/B 와이프는 numpy 합성 대신 A를 전체에, B를 glScissor(wipe_scissor — 물리 픽셀, GL 창 좌표라 원점이 왼쪽 아래) 안에 그린다(X·Y 와이프가 함께면
상자 둘 — 오른쪽과 아래쪽 — 에 그려 합집합, Ruling 17). 면은 네이티브(표면
전체 — frame_handles.whole_surface_handle로만 가름; 조각·뒤집힌 뷰는 ValueError)·RGB 배열(set_frame과 같은 업로드 코드, 면마다 따로 둔 2D 텍스처라
set_frame의 텍스처를 건드리지 않음)·없음(B — 검정, 기존 np.zeros_like 규칙) 중 하나. 면 텍스처는 처음 그릴 때 만들고 컨텍스트가 바뀌거나 죽으면 버린다
(다음 paint가 새 컨텍스트에서 다시 만들고 다시 묶음). 묶인 표면의 손잡이는 텍스처가 그 표면에 묶여 있는 동안 쥔다(버퍼가 풀로 돌아가 다른 프레임으로
덮이지 않게 — 다음 묶기나 컨텍스트가 죽을 때 놓음). set_frame 경로(_draw_native)의 GL 호출은 그대로다.

GL 준비(함수 묶기·텍스처)는 생성 때가 아니라 첫 paint()에서 그때 current인 위젯 컨텍스트로 한다: getProcAddress는 current 컨텍스트가
있어야 하고, 위젯의 진짜 컨텍스트(MSAA 포맷)는 첫 show 때 생긴다. GL 호출은 전부 beginNativePainting/endNativePainting 안에서만(Qt GL2
엔진이 캐시한 상태와 엇갈리지 않게 — 스파이크와 같음). GL 함수 묶기는 gl_bindings, 이 모듈은 아이템과 선택 규칙만.

엔진 없는 paint: 컨텍스트가 생기지 않은 QOpenGLWidget(offscreen에서 강제한 GL 뷰포트 — 시험, 또는 위젯 컨텍스트 생성이 실패한 GL 뷰포트 —
강제 GL이든 확인을 통과한 cocoa 기본이든)에서도
QGraphicsView는 paint를 부르지만 painter에 엔진이 없다(QPainter::begin 실패 — paintEngine()이 None, Qt가 경고를 남김; offscreen 실측). Qt 자신도
그 장치에는 아무것도 못 그리므로 준비도 그리기도 없이 기록 한 줄만 남기고 돌아간다 — 아이템마다 한 번, 오류 창 없음, 실패로 치지 않음(뒤에 진짜
엔진이 오면 그대로 그림). 실패 창(모달)을 띄우면 offscreen 시험이 멈춘다(test_gl_viewport의 gl_widget).
"""

import ctypes
import sys
import traceback
from collections.abc import Mapping
from typing import NamedTuple

import numpy as np
from PyQt5.QtCore import QPointF, Qt, QTimer
from PyQt5.QtGui import QImage, QOpenGLContext, QPaintEngine, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem

from yesoncheck import error_window, gl_bindings, gl_surface
from yesoncheck.frame_handles import native_surface_of, whole_surface_handle
from yesoncheck.gl_bindings import (
    GL_BLEND,
    GL_CLAMP_TO_EDGE,
    GL_LINEAR,
    GL_MODELVIEW,
    GL_NEAREST,
    GL_PROJECTION,
    GL_QUADS,
    GL_RGB,
    GL_RGB8,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_UNPACK_ALIGNMENT,
    GL_UNPACK_ROW_LENGTH,
    GL_UNSIGNED_BYTE,
    GLBindingError,
)
from yesoncheck.gl_surface import GL_BGRA, GL_RGBA, GL_SCISSOR_TEST, GL_TEXTURE_RECTANGLE_ARB, GL_UNSIGNED_INT_8_8_8_8_REV

VIDEO_ITEM_ENV = "YESONCHECK_VIDEO_ITEM"
VIDEO_ITEM_MODES = ("auto", "gl", "pixmap")
LOG_PREFIX = "[표시]"
# (Mac) 실패 창의 킬 스위치 안내 앞에 붙는 줄 — player_base의 Setting 메뉴 '재생 디코더 (Mac)'가 그 걸쇠를 풂 (스펙 2026-11-04 §5.4 ④)
DECODER_MENU_HINT = "Setting → 재생 디코더 → ffmpeg (예전 방식) 으로 바꾸면 예전 방식으로 재생합니다"
# (Mac) 네이티브 면을 그리다 실패했고 받을 쪽(실패 콜백)이 있을 때 실패 창의 첫 줄 — 플레이어가 이 창만 ffmpeg로 바꿈 (스펙 2026-11-04 §5.8)
NATIVE_FALLBACK_LINE = "네이티브 화면 그리기에 실패해 이 창은 ffmpeg 방식으로 바꿉니다(설정 파일은 그대로 — 다음 창은 다시 시도)"
FAILURE_LINE = "영상 화면(GL 텍스처 스트리밍)을 그리지 못했습니다 — 영상 영역을 비워 둡니다 (재생·다른 기능은 그대로)."  # 그 밖의 실패 창 첫 줄

GL_DEFAULT_UNPACK_ALIGNMENT = 4  # GL 기본값 — 업로드 뒤 되돌림 (endNativePainting은 픽셀 저장 상태를 되돌리지 않음)
QUAD_TEX_COORDS = ((0, 0), (1, 0), (1, 1), (0, 1))  # 모서리 (0,0)(w,0)(w,h)(0,h)와 짝 — 텍스처 행 0 = 배열 행 0 = 위
WIPE_AXES = ("x", "y", "xy", None)  # set_sides의 axis — B = 오른쪽·아래쪽·둘의 합집합(ratio = (rx, ry))·와이프 없음


def video_item_mode(env: Mapping) -> str:
    """YESONCHECK_VIDEO_ITEM 값 — "auto"·"gl"·"pixmap". 없거나 비면 "auto", 대소문자 무시, 그 밖의 값은 ValueError(조용한 폴백 금지).

    pixmap은 킬 스위치(GL 뷰포트에서도 예전 QPixmap 경로), gl은 GL 뷰포트에서만 될 수 있음(use_stream_item)."""
    value = env.get(VIDEO_ITEM_ENV)
    if not value:
        return "auto"
    mode = value.lower()
    if mode not in VIDEO_ITEM_MODES:
        raise ValueError(f"{VIDEO_ITEM_ENV}는 auto, gl 또는 pixmap이어야 합니다: {value!r}")
    return mode


def use_stream_item(viewport_is_gl: bool, mode: str) -> bool:
    """스트림 아이템(VideoFrameItem(stream=True))을 쓸지 — auto는 뷰포트를 따르고, pixmap은 늘 아님, gl은 GL 뷰포트가 아니면 ValueError
    (raster 엔진에는 native painting이 없어 될 수 없음 — 강제로 틀어 주지 않음)."""
    if mode == "auto":
        return bool(viewport_is_gl)
    if mode == "pixmap":
        return False
    if mode == "gl":
        if not viewport_is_gl:
            raise ValueError(f"{VIDEO_ITEM_ENV}=gl은 GL 뷰포트에서만 됩니다 (YESONCHECK_VIEWPORT=gl)")
        return True
    raise ValueError(f"알 수 없는 영상 아이템 모드입니다 (video_item_mode가 정한 값이어야 함): {mode!r}")


def wipe_scissor(axis, ratio, pw, ph, corners):
    """와이프 B 면의 glScissor 상자 (x, y, 너비, 높이) — GL 창 좌표(물리 픽셀, 원점이 왼쪽 **아래**). corners: 아이템 (0,0)(w,0)(w,h)(0,h)를
    매핑한 물리 픽셀(y 아래 방향 — glOrtho(0, pw, ph, 0)). 나눔 자리 split은 모서리 사이 ratio 자리를 int(x + 0.5)로 반올림해 [0, pw]·[0, ph]로 자른
    값이다(스파이크 spike/mac-native와 같은 계산; 자르지 않으면 음수 너비·높이 — GL_INVALID_VALUE). "x"는 B = 오른쪽 (split, 0, pw − split, ph),
    "y"는 B = 아래쪽 — 위에서 split까지가 A라 GL 창 좌표로는 (0, 0, pw, ph − split).

    기존 numpy 합성(video_widget.updateFrame)은 영상 픽셀 int(w × ratio)에서 나눠 확대하면 영상 픽셀 경계에 붙고, 이것은 와이프 선(updateWipeLine —
    w × ratio) 자리에서 나눈다 — 차이는 영상 픽셀 한 칸 안."""
    (x0, y0), (x1, _y1), _corner, (_x3, y3) = corners
    if axis == "x":
        split = min(max(int(x0 + (x1 - x0) * ratio + 0.5), 0), pw)
        return split, 0, pw - split, ph
    if axis == "y":
        split = min(max(int(y0 + (y3 - y0) * ratio + 0.5), 0), ph)
        return 0, 0, pw, ph - split
    raise ValueError(f"와이프 axis는 'x' 또는 'y'여야 합니다: {axis!r}")


class _Side(NamedTuple):
    """set_sides가 받은 면 하나 — frame: 받은 배열 그대로(쥐고 있어 IOSurface가 산다), handle: 표면 전체 네이티브면 그 NativeHandle, RGB면 None."""
    frame: np.ndarray
    handle: object

    @property
    def size(self):
        """(너비, 높이) — 네이티브면 손잡이 크기와 같음(whole_surface_handle이 확인)."""
        return self.frame.shape[1], self.frame.shape[0]


class _Sides(NamedTuple):
    """다음 그림(set_sides) — a: _Side, b: _Side 또는 None(와이프면 검정), wipes: B를 그릴 scissor 상자마다 (축 "x"·"y", 나눔 자리) — 와이프 없음은 (),
    "x"·"y"는 하나, "xy"는 (("x", rx), ("y", ry)) 둘(B는 두 상자에 그려 합집합)."""
    a: _Side
    b: _Side | None
    wipes: tuple


class _SideTexture:
    """면 텍스처 하나(이 컨텍스트의 것) — 면(0 = A, 1 = B)·대상(2D·RECT)마다 하나, 처음 그릴 때 만들고 컨텍스트와 함께 버린다.
    filter: 세운 MIN/MAG 필터, storage: (2D) 저장소 크기 (w, h) 또는 None, content: 지금 담긴 것 — 2D는 올린 RGB 배열, RECT는 묶은 NativeHandle
    (같음은 동일성; 쥐고 있으므로 묶인 IOSurface의 버퍼가 산다)."""

    __slots__ = ("target", "name", "filter", "storage", "content")

    def __init__(self, target, name, filt):
        self.target, self.name, self.filter = target, name, filt
        self.storage = None
        self.content = None


def _wipes(axis, ratio):
    """set_sides의 axis·ratio를 scissor 상자마다의 (축, 나눔 자리) tuple로 — None은 (), "x"·"y"는 하나, "xy"는 (("x", rx), ("y", ry)) (Ruling 17).
    "xy"는 ratio가 [0, 1] 실수 두 개의 tuple, 그 밖은 [0, 1] 실수 하나여야 하고 어긋나면 ValueError(한 값을 두 축에 몰래 쓰지 않음)."""
    if axis not in WIPE_AXES:
        raise ValueError(f"와이프 axis는 'x', 'y', 'xy' 또는 None이어야 합니다: {axis!r}")
    if axis == "xy":
        if not (isinstance(ratio, tuple) and len(ratio) == 2):
            raise ValueError(f"와이프 axis 'xy'의 ratio는 (rx, ry) 두 값 tuple이어야 합니다: {ratio!r}")
        ratios = ratio
    else:
        if isinstance(ratio, (tuple, list)):
            raise ValueError(f"와이프 axis {axis!r}의 ratio는 실수 하나여야 합니다 (두 값은 axis 'xy'): {ratio!r}")
        ratios = (ratio,)
    for value in ratios:
        if not 0 <= value <= 1:
            raise ValueError(f"와이프 ratio는 0~1이어야 합니다: {ratio!r}")
    if axis is None:
        return ()
    return tuple(zip(("x", "y") if axis == "xy" else (axis,), ratios))


def _side(label, frame):
    """set_sides의 면 하나를 가른다 — 표면 전체 네이티브(whole_surface_handle — Ruling 14)면 손잡이와 함께, (높이, 너비, 3) uint8 C 연속 RGB면 손잡이
    None. 손잡이는 있지만 표면 전체가 아닌 뷰와 그 밖의 어긋남은 면 이름(label)과 조건을 넣은 ValueError — 복사·변환하지 않는다."""
    handle = whole_surface_handle(frame)
    if handle is not None:
        return _Side(frame, handle)
    if native_surface_of(frame) is not None:
        raise ValueError(
            f"{label} 면이 네이티브 프레임의 표면 전체가 아닙니다(조각·상하 반전·채널 역순 뷰 — shape {frame.shape}, strides {frame.strides}) — "
            "IOSurface로 묶을 수 없고 복사·업로드하지 않습니다"
        )
    if frame.ndim != 3:
        raise ValueError(f"{label} 면은 (높이, 너비, 3) 3차원 RGB 배열이어야 합니다: shape {frame.shape}")
    if frame.shape[2] != 3:
        raise ValueError(f"{label} 면은 RGB 3채널이어야 합니다(손잡이 없는 4채널 배열은 네이티브 프레임이 아님): shape {frame.shape}")
    if frame.dtype != np.uint8:
        raise ValueError(f"{label} 면 dtype은 uint8이어야 합니다: {frame.dtype}")
    if not frame.flags["C_CONTIGUOUS"]:
        raise ValueError(f"{label} 면 배열이 C 연속(C-contiguous)이 아닙니다 — 조용히 복사하지 않습니다 (부른 쪽에서 np.ascontiguousarray)")
    return _Side(frame, None)


class VideoFrameItem(QGraphicsPixmapItem):
    """픽스맵 아이템 자리에 들어가는 영상 프레임 아이템 (모듈 설명). stream: 스트림(GL 텍스처) 모드인지 — 만든 뒤 바꾸지 않음.

    시험 훅: failure_count(_fail이 실패를 알린 수 — 걸쇠가 걸린 동안은 첫 실패만 알리므로 reset_failure 사이마다 많아야 1씩 늚 — 실패 콜백도 그만큼)."""

    def __init__(self, stream: bool):
        super().__init__()
        self.stream = stream
        self.failure_count = 0
        self._frame = None  # 마지막 그림 배열 (스트림 모드 — set_frame의 RGB, set_sides·set_surface의 A 면; frame())
        self._dirty = False  # 텍스처에 아직 올리지 않은 프레임이 있음
        self._failed = False  # 첫 실패를 알린 뒤 — 더 그리지 않음
        self._context = None  # 텍스처를 만든 QOpenGLContext
        self._gl = None  # 그 컨텍스트에서 묶은 gl_bindings.GLFunctions
        self._texture = None  # 텍스처 이름
        self._storage = None  # 텍스처 저장소 크기 (w, h) — 없으면 None
        self._filter = None  # 텍스처에 세운 MIN/MAG 필터 (GL_LINEAR·GL_NEAREST) — transformationMode()가 바뀌면 다시 세움
        self._warned_no_engine = False  # 엔진 없는 paint를 기록했음 — 한 번만 (실패 표시 _failed와 따로)
        self._sides = None  # 면 그리기(set_sides·set_surface)의 _Sides — 있으면 paint가 _draw_sides, 없으면 _draw_native
        self._side_textures = {}  # (면, 대상) → _SideTexture — 이 컨텍스트의 면 텍스처
        self._cgl = None  # gl_surface.CGLFunctions — 처음 IOSurface를 묶을 때 (프로세스에 하나인 C API라 컨텍스트와 무관)
        self._failure_callback = None  # 실패 콜백 (native: bool) -> None — set_failure_callback, _fail이 Qt 루프로 미뤄 부름

    # ------------------------------------------------------------ 프레임

    def set_frame(self, rgb: np.ndarray) -> None:
        """(높이, 너비, 3) uint8 C 연속 RGB 배열을 다음 그림으로 — 복사하지 않고 그대로 든다(동기 업로드라 다음 set_frame까지만 쥠).

        배열 소유: **set_frame 뒤에는 그 배열을 고치지 말 것** — 아이템은 paint 때 읽고, 그 뒤에도 다시 올려야 할 때(컨텍스트가 바뀜·
        저장소를 다시 잡음) 같은 배열을 다시 읽는다. 다음 프레임은 새 배열로 set_frame.

        조건이 어긋나면 어느 조건인지 ValueError(조용한 복사·변환 없음). 크기가 바뀌면 자리표시자 픽스맵만 바꿈(모듈 설명)."""
        if not self.stream:
            raise RuntimeError("stream=False 아이템은 set_frame을 받지 않습니다 — 픽스맵 아이템 그대로 setPixmap으로 그립니다")
        if rgb.ndim != 3:
            raise ValueError(f"프레임은 (높이, 너비, 3) 3차원 배열이어야 합니다: shape {rgb.shape}")
        if rgb.shape[2] != 3:
            raise ValueError(f"프레임은 RGB 3채널이어야 합니다: shape {rgb.shape}")
        if rgb.dtype != np.uint8:
            raise ValueError(f"프레임 dtype은 uint8이어야 합니다: {rgb.dtype}")
        if not rgb.flags["C_CONTIGUOUS"]:
            raise ValueError("프레임 배열이 C 연속(C-contiguous)이 아닙니다 — 조용히 복사하지 않습니다 (부른 쪽에서 np.ascontiguousarray)")
        h, w = rgb.shape[:2]
        placeholder = self.pixmap()
        if placeholder.isNull() or placeholder.width() != w or placeholder.height() != h:
            super().setPixmap(QPixmap(w, h))
        self._sides = None  # 면 그리기를 끝냄 (면 텍스처에 묶인 손잡이는 다음 묶기·컨텍스트가 죽을 때까지 그 텍스처가 쥠)
        self._frame = rgb
        self._dirty = True
        self.update()

    def frame(self) -> np.ndarray | None:
        """마지막으로 받은 그림 배열 — set_frame의 RGB 배열 그대로, set_sides·set_surface면 A 면(네이티브면 BGRX NativeFrameArray — CPU로 읽지
        말 것). 없으면 None. 스트림 모드에서 그림 내용은 pixmap()이 아니라 이것."""
        return self._frame

    def set_sides(self, a, b, axis, ratio) -> None:
        """A·B 두 면을 다음 그림으로 — A를 전체에, 와이프면 B를 glScissor 안에 (모듈 설명의 'IOSurface 면 그리기').

        면마다: 표면 전체 네이티브 프레임(whole_surface_handle — NativeFrameArray든 표면 전체를 가리키는 일반 뷰든)이면 IOSurface를 RECT 텍스처에
        그대로 묶고(CPU 복사 0), (높이, 너비, 3) uint8 C 연속 RGB 배열이면 2D 텍스처에 올린다(set_frame과 같은 업로드, 면마다 따로 둔 텍스처).
        b는 None일 수 있다. 손잡이는 있지만 표면 전체가 아닌 뷰(조각·상하 반전·채널 역순)는 ValueError — 복사하거나 올리지 않는다. 그 밖에 어긋나도
        어느 조건인지 ValueError이고, 그때 아이템은 그대로다.

        axis·ratio: "x"(B = 오른쪽)·"y"(B = 아래쪽)는 ratio가 나눔 자리 실수 하나 [0, 1](video_widget의 wipe_position_x/y), "xy"(X·Y 와이프가 함께 —
        Ruling 17)는 ratio = (rx, ry) tuple — B를 오른쪽(rx부터)과 아래쪽(ry부터) 두 scissor 상자에 그려 보이는 B가 합집합(기존 numpy 합성이
        result[:, wipe_x:] = B 뒤 result[wipe_y:, :] = B로 만드는 그림), None은 와이프 없음(B를 그리지도 쥐지도 않음; ratio는 [0, 1] 실수 — 쓰지 않음).
        모양이 어긋나면("xy"에 실수·리스트·길이가 2가 아닌 tuple, "x"·"y"에 tuple, 범위 밖·NaN) ValueError. 와이프인데 B가 None이거나 B의 (높이, 너비)가
        A와 다르면 B 자리는 검정 — 기존 numpy 합성(updateFrame의 np.zeros_like)과 같은 그림(채널 수 — BGRX 4 대 RGB 3 — 는 크기로 치지 않음).

        배열 소유: set_frame과 같다 — 넘긴 배열은 고치지 말 것. 아이템은 마지막 a·b를 쥐고(IOSurface 수명), 같은 배열·같은 손잡이면 다시 올리거나
        묶지 않는다. 자리표시자 픽스맵과 frame()은 A를 따른다."""
        if not self.stream:
            raise RuntimeError("stream=False 아이템은 set_sides를 받지 않습니다 — 픽스맵 아이템 그대로 setPixmap으로 그립니다")
        if a is None:
            raise ValueError("A 면이 없습니다 — 빈 그림은 setPixmap(QPixmap())")
        wipes = _wipes(axis, ratio)
        side_a = _side("A", a)
        side_b = None if b is None else _side("B", b)
        if not wipes or (side_b is not None and side_b.size != side_a.size):
            side_b = None  # 와이프 없음 — 그리지 않음 / 크기가 다른 B — 검정 (위 docstring)
        w, h = side_a.size
        placeholder = self.pixmap()
        if placeholder.isNull() or placeholder.width() != w or placeholder.height() != h:
            super().setPixmap(QPixmap(w, h))
        self._sides = _Sides(side_a, side_b, wipes)
        self._frame = a
        self.update()

    def set_surface(self, frame) -> None:
        """네이티브 프레임 하나를 다음 그림으로 — set_sides(frame, None, None, 0.0)(와이프 없음). 네이티브 프레임이 아니면 ValueError(RGB 배열은
        set_frame), 표면 전체가 아닌 뷰도 ValueError(set_sides)."""
        if self.stream and native_surface_of(frame) is None and whole_surface_handle(frame) is None:
            raise ValueError(f"set_surface는 네이티브 프레임(IOSurface)만 받습니다 — RGB 배열은 set_frame: shape {getattr(frame, 'shape', None)}")
        self.set_sides(frame, None, None, 0.0)

    def surface_handle(self):
        """(시험용) 마지막 set_sides·set_surface의 A 면 손잡이(NativeHandle) — A가 RGB이거나 면 그리기가 아니면 None."""
        return self._sides.a.handle if self._sides is not None else None

    @property
    def latched(self) -> bool:
        """그리기 실패 걸쇠가 걸려 있는가 — _fail 뒤 reset_failure 전(그동안 paint는 아무것도 그리지 않음)."""
        return self._failed

    def has_native_side(self) -> bool:
        """지금 그림에 IOSurface 면이 있는가 — 면 그리기(set_sides·set_surface)의 _Sides 중 그릴 면(A, 와이프일 때만 B — 와이프가 아니거나 크기가 다른
        B는 set_sides가 이미 뺌)의 _Side.handle(whole_surface_handle이 준 손잡이)이 있으면 True. set_frame(RGB 길)·빈 그림이면 False.
        paint가 그리는 것과 같은 판단이다(_sides가 있으면 _draw_sides) — 텍스처에 예전에 묶인 손잡이(_SideTexture.content)는 보지 않음.
        _fail이 실패 콜백에 넘기는 native이고, 플레이어가 폴백 뒤 걸쇠를 풀어도 되는지(네이티브 면이 다 빠졌는지) 볼 때 씀."""
        sides = self._sides
        return sides is not None and any(side is not None and side.handle is not None for side in (sides.a, sides.b))

    def set_failure_callback(self, callback) -> None:
        """실패 콜백 callback(native: bool) 등록 — None이면 끔. _fail이 실패를 알릴 때마다(걸쇠 사이마다 첫 실패) 오류 창 예약 바로 뒤에 Qt 루프로 미뤄
        (QTimer.singleShot(0) — paint 안에서 플레이어 일을 하지 않게) 부른다. native: 그때 그리던 그림에 IOSurface 면이 있었는가(has_native_side).
        콜백이 예외를 내면 _last_resort(Qt 루프로 내보내지 않음 — PyQt5 qFatal). CustomVideoWidget이 스트림 아이템을 만들 때 등록해 streamPaintFailed
        신호로 넘김. 부를 수 없는 값은 TypeError."""
        if callback is not None and not callable(callback):
            raise TypeError(f"GL 그리기 실패 콜백은 호출할 수 있어야 합니다(끄려면 None): {callback!r}")
        self._failure_callback = callback

    def setPixmap(self, pixmap):
        """stream=False면 부모 그대로. 스트림 모드: 빈 픽스맵은 배열까지 비우고, 비지 않은 픽스맵은 RGB 배열로 복사해 set_frame
        (느려도 됨 — 시험·레거시 경로뿐; 재생은 set_frame)."""
        if not self.stream:
            super().setPixmap(pixmap)
            return
        if pixmap.isNull():
            self._frame = None
            self._sides = None
            self._dirty = False
            super().setPixmap(QPixmap())
            return
        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        w, h, stride = image.width(), image.height(), image.bytesPerLine()
        bits = image.constBits()
        bits.setsize(image.sizeInBytes())
        rows = np.frombuffer(bits, np.uint8).reshape(h, stride)
        self.set_frame(rows[:, : w * 3].reshape(h, w, 3).copy())  # 복사 — image가 사라지면 그 메모리도 사라짐

    # ------------------------------------------------------------ 그리기

    def paint(self, painter, option, widget=None):
        """stream=False면 부모 그대로. 스트림 모드는 GL로 그리고, 어떤 예외도 밖으로 내보내지 않는다(모듈 설명의 paint 가드)."""
        if not self.stream:
            super().paint(painter, option, widget)
            return
        if self._frame is None or self._failed:
            return
        try:
            self._paint_stream(painter)
        except BaseException as exc:  # paint 밖으로 나가면 PyQt5가 프로세스를 끝냄(qFatal) — 첫 실패만 크게 알리고 비워 둠
            self._fail(exc)

    def reset_failure(self) -> None:
        """그리기 실패 걸쇠(_failed)를 풀고 다시 그리기를 예약 — 다음 paint가 지금 프레임을 다시 그린다(다시 실패하면 _fail이 다시 기록 + 창 1회).
        Setting → 재생 디코더에서 고를 때 플레이어가 캡처를 바꿔 끼운 뒤 부름(디코더를 바꾸는 것이 걸쇠의 탈출구 — 스펙 2026-11-04 §5.4 ④; 바꿔 끼우는 동안의
        창이 옛 프레임을 그려도 다시 실패하지 않게 그 뒤에). failure_count(알린 수)는 그대로.

        GL 상태는 비우지 않는다 — 다음 paint는 실패한 단계부터 다시 한다: 단계마다 성공한 뒤에만 기록하기 때문(준비 — _context는 _prepare 끝에서·
        옛 컨텍스트 신호를 끊으면 바로 None, 저장소 — _storage는 잡은 뒤, 업로드 — _dirty는 올린 뒤에 False, 면 — 텍스처의 storage·content는 잡고
        묶고 올린 뒤). 텍스처를 버리고 새로 만들게 하지 않는 이유: 여기(paint 밖)에는 current 컨텍스트가 없어 glDeleteTextures를 못 부르고,
        IOSurface에 묶인 면 텍스처를 놓아 버리면 그 표면이 창을 닫을 때까지 GPU에 남음 — 메뉴로 디코더를 바꿀 때마다 부르므로 쌓임."""
        self._failed = False
        self.update()

    def _paint_stream(self, painter):
        engine = painter.paintEngine()
        if engine is None:  # GL 뷰포트에 컨텍스트가 없음 — Qt도 못 그림 (모듈 설명의 '엔진 없는 paint')
            self._warn_no_engine()
            return
        if engine.type() != QPaintEngine.OpenGL2:
            raise GLBindingError(
                f"GL 페인트 엔진이 아닙니다 (엔진 종류 {int(engine.type())}) — GL 텍스처 스트리밍은 GL 뷰포트(QOpenGLWidget)에서만 됩니다"
            )
        context = QOpenGLContext.currentContext()
        if context is None:
            raise GLBindingError("GL 페인트 엔진인데 current GL 컨텍스트가 없습니다")
        h, w = self._frame.shape[:2]
        device = painter.device()
        dpr = device.devicePixelRatioF()
        # 물리 픽셀 (모듈 설명의 좌표 규칙). Qt는 FBO·GL2 뷰포트 크기를 qRound(.5 올림)로 잡는다 — 파이썬 round는 은행가 반올림이라
        # dpr 1.5·논리 1487처럼 .5에서 1px 어긋나(2230 대 2231) 아래·오른쪽 가장자리에 이음매가 생기므로 int(x + 0.5)로 맞춘다(양수에서 qRound와 같음).
        pw, ph = int(device.width() * dpr + 0.5), int(device.height() * dpr + 0.5)
        transform = painter.combinedTransform()  # 아이템 좌표 → 물리 픽셀
        corners = [transform.map(QPointF(x, y)) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        painter.beginNativePainting()
        try:
            if context is not self._context:
                self._prepare(context)
            if self._sides is not None:  # 면 그리기(set_sides·set_surface)
                self._draw_sides(pw, ph, [(p.x(), p.y()) for p in corners])
            else:
                self._draw_native(pw, ph, [(p.x(), p.y()) for p in corners])
        finally:
            painter.endNativePainting()

    def _draw_native(self, pw, ph, corners):
        """(native painting 안에서) 들어온 GL 오류 확인 → 저장소 확인 → 필터가 바뀌었으면 다시 세움 → 새 프레임이면 업로드 → 텍스처 사각형.
        corners: 물리 픽셀 (x, y) 네 개 — 아이템의 (0,0)(w,0)(w,h)(0,h)를 매핑한 값 그대로."""
        gl = self._gl
        h, w = self._frame.shape[:2]
        gl.check_error("native 진입 — 이전 GL 호출이 남긴 오류")  # 우리 GL 호출 전에 — Qt 엔진이 남긴 오류를 우리 업로드·그리기 탓으로 돌리지 않음(삼키지 않고 같은 실패 경로)
        self._ensure_storage(w, h)
        gl.glBindTexture(GL_TEXTURE_2D, self._texture)
        filt = self._wanted_filter()
        if filt != self._filter:  # setTransformationMode가 준비 뒤에 바뀜
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
            self._filter = filt
        if self._dirty:
            self._upload_rgb(self._frame)
            self._dirty = False
        gl.glViewport(0, 0, pw, ph)
        gl.glMatrixMode(GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, pw, ph, 0, -1, 1)  # y 아래 방향 (Qt와 같음)
        gl.glMatrixMode(GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glDisable(GL_BLEND)
        gl.glEnable(GL_TEXTURE_2D)
        gl.glColor4f(1, 1, 1, 1)
        gl.glBegin(GL_QUADS)
        for (u, v), (x, y) in zip(QUAD_TEX_COORDS, corners):
            gl.glTexCoord2f(u, v)
            gl.glVertex2f(x, y)
        gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.check_error("draw")

    def _prepare(self, context):
        """(native painting 안에서, context가 current) 이 컨텍스트로 GL 함수를 묶고 텍스처를 만든다. 필터는 transformationMode()가
        Smooth면 GL_LINEAR, 아니면 GL_NEAREST(앱은 늘 Smooth), 가장자리 GL_CLAMP_TO_EDGE. 저장소는 _ensure_storage가 잡는다.
        면 텍스처(set_sides)는 여기서 만들지 않는다 — 처음 그릴 때(_side_texture)."""
        if self._context is not None:  # 죽지 않은 다른 컨텍스트에서 넘어옴 — 옛 신호가 새 텍스처를 지우지 않게 끊음(옛 텍스처는 그 컨텍스트와 함께 해제)
            self._context.aboutToBeDestroyed.disconnect(self._release_texture)
            self._context = None  # 끊었음 — 아래에서 실패해도(걸쇠를 푼 뒤의) 다음 준비가 다시 끊으려다 TypeError로 또 실패하지 않게
        self._gl = gl_bindings.bind(context)
        filt = self._wanted_filter()
        self._texture = self._new_texture(GL_TEXTURE_2D, filt, "prepare")
        self._storage = None
        self._side_textures = {}  # 옛 컨텍스트의 면 텍스처 — 처음 그릴 때 이 컨텍스트에서 다시 만들고 다시 묶음
        self._filter = filt
        self._context = context
        context.aboutToBeDestroyed.connect(self._release_texture)

    def _wanted_filter(self):
        """transformationMode()에 맞는 텍스처 필터 — Smooth면 GL_LINEAR, 아니면 GL_NEAREST."""
        return GL_LINEAR if self.transformationMode() == Qt.SmoothTransformation else GL_NEAREST

    def _ensure_storage(self, w, h):
        """텍스처 저장소를 (w, h)로 — 같으면 아무것도 안 함. GPU 한도를 넘으면 GLBindingError(축소하지 않음). 새 저장소는 내용이
        없으므로 이번 그리기에서 프레임을 다시 올리게 표시한다."""
        if self._storage == (w, h):
            return
        self._allocate_storage(self._texture, w, h)
        self._storage = (w, h)
        self._dirty = True

    def _allocate_storage(self, texture, w, h):
        """(native 안) 2D 텍스처 texture에 (w, h) GL_RGB8 저장소를 새로 잡는다(내용 없음) — set_frame 경로와 RGB 면이 함께 씀.
        GPU 한도를 넘으면 GLBindingError(축소하지 않음)."""
        limit = self._gl.max_texture_size
        if w > limit or h > limit:
            raise GLBindingError(f"프레임 {w}×{h}가 이 GPU의 텍스처 한도 {limit}를 넘습니다 — 축소하지 않습니다")
        gl = self._gl
        gl.glBindTexture(GL_TEXTURE_2D, texture)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, None)  # 저장소만 (내용 없음)
        gl.check_error("storage")

    def _upload_rgb(self, rgb):
        """(native 안, 저장소를 잡은 2D 텍스처를 바인드한 뒤) (높이, 너비, 3) RGB 배열 전체를 동기 업로드 — set_frame 경로와 RGB 면이 함께 씀."""
        gl = self._gl
        h, w = rgb.shape[:2]
        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)  # 한 줄 = w×3바이트, 줄 사이 채움 없음
        try:
            gl.glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
            gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, rgb.ctypes.data)  # 동기
        finally:  # 실패해도 정렬 1을 Qt의 뒤이은 업로드(주석·글자)에 남기지 않음
            gl.glPixelStorei(GL_UNPACK_ALIGNMENT, GL_DEFAULT_UNPACK_ALIGNMENT)
        gl.check_error("upload")

    def _new_texture(self, target, filt, where):
        """(native 안) target(2D·RECT) 텍스처 하나를 만들어 MIN/MAG 필터 filt·가장자리 GL_CLAMP_TO_EDGE를 세우고 이름을 돌려준다(저장소·내용 없음).
        where: 오류 확인 자리."""
        gl = self._gl
        names = (ctypes.c_uint * 1)()
        gl.glGenTextures(1, names)
        gl.glBindTexture(target, names[0])
        for name, value in ((GL_TEXTURE_MIN_FILTER, filt), (GL_TEXTURE_MAG_FILTER, filt),
                            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(target, name, value)
        gl.glBindTexture(target, 0)
        gl.check_error(where)
        return names[0]

    def _release_texture(self):
        """(컨텍스트의 aboutToBeDestroyed) 그 컨텍스트에 묶인 것을 놓는다 — 다음 paint가 새 컨텍스트에서 새로 준비하고 프레임을 다시 올림
        (면 그리기면 면 텍스처를 새로 만들고 IOSurface를 다시 묶음 — 면 텍스처가 쥔 손잡이도 여기서 놓음).

        glDeleteTextures는 부르지 않는다: 아이템에는 컨텍스트를 current로 만들 표면이 없다. 텍스처는 컨텍스트(공유 그룹)와 함께 해제되고,
        이 앱에서 뷰포트 컨텍스트가 죽는 때는 창이 닫힐 때뿐이다(뷰포트 위젯을 다른 창으로 옮기지 않음)."""
        self._texture = None
        self._context = None
        self._gl = None
        self._storage = None
        self._filter = None
        self._side_textures = {}

    # ------------------------------------------------------------ 면 그리기 (set_sides·set_surface)

    def _draw_sides(self, pw, ph, corners):
        """(native painting 안에서) 들어온 GL 오류 확인 → 면마다 내용을 그 면의 텍스처에(_load_side — 바뀌었을 때만) → 뷰포트·투영(_draw_native와
        같음), blend 끔 → A를 corners 전체에 → 와이프면 상자마다(wipes — "xy"면 둘) B를 glScissor(wipe_scissor) 안에(B가 없으면 검정) → (실패해도) scissor·RECT·2D를 끄고
        바인딩 0 → 오류 확인. corners: 물리 픽셀 (x, y) 네 개 — 아이템의 (0,0)(w,0)(w,h)(0,h)를 매핑한 값 그대로."""
        gl = self._gl
        sides = self._sides
        gl.check_error("native 진입 — 이전 GL 호출이 남긴 오류")
        try:
            drawn_a = self._load_side(0, sides.a)
            drawn_b = self._load_side(1, sides.b) if sides.wipes and sides.b is not None else None
            gl.glViewport(0, 0, pw, ph)
            gl.glMatrixMode(GL_PROJECTION)
            gl.glLoadIdentity()
            gl.glOrtho(0, pw, ph, 0, -1, 1)  # y 아래 방향 (Qt와 같음)
            gl.glMatrixMode(GL_MODELVIEW)
            gl.glLoadIdentity()
            gl.glDisable(GL_BLEND)  # 텍스처의 넷째 채널(BGRX의 X — 알파 아님)이 섞이지 않게
            gl.glColor4f(1, 1, 1, 1)
            self._draw_textured(*drawn_a, corners)
            if sides.wipes:
                gl.glEnable(GL_SCISSOR_TEST)
                for axis, ratio in sides.wipes:  # "xy"면 상자 둘 — 겹친 곳은 같은 B를 두 번(blend 꺼짐 — 그림 같음)
                    gl.glScissor(*wipe_scissor(axis, ratio, pw, ph, corners))
                    if drawn_b is None:
                        self._draw_black(corners)
                    else:
                        self._draw_textured(*drawn_b, corners)
        finally:  # 실패해도 scissor·텍스처를 켠 채 Qt 엔진으로 돌아가지 않음
            gl.glDisable(GL_SCISSOR_TEST)
            gl.glDisable(GL_TEXTURE_RECTANGLE_ARB)
            gl.glDisable(GL_TEXTURE_2D)
            gl.glBindTexture(GL_TEXTURE_RECTANGLE_ARB, 0)
            gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.check_error("draw sides")

    def _load_side(self, slot, side):
        """(native 안) 면 하나의 내용을 그 면(slot — 0 = A, 1 = B)의 텍스처에 — 네이티브면 RECT 텍스처를 IOSurface에 묶고(손잡이가 바뀌었을 때만),
        RGB면 2D 텍스처의 저장소를 맞추고 올린다(배열이 바뀌었을 때만 — set_frame과 같은 업로드). 필터는 transformationMode()를 따름.
        (텍스처, 텍스처 좌표 네 개)를 돌려준다 — RECT는 픽셀 단위, 2D는 0..1."""
        gl = self._gl
        w, h = side.size
        if side.handle is not None:
            texture = self._side_texture(slot, GL_TEXTURE_RECTANGLE_ARB)
            gl.glBindTexture(GL_TEXTURE_RECTANGLE_ARB, texture.name)
            self._sync_filter(texture)
            if texture.content is not side.handle:
                self._bind_surface(side.handle)
                texture.content = side.handle  # 옛 손잡이는 여기서 놓음 — 텍스처가 이제 새 표면을 가리킴
            return texture, ((0, 0), (w, 0), (w, h), (0, h))
        texture = self._side_texture(slot, GL_TEXTURE_2D)
        if texture.storage != (w, h):
            self._allocate_storage(texture.name, w, h)
            texture.storage, texture.content = (w, h), None  # 새 저장소는 내용이 없음
        gl.glBindTexture(GL_TEXTURE_2D, texture.name)
        self._sync_filter(texture)
        if texture.content is not side.frame:
            self._upload_rgb(side.frame)
            texture.content = side.frame
        return texture, QUAD_TEX_COORDS

    def _side_texture(self, slot, target):
        """(native 안) 면 slot의 target 텍스처 — 이 컨텍스트에서 처음이면 만든다."""
        key = (slot, target)
        texture = self._side_textures.get(key)
        if texture is None:
            filt = self._wanted_filter()
            texture = _SideTexture(target, self._new_texture(target, filt, "prepare side"), filt)
            self._side_textures[key] = texture
        return texture

    def _sync_filter(self, texture):
        """(texture를 바인드한 뒤) transformationMode()가 바뀌었으면 MIN/MAG 필터를 다시 세운다 — _draw_native의 2D 텍스처와 같은 규칙
        (만들 때 한 번만 세우면 줌 모드를 바꿔도 남음 — 스파이크 검토 지적)."""
        filt = self._wanted_filter()
        if filt != texture.filter:
            self._gl.glTexParameteri(texture.target, GL_TEXTURE_MIN_FILTER, filt)
            self._gl.glTexParameteri(texture.target, GL_TEXTURE_MAG_FILTER, filt)
            texture.filter = filt

    def _bind_surface(self, handle):
        """(RECT 텍스처를 바인드한 뒤) 그 텍스처를 handle의 IOSurface에 묶는다 — CPU 복사 없음(모듈 gl_surface의 인자 그대로). current CGL 컨텍스트가
        없거나 CGL·GL이 오류를 내면 GLBindingError."""
        if self._cgl is None:
            self._cgl = gl_surface.bind_cgl()
        ctx = self._cgl.CGLGetCurrentContext()
        if not ctx:
            raise GLBindingError("CGLGetCurrentContext()가 NULL입니다 — native painting 안인데 current CGL 컨텍스트가 없어 IOSurface를 묶지 못합니다")
        self._cgl.CGLTexImageIOSurface2D(ctx, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, handle.width, handle.height, GL_BGRA,
                                         GL_UNSIGNED_INT_8_8_8_8_REV, handle.iosurface, 0)
        self._gl.check_error("CGLTexImageIOSurface2D")

    def _draw_textured(self, texture, coords, corners):
        """texture를 바인드해 켜고 corners에 텍스처 사각형(coords) → 끔."""
        gl = self._gl
        gl.glBindTexture(texture.target, texture.name)
        gl.glEnable(texture.target)
        gl.glBegin(GL_QUADS)
        for (u, v), (x, y) in zip(coords, corners):
            gl.glTexCoord2f(u, v)
            gl.glVertex2f(x, y)
        gl.glEnd()
        gl.glDisable(texture.target)

    def _draw_black(self, corners):
        """와이프인데 B가 없음(또는 크기가 다름) — B 자리(scissor 안)를 검정 사각형으로 (기존 numpy 합성의 np.zeros_like와 같은 그림)."""
        gl = self._gl
        gl.glColor4f(0, 0, 0, 1)
        gl.glBegin(GL_QUADS)
        for x, y in corners:
            gl.glVertex2f(x, y)
        gl.glEnd()
        gl.glColor4f(1, 1, 1, 1)

    def _warn_no_engine(self):
        """(paint 안에서) 엔진 없는 paint를 처음 한 번만 기록 — 오류 창 없음, 실패로 치지 않음. _fail처럼 예외를 내보내지 않는다
        (기록이 실패하면 _last_resort)."""
        if self._warned_no_engine:
            return
        self._warned_no_engine = True
        try:
            print(
                f"{LOG_PREFIX} 페인트 엔진이 없어 영상 프레임을 그리지 못함(GL 뷰포트 컨텍스트 없음 — offscreen이거나 컨텍스트 생성 실패) — 한 번만 기록",
                file=sys.stderr,
                flush=True,
            )
        except BaseException:  # 기록 파일이 닫힘·꽉 참 등
            _last_resort("페인트 엔진 없음을 기록하지 못했습니다")

    def _fail(self, exc):
        """첫 실패만: 기록(트레이스백 전문)과 오류 창(Qt 루프에서 — paint 안에서 모달 금지)으로 알리고 그 뒤 그리지 않게 표시한다. 창 예약 바로 뒤에
        실패 콜백(있으면)도 Qt 루프로 — 값 native = has_native_side()(그리던 그림에 IOSurface 면이 있었는가). 두 번째부터는 아무것도 하지 않음.

        창의 첫 줄: 네이티브 면 실패이고 macOS이고 콜백이 있으면(플레이어가 이 창만 ffmpeg로 바꿈 — 스펙 2026-11-04 §5.8) NATIVE_FALLBACK_LINE,
        아니면 FAILURE_LINE. 나머지(예외 줄·Mac 메뉴 안내·킬 스위치 안내)와 기록 줄은 같음. 콜백 쪽이 바꾸지 않기로 하는 경우(환경 변수가 덮음)는
        여기서 모름 — 플레이어가 기록 줄로 알림.

        paint의 except 안에서 불리므로 예외를 내보내지 않는다(내보내면 qFatal): 기록·창 예약·콜백 예약을 따로 감싸(기록이 실패해도 창은 뜨고 창 글을
        만들지 못해도 콜백은 감), 알리다 또 실패하면 _last_resort."""
        if self._failed:
            return
        self._failed = True
        self.failure_count += 1
        native = self.has_native_side()
        try:
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            print(
                f"{LOG_PREFIX} GL 텍스처 스트리밍 실패 — 영상 영역을 비워 둡니다 (탈출구: {VIDEO_ITEM_ENV}=pixmap)\n{details}",
                file=sys.stderr,
                flush=True,
            )
        except BaseException:  # 기록 파일이 닫힘·꽉 참 등
            _last_resort("GL 텍스처 스트리밍 실패를 기록하지 못했습니다")
        callback = self._failure_callback
        try:
            mac = sys.platform == "darwin"
            menu_hint = f"{DECODER_MENU_HINT}\n" if mac else ""  # 그 메뉴는 Mac에만 있음
            first = NATIVE_FALLBACK_LINE if native and mac and callback is not None else FAILURE_LINE
            text = (
                f"{first}\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                f"{menu_hint}"
                f"{VIDEO_ITEM_ENV}=pixmap 으로 켜면 예전 방식으로 그립니다"
            )
            QTimer.singleShot(0, lambda: _show_failure_window(text))
        except BaseException:  # str(exc)가 실패하는 예외 등
            _last_resort("GL 텍스처 스트리밍 실패 창을 띄우지 못했습니다")
        if callback is None:
            return
        try:
            QTimer.singleShot(0, lambda: _run_failure_callback(callback, native))
        except BaseException:
            _last_resort(f"GL 그리기 실패 콜백을 예약하지 못했습니다 (native={native})")


def _show_failure_window(text):
    """(Qt 루프에서) 오류 창 — 실패해도 Qt 루프로 내보내지 않음(_last_resort)."""
    try:
        error_window.show_window(text)
    except BaseException:
        _last_resort(f"오류 창을 띄우지 못했습니다: {text}")


def _run_failure_callback(callback, native):
    """(Qt 루프에서) 실패 콜백 callback(native) — 예외를 Qt 루프로 내보내지 않음(_last_resort; 콜백이 Qt 신호를 내면 그 슬롯의 예외는 PyQt가 sys.excepthook으로
    보내므로 여기 오는 것은 콜백 자체의 예외)."""
    try:
        callback(native)
    except BaseException:
        _last_resort(f"GL 그리기 실패 콜백이 실패했습니다 (native={native}) — 플레이어에 넘기지 못함")


def _last_resort(message):
    """(except 블록 안에서) 알리다 또 실패함: 원래 stderr(sys.__stderr__ — 빌드 앱이 기록 파일로 바꾸기 전)에 message와 지금 처리 중인
    예외(알리던 예외가 앞에 이어진 트레이스백). 원래 stderr가 없거나(Windows 창 앱) 거기 쓰는 것마저 실패하면 더 남길 곳이 없다 —
    올리면 paint·Qt 루프 밖으로 나가 qFatal이므로 올리지 않는다(movie_pipe_source._last_resort와 같은 모양). 이 함수가 알림 사슬의 끝."""
    stream = sys.__stderr__
    if stream is None:
        return
    try:
        stream.write(f"{LOG_PREFIX} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
        stream.flush()
    except BaseException:  # 남길 곳이 없음 (위 docstring) — 사슬의 끝이라 삼킴
        pass
