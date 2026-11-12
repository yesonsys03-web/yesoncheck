"""GPU 그리기(GL 텍스처 스트리밍)의 축소 필터 '고품질' — 줄여 그릴 때 면적 평균으로 줄인 그림을 텍스처로 올려 정수 픽셀 자리에 1:1로 (2026-11-12).

사용자 보고(Windows, 화면 그리기 GPU): 창에 맞춰 줄인 화면의 가는 선이 지글거림 — GL_LINEAR(겹선형)는 반쯤으로 줄일 때 원본 픽셀을 띄엄띄엄 고름.
Settings → 축소 필터 (Windows) → 고품질이면 프레임을 그릴 크기로 면적 평균해(CPU) 그 작은 그림을 올리고, 사각형을 정수 장치 픽셀에 맞춰 그려
텍스처 픽셀 = 화면 픽셀이 되게 함. 새 GL 기능(밉맵 등)은 쓰지 않음 — 호출의 종류·차례는 그대로이고 텍스처 크기·올리는 그림·사각형 자리만 다름.
**기본(Linear)은 GL 호출이 예전과 글자 그대로 같음**(test_gl_video_item의 호출 순서 시험이 무수정 통과 — Mac은 늘 이쪽).

가짜 GL에 호출을 기록하고 올린 픽셀을 그 자리에서 복사해 봄. 실제 GL 화면은 Windows 실기 몫.
"""

import ctypes

import numpy as np
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QOpenGLContext, QTransform

from tests.test_gl_video_item import FakeGLPainter, RecordingGL, expected_draw, paint_gl, shown  # noqa: F401 (shown: fixture)
from yesoncheck import downscale_filter, gl_bindings, gl_video_item
from yesoncheck.gl_bindings import GL_RGB, GL_RGB8, GL_TEXTURE_2D, GL_UNSIGNED_BYTE
from yesoncheck.gl_video_item import VideoFrameItem

WIDTH, HEIGHT = 160, 40
ENTRY = ("check_error", ("native 진입 — 이전 GL 호출이 남긴 오류",))


class UploadCapturingGL(RecordingGL):
    """RecordingGL + glTexSubImage2D가 받은 픽셀을 그 자리에서 복사해 둠 (줄인 그림은 업로드 뒤 사라지는 임시 배열이라 주소만으로는 못 봄)."""

    def __init__(self):
        super().__init__()
        self.uploads = []

    def __getattr__(self, name):
        call = super().__getattr__(name)
        if name != "glTexSubImage2D":
            return call

        def upload(*args):
            width, height, pointer = args[4], args[5], args[8]
            self.uploads.append(np.frombuffer(ctypes.string_at(pointer, width * height * 3), np.uint8).reshape(height, width, 3))
            call(*args)

        return upload


@pytest.fixture
def gl(monkeypatch):
    fake = UploadCapturingGL()
    monkeypatch.setattr(gl_bindings, "bind", lambda context: fake)
    return fake


@pytest.fixture
def area():
    """축소 필터 = 고품질 (conftest가 시험 뒤 Linear로 되돌림)."""
    downscale_filter.set_preferred("area")


def stripes():
    """4픽셀마다 1픽셀짜리 검은 세로선 (선화의 가는 선)."""
    frame = np.full((HEIGHT, WIDTH, 3), 255, np.uint8)
    frame[:, ::4] = 0
    return frame


def noise(seed=1):
    return np.random.default_rng(seed).integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8)


def box(x, y, width, height):
    """아이템의 (0,0)(w,0)(w,h)(0,h)가 매핑된 물리 픽셀 모서리 — 왼쪽 위 (x, y), 크기 width×height."""
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def prepared(frame):
    item = VideoFrameItem(stream=True)
    item.setTransformationMode(Qt.SmoothTransformation)
    item.set_frame(frame)
    item._prepare(QOpenGLContext())
    return item


def storage_sizes(gl):
    return [(args[3], args[4]) for name, args in gl.calls if name == "glTexImage2D"]


