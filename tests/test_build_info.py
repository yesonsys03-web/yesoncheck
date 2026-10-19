"""빌드 정보(build_info.json): 빌드할 때 버전을 정해(tools/write_build_info.py) 앱에 넣고, 앱은 읽어서 창 제목·정보 창에 보임."""

import dataclasses
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import types

import pytest

from tests.conftest import ROOT
from yesoncheck import build_info
from yesoncheck.build_info import BuildInfo, current, display_version, load, title_base

TOOL = os.path.join(ROOT, "tools", "write_build_info.py")


def load_tool():
    """tools/write_build_info.py를 모듈로 불러옴 (tools는 패키지가 아니므로 파일 경로로)."""
    spec = importlib.util.spec_from_file_location("write_build_info", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compute_version = load_tool().compute_version


@pytest.fixture
def no_cache():
    """빌드 앱의 빌드 정보는 한 번 읽고 기억함 → 시험 앞뒤로 비움."""
    build_info._frozen_info.cache_clear()
    yield
    build_info._frozen_info.cache_clear()


def test_compute_version_exact_tag():
    assert compute_version(["v1.1.2"], ["v1.1.0", "v1.1.2"], "0f4d3d7c" * 5, False) == "1.1.2"


def test_compute_version_untagged_uses_highest_reachable():
    assert compute_version([], ["v1.1.0", "v1.1.10", "v1.1.9"], "0f4d3d7" + "0" * 33, False) == "1.1.10+0f4d3d7"


def test_compute_version_no_tags_and_dirty():
    assert compute_version([], [], "0f4d3d7" + "0" * 33, True) == "0.0.0+0f4d3d7.dirty"
    assert compute_version(["v1.1.0"], ["v1.1.0"], "a" * 40, True) == "1.1.0+aaaaaaa.dirty"  # 태그여도 dirty면 배포판 아님


def test_compute_version_ignores_non_release_tags():
    assert compute_version(["vfoo"], ["v1.2", "release-1", "v1.1.0"], "b" * 40, False) == "1.1.0+bbbbbbb"


def test_compute_version_rejects_bad_sha():
    with pytest.raises(ValueError, match="커밋"):
        compute_version([], [], "0f4d3d7", False)


def test_load_roundtrip_and_errors(tmp_path):
    (tmp_path / "build_info.json").write_text('{"version": "1.1.0", "commit": "' + "c" * 40 + '", "built": "2026-10-20T10:00:00+09:00", "platform_key": "mac-arm64"}', encoding="utf-8")
    assert load(str(tmp_path)).version == "1.1.0"
    (tmp_path / "build_info.json").write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="build_info.json"):
        load(str(tmp_path))
    with pytest.raises(RuntimeError, match="build_info.json"):
        load(str(tmp_path / "없음"))


