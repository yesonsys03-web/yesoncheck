"""네이티브 재생 게이트 (yesoncheck/mac_native_gate.py): 토글·플랫폼(darwin 전체) 판정·파일 게이트(HDR이 아닌 ProRes는 모두 통과).

판정은 순수 파이썬이라 플랫폼은 SimpleNamespace 대역으로 바꿔 어느 OS에서나 돌린다 (mock은 platform·sys 모양뿐). 파일 게이트는
실제 ffprobe로 클립 공장(tests/prores_clips.py)의 4K 클립을 읽은 probe를 쓰고(모듈 범위 — 4K 인코드는 한 번씩), 조건 하나씩의
경계는 좋은 probe의 필드 하나만 바꾼 사본(dataclasses.replace)으로 본다.
"""

import dataclasses
import os
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.prores_clips import make_numbered_clip
from yesoncheck import mac_native_gate, movie_pipe_source
from yesoncheck.mac_native_gate import (
    HDR_PRIMARIES, HDR_TRANSFERS, NATIVE_CODEC, NATIVE_MODE_ENV, NATIVE_MODES, is_apple_silicon, native_eligible,
    native_ineligible_reason, native_mode, native_wanted,
)
from yesoncheck.movie_pipe_source import probe_movie

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = "YESONCHECK_MAC_NATIVE"
FRAMES = 3  # 4K 인코드가 느리므로 짧게 — 게이트 ④(프레임 수·길이·속도 삼자 일치)는 3장으로도 성립


def mac(machine):
    return SimpleNamespace(machine=lambda: machine), SimpleNamespace(platform="darwin")


# ---------------------------------------------------------------- 토글 값

def test_constants_match_the_documented_toggle():
    assert (NATIVE_MODE_ENV, NATIVE_MODES) == (ENV, ("auto", "on", "off"))
    assert NATIVE_CODEC == "prores"
    assert HDR_TRANSFERS == ("smpte2084", "arib-std-b67")
    assert HDR_PRIMARIES == "bt2020"


REMOVED_CONSTANTS = ("NATIVE_MIN_WIDTH", "NATIVE_MIN_HEIGHT", "NATIVE_PIX_FMTS", "COLOR_SPACES_OK", "COLOR_RANGES_OK", "UNTAGGED")


@pytest.mark.parametrize("name", REMOVED_CONSTANTS)
def test_removed_constants_are_gone(name):
    """4K·4:4:4·색 태그 조건과 함께 그 상수도 지움 — 남아 있으면 쓰이지 않는 죽은 코드이거나 조건이 되살아날 길."""
    assert not hasattr(mac_native_gate, name), name


@pytest.mark.parametrize("env,expected", [
    ({}, "auto"), ({ENV: ""}, "auto"), ({ENV: "auto"}, "auto"),
    ({ENV: "ON"}, "on"), ({ENV: "on"}, "on"), ({ENV: "Off"}, "off"),
])
def test_native_mode_values(env, expected):
    """없거나 비면 auto, 대소문자 무시 — movie_source_mode와 같은 규칙. 규칙이 달라지면(예: 빈 값을 거부) 실패."""
    assert native_mode(env) == expected


@pytest.mark.parametrize("bad", ["yes", "1", "true", "onn", " on"])
def test_native_mode_bad_value_raises_naming_the_variable_and_the_value(bad):
    """나쁜 값은 조용히 auto로 넘기지 않고 변수 이름과 받은 값을 든 ValueError (조용한 폴백 금지)."""
    with pytest.raises(ValueError, match=re.escape(ENV)) as excinfo:
        native_mode({ENV: bad})
    assert repr(bad) in str(excinfo.value)


def test_native_mode_reads_the_process_environment_by_default(monkeypatch):
    """env 인자를 안 주면 실제 환경 변수 (app.launch가 인자 없이 부름)."""
    monkeypatch.setenv(ENV, "off")
    assert native_mode() == "off"
    monkeypatch.setenv(ENV, "bogus")
    with pytest.raises(ValueError):
        native_mode()


# ---------------------------------------------------------------- 플랫폼(darwin 전체)·원함

def test_is_apple_silicon_needs_darwin_and_arm64():
    assert is_apple_silicon(*mac("arm64")) is True
    assert is_apple_silicon(*mac("x86_64")) is False


