import io
import sys

import numpy as np
import pytest
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QImage, QOpenGLContext, QPainter, QPaintEngine, QPixmap, QTransform
from PyQt5.QtWidgets import QGraphicsPixmapItem, QStyleOptionGraphicsItem

from yesoncheck import error_window, gl_bindings, gl_video_item
from yesoncheck.gl_bindings import (
    GL_BLEND, GL_CLAMP_TO_EDGE, GL_MODELVIEW, GL_NEAREST, GL_PROJECTION, GL_QUADS, GL_RGB, GL_RGB8, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_UNPACK_ALIGNMENT,
    GL_UNPACK_ROW_LENGTH, GL_UNSIGNED_BYTE,
)
from yesoncheck.gl_video_item import VIDEO_ITEM_ENV, VideoFrameItem, use_stream_item, video_item_mode


def rgb(h=6, w=8, value=7):
    return np.full((h, w, 3), value, np.uint8)


# ---------------------------------------------------------------- 선택 규칙 (순수 함수)

@pytest.mark.parametrize("env, expected", [({}, "auto"), ({VIDEO_ITEM_ENV: ""}, "auto"), ({VIDEO_ITEM_ENV: "GL"}, "gl"), ({VIDEO_ITEM_ENV: "pixmap"}, "pixmap")])
def test_video_item_mode(env, expected):
    assert video_item_mode(env) == expected

def test_video_item_mode_rejects_unknown():
    with pytest.raises(ValueError, match=VIDEO_ITEM_ENV):
        video_item_mode({VIDEO_ITEM_ENV: "fast"})

def test_use_stream_item_follows_viewport_in_auto():
    assert use_stream_item(True, "auto") is True and use_stream_item(False, "auto") is False
    assert use_stream_item(True, "pixmap") is False

def test_forced_gl_needs_gl_viewport():
    assert use_stream_item(True, "gl") is True
    with pytest.raises(ValueError, match="GL 뷰포트"):
        use_stream_item(False, "gl")


# ---------------------------------------------------------------- 아이템 계약

def test_raster_item_is_a_plain_pixmap_item(qapp):
    item = VideoFrameItem(stream=False)
    item.setPixmap(QPixmap(320, 240))
    assert isinstance(item, QGraphicsPixmapItem) and item.pixmap().size().width() == 320 and item.frame() is None

def test_set_frame_keeps_array_and_placeholder_size(qapp):
    item = VideoFrameItem(stream=True)
    frame = rgb(6, 8)
    item.set_frame(frame)
    assert item.frame() is frame
    assert not item.pixmap().isNull() and (item.pixmap().width(), item.pixmap().height()) == (8, 6)
    assert item.boundingRect() == QRectF(0, 0, 8, 6)

def test_set_frame_reuses_placeholder_for_same_size(qapp):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb(6, 8))
    key = item.pixmap().cacheKey()
    item.set_frame(rgb(6, 8, value=9))
    assert item.pixmap().cacheKey() == key  # 자리표시자는 크기가 같으면 다시 만들지 않음
    item.set_frame(rgb(3, 4))
    assert (item.pixmap().width(), item.pixmap().height()) == (4, 3)

@pytest.mark.parametrize("bad, what", [
    (np.zeros((6, 8, 4), np.uint8), "채널"), (np.zeros((6, 8, 3), np.float32), "dtype"),
    (np.zeros((6, 16, 3), np.uint8)[:, ::2], "연속"), (np.zeros((6, 8), np.uint8), "3차원"),
])
def test_set_frame_rejects_bad_arrays(qapp, bad, what):
    item = VideoFrameItem(stream=True)
    with pytest.raises(ValueError, match=what):
        item.set_frame(bad)

def test_null_pixmap_clears_frame(qapp):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    item.setPixmap(QPixmap())
    assert item.pixmap().isNull() and item.frame() is None

def test_non_null_pixmap_becomes_frame(qapp):
    item = VideoFrameItem(stream=True)
    image = QImage(4, 2, QImage.Format_RGB888)
    image.fill(Qt.red)
    item.setPixmap(QPixmap.fromImage(image))
    assert item.frame().shape == (2, 4, 3) and tuple(item.frame()[0, 0]) == (255, 0, 0)


# ---------------------------------------------------------------- paint 가드 (GL 엔진 없음 → 기록 1회 + 창 1회 + 예외 없음)

@pytest.fixture
def shown(monkeypatch):
    calls = []
    monkeypatch.setattr(error_window, "show_window", lambda text: calls.append(text))
    return calls

def paint_with_raster(item):
    target = QImage(16, 16, QImage.Format_ARGB32)
    painter = QPainter(target)
    try:
        item.paint(painter, QStyleOptionGraphicsItem(), None)
    finally:
        painter.end()

def test_paint_without_gl_engine_fails_loudly_once(qapp, shown, capsys):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    paint_with_raster(item)
    paint_with_raster(item)
    qapp.processEvents()
    err = capsys.readouterr().err
    assert err.count("[표시] GL 텍스처 스트리밍 실패") == 1 and "Traceback" in err and f"{VIDEO_ITEM_ENV}=pixmap" in err
    assert len(shown) == 1 and f"{VIDEO_ITEM_ENV}=pixmap" in shown[0]
    assert item.failure_count == 1

def test_paint_without_frame_draws_nothing_and_does_not_fail(qapp, shown):
    item = VideoFrameItem(stream=True)
    paint_with_raster(item)
    assert item.failure_count == 0 and shown == []

class NoEnginePainter:
    """컨텍스트가 없는 QOpenGLWidget(offscreen, 또는 위젯 컨텍스트 생성 실패 — 강제 GL·cocoa 기본 모두)에 그릴 때의 painter — QPainter::begin이 실패해 paintEngine()이 None (offscreen 실측)."""
    def paintEngine(self):
        return None

def test_paint_without_engine_logs_once_and_does_not_fail(qapp, shown, capsys):
    """엔진 없는 paint는 기록 한 줄(아이템마다 한 번)만 — 창 없음·실패 아님 (모달 창을 띄우면 offscreen 시험이 멈춤 — test_gl_viewport의 gl_widget).
    엔진이 있는데 GL이 아니면 예전대로 _fail 길 — 두 경우가 섞이지 않음."""
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    item.paint(NoEnginePainter(), QStyleOptionGraphicsItem(), None)
    item.paint(NoEnginePainter(), QStyleOptionGraphicsItem(), None)
    qapp.processEvents()
    err = capsys.readouterr().err
    assert err.count("[표시] 페인트 엔진이 없어 영상 프레임을 그리지 못함") == 1
    assert "(GL 뷰포트 컨텍스트 없음 — offscreen이거나 컨텍스트 생성 실패)" in err  # 원인을 offscreen·강제 GL로 좁히지 않음
    assert item.failure_count == 0 and shown == []
    paint_with_raster(item)
    qapp.processEvents()
    assert "[표시] GL 텍스처 스트리밍 실패" in capsys.readouterr().err
    assert item.failure_count == 1 and len(shown) == 1

def test_oversized_frame_fails_loudly_once(qapp, shown, monkeypatch):
    """텍스처 한도 초과는 축소가 아니라 큰 실패 — 준비(bind)는 성공한 것처럼 꾸미고 저장소 확보에서 걸리게 한다."""
    class FakeGL:
        max_texture_size = 64
        def __getattr__(self, name):  # glXxx 호출은 전부 아무것도 안 함
            return lambda *a, **k: 0
        def check_error(self, where):
            pass
    monkeypatch.setattr(gl_bindings, "bind", lambda ctx: FakeGL())
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb(64, 128))
    item._gl = FakeGL()  # Ruling 1: bind는 paint에서만 불리므로 _ensure_storage 앞에 둔다
    with pytest.raises(gl_bindings.GLBindingError, match="128×64.*64"):
        item._ensure_storage(128, 64)  # paint 안에서 불리는 단계 — 직접 불러 메시지 확인
    item._fail(gl_bindings.GLBindingError("x"))
    item._fail(gl_bindings.GLBindingError("y"))
    qapp.processEvents()
    assert item.failure_count == 1 and len(shown) == 1


# ---------------------------------------------------------------- 그 밖의 계약 (브리프 밖 — 구현이 더한 동작)

def test_raster_item_refuses_set_frame(qapp):
    """stream=False는 그냥 픽스맵 아이템 — 배열을 받으면 내용 없는 자리표시자가 그려질 것이라 받지 않는다."""
    with pytest.raises(RuntimeError, match="stream"):
        VideoFrameItem(stream=False).set_frame(rgb())


# ---------------------------------------------------------------- _fail의 2차 가드 (알리다 또 실패해도 paint·Qt 루프 밖으로 내보내지 않음)

