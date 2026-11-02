import ctypes
import pytest
from yesoncheck import gl_bindings

class StubContext:
    def __init__(self, es=False, missing=()):
        self.es, self.missing, self.asked = es, set(missing), []
    def isOpenGLES(self):
        return self.es
    def getProcAddress(self, name):
        self.asked.append(name)
        return 0 if name.decode() in self.missing else 0x1000  # 가짜 주소 — 호출하지 않음

def test_bind_resolves_every_function_by_name(monkeypatch):
    monkeypatch.setattr(gl_bindings, "_read_max_texture_size", lambda fns: 16384)
    ctx = StubContext()
    fns = gl_bindings.bind(ctx)
    assert sorted(n.decode() for n in ctx.asked) == sorted(gl_bindings.FUNCTIONS)
    assert fns.max_texture_size == 16384
    assert isinstance(fns.glTexSubImage2D, ctypes._CFuncPtr)

def test_bind_names_the_missing_function():
    with pytest.raises(gl_bindings.GLBindingError) as error:
        gl_bindings.bind(StubContext(missing=["glTexSubImage2D"]))
    assert "glTexSubImage2D" in str(error.value)

def test_bind_rejects_es_context():
    with pytest.raises(gl_bindings.GLBindingError) as error:
        gl_bindings.bind(StubContext(es=True))
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

def test_bind_reads_texture_limit_through_glgetintegerv():
    def fill(pname, out):
        assert pname == gl_bindings.GL_MAX_TEXTURE_SIZE
        out[0] = 8192
    assert gl_bindings.bind(GetIntegervContext(fill)).max_texture_size == 8192

def test_bind_rejects_zero_texture_limit():
    def leave_zero(pname, out):
        pass  # 컨텍스트가 current가 아니면 GL은 값을 채우지 않는다
    with pytest.raises(gl_bindings.GLBindingError, match=r"GL_MAX_TEXTURE_SIZE=0.*current"):
        gl_bindings.bind(GetIntegervContext(leave_zero))
