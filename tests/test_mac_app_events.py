"""yesoncheck/mac_app_events.py 시험: 파일 열기 라우터(모든 플랫폼)와 Mac 'reopen' Apple Event 처리기(Mac에서만).

- 라우터: 창을 보이기 전(ready 전)에 받은 파일(시작 인자 + 파일 열기 이벤트)은 모았다가 ready 때 첫 파일은 이 창,
  나머지는 새 창. ready 뒤의 파일 열기는 파일마다 새 창. 시작 인자와 같은 파일의 이벤트는 시작 중에만, 하나만 흡수.
- PyQt5는 QFileOpenEvent를 만들 수 없으므로("cannot be instantiated") 같은 모양(type·file·url)의 대역을 필터에 건넨다.
  설치(installEventFilter)는 대역 앱으로 확인 — 진짜 이벤트 전달은 빌드 앱에서 확인(모듈 설명).
- reopen 처리기: Mac에서 자기 자신에게 'aevt'/'rapp' Apple Event를 보내면 등록된 처리기(Objective-C 객체 → IMP)로
  동기 전달된다 — 등록·IMP·콜백을 끝까지 탄다(화면 없는 offscreen에서도).
"""

import ctypes
import os
import sys
import time
import unicodedata
from ctypes import CFUNCTYPE, c_double, c_int16, c_int32, c_uint32, c_ulong, c_void_p
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QEvent, QUrl
from PyQt5.QtWidgets import QApplication, QSplashScreen, QWidget

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import mac_app_events, new_window

MAC_ONLY = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Mac 전용: Apple Event 'reopen' 처리기는 Objective-C 런타임(NSAppleEventManager)을 씀 — 다른 플랫폼에는 없음",
)


class FileOpenEvent:
    """QFileOpenEvent 대역 (PyQt5에서는 만들 수 없음) — 필터가 쓰는 type()·file()·url()만."""

    def __init__(self, path, url=None):
        self._path = path
        self._url = QUrl.fromLocalFile(path) if url is None else QUrl(url)

    def type(self):
        return QEvent.FileOpen

    def file(self):
        return self._path

    def url(self):
        return self._url


class FakeApp:
    """install이 거는 이벤트 필터를 기록하는 QApplication 대역. deliver: Qt처럼 필터에 차례로 건넴 (하나라도 True면 처리됨)."""

    def __init__(self):
        self.filters = []

    def installEventFilter(self, obj):  # noqa: N802 (Qt 이름)
        self.filters.append(obj)

    def deliver(self, event):
        return any(f.eventFilter(self, event) for f in list(self.filters))


def process_events(rounds=5):
    """미뤄 둔 일(QTimer.singleShot(0) — 그 안에서 또 미룬 것까지)을 돌림."""
    for _ in range(rounds):
        QApplication.processEvents()
        time.sleep(0.002)


def wait_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout}초 안에 조건이 이루어지지 않았습니다")
        QApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture
def calls():
    """라우터 콜백 기록: here(이 창에 연 파일), spawned(on_open_files에 넘긴 목록), reopens, registered(reopen 처리기 등록)."""
    return SimpleNamespace(here=[], spawned=[], reopens=[], registered=[])


@pytest.fixture
def fake_register(monkeypatch, calls):
    """reopen 처리기 등록(Objective-C)을 기록으로 바꿈 — 라우터 시험이 모든 플랫폼에서 같게."""
    monkeypatch.setattr(mac_app_events, "register_reopen_handler", calls.registered.append)


def make_router(calls, argv_files, platform="darwin"):
    app = FakeApp()
    router = mac_app_events.install(app, lambda: calls.reopens.append("reopen"), calls.spawned.append, argv_files,
                                    platform=platform)
    return app, router