class BrokenStream:
    """쓰기마다 OSError — 디스크가 꽉 찬 기록 파일 대역."""
    def write(self, text):
        raise OSError(28, "No space left on device")
    def flush(self):
        raise OSError(28, "No space left on device")

def test_fail_itself_never_raises(qapp, shown, monkeypatch):
    original = io.StringIO()  # sys.__stderr__ 대역 (last resort가 쓰는 곳)
    monkeypatch.setattr(sys, "stderr", BrokenStream())
    monkeypatch.setattr(sys, "__stderr__", original)
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    paint_with_raster(item)
    paint_with_raster(item)
    qapp.processEvents()
    assert item.failure_count == 1
    assert original.getvalue().count("[표시] 오류를 알리지 못했습니다") == 1 and "OSError" in original.getvalue()
    assert len(shown) == 1  # 기록이 실패해도 창은 뜸

def test_fail_survives_exception_whose_str_fails(qapp, shown, monkeypatch, capsys):
    original = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", original)
    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError("str 실패")
    item = VideoFrameItem(stream=True)
    item._fail(Unprintable())
    qapp.processEvents()
    assert item.failure_count == 1 and shown == []
    assert "창을 띄우지 못했습니다" in original.getvalue() and "str 실패" in original.getvalue()

def test_failure_window_error_goes_to_last_resort(qapp, monkeypatch, capsys):
    original = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", original)
    def broken_window(text):
        raise RuntimeError("창 실패")
    monkeypatch.setattr(error_window, "show_window", broken_window)
    item = VideoFrameItem(stream=True)
    item._fail(gl_bindings.GLBindingError("x"))
    qapp.processEvents()  # 지연된 창 띄우기가 Qt 루프에서 돎 — 예외가 루프로 나가면 PyQt5가 프로세스를 끝냄
    assert "오류 창을 띄우지 못했습니다" in original.getvalue() and "창 실패" in original.getvalue()


# ---------------------------------------------------------------- GL 호출 순서 (가짜 GL에 기록 — 실제 GL 그리기는 Task 4의 cocoa 몫)

class RecordingGL:
    """glXxx 호출을 (이름, 인자)로 기록하는 가짜 GL. glGenTextures는 텍스처 이름을 5부터 차례로 채우고, fail_on 이름의 호출은
    기록한 뒤 RuntimeError."""
    max_texture_size = 4096
    def __init__(self):
        self.calls = []
        self.next_name = 5
        self.fail_on = None
    def __getattr__(self, name):
        if not name.startswith("gl"):
            raise AttributeError(name)
        def call(*args):
            self.calls.append((name, args))
            if name == self.fail_on:
                raise RuntimeError(f"가짜 GL 실패 @ {name}")
            if name == "glGenTextures":
                args[1][0] = self.next_name
                self.next_name += 1
        return call
    def check_error(self, where):
        self.calls.append(("check_error", (where,)))
    def names(self):
        return [name for name, _ in self.calls]

@pytest.fixture
def recording_gl(monkeypatch):
    gl = RecordingGL()
    monkeypatch.setattr(gl_bindings, "bind", lambda ctx: gl)
    return gl

def expected_draw(pw, ph, corners):
    """텍스처를 바인드한 뒤의 그리기 호출 — 순서까지 고정."""
    quad = []
    for (u, v), (x, y) in zip(((0, 0), (1, 0), (1, 1), (0, 1)), corners):
        quad += [("glTexCoord2f", (u, v)), ("glVertex2f", (x, y))]
    return [("glViewport", (0, 0, pw, ph)), ("glMatrixMode", (GL_PROJECTION,)), ("glLoadIdentity", ()),
            ("glOrtho", (0, pw, ph, 0, -1, 1)), ("glMatrixMode", (GL_MODELVIEW,)), ("glLoadIdentity", ()),
            ("glDisable", (GL_BLEND,)), ("glEnable", (GL_TEXTURE_2D,)), ("glColor4f", (1, 1, 1, 1)),
            ("glBegin", (GL_QUADS,)), *quad, ("glEnd", ()),
            ("glDisable", (GL_TEXTURE_2D,)), ("glBindTexture", (GL_TEXTURE_2D, 0)), ("check_error", ("draw",))]

@pytest.mark.parametrize("mode, expected", [(Qt.SmoothTransformation, gl_bindings.GL_LINEAR), (Qt.FastTransformation, gl_bindings.GL_NEAREST)])
def test_prepare_filter_follows_transformation_mode(qapp, recording_gl, mode, expected):
    item = VideoFrameItem(stream=True)
    item.setTransformationMode(mode)
    context = QOpenGLContext()  # 만들지(create) 않은 컨텍스트 — 신호 연결만 씀
    item._prepare(context)
    params = {args[1]: args[2] for name, args in recording_gl.calls if name == "glTexParameteri"}
    assert params == {GL_TEXTURE_MIN_FILTER: expected, GL_TEXTURE_MAG_FILTER: expected,
                      GL_TEXTURE_WRAP_S: GL_CLAMP_TO_EDGE, GL_TEXTURE_WRAP_T: GL_CLAMP_TO_EDGE}
    assert item._texture == 5 and item._context is context

def test_draw_call_sequence_is_fixed(qapp, recording_gl):
    item = VideoFrameItem(stream=True)
    frame = rgb(6, 8)
    item.set_frame(frame)
    item._prepare(QOpenGLContext())
    corners = [(10, 20), (90, 20), (90, 80), (10, 80)]
    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert recording_gl.calls == [
        ("check_error", ("native 진입 — 이전 GL 호출이 남긴 오류",)),  # 우리 GL 호출 전에 — Qt 엔진이 남긴 오류를 우리 탓으로 돌리지 않음
        ("glBindTexture", (GL_TEXTURE_2D, 5)),  # 저장소 — 업로드보다 먼저
        ("glTexImage2D", (GL_TEXTURE_2D, 0, GL_RGB8, 8, 6, 0, GL_RGB, GL_UNSIGNED_BYTE, None)),
        ("check_error", ("storage",)),
        ("glBindTexture", (GL_TEXTURE_2D, 5)),
        ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 1)),
        ("glPixelStorei", (GL_UNPACK_ROW_LENGTH, 0)),
        ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, 8, 6, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data)),
        ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 4)),  # GL 기본값으로 되돌림
        ("check_error", ("upload",)),
        *expected_draw(200, 100, corners),
    ]

    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)  # 같은 프레임 다시 그리기 — 저장소·업로드 없이 바인드 + 사각형만
    assert recording_gl.calls == [("check_error", ("native 진입 — 이전 GL 호출이 남긴 오류",)),
                                  ("glBindTexture", (GL_TEXTURE_2D, 5)), *expected_draw(200, 100, corners)]

    item.set_frame(rgb(3, 4))  # 크기가 바뀜 → 저장소 다시 잡고 올림
    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert recording_gl.names().count("glTexImage2D") == 1 and recording_gl.names().count("glTexSubImage2D") == 1

def test_failed_upload_still_restores_unpack_alignment(qapp, recording_gl):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    item._prepare(QOpenGLContext())
    recording_gl.fail_on = "glTexSubImage2D"
    with pytest.raises(RuntimeError, match="glTexSubImage2D"):
        item._draw_native(16, 16, [(0, 0)] * 4)
    assert recording_gl.calls[-2:] == [("glTexSubImage2D", recording_gl.calls[-2][1]), ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 4))]

def test_filter_follows_later_transformation_mode_change(qapp, recording_gl):
    item = VideoFrameItem(stream=True)
    item.setTransformationMode(Qt.SmoothTransformation)
    item.set_frame(rgb())
    item._prepare(QOpenGLContext())
    item._draw_native(16, 16, [(0, 0)] * 4)
    recording_gl.calls.clear()
    item.setTransformationMode(Qt.FastTransformation)  # 준비 뒤에 바뀜
    item._draw_native(16, 16, [(0, 0)] * 4)
    assert recording_gl.calls[:4] == [("check_error", ("native 진입 — 이전 GL 호출이 남긴 오류",)),
                                      ("glBindTexture", (GL_TEXTURE_2D, 5)),  # 바인드한 텍스처에 다시 세움
                                      ("glTexParameteri", (GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)),
                                      ("glTexParameteri", (GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST))]
    recording_gl.calls.clear()
    item._draw_native(16, 16, [(0, 0)] * 4)
    assert "glTexParameteri" not in recording_gl.names()  # 그대로면 다시 세우지 않음

