"""Windows 고해상도 배율: Qt 5.15 기본 반올림(Round)은 125%를 1배, 150%를 2배로 그려서 앱이 다른 앱보다 20% 작거나
33% 컸다 (사용자: 3840×2160 모니터, 150%일 때 창이 줄지 않는다고 알림 — 최소 창이 실제 픽셀로 약 2284×1690 —
지금은 125%로 1배라 20% 작음). Windows에서만 QApplication을 만들기 전에 PassThrough(배율 그대로)로 정한다.
Mac은 배율이 정수라 차이가 없지만 바꾸지 않는다.

시작 로그에는 화면의 논리 크기·작업 영역·devicePixelRatio·논리 DPI·반올림 정책을 한 줄로 남긴다 (배율이 2배로
반올림되는지 사용자 로그로 알 수 있게).
"""

import os
import subprocess
import sys

import pytest
from PyQt5.QtCore import Qt

from tests.conftest import ROOT
from yesoncheck import app as app_module

PASS_THROUGH = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough


class _FakeApplication:
    """QApplication 대신: 만들기 전에 불린 정적 설정과 만들어진 순서를 기록."""

    calls = []

    def __init__(self, argv):
        self.calls.append(("create", tuple(argv)))

    @classmethod
    def setAttribute(cls, attribute, on=True):
        cls.calls.append(("attribute", attribute, on))

    @classmethod
    def setHighDpiScaleFactorRoundingPolicy(cls, policy):
        cls.calls.append(("policy", policy))


@pytest.fixture
def fake_application(monkeypatch):
    _FakeApplication.calls = []
    monkeypatch.setattr(app_module, "QApplication", _FakeApplication)
    return _FakeApplication


def test_windows_sets_pass_through_before_creating_the_application(fake_application, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    app_module.create_application(["YesonCheck"])
    calls = fake_application.calls
    assert ("policy", PASS_THROUGH) in calls
    assert calls.index(("policy", PASS_THROUGH)) < calls.index(("create", ("YesonCheck",)))
    assert ("attribute", Qt.AA_EnableHighDpiScaling, True) in calls  # 예전 설정은 그대로


def test_mac_keeps_the_default_policy(fake_application, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    app_module.create_application(["YesonCheck"])
    assert not [c for c in fake_application.calls if c[0] == "policy"]
    assert ("create", ("YesonCheck",)) in fake_application.calls


def test_missing_policy_api_is_an_error_not_skipped(monkeypatch):
    """PyQt5가 너무 오래돼 정책을 못 정하면 조용히 넘어가지 않고 오류 (Windows 배율이 다시 반올림됨)."""

    class OldApplication:
        pass

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_module, "QApplication", OldApplication)
    with pytest.raises(RuntimeError, match="setHighDpiScaleFactorRoundingPolicy"):
        app_module.apply_high_dpi_rounding_policy()


def test_screen_report_line(qapp):
    line = app_module.screen_report(qapp.primaryScreen())
    for field in ("논리", "작업 영역", "devicePixelRatio", "논리 DPI", "반올림"):
        assert field in line, line
    assert "\n" not in line


LAUNCH_CHILD = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QWidget
before = QGuiApplication.highDpiScaleFactorRoundingPolicy()
from yesoncheck import app as app_module


class QuickPlayer(QWidget):
    # 진짜 창 대신 (app.launch 경로는 그대로): launch가 이벤트 루프에서 부르는 공유 설정 불러오기 때 앱을 끝냄
    # (show 안에서 quit하면 이벤트 루프가 시작되기 전이라 무시됨)
    def __init__(self, load_shared_config=True):
        super().__init__()

    def start_shared_config_load(self):
        QTimer.singleShot(0, QGuiApplication.instance().quit)

    def handle_update_startup(self, update_token):
        pass  # 지난 업데이트의 결과 알림 — 이 시험의 대상이 아님

    def show_user_file_problems(self):
        pass  # 시작할 때 읽은 북마크·설정 파일의 문제 알림 — 이 시험의 대상이 아님

    def start_instance_link(self):
        pass  # 창 기록·창 사이 연결 서버 — 이 시험의 대상이 아님

    def show_viewport_fallback(self):
        pass  # GL 뷰포트 폴백 알림 — 이 시험의 대상이 아님


app_module.VideoPlayer = QuickPlayer
code = app_module.launch([sys.argv[0]])
after = QGuiApplication.highDpiScaleFactorRoundingPolicy()
print(f"CHILD: policy before={before.name} after={after.name} code={code}", flush=True)
"""


def test_fresh_launch_uses_pass_through_on_windows(tmp_path):
    """새 프로세스에서 실제 app.launch: Windows는 PassThrough, 그 밖에는 Qt 기본값 그대로. 시작 로그에 화면 줄."""
    script = tmp_path / "launch_child.py"
    script.write_text(LAUNCH_CHILD, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, str(script), ROOT], cwd=ROOT, env=env, capture_output=True, timeout=90)
    out = result.stdout.decode("utf-8", "replace")
    err = result.stderr.decode("utf-8", "replace")
    report = f"종료 코드 {result.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    assert result.returncode == 0, report
    line = [l for l in out.splitlines() if l.startswith("CHILD: policy")]
    assert line, report
    before = line[0].split("before=")[1].split()[0]
    after = line[0].split("after=")[1].split()[0]
    if sys.platform == "win32":
        assert after == "PassThrough", report
    else:
        assert after == before, report
    assert "devicePixelRatio" in out and "반올림" in out, report  # 시작 로그의 화면 줄
