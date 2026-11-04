"""gl_surface — OpenGL.framework의 CGL 두 함수(CGLGetCurrentContext·CGLTexImageIOSurface2D)를 ctypes로 묶는 모듈.

실제 IOSurface 묶기는 화면이 있는 Mac 몫(yc_app_pixel_check)이라 여기서는 상수·시그니처·오류 경로와 진짜 프레임워크를 여는 것까지만 본다.
아이템 쪽(RECT 텍스처·와이프 scissor)은 tests/test_gl_video_item.py의 'IOSurface 그리기' 묶음."""

import ctypes
import sys

import pytest

from yesoncheck import gl_surface
from yesoncheck.gl_bindings import GLBindingError


def test_constants_are_the_opengl_header_values():
    """값이 하나라도 틀리면 CGLTexImageIOSurface2D가 오류를 내거나 색이 뒤바뀜 (Stage 0 스파이크 A3에서 확인한 인자 그대로)."""
    assert (gl_surface.GL_TEXTURE_RECTANGLE_ARB, gl_surface.GL_BGRA, gl_surface.GL_UNSIGNED_INT_8_8_8_8_REV,
            gl_surface.GL_RGBA, gl_surface.GL_SCISSOR_TEST) == (0x84F5, 0x80E1, 0x8367, 0x1908, 0x0C11)


def test_cgl_signatures_match_the_spike():
    """argtypes를 바꾸면(예: 포인터를 c_int로) arm64에서 IOSurface 포인터 위쪽 32비트가 잘림 — 스파이크가 검증한 시그니처 그대로."""
    p, u, i = ctypes.c_void_p, ctypes.c_uint, ctypes.c_int
    assert gl_surface.CGL_FUNCTIONS["CGLGetCurrentContext"] == (p, [])
    assert gl_surface.CGL_FUNCTIONS["CGLTexImageIOSurface2D"] == (i, [p, u, u, i, i, u, u, p, u])


class Recorder:
    """CGL 함수 대역 — 받은 인자를 남기고 정한 값을 돌려줌."""
    def __init__(self, result):
        self.result, self.calls = result, []
    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def make_cgl(context=0xC61, error=0):
    tex = Recorder(error)
    functions = {"CGLGetCurrentContext": Recorder(context), "CGLTexImageIOSurface2D": tex,
                 "CGLErrorString": Recorder(b"invalid share context")}
    return gl_surface.CGLFunctions(functions), tex


def test_tex_image_passes_arguments_through_and_returns_no_error():
    """CGLFunctions가 인자를 바꾸거나 빠뜨리면 실패 — 래퍼는 그대로 넘기고 kCGLNoError(0)를 돌려줌."""
    cgl, tex = make_cgl()
    assert cgl.CGLTexImageIOSurface2D(0xC61, 0x84F5, 0x1908, 4, 2, 0x80E1, 0x8367, 0x5000, 0) == 0
    assert tex.calls == [(0xC61, 0x84F5, 0x1908, 4, 2, 0x80E1, 0x8367, 0x5000, 0)]


def test_tex_image_error_raises_with_code_surface_and_size():
    """CGLError ≠ 0을 돌려주기만 하고 올리지 않으면(조용한 실패) 빈 텍스처가 그려짐 — 오류 코드·설명·IOSurface·크기를 담아 GLBindingError."""
    cgl, _ = make_cgl(error=10008)
    with pytest.raises(GLBindingError) as error:
        cgl.CGLTexImageIOSurface2D(0xC61, 0x84F5, 0x1908, 3840, 2160, 0x80E1, 0x8367, 0x5000, 0)
    text = str(error.value)
    assert "CGLError 10008" in text and "invalid share context" in text
    assert "0x5000" in text and "3840×2160" in text


@pytest.mark.parametrize("raw, expected", [(None, 0), (0xC61, 0xC61)])
def test_current_context_is_an_int(raw, expected):
    """ctypes c_void_p 반환은 NULL을 None으로 줌 — 그대로 넘기면 부른 쪽의 0 검사·서식(0x…)이 깨짐: 늘 int (없으면 0)."""
    cgl, _ = make_cgl(context=raw)
    assert cgl.CGLGetCurrentContext() == expected


def test_bind_cgl_missing_framework_raises(monkeypatch):
    """프레임워크를 못 열 때(Windows·Linux) OSError가 그대로 새거나 None을 돌려주면 paint 가드가 원인을 못 보여 줌 — GLBindingError로 경로와 함께."""
    def no_framework(path):
        raise OSError(f"dlopen({path}): image not found")
    monkeypatch.setattr(gl_surface.ctypes, "CDLL", no_framework)
    with pytest.raises(GLBindingError, match="OpenGL.framework") as error:
        gl_surface.bind_cgl()
    assert "image not found" in str(error.value)


def test_bind_cgl_missing_symbol_names_it(monkeypatch):
    """함수 하나가 없을 때 AttributeError가 새면 어느 함수인지 기록에 안 남음 — 이름을 넣은 GLBindingError."""
    class Library:
        def __init__(self, path):
            self.CGLGetCurrentContext = Recorder(0)
            self.CGLErrorString = Recorder(b"")
    monkeypatch.setattr(gl_surface.ctypes, "CDLL", Library)
    with pytest.raises(GLBindingError, match="CGLTexImageIOSurface2D"):
        gl_surface.bind_cgl()


@pytest.mark.skipif(sys.platform != "darwin", reason="OpenGL.framework는 macOS에만 있음")
def test_bind_cgl_opens_the_real_framework():
    """진짜 OpenGL.framework에서 세 함수를 찾고 시그니처를 세움 — 이름 오타·restype 누락이면 여기서 실패 (current 컨텍스트가 없으면 0)."""
    cgl = gl_surface.bind_cgl()
    assert isinstance(cgl, gl_surface.CGLFunctions)
    assert isinstance(cgl.CGLGetCurrentContext(), int)
