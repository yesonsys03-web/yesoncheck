"""창이 바로 보이게 (Windows 사용자 보고 2026-10-14): 소리 재생기는 처음 쓸 때 만들고, 공유 설정은 창을 보인 뒤
백그라운드 스레드에서 읽는다. Mac·Windows 공통 (Windows 동작과 네트워크 드라이브는 test_path_map_auto_ui의 win으로 흉내 냄).
"""

import json
import os
import threading
import time

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QTimer
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtWidgets import QApplication, QSplashScreen, QWidget

from yesoncheck import path_map_setup, paths, shared_config
from yesoncheck.path_map_setup import Share
from tests.conftest import write_test_video
from tests.test_path_map_auto_ui import NAS, WORK, path_map_criticals, win  # noqa: F401 (win: fixture)
from tests.test_work_paths_ui import combo_items, make_config, new_player  # noqa: F401 (new_player: fixture)

LOADING_NOTICE = "공유 설정을 불러오는 중입니다. 잠시 뒤 다시 시도하세요."


def wait_until(condition, timeout=10.0):
    """이벤트를 처리하며 condition()이 참이 될 때까지 기다림 (시간 초과면 실패)."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout}초 안에 조건이 이루어지지 않았습니다")
        QApplication.processEvents()
        time.sleep(0.005)


def loading_player(win, monkeypatch, config_dir=None):
    """launch처럼 공유 설정 없이 만든 창 (win.players에 넣어 시험 끝에 닫힘)."""
    if config_dir is None:
        monkeypatch.delenv("YESONCHECK_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config_dir)
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer(load_shared_config=False)
    win.players.append(player)
    return player


def snapshot(player, problem_text=True):
    """공유 설정 상태 (동기 setup_shared_config 결과와 비교용).

    problem_text=False: 문제는 있는지만 비교 (가짜 UNC를 실제로 열어 본 오류 문구는 Windows에서 시도마다 다를 수 있음).
    """
    active = paths._active_map

    def problem(text):
        return text if problem_text else bool(text)

    return {
        "work_paths": dict(player.work_paths),
        "shared_config_problem": problem(player.shared_config_problem),
        "path_map_problem": problem(player.path_map_problem),
        "config_dir": player.work_paths_config_dir,
        "work_paths_file": player.work_paths_file,
        "password_file": player.work_paths_password_file,
        "candidates": list(player.config_dir_candidates),
        "search_failed": player.config_dir_search_failed,
        "active_map": None if active is None else active.shares,
        "combo": combo_items(player.workComboBox),
        "title": player.windowTitle(),
    }


def blocking(func):
    """func를 부르기 전에 release를 기다리는 가짜 → (가짜, entered, release). 시험이 끝나면 반드시 release.set()."""
    entered, release = threading.Event(), threading.Event()

    def fake(*args, **kwargs):
        entered.set()
        if not release.wait(10):
            raise AssertionError("시험이 release를 보내지 않았습니다")
        return func(*args, **kwargs)

    return fake, entered, release


def test_loading_player_reads_nothing_and_creates_no_media_player(win, dialogs, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("창을 만들 때 공유 설정·NAS에 접근했습니다")

    for owner, name in [
        (path_map_setup, "connected_shares"), (path_map_setup, "find_config_dirs"),
        (shared_config, "configured_config_dir"), (shared_config, "read_work_paths"),
        (shared_config, "load_local_settings"), (shared_config, "is_valid_config_dir"),
    ]:
        monkeypatch.setattr(owner, name, forbidden)
    monkeypatch.setattr(paths.PathMap, "load", classmethod(forbidden))

    player = loading_player(win, monkeypatch)
    assert player.shared_config_loading is True
    assert player.work_paths == {}
    assert player.shared_config_problem is None and player.path_map_problem is None
    assert player.work_paths_config_dir is None and player.work_paths_file is None
    assert player.config_dir_candidates == [] and player.config_dir_search_failed is False
    assert combo_items(player.workComboBox) == ["작품선택"]
    assert player.windowTitle() == "Yeson Checker — 공유 설정 불러오는 중…"
    assert player.findChildren(QMediaPlayer) == []

    # 볼륨은 재생기를 만들기 전에도 기억했다가 만들 때 적용 (만들지 않고 읽기)
    player.setVolume(30)
    assert player.media_volume() == 30
    assert player.findChildren(QMediaPlayer) == []

    media = player.mediaPlayer  # 처음 쓸 때 하나만 만듦
    assert isinstance(media, QMediaPlayer)
    assert player.mediaPlayer is media
    assert player.findChildren(QMediaPlayer) == [media]
    assert media.volume() == 30

    other = loading_player(win, monkeypatch)
    other.stop_video()  # 소리를 연 적이 없으면 정지도 재생기를 만들지 않음
    other.close()
    assert other.findChildren(QMediaPlayer) == []


def test_opening_a_video_creates_the_media_player(new_player, dialogs, tmp_path):
    """처음으로 재생기를 만드는 곳은 영상 A를 열 때(setMedia)."""
    player = new_player(make_config(str(tmp_path), {}))
    assert player.findChildren(QMediaPlayer) == []
    video = write_test_video(os.path.join(str(tmp_path), "v", "a.mp4"))
    player.open_file("A", video)
    assert len(player.findChildren(QMediaPlayer)) == 1
    opened = player.mediaPlayer.media().canonicalUrl().toLocalFile()  # Windows에서는 / 구분자로 돌려줌
    assert os.path.normcase(os.path.normpath(opened)) == os.path.normcase(os.path.normpath(video))


def test_background_load_matches_sync_and_offers_auto_setup(win, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), WORK)  # path_map.json 없음 → 시작하면 변환표 자동 설정을 제안해야 함
    win.accept = False  # 제안 창은 띄우되 거절 → 상태가 그대로라 동기 결과와 비교할 수 있음
    expected = snapshot(win.player(config))
    paths.activate(None)

    player = loading_player(win, monkeypatch, config)
    player.start_shared_config_load()
    assert player.windowTitle() == "Yeson Checker — 공유 설정 불러오는 중…"
    wait_until(lambda: not player.shared_config_loading)
    assert snapshot(player) == expected
    assert len(win.shown) == 1  # resolve가 실행됨
    assert len(path_map_criticals(dialogs)) == 1


def test_background_load_with_preferred_alias_matches_sync(win, dialogs, tmp_path, monkeypatch):
    """변환표의 첫 주소가 이 PC에 연결된 주소가 아님 → 연결된 주소(NAS)를 앞으로 옮긴 변환표가 활성화돼야 함."""
    old = "\\\\localhost\\yc_fake_old"
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [old, NAS]}]})
    expected = snapshot(win.player(config))
    assert expected["active_map"][0][1][0] == ["localhost", "yc_fake"]
    paths.activate(None)

    player = loading_player(win, monkeypatch, config)
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    assert snapshot(player) == expected
    assert paths.to_native("/Volumes/yc/작품") == NAS + "\\작품"
    assert win.shown == [] and dialogs.messages == []  # 작품이 열림 → 아무 창도 없음


def test_background_load_auto_finds_config_dir_like_sync(win, dialogs, tmp_path, monkeypatch):
    share = "\\\\localhost\\yc_fake_cfg"
    win.shares = [Share(share, ["U:"])]
    target = f"{share}\\test_jn\\.yesoncheck"
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() == f"{target}\\work_paths.json".casefold())
    settings = os.path.join(str(tmp_path / "appdata"), "YesonCheck", "settings.json")

    player = loading_player(win, monkeypatch)
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    with open(settings, encoding="utf-8") as fh:
        assert json.load(fh) == {"config_dir": target}  # 백그라운드에서 PC별 설정에 저장
    got = snapshot(player, problem_text=False)
    assert got["config_dir"] == target

    os.remove(settings)
    paths.activate(None)
    assert snapshot(win.player(), problem_text=False) == got


def test_startup_works_check_runs_off_the_gui_thread(win, dialogs, tmp_path, monkeypatch):
    """시작할 때 '열리지 않는 작품' 확인(NAS 열기)은 백그라운드에서 하고, resolve는 그 목록으로 자동 설정을 제안."""
    old = "\\\\localhost\\yc_fake_old"
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [old]}]})
    win.accept = False
    probes = []
    fake_is_dir = path_map_setup._default_is_dir

    def is_dir(path):
        probes.append((path.casefold(), threading.current_thread() is threading.main_thread()))
        return fake_is_dir(path)

    monkeypatch.setattr(path_map_setup, "_default_is_dir", is_dir)
    player = loading_player(win, monkeypatch, config)
    gui_checks = []
    player._works_not_opening = lambda: gui_checks.append(1) or []
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    assert gui_checks == []  # GUI 스레드에서 다시 확인하지 않음
    assert (old.casefold(), False) in probes  # 공유 루트는 백그라운드에서 열어 봄
    assert len(win.shown) == 1  # 미리 계산한 목록(열리지 않는 작품 있음)으로 자동 설정 제안


def test_start_returns_while_gather_is_blocked(win, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]})
    fake, entered, release = blocking(path_map_setup.connected_shares)
    monkeypatch.setattr(path_map_setup, "connected_shares", fake)
    player = loading_player(win, monkeypatch, config)
    try:
        started = time.monotonic()
        player.start_shared_config_load()
        returned_after = time.monotonic() - started
        assert entered.wait(5), "백그라운드 읽기가 시작되지 않았습니다"
        assert not release.is_set() and returned_after < 2.0  # 읽기가 막혀 있는 동안 이미 돌아옴

        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        wait_until(lambda: len(ticks) >= 5)  # GUI 이벤트는 계속 처리됨
        timer.stop()
        assert player.shared_config_loading and player.work_paths == {}

        # 불러오는 동안: 작품 경로 관리·공유 설정 폴더 변경은 안내만 (입력 창이 열리면 win의 getText가 실패시킴)
        player.manage_work_paths()
        assert player.choose_shared_config_dir() is False
        assert [m for m in dialogs.messages if m[0] == "information" and m[2] == LOADING_NOTICE] == [
            ("information", "공유 설정", LOADING_NOTICE)
        ] * 2
    finally:
        release.set()
    wait_until(lambda: not player.shared_config_loading)
    assert player.work_paths == WORK
    assert player.shared_config_problem is None and player.path_map_problem is None
    assert combo_items(player.workComboBox) == ["작품선택", "W"]
    assert player.windowTitle() == "Yeson Checker"
    assert paths.to_native("/Volumes/yc/작품") == NAS + "\\작품"
    assert dialogs.errors() == []


def test_close_while_loading_ignores_late_result(win, dialogs, tmp_path, monkeypatch, capsys):
    from yesoncheck.player_base import VideoPlayerBase
    from yesoncheck.player_sidebar import SharedConfigLoad

    config = make_config(str(tmp_path), WORK)  # 결과를 넣었다면 자동 설정 제안 창이 떴을 것
    fake, entered, release = blocking(shared_config.read_work_paths)
    monkeypatch.setattr(shared_config, "read_work_paths", fake)
    monkeypatch.setattr(VideoPlayerBase, "SHARED_CONFIG_CLOSE_WAIT_MS", 100)
    player = loading_player(win, monkeypatch, config)
    player.show()
    visible_while_waiting = []
    original_wait = player.wait_for_shared_config_load

    def recording_wait(timeout_ms):
        visible_while_waiting.append(player.isVisible())
        return original_wait(timeout_ms)

    player.wait_for_shared_config_load = recording_wait
    try:
        player.start_shared_config_load()
        assert entered.wait(5)
        load = player._shared_config_load
        started = time.monotonic()
        player.close()
        assert time.monotonic() - started < 5  # 기다림은 정해진 시간까지만
        assert visible_while_waiting == [False]  # 기다리기 전에 창을 숨김 (보이는 창이 멈춰 있지 않게)
        assert "끝나지 않았습니다" in capsys.readouterr().out
        assert load.isRunning()
    finally:
        release.set()
    wait_until(load.isFinished)
    wait_until(lambda: load not in SharedConfigLoad._running)  # finished 처리됨 (loaded는 그 전에 처리됨)
    assert "결과를 버림" in capsys.readouterr().out
    assert player.shared_config_loading is True and player.work_paths == {}
    assert player.work_paths_config_dir is None
    assert paths._active_map is None
    assert win.shown == [] and dialogs.messages == []


def test_window_deleted_while_loading_keeps_thread_alive(win, dialogs, tmp_path, monkeypatch):
    """닫힌 창이 지워져도 실행 중인 QThread는 파괴되지 않음 (파괴되면 'QThread: Destroyed while thread is still
    running'으로 프로세스가 중단됨 — 이 시험이 끝까지 돌면 통과)."""
    from yesoncheck.main_window import VideoPlayer
    from yesoncheck.player_base import VideoPlayerBase
    from yesoncheck.player_sidebar import SharedConfigLoad

    config = make_config(str(tmp_path), WORK)
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config)
    fake, entered, release = blocking(shared_config.read_work_paths)
    monkeypatch.setattr(shared_config, "read_work_paths", fake)
    monkeypatch.setattr(VideoPlayerBase, "SHARED_CONFIG_CLOSE_WAIT_MS", 50)
    player = VideoPlayer(load_shared_config=False)  # win.players에 넣지 않음 (아래에서 지움)
    try:
        player.start_shared_config_load()
        assert entered.wait(5)
        load = player._shared_config_load
        assert load.parent() is None  # 창의 자식이 아님 → 창과 함께 파괴되지 않음
        player.close()
        player.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert sip.isdeleted(player)
        assert load.isRunning() and load in SharedConfigLoad._running
    finally:
        release.set()
    wait_until(load.isFinished)
    wait_until(lambda: load not in SharedConfigLoad._running)
    assert paths._active_map is None and dialogs.messages == []


