"""사이드바 목록 다시 읽기: 디스크에 없는 영상은 목록에 보이지 않고, 작업 폴더에 새로 생긴 영상은 목록에 들어옴.

사용자 보고 (2026-10-16): FL_904 목록을 띄운 뒤 NAS에서 scene 폴더 22개(scene-Z007 등)를 지웠는데 실행 중인 앱의 목록에
FL_904_Z007_TK1.mov 등이 그대로 남았고, 누르면 지금 영상이 멈춘 뒤 로그에만 "Failed to open"이 남았음.
목록은 job을 고를 때 한 번 읽은 것이었고(다시 읽는 곳이 없었음), 같은 job을 다시 골라도 currentIndexChanged가 오지 않았음.
"""

import errno
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtMultimedia import QMediaContent
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QDialog, QMessageBox, QShortcut

from yesoncheck import paths, thumbnails, video_list
from yesoncheck.player_sidebar import (
    LIST_READ_FAILED,
    THUMBNAIL_CONTEXT_ROLE,
    THUMBNAIL_FOLDER_PROBLEM,
    ThumbnailContext,
)
from tests.conftest import ROOT, write_test_video
from tests.test_thumbnails import (
    drop_folder,
    listed_path,
    record_worker_starts,
    turn_on_thumbnail_mode,
    wait_until,
)
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


def listed(player):
    return [player.sidebar.item(i).text() for i in range(player.sidebar.count())]


def items_by_name(player):
    return {player.sidebar.item(i).text(): player.sidebar.item(i) for i in range(player.sidebar.count())}


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def wait_refreshed(player, timeout=10.0):
    """목록 다시 읽기(디스크 읽기는 GUI 밖 스레드)가 끝나 결과를 넣을 때까지 — 미뤄 둔·다시 할 읽기까지."""
    wait_until(lambda: (player._sidebar_scan is None and not player._sidebar_rescan_queued
                        and not player._sidebar_refresh_deferred and not player._sidebar_refresh_holds), timeout)
    QApplication.processEvents()


def refresh(player):
    player.refresh_sidebar()
    wait_refreshed(player)


def choose(player, text):
    """사용자가 job 목록에서 고르듯이: 목록을 펼쳐 그 항목에서 Enter (Qt가 고른 항목을 처리하는 그대로 — offscreen에서는
    마우스 클릭이 펼친 목록에 전달되지 않음). 사용자의 동작은 앞의 동작과 다른 이벤트 처리 차례에 옴."""
    from PyQt5.QtTest import QTest

    combo = player.jobComboBox
    QApplication.processEvents()
    combo.showPopup()
    view = combo.view()
    view.setCurrentIndex(combo.model().index(combo.findText(text), 0))
    QTest.keyClick(view, Qt.Key_Return)
    QApplication.processEvents()


@pytest.fixture
def pumping_dialogs(dialogs, monkeypatch):
    """dialogs처럼 기록하되, 창마다 진짜 모달 QMessageBox처럼 잠깐 이벤트를 처리함 (그동안 타이머·신호가 돎)."""
    def recorder(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            dialogs.messages.append((kind, title, text))
            pump(50)
            return answer
        return fake

    for kind in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, kind, recorder(kind, QMessageBox.Ok))
    return dialogs


def block_reads(monkeypatch):
    """다시 읽기의 디스크 읽기(video_list.read_sources)를 풀어 줄 때까지 붙잡음 → (풀기 Event, 읽은 횟수 목록)."""
    release = threading.Event()
    calls = []
    real_read = video_list.read_sources

    def blocked(sources, files):
        calls.append(sources)
        assert release.wait(10), "시험이 읽기를 풀어 주지 않음"
        return real_read(sources, files)

    monkeypatch.setattr(video_list, "read_sources", blocked)
    return release, calls