def vertices(gl):
    return [args for name, args in gl.calls if name == "glVertex2f"]


# ---------------------------------------------------------------- 기본(Linear) — 예전 그대로


def test_the_default_filter_uploads_the_frame_itself_and_draws_at_the_mapped_corners(qapp, gl):
    """줄여 그리는 자리여도 기본값이면 프레임 그대로 올리고 매핑된(소수) 모서리에 그림 — 호출 전체가 예전 순서."""
    frame = stripes()
    item = prepared(frame)
    corners = box(10.4, 20.6, WIDTH * 0.25, HEIGHT * 0.25)
    gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert gl.calls == [
        ENTRY,
        ("glBindTexture", (GL_TEXTURE_2D, 5)),
        ("glTexImage2D", (GL_TEXTURE_2D, 0, GL_RGB8, WIDTH, HEIGHT, 0, GL_RGB, GL_UNSIGNED_BYTE, None)),
        ("check_error", ("storage",)),
        ("glBindTexture", (GL_TEXTURE_2D, 5)),
        ("glPixelStorei", (gl_bindings.GL_UNPACK_ALIGNMENT, 1)),
        ("glPixelStorei", (gl_bindings.GL_UNPACK_ROW_LENGTH, 0)),
        ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, WIDTH, HEIGHT, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data)),
        ("glPixelStorei", (gl_bindings.GL_UNPACK_ALIGNMENT, 4)),
        ("check_error", ("upload",)),
        *expected_draw(200, 100, corners),
    ]


# ---------------------------------------------------------------- 고품질(면적 평균)


def test_a_minified_frame_is_area_scaled_and_drawn_on_whole_pixels(qapp, gl, area):
    """0.25배 자리 (10.4, 20.6)–(50.4, 30.6): 40×10으로 면적 평균한 그림을 올리고 사각형은 정수 자리 (10, 21)–(50, 31) — 텍스처 픽셀 = 화면 픽셀."""
    frame = stripes()
    item = prepared(frame)
    gl.calls.clear()
    item._draw_native(200, 100, box(10.4, 20.6, WIDTH * 0.25, HEIGHT * 0.25))
    snapped = box(10, 21, 40, 10)
    upload = next(args for name, args in gl.calls if name == "glTexSubImage2D")
    assert [name for name, _ in gl.calls] == [name for name, _ in [
        ENTRY, ("glBindTexture", ()), ("glTexImage2D", ()), ("check_error", ()), ("glBindTexture", ()), ("glPixelStorei", ()), ("glPixelStorei", ()),
        ("glTexSubImage2D", ()), ("glPixelStorei", ()), ("check_error", ()), *expected_draw(200, 100, snapped)]]  # 호출의 종류·차례는 예전과 같음
    assert storage_sizes(gl) == [(40, 10)]
    assert upload[:8] == (GL_TEXTURE_2D, 0, 0, 0, 40, 10, GL_RGB, GL_UNSIGNED_BYTE)
    assert gl.calls[-len(expected_draw(200, 100, snapped)):] == expected_draw(200, 100, snapped)
    [small] = gl.uploads
    assert np.array_equal(small, downscale_filter.area_scaled(frame, 40, 10))
    assert small.min() == small.max() == 191  # 선의 양이 어디나 같음 — 겹선형이면 선이 사라지거나 새까맣게 됨


def test_the_original_frame_is_kept(qapp, gl, area):
    """아이템이 쥔 프레임(frame() — 자리표시자 크기·다시 올릴 원본)은 그대로."""
    frame = stripes()
    item = prepared(frame)
    item._draw_native(200, 100, box(0, 0, 40, 10))
    assert item.frame() is frame and (item.pixmap().width(), item.pixmap().height()) == (WIDTH, HEIGHT)


