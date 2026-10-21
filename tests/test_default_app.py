"""yesoncheck/default_app.py 시험: Mac에서 .mov·.mp4의 기본 앱을 YesonCheck로 (설계 3-3·6장).

- 묻기 판단(should_ask)은 순수 함수, 답은 prefs.json(`~/Library/Application Support/YesonCheck/prefs.json`)에 기록.
- LaunchServices는 대역(FakeLaunchServices)으로 바꿔 끼움 — 이 Mac의 기본 앱을 바꾸지 않음. 진짜 API는 읽기만 하는
  test_current_handler_real_api_returns_str_or_none (Mac에서만).
- 결과·오류 창은 dialogs 픽스처가 기록. 묻는 창(default_app._ask)은 흐름 시험에서는 대역(ask 픽스처 — 차례로 답함), 창 자체는
  진짜 QMessageBox로(단추 누르기·Esc·⌘.·닫기·reject) — 단추를 누른 것만 답.
- Info.plist의 CFBundleDocumentTypes는 spec 파일의 BUNDLE(info_plist=…)을 그대로 읽어 확인 (빌드 앱의 Info.plist는 CI의
  plutil 확인 단계).
"""

import ast
import json
import os
import plistlib
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QKeyEvent, QKeySequence
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from tests.conftest import ROOT
from tests.test_fast_startup import wait_until
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import app as app_module  # sys.frozen을 바꾸기 전에 (불러올 때 frozen이면 _MEIPASS를 찾음)
from yesoncheck import default_app, file_associations, instances, update_install
from yesoncheck.user_files import UserFileError

MAC_ONLY = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Mac 전용: LaunchServices(CoreServices)는 Mac에만 있음",
)
# 진짜 QMessageBox를 띄우는 시험 (묻는 창은 Mac에서만 뜸)
REAL_BOX = pytest.mark.skipif(sys.platform == "win32", reason="Windows offscreen에서 QMessageBox는 Qt를 죽임 (시험 환경)")

QT_MOVIE, MPEG4 = "com.apple.quicktime-movie", "public.mpeg-4"
BUNDLE_ID = "com.yeson.check"
EXPECTED_DOCUMENT_TYPES = [{"CFBundleTypeName": "Video", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
                            "LSItemContentTypes": ["com.apple.quicktime-movie", "public.mpeg-4"]}]


ALL, VIEWER = "All", "Viewer"  # 역할 이름 (default_app.VERIFIED_ROLES)


def both_roles(handlers):
    """UTI → 앱 ID 표를 (UTI, 역할) → 앱 ID로 (두 역할이 같은 앱 — should_ask의 handlers 모양)."""
    return {(uti, role): handler for uti, handler in handlers.items() for role in (ALL, VIEWER)}


class FakeLaunchServices:
    """LaunchServices 대역. handlers: UTI → 기본 앱 ID (없으면 None — 역할 All·Viewer 모두), viewer: UTI → Viewer 역할에만
    따로 정해진 앱 ID (kLSRolesAll로 정해도 바뀌지 않음 — 다른 동영상 앱이 남긴 항목), copies: 앱 ID(소문자) → 등록된 사본
    경로들, calls: 부른 차례 (읽기는 역할 이름까지). set_status: UTI → 돌려줄 OSStatus (0이 아니면 바꾸지 않음), ignored: 정해도(0)
    바뀌지 않는 UTI (다시 읽으면 옛 값 — 확인에서 걸려야 함), raises: 정해 두면 정하기에서 그 예외. LaunchServices처럼 정한 앱 ID는
    소문자로."""

    def __init__(self, handlers=None, copies=None):
        self.handlers = dict(handlers or {})
        self.viewer = {}
        self.copies = dict(copies or {})
        self.calls = []
        self.set_status = {}
        self.ignored = set()
        self.register_status = 0
        self.raises = None

    def register(self, app_path):
        self.calls.append(("register", app_path))
        return self.register_status

    def default_handler(self, uti, role):
        name = {default_app._ROLES_ALL: ALL, default_app._ROLES_VIEWER: VIEWER}[role]
        self.calls.append(("read", uti, name))
        if name == VIEWER and uti in self.viewer:
            return self.viewer[uti]
        return self.handlers.get(uti)

    def set_default_handler(self, uti, bundle_id):
        self.calls.append(("set", uti, bundle_id))
        if self.raises is not None:
            raise self.raises
        status = self.set_status.get(uti, 0)
        if status == 0 and uti not in self.ignored:
            self.handlers[uti] = bundle_id.lower()
        return status

    def application_paths(self, bundle_id):
        self.calls.append(("copies", bundle_id))
        return list(self.copies.get(bundle_id.lower(), []))


