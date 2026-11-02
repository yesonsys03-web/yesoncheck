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