def open_job(new_player, work_area, monkeypatch, scenes=("001", "002", "003")):
    """작품 SMOKE·시즌 S1의 job_01(scene마다 FL_<번호>.mov)을 고름 → (창, job 폴더의 로컬 경로)."""
    job = os.path.join(work_area.local, "S1", "job_01")
    for scene in scenes:
        write_test_video(os.path.join(job, f"scene-{scene}", "frames", f"FL_{scene}.mov"))
    write_test_video(os.path.join(work_area.local, "S1", "job_02", "scene-001", "frames", "other.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    monkeypatch.setattr(player, "save_bookmarks", lambda: None)  # 끌어다 놓은 폴더를 사용자의 북마크 파일에 쓰지 않게
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    assert listed(player) == [f"FL_{scene}.mov" for scene in scenes]
    return player, job


def add_scene(job, scene):
    return write_test_video(os.path.join(job, f"scene-{scene}", "frames", f"FL_{scene}.mov"))


def close_open_video(player):
    """앱이 연 영상(목록을 불러오면 여는 첫 영상)을 닫음 — Windows는 열려 있는 파일을 지우지 못하므로 그 영상이 든 폴더를
    지우는 시험은 먼저 닫음 (다른 PC에서 지우는 경우를 흉내. Mac은 열려 있어도 지워짐)."""
    player.stop_video()
    for name in ("cap_a", "cap_b"):
        cap = getattr(player, name)
        if cap is not None:
            cap.release()
            setattr(player, name, None)
    if player._media_player is not None:
        player._media_player.setMedia(QMediaContent())


def count_scans(monkeypatch):
    """video_list.scan_job 호출(job 폴더 경로)을 기록."""
    calls = []
    real_scan_job = video_list.scan_job

    def counting(work, base_path):
        calls.append(base_path)
        return real_scan_job(work, base_path)

    monkeypatch.setattr(video_list, "scan_job", counting)
    return calls


def list_warnings(dialogs):
    return [(title, text) for kind, title, text in dialogs.messages if kind in ("warning", "critical")]


def test_refresh_removes_deleted_and_adds_new_keeping_items(new_player, dialogs, work_area, monkeypatch):
    """지운 scene의 영상은 빠지고 새 scene의 영상은 정렬 자리에 들어옴 (처음 불러온 목록과 같음). 남은 항목은 그대로:
    같은 항목 객체·썸네일 자리·선택·현재 항목·재생 중 표시(빨간 글자)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    before = items_by_name(player)
    contexts = {name: item.data(THUMBNAIL_CONTEXT_ROLE) for name, item in before.items()}
    player.sidebar.setCurrentItem(before["FL_003.mov"])
    before["FL_001.mov"].setSelected(True)
    before["FL_003.mov"].setForeground(QColor("red"))
    generation = player._sidebar_generation

    shutil.rmtree(os.path.join(job, "scene-002"))
    add_scene(job, "004")
    add_scene(job, "000")
    refresh(player)

    assert listed(player) == ["FL_000.mov", "FL_001.mov", "FL_003.mov", "FL_004.mov"]
    fresh = video_list.scan_job("SMOKE", player.current_job_path)
    assert [paths.path_key(player.sidebar.item(i).data(Qt.UserRole)) for i in range(player.sidebar.count())] == \
        [paths.path_key(path) for _name, path in fresh.videos]
    after = items_by_name(player)
    for name in ("FL_001.mov", "FL_003.mov"):
        assert after[name] is before[name]
        assert after[name].data(THUMBNAIL_CONTEXT_ROLE) is contexts[name]
    for name in ("FL_000.mov", "FL_004.mov"):  # 처음 job을 불러올 때와 같은 자리 (job의 썸네일 폴더)
        assert after[name].data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=player.current_thumbnail_folder)
        assert after[name].toolTip() == after[name].data(Qt.UserRole)
    assert player.sidebar.currentItem() is before["FL_003.mov"]
    assert {item.text() for item in player.sidebar.selectedItems()} == {"FL_001.mov", "FL_003.mov"}
    assert after["FL_003.mov"].foreground().color() == QColor("red")
    assert player._sidebar_generation > generation  # 진행 중인 썸네일 반복이 예전 줄 번호를 쓰지 않게
    assert list_warnings(dialogs) == []


def test_refresh_without_changes_touches_nothing(new_player, dialogs, work_area, monkeypatch):
    player, _job = open_job(new_player, work_area, monkeypatch)
    model = player.sidebar.model()
    changes = []
    for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged, model.layoutChanged):
        signal.connect(lambda *args, _s=signal: changes.append(_s))
    generation = player._sidebar_generation

    refresh(player)

    assert changes == []
    assert player._sidebar_generation == generation
    assert list_warnings(dialogs) == []


def test_refresh_in_thumbnail_mode_only_makes_new_thumbnails(new_player, dialogs, work_area, monkeypatch):
    player, job = open_job(new_player, work_area, monkeypatch)
    turn_on_thumbnail_mode(player)
    icons = {name: item.icon().cacheKey() for name, item in items_by_name(player).items()}
    assert all(not item.icon().isNull() for item in items_by_name(player).values())
    started = record_worker_starts(monkeypatch)

    shutil.rmtree(os.path.join(job, "scene-002"))
    add_scene(job, "004")
    refresh(player)
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()

    assert listed(player) == ["FL_001.mov", "FL_003.mov", "FL_004.mov"]
    new_video = listed_path(player, "FL_004.mov")
    assert started == [new_video]
    after = items_by_name(player)
    assert {name: after[name].icon().cacheKey() for name in ("FL_001.mov", "FL_003.mov")} == \
        {name: icons[name] for name in ("FL_001.mov", "FL_003.mov")}
    assert not after["FL_004.mov"].icon().isNull()
    assert os.path.isfile(thumbnails.thumbnail_path(player.current_thumbnail_folder, new_video))
    assert list_warnings(dialogs) == []


def fail_scandir_of(monkeypatch, app_path, error):
    """앱이 쓰는 경로 app_path를 읽으면(scandir) error."""
    real_scandir = os.scandir

    def scandir(path="."):
        if not isinstance(path, int) and paths.same_path(os.path.normpath(os.fspath(path)), os.path.normpath(app_path)):
            raise error
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)


def test_unreadable_job_folder_keeps_items_and_reports_once(new_player, dialogs, work_area, monkeypatch):
    """NAS가 끊겼거나 권한이 없어 job 폴더를 읽지 못하면 목록을 비우지 않고 그대로 두고, 실제 오류를 창으로 한 번만
    (창이 다시 활성될 때마다 다시 읽으므로 창이 계속 뜨지 않게)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    before = listed(player)
    generation = player._sidebar_generation
    shutil.rmtree(os.path.join(job, "scene-002"))  # 다시 읽을 수 있었다면 빠졌을 영상
    fail_scandir_of(monkeypatch, player.current_job_path,
                    TimeoutError(errno.ETIMEDOUT, "Operation timed out", player.current_job_path))

    refresh(player)
    refresh(player)

    assert listed(player) == before
    assert player._sidebar_generation == generation
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1
    assert player.current_job_path in warnings[0][1] and "Operation timed out" in warnings[0][1]


def test_unreadable_scene_folder_keeps_its_items(new_player, dialogs, work_area, monkeypatch):
    player, job = open_job(new_player, work_area, monkeypatch)
    frames = os.path.join(player.current_job_path, "scene-002", "frames")
    fail_scandir_of(monkeypatch, frames, PermissionError(errno.EACCES, "Permission denied", frames))
    shutil.rmtree(os.path.join(job, "scene-003"))

    refresh(player)
    refresh(player)

    assert listed(player) == ["FL_001.mov", "FL_002.mov"]
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1
    assert frames in warnings[0][1] and "Permission denied" in warnings[0][1]


def test_deleted_job_folder_removes_its_items_and_reports_once(new_player, dialogs, work_area, monkeypatch):
    """job 폴더가 지워짐(위 폴더는 읽힘) → 영상이 디스크에 없으므로 목록에서 빼고 창으로 한 번 알림."""
    player, job = open_job(new_player, work_area, monkeypatch)
    close_open_video(player)
    shutil.rmtree(job)

    refresh(player)
    refresh(player)

    assert listed(player) == []
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1
    assert player.current_job_path in warnings[0][1] and "FileNotFoundError" in warnings[0][1]


@pytest.mark.parametrize("how", ["click", "open_a", "open_b"])
def test_opening_missing_item_reports_and_refreshes_without_stopping(new_player, dialogs, work_area, monkeypatch, how):
    player, job = open_job(new_player, work_area, monkeypatch)
    playing = player.filename_a
    cap = player.cap_a
    assert os.path.basename(playing) == "FL_001.mov"
    stops = []
    monkeypatch.setattr(player, "stop_video", lambda: stops.append(True))
    missing = items_by_name(player)["FL_002.mov"]
    missing_path = missing.data(Qt.UserRole)
    shutil.rmtree(os.path.join(job, "scene-002"))

    if how == "click":
        player.on_sidebar_item_clicked(missing)
    elif how == "open_a":
        player.open_video_a(player.sidebar.indexFromItem(missing))
    else:
        player.open_video_b(player.sidebar.indexFromItem(missing))
    wait_refreshed(player)

    assert stops == []
    assert player.filename_a == playing and player.cap_a is cap
    assert listed(player) == ["FL_001.mov", "FL_003.mov"]
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1
    assert "디스크에 없는 영상입니다" in warnings[0][1] and missing_path in warnings[0][1]


def test_unopenable_video_reports_and_keeps_current(new_player, dialogs, work_area, monkeypatch):
    """파일은 있지만 OpenCV가 열지 못하면 로그만 남기지 않고 창으로 — 지금 영상은 멈추지 않음."""
    player, job = open_job(new_player, work_area, monkeypatch)
    playing = player.filename_a
    stops = []
    monkeypatch.setattr(player, "stop_video", lambda: stops.append(True))
    broken = os.path.join(player.current_job_path, "scene-002", "frames", "FL_002.mov")
    with open(broken, "wb") as fh:
        fh.write(b"not a video")

    assert player.open_file("A", broken) is False

    assert stops == []
    assert player.filename_a == playing
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1 and broken in warnings[0][1]


def test_playlist_skips_missing_video(new_player, dialogs, work_area, monkeypatch):
    """선택 재생 중 없는 영상: 창으로 알리고 목록을 다시 읽은 뒤 다음 영상으로 (예전 영상을 다시 재생하지 않음)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    items = items_by_name(player)
    for name in ("FL_002.mov", "FL_003.mov"):
        items[name].setSelected(True)
    shutil.rmtree(os.path.join(job, "scene-002"))
    try:
        player.play_selected_files()
        wait_refreshed(player)
        assert os.path.basename(player.filename_a) == "FL_003.mov"
        assert player.is_playlist_playing
        assert listed(player) == ["FL_001.mov", "FL_003.mov"]
        assert [title for title, _text in list_warnings(dialogs)] == ["영상 없음"]
    finally:
        player.stop_video()


def test_reselecting_same_job_refreshes_and_other_job_scans_once(new_player, dialogs, work_area, monkeypatch):
    """같은 job을 다시 고르면(currentIndexChanged가 오지 않음 — activated만) 다시 읽음. 다른 job을 고르면 Qt가
    currentIndexChanged 다음 activated를 보내는데, 그때는 한 번만 읽음."""
    player, job = open_job(new_player, work_area, monkeypatch)
    scans = count_scans(monkeypatch)
    add_scene(job, "004")

    choose(player, "job_01")
    wait_refreshed(player)
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov", "FL_004.mov"]
    assert len(scans) == 1

    scans.clear()
    choose(player, "job_02")
    wait_refreshed(player)
    assert listed(player) == ["other.mov"]
    assert len(scans) == 1

    scans.clear()
    choose(player, "job_02")  # 바로 다시 골라도 다시 읽음 (job_02를 고를 때의 표시가 남아 있지 않음)
    wait_refreshed(player)
    assert len(scans) == 1


def test_unreadable_job_on_selection_one_box_one_scan(new_player, pumping_dialogs, work_area, monkeypatch):
    """리뷰 M2: 고른 job 폴더를 읽지 못하면 창 한 번·읽기 한 번 (예전에는 update_playlist의 창이 이벤트를 처리하는 동안
    '방금 읽음' 표시가 지워져 activated가 또 읽고, 문구가 달라 같은 문제가 두 번 뜸)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    job2 = os.path.normpath(os.path.join(player.current_job_path, os.pardir, "job_02"))  # 앱이 쓰는 경로 (Windows는 UNC)
    scans = count_scans(monkeypatch)
    fail_scandir_of(monkeypatch, job2, PermissionError(errno.EACCES, "Permission denied", job2))

    choose(player, "job_02")
    wait_refreshed(player)
    refresh(player)  # F5·창이 다시 활성: 같은 문제는 다시 알리지 않음

    warnings = list_warnings(pumping_dialogs)
    assert len(warnings) == 1, warnings
    assert "Permission denied" in warnings[0][1]
    assert len(scans) == 2  # 고를 때 한 번 + F5 한 번


def test_job_folder_stat_failure_registers_source_and_recovers(new_player, dialogs, work_area, monkeypatch):
    """리뷰 M5: job을 고를 때 job 폴더를 확인하지 못하면(NAS 끊김) 로그만 남기고 끝내지 않음 — 실제 오류를 창으로 알리고
    그 job을 기억해 연결이 돌아온 뒤 F5로 목록이 생김."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    real_stat = os.stat
    down = {"on": True}
    job2_app = []

    def stat(path, *args, **kwargs):
        if down["on"] and os.path.basename(os.path.normpath(os.fspath(path))) == "job_02":
            job2_app.append(path)
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    choose(player, "job_02")
    wait_refreshed(player)
    assert listed(player) == []
    warnings = list_warnings(dialogs)
    assert len(warnings) == 1 and "Operation timed out" in warnings[0][1] and "job_02" in warnings[0][1]

    down["on"] = False
    refresh(player)
    assert listed(player) == ["other.mov"]
    assert len(list_warnings(dialogs)) == 1


def test_deleted_job_folder_on_selection_reports_not_found(new_player, dialogs, work_area, monkeypatch):
    """리뷰 M5: 고른 job 폴더가 지워졌으면(위 폴더는 읽힘) 로그만이 아니라 창으로 '목록 폴더 없음'."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    shutil.rmtree(os.path.join(work_area.local, "S1", "job_02"))
    choose(player, "job_02")
    wait_refreshed(player)
    assert listed(player) == []
    assert [title for title, _text in list_warnings(dialogs)] == ["목록 폴더 없음"]


def test_problem_reported_again_after_source_recovered(new_player, dialogs, work_area, monkeypatch):
    """리뷰 L11: 읽지 못한 폴더를 다시 읽을 수 있게 되면 알린 기록을 지움 → 나중에 또 끊기면 다시 알림."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    job_path = player.current_job_path
    real_scandir = os.scandir
    down = {"on": True}

    def scandir(path="."):
        if down["on"] and not isinstance(path, int) and paths.same_path(os.fspath(path), job_path):
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", job_path)
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    refresh(player)
    refresh(player)
    assert len(list_warnings(dialogs)) == 1
    down["on"] = False
    refresh(player)
    down["on"] = True
    refresh(player)
    assert len(list_warnings(dialogs)) == 2


def test_reselecting_job_after_folder_load_shows_the_job(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """폴더를 불러와 목록이 바뀐 뒤 job 목록에 보이는 그 job을 다시 고르면 그 job의 목록 (예전처럼 아무 일도 없지 않음)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    folder = tmp_path / "clips"
    write_test_video(str(folder / "clip1.mov"))
    player.load_videos_from_folder(str(folder))
    assert listed(player) == ["clip1.mov"]
    QApplication.processEvents()

    choose(player, "job_01")  # 같은 job을 다시 고름 (activated만 옴)

    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov"]
    assert os.path.basename(player.filename_a) == "FL_001.mov"


@pytest.fixture
def shown_job(new_player, dialogs, work_area, monkeypatch):
    player, job = open_job(new_player, work_area, monkeypatch)
    player.show()
    pump(300)
    assert QApplication.activeWindow() is player
    # 창을 보일 때(활성화) 예약된 다시 읽기가 끝날 때까지 — 시험 중에 끝나 '방금 읽음'이 되지 않게
    wait_until(lambda: not player._sidebar_refresh_timer.isActive())
    wait_refreshed(player)
    return player, job


def test_app_activation_refreshes(shown_job, dialogs):
    """다른 앱에서 돌아오면(QGuiApplication.applicationStateChanged → ApplicationActive) 다시 읽음."""
    player, job = shown_job
    player._sidebar_refreshed_at = None
    add_scene(job, "004")
    QApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)
    wait_until(lambda: "FL_004.mov" in listed(player))
    assert list_warnings(dialogs) == []


def test_own_window_switches_do_not_refresh(shown_job, monkeypatch):
    """2차 검토 M2: 이 앱의 창 사이를 오가거나(창 활성 바뀜) 이 앱의 창을 닫아도 다시 읽지 않음 — 앱이 다시 활성될 때만.
    창 활성화 때의 포커스 되돌리기(force_focus)는 그대로."""
    from PyQt5.QtWidgets import QWidget

    player, job = shown_job
    scans = count_scans(monkeypatch)
    player._sidebar_refreshed_at = None
    focus = []
    monkeypatch.setattr(player, "force_focus", lambda: focus.append(True))
    other = QWidget()
    other.show()
    other.activateWindow()
    wait_until(lambda: QApplication.activeWindow() is other)
    other.close()
    QWidget.activateWindow(player)
    wait_until(lambda: QApplication.activeWindow() is player)
    player.changeEvent(QEvent(QEvent.ActivationChange))
    pump(600)
    wait_refreshed(player)
    assert scans == []
    assert focus  # 창 활성화 뒤 포커스 되돌리기는 예전처럼


def test_activation_gap_grows_with_scan_time(shown_job, monkeypatch):
    """2차 검토 M2: 마지막 읽기가 오래 걸렸으면(Windows SMB의 큰 job) 그만큼 오래 다시 읽지 않음 (10배, 최소 2초)."""
    player, _job = shown_job
    scans = count_scans(monkeypatch)
    player._sidebar_scan_seconds = 1.0
    player._sidebar_refreshed_at = time.monotonic() - 5  # 5초 전 — 1초 걸린 읽기면 10초 동안은 다시 읽지 않음
    player._refresh_sidebar_on_activation()
    wait_refreshed(player)
    assert scans == []
    player._sidebar_scan_seconds = 0.01  # 빠른 읽기면 2초 뒤에는 다시 읽음
    player._refresh_sidebar_on_activation()
    wait_refreshed(player)
    assert len(scans) == 1


def count_reads(monkeypatch):
    """목록 다시 읽기의 디스크 읽기(video_list.read_sources — GUI 밖 스레드) 횟수. 처음 불러오기는 세지 않음."""
    calls = []
    real_read = video_list.read_sources

    def counting(sources, files):
        calls.append(sources)
        return real_read(sources, files)

    monkeypatch.setattr(video_list, "read_sources", counting)
    return calls


@pytest.mark.parametrize("how", ["job", "folder", "drop"])
def test_sync_load_counts_as_recent_read(shown_job, tmp_path, monkeypatch, how):
    """2차 검토 M2: job을 고르거나 폴더를 불러오거나 끌어다 놓은 바로 뒤 앱이 다시 활성돼도(예: 그때 뜬 창을 닫음) 또 읽지
    않음 — 방금 디스크에서 읽었음."""
    player, _job = shown_job
    folder = tmp_path / "dropped"
    write_test_video(str(folder / "a.mov"))
    reads = count_reads(monkeypatch)
    player._sidebar_refreshed_at = None
    if how == "job":
        player.jobComboBox.setCurrentText("job_02")
    elif how == "folder":
        player.load_videos_from_folder(str(folder))
    else:
        drop_folder(player, "sidebar", folder)
    assert player._sidebar_refreshed_at is not None
    player._refresh_sidebar_on_activation()
    wait_refreshed(player)
    assert reads == []


def test_activation_refresh_skipped_under_modal_dialog_and_right_after_refresh(shown_job, monkeypatch):
    from PyQt5.QtWidgets import QWidget

    player, job = shown_job
    scans = count_scans(monkeypatch)
    player._sidebar_refreshed_at = None
    dialog = QDialog(player)
    dialog.setModal(True)
    dialog.show()
    try:
        wait_until(lambda: QApplication.activeModalWidget() is dialog)
        player._refresh_sidebar_on_activation()
        assert scans == []
    finally:
        dialog.close()
        dialog.deleteLater()
    # 모달 창이 닫히면 OS가 메인 창을 다시 활성화함 (offscreen은 하지 않으므로 직접)
    QWidget.activateWindow(player)
    wait_until(lambda: QApplication.activeWindow() is player)
    player._sidebar_refreshed_at = None

    player._refresh_sidebar_on_activation()
    wait_refreshed(player)
    assert len(scans) == 1
    # 바로 뒤에 또 활성화(예: 없는 영상 창을 닫음 — 그 창을 띄운 쪽이 이미 다시 읽음)되면 또 읽지 않음
    player._refresh_sidebar_on_activation()
    wait_refreshed(player)
    assert len(scans) == 1


def test_refresh_button_and_f5(new_player, dialogs, work_area, monkeypatch):
    player, job = open_job(new_player, work_area, monkeypatch)
    button = player.refreshListButton
    assert button.text() == "새로고침" and "F5" in button.toolTip()
    shortcuts = [s for s in player.findChildren(QShortcut) if s.key().toString() == "F5"]
    assert len(shortcuts) == 1

    add_scene(job, "004")
    button.click()
    wait_refreshed(player)
    assert "FL_004.mov" in listed(player)
    add_scene(job, "005")
    shortcuts[0].activated.emit()
    wait_refreshed(player)
    assert "FL_005.mov" in listed(player)


def test_refresh_waits_for_running_thumbnail_pass(new_player, dialogs, work_area, monkeypatch):
    """썸네일을 만드는 동안(이벤트 처리 중) 다시 읽으면 그 반복이 멈추지 않게 끝난 뒤로 미룸 → 끝나면 다시 읽고 새 영상의
    썸네일도 만듦."""
    player, job = open_job(new_player, work_area, monkeypatch)
    real_generate = player.generate_thumbnail
    during = []

    def generate_and_refresh(*args, **kwargs):
        if not during:
            add_scene(job, "004")
            player.refresh_sidebar()  # 예: F5 / 창이 다시 활성
            during.append(listed(player))
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(player, "generate_thumbnail", generate_and_refresh)
    turn_on_thumbnail_mode(player)
    assert during == [["FL_001.mov", "FL_002.mov", "FL_003.mov"]]  # 반복 중에는 그대로
    assert player.thumbnailProgressBar.format() == "썸네일 생성 완료"
    wait_until(lambda: "FL_004.mov" in listed(player))
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert all(not item.icon().isNull() for item in items_by_name(player).values())
    for name in ("FL_001.mov", "FL_002.mov", "FL_003.mov", "FL_004.mov"):
        assert os.path.isfile(thumbnails.thumbnail_path(player.current_thumbnail_folder, listed_path(player, name)))


# ---- 새로고침 버튼·F5: 같은 이름으로 다시 렌더링한 영상의 썸네일도 다시 만듦 ----

THUMBNAIL_CHECK_LOG = "새로고침: 썸네일 확인"


def press_refresh(player, how="button"):
    """사용자의 새로고침: 새로고침 버튼 또는 F5 단축키."""
    if how == "button":
        player.refreshListButton.click()
    else:
        [shortcut] = [s for s in player.findChildren(QShortcut) if s.key().toString() == "F5"]
        shortcut.activated.emit()


def settle_thumbnail_times(player):
    """목록의 모든 썸네일을 영상보다 새것으로 (os.utime으로 시각을 정해 둠 — 파일 시스템 시각의 정밀도와 상관없이)
    → 그 썸네일의 시각. 그 뒤 다시 만든 썸네일(지금 시각)은 rerender의 영상보다도 새것."""
    base = time.time() - 100
    for i in range(player.sidebar.count()):
        item = player.sidebar.item(i)
        video = item.data(Qt.UserRole)
        os.utime(video, (base - 10, base - 10))
        os.utime(thumbnails.thumbnail_path(item.data(THUMBNAIL_CONTEXT_ROLE).folder, video), (base, base))
    return base


def rerender(video, base):
    """같은 이름으로 다시 렌더링한 영상: 다른 크기로 다시 써서(썸네일 120×60 — 처음은 120×90) 썸네일보다 새 시각."""
    write_test_video(video, size=(320, 160))
    os.utime(video, (base + 10, base + 10))


def icon_size(item):
    """항목 아이콘의 크기 (아이콘이 없으면 None) — 다시 렌더링한 영상의 새 썸네일이 붙었는지."""
    sizes = item.icon().availableSizes()
    return (sizes[0].width(), sizes[0].height()) if sizes else None


def wait_thumbnails(player):
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()


def thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch):
    """job_01을 썸네일 모드로 보고(썸네일 모두 영상보다 새것) FL_002를 같은 이름으로 다시 렌더링함
    → (창, job 폴더, 다시 렌더링한 영상의 앱 경로, 그 썸네일 파일)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    turn_on_thumbnail_mode(player)
    base = settle_thumbnail_times(player)
    changed = listed_path(player, "FL_002.mov")
    rerender(changed, base)
    return player, job, changed, thumbnails.thumbnail_path(player.current_thumbnail_folder, changed)


@pytest.mark.parametrize("how", ["button", "f5"])
def test_manual_refresh_remakes_rerendered_thumbnail(new_player, dialogs, work_area, monkeypatch, capsys, how):
    """새로고침 버튼·F5: 다시 읽은 뒤(목록이 바뀌지 않아도) 모든 영상의 썸네일을 썸네일 버튼처럼 확인 — 같은 이름으로 다시
    렌더링한(썸네일보다 새) 영상만 다시 만들어 아이콘을 바꾸고 나머지는 저장된 썸네일을 씀. 방금 읽었어도(앱이 다시
    활성될 때는 건너뛰는 간격 안) 읽음."""
    player, _job, changed, thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    reads = count_reads(monkeypatch)
    generation = player._sidebar_generation
    player._sidebar_scan_seconds = 1.0
    player._sidebar_refreshed_at = time.monotonic()
    capsys.readouterr()

    press_refresh(player, how)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert len(reads) == 1
    assert started == [changed]
    after = items_by_name(player)
    assert icon_size(after["FL_002.mov"]) == (120, 60)
    assert [icon_size(after[name]) for name in ("FL_001.mov", "FL_003.mov")] == [(120, 90), (120, 90)]
    assert QPixmap(thumb).size().width() == 120 and QPixmap(thumb).size().height() == 60  # 새 썸네일 파일
    assert thumbnails.is_fresh(thumb, changed)
    assert player._sidebar_generation == generation  # 목록은 그대로 (바뀐 것 없음)
    out = capsys.readouterr().out
    assert out.count(THUMBNAIL_CHECK_LOG) == 1
    assert "새로고침: 썸네일 확인 3개, 다시 만듦 1개" in out
    assert list_warnings(dialogs) == []


def test_manual_refresh_new_and_rerendered_video_each_once(new_player, dialogs, work_area, monkeypatch, capsys):
    """한 번의 새로고침에 새 영상과 다시 렌더링한 영상이 함께 있으면 둘 다 한 번씩만 만듦 (새 영상을 두 번 보지 않음)."""
    player, job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    add_scene(job, "004")
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov", "FL_004.mov"]
    assert started == [changed, listed_path(player, "FL_004.mov")]
    after = items_by_name(player)
    assert icon_size(after["FL_002.mov"]) == (120, 60)
    assert icon_size(after["FL_004.mov"]) == (120, 90)
    out = capsys.readouterr().out
    assert out.count(THUMBNAIL_CHECK_LOG) == 1
    assert "새로고침: 썸네일 확인 4개, 다시 만듦 2개" in out
    assert list_warnings(dialogs) == []


def test_manual_refresh_updates_every_item_of_rerendered_video(new_player, dialogs, tmp_path, monkeypatch):
    """같은 영상이 목록에 두 번 있으면 한 번만 다시 만들고 두 항목 모두 새 아이콘."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    player.add_files_to_sidebar([video])
    turn_on_thumbnail_mode(player)
    rerender(video, settle_thumbnail_times(player))
    started = record_worker_starts(monkeypatch)

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert started == [video]
    assert [icon_size(player.sidebar.item(i)) for i in range(player.sidebar.count())] == [(120, 60), (120, 60)]
    assert dialogs.errors() == []