def test_destroyed_context_drops_texture_and_next_context_uploads_again(qapp, recording_gl):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    context = QOpenGLContext()
    item._prepare(context)
    item._draw_native(16, 16, [(0, 0)] * 4)
    context.aboutToBeDestroyed.emit()
    assert item._texture is None and item._context is None
    recording_gl.calls.clear()
    item._prepare(QOpenGLContext())
    item._draw_native(16, 16, [(0, 0)] * 4)
    assert "glTexImage2D" in recording_gl.names() and "glTexSubImage2D" in recording_gl.names()  # 새 텍스처에 저장소·내용 다시


# ---------------------------------------------------------------- _paint_stream (GL2 엔진의 페인터 대역 — 좌표 규칙·native 블록·컨텍스트)

class FakeEngine:
    def type(self):
        return QPaintEngine.OpenGL2

class FakeDevice:
    """QOpenGLWidget 페인트 장치 대역: width/height는 논리 픽셀."""
    def __init__(self, width, height, dpr):
        self._size, self._dpr = (width, height), dpr
    def width(self):
        return self._size[0]
    def height(self):
        return self._size[1]
    def devicePixelRatioF(self):
        return self._dpr

class FakeGLPainter:
    """GL2 엔진의 QPainter 대역: combinedTransform은 아이템 → 물리 픽셀, begin/endNativePainting은 GL 기록에 함께 남김(순서 확인)."""
    def __init__(self, gl, transform, width=100, height=50, dpr=2.0):
        self.gl, self.transform, self.dev = gl, transform, FakeDevice(width, height, dpr)
    def paintEngine(self):
        return FakeEngine()
    def device(self):
        return self.dev
    def combinedTransform(self):
        return self.transform
    def beginNativePainting(self):
        self.gl.calls.append(("beginNativePainting", ()))
    def endNativePainting(self):
        self.gl.calls.append(("endNativePainting", ()))

@pytest.fixture
def gl_contexts(monkeypatch, recording_gl):
    """gl_video_item.QOpenGLContext 대역 — currentContext()가 current(만들지 않은 진짜 QOpenGLContext — 신호만 씀)를 돌려줌."""
    class Contexts:
        current = QOpenGLContext()
        @classmethod
        def currentContext(cls):
            return cls.current
    monkeypatch.setattr(gl_video_item, "QOpenGLContext", Contexts)
    return Contexts

def paint_gl(item, painter):
    item.paint(painter, QStyleOptionGraphicsItem(), None)

def test_paint_stream_uses_physical_viewport_and_mapped_corners(qapp, recording_gl, gl_contexts, shown):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb(6, 8))
    painter = FakeGLPainter(recording_gl, QTransform(2.5, 0, 0, 2.5, 10, 20), width=100, height=50, dpr=2.0)
    paint_gl(item, painter)
    assert item.failure_count == 0 and shown == []
    names, calls = recording_gl.names(), recording_gl.calls
    assert names[0] == "beginNativePainting" and names[-1] == "endNativePainting"  # GL 호출은 전부 native 블록 안
    assert names.index("glGenTextures") > names.index("beginNativePainting")  # 준비(_prepare)도 begin 뒤
    assert ("glViewport", (0, 0, 200, 100)) in calls and ("glOrtho", (0, 200, 100, 0, -1, 1)) in calls  # 논리 100×50 × dpr 2
    assert [args for name, args in calls if name == "glVertex2f"] == [(10, 20), (30, 20), (30, 35), (10, 35)]  # 매핑값 그대로 — dpr을 또 곱하지 않음

@pytest.mark.parametrize("logical, dpr, physical", [
    ((1487, 935), 1.5, (2231, 1403)),  # 2230.5 / 1402.5 — qRound는 .5를 올림 (파이썬 round는 짝수 쪽 2230 / 1402)
    ((1490, 800), 1.25, (1863, 1000)),  # 1862.5 — 가로만 .5
])
def test_paint_stream_rounds_like_qround(qapp, recording_gl, gl_contexts, shown, logical, dpr, physical):
    """Qt는 FBO·GL2 뷰포트 크기를 qRound(.5 올림)로 잡는다 — 파이썬 round(은행가 반올림)를 쓰면 .5에서 1px 어긋나 아래·오른쪽 가장자리에 이음매가 생김."""
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb(6, 8))
    painter = FakeGLPainter(recording_gl, QTransform(), width=logical[0], height=logical[1], dpr=dpr)
    paint_gl(item, painter)
    pw, ph = physical
    assert item.failure_count == 0 and shown == []
    calls = recording_gl.calls
    assert ("glViewport", (0, 0, pw, ph)) in calls and ("glOrtho", (0, pw, ph, 0, -1, 1)) in calls

def test_paint_stream_failure_ends_native_painting_and_fails_once(qapp, recording_gl, gl_contexts, shown, capsys):
    recording_gl.fail_on = "glTexSubImage2D"
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    painter = FakeGLPainter(recording_gl, QTransform())
    paint_gl(item, painter)
    paint_gl(item, painter)
    qapp.processEvents()
    names = recording_gl.names()
    assert names.count("beginNativePainting") == 1 and names[-1] == "endNativePainting"
    assert recording_gl.calls[-2] == ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 4))  # 정렬은 finally로 되돌린 뒤 end
    assert item.failure_count == 1 and len(shown) == 1
    assert "[표시] GL 텍스처 스트리밍 실패" in capsys.readouterr().err

def test_paint_stream_prepares_once_per_context_and_drops_old_context_signal(qapp, recording_gl, gl_contexts, shown):
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    painter = FakeGLPainter(recording_gl, QTransform())
    first = gl_contexts.current
    paint_gl(item, painter)
    paint_gl(item, painter)
    assert recording_gl.names().count("glGenTextures") == 1  # 같은 컨텍스트 — 준비 한 번
    second = QOpenGLContext()
    gl_contexts.current = second
    paint_gl(item, painter)
    names = recording_gl.names()
    assert names.count("glGenTextures") == 2 and names.count("glTexSubImage2D") == 2  # 새 컨텍스트 — 새 텍스처에 다시 올림
    assert item._context is second and item._texture == 6
    first.aboutToBeDestroyed.emit()  # 옛 컨텍스트가 이제 죽어도 새 텍스처는 그대로 (연결을 끊었음)
    assert item._context is second and item._texture == 6
    second.aboutToBeDestroyed.emit()
    assert item._context is None and item._texture is None
    assert item.failure_count == 0 and shown == []


# ---------------------------------------------------------------- 걸쇠 풀기 reset_failure (Settings → 재생 디코더 (Mac) — 스펙 2026-11-04 §5.4 ④)

MENU_HINT = "Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식) 으로 바꾸면 예전 방식으로 재생합니다"
ENV_HINT = f"{VIDEO_ITEM_ENV}=pixmap 으로 켜면 예전 방식으로 그립니다"


def test_reset_failure_lets_paint_run_again(qapp, recording_gl, gl_contexts, shown):
    """첫 실패 뒤에는 걸쇠가 걸려 paint가 GL을 부르지 않음 → reset_failure() 뒤 다음 paint가 실패한 단계(업로드)부터 다시 그림(같은 컨텍스트라 준비는
    다시 하지 않음). failure_count(알린 수)는 그대로이고, 풀린 뒤 다시 실패하면 다시 알림(기록·창 1회 더).

    깨지는 변경: _failed를 풀지 않으면 GL 호출이 없음; failure_count를 0으로 되돌리면 1 단언."""
    recording_gl.fail_on = "glTexSubImage2D"
    item = VideoFrameItem(stream=True)
    frame = rgb()
    item.set_frame(frame)
    painter = FakeGLPainter(recording_gl, QTransform())
    paint_gl(item, painter)
    qapp.processEvents()
    assert item.failure_count == 1 and len(shown) == 1
    recording_gl.calls.clear()
    paint_gl(item, painter)
    assert recording_gl.calls == []  # 걸쇠 — 그리지 않음

    recording_gl.fail_on = None
    item.reset_failure()
    paint_gl(item, painter)
    qapp.processEvents()
    names = recording_gl.names()
    assert "glGenTextures" not in names and "glTexImage2D" not in names  # 준비·저장소는 실패 전에 끝났음 — 그대로 씀
    assert ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, 8, 6, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data)) in recording_gl.calls
    assert recording_gl.calls[-2:] == [("check_error", ("draw",)), ("endNativePainting", ())]
    assert item.failure_count == 1 and len(shown) == 1

    recording_gl.fail_on = "glTexSubImage2D"
    item.set_frame(rgb(value=9))
    paint_gl(item, painter)
    qapp.processEvents()
    assert item.failure_count == 2 and len(shown) == 2  # 풀린 걸쇠는 다음 실패에서 다시 걸리고 다시 알림