def test_unexpected_gather_error_becomes_shared_config_problem(win, dialogs, tmp_path, monkeypatch, capsys):
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]})

    def broken(remote_of_drive=None):
        raise OSError("드라이브 목록을 읽다 실패 (가짜 재현)")

    monkeypatch.setattr(path_map_setup, "connected_shares", broken)
    player = loading_player(win, monkeypatch, config)
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    assert "드라이브 목록을 읽다 실패 (가짜 재현)" in player.shared_config_problem
    assert "Traceback" in player.shared_config_problem
    assert "드라이브 목록을 읽다 실패 (가짜 재현)" in capsys.readouterr().err  # 로그에도 스택 트레이스째
    assert "공유 설정 오류" in player.windowTitle()
    # resolve가 알림: 설정 폴더를 고르게 하고(취소) 공유 설정 오류 창
    assert any(kind == "critical" and title == "공유 설정 오류" and "가짜 재현" in text
               for kind, title, text in dialogs.messages)


def test_launch_shows_window_then_loads_shared_config(qapp, monkeypatch):
    from yesoncheck import app as app_module

    events = []

    class FakePlayer(QWidget):
        def __init__(self, **kwargs):
            super().__init__()
            events.append(("init", kwargs))

        def show(self):
            events.append("show")
            super().show()

        def start_shared_config_load(self):
            events.append("load")

    created = []
    monkeypatch.setattr(app_module, "VideoPlayer", lambda **kwargs: created.append(FakePlayer(**kwargs)) or created[-1])
    assert app_module.launch(["yesoncheck"]) == 0
    assert events == [("init", {"load_shared_config": False}), "show"]  # 불러오기는 창을 보인 뒤 이벤트 루프에서
    wait_until(lambda: "load" in events)
    assert events[-1] == "load"
    created[0].close()


