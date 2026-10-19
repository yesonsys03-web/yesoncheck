"""작품 → 시즌 → job 순서: 시즌이 있는 작품은 시즌을 고르기 전에는 job 목록이 비어 있고('job선택'만), job을 고르기
전에는 어떤 폴더도 영상 목록으로 읽지 않음.

사용자 보고: 작품만 고르고 시즌은 고르지 않았는데 job 목록에 작품 폴더의 하위 폴더(시즌 폴더들·라이브러리 폴더 …)가
보였음. 시즌 목록을 비울 때(clear) Qt가 빈 글자로 currentIndexChanged(-1)를 보내는데 update_job_list는 '시즌선택'이 아닌
글자를 시즌으로 여겨 os.path.join(작품 폴더, "") = 작품 폴더를 시즌 폴더처럼 읽었고, 이어서 온 '시즌선택'(0번)에서는 job
목록을 그대로 두었음. _load_job_list도 빈 job을 job으로 여겨 작품·시즌 폴더를 job 폴더처럼 읽었음.
"""

import os

import pytest
from PyQt5.QtCore import Qt

from yesoncheck import video_list
from tests.conftest import write_test_video
from tests.test_sidebar_refresh import choose, listed
from tests.test_work_paths_ui import combo_items, make_config, new_player  # noqa: F401 (new_player: fixture)


def norm(path):
    return os.path.normcase(os.path.normpath(path))


@pytest.fixture
def reads(monkeypatch):
    """폴더 읽기를 기록: listdir(시즌·job 목록)과 video_list.scan_job(job 폴더의 영상 목록) — 앱이 쓰는 경로로."""
    record = type("Reads", (), {})()
    record.listdir = []
    record.scans = []
    real_listdir = os.listdir
    real_scan_job = video_list.scan_job

    def listdir(path="."):
        if isinstance(path, str):
            record.listdir.append(norm(path))
        return real_listdir(path)

    def scan_job(work, base_path):
        record.scans.append((work, norm(base_path)))
        return real_scan_job(work, base_path)

    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(video_list, "scan_job", scan_job)
    return record


def write_season_work(root):
    """시즌이 있는 작품 BB: 시즌 폴더 둘과 시즌이 아닌 폴더(BB_library — 그 아래 영상도 둠: 작품 폴더를 job처럼 읽으면
    목록에 들어옴)."""
    write_test_video(os.path.join(root, "BB_Season1", "job_01", "scene-001", "frames", "a.mov"))
    write_test_video(os.path.join(root, "BB_Season1", "job_02", "scene-001", "frames", "b.mov"))
    write_test_video(os.path.join(root, "BB_Season2", "job_03", "scene-001", "frames", "c.mov"))
    write_test_video(os.path.join(root, "BB_library", "frames", "lib.mov"))


def season_player(new_player, work_area):
    """작품 BB(시즌 있음)와 SMOKE(시즌 있음, 모든 폴더가 시즌)."""
    write_season_work(os.path.join(work_area.local, "bb"))
    write_test_video(os.path.join(work_area.local, "smoke", "S1", "job_09", "scene-001", "frames", "s.mov"))
    write_test_video(os.path.join(work_area.local, "smoke", "extra", "frames", "root.mov"))  # 작품 폴더를 job처럼 읽으면 들어옴
    return new_player(make_config(work_area.local, {"BB": work_area.stored + "/bb", "SMOKE": work_area.stored + "/smoke"},
                                  work_area.path_map))


def under(record, folder):
    """record.listdir 중 folder와 그 아래 폴더."""
    folder = norm(folder)
    return [p for p in record.listdir if p == folder or p.startswith(folder + os.sep)]


def test_season_work_lists_jobs_only_after_season(new_player, dialogs, work_area, reads):
    player = season_player(new_player, work_area)
    player.workComboBox.setCurrentText("BB")
    root = player.get_work_path("BB")  # 앱이 쓰는 경로 (Windows는 UNC)
    assert combo_items(player.seasonComboBox) == ["시즌선택", "BB_Season1", "BB_Season2"]
    assert combo_items(player.jobComboBox) == ["job선택"]  # 예전: ["job선택", "BB_Season1", "BB_Season2", "BB_library"]
    assert under(reads, root) == [norm(root)]  # 작품 폴더는 시즌 목록으로 한 번만 (job 목록으로 읽지 않음)
    assert reads.scans == [] and listed(player) == []

    player.seasonComboBox.setCurrentText("BB_Season1")
    assert combo_items(player.jobComboBox) == ["job선택", "job_01", "job_02"]
    assert under(reads, root) == [norm(root), norm(os.path.join(root, "BB_Season1"))]
    assert reads.scans == [] and listed(player) == []  # job을 고르기 전에는 영상 목록을 만들지 않음

    player.seasonComboBox.setCurrentText("시즌선택")
    assert combo_items(player.jobComboBox) == ["job선택"]
    assert reads.scans == [] and listed(player) == []
    assert len(under(reads, root)) == 2  # 시즌을 되돌릴 때 읽지 않음
    assert dialogs.errors() == []