@pytest.mark.parametrize("how", ["activation", "reselect_job", "missing_video"])
def test_automatic_refresh_makes_only_new_thumbnails(shown_job, dialogs, monkeypatch, capsys, how):
    """저절로 다시 읽을 때(다른 앱에서 돌아옴·같은 job을 다시 고름·없는 영상을 엶)는 예전처럼 새 영상의 썸네일만 — 다시
    렌더링한 영상은 그대로 (앱을 오갈 때마다 모든 영상을 NAS에서 확인하지 않게. 새로고침 버튼·F5를 누르면 다시 만듦)."""
    player, job = shown_job
    turn_on_thumbnail_mode(player)
    changed = listed_path(player, "FL_002.mov")
    rerender(changed, settle_thumbnail_times(player))
    missing = listed_path(player, "FL_003.mov")
    add_scene(job, "004")
    started = record_worker_starts(monkeypatch)
    reads = count_reads(monkeypatch)
    capsys.readouterr()

    if how == "activation":
        player._sidebar_refreshed_at = None
        QApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)
    elif how == "reselect_job":
        choose(player, "job_01")
    else:
        shutil.rmtree(os.path.join(job, "scene-003"))
        assert player.open_file("B", missing) is False  # '영상 없음' 창 → 목록 다시 읽기
    wait_until(lambda: len(reads) == 1)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert "FL_004.mov" in listed(player)
    assert started == [listed_path(player, "FL_004.mov")]
    assert icon_size(items_by_name(player)["FL_002.mov"]) == (120, 90)
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out