def test_launch_opens_command_line_file_after_window_is_shown(qapp, monkeypatch, tmp_path, capsys):
    """명령줄로 받은 파일은 창을 보이고 스플래시를 닫은 뒤에 엶 (여는 중 소리 재생기를 만들고, 오류 창이 가려지지 않게)."""
    from yesoncheck import app as app_module

    video = tmp_path / "a.mov"
    video.write_bytes(b"x")
    events = []

    class FakePlayer(QWidget):
        def __init__(self, **kwargs):
            super().__init__()

        def show(self):
            events.append("show")
            super().show()

        def start_shared_config_load(self):
            events.append("load")

        def open_file(self, video_type, file_path):
            events.append(("open", video_type, file_path))

    created = []
    monkeypatch.setattr(app_module, "VideoPlayer", lambda **kwargs: created.append(FakePlayer(**kwargs)) or created[-1])
    try:
        assert app_module.launch(["yesoncheck", str(video)]) == 0
        assert events == ["show"]  # launch 안에서는 열지 않음
        wait_until(lambda: len(events) == 3)
        assert events == ["show", "load", ("open", "A", str(video))]

        events.clear()
        missing = str(tmp_path / "없음.mov")
        assert app_module.launch(["yesoncheck", missing]) == 0
        wait_until(lambda: "load" in events)
        QApplication.processEvents()
        assert events == ["show", "load"]
        assert f"File does not exist: {missing}" in capsys.readouterr().out
    finally:
        for player in created:
            player.close()