@pytest.mark.parametrize("platform_name,machine", [
    ("linux", "aarch64"), ("linux", "arm64"), ("win32", "ARM64"), ("win32", "AMD64"), ("linux", "x86_64"),
])
def test_is_apple_silicon_false_off_darwin_even_for_arm_machines(platform_name, machine):
    """Windows ARM·Linux ARM이 arm64로 보고해도 Apple Silicon이 아님 — machine()만 보면 auto가 켜짐."""
    assert is_apple_silicon(SimpleNamespace(machine=lambda: machine), SimpleNamespace(platform=platform_name)) is False


def test_auto_is_on_for_any_darwin():
    """auto는 macOS면 어느 칩이든 켬 (Intel Mac·Rosetta 아래 x86_64 빌드도) — 2026-11-04 사용자 결정: 모든 Mac이 QuickTime과 같은 화면.
    platform.machine()을 다시 보는 쪽으로 되돌아가면 x86_64 줄이 실패."""
    assert native_wanted({}, *mac("x86_64")) is True
    assert native_wanted({}, *mac("arm64")) is True


def test_off_is_off_even_on_apple_silicon():
    assert native_wanted({ENV: "off"}, *mac("arm64")) is False


def test_on_is_on_on_darwin():
    assert native_wanted({ENV: "on"}, *mac("arm64")) is True
    assert native_wanted({ENV: "ON"}, *mac("x86_64")) is True


@pytest.mark.parametrize("platform_name", ["win32", "linux"])
def test_on_outside_darwin_raises(platform_name):
    """on을 강제했는데 macOS가 아니면 조용히 끄지 않고 ValueError (이유와 플랫폼을 든다)."""
    with pytest.raises(ValueError, match="macOS") as excinfo:
        native_wanted({ENV: "on"}, SimpleNamespace(machine=lambda: "AMD64"), SimpleNamespace(platform=platform_name))
    assert platform_name in str(excinfo.value) and ENV in str(excinfo.value)


@pytest.mark.parametrize("platform_name,machine", [("win32", "AMD64"), ("linux", "x86_64"), ("linux", "aarch64"), ("win32", "ARM64")])
def test_auto_is_off_outside_darwin(platform_name, machine):
    """macOS 밖은 칩이 무엇이든(ARM 포함) 꺼짐 — VideoToolbox가 없음."""
    assert native_wanted({}, SimpleNamespace(machine=lambda: machine), SimpleNamespace(platform=platform_name)) is False


def test_native_wanted_validates_the_toggle():
    """원함을 묻는 길도 나쁜 값을 삼키지 않음."""
    with pytest.raises(ValueError, match=re.escape(repr("yes"))):
        native_wanted({ENV: "yes"}, *mac("arm64"))


# ---------------------------------------------------------------- 파일 게이트 (실제 ffprobe)

def _clip_probe(tmp_path_factory, name, **kwargs):
    path = str(tmp_path_factory.mktemp(name) / f"{name}.mov")
    make_numbered_clip(path, count=FRAMES, fps="24", width=3840, height=2160, **kwargs)
    return probe_movie(path)


@pytest.fixture(scope="module")
def good_4k_probe(tmp_path_factory):
    """4K ProRes 4444(디코더 쪽 yuv444p12le), bt709 태그."""
    return _clip_probe(tmp_path_factory, "good_4k", color="bt709", profile="4", pix_fmt="yuv444p10le")


@pytest.fixture(scope="module")
def hq_422_4k_probe(tmp_path_factory):
    return _clip_probe(tmp_path_factory, "hq422_4k", color="bt709", profile="3", pix_fmt="yuv422p10le")


@pytest.fixture(scope="module")
def alpha_4k_probe(tmp_path_factory):
    return _clip_probe(tmp_path_factory, "alpha_4k", color="bt709", profile="4", pix_fmt="yuva444p10le")


@pytest.fixture(scope="module")
def untagged_4k_probe(tmp_path_factory):
    return _clip_probe(tmp_path_factory, "untagged_4k", profile="4", pix_fmt="yuv444p10le")


def test_the_factory_clip_is_the_fixture_we_think_it_is(good_4k_probe):
    """아래 시험이 기댈 전제 — 공장 클립이 ffprobe에서 4K·prores·4444 12비트·bt709로 읽힘 (달라지면 이 시험이 먼저 실패)."""
    probe = good_4k_probe
    assert (probe.codec, probe.width, probe.height, probe.pix_fmt, probe.color_space) == (
        "prores", 3840, 2160, "yuv444p12le", "bt709")
    assert movie_pipe_source.ineligible_reason(probe) is None