def test_choosing_job_loads_videos_and_placeholder_loads_nothing(new_player, dialogs, work_area, reads):
    player = season_player(new_player, work_area)
    player.workComboBox.setCurrentText("BB")
    player.seasonComboBox.setCurrentText("BB_Season1")
    season = os.path.join(player.get_work_path("BB"), "BB_Season1")
    player.jobComboBox.setCurrentText("job_01")
    assert listed(player) == ["a.mov"]
    assert reads.scans == [("BB", norm(os.path.join(season, "job_01")))]
    assert player.current_thumbnail_folder and paths_equal(player.current_job_path, os.path.join(season, "job_01"))

    choose(player, "job선택")  # 사용자가 'job선택'을 고름 (currentIndexChanged + activated)
    assert player.jobComboBox.currentIndex() == 0
    assert listed(player) == [] and len(reads.scans) == 1  # job의 목록을 비우기만 하고 어떤 폴더도 읽지 않음
    assert player.current_thumbnail_folder is None and player.current_job_path is None
    choose(player, "job선택")  # 이미 'job선택' → activated만
    player.jobComboBox.activated.emit(0)
    assert listed(player) == [] and len(reads.scans) == 1

    choose(player, "job_02")  # 다른 job: 한 번 읽음 (activated는 다시 읽지 않음)
    assert listed(player) == ["b.mov"]
    assert reads.scans[1:] == [("BB", norm(os.path.join(season, "job_02")))]
    assert combo_items(player.jobComboBox) == ["job선택", "job_01", "job_02"]
    assert dialogs.errors() == []


def test_switching_season_work_clears_job_and_list(new_player, dialogs, work_area, reads):
    """시즌·job까지 고른 뒤 다른 (시즌이 있는) 작품으로 바꾸면 job은 'job선택'만, 사이드바의 job 목록은 비움.
    새 작품 폴더의 하위 폴더는 job으로 보이지 않고, 작품·시즌 폴더를 영상 목록으로 읽지 않음."""
    player = season_player(new_player, work_area)
    player.workComboBox.setCurrentText("BB")
    player.seasonComboBox.setCurrentText("BB_Season1")
    player.jobComboBox.setCurrentText("job_01")
    assert listed(player) == ["a.mov"] and len(reads.scans) == 1

    player.workComboBox.setCurrentText("SMOKE")
    smoke = player.get_work_path("SMOKE")
    assert combo_items(player.seasonComboBox) == ["시즌선택", "S1", "extra"]  # 이 작품은 모든 폴더가 시즌 (예전 규칙 그대로)
    assert combo_items(player.jobComboBox) == ["job선택"]
    assert listed(player) == [] and len(reads.scans) == 1
    assert under(reads, smoke) == [norm(smoke)]
    # 예전 job의 썸네일 자리는 잊음: 이제 끌어다 놓는 파일의 썸네일이 예전 job 폴더에 저장되지 않게
    assert player.current_thumbnail_folder is None and player.current_job_path is None

    player.seasonComboBox.setCurrentText("S1")
    assert combo_items(player.jobComboBox) == ["job선택", "job_09"]
    player.jobComboBox.setCurrentText("job_09")
    assert listed(player) == ["s.mov"]
    assert reads.scans[1:] == [("SMOKE", norm(os.path.join(smoke, "S1", "job_09")))]
    assert dialogs.errors() == []


@pytest.mark.parametrize("work", ["The_Johnsons", "TJS_Animatic"])
def test_no_season_work_lists_jobs_directly(new_player, dialogs, work_area, reads, work):
    """시즌이 없는 작품: 작품을 고르면 작품 폴더 바로 아래의 job (예전 그대로). 영상은 job을 고른 뒤에만 —
    TJS_Animatic은 예전에 job을 고르지 않아도 모든 job의 영상을 보였음 (이제 job을 고르기 전에는 비어 있음)."""
    works = os.path.join(work_area.local, "works")
    write_test_video(os.path.join(works, "TJS_921", "a.mov"))
    write_test_video(os.path.join(works, "TJS_922", "b.mov"))
    os.makedirs(os.path.join(works, "library"))
    player = new_player(make_config(work_area.local, {work: work_area.stored + "/works"}, work_area.path_map))
    player.workComboBox.setCurrentText(work)
    root = player.get_work_path(work)
    assert combo_items(player.seasonComboBox) == ["시즌선택"]
    assert combo_items(player.jobComboBox) == ["job선택", "TJS_921", "TJS_922"]
    assert listed(player) == [] and reads.scans == []

    player.jobComboBox.setCurrentText("TJS_921")
    assert listed(player) == ["a.mov"]
    assert reads.scans == [(work, norm(os.path.join(root, "TJS_921")))]
    assert paths_equal(player.sidebar.item(0).data(Qt.UserRole), os.path.join(root, "TJS_921", "a.mov"))

    choose(player, "job선택")
    assert listed(player) == [] and len(reads.scans) == 1
    assert dialogs.errors() == []


def paths_equal(a, b):
    return a is not None and norm(a) == norm(b)
