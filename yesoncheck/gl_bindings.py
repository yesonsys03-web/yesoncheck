"""GL 함수 묶기: QOpenGLContext.getProcAddress로 필요한 OpenGL 함수의 주소를 얻어 ctypes로 감싼다.

왜 ctypes + getProcAddress인가: 비디오 아이템이 paint() 안에서 프레임을 GL 텍스처로 직접 올리려면 glTexSubImage2D 같은 데스크톱
GL 함수 20개가 필요하다. PyOpenGL을 들이면 의존성이 하나 늘고 PyInstaller 번들·플랫폼별 로더 문제가 따라오므로, Qt가 이미 열어 둔
컨텍스트에게 이름으로 주소를 물어(getProcAddress) ctypes 함수 객체로 감싼다 — 의존성 0, 컨텍스트가 실제로 제공하는 함수만 쓴다.
시그니처는 스파이크(docs/superpowers/records/2026-11-02-gl-stream-design/yc_gl_stream_spike.py)에서 Mac(GL 2.1)로 검증한 것 그대로다
(glOrtho는 c_double 6개, 포인터 인자는 c_void_p, glGetError는 c_uint 반환, glGetIntegerv는 POINTER(c_int)).

ES 컨텍스트(Windows의 ANGLE 등)는 거부한다: 고정 기능 파이프라인(glBegin·glOrtho·glMatrixMode…)이 없어서 이 함수들이 아예 없거나
동작하지 않는다. 몰래 다른 경로로 돌리지 않고 GLBindingError로 알려, 부른 쪽이 환경변수(YESONCHECK_VIDEO_ITEM=pixmap 등)로 기존 경로를
고르게 한다. 함수를 못 찾을 때도 마찬가지로 이름을 넣어 올린다 — 삼키거나 기본값으로 대신하지 않는다.

이 모듈은 함수와 상수를 풀고 오류를 확인하는 일만 한다. 그리기·좌표 규칙(원점·뒤집기·종횡비)은 아이템 쪽에 있다.
GL 호출은 max_texture_size를 읽는 glGetIntegerv 한 번뿐이며, 그때 컨텍스트가 current여야 하는 것은 부른 쪽의 책임이다.
"""

import ctypes

# ---------------------------------------------------------------- 상수 (OpenGL 헤더 값 그대로)
GL_TEXTURE_2D = 0x0DE1
GL_RGB = 0x1907
GL_RGB8 = 0x8051
GL_UNSIGNED_BYTE = 0x1401
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_NEAREST = 0x2600
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_CLAMP_TO_EDGE = 0x812F
GL_UNPACK_ALIGNMENT = 0x0CF5
GL_UNPACK_ROW_LENGTH = 0x0CF2
GL_PROJECTION = 0x1701
GL_MODELVIEW = 0x1700
GL_QUADS = 0x0007
GL_BLEND = 0x0BE2
GL_MAX_TEXTURE_SIZE = 0x0D33
GL_NO_ERROR = 0

_UINT, _INT, _FLOAT, _DOUBLE = ctypes.c_uint, ctypes.c_int, ctypes.c_float, ctypes.c_double
_PTR = ctypes.c_void_p

# 함수 이름 → (반환형, [인자형…]). 반환형 None은 void.
FUNCTIONS = {
    "glGenTextures": (None, [_INT, ctypes.POINTER(_UINT)]),
    "glDeleteTextures": (None, [_INT, ctypes.POINTER(_UINT)]),
    "glBindTexture": (None, [_UINT, _UINT]),
    "glTexParameteri": (None, [_UINT, _UINT, _INT]),
    "glTexImage2D": (None, [_UINT, _INT, _INT, _INT, _INT, _INT, _UINT, _UINT, _PTR]),
    "glTexSubImage2D": (None, [_UINT, _INT, _INT, _INT, _INT, _INT, _UINT, _UINT, _PTR]),
    "glPixelStorei": (None, [_UINT, _INT]),
    "glEnable": (None, [_UINT]),
    "glDisable": (None, [_UINT]),
    "glViewport": (None, [_INT, _INT, _INT, _INT]),
    "glMatrixMode": (None, [_UINT]),
    "glLoadIdentity": (None, []),
    "glOrtho": (None, [_DOUBLE] * 6),
    "glBegin": (None, [_UINT]),
    "glEnd": (None, []),
    "glTexCoord2f": (None, [_FLOAT, _FLOAT]),
    "glVertex2f": (None, [_FLOAT, _FLOAT]),
    "glColor4f": (None, [_FLOAT] * 4),
    "glGetError": (_UINT, []),
    "glGetIntegerv": (None, [_UINT, ctypes.POINTER(_INT)]),
}


class GLBindingError(RuntimeError):
    """GL 함수를 묶지 못했거나(ES 컨텍스트·함수 주소 0) GL이 오류를 돌려줬을 때."""


class GLFunctions:
    """묶은 GL 함수 모음: FUNCTIONS의 이름마다 같은 이름의 속성(ctypes 함수 객체)과 max_texture_size를 가진다."""

    def __init__(self, functions, max_texture_size):
        for name, function in functions.items():
            setattr(self, name, function)
        self.max_texture_size = max_texture_size

    def check_error(self, where):
        """glGetError가 오류를 돌려주면 where(어디서 확인했는지)를 넣어 GLBindingError로 올린다."""
        err = self.glGetError()
        if err != GL_NO_ERROR:
            raise GLBindingError(f"GL 오류 0x{err:04X} @ {where}")


def _read_max_texture_size(fns):
    """GL_MAX_TEXTURE_SIZE를 읽는다 — bind()가 거는 유일한 GL 호출이라 컨텍스트가 current여야 한다 (시험에서 바꿔치기).

    컨텍스트가 current가 아니면 GL은 값을 채우지 않아 0이 남는다 — 그대로 돌려주면 뒤에서 "프레임이 너무 크다"로 잘못 읽히므로 여기서 올린다.
    """
    value = ctypes.c_int(0)
    fns.glGetIntegerv(GL_MAX_TEXTURE_SIZE, ctypes.byref(value))
    if value.value <= 0:
        raise GLBindingError(
            f"GL 텍스처 크기 한도를 읽지 못했습니다 (GL_MAX_TEXTURE_SIZE={value.value}) — "
            "컨텍스트가 current가 아니거나 GL이 값을 돌려주지 않았습니다"
        )
    return value.value


def bind(context):
    """QOpenGLContext에서 FUNCTIONS의 함수를 모두 찾아 GLFunctions로 돌려준다. 하나라도 못 찾으면 GLBindingError.

    결과는 따로 캐시하지 않는다 — 컨텍스트가 바뀌면 부른 쪽(아이템)이 다시 묶는다.
    """
    if context.isOpenGLES():
        raise GLBindingError(
            "OpenGL ES(ANGLE) 컨텍스트 — 고정 기능 GL이 없어 GL 텍스처 스트리밍을 쓸 수 없습니다; "
            "YESONCHECK_VIDEO_ITEM=pixmap 또는 YESONCHECK_VIEWPORT=raster"
        )
    functions = {}
    for name, (restype, argtypes) in FUNCTIONS.items():
        address = int(context.getProcAddress(name.encode()))
        if address == 0:
            raise GLBindingError(f"GL 함수 {name}을(를) 찾지 못했습니다")
        functions[name] = ctypes.CFUNCTYPE(restype, *argtypes)(address)
    fns = GLFunctions(functions, 0)  # 최대 크기는 glGetIntegerv가 묶인 뒤에야 읽을 수 있어 바로 아래에서 채운다
    fns.max_texture_size = _read_max_texture_size(fns)
    return fns