def test_reset_failure_after_a_failed_context_switch_prepares_again(qapp, recording_gl, gl_contexts, shown, monkeypatch):
    """새 컨텍스트에서 준비하다(GL 함수 묶기) 실패한 뒤 걸쇠를 풀면 다음 paint가 그 컨텍스트에서 처음부터 준비 — 옛 컨텍스트의 신호는 실패 전에 이미
    끊었으므로 다시 끊으려다(TypeError) 또 실패하지 않음(_prepare가 끊자마자 _context를 비움). 그 뒤 옛 컨텍스트가 죽어도 새 텍스처는 그대로."""
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    painter = FakeGLPainter(recording_gl, QTransform())
    first = gl_contexts.current
    paint_gl(item, painter)
    second = gl_contexts.current = QOpenGLContext()

    def broken_bind(context):
        raise gl_bindings.GLBindingError("가짜 묶기 실패")

    monkeypatch.setattr(gl_bindings, "bind", broken_bind)
    paint_gl(item, painter)
    qapp.processEvents()
    assert item.failure_count == 1 and len(shown) == 1 and "가짜 묶기 실패" in shown[0]

    monkeypatch.setattr(gl_bindings, "bind", lambda context: recording_gl)
    item.reset_failure()
    recording_gl.calls.clear()
    paint_gl(item, painter)
    qapp.processEvents()
    assert item.failure_count == 1 and len(shown) == 1
    names = recording_gl.names()
    assert names.count("glGenTextures") == 1 and names.count("glTexSubImage2D") == 1  # 새 컨텍스트에서 준비·업로드
    assert item._context is second
    first.aboutToBeDestroyed.emit()
    assert item._context is second and item._texture is not None
    second.aboutToBeDestroyed.emit()
    assert item._context is None and item._texture is None


def test_reset_failure_schedules_a_repaint(qapp, shown, monkeypatch):
    """걸쇠를 풀면 다시 그리기를 예약 — 프레임이 바뀌지 않아도(바꿔 끼울 캡처가 없는 h264 등) 비어 있던 영상 영역이 지금 프레임으로 다시 그려짐."""
    item = VideoFrameItem(stream=True)
    item.set_frame(rgb())
    item._fail(gl_bindings.GLBindingError("x"))
    qapp.processEvents()  # 예약된 실패 창을 이 시험 안에서 (다음 시험의 shown에 새지 않게)
    assert len(shown) == 1
    updates = []
    monkeypatch.setattr(item, "update", lambda *args: updates.append(args))
    item.reset_failure()
    assert updates == [()] and item.failure_count == 1


@pytest.mark.parametrize("platform, menu", [("darwin", True), ("win32", False), ("linux", False)])
def test_failure_window_names_the_decoder_menu_on_mac(qapp, shown, monkeypatch, platform, menu):
    """Mac의 실패 창은 킬 스위치 안내 앞에 Settings → 재생 디코더 (Mac) → ffmpeg 안내 한 줄(그 선택이 걸쇠를 풂), Windows는 화면 그리기 메뉴 한 줄 — 그 밖의 플랫폼은 메뉴가 없으므로 예전 글 그대로."""
    monkeypatch.setattr(sys, "platform", platform)
    item = VideoFrameItem(stream=True)
    item._fail(gl_bindings.GLBindingError("x"))
    qapp.processEvents()
    [text] = shown
    assert text.endswith(ENV_HINT)
    if menu:
        assert text.endswith(f"\n\n{MENU_HINT}\n{ENV_HINT}")
    elif platform == "win32":
        assert "재생 디코더" not in text and text.endswith(f"x\n\n{gl_video_item.failure_menu_hint('win32')}\n{ENV_HINT}")
    else:
        assert "재생 디코더" not in text and text.endswith(f"x\n\n{ENV_HINT}")


# ---------------------------------------------------------------- CustomVideoWidget 연결

from PyQt5.QtWidgets import QGraphicsPixmapItem, QOpenGLWidget
from yesoncheck.video_widget import CustomVideoWidget


def test_offscreen_default_keeps_plain_pixmap_item(qapp):
    widget = CustomVideoWidget()
    assert type(widget.video_item) is QGraphicsPixmapItem and widget.video_item_stream is False

def test_forced_gl_viewport_installs_stream_item_below_wipe_lines(qapp, monkeypatch, capsys):
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    assert isinstance(widget.viewport(), QOpenGLWidget)
    assert isinstance(widget.video_item, VideoFrameItem) and widget.video_item_stream is True
    assert widget.scene.items()[-1] is widget.video_item  # 맨 아래(와이프 선·ROI보다 먼저 넣음)
    assert "[표시] GL 텍스처 스트리밍(VideoFrameItem)" in capsys.readouterr().out

def test_pixmap_toggle_keeps_pixmap_item_on_gl_viewport(qapp, monkeypatch, capsys):
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    monkeypatch.setenv(VIDEO_ITEM_ENV, "pixmap")
    widget = CustomVideoWidget()
    assert type(widget.video_item) is QGraphicsPixmapItem and widget.video_item_stream is False
    assert "[표시] QPixmap 경로" in capsys.readouterr().out

def _fake_cocoa(monkeypatch, context_ok):
    """test_gl_viewport._fake_platform과 같은 모양 — 위젯이 보는 platformName만 cocoa로, 컨텍스트 확인 결과는 context_ok
    (강제 토글 없이 cocoa 기본 경로의 연결부 platformName → viewport_mode → gl_context_available → use_stream_item을 그대로 태움)."""
    from types import SimpleNamespace

    from yesoncheck import video_widget as module

    monkeypatch.delenv("YESONCHECK_VIEWPORT", raising=False)
    monkeypatch.delenv(VIDEO_ITEM_ENV, raising=False)
    monkeypatch.setattr(module, "QApplication", SimpleNamespace(platformName=lambda: "cocoa"))
    monkeypatch.setattr(module, "gl_context_available", lambda: context_ok)

def test_cocoa_default_installs_stream_item_when_context_ok(qapp, monkeypatch, capsys):
    _fake_cocoa(monkeypatch, context_ok=True)
    widget = CustomVideoWidget()
    try:
        assert isinstance(widget.viewport(), QOpenGLWidget)
        assert isinstance(widget.video_item, VideoFrameItem) and widget.video_item_stream is True
        assert "[표시] GL 텍스처 스트리밍(VideoFrameItem)" in capsys.readouterr().out
    finally:
        widget.close()

def test_cocoa_default_keeps_pixmap_item_when_context_fails(qapp, monkeypatch, capsys):
    """확인 실패 → raster 뷰포트로 폴백(test_gl_viewport가 지킴)하고 아이템도 예전 픽스맵 — GL 표시 기록([표시])은 남기지 않음."""
    _fake_cocoa(monkeypatch, context_ok=False)
    widget = CustomVideoWidget()
    try:
        assert not isinstance(widget.viewport(), QOpenGLWidget)
        assert type(widget.video_item) is QGraphicsPixmapItem and widget.video_item_stream is False
        assert "[표시]" not in capsys.readouterr().out
    finally:
        widget.close()

def test_gl_toggle_on_raster_viewport_is_an_error(qapp, monkeypatch):
    monkeypatch.setenv(VIDEO_ITEM_ENV, "gl")
    with pytest.raises(ValueError, match="GL 뷰포트"):
        CustomVideoWidget()

def test_launch_rejects_bad_video_item_mode(qapp, monkeypatch):
    """test_movie_pipe_integration::test_launch_rejects_a_bad_mode_before_the_window과 같은 모양 — 창을 만들기 전에 ValueError."""
    import re
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 모드인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(VIDEO_ITEM_ENV, "fast")
    with pytest.raises(ValueError, match=re.escape(repr("fast"))):
        app_module.launch(["yesoncheck"])

def test_update_frame_streams_composed_wipe(qapp, monkeypatch):
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    a = np.full((4, 6, 3), 10, np.uint8)
    b = np.full((4, 6, 3), 200, np.uint8)
    widget.wipe_enabled_x, widget.wipe_position_x = True, 0.5
    widget.updateFrame(a, b)
    shown = widget.video_item.frame()
    assert shown.shape == (4, 6, 3) and shown[0, 2, 0] == 10 and shown[0, 3, 0] == 200  # numpy 합성 그대로
    widget.wipe_enabled_x = False  # 와이프를 끔 (켜 둔 채 B가 없으면 기존 코드가 B 쪽을 검정으로 합성 — raster와 같음)
    widget.updateFrame(a, None)
    assert widget.video_item.frame() is a  # 와이프 없으면 복사 없이 그대로