@pytest.mark.parametrize("data", [
    [],  # 객체가 아님
    {"version": "1.1.0", "commit": "c" * 40, "built": "2026-10-20T10:00:00+09:00"},  # platform_key 없음
    {"version": "1.1", "commit": "c" * 40, "built": "2026-10-20T10:00:00+09:00", "platform_key": "windows"},
    {"version": "1.1.0", "commit": 1, "built": "2026-10-20T10:00:00+09:00", "platform_key": "windows"},
])
def test_load_rejects_bad_format(tmp_path, data):
    (tmp_path / "build_info.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="build_info.json"):
        load(str(tmp_path))


def test_source_run_has_no_build_info():
    assert current() is None and title_base() == "Yeson Checker" and display_version() == "개발(소스)"


def test_display_version_marks_test_builds(monkeypatch):
    monkeypatch.setattr(build_info, "current", lambda: BuildInfo("1.1.0+0f4d3d7", "0" * 40, "", "windows"))
    assert display_version() == "1.1.0+0f4d3d7 (시험 빌드)" and title_base() == "Yeson Checker 1.1.0+0f4d3d7"


def test_release_build_shows_plain_version(monkeypatch):
    monkeypatch.setattr(build_info, "current", lambda: BuildInfo("1.1.0", "0" * 40, "", "windows"))
    assert display_version() == "1.1.0" and title_base() == "Yeson Checker 1.1.0"


def test_frozen_app_reads_meipass_once(tmp_path, monkeypatch, no_cache):
    info = BuildInfo("1.1.0", "d" * 40, "2026-10-20T10:00:00+09:00", "windows")
    (tmp_path / "build_info.json").write_text(json.dumps(dataclasses.asdict(info)), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert current() == info
    (tmp_path / "build_info.json").unlink()
    assert current() == info  # 기억한 값 (다시 읽지 않음)


def test_frozen_app_without_build_info_raises(tmp_path, monkeypatch, no_cache):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match="build_info.json"):
        current()


def test_platform_key_matches_this_python():
    import platform

    expected = "windows" if sys.platform == "win32" else "mac-" + platform.machine()
    assert build_info.platform_key() == expected
    assert expected in ("windows", "mac-x86_64", "mac-arm64")


def run_tool(*args):
    # 도구는 한글 진단을 표준 오류에 씀 → Windows(PYTHONUTF8 없음)에서도 UTF-8로 읽게
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, TOOL, *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")


def test_write_build_info_tool(tmp_path):
    """이 저장소의 git으로 버전을 정해 JSON을 쓰고, 표준 출력 한 줄은 파일 이름에 붙일 file_tag."""
    out = tmp_path / "x" / "build_info.json"
    result = run_tool("--out", str(out))
    assert result.returncode == 0, result.stderr
    info = load(str(out.parent))
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert info.commit == sha and info.platform_key == build_info.platform_key()
    assert info.built  # ISO 8601 (시간대 포함)
    tag = result.stdout.strip()
    assert result.stdout == tag + "\n"  # 한 줄만
    if "+" in info.version:  # 배포가 아닌 빌드 (태그가 없거나 커밋 안 된 변경이 있음): X.Y.Z+<커밋 7자리>[.dirty]
        assert tag == sha[:7] and info.version.split("+")[1].split(".")[0] == sha[:7]
    else:
        assert tag == info.version


def test_write_build_info_tool_version_override(tmp_path):
    out = tmp_path / "build_info.json"
    result = run_tool("--out", str(out), "--version", "1.2.3")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "1.2.3\n"
    assert load(str(tmp_path)).version == "1.2.3"
    bad = run_tool("--out", str(tmp_path / "bad.json"), "--version", "1.2")
    assert bad.returncode != 0 and not (tmp_path / "bad.json").exists()


class FakeWindow:
    """창 제목 규칙(_update_shared_config_title)만 시험: 창 대신 제목을 기록."""

    def __init__(self, loading=False, problem=None, path_map_problem=None):
        self.shared_config_loading = loading
        self.shared_config_problem = problem
        self.path_map_problem = path_map_problem
        self.title = None

    def setWindowTitle(self, title):
        self.title = title


def window_title(**kwargs):
    from yesoncheck.player_sidebar import PlayerSidebarMixin

    window = FakeWindow(**kwargs)
    PlayerSidebarMixin._update_shared_config_title(window)
    return window.title


def test_window_title_shows_version_in_built_app(monkeypatch):
    assert window_title() == "Yeson Checker"  # 소스 실행: 예전 제목 그대로
    monkeypatch.setattr(build_info, "current", lambda: BuildInfo("1.1.0", "0" * 40, "", "windows"))
    assert window_title() == "Yeson Checker 1.1.0"
    assert window_title(loading=True) == "Yeson Checker 1.1.0 — 공유 설정 불러오는 중…"
    assert window_title(problem="없음").startswith("Yeson Checker 1.1.0 — 공유 설정 오류")


def about_text(monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    from yesoncheck.player_base import VideoPlayerBase

    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
    VideoPlayerBase.show_about(None)
    assert len(shown) == 1
    return shown[0]


def test_about_shows_version_commit_and_build_date(monkeypatch):
    assert "<b>버전:</b> 개발(소스)</p>" in about_text(monkeypatch)
    monkeypatch.setattr(build_info, "current",
                        lambda: BuildInfo("1.1.0+0f4d3d7", "0f4d3d7" + "e" * 33, "2026-10-20T10:00:00+09:00", "mac-arm64"))
    text = about_text(monkeypatch)
    assert "<b>버전:</b> 1.1.0+0f4d3d7 (시험 빌드) · 커밋 0f4d3d7 · 2026-10-20 빌드</p>" in text
    assert "2025.11" not in text


class EnglishWindowsDate(datetime.date):
    """영어 Windows의 strftime처럼: 형식 문자열을 locale 인코딩(cp1252)으로 바꿀 수 없으면 UnicodeEncodeError."""

    @classmethod
    def today(cls):
        return cls(2026, 10, 20)

    def strftime(self, fmt):
        fmt.encode("cp1252")
        return super().strftime(fmt)


@pytest.mark.parametrize("show", ["show_about", "show_help"])
def test_about_and_help_dates_do_not_depend_on_windows_locale(monkeypatch, qapp, show):
    """정보·도움말 창의 날짜(…까지 기록)는 한글을 strftime에 넘기지 않음 — 영어 Windows에서 창이 열리지 않던 문제."""
    from PyQt5.QtWidgets import QMessageBox

    from yesoncheck import player_base

    shown = []
    monkeypatch.setattr(player_base, "datetime", types.SimpleNamespace(date=EnglishWindowsDate))
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
    monkeypatch.setattr(QMessageBox, "setText", lambda box, text: shown.append(text))
    monkeypatch.setattr(QMessageBox, "exec_", lambda box: 0)
    getattr(player_base.VideoPlayerBase, show)(None)
    assert len(shown) == 1 and "2026년 10월 20일까지 기록" in shown[0]


def test_ci_tag_build_must_have_the_tag_version():
    """태그(vX.Y.Z)로 돈 빌드는 앱에 넣은 build_info의 버전이 X.Y.Z여야 함 — Windows·Mac job 둘 다 확인하고 다르면 실패
    (태그가 가리키는 커밋과 빌드한 것이 다르면 배포판 이름·버전이 조용히 틀어짐)."""
    import re

    with open(os.path.join(ROOT, ".github", "workflows", "windows-build.yml"), encoding="utf-8") as fh:
        text = fh.read()
    windows, mac = text.split("\n  mac:\n", 1)
    assert re.search(r"\$env:GITHUB_REF -match '\^refs/tags/v\(\\d\+\\\.\\d\+\\\.\\d\+\)\$'", windows), windows
    assert "if ($version -ne $tagVersion) { throw" in windows
    assert "REF_RE='^refs/tags/v([0-9]+\\.[0-9]+\\.[0-9]+)$'" in mac
    assert 'if [ "$BUILD_VERSION" != "$TAG_VERSION" ]; then' in mac
