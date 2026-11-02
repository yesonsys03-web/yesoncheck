import ctypes
import pytest
from PyQt5.QtGui import QSurfaceFormat
from yesoncheck import gl_bindings

class StubFormat:
    def __init__(self, profile):
        self._profile = profile
    def profile(self):
        return self._profile

class StubContext:
    def __init__(self, es=False, missing=(), missing_value=0, profile=QSurfaceFormat.NoProfile):
        self.es, self.missing, self.missing_value, self.profile = es, set(missing), missing_value, profile
        self.asked = []
    def isOpenGLES(self):
        return self.es
    def format(self):
        return StubFormat(self.profile)
    def getProcAddress(self, name):
        self.asked.append(name)
        # 없는 함수: 진짜 PyQt5는 None을 돌려준다 (0도 "없음"으로 다룸); 있는 함수는 가짜 주소 — 호출하지 않음
        return self.missing_value if name.decode() in self.missing else 0x1000

class GetIntegervContext(StubContext):
    """glGetIntegerv만 진짜 ctypes 콜백 주소를 돌려주는 스텁 — bind()의 실제 읽기 경로를 태운다 (다른 함수는 호출되지 않음)."""
    def __init__(self, callback):
        super().__init__()
        self.callback = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))(callback)  # 시험 동안 살아 있게 들고 있음
    def getProcAddress(self, name):
        address = super().getProcAddress(name)
        if name == b"glGetIntegerv":
            return ctypes.cast(self.callback, ctypes.c_void_p).value
        return address

def test_bind_resolves_every_function_by_name(monkeypatch):
    monkeypatch.setattr(gl_bindings, "_read_max_texture_size", lambda fns: 16384)
    ctx = StubContext()
    fns = gl_bindings.bind(ctx)
    assert sorted(n.decode() for n in ctx.asked) == sorted(gl_bindings.FUNCTIONS)
    assert fns.max_texture_size == 16384
    assert isinstance(fns.glTexSubImage2D, ctypes._CFuncPtr)

@pytest.mark.parametrize("missing_value", [None, 0])
def test_bind_names_the_missing_function(missing_value):
    with pytest.raises(gl_bindings.GLBindingError) as error:
        gl_bindings.bind(StubContext(missing=["glTexSubImage2D"], missing_value=missing_value))
    assert "glTexSubImage2D" in str(error.value)

def test_bind_rejects_es_context():
    with pytest.raises(gl_bindings.GLBindingError) as error:
        gl_bindings.bind(StubContext(es=True))
    assert "YESONCHECK_VIDEO_ITEM=pixmap" in str(error.value)

def test_bind_rejects_core_profile_context():
    with pytest.raises(gl_bindings.GLBindingError, match="core profile") as error:
        gl_bindings.bind(StubContext(profile=QSurfaceFormat.CoreProfile))
    assert "YESONCHECK_VIDEO_ITEM=pixmap" in str(error.value)

def test_check_error_raises_with_place(monkeypatch):
    monkeypatch.setattr(gl_bindings, "_read_max_texture_size", lambda fns: 1)
    fns = gl_bindings.bind(StubContext())
    monkeypatch.setattr(fns, "glGetError", lambda: 0x0502)
    with pytest.raises(gl_bindings.GLBindingError, match="0x0502 @ upload"):
        fns.check_error("upload")
    monkeypatch.setattr(fns, "glGetError", lambda: 0)
    fns.check_error("upload")  # 오류 없음 — 예외 없음

def test_glortho_takes_doubles():
    assert gl_bindings.FUNCTIONS["glOrtho"][1] == [ctypes.c_double] * 6

def test_bind_reads_texture_limit_through_glgetintegerv():
    asked = []
    def fill(pname, out):  # ctypes 콜백 안의 예외는 삼켜지므로 단언은 밖에서 — 여기서는 기록만
        asked.append(pname)
        out[0] = 8192
    assert gl_bindings.bind(GetIntegervContext(fill)).max_texture_size == 8192
    assert asked == [gl_bindings.GL_MAX_TEXTURE_SIZE]

def test_bind_rejects_zero_texture_limit():
    def leave_zero(pname, out):
        pass  # 컨텍스트가 current가 아니면 GL은 값을 채우지 않는다
    with pytest.raises(gl_bindings.GLBindingError, match=r"GL_MAX_TEXTURE_SIZE=0.*current"):
        gl_bindings.bind(GetIntegervContext(leave_zero))