def test_manual_refresh_in_list_mode_makes_no_thumbnails(new_player, dialogs, work_area, monkeypatch, capsys):
    """목록 모드에서는 새로고침 버튼·F5도 예전처럼 목록만 다시 읽음 (다시 렌더링한 영상·새 영상의 썸네일을 만들지 않음)."""
    player, job, changed, thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    player.switch_to_list_mode()
    add_scene(job, "004")
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_refreshed(player)
    press_refresh(player, "f5")
    wait_refreshed(player)
    wait_thumbnails(player)

    assert "FL_004.mov" in listed(player)
    assert started == []
    assert all(item.icon().isNull() for item in items_by_name(player).values())
    assert not thumbnails.is_fresh(thumb, changed)
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out
    # 목록 모드에서 누른 새로고침은 남지 않음: 그 뒤 저절로 다시 읽어도 모든 영상을 확인하지 않음
    turn_on_thumbnail_mode(player)
    started.clear()
    capsys.readouterr()
    refresh(player)
    wait_thumbnails(player)
    assert started == []
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out


def test_manual_refresh_then_list_mode_makes_no_thumbnails(new_player, dialogs, work_area, monkeypatch, capsys):
    """썸네일 모드에서 새로고침을 누른 뒤 결과를 넣기 전에 목록 모드로 바꾸면 썸네일을 만들지 않음."""
    player, _job, changed, thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    release, calls = block_reads(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_until(lambda: len(calls) == 1)
    player.switch_to_list_mode()
    release.set()
    wait_refreshed(player)
    wait_thumbnails(player)

    assert started == []
    assert all(item.icon().isNull() for item in items_by_name(player).values())
    assert not thumbnails.is_fresh(thumb, changed)
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out


@pytest.mark.parametrize("how", ["in_flight", "hold", "result_under_hold", "folder_appended"])
def test_manual_refresh_request_survives_coalescing(new_player, dialogs, work_area, tmp_path, monkeypatch, capsys, how):
    """새로고침을 누를 때 읽는 중이거나(끝난 뒤 한 번 더로 모음 — 몇 번 눌러도), 목록을 쓰는 중이라 미루거나, 결과를 버리고
    다시 읽어도(목록을 쓰는 중·읽는 동안 폴더를 덧붙임) 썸네일 확인은 결과를 넣을 때 꼭 한 번 (잃지 않고 두 번 하지도 않음)."""
    player, _job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    release, calls = block_reads(monkeypatch)
    capsys.readouterr()

    if how == "in_flight":
        player.refresh_sidebar()  # 예: 앱이 다시 활성 — 읽는 동안 새로고침 버튼과 F5를 누름
        wait_until(lambda: len(calls) == 1)
        press_refresh(player)
        press_refresh(player, "f5")
        assert player._sidebar_rescan_queued
        release.set()
    elif how == "hold":
        release.set()
        with player._hold_sidebar_refresh():  # 예: 오른쪽 클릭 메뉴가 떠 있음
            press_refresh(player)
            assert player._sidebar_refresh_deferred and calls == []
    elif how == "result_under_hold":
        press_refresh(player)
        wait_until(lambda: len(calls) == 1)
        with player._hold_sidebar_refresh():
            release.set()
            wait_until(lambda: player._sidebar_scan is None)  # 결과를 버리고 끝난 뒤 다시 읽기로 미룸
            assert player._sidebar_refresh_deferred
    else:
        dropped = tmp_path / "other"
        extra = write_test_video(str(dropped / "x.mov"))
        os.utime(extra, (time.time() - 100, time.time() - 100))
        press_refresh(player)
        wait_until(lambda: len(calls) == 1)
        drop_folder(player, "sidebar", dropped)  # 읽는 동안 폴더를 덧붙임 → 그 결과는 버리고 다시 읽음
        release.set()
    wait_refreshed(player)
    wait_thumbnails(player)

    assert len(calls) == (1 if how == "hold" else 2)
    if how == "folder_appended":
        assert started == [listed_path(player, "x.mov"), changed]  # 덧붙인 영상은 넣을 때 만듦
    else:
        assert started == [changed]
    assert icon_size(items_by_name(player)["FL_002.mov"]) == (120, 60)
    assert capsys.readouterr().out.count(THUMBNAIL_CHECK_LOG) == 1
    assert list_warnings(dialogs) == []


@pytest.mark.parametrize("how", ["in_flight", "hold"])
def test_manual_refresh_request_dropped_when_list_reset(new_player, dialogs, work_area, monkeypatch, capsys, how):
    """새로고침을 누른 뒤 결과를 넣기 전에 다른 job을 고르면(목록을 새로 불러옴) 썸네일 확인 요청은 버림 — 새 목록은 처음
    불러올 때의 흐름대로 (job_02의 영상은 썸네일이 없지만 새로고침 요청으로 만들지 않음, 그 뒤 저절로 다시 읽어도)."""
    player, _job, _changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    release, calls = block_reads(monkeypatch)
    capsys.readouterr()

    if how == "in_flight":
        press_refresh(player)
        wait_until(lambda: len(calls) == 1)
        player.jobComboBox.setCurrentText("job_02")
        release.set()
    else:
        release.set()
        with player._hold_sidebar_refresh():
            press_refresh(player)
            player.jobComboBox.setCurrentText("job_02")
    assert listed(player) == ["other.mov"]
    wait_refreshed(player)
    refresh(player)  # 저절로 다시 읽기 (예: 앱이 다시 활성)
    wait_thumbnails(player)

    assert started == []
    assert listed(player) == ["other.mov"]
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out
    assert list_warnings(dialogs) == []


def test_manual_refresh_on_empty_list_leaves_no_request(new_player, dialogs, tmp_path, monkeypatch, capsys):
    """빈 목록(읽을 곳도 영상도 없음)에서 누른 새로고침은 할 일이 없음 — 그 뒤 파일을 넣고 저절로 다시 읽어도 모든 영상을
    확인하지 않음 (요청이 남아 있지 않음)."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    turn_on_thumbnail_mode(player)
    press_refresh(player)
    wait_refreshed(player)
    player.add_files_to_sidebar([video])
    wait_thumbnails(player)
    rerender(video, settle_thumbnail_times(player))
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    refresh(player)  # 저절로 다시 읽기 (예: 앱이 다시 활성)
    wait_thumbnails(player)

    assert started == []
    assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out
    assert dialogs.errors() == []


@pytest.mark.parametrize("how", ["error_alone", "pressed_again_during_read"])
def test_manual_refresh_request_dropped_with_failed_read(new_player, dialogs, work_area, monkeypatch, capsys, how):
    """새로고침으로 시작한 읽기가 예상 못 한 오류로 끝나면(오류 창) 그 썸네일 확인은 버림 — 몇 시간 뒤 저절로 다시 읽을 때
    모든 영상을 확인하지 않음. 그 읽기 중에 또 누른 새로고침은 뒤이은 읽기에서 한 번."""
    player, _job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    release = threading.Event()
    real_read = video_list.read_sources
    reads = []

    def first_read_fails(sources, files):
        reads.append(sources)
        if len(reads) == 1:
            assert release.wait(10), "시험이 읽기를 풀어 주지 않음"
            raise RuntimeError("synthetic read failure")
        return real_read(sources, files)

    monkeypatch.setattr(video_list, "read_sources", first_read_fails)
    capsys.readouterr()

    press_refresh(player)
    wait_until(lambda: len(reads) == 1)
    if how == "pressed_again_during_read":
        press_refresh(player, "f5")
    release.set()
    wait_refreshed(player)
    wait_thumbnails(player)
    assert [title for kind, title, _text in dialogs.messages if kind == "critical"] == ["목록 다시 읽기 오류"]
    if how == "error_alone":
        refresh(player)  # 저절로 다시 읽기 (예: 몇 시간 뒤 앱이 다시 활성)
        wait_thumbnails(player)
        assert started == []
        assert THUMBNAIL_CHECK_LOG not in capsys.readouterr().out
    else:
        assert started == [changed]
        assert capsys.readouterr().out.count(THUMBNAIL_CHECK_LOG) == 1
    assert len(reads) == 2


def test_manual_refresh_without_changes_keeps_list_rows(new_player, dialogs, work_area, monkeypatch, capsys):
    """바뀐 것이 없는 새로고침(썸네일 모드)은 목록의 줄을 건드리지 않음 (넣기·빼기·초기화·배치 없음, 세대 그대로) — 썸네일
    확인은 저장된 썸네일을 붙이기만 하고 다시 만들지 않음."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    turn_on_thumbnail_mode(player)
    settle_thumbnail_times(player)
    model = player.sidebar.model()
    changes = []
    for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
        signal.connect(lambda *args, _s=signal: changes.append(_s))
    generation = player._sidebar_generation
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert changes == []
    assert player._sidebar_generation == generation
    assert started == []
    assert "새로고침: 썸네일 확인 3개, 다시 만듦 0개" in capsys.readouterr().out


def test_manual_refresh_during_thumb_button_pass_runs_after_it(new_player, dialogs, work_area, monkeypatch, capsys):
    """썸네일 버튼으로 만드는 중에 누른 F5는 끝난 뒤로 미루고 그 뒤 썸네일을 한 번 확인 — 방금 만든 썸네일은 다시 만들지 않음."""
    from PyQt5.QtCore import QTimer

    player, _job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    real_generate = player.generate_thumbnail
    calls = []

    def generate_then_f5(*args, **kwargs):
        if not calls:
            QTimer.singleShot(0, lambda: press_refresh(player, "f5"))
        calls.append(args[0])
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(player, "generate_thumbnail", generate_then_f5)
    capsys.readouterr()

    player.thumbnailModeButton.click()  # 썸네일 버튼 다시 (FL_002가 썸네일보다 새것)
    wait_thumbnails(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert calls == [changed] and started == [changed]
    assert capsys.readouterr().out.count("새로고침: 썸네일 확인 3개, 다시 만듦 0개") == 1
    assert icon_size(items_by_name(player)["FL_002.mov"]) == (120, 60)


def test_manual_refresh_survives_list_and_thumbnail_round_trip(new_player, dialogs, work_area, monkeypatch, capsys):
    """F5로 읽는 중에 목록 모드로 갔다 썸네일 모드로 돌아오면(썸네일 버튼이 다시 렌더링한 영상을 만듦) 결과를 넣을 때
    확인은 한 번 — 이미 만든 썸네일을 또 만들지 않음."""
    player, _job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    started = record_worker_starts(monkeypatch)
    release, calls = block_reads(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_until(lambda: len(calls) == 1)
    player.switch_to_list_mode()
    player.switch_to_thumbnail_mode()  # 썸네일 버튼: FL_002를 여기서 다시 만듦
    wait_thumbnails(player)
    release.set()
    wait_refreshed(player)
    wait_thumbnails(player)

    assert len(calls) == 1
    assert started == [changed]
    assert capsys.readouterr().out.count(THUMBNAIL_CHECK_LOG) == 1
    assert icon_size(items_by_name(player)["FL_002.mov"]) == (120, 60)


class BusyWorker:
    """썸네일 워커 자리 (목록 모드로 바뀔 때까지 실행 중) — generate_thumbnail이 다른 워커를 기다리게."""

    def __init__(self, player):
        self.player = player

    def isRunning(self):
        return self.player.is_thumbnail_mode

    def stop(self):
        pass


@pytest.mark.parametrize("how", ["f5", "f5_during_check", "thumb_button", "add_files"])
def test_list_mode_during_thumbnail_loop_stops_it(new_player, dialogs, work_area, tmp_path, monkeypatch, capsys, how):
    """썸네일을 만드는 반복(새로고침·썸네일 버튼·파일 넣기 — 이벤트를 처리함) 중에 목록 모드로 바꾸면 나머지는 만들지 않음
    (워커를 더 띄우지 않고 목록 모드에 아이콘을 붙이지 않음). 새로고침 로그는 실제로 확인·만든 수."""
    from PyQt5.QtCore import QTimer

    player, _job = open_job(new_player, work_area, monkeypatch)
    turn_on_thumbnail_mode(player)
    base = settle_thumbnail_times(player)
    close_open_video(player)  # 앱이 연 FL_001.mov도 다시 씀 — Windows는 열려 있는 파일에 쓰지 못함
    for name in ("FL_001.mov", "FL_002.mov", "FL_003.mov"):
        rerender(listed_path(player, name), base)
    extra = [write_test_video(str(tmp_path / "extra" / f"{name}.mov")) for name in ("e", "f", "g")]
    started = record_worker_starts(monkeypatch)
    calls = []
    if how == "f5_during_check":
        real_update = player.update_sidebar_item_thumbnail

        def update_then_list_mode(*args):
            if not calls:  # 저장된 썸네일을 붙이는 중(첫 영상)에 사용자가 목록 모드를 누름
                calls.append(args[0])
                QTimer.singleShot(0, player.listModeButton.click)
            return real_update(*args)

        monkeypatch.setattr(player, "update_sidebar_item_thumbnail", update_then_list_mode)
        settle_thumbnail_times(player)  # 모두 저장된 썸네일을 씀 — 첫 영상 뒤로는 확인하지 않음
    else:
        real_generate = player.generate_thumbnail

        def generate_then_list_mode(*args, **kwargs):
            if not calls:  # 첫 썸네일을 만드는 중에 사용자가 목록 모드를 누름
                QTimer.singleShot(0, player.listModeButton.click)
            calls.append(args[0])
            return real_generate(*args, **kwargs)

        monkeypatch.setattr(player, "generate_thumbnail", generate_then_list_mode)
    before = len(dialogs.messages)
    capsys.readouterr()

    if how in ("f5", "f5_during_check"):
        press_refresh(player)
        wait_refreshed(player)
    elif how == "thumb_button":
        player.thumbnailModeButton.click()
    else:
        player.add_files_to_sidebar(extra)
    wait_thumbnails(player)
    pump(300)

    assert not player.is_thumbnail_mode
    # 목록 모드로 바꾸기 전에 띄운 첫 워커만 (파일 넣기는 다음 영상이 그 워커를 기다리다 바뀐 것을 보고 띄우지 않음)
    assert started == ([] if how == "f5_during_check" else calls[:1])
    not_started = [item for item in items_by_name(player).values()
                   if not any(paths.same_path(item.data(Qt.UserRole), path) for path in started)]
    assert len(not_started) == player.sidebar.count() - len(started)
    assert all(item.icon().isNull() for item in not_started)
    out = capsys.readouterr().out
    if how == "f5":
        assert "새로고침: 썸네일 확인 3개, 다시 만듦 1개" in out
    elif how == "f5_during_check":
        assert "새로고침: 썸네일 확인 1개, 다시 만듦 0개" in out
    elif how == "thumb_button":
        assert player.thumbnailProgressBar.format() == "썸네일 생성 멈춤 (목록 모드로 바꿈)"
        assert [m for m in dialogs.messages[before:] if m[1] == "썸네일 생성 완료"] == []  # 멈추면 완료 창 없음
    assert dialogs.errors() == []


def test_generate_thumbnail_not_started_after_list_mode_while_waiting(new_player, dialogs, tmp_path, monkeypatch):
    """다른 썸네일 워커를 기다리는 동안(이벤트 처리) 목록 모드로 바꾸면 그 영상의 워커는 띄우지 않음. 목록 모드에서
    부른 것(썸네일 재생성 R)은 예전처럼 만듦."""
    from PyQt5.QtCore import QTimer

    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    turn_on_thumbnail_mode(player)
    started = record_worker_starts(monkeypatch)
    os.utime(video, (time.time() + 100, time.time() + 100))  # 썸네일보다 새 영상 → 다시 만들 차례
    player.thumbnail_workers.append(BusyWorker(player))
    QTimer.singleShot(50, player.listModeButton.click)

    assert player.generate_thumbnail(video) is False
    assert started == []
    assert player.thumbnail_workers == []  # 목록 모드로 바꾸며 워커를 멈추고 비움
    assert player.generate_thumbnail(video) is True  # 목록 모드에서 부름
    wait_thumbnails(player)
    assert started == [video]


def test_manual_refresh_skips_screen_only_items_with_icons(new_player, dialogs, tmp_path, monkeypatch, capsys):
    """썸네일 폴더를 만들지 못해 화면에만 보이는 영상은 저장된 썸네일이 없으므로, 아이콘이 이미 있으면 새로고침마다 다시
    만들지 않음 (아이콘이 없는 것만 만듦)."""
    videos = [write_test_video(str(tmp_path / "job" / f"{name}.mov")) for name in ("a", "b", "c")]
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar(videos)

    def cannot_create(parent_dir):
        raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))

    monkeypatch.setattr(thumbnails, "ensure_folder", cannot_create)
    turn_on_thumbnail_mode(player)
    assert all(player.sidebar.item(i).data(THUMBNAIL_CONTEXT_ROLE).folder is None for i in range(3))
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(3))
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    for _ in range(2):
        press_refresh(player)
        wait_refreshed(player)
        wait_thumbnails(player)
    assert started == []
    out = capsys.readouterr().out
    assert out.count("새로고침: 썸네일 확인 0개, 다시 만듦 0개") == 2
    assert "화면에만 보이는 영상 3개" in out

    player.sidebar.item(1).setIcon(QIcon())
    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)
    assert started == [videos[1]]
    assert not player.sidebar.item(1).icon().isNull()
    assert [title for title, _text in list_warnings(dialogs)] == [THUMBNAIL_FOLDER_PROBLEM]  # 썸네일 모드를 켤 때 한 번