def test_update_frame_follows_resolution_change(qapp, monkeypatch):
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    widget.updateFrame(np.zeros((9, 16, 3), np.uint8), None)
    assert widget.scene.sceneRect() == QRectF(0, 0, 16, 9)
    widget.updateFrame(np.zeros((18, 32, 3), np.uint8), None)
    assert widget.scene.sceneRect() == QRectF(0, 0, 32, 18) and widget.video_item.boundingRect() == QRectF(0, 0, 32, 18)
    widget.updateFrame(None, None)
    assert widget.video_item.pixmap().isNull() and widget.video_item.frame() is None

def test_raster_update_frame_still_sets_a_pixmap(qapp, monkeypatch):
    widget = CustomVideoWidget()
    calls = []
    real = widget.video_item.setPixmap
    monkeypatch.setattr(widget.video_item, "setPixmap", lambda pm: (calls.append(pm), real(pm)))
    widget.updateFrame(np.full((4, 6, 3), 3, np.uint8), None)
    assert len(calls) == 1 and calls[0].width() == 6


# ---------------------------------------------------------------- IOSurface 그리기 (set_surface·set_sides — 가짜 GL·가짜 CGL에 기록; 실제 화면은 cocoa의 yc_app_pixel_check 몫)

import gc
import weakref
from types import SimpleNamespace

from PyQt5.QtWidgets import QApplication

from yesoncheck import frame_handles, gl_surface
from yesoncheck.gl_surface import GL_BGRA, GL_RGBA, GL_SCISSOR_TEST, GL_TEXTURE_RECTANGLE_ARB, GL_UNSIGNED_INT_8_8_8_8_REV

CGL_CTX = 0xC61
ENTRY = ("check_error", ("native 진입 — 이전 GL 호출이 남긴 오류",))
CORNERS = [(20, 10), (60, 10), (60, 30), (20, 30)]  # 아이템 (0,0)(4,0)(4,2)(0,2) × 10 + (20, 10) — fake_gl_item의 페인터
UNIT = ((0, 0), (1, 0), (1, 1), (0, 1))  # 2D 텍스처 좌표


class FakeCGL:
    """gl_surface.CGLFunctions 대역 — 호출을 RecordingGL 기록에 함께 남겨 GL 호출과의 순서를 본다. context가 current CGL 컨텍스트(0이면 없음)."""
    def __init__(self, gl):
        self.gl, self.context = gl, CGL_CTX
    def CGLGetCurrentContext(self):
        self.gl.calls.append(("CGLGetCurrentContext", ()))
        return self.context
    def CGLTexImageIOSurface2D(self, *args):
        self.gl.calls.append(("CGLTexImageIOSurface2D", args))
        return 0


class Owner:
    """keepalive 대역(버퍼 주인) — weakref로 수명을 본다."""


def native(w=4, h=2, surface=0x5000, pad=16):
    """w×h BGRX 네이티브 프레임(읽기 전용 — 디코더처럼) — 행 끝 pad 바이트 패딩(진짜 CVPixelBuffer처럼 bytesPerRow > 너비×4)."""
    handle = frame_handles.NativeHandle(iosurface=surface, width=w, height=h, index=0, keepalive=Owner())
    return frame_handles.wrap_native(memoryview(np.zeros((h, w * 4 + pad), np.uint8)).toreadonly(), handle)


@pytest.fixture
def fake_gl_item(qapp, recording_gl, gl_contexts, shown, monkeypatch):
    """스트림 아이템(Smooth — 앱과 같음) + 가짜 GL·CGL + GL2 페인터 대역(논리 100×50 × dpr 2 → 뷰포트 200×100, 모서리 CORNERS).
    기존 경로의 준비(_prepare — 2D 텍스처 5)는 미리 해 두고 기록을 비움 — 면 텍스처는 6부터. paint()는 기록을 비우고 한 번 그린 기록을 돌려줌."""
    cgl = FakeCGL(recording_gl)
    monkeypatch.setattr(gl_surface, "bind_cgl", lambda: cgl)
    item = VideoFrameItem(stream=True)
    item.setTransformationMode(Qt.SmoothTransformation)
    painter = FakeGLPainter(recording_gl, QTransform(10, 0, 0, 10, 20, 10), width=100, height=50, dpr=2.0)
    item._prepare(gl_contexts.current)
    recording_gl.calls.clear()

    def paint():
        recording_gl.calls.clear()
        paint_gl(item, painter)
        return normalized(recording_gl.calls)

    return SimpleNamespace(item=item, gl=recording_gl, cgl=cgl, contexts=gl_contexts, shown=shown, paint=paint)


def normalized(calls):
    """glGenTextures의 출력 배열(ctypes)은 비교할 수 없어 개수만 남김."""
    return [(name, args[:1]) if name == "glGenTextures" else (name, args) for name, args in calls]

def new_texture(target, name, where="prepare side", filt=gl_bindings.GL_LINEAR):
    return [("glGenTextures", (1,)), ("glBindTexture", (target, name)),
            ("glTexParameteri", (target, GL_TEXTURE_MIN_FILTER, filt)), ("glTexParameteri", (target, GL_TEXTURE_MAG_FILTER, filt)),
            ("glTexParameteri", (target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)), ("glTexParameteri", (target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)),
            ("glBindTexture", (target, 0)), ("check_error", (where,))]

def surface_bind(name, frame):
    handle = frame_handles.whole_surface_handle(frame)
    return [("glBindTexture", (GL_TEXTURE_RECTANGLE_ARB, name)), ("CGLGetCurrentContext", ()),
            ("CGLTexImageIOSurface2D", (CGL_CTX, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, handle.width, handle.height, GL_BGRA,
                                        GL_UNSIGNED_INT_8_8_8_8_REV, handle.iosurface, 0)),
            ("check_error", ("CGLTexImageIOSurface2D",))]

def rgb_storage(name, frame):
    h, w = frame.shape[:2]
    return [("glBindTexture", (GL_TEXTURE_2D, name)), ("glTexImage2D", (GL_TEXTURE_2D, 0, GL_RGB8, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, None)),
            ("check_error", ("storage",))]

def rgb_upload(name, frame):
    h, w = frame.shape[:2]
    return [("glBindTexture", (GL_TEXTURE_2D, name)), ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 1)), ("glPixelStorei", (GL_UNPACK_ROW_LENGTH, 0)),
            ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data)),
            ("glPixelStorei", (GL_UNPACK_ALIGNMENT, 4)), ("check_error", ("upload",))]

def setup(pw=200, ph=100):
    return [("glViewport", (0, 0, pw, ph)), ("glMatrixMode", (GL_PROJECTION,)), ("glLoadIdentity", ()),
            ("glOrtho", (0, pw, ph, 0, -1, 1)), ("glMatrixMode", (GL_MODELVIEW,)), ("glLoadIdentity", ()),
            ("glDisable", (GL_BLEND,)), ("glColor4f", (1, 1, 1, 1))]

def pixels(w, h):
    """사각형 텍스처 좌표 — 픽셀 단위."""
    return ((0, 0), (w, 0), (w, h), (0, h))

def quad(target, name, coords, corners=CORNERS):
    calls = [("glBindTexture", (target, name)), ("glEnable", (target,)), ("glBegin", (GL_QUADS,))]
    for (u, v), (x, y) in zip(coords, corners):
        calls += [("glTexCoord2f", (u, v)), ("glVertex2f", (x, y))]
    return calls + [("glEnd", ()), ("glDisable", (target,))]

def black(corners=CORNERS):
    return [("glColor4f", (0, 0, 0, 1)), ("glBegin", (GL_QUADS,)), *[("glVertex2f", corner) for corner in corners],
            ("glEnd", ()), ("glColor4f", (1, 1, 1, 1))]

def scissor(box):
    return [("glEnable", (GL_SCISSOR_TEST,)), ("glScissor", box)]

RESTORE = [("glDisable", (GL_SCISSOR_TEST,)), ("glDisable", (GL_TEXTURE_RECTANGLE_ARB,)), ("glDisable", (GL_TEXTURE_2D,)),
           ("glBindTexture", (GL_TEXTURE_RECTANGLE_ARB, 0)), ("glBindTexture", (GL_TEXTURE_2D, 0))]
END = [*RESTORE, ("check_error", ("draw sides",))]
BEGIN, FINISH = ("beginNativePainting", ()), ("endNativePainting", ())


def test_set_surface_binds_rect_texture_and_draws(fake_gl_item):
    """IOSurface → RECT 텍스처 → 픽셀 좌표 사각형, 순서까지 고정. CGLTexImageIOSurface2D 인자(GL_RGBA·GL_BGRA·…_REV·plane 0)·텍스처 좌표를
    0..1로(RECT는 픽셀 단위)·blend를 켠 채 그리기·RECT/scissor를 켠 채·바인딩을 남긴 채 나오기 중 하나라도 바뀌면 실패. CPU 업로드(glTexSubImage2D) 없음."""
    frame = native()
    fake_gl_item.item.set_surface(frame)
    assert fake_gl_item.paint() == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, frame),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *END, FINISH,
    ]
    assert fake_gl_item.item.failure_count == 0 and fake_gl_item.shown == []
    assert fake_gl_item.item.surface_handle() is frame.native