def test_launch_closes_splash_when_window_fails(qapp, monkeypatch):
    """창을 만들다 실패하면 오류 창이 스플래시(항상 위)에 가려지지 않도록 스플래시를 먼저 닫음."""
    from yesoncheck import app as app_module

    splashes = []

    class RecordingSplash(QSplashScreen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            splashes.append(self)

    def failing_player(**kwargs):
        assert splashes[0].isVisible()
        raise RuntimeError("창 생성 실패 (시험)")

    monkeypatch.setattr(app_module, "QSplashScreen", RecordingSplash)
    monkeypatch.setattr(app_module, "VideoPlayer", failing_player)
    with pytest.raises(RuntimeError, match="창 생성 실패"):
        app_module.launch(["yesoncheck"])
    assert not splashes[0].isVisible()


def test_smoke_open_like_launch(qapp, dialogs, work_area, monkeypatch):
    """실행 시험(자동 연결)이 쓰는 'launch처럼 열기': 창을 보이고 공유 설정을 백그라운드로 불러와 기다림.

    (Windows CI: 실제 시험 공유와 변환표로 — 작품이 열리므로 아무 창도 뜨지 않아야 함)
    """
    from yesoncheck.main_window import VideoPlayer
    from yesoncheck.smoke_test import open_like_launch

    config = make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map)
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config)
    player, shown_s, load_s = open_like_launch(VideoPlayer, qapp, timeout_s=60)
    try:
        assert player.isVisible() and not player.shared_config_loading
        assert player.work_paths == {"SMOKE": work_area.stored}
        assert combo_items(player.workComboBox) == ["작품선택", "SMOKE"]
        assert 0 <= shown_s and 0 <= load_s
        assert dialogs.errors() == []
    finally:
        player.close()
        paths.activate(None)