def count_gui_stats_failing(monkeypatch, failing):
    """GUI 스레드에서 영상(.mov)을 os.stat한 경로 목록. failing(경로)이면 그 영상은 PermissionError (권한·끊긴 공유처럼 —
    GUI 밖 스레드의 읽기도 같음)."""
    real_stat = os.stat
    main = threading.main_thread()
    gui_stats = []

    def stat_(path, *args, **kwargs):
        name = os.fspath(path) if not isinstance(path, int) else ""
        if name.endswith(".mov"):
            if threading.current_thread() is main:
                gui_stats.append(name)
            if failing(name):
                raise PermissionError(errno.EACCES, "Permission denied", name)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat_)
    return gui_stats


@pytest.mark.parametrize("how", ["job_folder", "scene_folder", "loose_file"])
def test_manual_refresh_skips_videos_the_read_could_not_confirm(new_player, dialogs, work_area, tmp_path, monkeypatch,
                                                                 capsys, how):
    """이번 읽기에서 확인하지 못한 영상(읽지 못한 목록 폴더·하위 폴더 아래, 있는지 확인하지 못한 따로 넣은 파일)은 새로고침의
    썸네일 확인에서 건너뜀 — 목록 창 하나만 뜨고, GUI 스레드에서 그 영상을 하나씩 확인하지 않음 (NAS가 끊겼으면 영상마다
    기다림) "영상 확인 실패" 창도 없음."""
    player, job = open_job(new_player, work_area, monkeypatch)
    loose = write_test_video(str(tmp_path / "loose" / "x.mov"))
    player.add_files_to_sidebar([loose])
    turn_on_thumbnail_mode(player)
    settle_thumbnail_times(player)
    if how == "job_folder":
        fail_scandir_of(monkeypatch, player.current_job_path,
                        TimeoutError(errno.ETIMEDOUT, "Operation timed out", player.current_job_path))
        skipped = [listed_path(player, name) for name in ("FL_001.mov", "FL_002.mov", "FL_003.mov")]
    elif how == "scene_folder":
        frames = os.path.join(player.current_job_path, "scene-002", "frames")
        fail_scandir_of(monkeypatch, frames, PermissionError(errno.EACCES, "Permission denied", frames))
        skipped = [listed_path(player, "FL_002.mov")]
    else:
        skipped = [listed_path(player, "x.mov")]
    gui_stats = count_gui_stats_failing(monkeypatch, lambda name: any(paths.same_path(name, p) for p in skipped))
    started = record_worker_starts(monkeypatch)
    before = len(dialogs.messages)
    capsys.readouterr()

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert [title for kind, title, _text in dialogs.messages[before:]] == [LIST_READ_FAILED]
    assert not any(paths.same_path(name, p) for name in gui_stats for p in skipped)
    assert started == []
    out = capsys.readouterr().out
    assert f"새로고침: 이번에 읽지 못한 곳의 영상 {len(skipped)}개는 썸네일을 확인하지 않음" in out
    assert f"새로고침: 썸네일 확인 {4 - len(skipped)}개, 다시 만듦 0개" in out