def test_set_sides_mixed_native_and_rgb_draws_both(fake_gl_item):
    """A 네이티브·B RGB(h264를 B로 연 와이프): A는 RECT 한 번 묶기, B는 두 번째 2D 텍스처(7)에 glTexSubImage2D 한 번 — 기존 텍스처 5는 건드리지 않음 —,
    B는 glScissor(오른쪽 — 모서리 매핑의 25% 자리 x=30부터) 안에서만, 검정 없음. B를 검정으로 두거나(np.zeros_like 규칙을 섞음) B를 텍스처 5에 올리거나
    scissor 밖에서 B를 그리면 실패."""
    a, b = native(), rgb(2, 4)
    fake_gl_item.item.set_sides(a, b, "x", 0.25)
    calls = fake_gl_item.paint()
    assert calls == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, a),
        *new_texture(GL_TEXTURE_2D, 7), *rgb_storage(7, b), *rgb_upload(7, b),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *scissor((30, 0, 170, 100)), *quad(GL_TEXTURE_2D, 7, UNIT),
        *END, FINISH,
    ]
    assert ("glColor4f", (0, 0, 0, 1)) not in calls
    assert fake_gl_item.item.failure_count == 0


def test_set_sides_rgb_native_other_way(fake_gl_item):
    """A RGB(h264)·B 네이티브, 아래쪽 와이프: A는 면 2D 텍스처(6), B는 RECT(7)를 glScissor(GL 창 좌표는 아래가 0 — 아래 80줄) 안에서.
    y 와이프의 scissor를 위쪽(0, split)으로 잡거나 A의 RGB를 기존 텍스처 5에 올리면 실패."""
    a, b = rgb(2, 4), native(surface=0x6000)
    fake_gl_item.item.set_sides(a, b, "y", 0.5)
    assert fake_gl_item.paint() == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_2D, 6), *rgb_storage(6, a), *rgb_upload(6, a),
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 7), *surface_bind(7, b),
        *setup(), *quad(GL_TEXTURE_2D, 6, UNIT),
        *scissor((0, 0, 200, 80)), *quad(GL_TEXTURE_RECTANGLE_ARB, 7, pixels(4, 2)),
        *END, FINISH,
    ]
    assert fake_gl_item.item.surface_handle() is None  # A가 표면이 아님


def test_set_sides_both_native_bind_two_rect_textures(fake_gl_item):
    """4K ProRes A/B 와이프(둘 다 네이티브): 면마다 RECT 텍스처 하나씩(6·7), 그릴 때 각자 다시 바인드. RECT 텍스처를 하나만 두면 B가 A를 덮어 실패."""
    a, b = native(), native(surface=0x6000)
    fake_gl_item.item.set_sides(a, b, "x", 0.5)
    assert fake_gl_item.paint() == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, a),
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 7), *surface_bind(7, b),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *scissor((40, 0, 160, 100)), *quad(GL_TEXTURE_RECTANGLE_ARB, 7, pixels(4, 2)),
        *END, FINISH,
    ]


def test_set_sides_without_b_draws_black_rect_for_b(fake_gl_item):
    """와이프인데 B가 없음 → B 자리를 scissor 안에서 검정 사각형으로(기존 numpy 합성의 np.zeros_like 규칙과 같은 그림), B 텍스처는 만들지 않음.
    검정을 빼면(A가 비침) 또는 scissor 밖까지 칠하면 실패."""
    a = native()
    fake_gl_item.item.set_sides(a, None, "x", 0.5)
    assert fake_gl_item.paint() == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, a),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *scissor((40, 0, 160, 100)), *black(),
        *END, FINISH,
    ]


def test_set_sides_xy_draws_b_in_two_scissor_boxes(fake_gl_item):
    """(Ruling 17) X·Y 와이프가 함께 켜지면 axis="xy"·ratio=(rx, ry): A는 한 번, B는 상자 둘 — 오른쪽 (split_x, 0, pw − split_x, ph)과 아래쪽
    (0, 0, pw, ph − split_y) — 에 차례로 그려 보이는 B는 합집합(기존 numpy 합성 result[:, wipe_x:] = B 뒤 result[wipe_y:, :] = B와 같음). B 텍스처는 한 번만
    올림. 상자 하나만 그리거나(교집합·한쪽만) A를 두 번 그리거나 B를 상자마다 다시 올리면 실패."""
    a, b = native(), rgb(2, 4)
    fake_gl_item.item.set_sides(a, b, "xy", (0.25, 0.5))
    calls = fake_gl_item.paint()
    assert calls == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, a),
        *new_texture(GL_TEXTURE_2D, 7), *rgb_storage(7, b), *rgb_upload(7, b),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *scissor((30, 0, 170, 100)), *quad(GL_TEXTURE_2D, 7, UNIT),
        ("glScissor", (0, 0, 200, 80)), *quad(GL_TEXTURE_2D, 7, UNIT),
        *END, FINISH,
    ]
    names = [name for name, _ in calls]
    assert names.count("glScissor") == 2 and names.count("glTexSubImage2D") == 1


def test_set_sides_xy_without_b_draws_black_in_both_boxes(fake_gl_item):
    """(Ruling 17) "xy"인데 B가 없으면 두 상자 모두 검정 — 기존 numpy 합성은 np.zeros_like를 두 영역에 넣음. 한 상자만 칠하면 A가 비쳐 실패."""
    a = native()
    fake_gl_item.item.set_sides(a, None, "xy", (0.5, 0.5))
    assert fake_gl_item.paint() == [
        BEGIN, ENTRY,
        *new_texture(GL_TEXTURE_RECTANGLE_ARB, 6), *surface_bind(6, a),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)),
        *scissor((40, 0, 160, 100)), *black(), ("glScissor", (0, 0, 200, 80)), *black(),
        *END, FINISH,
    ]


@pytest.mark.parametrize("axis, ratio", [
    ("xy", 0.5), ("xy", [0.25, 0.5]), ("xy", (0.5,)), ("xy", (0.5, 0.5, 0.5)), ("xy", (0.5, 1.5)), ("xy", (float("nan"), 0.5)),
    ("x", (0.25, 0.5)), ("y", (0.25, 0.5)),
], ids=["xy-float", "xy-list", "xy-one", "xy-three", "xy-out-of-range", "xy-nan", "x-pair", "y-pair"])
def test_set_sides_xy_requires_ratio_pair(fake_gl_item, axis, ratio):
    """(Ruling 17) "xy"의 ratio는 [0, 1] 실수 두 개의 tuple (rx, ry)만, "x"·"y"는 실수 하나만 — 어긋나면 ValueError(조용히 한 값을 두 축에 쓰거나 한쪽만
    쓰지 않음), 아이템은 그대로. 받아들이면 실패."""
    with pytest.raises(ValueError, match="ratio"):
        fake_gl_item.item.set_sides(native(), rgb(2, 4), axis, ratio)
    assert fake_gl_item.item.frame() is None and fake_gl_item.paint() == []


@pytest.mark.parametrize("b", [rgb(3, 4), np.zeros((2, 8, 3), np.uint8), "native"], ids=["rgb-taller", "rgb-wider", "native-other-size"])
def test_set_sides_b_of_other_size_draws_black(fake_gl_item, b):
    """B의 (높이, 너비)가 A와 다르면 기존 numpy 합성처럼(frame_b.shape != frame_a.shape → zeros) 검정 — 채널 수(BGRX 4 대 RGB 3)는 크기가 아님.
    다른 크기의 B를 A 사각형에 늘려 그리면(올리기·묶기) 실패."""
    if isinstance(b, str):
        b = native(w=8, h=4, surface=0x6000)
    fake_gl_item.item.set_sides(native(), b, "x", 0.5)
    calls = fake_gl_item.paint()
    assert calls[-len(black()) - len(END) - 1:] == [*black(), *END, FINISH]
    names = [name for name, _ in calls]
    assert names.count("CGLTexImageIOSurface2D") == 1 and "glTexSubImage2D" not in names