def test_media_player_creation_shows_wait_cursor(win, dialogs, monkeypatch):
    """처음 쓸 때 재생기를 만드는 동안(Windows에서 수 초) 대기 커서. 만들다 실패해도 커서는 되돌리고 오류는 그대로."""
    from PyQt5.QtCore import Qt

    from yesoncheck import player_base

    real = player_base.QMediaPlayer
    cursors = []

    def recording(parent):
        cursor = QApplication.overrideCursor()
        cursors.append(None if cursor is None else cursor.shape())
        return real(parent)

    monkeypatch.setattr(player_base, "QMediaPlayer", recording)
    player = loading_player(win, monkeypatch)
    assert QApplication.overrideCursor() is None
    player.mediaPlayer
    assert cursors == [Qt.WaitCursor]
    assert QApplication.overrideCursor() is None

    def failing(parent):
        raise RuntimeError("재생기 생성 실패 (시험)")

    monkeypatch.setattr(player_base, "QMediaPlayer", failing)
    other = loading_player(win, monkeypatch)
    with pytest.raises(RuntimeError, match="재생기 생성 실패"):
        other.mediaPlayer
    assert QApplication.overrideCursor() is None


EXIT_CHILD = r"""
import sys, threading, time
sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QTimer
from yesoncheck import app as app_module, path_map_setup, player_sidebar
from yesoncheck.path_map_setup import Share
from yesoncheck.player_base import VideoPlayerBase

VideoPlayerBase.SHARED_CONFIG_CLOSE_WAIT_MS = 200
probing = threading.Event()


def dead_share_is_file(path):
    probing.set()
    time.sleep(300)  # 서버가 꺼진 공유처럼 오래 걸림 (닫는 쪽은 이것을 기다리면 안 됨)
    return False


def blocked_gather(find_works_not_opening=False):
    path_map_setup.find_config_dirs(
        [Share("\\\\192.0.2.1\\dead", ["W:"]), Share("\\\\192.0.2.2\\dead", ["V:"])], is_file=dead_share_is_file)
    raise AssertionError("여기까지 오면 안 됨")


player_sidebar.gather_shared_config = blocked_gather
real_player = app_module.VideoPlayer
started = time.monotonic()


def player_factory(**kwargs):
    player = real_player(**kwargs)

    def close_when_probing():
        if probing.is_set():
            print("CHILD: 공유 확인 중 → 1초 뒤 창 닫기", flush=True)
            QTimer.singleShot(1000, player.close)
        elif time.monotonic() - started > 60:
            print("CHILD: 공유 확인이 시작되지 않음 → 창 닫기", flush=True)
            player.close()
        else:
            QTimer.singleShot(50, close_when_probing)

    QTimer.singleShot(0, close_when_probing)
    return player


app_module.VideoPlayer = player_factory
code = app_module.launch([sys.argv[0]])
print(f"CHILD: launch 끝 {code}", flush=True)
sys.exit(code)
"""


