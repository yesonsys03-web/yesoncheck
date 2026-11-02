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
    """초기화되지 않은 QOpenGLWidget(offscreen·컨텍스트가 안 생긴 강제 GL)에 그릴 때의 painter — QPainter::begin이 실패해 paintEngine()이 None (offscreen 실측)."""
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
    assert capsys.readouterr().err.count("[표시] 페인트 엔진이 없어 영상 프레임을 그리지 못함") == 1
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
    assert recording_gl.calls == [("glBindTexture", (GL_TEXTURE_2D, 5)), *expected_draw(200, 100, corners)]

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
    assert recording_gl.calls[:3] == [("glBindTexture", (GL_TEXTURE_2D, 5)),  # 바인드한 텍스처에 다시 세움
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