def test_manual_refresh_counts_only_started_thumbnails(new_player, dialogs, work_area, monkeypatch, capsys):
    """로그의 '다시 만듦'은 워커를 띄운 수: 확인한 뒤 만들기 전에 없어진 영상은 세지 않음."""
    player, job, changed, _thumb = thumbnail_mode_with_rerendered_video(new_player, work_area, monkeypatch)
    vanishing = listed_path(player, "FL_003.mov")
    rerender(vanishing, time.time() - 100)
    real_generate = player.generate_thumbnail

    def remove_then_generate(file_path, *args, **kwargs):
        if paths.same_path(file_path, vanishing):
            os.remove(vanishing)  # 다른 PC에서 지움
        return real_generate(file_path, *args, **kwargs)

    monkeypatch.setattr(player, "generate_thumbnail", remove_then_generate)
    started = record_worker_starts(monkeypatch)
    capsys.readouterr()

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    assert started == [changed]
    assert "새로고침: 썸네일 확인 3개, 다시 만듦 1개" in capsys.readouterr().out
    assert player.thumbnailProgressBar.format() == "썸네일 생성 완료"
    assert list_warnings(dialogs) == []


@pytest.mark.parametrize("rerendered", [True, False], ids=["one_rerendered", "none"])
def test_manual_refresh_shows_progress(new_player, dialogs, work_area, monkeypatch, rerendered):
    """새로고침의 썸네일 확인도 썸네일 버튼처럼 진행바에 (예전 진행바 글자가 남지 않음)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    turn_on_thumbnail_mode(player)
    base = settle_thumbnail_times(player)
    if rerendered:
        rerender(listed_path(player, "FL_002.mov"), base)
    bar = player.thumbnailProgressBar
    bar.setFormat("썸네일 생성 멈춤 (목록이 바뀜)")  # 전에 멈춘 반복의 글자
    values = []
    bar.valueChanged.connect(values.append)
    before = len(dialogs.messages)

    press_refresh(player)
    wait_refreshed(player)
    wait_thumbnails(player)

    if rerendered:
        assert (bar.format(), bar.maximum(), bar.value()) == ("썸네일 생성 완료", 1, 1)
        assert 0 in values
    else:
        assert (bar.format(), bar.value()) == ("썸네일 모두 디스크에 저장됨", bar.maximum())
    assert bar.isVisibleTo(player)
    assert [m for m in dialogs.messages[before:] if m[1] == "썸네일 생성 완료"] == []  # 새로고침은 완료 창을 띄우지 않음


def test_refresh_folder_source(new_player, dialogs, tmp_path):
    """폴더 불러오기(폴더 선택·북마크): 하위 폴더까지 같은 규칙(번호 순서)으로 다시 읽음."""
    folder = tmp_path / "clips"
    for name in ("clip1.mov", "sub/clip10.mov", "clip3.mov"):
        write_test_video(str(folder / name))
    player = new_player(make_config(str(tmp_path), {}))
    player.load_videos_from_folder(str(folder))
    assert listed(player) == ["clip1.mov", "clip3.mov", "clip10.mov"]
    context = items_by_name(player)["clip1.mov"].data(THUMBNAIL_CONTEXT_ROLE)

    os.remove(folder / "clip3.mov")
    write_test_video(str(folder / "sub" / "clip2.mov"))
    refresh(player)

    assert listed(player) == ["clip1.mov", "clip2.mov", "clip10.mov"]
    assert items_by_name(player)["clip2.mov"].data(THUMBNAIL_CONTEXT_ROLE) == context
    assert list_warnings(dialogs) == []


def test_refresh_appended_folder_and_job_each_with_own_rules(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """job 목록 + 사이드바에 끌어다 놓아 덧붙인 폴더: 출처마다 원래 규칙으로 다시 읽고, 새 영상은 그 출처의 썸네일 자리."""
    player, job = open_job(new_player, work_area, monkeypatch)
    job_thumbs = player.current_thumbnail_folder
    dropped = tmp_path / "other"
    write_test_video(str(dropped / "c1.mov"))
    write_test_video(str(dropped / "c2.mov"))
    drop_folder(player, "sidebar", dropped)
    dropped_thumbs = player.current_thumbnail_folder
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov", "c1.mov", "c2.mov"]

    close_open_video(player)
    shutil.rmtree(os.path.join(job, "scene-001"))
    add_scene(job, "004")
    os.remove(dropped / "c1.mov")
    write_test_video(str(dropped / "deeper" / "c3.mov"))
    refresh(player)

    assert listed(player) == ["FL_002.mov", "FL_003.mov", "FL_004.mov", "c2.mov", "c3.mov"]
    after = items_by_name(player)
    assert after["FL_004.mov"].data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=job_thumbs)
    assert after["c3.mov"].data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=dropped_thumbs)


def test_refresh_dropped_files_kept_while_they_exist(new_player, dialogs, tmp_path):
    keep = write_test_video(str(tmp_path / "files" / "keep.mov"))
    gone = write_test_video(str(tmp_path / "files" / "gone.mov"))
    write_test_video(str(tmp_path / "files" / "not_dropped.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([keep, gone])
    assert listed(player) == ["gone.mov", "keep.mov"]

    os.remove(gone)
    refresh(player)

    assert listed(player) == ["keep.mov"]  # 같은 폴더의 다른 파일은 넣지 않음 (폴더를 끌어다 놓지 않았음)
    assert list_warnings(dialogs) == []


def test_refresh_keeps_top_visible_item(new_player, dialogs, tmp_path):
    """위쪽 영상이 빠져도 보고 있던 자리(맨 위에 보이는 영상)가 그대로."""
    folder = tmp_path / "many"
    write_test_video(str(folder / "v00.mov"))
    for i in range(1, 60):
        (folder / f"v{i:02d}.mov").parent.mkdir(parents=True, exist_ok=True)
        (folder / f"v{i:02d}.mov").write_bytes(b"x")  # 목록 규칙은 이름만 봄
    player = new_player(make_config(str(tmp_path), {}))
    player.load_videos_from_folder(str(folder))
    player.resize(900, 600)
    player.show()
    pump(200)
    top = items_by_name(player)["v30.mov"]
    player.sidebar.scrollToItem(top, QAbstractItemView.PositionAtTop)
    QApplication.processEvents()
    assert player.sidebar.itemAt(QPoint(5, 5)) is top

    for i in range(1, 11):
        os.remove(folder / f"v{i:02d}.mov")
    refresh(player)

    assert player.sidebar.count() == 50
    assert player.sidebar.itemAt(QPoint(5, 5)) is top


# ---- 리뷰 M1: 없어진 영상·폴더는 위로 올라가며 확인 ----

def test_dropped_file_whose_scene_folder_was_deleted_is_removed(new_player, dialogs, tmp_path):
    """따로 끌어다 놓은 …/scene-Z007/frames/X.mov의 scene-Z007이 통째로 지워짐 → 목록에서 빠짐 (예전에는 바로 위
    frames 폴더도 없어 'NAS 문제'로 영원히 남았음)."""
    gone = write_test_video(str(tmp_path / "job" / "scene-Z007" / "frames" / "Z007.mov"))
    keep = write_test_video(str(tmp_path / "job" / "scene-Z008" / "frames" / "Z008.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([gone, keep])

    shutil.rmtree(tmp_path / "job" / "scene-Z007")
    refresh(player)

    assert listed(player) == ["Z008.mov"]
    assert list_warnings(dialogs) == []


def test_folder_source_whose_parent_was_deleted_is_removed(new_player, dialogs, tmp_path):
    folder = tmp_path / "work" / "S1" / "clips"
    write_test_video(str(folder / "a.mov"))
    (tmp_path / "work" / "S2").mkdir()  # 남은 시즌 (위 폴더가 비면 '확인하지 못함')
    player = new_player(make_config(str(tmp_path), {}))
    player.load_videos_from_folder(str(folder))
    assert listed(player) == ["a.mov"]

    close_open_video(player)
    shutil.rmtree(tmp_path / "work" / "S1")
    refresh(player)
    refresh(player)

    assert listed(player) == []
    assert [title for title, _text in list_warnings(dialogs)] == ["목록 폴더 없음"]


def test_missing_video_on_unreachable_share_is_not_called_gone(new_player, dialogs, work_area, monkeypatch):
    """리뷰 L6: 공유가 끊겨(Windows는 FileNotFoundError) 영상을 확인하지 못하면 '디스크에 없는 영상'이 아니라 확인하지 못했다고,
    목록은 다시 읽지 않음 (목록 폴더도 읽지 못함)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    scans = count_scans(monkeypatch)
    monkeypatch.setattr(video_list, "_inside_share", lambda folder: (False, "공유를 붙이는 곳까지 올라감 (시험)"))
    target = items_by_name(player)["FL_002.mov"]
    shutil.rmtree(os.path.join(job, "scene-002"))

    player.on_sidebar_item_clicked(target)
    wait_refreshed(player)

    warnings = list_warnings(dialogs)
    assert [title for title, _text in warnings] == ["영상을 열 수 없음"]
    assert "디스크에 없는 영상" not in warnings[0][1] and "FileNotFoundError" in warnings[0][1]
    assert "공유를 붙이는 곳까지 올라감 (시험)" in warnings[0][1]  # 없어진 것으로 보지 않은 까닭 (2차 검토 L4)
    assert scans == []


