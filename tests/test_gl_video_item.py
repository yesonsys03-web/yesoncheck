import numpy as np
import pytest
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QImage, QOpenGLContext, QPainter, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QStyleOptionGraphicsItem

from yesoncheck import error_window, gl_bindings
from yesoncheck.gl_bindings import (
    GL_CLAMP_TO_EDGE, GL_RGB, GL_RGB8, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_UNPACK_ALIGNMENT, GL_UNSIGNED_BYTE,
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


# ---------------------------------------------------------------- GL 호출 순서 (가짜 GL에 기록 — 실제 GL 그리기는 Task 4의 cocoa 몫)

class RecordingGL:
    """glXxx 호출을 (이름, 인자)로 기록하는 가짜 GL. glGenTextures는 텍스처 이름 5를 채운다."""
    max_texture_size = 4096
    def __init__(self):
        self.calls = []
    def __getattr__(self, name):
        if not name.startswith("gl"):
            raise AttributeError(name)
        def call(*args):
            self.calls.append((name, args))
            if name == "glGenTextures":
                args[1]._obj.value = 5  # ctypes.byref(c_uint)의 대상
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

def test_draw_uploads_only_new_frames_and_maps_corners_as_given(qapp, recording_gl):
    item = VideoFrameItem(stream=True)
    frame = rgb(6, 8)
    item.set_frame(frame)
    item._prepare(QOpenGLContext())
    corners = [(10, 20), (90, 20), (90, 80), (10, 80)]
    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)
    calls = recording_gl.calls
    assert ("glTexImage2D", (GL_TEXTURE_2D, 0, GL_RGB8, 8, 6, 0, GL_RGB, GL_UNSIGNED_BYTE, None)) in calls
    upload = ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, 8, 6, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data))
    assert calls.index(("glPixelStorei", (GL_UNPACK_ALIGNMENT, 1))) < calls.index(upload) \
        < calls.index(("glPixelStorei", (GL_UNPACK_ALIGNMENT, 4)))  # 정렬은 GL 기본값으로 되돌림
    assert ("glViewport", (0, 0, 200, 100)) in calls and ("glOrtho", (0, 200, 100, 0, -1, 1)) in calls
    quad = [args for name, args in calls if name in ("glTexCoord2f", "glVertex2f")]
    assert quad == [(0, 0), (10, 20), (1, 0), (90, 20), (1, 1), (90, 80), (0, 1), (10, 80)]
    assert calls[-3:] == [("glDisable", (GL_TEXTURE_2D,)), ("glBindTexture", (GL_TEXTURE_2D, 0)), ("check_error", ("draw",))]

    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)  # 같은 프레임 다시 그리기 — 저장소·업로드 없이 사각형만
    assert "glTexImage2D" not in recording_gl.names() and "glTexSubImage2D" not in recording_gl.names()
    assert "glEnd" in recording_gl.names()

    item.set_frame(rgb(3, 4))  # 크기가 바뀜 → 저장소 다시 잡고 올림
    recording_gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert recording_gl.names().count("glTexImage2D") == 1 and recording_gl.names().count("glTexSubImage2D") == 1

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