def test_gate_accepts_a_good_prores_and_names_codec_and_hdr(good_4k_probe):
    """좋은 클립은 통과, 코덱·HDR이 어긋나면 그 말이 든 사유. 게이트 조건을 빼면 해당 줄이 실패."""
    assert native_ineligible_reason(good_4k_probe) is None
    assert native_eligible(good_4k_probe) is True
    assert "HDR" in native_ineligible_reason(dataclasses.replace(good_4k_probe, color_transfer="smpte2084"))
    assert "코덱" in native_ineligible_reason(dataclasses.replace(good_4k_probe, codec="h264"))


def test_pipe_conditions_come_first(good_4k_probe):
    """①~⑥은 ineligible_reason 그대로 먼저 — nb_frames를 모르면 ③ (네이티브 조건이 모두 맞아도)."""
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, nb_frames=None)).startswith("③")
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, rotation=90)).startswith("⑤")


def test_pipe_conditions_are_reused_not_reimplemented(good_4k_probe, monkeypatch):
    """게이트가 movie_pipe_source.ineligible_reason을 그대로 부름 — 그 결과가 곧 사유 (복제본이면 이 시험이 실패)."""
    monkeypatch.setattr(mac_native_gate, "ineligible_reason", lambda probe: "① 센티널")
    assert native_ineligible_reason(good_4k_probe) == "① 센티널"


@pytest.mark.parametrize("width,height", [(3840, 2160), (4096, 2160), (1920, 1080), (1280, 720), (320, 180), (3840, 1080), (1920, 2160)])
@pytest.mark.parametrize("pix_fmt", ["yuv422p10le", "yuv422p12le", "yuv444p10le", "yuv444p12le", "yuva444p10le", "yuva444p12le"])
def test_gate_accepts_any_prores_size_and_chroma(good_4k_probe, width, height, pix_fmt):
    """크기(HD·SD·세로·4K)와 크로마(4:2:2·4:4:4·알파, 10·12비트)는 조건이 아님 — 2026-11-04 사용자 결정(모든 ProRes를 QuickTime과 같은
    VideoToolbox로). 4K나 4:4:4 조건이 되살아나면 해당 줄이 실패."""
    probe = dataclasses.replace(good_4k_probe, width=width, height=height, pix_fmt=pix_fmt)
    assert native_ineligible_reason(probe) is None
    assert native_eligible(probe) is True


def test_codec_condition_holds_even_if_the_pipe_codecs_widen(good_4k_probe, monkeypatch):
    """지금은 ①이 prores 아닌 코덱을 먼저 거르지만, 파이프 대상 코덱이 늘어도 네이티브는 prores만 (⑦)."""
    h264 = dataclasses.replace(good_4k_probe, codec="h264")
    assert native_ineligible_reason(h264).startswith("①")
    monkeypatch.setattr(movie_pipe_source, "PIPE_CODECS", ("prores", "h264"))
    assert native_ineligible_reason(h264) == "⑦ 코덱이 prores가 아님(h264)"


def test_real_alpha_clip_passes(alpha_4k_probe):
    """알파 트랙이 있는 4444(디코더 쪽 yuva444p12le)는 통과 (Ruling 6) — ffprobe가 실제로 주는 pix_fmt에서도."""
    assert alpha_4k_probe.pix_fmt == "yuva444p12le"
    assert native_ineligible_reason(alpha_4k_probe) is None


def test_real_422_clip_passes(hq_422_4k_probe):
    """공장의 4K ProRes HQ 4:2:2 클립도 통과 (옛 test_real_422_clip_is_negative_at_condition_8를 뒤집음). 근거: 실파일 1080p 4:2:2 HQ에서
    VideoToolbox 대 ffmpeg 파이프는 평균 1.4·최대 73이고 다른 픽셀은 전부 홀수 열 — 색차(4:2:2 → 4:4:4) 수평 보간 필터 하나의 차이이며
    VideoToolbox 쪽이 QuickTime과 같음."""
    assert hq_422_4k_probe.pix_fmt == "yuv422p10le"
    assert native_ineligible_reason(hq_422_4k_probe) is None
    assert native_eligible(hq_422_4k_probe) is True