def test_router_before_ready_first_file_here_rest_spawned(qapp, calls, fake_register, tmp_path):
    a, b, c = (str(tmp_path / name) for name in ("a.mov", "b 2.mov", "c.mp4"))
    app, router = make_router(calls, [a])
    assert app.filters == [router]  # 파일 열기 필터는 install에서 바로 (스플래시의 processEvents 전에 와도 받게)
    assert app.deliver(FileOpenEvent(b)) and app.deliver(FileOpenEvent(c))  # 처리함 (Qt에 더 넘기지 않음)
    process_events()
    assert calls.here == [] and calls.spawned == [] and calls.registered == []  # 창을 보이기 전에는 모아만 둠

    router.ready(calls.here.append)
    assert len(calls.registered) == 1  # reopen 처리기는 ready 안에서 동기로 (AppKit finishLaunching 뒤)
    assert calls.here == [] and calls.spawned == []  # 여는 일은 Qt 루프에서 (launch가 먼저 예약한 일 뒤)
    process_events()
    assert calls.here == [a] and calls.spawned == [[b, c]] and calls.reopens == []  # 받은 차례 그대로

    # 시작 인자 없이 이벤트만 온 경우도 첫 파일은 이 창
    calls.here.clear()
    calls.spawned.clear()
    app, router = make_router(calls, [])
    app.deliver(FileOpenEvent(b))
    app.deliver(FileOpenEvent(c))
    router.ready(calls.here.append)
    process_events()
    assert calls.here == [b] and calls.spawned == [[c]]

    # 파일이 없으면 아무것도 열지 않음
    calls.here.clear()
    calls.spawned.clear()
    _, router = make_router(calls, [])
    router.ready(calls.here.append)
    process_events()
    assert calls.here == [] and calls.spawned == []


def test_router_after_ready_spawns_each(qapp, calls, fake_register, tmp_path):
    a, b, c = (str(tmp_path / name) for name in ("a.mov", "b.mov", "c.mp4"))
    app, router = make_router(calls, [a])
    router.ready(calls.here.append)
    process_events()
    assert calls.here == [a]

    # 켜진 뒤 연 파일은 파일마다 새 창 — 이 창에 열린 영상을 다시 열어도 새 창 (설계 3-2 "무조건 새 창")
    for path in (b, c, a):
        assert app.deliver(FileOpenEvent(path))
    assert calls.spawned == []  # 이벤트 처리 안에서 띄우지 않음 (Qt 루프로 미룸)
    process_events()
    assert calls.spawned == [[b], [c], [a]] and calls.here == [a] and calls.reopens == []

    # 다른 이벤트는 건드리지 않고 그대로 넘김
    assert router.eventFilter(app, QEvent(QEvent.User)) is False
    assert len(calls.registered) == 1


def test_router_dedups_argv_file(qapp, calls, fake_register, tmp_path):
    """argv(argv_emulation)와 같은 파일의 이벤트는 시작 중에만, 시작 인자 하나가 이벤트 하나만 흡수.
    비교는 링크를 푼 경로의 NFC — Finder는 NFD·링크 푼 경로(/tmp → /private/tmp)를 보냄."""
    name = "장면 #1 'q'.mov"
    first = os.path.join(str(tmp_path), unicodedata.normalize("NFC", name))
    first_as_event = os.path.join(str(tmp_path), "sub", "..", unicodedata.normalize("NFD", name))
    second = str(tmp_path / "b.mov")
    assert first != first_as_event
    if sys.platform != "win32":  # (Windows는 링크를 만들 권한이 없을 수 있음)
        (tmp_path / "real").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
        linked = str(tmp_path / "link" / "c.mov")
        real = str(tmp_path / "real" / "c.mov")
    else:
        linked = real = str(tmp_path / "c.mov")

    app, router = make_router(calls, [first, second, linked])
    for path in (first_as_event, real, second):  # 셋 다 시작 인자와 같은 파일 → 하나씩 흡수
        assert app.deliver(FileOpenEvent(path))
    assert app.deliver(FileOpenEvent(first_as_event))  # 같은 파일의 두 번째 이벤트는 흡수하지 않음 → 새 창
    router.ready(calls.here.append)
    process_events()
    assert calls.here == [first] and calls.spawned == [[second, linked, first_as_event]]

    # ready 뒤에는 시작 인자와 같은 파일이라도 흡수하지 않음
    app.deliver(FileOpenEvent(first))
    process_events()
    assert calls.spawned == [[second, linked, first_as_event], [first]]