@pytest.mark.parametrize("corners", [box(3.3, 4.7, WIDTH, HEIGHT), box(3.3, 4.7, WIDTH * 2, HEIGHT * 2), box(0.2, 0.3, WIDTH * 0.99, HEIGHT * 0.99)])
def test_one_to_one_and_enlarged_views_are_drawn_as_before(qapp, gl, area, corners):
    frame = noise()
    item = prepared(frame)
    gl.calls.clear()
    item._draw_native(800, 400, corners)
    assert storage_sizes(gl) == [(WIDTH, HEIGHT)] and vertices(gl) == corners
    assert next(args for name, args in gl.calls if name == "glTexSubImage2D")[8] == frame.ctypes.data


def test_a_rotated_or_flipped_placement_is_drawn_as_before(qapp, gl, area):
    frame = noise()
    item = prepared(frame)
    rotated = [(50.0, 0.0), (50.0, 40.0), (40.0, 40.0), (40.0, 0.0)]  # 90도 — 이 앱에는 없는 변환
    item._draw_native(200, 100, rotated)
    assert storage_sizes(gl) == [(WIDTH, HEIGHT)] and vertices(gl) == rotated


def test_repainting_the_same_frame_at_the_same_size_uploads_nothing(qapp, gl, area):
    item = prepared(stripes())
    item._draw_native(200, 100, box(10.4, 20.6, 40, 10))
    gl.calls.clear()
    gl.uploads.clear()
    item._draw_native(200, 100, box(10.4, 20.6, 40, 10))
    item._draw_native(200, 100, box(77.7, 3.1, 40.2, 9.9))  # 자리만 바뀜(팬·창 옮김) — 같은 40×10
    assert gl.uploads == [] and storage_sizes(gl) == []
    assert vertices(gl) == box(10, 21, 40, 10) + box(78, 3, 40, 10)


def test_every_new_frame_is_scaled_and_uploaded_without_new_storage(qapp, gl, area):
    """재생 중에도 같은 필터 — 프레임마다 줄여 올림(저장소는 크기가 같으면 그대로)."""
    item = prepared(noise(0))
    item._draw_native(200, 100, box(0, 0, 40, 10))
    gl.calls.clear()
    gl.uploads.clear()
    frames = [noise(seed) for seed in (1, 2, 3)]
    for frame in frames:
        item.set_frame(frame)
        item._draw_native(200, 100, box(0, 0, 40, 10))
    assert storage_sizes(gl) == []
    assert len(gl.uploads) == 3 and all(np.array_equal(up, downscale_filter.area_scaled(frame, 40, 10)) for up, frame in zip(gl.uploads, frames))


def test_zooming_rescales_the_same_frame(qapp, gl, area):
    """멈춘 채 확대·축소(그릴 크기가 바뀜) → 새 크기로 다시 줄여 올림. 1:1을 넘으면 원본 그대로."""
    frame = noise()
    item = prepared(frame)
    item._draw_native(400, 200, box(0, 0, 40, 10))
    gl.uploads.clear()
    item._draw_native(400, 200, box(0, 0, 80, 20))
    assert storage_sizes(gl) == [(40, 10), (80, 20)]
    assert np.array_equal(gl.uploads[-1], downscale_filter.area_scaled(frame, 80, 20))
    item._draw_native(400, 200, box(0, 0, WIDTH * 2, HEIGHT * 2))
    assert storage_sizes(gl)[-1] == (WIDTH, HEIGHT) and np.array_equal(gl.uploads[-1], frame)


def test_switching_the_filter_applies_to_the_next_paint(qapp, gl):
    """메뉴로 바꾸면 이 창에 바로 — 그릴 때마다 설정을 봄. Linear로 돌아가면 원본을 다시 올리고 매핑된 모서리에."""
    frame = stripes()
    item = prepared(frame)
    corners = box(10.4, 20.6, 40, 10)
    item._draw_native(200, 100, corners)
    assert storage_sizes(gl) == [(WIDTH, HEIGHT)] and vertices(gl) == corners
    downscale_filter.set_preferred("area")
    gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert storage_sizes(gl) == [(40, 10)] and vertices(gl) == box(10, 21, 40, 10)
    assert np.array_equal(gl.uploads[-1], downscale_filter.area_scaled(frame, 40, 10))
    downscale_filter.set_preferred("linear")
    gl.calls.clear()
    item._draw_native(200, 100, corners)
    assert storage_sizes(gl) == [(WIDTH, HEIGHT)] and vertices(gl) == corners and np.array_equal(gl.uploads[-1], frame)


