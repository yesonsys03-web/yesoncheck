"""네이티브 재생 게이트 (yesoncheck/mac_native_gate.py): 토글·Apple Silicon 판정·파일 게이트.

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
    COLOR_SPACES_OK, HDR_TRANSFERS, NATIVE_MIN_HEIGHT, NATIVE_MIN_WIDTH, NATIVE_MODE_ENV, NATIVE_MODES, is_apple_silicon,
    native_eligible, native_ineligible_reason, native_mode, native_wanted,
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
    assert (NATIVE_MIN_WIDTH, NATIVE_MIN_HEIGHT) == (3840, 2160)
    assert COLOR_SPACES_OK == ("bt709", "smpte170m", "bt470bg")
    assert HDR_TRANSFERS == ("smpte2084", "arib-std-b67")


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


# ---------------------------------------------------------------- Apple Silicon·원함

def test_is_apple_silicon_needs_darwin_and_arm64():
    assert is_apple_silicon(*mac("arm64")) is True
    assert is_apple_silicon(*mac("x86_64")) is False


@pytest.mark.parametrize("platform_name,machine", [
    ("linux", "aarch64"), ("linux", "arm64"), ("win32", "ARM64"), ("win32", "AMD64"), ("linux", "x86_64"),
])
def test_is_apple_silicon_false_off_darwin_even_for_arm_machines(platform_name, machine):
    """Windows ARM·Linux ARM이 arm64로 보고해도 Apple Silicon이 아님 — machine()만 보면 auto가 켜짐."""
    assert is_apple_silicon(SimpleNamespace(machine=lambda: machine), SimpleNamespace(platform=platform_name)) is False


def test_auto_is_off_on_x86_64_even_on_mac():
    """Intel Mac(또는 Rosetta 아래 x86_64 빌드)는 auto에서 꺼짐 — 의도."""
    assert native_wanted({}, *mac("x86_64")) is False


def test_auto_on_arm64_mac():
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
def test_auto_is_never_on_off_apple_silicon(platform_name, machine):
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


def test_gate_requires_4k_prores_tagged(good_4k_probe):
    """좋은 클립은 통과, 크기·색·HDR·코덱 하나씩 어긋나면 그 말이 든 사유. 게이트 조건을 빼면 해당 줄이 실패."""
    assert native_ineligible_reason(good_4k_probe) is None
    assert native_eligible(good_4k_probe) is True
    assert "4K" in native_ineligible_reason(dataclasses.replace(good_4k_probe, width=1920, height=1080))
    assert "색" in native_ineligible_reason(dataclasses.replace(good_4k_probe, color_space=""))
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


def test_not_4k_reason_names_the_size(good_4k_probe):
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, width=1920, height=1080))
    assert reason == "⑥½ 4K가 아님(1920×1080)"


@pytest.mark.parametrize("width,height,passes", [
    (3840, 2160, True), (3840, 1080, True), (1920, 2160, True), (4096, 2160, True),
    (3839, 2159, False), (1920, 1080, False), (2560, 1440, False),
])
def test_4k_means_width_or_height_reaches_the_minimum(good_4k_probe, width, height, passes):
    """4K 판정은 너비 3840 이상 또는 높이 2160 이상 (경계 3839×2159는 음성). and로 바뀌면 (3840, 1080) 줄이 실패."""
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, width=width, height=height))
    assert (reason is None) is passes
    if not passes:
        assert reason.startswith("⑥½") and f"{width}×{height}" in reason


def test_codec_condition_holds_even_if_the_pipe_codecs_widen(good_4k_probe, monkeypatch):
    """지금은 ①이 prores 아닌 코덱을 먼저 거르지만, 파이프 대상 코덱이 늘어도 네이티브는 prores만 (⑦)."""
    h264 = dataclasses.replace(good_4k_probe, codec="h264")
    assert native_ineligible_reason(h264).startswith("①")
    monkeypatch.setattr(movie_pipe_source, "PIPE_CODECS", ("prores", "h264"))
    assert native_ineligible_reason(h264) == "⑦ 코덱이 prores가 아님(h264)"


@pytest.mark.parametrize("pix_fmt", ["yuv444p10le", "yuv444p12le", "yuva444p10le", "yuva444p12le"])
def test_chroma_444_formats_pass_including_alpha(good_4k_probe, pix_fmt):
    """4:4:4는 10·12비트 모두, 알파(yuva)도 통과 (Ruling 5·6). 목록에서 알파 형식을 빼면 실패."""
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, pix_fmt=pix_fmt)) is None


@pytest.mark.parametrize("pix_fmt", ["yuv422p10le", "yuv422p12le", "yuv420p", "yuv444p", "rgb24", "unknown", ""])
def test_anything_but_listed_444_is_negative_with_the_format_in_the_reason(good_4k_probe, pix_fmt):
    """4:2:2·4:2:0·8비트·모르는 값·빈 값은 음성 — 양성 증거로만 켜짐. 사유에 번호 ⑧과 받은 값."""
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, pix_fmt=pix_fmt))
    assert reason.startswith("⑧ 4:4:4가 아님(")
    assert (pix_fmt or "없음") in reason


def test_real_alpha_clip_passes(alpha_4k_probe):
    """알파 트랙이 있는 4444(디코더 쪽 yuva444p12le)는 통과 (Ruling 6) — ffprobe가 실제로 주는 pix_fmt 이름이 목록에 있어야 함."""
    assert alpha_4k_probe.pix_fmt == "yuva444p12le"
    assert native_ineligible_reason(alpha_4k_probe) is None


def test_real_422_clip_is_negative_at_condition_8(hq_422_4k_probe):
    """공장의 4K ProRes HQ 4:2:2 클립 (Stage 0: 4:2:2는 네이티브 대 파이프 색 차이가 커서 파이프에 남김)."""
    assert hq_422_4k_probe.pix_fmt == "yuv422p10le"
    assert native_ineligible_reason(hq_422_4k_probe) == "⑧ 4:4:4가 아님(yuv422p10le)"
    assert native_eligible(hq_422_4k_probe) is False


def test_real_untagged_clip_is_negative_at_condition_9(untagged_4k_probe):
    """색 태그 없는 4K 4:4:4 클립은 파이프에 남음 (행렬을 추측하지 않음)."""
    assert untagged_4k_probe.pix_fmt == "yuv444p12le"
    reason = native_ineligible_reason(untagged_4k_probe)
    assert reason is not None and reason.startswith("⑨ 색 태그 없음")
    assert native_eligible(untagged_4k_probe) is False


@pytest.mark.parametrize("color_space", ["bt709", "smpte170m", "bt470bg"])
def test_709_and_601_family_color_spaces_pass(good_4k_probe, color_space):
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_space=color_space)) is None


@pytest.mark.parametrize("color_space", ["", "unknown"])
def test_missing_color_tag_is_negative_for_empty_and_unknown(good_4k_probe, color_space):
    """ffprobe는 태그가 없으면 빈 값 또는 "unknown" — 둘 다 음성, 사유에 받은 값."""
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, color_space=color_space))
    assert reason == f"⑨ 색 태그 없음(color_space {color_space!r})"


@pytest.mark.parametrize("color_space", ["bt2020nc", "bt2020c", "smpte240m", "fcc", "rgb", "ycgco"])
def test_other_color_spaces_are_negative_naming_the_space(good_4k_probe, color_space):
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, color_space=color_space))
    assert reason == f"⑨ 색 공간이 bt709/601 계열이 아님({color_space})"


@pytest.mark.parametrize("color_range", ["tv", "pc", "", "unknown"])
def test_known_or_absent_color_range_passes(good_4k_probe, color_range):
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_range=color_range)) is None


@pytest.mark.parametrize("color_range", ["mpeg", "jpeg", "full"])
def test_unexpected_color_range_is_negative_naming_it(good_4k_probe, color_range):
    reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, color_range=color_range))
    assert reason.startswith("⑨ ") and color_range in reason


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


def test_sdr_transfer_and_primaries_tags_pass(good_4k_probe):
    sdr = dataclasses.replace(good_4k_probe, color_transfer="bt709", color_primaries="bt709")
    assert native_ineligible_reason(sdr) is None
    assert native_ineligible_reason(dataclasses.replace(good_4k_probe, color_transfer="", color_primaries="unknown")) is None


def test_the_first_failing_condition_wins_in_order(good_4k_probe):
    """여러 조건이 한꺼번에 어긋나면 번호가 앞선 것: ⑥½ → ⑧ → ⑨. 순서가 바뀌면 해당 줄이 실패."""
    bad = dataclasses.replace(good_4k_probe, width=1920, height=1080, pix_fmt="yuv422p10le", color_space="", color_transfer="smpte2084")
    assert native_ineligible_reason(bad).startswith("⑥½")
    bad = dataclasses.replace(bad, width=3840, height=2160)
    assert native_ineligible_reason(bad).startswith("⑧")
    bad = dataclasses.replace(bad, pix_fmt="yuv444p12le")
    assert native_ineligible_reason(bad).startswith("⑨")
    assert native_eligible(bad) is False


def test_every_reason_leads_with_its_condition_number(good_4k_probe):
    changes = [dict(nb_frames=None), dict(width=640, height=360), dict(pix_fmt="yuv422p10le"), dict(color_space=""),
               dict(color_range="jpeg"), dict(color_transfer="arib-std-b67"), dict(color_primaries="bt2020")]
    for change in changes:
        reason = native_ineligible_reason(dataclasses.replace(good_4k_probe, **change))
        assert reason is not None and reason[0] in "①②③④⑤⑥⑦⑧⑨", (change, reason)


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


def test_conftest_clears_the_toggle_at_import():
    """개발자 셸에 토글이 남아 있어도 시험은 기본(auto)에서 시작 — conftest가 import 때 지움."""
    assert ENV not in os.environ