def send_reopen_to_self():
    """자기 프로세스에 'aevt'/'rapp'를 보냄 (kAENoReply) — NSAppleEventManager가 등록된 처리기로 동기 전달.

    objc_msgSend는 호출 모양마다 인자·반환 형을 정한 함수 포인터로 (arm64: 가변 인자로 부르면 인자가 깨짐)."""
    rt = mac_app_events._objc_runtime()
    send_id = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(rt.msg_send)
    # +appleEventWithEventClass:(AEEventClass)eventID:(AEEventID)targetDescriptor:(id)
    #  returnID:(AEReturnID)transactionID:(AETransactionID)
    make = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_uint32, c_uint32, c_void_p, c_int16, c_int32)(rt.msg_send)
    # -sendEventWithOptions:(NSAppleEventSendOptions)timeout:(NSTimeInterval)error:(NSError **)  (macOS 10.11+)
    send = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_ulong, c_double, c_void_p)(rt.msg_send)
    descriptor = rt.cls(b"NSAppleEventDescriptor")
    target = send_id(descriptor, rt.sel(b"currentProcessDescriptor"))
    event = make(descriptor, rt.sel(b"appleEventWithEventClass:eventID:targetDescriptor:returnID:transactionID:"),
                 mac_app_events.K_CORE_EVENT_CLASS, mac_app_events.K_AE_REOPEN_APPLICATION, target,
                 -1, 0)  # kAutoGenerateReturnID, kAnyTransactionID
    assert event, "rapp Apple Event를 만들지 못했습니다"
    error = c_void_p()
    reply = send(event, rt.sel(b"sendEventWithOptions:timeout:error:"), 0x1, -1.0, ctypes.byref(error))  # kAENoReply
    assert reply and not error.value, f"rapp를 보내지 못했습니다 (reply {reply}, error {error.value})"


@MAC_ONLY
def test_reopen_handler_dispatch_calls_callback(qapp, calls):
    """진짜 처리기: ready가 등록 → rapp → Objective-C 처리기 객체의 IMP → (Qt 루프에서) on_reopen 한 번."""
    app, router = make_router(calls, [])
    router.ready(calls.here.append)
    send_reopen_to_self()
    assert calls.reopens == []  # IMP는 일을 Qt 루프로 미루고 바로 돌아옴 (AppKit의 Apple Event 처리를 막지 않게)
    process_events()
    assert calls.reopens == ["reopen"] and calls.spawned == [] and calls.here == []

    send_reopen_to_self()
    send_reopen_to_self()
    process_events()
    assert calls.reopens == ["reopen"] * 3  # Apple Event 하나에 정확히 한 번

    # 다시 등록하면 콜백만 바뀜 (Objective-C 처리기 객체·클래스는 프로세스에 하나)
    other = []
    mac_app_events.register_reopen_handler(lambda: other.append("other"))
    send_reopen_to_self()
    process_events()
    assert other == ["other"] and calls.reopens == ["reopen"] * 3


@MAC_ONLY
def test_reopen_callback_failure_shows_error_window(qapp, dialogs, capsys):
    """reopen 콜백(새 창 띄우기)이 실패하면 기록과 오류 창에 트레이스백 — 앱은 그대로, 다음 reopen도 처리."""
    attempts = []

    def failing_spawn():
        attempts.append(1)
        raise RuntimeError("새 YesonCheck 창을 띄우지 못했습니다 — open이 종료 코드 1로 끝났습니다.\n"
                           "명령: /usr/bin/open -n /Applications/YesonCheck_Autocut.app\n출력: (시험)")

    mac_app_events.register_reopen_handler(failing_spawn)
    send_reopen_to_self()
    wait_until(lambda: dialogs.criticals)
    [text] = dialogs.criticals
    assert text.startswith(mac_app_events.REOPEN_FAILED_TEXT)
    assert "Traceback" in text and "명령: /usr/bin/open -n" in text and "출력: (시험)" in text
    assert "명령: /usr/bin/open -n" in capsys.readouterr().err  # 기록(빌드 앱은 stderr가 기록 파일)에도
    send_reopen_to_self()
    wait_until(lambda: len(dialogs.criticals) == 2)
    assert len(attempts) == 2


