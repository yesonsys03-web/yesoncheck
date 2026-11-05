"""하드웨어 디코드 여부 (mac_native_source._hardware_decode_supported — 열기 기록 줄의 hw=yes|no|?, Ruling 15): PyObjC VideoToolbox 래퍼가
있으면 그것, 없으면(빌드에는 넣지 않음) ctypes로 VideoToolbox.framework의 VTIsHardwareDecodeSupported(CMVideoCodecType → Boolean)를
직접 부른다. 프레임워크·함수를 열지 못하면 None(hw=?)이고 그 사유를 기록에 한 번만 찍는다 — 조용히 '?'가 되지 않게.

PyObjC 없이 어느 플랫폼에서나 돈다: ctypes.CDLL을 가짜로 바꿔치기(mac_native_source가 읽는 이름 — ctypes 모듈의 CDLL)해 FourCC → bool
배선(인자형·반환형·인자 값·한 번만 엶)을 본다. 진짜 프레임워크 호출은 macOS에서만(Intel에도 VideoToolbox.framework가 있음 — 이 Mac의
ap4h는 하드웨어 디코드 아님)."""

import ctypes
import sys
from types import SimpleNamespace

import pytest

from yesoncheck import mac_native_source
from yesoncheck.mac_native_source import NATIVE_LOG_PREFIX, VIDEOTOOLBOX_FRAMEWORK

NO_WRAPPER = SimpleNamespace(VideoToolbox=None)  # _pyobjc()의 묶음 중 이 함수가 보는 것 — 래퍼 없음 (빌드 환경과 같음)


def fourcc(text):
    """'ap4h' → CMVideoCodecType 정수 (CMFormatDescriptionGetMediaSubType이 주는 값과 같은 큰 끝 순서)."""
    return int.from_bytes(text.encode("ascii"), "big")


@pytest.fixture(autouse=True)
def fresh_probe(monkeypatch):
    """모듈에 묶어 둔 ctypes 함수·실패 사유를 시험마다 비움 (진짜 프레임워크를 연 결과가 다른 시험에 새지 않게 — 끝나면 되돌림)."""
    monkeypatch.setattr(mac_native_source, "_HW_PROBE", None)
    monkeypatch.setattr(mac_native_source, "_HW_PROBE_FAILURE", None)


class FakeVTFunction:
    """ctypes 함수 자리: restype·argtypes를 받아 두고, 부른 인자를 기록하고, supported에 든 코덱이면 참."""

    def __init__(self, supported):
        self.supported = supported
        self.restype = None
        self.argtypes = None
        self.calls = []

    def __call__(self, codec_type):
        self.calls.append(codec_type)
        return codec_type in self.supported


@pytest.fixture
def fake_cdll(monkeypatch):
    """ctypes.CDLL 가짜: 연 경로를 opened에, 함수는 rig.function (supported = {'apch'}). rig.error를 정하면 열 때 그 예외,
    rig.symbol=False면 함수가 없는 라이브러리(AttributeError)."""
    rig = SimpleNamespace(opened=[], error=None, symbol=True, function=FakeVTFunction({fourcc("apch")}))

    def cdll(path):
        rig.opened.append(path)
        if rig.error is not None:
            raise rig.error
        library = SimpleNamespace()
        if rig.symbol:
            library.VTIsHardwareDecodeSupported = rig.function
        return library

    monkeypatch.setattr(ctypes, "CDLL", cdll)
    return rig


def test_ctypes_probe_maps_fourcc_to_bool(fake_cdll):
    """래퍼가 없으면 VideoToolbox.framework를 ctypes로 한 번 열고 VTIsHardwareDecodeSupported(c_uint32) → c_bool. 코덱 FourCC 정수를 그대로
    넘기고 답을 bool로 (ap4h 아니오, apch 예). 두 번째 부름은 열어 둔 함수를 다시 씀."""
    assert mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc("ap4h")) is False
    assert mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc("apch")) is True
    assert fake_cdll.opened == [VIDEOTOOLBOX_FRAMEWORK]
    assert VIDEOTOOLBOX_FRAMEWORK == "/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox"
    function = fake_cdll.function
    assert function.restype is ctypes.c_bool
    assert function.argtypes == [ctypes.c_uint32]
    assert function.calls == [fourcc("ap4h"), fourcc("apch")] == [0x61703468, 0x61706368]