def test_click_on_missing_item_keeps_frame_cache(new_player, dialogs, work_area, monkeypatch):
    """리뷰 L13: 열지 못한 영상을 눌러도 보던 영상의 프레임 캐시는 지우지 않음 (열었을 때만 open_file이 지움)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    cleared = []
    monkeypatch.setattr(player, "clear_cache", lambda: cleared.append(True))
    target = items_by_name(player)["FL_002.mov"]
    shutil.rmtree(os.path.join(job, "scene-002"))
    player.on_sidebar_item_clicked(target)
    wait_refreshed(player)
    assert cleared == []
    player.on_sidebar_item_clicked(items_by_name(player)["FL_003.mov"])
    assert cleared == [True]


# ---- 리뷰 M3: 읽지 못한 폴더를 불러오면 창 한 번 ----

def test_unreadable_folder_load_one_box(new_player, dialogs, tmp_path, monkeypatch):
    """폴더 불러오기·북마크: 폴더를 읽지 못하면 그 오류만 한 번 — '지원되는 비디오 파일이 없습니다'(틀린 말)도, 다시 읽기의
    다른 문구 창도 없음. 연결이 돌아오면 F5로 목록이 생김."""
    folder = tmp_path / "clips"
    write_test_video(str(folder / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    real_scandir = os.scandir
    down = {"on": True}

    def scandir(path="."):
        if down["on"] and not isinstance(path, int) and os.path.normpath(os.fspath(path)) == str(folder):
            raise PermissionError(errno.EACCES, "Permission denied", str(folder))
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    player.load_videos_from_folder(str(folder))
    refresh(player)

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "목록 폴더를 읽지 못함")]
    down["on"] = False
    refresh(player)
    assert listed(player) == ["a.mov"]


@pytest.mark.parametrize("target", ["video", "sidebar"])
def test_unreadable_dropped_folder_one_box_keeps_list(new_player, dialogs, work_area, tmp_path, monkeypatch, target):
    player, _job = open_job(new_player, work_area, monkeypatch)
    folder = tmp_path / "dropped"
    write_test_video(str(folder / "a.mov"))
    fail_scandir_of(monkeypatch, str(folder), PermissionError(errno.EACCES, "Permission denied", str(folder)))

    drop_folder(player, target, folder)

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "목록 폴더를 읽지 못함")]
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov"]  # 보던 목록을 비우지 않음


# ---- 리뷰 M4: 선택 재생 중 없는 영상 여러 개 ----

def test_playlist_many_missing_one_box_one_scan(new_player, dialogs, work_area, monkeypatch):
    player, job = open_job(new_player, work_area, monkeypatch, scenes=("001", "002", "003", "004", "005"))
    scans = count_scans(monkeypatch)
    for item in items_by_name(player).values():
        item.setSelected(True)
    for scene in ("002", "003", "004"):
        shutil.rmtree(os.path.join(job, f"scene-{scene}"))
    try:
        player.play_selected_files()
        assert os.path.basename(player.filename_a) == "FL_001.mov"
        player.handle_video_end()  # FL_001이 끝남 → FL_002~004는 없음 → FL_005
        wait_refreshed(player)
        assert os.path.basename(player.filename_a) == "FL_005.mov"
        assert player.is_playlist_playing
        warnings = list_warnings(dialogs)
        assert [title for title, _text in warnings] == ["영상 없음"]
        assert "3개" in warnings[0][1] and all(f"FL_{s}.mov" in warnings[0][1] for s in ("002", "003", "004"))
        assert len(scans) == 1
        assert [os.path.basename(p) for p in player.playlist] == ["FL_001.mov", "FL_005.mov"]
        assert listed(player) == ["FL_001.mov", "FL_005.mov"]
    finally:
        player.stop_video()


def test_playlist_all_missing_keeps_current_video(new_player, dialogs, work_area, monkeypatch):
    """선택한 영상이 모두 없으면 보던 영상을 멈추지 않고 선택 재생만 끝냄 ('모두 재생함' 창도 없음)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    playing = player.filename_a
    stops = []
    monkeypatch.setattr(player, "stop_video", lambda: stops.append(True))
    items = items_by_name(player)
    for name in ("FL_002.mov", "FL_003.mov"):
        items[name].setSelected(True)
    for scene in ("002", "003"):
        shutil.rmtree(os.path.join(job, f"scene-{scene}"))

    player.play_selected_files()
    wait_refreshed(player)

    assert stops == []
    assert player.filename_a == playing
    assert not player.is_playlist_playing
    assert [title for _kind, title, _text in dialogs.messages] == ["영상 없음"]


# ---- 리뷰 L7·L8·L9 ----

def test_refresh_error_still_records_time(new_player, dialogs, work_area, monkeypatch):
    """리뷰 L7: 결과를 넣다 예외가 나도 마지막으로 읽은 때를 남김 (창 → 활성 → 다시 읽기 → 창이 되풀이되지 않게)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    monkeypatch.setattr(video_list, "plan_refresh", lambda *args: (_ for _ in ()).throw(RuntimeError("계획 실패")))
    release, calls = block_reads(monkeypatch)
    player.refresh_sidebar()
    wait_until(lambda: calls)
    player._sidebar_refreshed_at = None  # 읽기를 시작할 때 남긴 것은 지움 — 결과를 넣을 때(예외가 나도) 남겨야 함
    release.set()
    wait_until(lambda: errors)
    wait_refreshed(player)
    assert "계획 실패" in str(errors[0][1])
    assert player._sidebar_refreshed_at is not None
    assert time.monotonic() - player._sidebar_refreshed_at < ACTIVATION_GAP


ACTIVATION_GAP = 2.0


def test_dropping_folder_with_its_subfolder_refresh_is_no_op(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """리뷰 L8: A와 A/sub를 함께 끌어다 놓으면 A/sub의 영상은 두 번 들어옴(처음 불러오기 그대로) — 다시 읽어도 그대로
    (출처마다 한 번씩: 세 번째가 생기지 않음)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    folder = tmp_path / "A"
    write_test_video(str(folder / "a.mov"))
    write_test_video(str(folder / "sub" / "b.mov"))
    from PyQt5.QtCore import QMimeData, QPointF, QUrl
    from PyQt5.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(folder / "sub"))])
    player.videoWidget.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    before = listed(player)
    assert sorted(before) == ["a.mov", "b.mov", "b.mov"]

    refresh(player)
    assert listed(player) == before


def test_refresh_during_job_load_box_does_not_double_list(new_player, pumping_dialogs, work_area, monkeypatch):
    """리뷰 L9: job을 고를 때 읽지 못한 하위 폴더 창이 떠 있는 동안 다시 읽어도 목록이 두 배가 되지 않음."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    job2 = os.path.join(player.current_job_path, os.pardir, "job_02")
    write_test_video(os.path.join(work_area.local, "S1", "job_02", "scene-002", "frames", "other2.mov"))
    locked = os.path.normpath(os.path.join(job2, "scene-002", "frames"))
    fail_scandir_of(monkeypatch, locked, PermissionError(errno.EACCES, "Permission denied", locked))
    real_warning = QMessageBox.warning

    def warning_and_refresh(parent, title, text, *args, **kwargs):
        player.refresh_sidebar()  # 창이 떠 있는 동안 F5·창이 다시 활성
        pump(300)
        return real_warning(parent, title, text, *args, **kwargs)

    monkeypatch.setattr(QMessageBox, "warning", warning_and_refresh)
    choose(player, "job_02")
    wait_refreshed(player)
    assert listed(player) == ["other.mov"]


# ---- 다시 읽기는 GUI 밖 스레드에서 ----

def test_one_read_in_flight_and_one_queued(new_player, dialogs, work_area, monkeypatch):
    """읽는 동안 들어온 요청은 몇 번이든 한 번으로 모아 끝난 뒤 다시 읽음. 그동안 창은 이벤트를 처리함(멈추지 않음)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    release, calls = block_reads(monkeypatch)
    player.refresh_sidebar()
    wait_until(lambda: len(calls) == 1)
    add_scene(job, "004")
    for _ in range(3):
        player.refresh_sidebar()
    pump(100)
    assert len(calls) == 1 and player._sidebar_scan.isRunning()
    release.set()
    wait_refreshed(player)
    assert len(calls) == 2
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov", "FL_004.mov"]