def test_install_off_mac_routes_files_only(qapp, calls, fake_register, tmp_path):
    """Mac이 아니면 이벤트 필터·Apple Event 없이 받은 파일만 나눔 (Windows에서 여러 파일을 한 명령으로 받은 경우)."""
    a, b, c = (str(tmp_path / name) for name in ("a.mov", "b.mov", "c.mp4"))
    app, router = make_router(calls, [a, b, c], platform="win32")
    assert app.filters == []
    router.ready(calls.here.append)
    process_events()
    assert calls.here == [a] and calls.spawned == [[b, c]] and calls.registered == []


def test_router_open_failure_shows_error_window_and_keeps_routing(qapp, calls, fake_register, dialogs, tmp_path,
                                                                  capsys):
    """새 창 띄우기 실패 → 기록과 오류 창(명령·출력·트레이스백), 이 창은 그대로 — 다음 파일 열기도 처리."""
    a, b = str(tmp_path / "a.mov"), str(tmp_path / "b.mov")
    attempts = []

    def failing_spawn(files):
        attempts.append(files)
        raise RuntimeError("새 YesonCheck 창을 띄우지 못했습니다 — open이 종료 코드 1로 끝났습니다.\n"
                           f"명령: /usr/bin/open -n /Applications/YesonCheck_Autocut.app --args {files[0]}\n출력: (시험)")

    app = FakeApp()
    router = mac_app_events.install(app, calls.reopens.append, failing_spawn, [], platform="darwin")
    router.ready(calls.here.append)
    app.deliver(FileOpenEvent(a))
    wait_until(lambda: dialogs.criticals)
    [text] = dialogs.criticals
    assert a in text and "Traceback" in text and f"--args {a}" in text and "출력: (시험)" in text
    assert f"--args {a}" in capsys.readouterr().err
    app.deliver(FileOpenEvent(b))
    wait_until(lambda: len(dialogs.criticals) == 2)
    assert attempts == [[a], [b]]


def test_router_file_open_without_path_shows_error_window(qapp, calls, fake_register, dialogs):
    app, router = make_router(calls, [])
    router.ready(calls.here.append)
    assert app.deliver(FileOpenEvent("", url="yesoncheck://x"))
    wait_until(lambda: dialogs.criticals)
    assert "yesoncheck://x" in dialogs.criticals[0] and "Traceback" in dialogs.criticals[0]
    assert calls.spawned == [] and calls.here == []


def test_ready_reports_reopen_registration_failure_and_still_opens_files(qapp, calls, dialogs, monkeypatch,
                                                                       tmp_path):
    """reopen 처리기를 등록하지 못해도(예상 못 한 오류) 창은 쓰게: 오류 창 + 받은 파일은 그대로 엶."""
    a = str(tmp_path / "a.mov")

    def broken(callback):
        raise RuntimeError("objc 시험 실패")

    monkeypatch.setattr(mac_app_events, "register_reopen_handler", broken)
    _, router = make_router(calls, [a])
    router.ready(calls.here.append)
    wait_until(lambda: dialogs.criticals and calls.here)
    assert calls.here == [a]
    [text] = dialogs.criticals
    assert text.startswith(mac_app_events.REGISTER_FAILED_TEXT) and "RuntimeError: objc 시험 실패" in text


def test_ready_twice_is_an_error(qapp, calls, fake_register):
    _, router = make_router(calls, [])
    router.ready(calls.here.append)
    with pytest.raises(RuntimeError):
        router.ready(calls.here.append)


# ---- app.launch: install → (업데이트 확인·스플래시) → 창 → ready ----


class LaunchPlayer(QWidget):
    """진짜 창 대신 — launch가 부르는 것만 기록."""

    events = []

    def __init__(self, **kwargs):
        super().__init__()

    def show(self):
        LaunchPlayer.events.append("show")
        super().show()

    def handle_update_startup(self, update_token):
        LaunchPlayer.events.append("update")

    def start_instance_link(self):
        LaunchPlayer.events.append("instances")

    def show_user_file_problems(self):
        LaunchPlayer.events.append("user_files")

    def start_shared_config_load(self):
        LaunchPlayer.events.append("load")

    def open_file(self, video_type, file_path):
        LaunchPlayer.events.append(("open", video_type, file_path))