def test_real_untagged_clip_passes(untagged_4k_probe):
    """색 태그 없는 4K 4:4:4 클립도 통과 (옛 test_real_untagged_clip_is_negative_at_condition_9를 뒤집음). 근거: VideoToolbox는 QuickTime처럼
    태그 없는 HD를 709, SD를 601로 읽음 — 앱 화면이 QuickTime과 같아짐."""
    assert untagged_4k_probe.pix_fmt == "yuv444p12le"
    assert untagged_4k_probe.color_space in ("", "unknown")
    assert native_ineligible_reason(untagged_4k_probe) is None
    assert native_eligible(untagged_4k_probe) is True


@pytest.mark.parametrize("color_space", ["", "unknown", "bt709", "smpte170m", "bt470bg", "smpte240m", "fcc", "rgb", "ycgco"])
def test_color_space_is_not_a_condition(good_4k_probe, color_space):
    """행렬 태그(없음·709·601 계열·그 밖)는 거르지 않음 — 거르는 것은 HDR뿐."""
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_space=color_space)) is None


def test_color_tags_other_than_hdr_pass(good_4k_probe):
    """bt2020nc 행렬이어도 전달 함수·원색이 SDR이면 통과 (HDR 판정은 전달 함수·원색이 정함), 범위 mpeg·jpeg·full·tv·pc·없음도 통과."""
    sdr_2020 = dataclasses.replace(good_4k_probe, color_space="bt2020nc", color_transfer="bt709", color_primaries="bt709")
    assert native_ineligible_reason(sdr_2020) is None
    for color_range in ("mpeg", "jpeg", "full", "tv", "pc", "", "unknown"):
        assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_range=color_range)) is None, color_range


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_hdr_transfers_are_negative_naming_the_transfer(good_4k_probe, transfer):
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_transfer=transfer)) == f"⑨ HDR({transfer})"


def test_bt2020_primaries_are_hdr_negative(good_4k_probe):
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, color_primaries="bt2020"))
    assert reason == "⑨ HDR(원색 bt2020)"


def test_a_real_hdr_tag_set_reports_hdr_not_just_the_color_space(good_4k_probe):
    """진짜 HDR 파일은 bt2020nc + smpte2084 + bt2020 — 사유가 색 공간 한 줄이 아니라 HDR이라고 말해야 읽는 사람이 이유를 안다."""
    hdr = dataclasses.replace(good_4k_probe, color_space="bt2020nc", color_transfer="smpte2084", color_primaries="bt2020")
    assert native_ineligible_reason(hdr) == "⑨ HDR(smpte2084)"


@pytest.mark.parametrize("width,height,pix_fmt,color_space", [(1920, 1080, "yuv422p10le", ""), (320, 180, "yuv422p10le", "bt709")])
def test_hdr_is_negative_whatever_the_size_chroma_or_matrix(good_4k_probe, width, height, pix_fmt, color_space):
    """HDR 거름은 크기·크로마·행렬과 상관없이 — 조건이 풀린 만큼 HDR 보호가 유일한 색 조건."""
    probe = dataclasses.replace(good_4k_probe, width=width, height=height, pix_fmt=pix_fmt, color_space=color_space,
                                color_transfer="arib-std-b67")
    assert native_ineligible_reason(probe) == "⑨ HDR(arib-std-b67)"


def test_sdr_transfer_and_primaries_tags_pass(good_4k_probe):
    sdr = dataclasses.replace(good_4k_probe, color_transfer="bt709", color_primaries="bt709")
    assert native_ineligible_reason(sdr) is None
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_transfer="", color_primaries="unknown")) is None


def test_the_first_failing_condition_wins_in_order(good_4k_probe, monkeypatch):
    """여러 조건이 한꺼번에 어긋나면 번호가 앞선 것: ①~⑥ → ⑦ → ⑨. 순서가 바뀌면 해당 줄이 실패."""
    bad = dataclasses.replace(good_4k_probe, nb_frames=None, codec="h264", color_transfer="smpte2084")
    assert native_ineligible_reason(bad).startswith("①")
    monkeypatch.setattr(movie_pipe_source, "PIPE_CODECS", ("prores", "h264"))
    bad = dataclasses.replace(bad, nb_frames=good_4k_probe.nb_frames)
    assert native_ineligible_reason(bad).startswith("⑦")
    bad = dataclasses.replace(bad, codec="prores")
    assert native_ineligible_reason(bad).startswith("⑨")
    assert native_eligible(bad) is False


