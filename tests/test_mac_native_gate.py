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
from yesoncheck import mac_native_gate, mac_prefs, movie_pipe_source
from yesoncheck.mac_native_gate import (
    DECODERS, HDR_PRIMARIES, HDR_TRANSFERS, NATIVE_CODEC, NATIVE_MODE_ENV, NATIVE_MODES, PREF_KEY, SOURCE_FALLBACK,
    effective_decoder,
    native_eligible, native_ineligible_reason, native_mode, native_wanted, preferred_decoder,
    set_preferred_decoder,
)
from yesoncheck.movie_pipe_source import probe_movie

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = "YESONCHECK_MAC_NATIVE"
FRAMES = 3  # 4K 인코드가 느리므로 짧게 — 게이트 ④(프레임 수·길이·속도 삼자 일치)는 3장으로도 성립


def mac(machine):
    return SimpleNamespace(machine=lambda: machine), SimpleNamespace(platform="darwin")


@pytest.fixture
def home(monkeypatch, tmp_path):
    """prefs.json은 시험마다 새 HOME 아래에 (사용자의 ~/Library/Application Support를 건드리지 않음) — tests/conftest.py의 autouse 격리
    위에 경로를 시험이 아는 폴더로 바꿔 줌. Windows의 expanduser는 USERPROFILE을 봄 — 둘 다. (tests/test_default_app.py의 home과 같은 모양)"""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


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


# ---------------------------------------------------------------- 재생 디코더 설정 (프로세스 캐시 · 환경 변수 > prefs > 기본)

def test_preference_constants_match_the_documented_values():
    assert PREF_KEY == "playback_decoder"
    assert DECODERS == ("videotoolbox", "ffmpeg")
    assert (mac_native_gate.SOURCE_DEFAULT, mac_native_gate.SOURCE_PREFS) == ("기본값", "prefs.json")
    assert SOURCE_FALLBACK == "prefs.json 읽기 실패 — 이 세션만 ffmpeg"
    assert mac_native_gate.SOURCE_GL_FALLBACK == "네이티브 화면 그리기 실패 — 이 창만 ffmpeg"  # 실행 중 폴백(Task 5 — 파일은 그대로)
    # 메뉴(Task 4)가 환경 변수가 덮는 경우를 출처의 머리글로 알아봄 — 다른 출처는 그 머리글로 시작하면 안 됨
    assert not any(label.startswith("환경 변수") for label in (mac_native_gate.SOURCE_DEFAULT, mac_native_gate.SOURCE_PREFS, SOURCE_FALLBACK,
                                                              mac_native_gate.SOURCE_GL_FALLBACK))