@pytest.mark.parametrize("mode", ["linear", "area"])
def test_a_frame_over_the_texture_limit_fails_the_same_way_whatever_the_filter(qapp, gl, mode):
    """GPU 텍스처 한도를 넘는 프레임은 줄이지 않고 크게 실패하는 것이 규칙 — 고품질이 줄인 그림만 한도와 견주면 창에 맞춘 동안은 그려지다가
    확대하는 순간 실패해 영상 영역이 비게 됨(리뷰에서 잡음). 원본 크기로 판정: 줄여 그리는 자리에서도 GL을 부르기 전에 같은 오류."""
    downscale_filter.set_preferred(mode)
    wide = np.zeros((8, gl.max_texture_size + 4, 3), np.uint8)
    item = prepared(wide)
    gl.calls.clear()
    with pytest.raises(gl_bindings.GLBindingError, match="텍스처 한도"):
        item._draw_native(2000, 100, box(0.0, 0.0, 1000.0, 2.0))
    assert [name for name, _ in gl.calls] == ["check_error"]  # 들어올 때의 오류 확인뿐 — 저장소·업로드·그리기 없음


# ---------------------------------------------------------------- paint를 거쳐 (좌표 규칙·가드)


@pytest.fixture
def contexts(monkeypatch):
    """gl_video_item.QOpenGLContext 대역 — currentContext()가 만들지 않은 진짜 QOpenGLContext(신호만 씀)를 돌려줌."""

    class Contexts:
        current = QOpenGLContext()

        @classmethod
        def currentContext(cls):
            return cls.current

    monkeypatch.setattr(gl_video_item, "QOpenGLContext", Contexts)
    return Contexts


def test_paint_snaps_in_physical_pixels(qapp, gl, area, contexts, shown):  # noqa: F811
    """paint → 물리 픽셀로 매핑한 자리에서 판단 — 논리 0.125배 × 화면 배율 2 = 물리 0.25배, 자리 (10.4, 20.6) → (10, 21)."""
    item = VideoFrameItem(stream=True)
    frame = stripes()
    item.set_frame(frame)
    paint_gl(item, FakeGLPainter(gl, QTransform(0.25, 0, 0, 0.25, 10.4, 20.6), width=100, height=50, dpr=2.0))
    assert item.failure_count == 0 and shown == []
    assert storage_sizes(gl) == [(40, 10)] and vertices(gl) == box(10, 21, 40, 10)
    assert np.array_equal(gl.uploads[-1], downscale_filter.area_scaled(frame, 40, 10))


def test_a_failure_while_scaling_goes_through_the_paint_guard(qapp, gl, area, contexts, shown, monkeypatch, capsys):  # noqa: F811
    """줄이다 실패해도 paint 밖으로 예외가 나가지 않음(PyQt5 qFatal) — 기존 가드: 기록 + 창 1회."""

    def broken(frame, width, height):
        raise MemoryError("줄이기 실패 (시험)")

    monkeypatch.setattr(downscale_filter, "area_scaled", broken)
    item = VideoFrameItem(stream=True)
    item.set_frame(stripes())
    painter = FakeGLPainter(gl, QTransform(0.25, 0, 0, 0.25, 0, 0), width=100, height=50, dpr=1.0)
    paint_gl(item, painter)
    paint_gl(item, painter)
    qapp.processEvents()
    assert item.failure_count == 1 and item.latched and len(shown) == 1
    assert "줄이기 실패 (시험)" in capsys.readouterr().err
    assert gl.calls[-1] == ("endNativePainting", ())