def test_every_reason_leads_with_its_condition_number(good_4k_probe):
    """남은 조건 번호는 ①~⑥·⑦·⑨ (⑥½·⑧은 지워짐 — 번호는 다시 매기지 않음: 기록·문서의 ⑨ HDR이 그대로 읽히게)."""
    changes = [dict(nb_frames=None), dict(codec="h264"), dict(color_transfer="arib-std-b67"), dict(color_primaries="bt2020")]
    for change in changes:
        reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, **change))
        assert reason is not None and reason[0] in "①②③④⑤⑥⑦⑨", (change, reason)


def test_no_video_track_probe_is_negative(good_4k_probe):
    """영상 트랙이 없는 probe(전부 빈 값)는 양성 증거가 없으므로 음성."""
    empty = dataclasses.replace(good_4k_probe, codec="", width=0, height=0, pix_fmt="", color_space="", nb_frames=None)
    assert native_eligible(empty) is False


# ---------------------------------------------------------------- 어디서나 import

def test_module_imports_without_qt_or_pyobjc():
    """게이트는 Windows·Intel에서도 불리므로 Qt·PyObjC 없이 import됨 — 새 프로세스에서 모듈만 불러 sys.modules를 본다."""
    code = (
        "import sys, yesoncheck.mac_native_gate\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in ('PyQt5', 'objc', 'Foundation', 'Quartz', 'AppKit', 'VideoToolbox', 'CoreMedia'))\n"
        "print(heavy)\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout {result.stdout!r} stderr {result.stderr!r}"


# ---------------------------------------------------------------- app.launch: 토글 검증

def test_launch_validates_native_toggle(qapp, monkeypatch):
    """YESONCHECK_MAC_NATIVE가 나쁜 값이면 시작 때 ValueError — 창을 만들기 전에 (다른 세 토글과 같은 자리).
    app.py의 검증 줄을 지우면 창 대역이 불려 AssertionError로 실패."""
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 토글인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(ENV, "bad")
    with pytest.raises(ValueError, match=re.escape(repr("bad"))):
        app_module.launch(["yesoncheck"])


def test_launch_rejects_on_outside_macos(qapp, monkeypatch):
    """YESONCHECK_MAC_NATIVE=on은 macOS 밖에서 시작 때 ValueError — 창을 만들기 전에 (값만 맞으면 시작을 통과한 뒤 영상을 열 때마다
    native_wanted()가 늦게 실패하지 않게 — 스펙 §5.8 "Windows에서 on은 ValueError", "app.launch가 시작 때 검증"). app이 읽는
    mac_native_gate.native_wanted를 진짜 함수를 Windows 대역(env on·machine AMD64·platform win32)으로 부르는 스파이로 바꿔 봄.
    깨지는 변경: app.py의 검증을 값만 보는 native_mode()로 두면 스파이가 불리지 않고 창 대역이 불려 AssertionError로 실패."""
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("macOS 밖의 on인데 창을 만들었습니다")

    real_wanted = mac_native_gate.native_wanted
    calls = []

    def windows_wanted(*args, **kwargs):
        calls.append((args, kwargs))
        return real_wanted({ENV: "on"}, SimpleNamespace(machine=lambda: "AMD64"), SimpleNamespace(platform="win32"))

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setattr(mac_native_gate, "native_wanted", windows_wanted)
    with pytest.raises(ValueError, match="macOS"):
        app_module.launch(["yesoncheck"])
    assert calls == [((), {})]  # 시작 때 한 번, 기본 인자(이 프로세스의 환경·플랫폼)로


def test_conftest_pins_the_toggle_off():
    """개발자 셸에 토글이 남아 있어도 시험은 off에서 시작 — conftest가 import 때 off로 고정 (옛 test_conftest_clears_the_toggle_at_import 대체).
    게이트가 모든 ProRes·모든 Mac으로 넓어져 auto면 Mac에서 기존 플레이어 시험의 작은 ProRes 클립이 네이티브로 열리기 때문
    (YESONCHECK_FRAME_CACHE=ring 고정과 같은 이유). 네이티브를 겨누는 시험은 on을 명시하거나 native_wanted를 바꿔치기."""
    assert os.environ[ENV] == "off"