def test_preferred_decoder_defaults_to_videotoolbox():
    """새 프로세스의 캐시는 videotoolbox·출처 "기본값" (prefs.json을 읽는 app.launch가 부르기 전의 모듈 기본). 시험 사이에는 conftest의 autouse
    픽스처가 이미 set_preferred_decoder로 맞춰 두므로 모듈 기본은 새 프로세스로 봄."""
    code = (
        "import yesoncheck.mac_native_gate as g\n"
        "print(g.preferred_decoder(), g.effective_decoder({}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout {result.stdout!r} stderr {result.stderr!r}"
    assert result.stdout.strip() == "videotoolbox ('videotoolbox', '기본값')"


def test_conftest_isolates_home_from_the_developers_prefs(tmp_path_factory):
    """HOME·USERPROFILE은 시험마다 pytest 임시 폴더 아래 새 폴더 — 개발자의 진짜 ~/Library/Application Support/YesonCheck/prefs.json을 읽지 않음
    (깨진 파일이면 launch 시험이 대역 없는 창에서 멈췄고, playback_decoder가 있으면 결과가 사람마다 달랐음). conftest의 autouse 픽스처를 지우면 실패."""
    base = str(tmp_path_factory.getbasetemp())
    assert os.path.expanduser("~").startswith(base) and os.environ["HOME"].startswith(base)
    assert os.environ["USERPROFILE"] == os.environ["HOME"]
    assert not os.path.exists(mac_prefs.prefs_path()) and mac_prefs.read_prefs() == {}


def test_conftest_leaves_the_cache_changed_by_a_test_behind_1():
    """(1/2) 캐시를 ffmpeg·출처 prefs.json으로 바꿔 둔 채 끝남 — 바로 다음 시험이 기본을 보는지 봄 (정의 순서대로 도는 쌍)."""
    set_preferred_decoder("ffmpeg", source="prefs.json")
    assert effective_decoder({}) == ("ffmpeg", "prefs.json")


def test_conftest_resets_the_cache_between_tests_2():
    """(2/2) 앞 시험이 바꾼 캐시가 남지 않음 — conftest의 autouse 픽스처가 끝날 때 videotoolbox·"기본값"으로 되돌림."""
    assert preferred_decoder() == "videotoolbox"
    assert effective_decoder({}) == ("videotoolbox", "기본값")


@pytest.mark.parametrize("bad", ["quicktime", "", "VideoToolbox", "FFMPEG", None, 3])
def test_set_preferred_decoder_rejects_unknown_value(bad):
    """DECODERS 밖의 값은 조용히 기본으로 넘기지 않고 설정 키와 받은 값을 든 ValueError — 캐시는 그대로."""
    set_preferred_decoder("ffmpeg", source="prefs.json")
    with pytest.raises(ValueError, match=PREF_KEY) as excinfo:
        set_preferred_decoder(bad)
    assert repr(bad) in str(excinfo.value)
    assert (preferred_decoder(), effective_decoder({})) == ("ffmpeg", ("ffmpeg", "prefs.json"))


def test_set_preferred_decoder_without_source_means_default():
    set_preferred_decoder("ffmpeg", source="prefs.json")
    set_preferred_decoder("ffmpeg")
    assert effective_decoder({}) == ("ffmpeg", "기본값")


def test_auto_follows_the_preferred_decoder():
    """auto = darwin이고 선호가 videotoolbox일 때만 켬 — ffmpeg를 고른 Mac은 꺼짐. macOS 밖은 선호와 무관하게 꺼짐 (Windows에는 이 설정이 없음)."""
    set_preferred_decoder("ffmpeg", source="prefs.json")
    assert native_wanted({}, *mac("arm64")) is False
    assert native_wanted({}, *mac("x86_64")) is False
    set_preferred_decoder("videotoolbox", source="prefs.json")
    assert native_wanted({}, *mac("arm64")) is True
    assert native_wanted({}, *mac("x86_64")) is True
    assert native_wanted({}, SimpleNamespace(machine=lambda: "AMD64"), SimpleNamespace(platform="win32")) is False


def test_auto_reads_the_process_environment_and_cache_by_default(monkeypatch):
    """인자 없이 부르는 쪽(player_playback·app.launch)이 보는 것 — 환경 변수가 없으면 캐시를 따름."""
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    set_preferred_decoder("ffmpeg", source="prefs.json")
    assert native_wanted() is False
    set_preferred_decoder("videotoolbox", source="prefs.json")
    assert native_wanted() is True


def test_env_on_off_override_the_preference():
    """on은 선호가 ffmpeg여도 켜고 off는 선호가 videotoolbox여도 끔 (진단·킬 스위치)."""
    set_preferred_decoder("ffmpeg", source="prefs.json")
    assert native_wanted({ENV: "on"}, *mac("arm64")) is True
    assert native_wanted({ENV: "ON"}, *mac("x86_64")) is True
    set_preferred_decoder("videotoolbox", source="prefs.json")
    assert native_wanted({ENV: "off"}, *mac("arm64")) is False
    assert native_wanted({ENV: "Off"}, *mac("x86_64")) is False


def test_env_on_outside_darwin_still_raises_with_a_preference():
    """선호가 videotoolbox여도 macOS 밖의 on은 ValueError 그대로 (조용히 끄지 않음)."""
    set_preferred_decoder("videotoolbox", source="prefs.json")
    with pytest.raises(ValueError, match="macOS"):
        native_wanted({ENV: "on"}, SimpleNamespace(machine=lambda: "AMD64"), SimpleNamespace(platform="win32"))


def test_effective_decoder_reports_the_source():
    """(디코더, 출처) — 출처는 환경 변수(on·off) > prefs.json > 기본값 (메뉴가 체크·비활성을 정하고 시작 기록이 찍음)."""
    assert effective_decoder({}) == ("videotoolbox", "기본값")
    set_preferred_decoder("ffmpeg", source="prefs.json")
    assert effective_decoder({}) == ("ffmpeg", "prefs.json")
    assert effective_decoder({ENV: ""}) == ("ffmpeg", "prefs.json")
    assert effective_decoder({ENV: "AUTO"}) == ("ffmpeg", "prefs.json")  # auto는 선호를 따름
    assert effective_decoder({ENV: "off"}) == ("ffmpeg", "환경 변수 YESONCHECK_MAC_NATIVE=off")
    assert effective_decoder({ENV: "on"}) == ("videotoolbox", "환경 변수 YESONCHECK_MAC_NATIVE=on")
    set_preferred_decoder("videotoolbox", source="prefs.json")
    assert effective_decoder({}) == ("videotoolbox", "prefs.json")
    assert effective_decoder({ENV: "off"}) == ("ffmpeg", "환경 변수 YESONCHECK_MAC_NATIVE=off")
    set_preferred_decoder("ffmpeg")
    assert effective_decoder({ENV: "On"}) == ("videotoolbox", "환경 변수 YESONCHECK_MAC_NATIVE=on")


def test_effective_decoder_rejects_a_bad_toggle():
    with pytest.raises(ValueError, match=re.escape(repr("yes"))):
        effective_decoder({ENV: "yes"})


@pytest.mark.parametrize("preferred", DECODERS)
@pytest.mark.parametrize("env", [{}, {ENV: ""}, {ENV: "auto"}, {ENV: "on"}, {ENV: "off"}])
def test_effective_decoder_agrees_with_native_wanted_on_darwin(preferred, env):
    """기록하는 디코더와 실제로 고르는 길이 어긋나지 않음 — 한쪽만 고치면 로그가 거짓말을 함."""
    set_preferred_decoder(preferred, source="prefs.json")
    decoder, _source = effective_decoder(env)
    assert (decoder == "videotoolbox") is native_wanted(env, *mac("arm64"))


def test_module_does_no_file_io_for_the_preference():
    """게이트는 순수 — 설정 파일을 읽는 쪽은 app.launch(mac_prefs). 이 모듈이 mac_prefs·user_files를 불러오지 않음."""
    code = (
        "import sys, yesoncheck.mac_native_gate\n"
        "bad = sorted(m for m in sys.modules if m in ('yesoncheck.mac_prefs', 'yesoncheck.user_files', 'yesoncheck.default_app'))\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout {result.stdout!r} stderr {result.stderr!r}"


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

def test_launch_validates_native_toggle(qapp, monkeypatch, home):
    """YESONCHECK_MAC_NATIVE가 나쁜 값이면 시작 때 ValueError(변수 이름과 받은 값 포함) — 창을 만들기 전에 (다른 세 토글과 같은 자리).
    Mac에서는 load_playback_decoder 끝의 effective_decoder()가, 그 밖에서는 native_wanted()가 같은 native_mode의 글로 올림 — 어느 쪽이든 ValueError가
    창 대역 앞에서 나와야 하므로, 둘 다 지우면 창 대역이 불려 AssertionError로 실패."""
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 토글인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(ENV, "bad")
    with pytest.raises(ValueError, match=re.escape(repr("bad"))):
        app_module.launch(["yesoncheck"])


def test_launch_rejects_on_outside_macos(qapp, monkeypatch, home):
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


# ---------------------------------------------------------------- app.launch: 재생 디코더 설정(prefs.json) 읽기

FALLBACK_NOTE = "이 세션은 예전 방식(ffmpeg)으로 재생합니다 — Setting → 재생 디코더에서 바꿀 수 있습니다"


class _StopLaunch(Exception):
    """창 대역이 던져 launch를 거기서 멈춤 — 설정을 읽는 단계는 그 앞이다."""


def launch_until_window(monkeypatch):
    """app.launch를 창을 만드는 줄에서 멈춰 돌리고, 그 사이 mac_native_gate.native_wanted()가 돌려준 값들을 돌려줌."""
    from yesoncheck import app as app_module

    def stop_at_window(**kwargs):
        raise _StopLaunch

    real_wanted = mac_native_gate.native_wanted
    wanted = []

    def recording_wanted(*args, **kwargs):
        wanted.append(real_wanted(*args, **kwargs))
        return wanted[-1]

    monkeypatch.setattr(app_module, "VideoPlayer", stop_at_window)
    monkeypatch.setattr(mac_native_gate, "native_wanted", recording_wanted)
    with pytest.raises(_StopLaunch):
        app_module.launch(["yesoncheck"])
    return wanted


def write_prefs(text):
    path = mac_prefs.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture
def mac_platform(monkeypatch):
    """이 시험은 macOS에서 켠 것으로 (Windows CI에서도 prefs를 읽는 갈래를 시험), 토글은 auto — conftest의 off 고정을 풂."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv(ENV, raising=False)


def test_launch_reads_prefs_and_sets_cache(qapp, monkeypatch, home, capsys, mac_platform):
    """prefs.json의 playback_decoder를 시작 때 한 번 읽어 캐시에 두고 한 줄 기록 — native_wanted가 그 캐시를 따라 꺼짐 (파일은 읽지 않음)."""
    write_prefs('{"asked_default_video_app": true, "playback_decoder": "ffmpeg"}')
    wanted = launch_until_window(monkeypatch)
    assert preferred_decoder() == "ffmpeg"
    assert wanted == [False]
    assert "[재생] 디코더: ffmpeg (prefs.json)\n" in capsys.readouterr().out


def test_launch_reads_videotoolbox_from_prefs(qapp, monkeypatch, home, capsys, mac_platform):
    write_prefs('{"playback_decoder": "videotoolbox"}')
    wanted = launch_until_window(monkeypatch)
    assert wanted == [True]
    assert "[재생] 디코더: videotoolbox (prefs.json)\n" in capsys.readouterr().out


@pytest.mark.parametrize("content", [None, "{}", '{"asked_default_video_app": true}'])
def test_launch_without_the_pref_uses_the_default_silently(qapp, monkeypatch, home, dialogs, capsys, mac_platform, content):
    """파일이 없거나 이 키가 없는 것은 오류가 아님 — 기본 videotoolbox, 출처 "기본값", 창 없음."""
    if content is not None:
        write_prefs(content)
    wanted = launch_until_window(monkeypatch)
    assert wanted == [True] and dialogs.messages == []
    assert "[재생] 디코더: videotoolbox (기본값)\n" in capsys.readouterr().out
    if content is None:
        assert not os.path.exists(mac_prefs.prefs_path())  # 읽기만 함 — 파일을 만들지 않음


def test_launch_logs_the_env_override(qapp, monkeypatch, home, capsys, mac_platform):
    """환경 변수가 설정을 덮으면 기록의 출처가 환경 변수 (캐시는 설정값 그대로 — 메뉴가 둘 다 보여 줌)."""
    write_prefs('{"playback_decoder": "ffmpeg"}')
    monkeypatch.setenv(ENV, "on")
    wanted = launch_until_window(monkeypatch)
    assert wanted == [True] and preferred_decoder() == "ffmpeg"
    assert "[재생] 디코더: videotoolbox (환경 변수 YESONCHECK_MAC_NATIVE=on)\n" in capsys.readouterr().out


def test_launch_broken_prefs_warns_once_and_uses_ffmpeg(qapp, monkeypatch, home, dialogs, capsys, mac_platform):
    """깨진 prefs.json은 빈 값으로 치지 않음 — 트레이스백을 기록하고 창 1회, 이 세션은 ffmpeg (설정을 읽지 못한 채 새 경로를 켜지 않음). 파일은 그대로."""
    path = write_prefs("not json")
    wanted = launch_until_window(monkeypatch)
    assert wanted == [False] and preferred_decoder() == "ffmpeg"
    [text] = dialogs.warnings
    assert dialogs.messages[0][:2] == ("warning", "재생 디코더 설정")
    assert "prefs.json" in text and text.endswith(FALLBACK_NOTE)
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and "UserFileError" in captured.err
    assert f"[재생] 디코더: ffmpeg ({SOURCE_FALLBACK})\n" in captured.out
    assert effective_decoder({}) == ("ffmpeg", SOURCE_FALLBACK)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "not json"


def test_launch_bad_pref_value_warns_once_and_uses_ffmpeg(qapp, monkeypatch, home, dialogs, capsys, mac_platform):
    """손으로 고친 나쁜 값("quicktime")도 같은 길 — 창 글에 키와 값, 이 세션은 ffmpeg."""
    write_prefs('{"playback_decoder": "quicktime"}')
    wanted = launch_until_window(monkeypatch)
    assert wanted == [False] and preferred_decoder() == "ffmpeg"
    [text] = dialogs.warnings
    assert PREF_KEY in text and repr("quicktime") in text and text.endswith(FALLBACK_NOTE)
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and "ValueError" in captured.err
    assert f"[재생] 디코더: ffmpeg ({SOURCE_FALLBACK})\n" in captured.out
    assert effective_decoder({}) == ("ffmpeg", SOURCE_FALLBACK)


def test_launch_on_windows_ignores_prefs(qapp, monkeypatch, home, dialogs, capsys):
    """macOS가 아니면 prefs.json을 읽지도 기록하지도 않음 (이 설정은 Mac 전용) — native_wanted는 선호와 무관하게 False."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv(ENV, raising=False)
    write_prefs('{"playback_decoder": "videotoolbox"}')
    reads = []

    def spy_read_prefs():
        reads.append(1)
        raise AssertionError("macOS가 아닌데 prefs.json을 읽었습니다")

    monkeypatch.setattr(mac_prefs, "read_prefs", spy_read_prefs)
    wanted = launch_until_window(monkeypatch)
    assert reads == [] and wanted == [False] and dialogs.messages == []
    assert "[재생]" not in capsys.readouterr().out


def test_conftest_pins_the_toggle_off():
    """개발자 셸에 토글이 남아 있어도 시험은 off에서 시작 — conftest가 import 때 off로 고정 (옛 test_conftest_clears_the_toggle_at_import 대체).
    게이트가 모든 ProRes·모든 Mac으로 넓어져 auto면 Mac에서 기존 플레이어 시험의 작은 ProRes 클립이 네이티브로 열리기 때문
    (YESONCHECK_FRAME_CACHE=ring 고정과 같은 이유). 네이티브를 겨누는 시험은 on을 명시하거나 native_wanted를 바꿔치기."""
    assert os.environ[ENV] == "off"
