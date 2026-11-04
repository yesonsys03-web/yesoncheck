"""IOSurface → GL 텍스처: OpenGL.framework의 CGL 함수 둘(CGLGetCurrentContext·CGLTexImageIOSurface2D)을 ctypes로 묶고 사각형 텍스처 상수를 둔다.

왜: 네이티브 재생 경로(Apple Silicon, mac_native_source)의 프레임은 VideoToolbox가 디코드한 IOSurface 안에 있다. 이것을 CPU로 읽어
glTexSubImage2D로 올리지 않고 CGLTexImageIOSurface2D로 GL_TEXTURE_RECTANGLE_ARB 텍스처에 그대로 묶으면 CPU 복사가 0이다
(VideoFrameItem.set_sides — gl_video_item). 인자는 Stage 0 스파이크 A3(내부 저장소 docs/superpowers/records/2026-11-03-mac-native-playback/
yc_iosurface_gl_spike.py)에서 Intel Mac으로 순서·색을 확인한 것 그대로다:

    CGLTexImageIOSurface2D(ctx, GL_TEXTURE_RECTANGLE_ARB, GL_RGBA, w, h, GL_BGRA, GL_UNSIGNED_INT_8_8_8_8_REV, surface, 0)

사각형 텍스처의 좌표는 0..1이 아니라 픽셀 단위다 — 사각형은 (0,0)…(w,h)로 그린다.

왜 getProcAddress가 아니라 ctypes.CDLL인가: CGL 함수는 GL 확장 함수가 아니라 프레임워크의 C API라 QOpenGLContext가 주소를 주지 않는다.
CGL 함수는 컨텍스트마다가 아니라 프로세스에 하나이고, 어느 컨텍스트에 묶을지는 부른 쪽이 CGLGetCurrentContext로 정한다. glScissor 같은
보통 GL 함수는 gl_bindings.FUNCTIONS(getProcAddress)에 있다.

이 모듈은 어느 플랫폼에서나 import된다(Windows·Intel CI의 모듈 검사) — 프레임워크는 bind_cgl()을 부를 때 연다. 못 열거나 함수가 없으면
GLBindingError(이유와 경로) — 조용히 None을 돌려주거나 다른 경로로 돌지 않는다. CGLTexImageIOSurface2D가 오류(CGLError ≠ 0)를 돌려주면
오류 코드·설명·IOSurface·크기를 담아 GLBindingError — 그리는 쪽(paint 가드)이 첫 실패를 크게 알린다.
"""

import ctypes

from yesoncheck.gl_bindings import GLBindingError

# ---------------------------------------------------------------- 상수 (OpenGL 헤더 값 그대로)
GL_TEXTURE_RECTANGLE_ARB = 0x84F5
GL_RGBA = 0x1908
GL_BGRA = 0x80E1
GL_UNSIGNED_INT_8_8_8_8_REV = 0x8367
GL_SCISSOR_TEST = 0x0C11
K_CGL_NO_ERROR = 0

OPENGL_FRAMEWORK = "/System/Library/Frameworks/OpenGL.framework/OpenGL"

_PTR, _UINT, _INT = ctypes.c_void_p, ctypes.c_uint, ctypes.c_int

# 함수 이름 → (반환형, [인자형…]) — 스파이크 A3와 같은 시그니처. CGLErrorString은 오류 글(설명)에만 쓴다.
CGL_FUNCTIONS = {
    "CGLGetCurrentContext": (_PTR, []),
    "CGLTexImageIOSurface2D": (_INT, [_PTR, _UINT, _UINT, _INT, _INT, _UINT, _UINT, _PTR, _UINT]),  # CGLError (0 = kCGLNoError)
    "CGLErrorString": (ctypes.c_char_p, [_INT]),
}


class CGLFunctions:
    """묶은 CGL 함수 — functions: CGL_FUNCTIONS의 이름 → 부를 수 있는 것(ctypes 함수, 시험에서는 대역)."""

    def __init__(self, functions):
        self._functions = dict(functions)

    def CGLGetCurrentContext(self) -> int:
        """지금 current인 CGLContextObj 포인터 — 없으면 0 (ctypes c_void_p 반환은 NULL을 None으로 줌)."""
        return self._functions["CGLGetCurrentContext"]() or 0

    def CGLTexImageIOSurface2D(self, ctx, target, internal_format, width, height, format_, type_, surface, plane) -> int:
        """지금 바인드된 target 텍스처에 IOSurface(surface 포인터)의 plane을 묶는다(CPU 복사 없음). 0(kCGLNoError)을 돌려주고, 그 밖의
        CGLError면 오류 코드·설명·IOSurface·크기·컨텍스트를 담아 GLBindingError."""
        error = self._functions["CGLTexImageIOSurface2D"](ctx, target, internal_format, width, height, format_, type_, surface, plane)
        if error != K_CGL_NO_ERROR:
            text = self._functions["CGLErrorString"](error)
            description = text.decode("utf-8", "replace") if text else "설명 없음"
            raise GLBindingError(
                f"CGLTexImageIOSurface2D 실패: CGLError {error} ({description}) — IOSurface 0x{surface:x} {width}×{height}, "
                f"plane {plane}, CGL 컨텍스트 0x{ctx:x}"
            )
        return error


def bind_cgl() -> CGLFunctions:
    """OpenGL.framework를 열어 CGL_FUNCTIONS를 찾고 시그니처를 세운 CGLFunctions. 못 열면(macOS가 아님 등)·함수가 없으면 GLBindingError.

    결과는 캐시하지 않는다 — 부른 쪽(아이템)이 쥔다. 함수 객체는 이 호출이 연 라이브러리 객체의 것이라 시그니처를 세워도 다른 곳에 번지지 않는다."""
    try:
        library = ctypes.CDLL(OPENGL_FRAMEWORK)
    except OSError as exc:
        raise GLBindingError(
            f"OpenGL.framework를 열지 못했습니다 ({OPENGL_FRAMEWORK}) — IOSurface 텍스처는 macOS에서만 됩니다: {exc}"
        ) from exc
    functions = {}
    for name, (restype, argtypes) in CGL_FUNCTIONS.items():
        try:
            function = getattr(library, name)
        except AttributeError as exc:
            raise GLBindingError(f"CGL 함수 {name}을(를) 찾지 못했습니다 ({OPENGL_FRAMEWORK})") from exc
        function.restype = restype
        function.argtypes = argtypes
        functions[name] = function
    return CGLFunctions(functions)