def test_context_destroyed_rebinds_surface_texture(fake_gl_item):
    """컨텍스트가 죽으면(aboutToBeDestroyed) RECT 텍스처 이름과 묶인 손잡이를 놓고, 다음 paint가 새 컨텍스트에서 glGenTextures + CGLTexImageIOSurface2D를
    다시 — _release_texture가 면 텍스처를 놓지 않으면 죽은 이름(6)을 새 컨텍스트에서 바인드하고 묶기를 건너뛰어(같은 손잡이) 실패."""
    frame = native()
    fake_gl_item.item.set_surface(frame)
    fake_gl_item.paint()
    fake_gl_item.contexts.current.aboutToBeDestroyed.emit()
    fake_gl_item.contexts.current = QOpenGLContext()
    assert fake_gl_item.paint() == [
        BEGIN, *new_texture(GL_TEXTURE_2D, 7, where="prepare"),  # 기존 준비(_prepare) 그대로
        ENTRY, *new_texture(GL_TEXTURE_RECTANGLE_ARB, 8), *surface_bind(8, frame),
        *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 8, pixels(4, 2)),
        *END, FINISH,
    ]


def test_context_switch_drops_surface_textures_of_the_old_context(fake_gl_item):
    """죽지 않은 다른 컨텍스트로 넘어가도(_prepare) 옛 컨텍스트의 면 텍스처는 버리고 새로 만들어 다시 묶음; 그 뒤 옛 컨텍스트가 죽어도 새 텍스처는 그대로.
    _prepare가 면 텍스처를 비우지 않으면 옛 컨텍스트의 이름을 새 컨텍스트에서 써서 실패."""
    frame = native()
    fake_gl_item.item.set_surface(frame)
    fake_gl_item.paint()
    old = fake_gl_item.contexts.current
    fake_gl_item.contexts.current = QOpenGLContext()
    names = [name for name, _ in fake_gl_item.paint()]
    assert names.count("glGenTextures") == 2 and names.count("CGLTexImageIOSurface2D") == 1  # 2D(준비) + RECT, 다시 묶음
    old.aboutToBeDestroyed.emit()
    names = [name for name, _ in fake_gl_item.paint()]
    assert "glGenTextures" not in names and "CGLTexImageIOSurface2D" not in names


def test_rebind_only_when_handle_changes(fake_gl_item):
    """같은 프레임을 다시 그리면 묶기 없이 바인드 + 사각형만(CGLTexImageIOSurface2D 한 번), 같은 프레임을 다시 넘겨도(같은 손잡이) 그대로, 새 손잡이면 같은
    텍스처(6)에 다시 묶음. 손잡이 비교를 빼면(paint마다 묶기) 또는 이름을 새로 만들면 실패."""
    item = fake_gl_item.item
    first = native()
    item.set_surface(first)
    fake_gl_item.paint()
    assert fake_gl_item.paint() == [BEGIN, ENTRY, ("glBindTexture", (GL_TEXTURE_RECTANGLE_ARB, 6)),
                                    *setup(), *quad(GL_TEXTURE_RECTANGLE_ARB, 6, pixels(4, 2)), *END, FINISH]
    item.set_surface(first)
    assert "CGLTexImageIOSurface2D" not in [name for name, _ in fake_gl_item.paint()]
    second = native(surface=0x7000)
    item.set_surface(second)
    calls = fake_gl_item.paint()
    assert calls[:len(surface_bind(6, second)) + 2] == [BEGIN, ENTRY, *surface_bind(6, second)]
    assert "glGenTextures" not in [name for name, _ in calls]


def test_rgb_side_uploads_only_when_the_array_changes(fake_gl_item):
    """RGB 면도 같은 배열이면 다시 올리지 않음(set_frame과 같은 약속 — 넘긴 배열은 고치지 않음), 새 배열이면 같은 저장소에 올림(크기가 같으면 glTexImage2D 없음)."""
    item, a, b = fake_gl_item.item, native(), rgb(2, 4)
    item.set_sides(a, b, "x", 0.5)
    fake_gl_item.paint()
    names = [name for name, _ in fake_gl_item.paint()]
    assert "glTexSubImage2D" not in names and "glTexImage2D" not in names
    other = rgb(2, 4, value=9)
    item.set_sides(a, other, "x", 0.5)
    calls = fake_gl_item.paint()
    assert [args for name, args in calls if name == "glTexSubImage2D"] == [rgb_upload(7, other)[3][1]]
    assert "glTexImage2D" not in [name for name, _ in calls]


def test_surface_filter_follows_transformation_mode(fake_gl_item):
    """(스파이크 검토 지적) RECT 텍스처 필터도 2D 경로처럼 transformationMode()를 따름 — 만들 때 한 번만 세우면 Fast로 바꿔도 GL_LINEAR로 남아 실패."""
    item = fake_gl_item.item
    item.set_surface(native())
    fake_gl_item.paint()
    item.setTransformationMode(Qt.FastTransformation)
    assert fake_gl_item.paint()[:5] == [BEGIN, ENTRY, ("glBindTexture", (GL_TEXTURE_RECTANGLE_ARB, 6)),
                                        ("glTexParameteri", (GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)),
                                        ("glTexParameteri", (GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST))]
    assert "glTexParameteri" not in [name for name, _ in fake_gl_item.paint()]


def test_existing_rgb_path_unchanged(fake_gl_item):
    """set_frame 뒤 paint는 예전 호출 그대로 — _draw_native 자체의 순서는 test_draw_call_sequence_is_fixed가 고정하고(재사용: expected_draw), 여기서는
    paint의 갈래와 set_sides → set_frame 전환을 본다: 면 텍스처·CGL·scissor가 끼지 않고, 와이프 B의 RGB 업로드가 기존 2D 텍스처(5)의 저장소를 건드리지 않아
    돌아온 set_frame은 저장소를 다시 잡지 않고 올리기만 함. set_frame이 _sides를 비우지 않거나 B의 RGB를 텍스처 5에 올리면 실패."""
    item = fake_gl_item.item
    first = rgb(2, 4)
    item.set_frame(first)
    assert fake_gl_item.paint() == [BEGIN, ENTRY, *rgb_storage(5, first), *rgb_upload(5, first),
                                    *normalized(expected_draw(200, 100, CORNERS)), FINISH]
    item.set_sides(native(), rgb(2, 4, value=3), "x", 0.5)
    fake_gl_item.paint()
    second = rgb(2, 4, value=9)
    item.set_frame(second)
    assert item.surface_handle() is None and item.frame() is second
    assert fake_gl_item.paint() == [BEGIN, ENTRY, *rgb_upload(5, second), *normalized(expected_draw(200, 100, CORNERS)), FINISH]


def test_null_pixmap_clears_sides(fake_gl_item):
    """빈 픽스맵(updateFrame(None, …))은 면까지 비움 — 남기면 다음 paint가 지난 IOSurface를 계속 그림."""
    item = fake_gl_item.item
    item.set_sides(native(), None, "x", 0.5)
    item.setPixmap(QPixmap())
    assert item.frame() is None and item.surface_handle() is None and item.pixmap().isNull()
    assert fake_gl_item.paint() == []


def test_set_sides_keeps_frames_and_sets_placeholder(fake_gl_item):
    """자리표시자 픽스맵은 A의 크기(boundingRect·fitInView 계약 — set_frame과 같음), frame()은 A, surface_handle()은 A의 손잡이(A가 RGB면 None)."""
    item, a = fake_gl_item.item, native()
    item.set_sides(a, rgb(2, 4), "x", 0.5)
    assert item.frame() is a and item.surface_handle() is a.native
    assert (item.pixmap().width(), item.pixmap().height()) == (4, 2) and item.boundingRect() == QRectF(0, 0, 4, 2)
    item.set_sides(rgb(2, 4), a, "x", 0.5)
    assert item.surface_handle() is None


def test_plain_view_of_whole_surface_is_drawn_as_surface(fake_gl_item):
    """표면 전체를 가리키는 일반 ndarray 뷰(np.asarray)도 표면으로 — 판별은 whole_surface_handle(Ruling 14) 하나. isinstance나 native_surface_of로
    가르면 이 뷰가 'RGB가 아닌 4채널 배열'로 거부되어 실패."""
    frame = native()
    fake_gl_item.item.set_surface(np.asarray(frame))
    assert fake_gl_item.item.surface_handle() is frame.native
    assert surface_bind(6, frame)[2] in fake_gl_item.paint()