@pytest.mark.parametrize("case", ["framework missing", "symbol missing"])
def test_unloadable_framework_is_unknown_and_says_why_once(fake_cdll, capsys, case):
    """프레임워크를 열지 못하거나(OSError) 함수가 없으면(AttributeError) None(기록 hw=?) — 그 사유를 기록에 한 줄로 한 번만 찍고, 다시 열어
    보지 않음 (열 때마다 같은 줄이 쌓이지 않게). 예외는 밖으로 내보내지 않음 (캡처는 열림 — 이 값은 기록 줄 하나뿐)."""
    if case == "framework missing":
        fake_cdll.error = OSError(f"dlopen({VIDEOTOOLBOX_FRAMEWORK}, 0x0006): image not found")
    else:
        fake_cdll.symbol = False
    assert mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc("ap4h")) is None
    assert mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc("apch")) is None
    assert fake_cdll.opened == [VIDEOTOOLBOX_FRAMEWORK]
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1, lines
    [line] = lines
    assert line.startswith(f"{NATIVE_LOG_PREFIX} 하드웨어 디코드 여부를 알 수 없음(hw=?)")
    assert VIDEOTOOLBOX_FRAMEWORK in line
    assert ("OSError: dlopen" in line) if case == "framework missing" else ("AttributeError" in line)
    assert fake_cdll.function.calls == []


def test_unexpected_error_is_not_swallowed(fake_cdll):
    """열지 못함(OSError)·함수 없음(AttributeError) 밖의 예외(코드 버그 등)는 '?'로 덮지 않고 그대로 올라옴."""
    fake_cdll.error = RuntimeError("예상 못 한 오류")
    with pytest.raises(RuntimeError, match="예상 못 한 오류"):
        mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc("ap4h"))


def test_pyobjc_wrapper_is_preferred_when_present(fake_cdll):
    """PyObjC VideoToolbox 래퍼가 있으면(pyobjc-framework-VideoToolbox를 설치한 개발 환경) 그것을 부르고 ctypes로 열지 않음."""
    asked = []
    wrapper = SimpleNamespace(VideoToolbox=SimpleNamespace(VTIsHardwareDecodeSupported=lambda codec: asked.append(codec) or 1))
    assert mac_native_source._hardware_decode_supported(wrapper, fourcc("ap4h")) is True
    assert asked == [fourcc("ap4h")]
    assert fake_cdll.opened == []


@pytest.mark.parametrize("supported, label", [(True, "yes"), (False, "no"), (None, "?")])
def test_open_log_line_shows_the_hw_answer(monkeypatch, capsys, supported, label):
    """열기 기록 줄의 hw= 는 캡처의 hardware_decode_supported 그대로 (yes·no·? — 알 수 없음)."""
    probe = SimpleNamespace(codec="prores", width=3840, height=2160, avg=24, nb_frames=334)

    def capture(path, given):
        assert given is probe
        return SimpleNamespace(hardware_decode_supported=supported)

    monkeypatch.setattr(mac_native_source, "NativeVTCapture", capture)
    mac_native_source.open_native_capture("/clips/FL_106.mov", probe)
    assert capsys.readouterr().out == (f"{NATIVE_LOG_PREFIX} FL_106.mov (prores 3840×2160 24fps, 프레임 334, 32BGRA, hw={label})\n")


@pytest.mark.skipif(sys.platform != "darwin", reason="VideoToolbox.framework는 macOS에만 있음 (Windows·Linux는 네이티브 경로가 없음)")
def test_real_framework_answers_yes_or_no(capsys):
    """이 Mac의 진짜 VideoToolbox.framework: 래퍼 없이도 ProRes 4444·422 HQ 둘 다 '알 수 없음'이 아니라 예/아니오 (Intel에도 프레임워크가 있음 —
    이 Intel Mac의 ap4h는 아니오). 사유 줄은 찍지 않음."""
    answers = {codec: mac_native_source._hardware_decode_supported(NO_WRAPPER, fourcc(codec)) for codec in ("ap4h", "apch")}
    assert all(isinstance(answer, bool) for answer in answers.values()), answers
    assert capsys.readouterr().out == ""
