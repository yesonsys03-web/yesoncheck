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
painter.device().width()/height()는 **논리** 픽셀이다 → pw, ph = round(논리 × devicePixelRatioF()), glViewport(0, 0, pw, ph)와
glOrtho(0, pw, ph, 0, -1, 1)(y 아래 방향 — Qt와 같음), 정점은 매핑값 그대로. 정점에 dpr을 또 곱하거나 뷰포트를 논리 크기로 잡으면
레티나에서 왼쪽 아래 1/4에 2배로 그려진다(스파이크 첫 실행).

함정(findings 해석 6): 뷰포트로 쓰인 QOpenGLWidget은 grab()도 grabFramebuffer()도 내용을 못 찍는다(paintGL이 비어 흰 그림) —
흰 그림 둘을 견주면 "차이 0"이 나온다. 실제 화면 검증은 screencapture -R(뷰포트의 전역 좌표 영역)로만.

paint 가드: PyQt5 가상 함수(paint)에서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음 — CLAUDE.md 함정)이다. 그래서 스트림 모드의
paint 본문 전체를 except BaseException으로 받아 첫 실패만 기록(트레이스백 전문, [표시]) + 오류 창(Qt 루프에서 1회 — paint 안에서 모달 금지)으로
알리고, 그 뒤 paint는 아무것도 그리지 않는다(빈 영상 영역). 재생·UI는 계속되고 탈출구는 YESONCHECK_VIDEO_ITEM=pixmap(예전 QPixmap 경로).

