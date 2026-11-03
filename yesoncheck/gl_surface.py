"""(스파이크 — spike/mac-native) IOSurface → GL 텍스처: CGL(OpenGL.framework)을 ctypes로 + 사각형 텍스처 상수 + 아이템이 더 쓰는 GL 함수.

CGLTexImageIOSurface2D(ctx, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, w, h, GL_BGRA, GL_UNSIGNED_INT_8_8_8_8_REV, surface, 0) — Stage 0 스파이크
(yc_iosurface_gl_spike.py)에서 Intel Mac으로 순서·색을 확인한 인자 그대로. 프레임워크는 처음 쓸 때 연다(이 모듈은 Windows·Intel CI에서도
import됨 — 모듈 검사).
"""

import ctypes

from yesoncheck.gl_bindings import GLBindingError

GL_TEXTURE_RECTANGLE_ARB = 0x84F5
GL_RGBA = 0x1908
GL_BGRA = 0x80E1
GL_UNSIGNED_INT_8_8_8_8_REV = 0x8367
GL_SCISSOR_TEST = 0x0C11
K_CGL_NO_ERROR = 0

OPENGL_FRAMEWORK = "/System/Library/Frameworks/OpenGL.framework/OpenGL"

_U, _I = ctypes.c_uint, ctypes.c_int
# gl_bindings.FUNCTIONS에 없는 것만 (같은 방식 — getProcAddress + ctypes)
EXTRA_FUNCTIONS = {
    "glScissor": (None, [_I, _I, _I, _I]),
    "glFinish": (None, []),
}

_CGL = []


def cgl():
    """(GetCurrentContext, TexImageIOSurface2D, ErrorString) — 처음 부를 때 OpenGL.framework를 연다."""
    if not _CGL:
        lib = ctypes.CDLL(OPENGL_FRAMEWORK)
        current = lib.CGLGetCurrentContext
        current.restype = ctypes.c_void_p
        current.argtypes = []
        tex = lib.CGLTexImageIOSurface2D
        tex.restype = ctypes.c_int  # CGLError
        tex.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        err = lib.CGLErrorString
        err.restype = ctypes.c_char_p
        err.argtypes = [ctypes.c_int]
        _CGL.append((current, tex, err))
    return _CGL[0]


def current_cgl_context():
    """지금 current인 CGLContextObj 포인터 — 없으면 GLBindingError."""
    ctx = cgl()[0]()
    if not ctx:
        raise GLBindingError("CGLGetCurrentContext()가 NULL입니다 (current GL 컨텍스트 없음)")
    return ctx


def bind_surface(ctx, handle):
    """지금 묶인 GL_TEXTURE_RECTANGLE_ARB 텍스처에 handle의 IOSurface를 묶는다 (CPU 복사 없음). CGLError ≠ 0이면 GLBindingError."""
    _current, tex, err_string = cgl()
    err = tex(ctx, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, handle.width, handle.height, GL_BGRA,
              GL_UNSIGNED_INT_8_8_8_8_REV, handle.surface, 0)
    if err != K_CGL_NO_ERROR:
        text = err_string(err)
        raise GLBindingError(f"CGLTexImageIOSurface2D 실패: CGLError {err} ({text.decode() if text else '?'}) — "
                             f"{handle!r} ctx 0x{ctx:x}")


class ExtraGL:
    """EXTRA_FUNCTIONS를 context에서 묶은 것 (이름마다 같은 이름의 속성)."""

    def __init__(self, context):
        for name, (restype, argtypes) in EXTRA_FUNCTIONS.items():
            proc = context.getProcAddress(name.encode())
            address = int(proc) if proc is not None else 0
            if address == 0:
                raise GLBindingError(f"GL 함수 {name}을(를) 찾지 못했습니다")
            setattr(self, name, ctypes.CFUNCTYPE(restype, *argtypes)(address))