@pytest.mark.parametrize("requested", [False, True], ids=["no_request", "refresh_requested"])
def test_stale_result_discarded_when_list_changed(new_player, dialogs, work_area, monkeypatch, requested):
    """읽는 동안 목록이 바뀌면(다른 job을 고름) 그 결과는 버림 — 예전 job의 영상이 섞이지 않음. 새로 불러온 목록은 방금
    디스크에서 읽은 것이므로 다시 읽지 않고, 읽는 동안 다시 읽어 달라는 요청이 왔을 때만 한 번 더 (2차 검토 M2)."""
    player, job = open_job(new_player, work_area, monkeypatch)
    release, calls = block_reads(monkeypatch)
    add_scene(job, "004")  # 예전 결과를 넣으면 job_02 목록에 FL_004가 생김
    player.refresh_sidebar()
    wait_until(lambda: len(calls) == 1)
    player.jobComboBox.setCurrentText("job_02")
    assert listed(player) == ["other.mov"]
    write_test_video(os.path.join(work_area.local, "S1", "job_02", "scene-002", "frames", "other2.mov"))
    if requested:
        player.refresh_sidebar()  # 예: F5 — 읽는 중이라 끝난 뒤 한 번 더
    release.set()
    wait_refreshed(player)
    if requested:
        assert len(calls) == 2
        assert listed(player) == ["other.mov", "other2.mov"]
    else:
        assert len(calls) == 1
        assert listed(player) == ["other.mov"]
    assert list_warnings(dialogs) == []


def test_playlist_not_advanced_twice_when_video_ends_under_box(new_player, dialogs, work_area, monkeypatch):
    """2차 검토 M1: 보던 영상이 재생 중일 때 선택 재생을 시작했는데 첫 영상이 없음 → '영상 없음' 창이 떠 있는 동안(모달 창처럼
    이벤트 처리) 보던 영상이 끝나도 선택 재생을 거기서 또 진행하지 않음 (예전에는 FL_004를 두 번 열고 FL_003을 건너뜀)."""
    player, job = open_job(new_player, work_area, monkeypatch, scenes=("001", "002", "003", "004"))
    opened = []
    real_open = player.open_file

    def recording_open(kind, path=None):
        ok = real_open(kind, path)
        if ok:
            opened.append(os.path.basename(path))
        return ok

    monkeypatch.setattr(player, "open_file", recording_open)
    ended = []
    real_end = player.handle_video_end
    monkeypatch.setattr(player, "handle_video_end", lambda: (ended.append(True), real_end()))
    player.timer.timeout.disconnect()
    player.timer.timeout.connect(player.next_frame_playback)  # 끝나면 위의 handle_video_end를 거치게 (self.를 다시 찾음)

    def box(parent, title, text, *args, **kwargs):
        dialogs.messages.append(("warning", title, text))
        wait_until(lambda: ended, timeout=10)  # 모달 창이 떠 있는 동안 보던 영상(1초)이 끝남
        pump(100)
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", box)
    items = items_by_name(player)
    for name in ("FL_002.mov", "FL_003.mov", "FL_004.mov"):
        items[name].setSelected(True)
    shutil.rmtree(os.path.join(job, "scene-002"))
    player.play_video()  # FL_001 재생 중
    try:
        player.play_selected_files()
        wait_refreshed(player)
        assert ended
        assert opened == ["FL_003.mov"]
        assert [os.path.basename(p) for p in player.playlist] == ["FL_003.mov", "FL_004.mov"]
        assert player.current_playlist_index == 0
        assert player.is_playlist_playing
    finally:
        player.stop_video()


def test_play_button_shows_play_when_video_ended_under_box_and_nothing_played(new_player, dialogs, work_area, monkeypatch):
    """3차 확인: 선택한 영상이 모두 없어 '영상 없음' 창이 떠 있는 동안 보던 영상이 끝남 → 선택 재생을 끝낼 때 재생 버튼이
    'Pause'로 남지 않고 'Play' (재생은 이미 멈춤)."""
    player, job = open_job(new_player, work_area, monkeypatch, scenes=("001", "002", "003"))
    ended = []
    real_end = player.handle_video_end
    monkeypatch.setattr(player, "handle_video_end", lambda: (ended.append(True), real_end()))
    player.timer.timeout.disconnect()
    player.timer.timeout.connect(player.next_frame_playback)  # 끝나면 위의 handle_video_end를 거치게 (self.를 다시 찾음)

    def box(parent, title, text, *args, **kwargs):
        dialogs.messages.append(("warning", title, text))
        wait_until(lambda: ended, timeout=10)  # 모달 창이 떠 있는 동안 보던 영상(1초)이 끝남
        pump(100)
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", box)
    items = items_by_name(player)
    for name in ("FL_002.mov", "FL_003.mov"):
        items[name].setSelected(True)
    for scene in ("002", "003"):
        shutil.rmtree(os.path.join(job, f"scene-{scene}"))
    player.play_video()  # FL_001 재생 중 → 버튼 'Pause'
    try:
        player.play_selected_files()
        wait_refreshed(player)
        assert ended
        assert not player.is_playlist_playing
        assert not player.timer.isActive()
        assert player.playPauseButton.text() == "Play"
    finally:
        player.stop_video()


def test_unverifiable_source_box_says_why(new_player, dialogs, work_area, monkeypatch):
    """2차 검토 L4: 없어진 것으로 보지 않은 까닭(확인한 위 폴더와 그 상태)을 창에. 예: 시즌의 job을 모두 지워 시즌 폴더가 빔
    → 떼고 남은 마운트 폴더와 구별할 수 없어 목록은 그대로 두고 그 까닭을 알림."""
    player, job = open_job(new_player, work_area, monkeypatch)
    close_open_video(player)
    shutil.rmtree(job)
    shutil.rmtree(os.path.join(work_area.local, "S1", "job_02"))
    refresh(player)
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov"]
    warnings = list_warnings(dialogs)
    assert [title for title, _text in warnings] == ["목록 폴더를 읽지 못함"]
    assert "비어 있음" in warnings[0][1] and "S1" in warnings[0][1]


def test_reselecting_job_that_failed_at_selection_loads_it(new_player, dialogs, work_area, monkeypatch):
    """2차 검토 L8: 고를 때 읽지 못한 job(목록 비어 있음)을 연결이 돌아온 뒤 다시 고르면 처음 고를 때처럼 불러옴 — job 경로·
    썸네일 폴더·첫 영상까지 (다시 읽기로 영상만 넣지 않음)."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    real_stat = os.stat
    down = {"on": True}

    def stat(path, *args, **kwargs):
        if down["on"] and os.path.basename(os.path.normpath(os.fspath(path))) == "job_02":
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    choose(player, "job_02")
    wait_refreshed(player)
    assert listed(player) == []
    down["on"] = False
    choose(player, "job_02")  # 같은 job을 다시 고름
    wait_refreshed(player)
    assert listed(player) == ["other.mov"]
    assert os.path.basename(player.filename_a) == "other.mov"
    assert os.path.basename(os.path.normpath(player.current_job_path)) == "job_02"
    assert player.current_thumbnail_folder and "job_02" in player.current_thumbnail_folder


def test_unreadable_dropped_folder_recovers_with_f5(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """2차 검토 L9: 읽지 못한 끌어다 놓은 폴더도 기억 → 연결이 돌아오면 새로고침(F5)으로 목록에 들어옴."""
    player, _job = open_job(new_player, work_area, monkeypatch)
    folder = tmp_path / "dropped"
    write_test_video(str(folder / "a.mov"))
    real_scandir = os.scandir
    down = {"on": True}

    def scandir(path="."):
        if down["on"] and not isinstance(path, int) and os.path.normpath(os.fspath(path)) == str(folder):
            raise PermissionError(errno.EACCES, "Permission denied", str(folder))
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    drop_folder(player, "sidebar", folder)
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov"]
    down["on"] = False
    refresh(player)
    assert listed(player) == ["FL_001.mov", "FL_002.mov", "FL_003.mov", "a.mov"]


_CLOSE_SCRIPT = r"""
import gc
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
folder = sys.argv[2]
from PyQt5.QtWidgets import QApplication, QMessageBox

app = QApplication([])
for kind in ("critical", "warning", "information"):
    setattr(QMessageBox, kind, staticmethod(lambda *a, **k: QMessageBox.Ok))
from yesoncheck import player_base, video_list
from yesoncheck.main_window import VideoPlayer

release = threading.Event()
real_read = video_list.read_sources


def slow_read(sources, files):
    release.wait(10)  # 응답이 느린 NAS
    return real_read(sources, files)


video_list.read_sources = slow_read
player = VideoPlayer()
player.load_videos_from_folder(folder)
if sys.argv[3] == "error_before":
    def broken_stop(*args, **kwargs):
        raise RuntimeError("다른 작업 정리 중 오류")
    player.stop_running_jobs = broken_stop  # 창 닫기의 앞쪽 정리에서 오류
applied = []
player._on_sidebar_scanned = lambda scan: applied.append(scan)
player.refresh_sidebar()
assert player._sidebar_scan is not None and player._sidebar_scan.isRunning()
player.close()  # 읽는 중에 창을 닫음 → 끝날 때까지 붙잡아 둠 (창은 기다리지 않음)
assert player._sidebar_scan is None
assert len(player_base._RELEASED_WORKERS) == 1, player_base._RELEASED_WORKERS
del player
gc.collect()  # 창이 사라져도 읽기 스레드는 남아 있어야 함
release.set()
assert player_base.wait_for_released_workers(10) == []
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
assert applied == []  # 닫힌 창에 결과를 넣지 않음
print("CLOSE OK")
"""


@pytest.mark.parametrize("scenario", ["plain", "error_before"])
def test_close_with_read_in_flight(tmp_path, scenario):
    """읽는 중에 창을 닫아도 실행 중인 스레드가 파괴되지 않고(앱이 죽지 않음), 닫힌 창에 결과를 넣지 않음. 창 닫기의 다른
    정리에서 오류가 나도 읽기 스레드는 놓음 (2차 검토 L6). 죽는 것(abort) 자체를 확인하므로 새 파이썬 프로세스에서
    (test_ocr_worker_lifetime과 같은 방식)."""
    folder = tmp_path / "clips"
    write_test_video(str(folder / "a.mov"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               YESONCHECK_CONFIG_DIR=make_config(str(tmp_path), {}))
    result = subprocess.run([sys.executable, "-c", _CLOSE_SCRIPT, ROOT, str(folder), scenario], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    output = f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Destroyed while thread is still running" not in result.stderr, output
    assert result.returncode == 0, output
    assert "CLOSE OK" in result.stdout, output