def test_app_exits_cleanly_while_shared_config_load_runs(tmp_path):
    """실제 app.launch 경로: 서버가 꺼진 공유를 확인하는 중에 창을 닫아도 정상 종료 (QThread 파괴 중단·예외 없음),
    확인 스레드를 기다리지 않고 바로 끝남."""
    import subprocess
    import sys

    from tests.conftest import ROOT

    script = tmp_path / "exit_child.py"
    script.write_text(EXIT_CHILD, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    env.pop("YESONCHECK_CONFIG_DIR", None)
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, str(script), ROOT], cwd=ROOT, env=env, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "앱이 90초 안에 끝나지 않았습니다 (닫은 뒤에도 공유 확인을 기다림?)\n"
            f"--- stdout ---\n{(exc.stdout or b'').decode('utf-8', 'replace')}\n"
            f"--- stderr ---\n{(exc.stderr or b'').decode('utf-8', 'replace')}"
        )
    elapsed = time.monotonic() - started
    out = result.stdout.decode("utf-8", "replace")
    err = result.stderr.decode("utf-8", "replace")
    report = f"종료 코드 {result.returncode}, {elapsed:.1f}초\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    assert result.returncode == 0, report
    assert "QThread: Destroyed" not in err and "Traceback" not in err, report
    assert "CHILD: 공유 확인 중 → 1초 뒤 창 닫기" in out, report
    assert "0.2초 안에 끝나지 않았습니다" in out, report  # 닫을 때 불러오기가 아직 실행 중이었음
    assert "CHILD: launch 끝 0" in out, report