GL 준비(함수 묶기·텍스처)는 생성 때가 아니라 첫 paint()에서 그때 current인 위젯 컨텍스트로 한다: getProcAddress는 current 컨텍스트가
있어야 하고, 위젯의 진짜 컨텍스트(MSAA 포맷)는 첫 show 때 생긴다. offscreen에서 강제한 GL 뷰포트(시험)는 컨텍스트를 못 만들어 paint가
불리지 않으므로 준비도 없다. GL 호출은 전부 beginNativePainting/endNativePainting 안에서만(Qt GL2 엔진이 캐시한 상태와 엇갈리지 않게 —
스파이크와 같음). GL 함수 묶기는 gl_bindings, 이 모듈은 아이템과 선택 규칙만.
"""

import ctypes
import sys
import traceback
from collections.abc import Mapping

import numpy as np
from PyQt5.QtCore import QPointF, Qt, QTimer
from PyQt5.QtGui import QImage, QOpenGLContext, QPaintEngine, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem

from yesoncheck import error_window, gl_bindings
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

VIDEO_ITEM_ENV = "YESONCHECK_VIDEO_ITEM"
VIDEO_ITEM_MODES = ("auto", "gl", "pixmap")
LOG_PREFIX = "[표시]"

GL_DEFAULT_UNPACK_ALIGNMENT = 4  # GL 기본값 — 업로드 뒤 되돌림 (endNativePainting은 픽셀 저장 상태를 되돌리지 않음)
QUAD_TEX_COORDS = ((0, 0), (1, 0), (1, 1), (0, 1))  # 모서리 (0,0)(w,0)(w,h)(0,h)와 짝 — 텍스처 행 0 = 배열 행 0 = 위


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


class VideoFrameItem(QGraphicsPixmapItem):
    """픽스맵 아이템 자리에 들어가는 영상 프레임 아이템 (모듈 설명). stream: 스트림(GL 텍스처) 모드인지 — 만든 뒤 바꾸지 않음.

    시험 훅: failure_count(_fail이 실패를 알린 수 — 첫 실패만 알리므로 0 또는 1)."""

    def __init__(self, stream: bool):
        super().__init__()
        self.stream = stream
        self.failure_count = 0
        self._frame = None  # 마지막 RGB 배열 (스트림 모드)
        self._dirty = False  # 텍스처에 아직 올리지 않은 프레임이 있음
        self._failed = False  # 첫 실패를 알린 뒤 — 더 그리지 않음
        self._context = None  # 텍스처를 만든 QOpenGLContext
        self._gl = None  # 그 컨텍스트에서 묶은 gl_bindings.GLFunctions
        self._texture = None  # 텍스처 이름
        self._storage = None  # 텍스처 저장소 크기 (w, h) — 없으면 None

    # ------------------------------------------------------------ 프레임

    def set_frame(self, rgb: np.ndarray) -> None:
        """(높이, 너비, 3) uint8 C 연속 RGB 배열을 다음 그림으로 — 복사하지 않고 그대로 든다(동기 업로드라 다음 set_frame까지만 쥠).

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
        self._frame = rgb
        self._dirty = True
        self.update()

    def frame(self) -> np.ndarray | None:
        """마지막으로 받은 RGB 배열(set_frame 그대로) — 없으면 None. 스트림 모드에서 그림 내용은 pixmap()이 아니라 이것."""
        return self._frame

    def setPixmap(self, pixmap):
        """stream=False면 부모 그대로. 스트림 모드: 빈 픽스맵은 배열까지 비우고, 비지 않은 픽스맵은 RGB 배열로 복사해 set_frame
        (느려도 됨 — 시험·레거시 경로뿐; 재생은 set_frame)."""
        if not self.stream:
            super().setPixmap(pixmap)
            return
        if pixmap.isNull():
            self._frame = None
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

    def _paint_stream(self, painter):
        engine = painter.paintEngine()
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
        pw, ph = round(device.width() * dpr), round(device.height() * dpr)  # 물리 픽셀 (모듈 설명의 좌표 규칙)
        transform = painter.combinedTransform()  # 아이템 좌표 → 물리 픽셀
        corners = [transform.map(QPointF(x, y)) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        painter.beginNativePainting()
        try:
            if context is not self._context:
                self._prepare(context)
            self._draw_native(pw, ph, [(p.x(), p.y()) for p in corners])
        finally:
            painter.endNativePainting()

    def _draw_native(self, pw, ph, corners):
        """(native painting 안에서) 저장소 확인 → 새 프레임이면 업로드 → 텍스처 사각형. corners: 물리 픽셀 (x, y) 네 개 —
        아이템의 (0,0)(w,0)(w,h)(0,h)를 매핑한 값 그대로."""
        gl = self._gl
        h, w = self._frame.shape[:2]
        self._ensure_storage(w, h)
        gl.glBindTexture(GL_TEXTURE_2D, self._texture)
        if self._dirty:
            gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)  # 한 줄 = w×3바이트, 줄 사이 채움 없음
            gl.glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
            gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, self._frame.ctypes.data)  # 동기
            gl.glPixelStorei(GL_UNPACK_ALIGNMENT, GL_DEFAULT_UNPACK_ALIGNMENT)
            gl.check_error("upload")
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
        Smooth면 GL_LINEAR, 아니면 GL_NEAREST(앱은 늘 Smooth), 가장자리 GL_CLAMP_TO_EDGE. 저장소는 _ensure_storage가 잡는다."""
        if self._context is not None:  # 죽지 않은 다른 컨텍스트에서 넘어옴 — 옛 신호가 새 텍스처를 지우지 않게 끊음(옛 텍스처는 그 컨텍스트와 함께 해제)
            self._context.aboutToBeDestroyed.disconnect(self._release_texture)
        self._gl = gl_bindings.bind(context)
        gl = self._gl
        texture = ctypes.c_uint(0)
        gl.glGenTextures(1, ctypes.byref(texture))
        self._texture = texture.value
        self._storage = None
        filt = GL_LINEAR if self.transformationMode() == Qt.SmoothTransformation else GL_NEAREST
        gl.glBindTexture(GL_TEXTURE_2D, self._texture)
        for name, value in ((GL_TEXTURE_MIN_FILTER, filt), (GL_TEXTURE_MAG_FILTER, filt),
                            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(GL_TEXTURE_2D, name, value)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.check_error("prepare")
        self._context = context
        context.aboutToBeDestroyed.connect(self._release_texture)

    def _ensure_storage(self, w, h):
        """텍스처 저장소를 (w, h)로 — 같으면 아무것도 안 함. GPU 한도를 넘으면 GLBindingError(축소하지 않음). 새 저장소는 내용이
        없으므로 이번 그리기에서 프레임을 다시 올리게 표시한다."""
        if self._storage == (w, h):
            return
        limit = self._gl.max_texture_size
        if w > limit or h > limit:
            raise GLBindingError(f"프레임 {w}×{h}가 이 GPU의 텍스처 한도 {limit}를 넘습니다 — 축소하지 않습니다")
        gl = self._gl
        gl.glBindTexture(GL_TEXTURE_2D, self._texture)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, None)  # 저장소만 (내용 없음)
        gl.check_error("storage")
        self._storage = (w, h)
        self._dirty = True

    def _release_texture(self):
        """(컨텍스트의 aboutToBeDestroyed) 그 컨텍스트에 묶인 것을 놓는다 — 다음 paint가 새 컨텍스트에서 새로 준비하고 프레임을 다시 올림.

        glDeleteTextures는 부르지 않는다: 아이템에는 컨텍스트를 current로 만들 표면이 없다. 텍스처는 컨텍스트(공유 그룹)와 함께 해제되고,
        이 앱에서 뷰포트 컨텍스트가 죽는 때는 창이 닫힐 때뿐이다(뷰포트 위젯을 다른 창으로 옮기지 않음)."""
        self._texture = None
        self._context = None
        self._gl = None
        self._storage = None

    def _fail(self, exc):
        """첫 실패만: 기록(트레이스백 전문)과 오류 창(Qt 루프에서 — paint 안에서 모달 금지)으로 알리고 그 뒤 그리지 않게 표시한다.
        두 번째부터는 아무것도 하지 않음."""
        if self._failed:
            return
        self._failed = True
        self.failure_count += 1
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(
            f"{LOG_PREFIX} GL 텍스처 스트리밍 실패 — 영상 영역을 비워 둡니다 (탈출구: {VIDEO_ITEM_ENV}=pixmap)\n{details}",
            file=sys.stderr,
            flush=True,
        )
        text = (
            "영상 화면(GL 텍스처 스트리밍)을 그리지 못했습니다 — 영상 영역을 비워 둡니다 (재생·다른 기능은 그대로).\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"{VIDEO_ITEM_ENV}=pixmap 으로 켜면 예전 방식으로 그립니다"
        )
        QTimer.singleShot(0, lambda: error_window.show_window(text))