@pytest.fixture
def launch_env(monkeypatch):
    """launch를 가짜 창으로: 차례(events)·새 창 띄우기(spawned)·install에 넘긴 콜백(installed)을 기록."""
    from yesoncheck import app as app_module

    events = LaunchPlayer.events = []
    created = []
    spawned = []
    installed = []
    real_install = mac_app_events.install

    def recording_install(app, on_reopen, on_open_files, argv_files, **kwargs):
        events.append("install")
        installed.append(SimpleNamespace(on_reopen=on_reopen, on_open_files=on_open_files, argv_files=argv_files))
        router = real_install(app, on_reopen, on_open_files, argv_files, **kwargs)
        real_ready = router.ready

        def recording_ready(open_here):
            events.append("ready")
            real_ready(open_here)

        router.ready = recording_ready
        return router

    class RecordingSplash(QSplashScreen):
        def __init__(self, *args, **kwargs):
            events.append("splash")
            super().__init__(*args, **kwargs)

    def update_check():
        events.append("update_check")
        return False

    monkeypatch.setattr(mac_app_events, "install", recording_install)
    monkeypatch.setattr(mac_app_events, "register_reopen_handler", lambda callback: events.append("register"))
    monkeypatch.setattr(app_module, "QSplashScreen", RecordingSplash)
    monkeypatch.setattr(app_module, "update_in_progress_at_start", update_check)
    monkeypatch.setattr(app_module, "VideoPlayer",
                        lambda **kwargs: created.append(LaunchPlayer(**kwargs)) or created[-1])
    monkeypatch.setattr(new_window, "spawn", spawned.append)
    yield SimpleNamespace(app=app_module, events=events, spawned=spawned, installed=installed, created=created)
    for player in created:
        player.close()


def test_launch_installs_router_first_and_readies_after_window_is_shown(qapp, launch_env, tmp_path):
    """파일 열기 필터는 QApplication 바로 다음(업데이트 확인·스플래시의 processEvents보다 먼저), ready는 창을 보인 뒤 —
    Mac이면 그 안에서 reopen 처리기 등록. 첫 파일은 창을 보인 뒤의 다른 일 다음에 이 창 A에."""
    video = tmp_path / "a.mov"
    video.write_bytes(b"x")
    assert launch_env.app.launch(["yesoncheck", str(video)]) == 0
    events = launch_env.events
    registered = ["register"] if sys.platform == "darwin" else []
    assert events == ["install", "update_check", "splash", "show", "ready", *registered]
    wait_until(lambda: ("open", "A", str(video)) in events)
    assert events[-5:] == ["update", "instances", "user_files", "load", ("open", "A", str(video))]
    assert launch_env.installed[0].argv_files == [str(video)] and launch_env.spawned == []


def test_launch_opens_first_file_here_and_spawns_the_rest(qapp, launch_env, tmp_path):
    """여러 파일을 한 명령으로 받으면(Windows 연결 프로그램·Finder 여러 개) 첫 파일은 이 창 A, 나머지는 새 창들."""
    paths = []
    for name in ("a.mov", "b 2.mov", "장면 #3.mp4"):
        (tmp_path / name).write_bytes(b"x")
        paths.append(str(tmp_path / name))
    assert launch_env.app.launch(["yesoncheck", *paths]) == 0
    wait_until(lambda: launch_env.spawned)
    process_events()
    assert ("open", "A", paths[0]) in launch_env.events
    assert [e for e in launch_env.events if isinstance(e, tuple)] == [("open", "A", paths[0])]
    assert launch_env.spawned == [paths[1:]]