@pytest.fixture
def fake_ls(monkeypatch):
    fake = FakeLaunchServices({QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None})
    monkeypatch.setattr(default_app, "_launch_services", lambda: fake)
    return fake


@pytest.fixture
def home(monkeypatch, tmp_path):
    """prefs.json은 시험마다 새 HOME 아래에 (사용자의 ~/Library/Application Support를 건드리지 않음). Windows의 expanduser는
    USERPROFILE을 봄 — 둘 다."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


@pytest.fixture
def ask(monkeypatch):
    """묻는 창(default_app._ask) 대역: answers의 차례로 답함(다 쓰면 [예] — True), 물은 횟수는 asked."""
    rec = SimpleNamespace(answers=[], asked=0)

    def fake(parent):
        rec.asked += 1
        return rec.answers.pop(0) if rec.answers else True

    monkeypatch.setattr(default_app, "_ask", fake)
    return rec


def make_bundle(folder, name, bundle_id=BUNDLE_ID):
    """Info.plist(CFBundleIdentifier)만 있는 .app 번들 → 경로."""
    app = os.path.join(str(folder), name)
    os.makedirs(os.path.join(app, "Contents"))
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as fh:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": name}, fh)
    return app


@pytest.fixture
def mac_app(monkeypatch, tmp_path):
    """Mac 빌드 앱처럼: sys.frozen, 자기 번들(update_install.running_app_location)은 tmp의 YesonCheck_Autocut_Intel.app.
    Windows 파일 연결 등록(file_associations — Windows 빌드 앱만)은 없음: Windows CI에서 launch()가 진짜 레지스트리에 쓰지 않게."""
    app = make_bundle(tmp_path / "Applications", "YesonCheck_Autocut_Intel.app")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(default_app, "IS_MAC", True)
    monkeypatch.setattr(file_associations, "IS_WINDOWS", False)
    monkeypatch.setattr(update_install, "running_app_location", lambda: app)
    return app


def prefs_on_disk():
    with open(default_app.prefs_path(), encoding="utf-8") as fh:
        return json.load(fh)


# ---- 묻기 판단·기록 ----


def test_should_ask_only_once_and_only_when_not_default():
    assert default_app.VIDEO_UTIS == ("com.apple.quicktime-movie", "public.mpeg-4")
    # 확인하는 역할: All(정하는 역할)과 Viewer(Finder 더블클릭이 여는 역할)
    assert default_app.VERIFIED_ROLES == ((ALL, 0xFFFFFFFF), (VIEWER, 0x00000002))
    not_default = both_roles({QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None})
    assert default_app.should_ask({}, not_default, BUNDLE_ID)
    assert default_app.should_ask({"other": 1}, not_default, BUNDLE_ID)
    # 한 번만: [예]·[아니요]를 기록한 뒤에는 묻지 않음 (기본 앱이 아니어도)
    assert not default_app.should_ask({"asked_default_video_app": True}, not_default, BUNDLE_ID)
    assert default_app.should_ask({"asked_default_video_app": False}, not_default, BUNDLE_ID)
    # 두 종류 모두 이미 YesonCheck면 묻지 않음 — LaunchServices는 앱 ID를 소문자로 돌려주기도 함 → 대소문자 무관
    yeson = both_roles({QT_MOVIE: "com.yeson.check", MPEG4: "COM.Yeson.Check"})
    assert not default_app.should_ask({}, yeson, "com.Yeson.check")
    # 하나라도 아니면 물음
    assert default_app.should_ask({}, both_roles({QT_MOVIE: "com.yeson.check", MPEG4: "com.apple.QuickTimePlayerX"}),
                                  BUNDLE_ID)
    assert default_app.should_ask({}, both_roles({QT_MOVIE: None, MPEG4: "com.yeson.check"}), BUNDLE_ID)
    # All은 YesonCheck여도 Viewer 역할(더블클릭)에 다른 앱이 따로 있으면 물음
    assert default_app.should_ask({}, {**yeson, (MPEG4, VIEWER): "org.videolan.vlc"}, BUNDLE_ID)


def test_prefs_file_records_answer_and_refuses_broken_file(home):
    path = default_app.prefs_path()
    assert path == os.path.join(str(home), "Library", "Application Support", "YesonCheck", "prefs.json")
    assert default_app.read_prefs() == {}  # 아직 없음
    default_app.record_asked()
    assert prefs_on_disk() == {"asked_default_video_app": True}
    assert default_app.read_prefs() == {"asked_default_video_app": True}
    # 다른 키는 그대로 둠 (다른 창·다음 버전이 쓴 것)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"something": [1, 2]}')
    default_app.record_asked()
    assert prefs_on_disk() == {"something": [1, 2], "asked_default_video_app": True}
    # 깨진 파일·객체가 아닌 JSON은 빈 값으로 치지 않음 (UserFileError, 파일은 그대로)
    for broken in ("{not json", "[1, 2]"):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(broken)
        with pytest.raises(UserFileError, match="prefs.json"):
            default_app.read_prefs()
        with pytest.raises(UserFileError, match="prefs.json"):
            default_app.record_asked()
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == broken


# ---- 기본 앱 정하기 (LaunchServices 대역) ----


def test_set_default_sets_both_utis_and_verifies(fake_ls, tmp_path):
    app = make_bundle(tmp_path, "YesonCheck_Autocut_Intel.app", "com.Yeson.Check")
    default_app.set_default(app)
    # 이 번들을 LaunchServices에 등록(이미 있으면 그대로) → 두 종류 모두 정함(역할 All — Viewer를 따로 정하지 않음) →
    # 둘 다 역할 All과 Viewer(더블클릭)로 다시 읽어 확인
    assert fake_ls.calls == [("register", app),
                             ("set", QT_MOVIE, "com.Yeson.Check"), ("set", MPEG4, "com.Yeson.Check"),
                             ("read", QT_MOVIE, ALL), ("read", QT_MOVIE, VIEWER),
                             ("read", MPEG4, ALL), ("read", MPEG4, VIEWER)]
    # 다시 읽은 값이 소문자여도 같은 앱 (대소문자 무관)
    assert fake_ls.handlers == {QT_MOVIE: "com.yeson.check", MPEG4: "com.yeson.check"}
    assert default_app.current_handler(QT_MOVIE) == "com.yeson.check"
    assert default_app.current_handlers() == both_roles({QT_MOVIE: "com.yeson.check", MPEG4: "com.yeson.check"})


def test_set_default_fails_when_double_click_role_stays_another_app(qapp, fake_ls, dialogs, ask, mac_app, home,
                                                                    tmp_path):
    """역할 All로 정해도 Viewer 역할(Finder 더블클릭)에 다른 앱이 따로 정해져 남아 있으면 더블클릭은 그 앱을 열 수 있음 →
    정한 것으로 치지 않고 DefaultAppError (다시 읽은 두 역할의 값). Viewer를 따로 정하지는 않음."""
    app = make_bundle(tmp_path, "YesonCheck_Autocut_Intel.app")
    fake_ls.viewer[MPEG4] = "org.videolan.vlc"
    with pytest.raises(default_app.DefaultAppError) as caught:
        default_app.set_default(app)
    text = str(caught.value)
    assert "public.mpeg-4" in text and "Viewer 'org.videolan.vlc'" in text and "All 'com.yeson.check'" in text
    assert "com.apple.quicktime-movie" not in text  # 이 종류는 두 역할 모두 YesonCheck
    assert [c for c in fake_ls.calls if c[0] == "set"] == [("set", QT_MOVIE, BUNDLE_ID), ("set", MPEG4, BUNDLE_ID)]

    # 처음 켤 때: All은 둘 다 YesonCheck여도 Viewer가 다른 앱이면 물음 → [예] → 정하기 실패를 오류 창으로
    fake_ls.calls.clear()
    default_app.ask_at_start(None)
    assert ask.asked == 1
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and default_app.SET_FAILED_TEXT in text and "org.videolan.vlc" in text


def test_set_default_reports_status_and_mismatch(fake_ls, tmp_path):
    app = make_bundle(tmp_path, "YesonCheck_Autocut_Intel.app")
    # 한 종류가 실패해도 다른 종류는 정하고, 실패한 것을 모두 알림 (OSStatus·다시 읽은 값)
    fake_ls.set_status[MPEG4] = -54
    fake_ls.ignored.add(QT_MOVIE)
    with pytest.raises(default_app.DefaultAppError) as caught:
        default_app.set_default(app)
    text = str(caught.value)
    assert "public.mpeg-4" in text and "-54" in text
    assert "com.apple.quicktime-movie" in text and "com.apple.QuickTimePlayerX" in text  # 정했는데 그대로
    assert ("set", QT_MOVIE, BUNDLE_ID) in fake_ls.calls and ("set", MPEG4, BUNDLE_ID) in fake_ls.calls
    # 등록 실패
    fake_ls.register_status = -10811
    with pytest.raises(default_app.DefaultAppError, match="-10811"):
        default_app.set_default(app)
    # Info.plist에 앱 ID가 없음
    os.remove(os.path.join(app, "Contents", "Info.plist"))
    with pytest.raises(default_app.DefaultAppError, match="Info.plist"):
        default_app.set_default(app)


def test_other_copies_reported(qapp, fake_ls, dialogs, ask, mac_app, home, tmp_path):
    other = make_bundle(tmp_path / "old", "yesonchecker.app")
    dist = make_bundle(tmp_path / "dist", "YesonCheck_Autocut_Intel.app")
    gone = str(tmp_path / "unmounted" / "YesonCheck_Autocut_Intel.app")  # LaunchServices에 남은, 이제 없는 사본
    # 자기 자신은 같은 파일인지로 비교 (경로 모양 — '..'·끝의 / — 가 달라도 같은 번들)
    roundabout = os.path.join(os.path.dirname(mac_app), "..", "Applications", os.path.basename(mac_app))
    fake_ls.copies[BUNDLE_ID] = [roundabout + os.sep, other, gone, dist]
    assert default_app.other_copies(BUNDLE_ID, mac_app) == [other, dist]
    assert default_app.other_copies("COM.YESON.CHECK", mac_app + "/") == [other, dist]

    # Help → 정하기: 정한 뒤 다른 사본의 경로와 지우라는 안내 (지우지 않음)
    default_app.set_default_from_menu(None)
    [(kind, title, text)] = dialogs.messages
    assert kind == "information"
    assert default_app.DONE_TEXT in text and default_app.OTHER_COPIES_TEXT in text
    assert other in text and dist in text and gone not in text
    assert f"이 앱: {mac_app}" in text
    assert os.path.isdir(other) and os.path.isdir(dist)

    # 처음 켤 때 [예]도 같은 안내 (정했다는 말 없이 — 묻는 창에 답한 것이므로)
    dialogs.messages.clear()
    fake_ls.handlers = {QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None}
    default_app.ask_at_start(None)
    assert ask.asked == 1
    [(kind, title, text)] = dialogs.messages
    assert kind == "information" and default_app.OTHER_COPIES_TEXT in text and other in text and dist in text
    assert default_app.DONE_TEXT not in text

    # 다른 사본이 없으면: Help는 정했다는 창 하나, 처음 켤 때는 묻는 창만
    fake_ls.copies[BUNDLE_ID] = [mac_app]
    dialogs.messages.clear()
    default_app.set_default_from_menu(None)
    assert dialogs.messages == [("information", default_app.TITLE, default_app.DONE_TEXT)]


def test_set_default_failure_shows_dialog(qapp, fake_ls, dialogs, ask, mac_app, home):
    # Help → 정하기: OSStatus 실패 → 오류 창(무엇이 왜) — 정했다는 창 없음
    fake_ls.set_status[MPEG4] = -54
    default_app.set_default_from_menu(None)
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and default_app.SET_FAILED_TEXT in text and "public.mpeg-4" in text and "-54" in text
    assert "Traceback" not in text  # 예상된 실패는 트레이스백 없이

    # 처음 켤 때 [예] → 실패해도 답은 기록 (다음에 다시 묻지 않음 — Help로 다시 할 수 있음), 오류 창
    dialogs.messages.clear()
    default_app.ask_at_start(None)
    assert ask.asked == 1
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and "-54" in text
    assert prefs_on_disk() == {"asked_default_video_app": True}

    # 정한 뒤 다시 읽은 값이 다름 → 오류 창
    dialogs.messages.clear()
    fake_ls.set_status.clear()
    fake_ls.handlers = {QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None}
    fake_ls.ignored.add(QT_MOVIE)
    default_app.set_default_from_menu(None)
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and "com.apple.quicktime-movie" in text and "com.apple.QuickTimePlayerX" in text

    # 예상 못 한 오류 → 기록(stderr)에 트레이스백, 오류 창에도
    dialogs.messages.clear()
    fake_ls.raises = RuntimeError("시험: LaunchServices가 이상함")
    default_app.set_default_from_menu(None)
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and "Traceback" in text and "시험: LaunchServices가 이상함" in text


def test_failure_dialog_is_the_apps_error_window(qapp, fake_ls, dialogs, mac_app, home, tmp_path, monkeypatch):
    """빌드 앱(예외 창이 있음)에서는 오류 창이 앱의 예외 창 — 기록 파일 경로가 붙고 한 번에 하나만 (app._ErrorDialog)."""
    log_path = str(tmp_path / "yesoncheck_20261021_123.log")
    monkeypatch.setattr(sys, "excepthook", app_module.make_excepthook(log_path))
    fake_ls.set_status[QT_MOVIE] = -10814
    default_app.set_default_from_menu(None)
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and title == "YesonCheck 오류"
    assert default_app.SET_FAILED_TEXT in text and "-10814" in text and f"로그: {log_path}" in text


def test_source_run_and_app_location_are_not_made_default(qapp, fake_ls, dialogs, ask, home, tmp_path, monkeypatch):
    """소스 실행은 정하지 않음(안내만). dmg 안(/Volumes)·임시 격리 위치(AppTranslocation)에서 켠 앱은 정하지 않고 묻지도 않음 —
    응용 프로그램 폴더의 진짜 사본을 '다른 사본'으로 지우라고 하지 않게."""
    monkeypatch.setattr(default_app, "IS_MAC", True)
    monkeypatch.delattr(sys, "frozen", raising=False)
    default_app.set_default_from_menu(None)
    assert dialogs.messages == [("information", default_app.TITLE, default_app.SOURCE_RUN_TEXT)]
    assert fake_ls.calls == []

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for app in ("/Volumes/YesonCheck 1.2.0/YesonCheck_Autocut_Intel.app",
                "/private/var/folders/x/T/AppTranslocation/1A2B/d/YesonCheck_Autocut_Intel.app"):
        monkeypatch.setattr(update_install, "running_app_location", lambda app=app: app)
        dialogs.messages.clear()
        default_app.set_default_from_menu(None)
        [(kind, title, text)] = dialogs.messages
        assert kind == "warning" and text == default_app.location_problem(app) is not None
        default_app.ask_at_start(None)  # 묻지 않음, 기록하지 않음
        assert ask.asked == 0 and len(dialogs.messages) == 1 and not os.path.exists(default_app.prefs_path())
    assert fake_ls.calls == []
    assert default_app.location_problem("/Applications/YesonCheck_Autocut_Intel.app") is None


# ---- 처음 켤 때 한 번 묻기 ----


def test_first_run_asks_once_and_records_explicit_answers(qapp, fake_ls, dialogs, ask, mac_app, home):
    fake_ls.copies[BUNDLE_ID] = [mac_app]
    # [아니요] → 기록, 정하지 않음
    ask.answers = [False]
    default_app.ask_at_start(None)
    assert ask.asked == 1 and dialogs.messages == []
    assert prefs_on_disk() == {"asked_default_video_app": True}
    assert not [c for c in fake_ls.calls if c[0] in ("register", "set")]
    # 다음에 켤 때는 묻지 않음 (LaunchServices도 읽지 않음)
    calls = len(fake_ls.calls)
    default_app.ask_at_start(None)
    assert ask.asked == 1 and len(fake_ls.calls) == calls

    # 새 사용자: [예] → 기록하고 두 종류 모두 정함 (다른 사본 없음 → 창 없음)
    os.remove(default_app.prefs_path())
    ask.answers = [True]
    default_app.ask_at_start(None)
    assert ask.asked == 2 and dialogs.messages == []
    assert prefs_on_disk() == {"asked_default_video_app": True}
    assert fake_ls.handlers == {QT_MOVIE: BUNDLE_ID, MPEG4: BUNDLE_ID}

    # 이미 기본 앱이면 묻지 않음 (기록도 하지 않음 — 답한 것이 아님)
    os.remove(default_app.prefs_path())
    default_app.ask_at_start(None)
    assert ask.asked == 2 and not os.path.exists(default_app.prefs_path())

    # 단추 없이 닫힘(None) → 기록하지 않음, 정하지 않음
    fake_ls.handlers = {QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None}
    ask.answers = [None]
    default_app.ask_at_start(None)
    assert ask.asked == 3 and not os.path.exists(default_app.prefs_path())
    assert fake_ls.handlers == {QT_MOVIE: "com.apple.QuickTimePlayerX", MPEG4: None}


def test_first_run_does_not_ask_while_other_windows_are_open(qapp, fake_ls, dialogs, ask, mac_app, home, capsys):
    """처음 켤 때 한 번(설계 3-3): 같은 앱 자리의 다른 YesonCheck 창이 열려 있으면(창 기록 — 그 창이 묻고 있을 수 있음) 묻지도
    기록하지도 않음 — 답하기 전에 여러 파일·Dock 클릭으로 창을 여러 개 띄워도 같은 질문이 창마다 쌓이지 않게. 혼자 켜질 때
    다시 물음. 이 창의 기록(start_instance_link — 묻기보다 먼저)은 세지 않음."""
    instances.register(mac_app, "yesoncheck-me")  # 이 창 (app.launch가 묻기 전에 남김)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        started = instances.process_start_time(child.pid)
        assert started is not None
        os.makedirs(instances.registry_dir(), exist_ok=True)
        with open(os.path.join(instances.registry_dir(), f"{child.pid}.json"), "w", encoding="utf-8") as fh:
            json.dump({"pid": child.pid, "app_path": mac_app, "started": started, "server_name": "yesoncheck-other"}, fh)
        default_app.ask_at_start(None)
        assert ask.asked == 0 and dialogs.messages == []
        assert not os.path.exists(default_app.prefs_path())  # 답한 것이 아님
        assert fake_ls.calls == []  # LaunchServices도 보지 않음
        out = capsys.readouterr().out
        assert "다른 YesonCheck 창 1개" in out and f"pid {child.pid}" in out
    finally:
        child.kill()
        child.wait()
    # 다른 창이 끝나면(기록은 죽은 창 — others가 지움) 이 창 혼자 → 물음
    default_app.ask_at_start(None)
    assert ask.asked == 1 and prefs_on_disk() == {"asked_default_video_app": True}


def _answer_box_with(action):
    """진짜 묻는 창(default_app._ask)을 띄우고, 뜨면 action(box) → (_ask의 값, 창의 글·단추·기본 단추)."""
    seen = []

    def act():
        [box] = [w for w in QApplication.topLevelWidgets()
                 if isinstance(w, QMessageBox) and w.isVisible() and w.isModal()]
        seen.append((box.text(), [b.text() for b in box.buttons()], box.defaultButton().text(),
                     box.property("ycTitle")))
        action(box)

    QTimer.singleShot(50, act)
    return default_app._ask(None), seen


@REAL_BOX
def test_ask_counts_only_button_presses(qapp):
    """[예]·[아니요]를 누른 것만 답(True·False). 단추를 누르지 않고 닫히면 None (기록하지 않음 — Ruling 26): 취소 키(Esc, Mac은
    ⌘.도 — Qt 기본은 [아니요]를 누르지만 이 창은 누르지 않고 닫음), reject()(다른 창의 닫기 요청 — close_for_update), 창
    닫기(QCloseEvent — 앱 끝내기·로그아웃; Qt의 결과는 [아니요]지만 누르지 않음)."""
    esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    cases = [
        (lambda box: box.button(QMessageBox.Yes).click(), True),
        (lambda box: box.button(QMessageBox.No).click(), False),
        (lambda box: QApplication.sendEvent(box, esc), None),
        (lambda box: box.close(), None),
        (lambda box: box.reject(), None),
    ]
    # ⌘.(Qt는 Mac의 ⌘를 ControlModifier로): 취소 키인지는 화면 플러그인의 키 묶음이 정함 — Cocoa는 Esc·⌘., 시험의 offscreen은
    # Esc만. 이 화면에서 취소 키일 때만 (창은 Qt와 같은 QKeyEvent.matches(QKeySequence.Cancel)로 가림)
    command_period = QKeyEvent(QEvent.KeyPress, Qt.Key_Period, Qt.ControlModifier)
    if command_period.matches(QKeySequence.Cancel):
        cases.append((lambda box: QApplication.sendEvent(box, command_period), None))
    for action, expected in cases:
        answer, seen = _answer_box_with(action)
        assert answer is expected
        assert seen == [(default_app.ASK_TEXT, ["예", "아니요"], "예", default_app.TITLE)]


@REAL_BOX
def test_first_run_dismissed_ask_is_not_recorded(qapp, fake_ls, mac_app, home):
    """다른 창의 업데이트가 이 창에 닫기를 요청하면 열린 대화 상자를 reject() (player_base.close_for_update) — [예]·[아니요]가
    아니므로 기록하지 않음 (다음에 켤 때 다시 물음). 진짜 QMessageBox로."""
    seen = []

    def reject_like_close_request():
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible() and widget.isModal():
                seen.append(widget.text())
                widget.reject()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(reject_like_close_request)
    timer.start(50)
    default_app.ask_at_start(None)
    assert seen == [default_app.ASK_TEXT]
    assert not os.path.exists(default_app.prefs_path())
    assert not [c for c in fake_ls.calls if c[0] in ("register", "set")]


def test_first_run_prefs_problems_show_dialog_and_do_not_ask(qapp, fake_ls, dialogs, ask, mac_app, home):
    os.makedirs(os.path.dirname(default_app.prefs_path()))
    with open(default_app.prefs_path(), "w", encoding="utf-8") as fh:
        fh.write("{broken")
    default_app.ask_at_start(None)
    [(kind, title, text)] = dialogs.messages
    assert ask.asked == 0
    assert kind == "critical" and default_app.PREFS_READ_FAILED_TEXT in text and "prefs.json" in text
    with open(default_app.prefs_path(), encoding="utf-8") as fh:
        assert fh.read() == "{broken"  # 덮지 않음


def test_first_run_ask_only_in_built_mac_app_after_update_result(qapp, monkeypatch, mac_app):
    """빌드한 Mac 앱만, 창을 보이고 지난 업데이트의 결과 판정(handle_update_startup)이 끝난 뒤. 도우미가 켠 앱
    (--update-result)은 묻지 않음 (다음에 보통으로 켤 때)."""
    assert default_app.asks_on_start(None)
    assert not default_app.asks_on_start("token")
    monkeypatch.setattr(default_app, "IS_MAC", False)
    assert not default_app.asks_on_start(None)
    monkeypatch.setattr(default_app, "IS_MAC", True)
    monkeypatch.delattr(sys, "frozen")
    assert not default_app.asks_on_start(None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    events = []

    class FakePlayer(QWidget):
        def __init__(self, **kwargs):
            super().__init__()

        def show(self):
            events.append("show")
            super().show()

        def handle_update_startup(self, update_token):
            events.append(("update", update_token))

        def start_instance_link(self):
            events.append("instances")

        def show_user_file_problems(self):
            events.append("user_files")

        def start_shared_config_load(self):
            events.append("load")

    created = []
    monkeypatch.setattr(app_module, "VideoPlayer", lambda **kwargs: created.append(FakePlayer(**kwargs)) or created[-1])
    monkeypatch.setattr(app_module, "update_in_progress_at_start", lambda: False)
    monkeypatch.setattr(default_app, "ask_at_start", lambda parent: events.append(("ask", parent)))
    try:
        assert app_module.launch(["yesoncheck"]) == 0
        wait_until(lambda: any(isinstance(e, tuple) and e[0] == "ask" for e in events))
        assert events == ["show", ("update", None), "instances", "user_files", "load", ("ask", created[0])]

        events.clear()
        assert app_module.launch(["yesoncheck", "--update-result", "tok"]) == 0
        wait_until(lambda: "load" in events)
        for _ in range(5):
            QApplication.processEvents()
        assert events == ["show", ("update", "tok"), "instances", "user_files", "load"]
    finally:
        for player in created:
            player.close()


# ---- Help 메뉴 ----


@pytest.mark.parametrize("is_mac", [True, False])
def test_help_menu_item_per_platform(new_player, dialogs, tmp_path, monkeypatch, fake_ls, is_mac):
    """Mac만 "동영상 기본 앱으로 정하기…" (Windows 항목 "동영상 기본 앱 설정 열기…"는 file_associations)."""
    monkeypatch.setattr(default_app, "IS_MAC", is_mac)
    player = new_player(make_config(str(tmp_path), {}))
    [help_menu] = [action.menu() for action in player.menuBar().actions() if action.text() == "&Help"]
    texts = [action.text() for action in help_menu.actions()]
    assert (default_app.MENU_TEXT in texts) is is_mac
    assert default_app.MENU_TEXT == "동영상 기본 앱으로 정하기…"
    if is_mac:
        # 묻지 않고 정하기 (소스 실행이면 안내만 — 이 시험은 소스 실행)
        monkeypatch.delattr(sys, "frozen", raising=False)
        [action] = [action for action in help_menu.actions() if action.text() == default_app.MENU_TEXT]
        action.trigger()
        assert dialogs.messages == [("information", default_app.TITLE, default_app.SOURCE_RUN_TEXT)]
        assert fake_ls.calls == []


def test_platform_flag_matches_this_platform():
    assert default_app.IS_MAC is (sys.platform == "darwin")


# ---- Info.plist (spec) ----


def _spec_info_plist():
    with open(os.path.join(ROOT, "YesonCheck_Autocut.spec"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    [bundle] = [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BUNDLE"]
    [info_plist] = [kw.value for kw in bundle.keywords if kw.arg == "info_plist"]
    assert isinstance(info_plist, ast.Dict)
    return {ast.literal_eval(key): value for key, value in zip(info_plist.keys, info_plist.values)}


def test_spec_declares_video_document_types():
    """'다음으로 열기'에 늘 보이게: CFBundleDocumentTypes (Viewer, Alternate — 기본 앱을 저절로 빼앗지 않음), 종류는 VIDEO_UTIS."""
    info_plist = _spec_info_plist()
    document_types = ast.literal_eval(info_plist["CFBundleDocumentTypes"])
    assert document_types == EXPECTED_DOCUMENT_TYPES
    assert tuple(document_types[0]["LSItemContentTypes"]) == default_app.VIDEO_UTIS
    # 그대로 plist로 쓸 수 있는 값 (BUNDLE이 Info.plist에 병합)
    assert plistlib.loads(plistlib.dumps({"CFBundleDocumentTypes": document_types}))["CFBundleDocumentTypes"] == \
        EXPECTED_DOCUMENT_TYPES


# ---- 진짜 LaunchServices (읽기만) ----


@MAC_ONLY
def test_current_handler_real_api_returns_str_or_none():
    for uti in default_app.VIDEO_UTIS:
        handler = default_app.current_handler(uti)
        assert handler is None or (isinstance(handler, str) and handler), (uti, handler)
    handlers = default_app.current_handlers()  # 두 역할 (All·Viewer)
    assert set(handlers) == {(uti, role) for uti in default_app.VIDEO_UTIS for role in (ALL, VIEWER)}
    assert all(h is None or (isinstance(h, str) and h) for h in handlers.values()), handlers
    # 등록된 사본이 없는 앱 ID → 빈 목록 (kLSApplicationNotFoundErr는 오류가 아님)
    assert default_app.other_copies("com.yeson.no-such-app-for-tests", "/Applications/None.app") == []



@MAC_ONLY
def test_application_paths_real_api_reads_url_array():
    """진짜 API로 사본 목록 읽기(CFArray를 돌며 CFURL → 경로 — LSCopyApplicationURLsForBundleIdentifier, 읽기만): Finder는 어느 Mac에나
    있음 → 있는 Finder.app이 하나 이상 (등록만 남은, 떼어 낸 디스크의 경로는 있을 수 있음 — other_copies가 뺌). Apple Silicon
    CI에서도 이 ctypes 경로(arm64)를 탐."""
    found = default_app._launch_services().application_paths("com.apple.finder")
    assert all(isinstance(path, str) and path.endswith(".app") for path in found), found
    assert any(os.path.basename(path) == "Finder.app" and os.path.isdir(path) for path in found), found