@pytest.mark.parametrize("view", [lambda f: f[::-1], lambda f: f[:, :2], lambda f: f[..., ::-1]], ids=["flipped", "cropped", "channels-reversed"])
def test_non_whole_surface_native_array_is_rejected(fake_gl_item, view):
    """손잡이는 있지만 표면 전체가 아닌 뷰(상하 반전·조각·채널 역순)는 어느 자리로 와도 ValueError — 표면으로 묶으면 다른 그림이 나오고, 복사·업로드는
    네이티브 경로의 약속(CPU 복사 0) 위반. native_surface_of(손잡이 있음)로만 가르면 실패. 거부할 때 아이템 상태는 그대로."""
    item, frame = fake_gl_item.item, native()
    bad = view(frame)
    assert frame_handles.native_surface_of(bad) is frame.native and frame_handles.whole_surface_handle(bad) is None
    for call in (lambda: item.set_surface(bad), lambda: item.set_sides(bad, None, None, 0.0),
                 lambda: item.set_sides(native(), bad, "x", 0.5)):
        with pytest.raises(ValueError, match="표면 전체"):
            call()
    assert item.frame() is None and item.pixmap().isNull() and fake_gl_item.paint() == []


@pytest.mark.parametrize("args, what", [
    ((None, None, None, 0.0), "A 면"),
    ((rgb(2, 4), None, "xz", 0.5), "axis"),
    ((rgb(2, 4), None, "x", 1.5), "ratio"),
    ((rgb(2, 4), None, "x", float("nan")), "ratio"),
    ((np.zeros((2, 4, 3), np.float32), None, None, 0.0), "dtype"),
    ((np.zeros((2, 4, 4), np.uint8), None, None, 0.0), "채널"),  # 손잡이 없는 BGRX 일반 배열 — 네이티브도 RGB도 아님
    ((rgb(2, 4), np.zeros((2, 8, 3), np.uint8)[:, ::2], "x", 0.5), "연속"),
    ((rgb(2, 4), np.zeros((2, 4), np.uint8), "x", 0.5), "3차원"),
])
def test_set_sides_rejects_bad_arguments(fake_gl_item, args, what):
    """조건이 어긋나면 어느 조건인지 ValueError(조용한 복사·변환·자르기 없음) — set_frame과 같은 규칙에 면 이름을 붙임."""
    with pytest.raises(ValueError, match=what):
        fake_gl_item.item.set_sides(*args)
    assert fake_gl_item.item.frame() is None


def test_set_surface_needs_a_native_frame_and_stream_item(qapp):
    """set_surface는 표면 전체 네이티브 프레임만(RGB는 set_frame), stream=False 아이템은 set_sides·set_surface를 받지 않음(set_frame과 같음)."""
    with pytest.raises(ValueError, match="네이티브"):
        VideoFrameItem(stream=True).set_surface(rgb(2, 4))
    raster = VideoFrameItem(stream=False)
    for call in (lambda: raster.set_surface(native()), lambda: raster.set_sides(native(), None, None, 0.0)):
        with pytest.raises(RuntimeError, match="stream"):
            call()


def test_surface_stays_alive_while_bound_and_is_released_with_context(fake_gl_item):
    """IOSurface 수명: 아이템이 받은 프레임을 쥐고(부른 쪽이 놓아도), RECT 텍스처가 그 표면에 묶여 있는 동안은 손잡이를 쥐며(RGB 경로로 돌아가도),
    다른 손잡이로 다시 묶거나 컨텍스트가 죽으면 놓음. 프레임·손잡이를 쥐지 않으면 버퍼가 풀(pool)로 돌아가 묶인 표면이 다른 프레임으로 덮여 실패,
    놓지 않으면 버퍼가 샘."""
    item = fake_gl_item.item
    frame = native()
    first = weakref.ref(frame.native.keepalive)
    item.set_surface(frame)
    del frame
    gc.collect()
    assert first() is not None  # 아이템이 프레임을 쥠
    fake_gl_item.paint()
    item.set_frame(rgb(2, 4))
    gc.collect()
    assert first() is not None  # RECT 텍스처가 아직 그 표면에 묶여 있음
    item.set_surface(native(surface=0x7000))
    fake_gl_item.paint()  # 같은 텍스처를 새 표면에 다시 묶음 → 옛 손잡이를 놓음
    gc.collect()
    assert first() is None
    second = weakref.ref(item.surface_handle().keepalive)
    item.set_frame(rgb(2, 4))
    fake_gl_item.contexts.current.aboutToBeDestroyed.emit()
    gc.collect()
    assert second() is None


def test_no_wipe_neither_draws_nor_holds_b(fake_gl_item):
    """axis None이면 B는 그리지도 쥐지도 않음 — 쥐면 와이프를 끈 동안 B의 IOSurface 버퍼가 풀로 돌아가지 못하고 묶이지도 않은 채 남아 실패."""
    b = native(surface=0x6000)
    held = weakref.ref(b.native.keepalive)
    fake_gl_item.item.set_sides(native(), b, None, 0.0)
    del b
    gc.collect()
    assert held() is None
    calls = fake_gl_item.paint()
    assert [args[-2] for name, args in calls if name == "CGLTexImageIOSurface2D"] == [0x5000] and "glScissor" not in [name for name, _ in calls]


def test_surface_bind_failure_fails_loudly_once(fake_gl_item, capsys):
    """CGL 컨텍스트가 없으면(NULL) 묶지 않고 GLBindingError → 기존 paint 가드(_fail: 기록 + 창 1회, 그 뒤 그리지 않음) — 상태를 되돌린 뒤 native 블록을 닫음.
    0을 그대로 CGLTexImageIOSurface2D에 넘기면(CGL이 무엇을 할지 모름) 또는 가드를 거치지 않으면 실패."""
    fake_gl_item.cgl.context = 0
    fake_gl_item.item.set_surface(native())
    calls = fake_gl_item.paint()
    assert fake_gl_item.paint() == []  # 첫 실패 뒤로는 그리지 않음
    QApplication.instance().processEvents()  # 창은 Qt 루프에서 뜸
    assert calls[-len(RESTORE) - 2:] == [("CGLGetCurrentContext", ()), *RESTORE, FINISH]
    assert fake_gl_item.item.failure_count == 1 and len(fake_gl_item.shown) == 1
    assert "CGLGetCurrentContext" in capsys.readouterr().err


def test_failure_while_drawing_sides_still_restores_gl_state(fake_gl_item):
    """그리는 도중 실패해도(가짜 GL이 glScissor에서 실패) scissor·RECT·2D를 끄고 바인딩 0을 둔 뒤 native 블록을 닫음 — finally가 없으면 scissor가 켜진 채
    Qt 엔진으로 돌아가 실패."""
    fake_gl_item.gl.fail_on = "glScissor"
    fake_gl_item.item.set_sides(native(), None, "x", 0.5)
    calls = fake_gl_item.paint()
    QApplication.instance().processEvents()  # 실패 창은 Qt 루프에서 뜸 — 여기서 비우지 않으면 대역이 풀린 뒤 다른 시험에서 진짜 모달이 뜸
    assert calls[-len(RESTORE) - 2:] == [("glScissor", (40, 0, 160, 100)), *RESTORE, FINISH]
    assert fake_gl_item.item.failure_count == 1 and len(fake_gl_item.shown) == 1


@pytest.mark.parametrize("axis, ratio, corners, box", [
    ("x", 0.25, CORNERS, (30, 0, 170, 100)),
    ("x", 0.0, CORNERS, (20, 0, 180, 100)),
    ("x", 1.0, CORNERS, (60, 0, 140, 100)),
    ("y", 0.5, CORNERS, (0, 0, 200, 80)),
    ("x", 0.5, [(10.2, 0), (11.2, 0), (11.2, 5), (10.2, 5)], (11, 0, 189, 100)),  # 10.7 → qRound처럼 .5 올림
    ("x", 0.5, [(-100, 0), (-20, 0), (-20, 50), (-100, 50)], (0, 0, 200, 100)),  # 나눔 자리가 뷰포트 왼쪽 밖 — 0으로
    ("x", 0.5, [(250, 0), (400, 0), (400, 50), (250, 50)], (200, 0, 0, 100)),  # 오른쪽 밖 — 너비 0
    ("y", 0.5, [(0, -100), (50, -100), (50, -50), (0, -50)], (0, 0, 200, 100)),  # 위 밖 — B가 뷰포트 전체
    ("y", 0.5, [(0, 150), (50, 150), (50, 300), (0, 300)], (0, 0, 200, 0)),  # 아래 밖 — 높이 0
])
def test_wipe_scissor_box(axis, ratio, corners, box):
    """B 면의 scissor 상자(GL 창 좌표 — 물리 픽셀, 원점 왼쪽 아래): x는 오른쪽 (split, 0, pw − split, ph), y는 아래쪽 (0, 0, pw, ph − split),
    split은 모서리 매핑의 비율 자리(스파이크와 같은 계산)이고 뷰포트 [0, pw]·[0, ph]로 자름. 음수 너비·높이는 GL_INVALID_VALUE라 자르지 않으면 실패."""
    assert gl_video_item.wipe_scissor(axis, ratio, 200, 100, corners) == box