def test_launch_reopen_and_later_files_spawn_new_windows(qapp, launch_env):
    """install에 넘기는 콜백: reopen(Dock 클릭·앱 다시 열기) → 파일 없는 새 창, 켜진 뒤 연 파일 → 그 파일의 새 창."""
    assert launch_env.app.launch(["yesoncheck"]) == 0
    [installed] = launch_env.installed
    installed.on_reopen()
    installed.on_open_files(["/Volumes/USA_DB/FL_901 컷/장면 #3.mov"])
    assert launch_env.spawned == [[], ["/Volumes/USA_DB/FL_901 컷/장면 #3.mov"]]


def test_launch_spawn_failure_shows_error_and_keeps_window(qapp, launch_env, dialogs, monkeypatch, tmp_path):
    """나머지 파일의 새 창을 띄우지 못하면 오류 창(명령·출력·트레이스백), 이 창과 첫 파일은 그대로."""
    paths = []
    for name in ("a.mov", "b.mov"):
        (tmp_path / name).write_bytes(b"x")
        paths.append(str(tmp_path / name))

    def failing_spawn(files):
        raise RuntimeError("새 YesonCheck 창을 띄우지 못했습니다 — open이 종료 코드 1로 끝났습니다.\n"
                           f"명령: /usr/bin/open -n /Applications/YesonCheck_Autocut.app --args {files[0]}\n출력: (시험)")

    monkeypatch.setattr(new_window, "spawn", failing_spawn)
    assert launch_env.app.launch(["yesoncheck", *paths]) == 0
    wait_until(lambda: dialogs.criticals)
    [text] = dialogs.criticals
    assert paths[1] in text and "Traceback" in text and "명령: /usr/bin/open -n" in text
    [player] = launch_env.created
    assert player.isVisible() and ("open", "A", paths[0]) in launch_env.events


# ---- 받은 첫 파일 열기 (app.open_startup_file) ----


def test_launch_opens_missing_startup_file_through_open_file(qapp, launch_env, tmp_path):
    """받은 파일이 그대로는 없어도 open_file로 넘김 — 열지 못하면 open_file이 무엇을 왜 못 열었는지 오류 창 (예전에는 기록에
    한 줄만 남고 빈 창만 떴음 — 설계 3-2 "영상을 열지 못하면 오류 창")."""
    missing = str(tmp_path / "없는 폴더" / "장면 #3.mov")
    assert launch_env.app.launch(["yesoncheck", missing]) == 0
    wait_until(lambda: ("open", "A", missing) in launch_env.events)


def test_open_startup_file_uses_path_with_other_unicode_form(qapp, monkeypatch, tmp_path):
    """받은 경로가 그대로는 없고 이름의 정규화(NFC·NFD)만 다른 실제 경로가 있으면(NFS 공유) 그 경로로 엶 (paths.find_unicode_variant)."""
    from yesoncheck import app as app_module, paths

    handed = unicodedata.normalize("NFD", "/nas/usadata9/FL_901 컷/장면.mov")
    real = unicodedata.normalize("NFC", "/nas/usadata9/FL_901 컷/") + unicodedata.normalize("NFD", "장면.mov")
    asked = []

    def fake_find(path):
        asked.append(path)
        return real

    monkeypatch.setattr(paths, "find_unicode_variant", fake_find)
    opened = []
    player = SimpleNamespace(open_file=lambda video_type, path: opened.append((video_type, path)))
    app_module.open_startup_file(player, handed)
    assert asked == [handed] and opened == [("A", real)]

    # 찾지 못하면 받은 그대로 (open_file이 오류 창)
    monkeypatch.setattr(paths, "find_unicode_variant", lambda path: None)
    opened.clear()
    app_module.open_startup_file(player, handed)
    assert opened == [("A", handed)]


def test_open_startup_file_missing_video_shows_error_window_naming_it(new_player, dialogs, tmp_path):
    """진짜 창: 없는 영상을 받으면 그 경로가 든 오류 창 (open_file — 없음·확인 못 함을 가려서), 창은 그대로."""
    from yesoncheck import app as app_module

    player = new_player(make_config(str(tmp_path), {}))
    missing = str(tmp_path / "없는 폴더" / "장면 #3.mov")
    app_module.open_startup_file(player, missing)
    [(kind, title, text)] = dialogs.messages
    assert kind in ("critical", "warning") and missing in text
    assert player.filename_a in (None, "")
