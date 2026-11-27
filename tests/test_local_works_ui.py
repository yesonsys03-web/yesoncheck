"""회사 밖 PC의 작품 고르기 — 사내 공유 설정(NAS)을 찾지 못한 PC에서 '작품 경로 관리'가 그 PC만의 작품 목록을 열고, 등록한 작품을
작품 → 폴더 → 폴더로 골라 영상 목록을 봄 (저장·규칙은 test_local_works).

사용자 (2026-11-27): 회사 밖 컴에서 작품 경로 관리를 누르면 "공유 설정에 문제가 있어 작품 경로를 관리할 수 없습니다 … Traceback" 창이 뜨고
창 제목에 "공유 설정 오류 (작품 목록 없음)"가 붙음 → "앱 타이틀 바에 공유설정 오류 메시지 표시는 필요없어", "이 기능을 외부 컴에서도
사용할 수 있게", "작품 폴더/시즌/job/영상 구조로만 구성되게 하면 안 돼. 이건 회사마다 상황이 다를 수 있어서" → 작품마다 단계 수(0·1·2),
영상은 마지막으로 고른 폴더 아래를 폴더 열기와 같은 규칙으로.

이 OS 그대로 돈다 (Mac은 공유 설정의 자리가 없는 Mac, Windows CI는 정해 둔 폴더·네트워크 드라이브가 없는 PC). 예시 이름만 씀.
"""

import json
import os
import shutil
import sys

import pytest
from PyQt5.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox, QPushButton

from tests import ui_texts
from tests.conftest import write_test_video
from tests.test_fast_startup import wait_until
from tests.test_mac_mounts import NO_SUCH_CONFIG
from tests.test_sidebar_refresh import wait_refreshed
from tests.test_work_paths_ui import combo_items, make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import hover_strip, local_works, path_map_setup, paths, shared_config, video_list, work_picker
from yesoncheck.local_works import LocalWork

FOLDER = "폴더선택"  # 이 PC의 작품에서 둘째·셋째 콤보의 안내 항목 (사내 작품은 '시즌선택'·'job선택')
MANAGER_TITLE = "작품 경로 관리 (이 PC)"


@pytest.fixture
def outside(qapp, dialogs, monkeypatch, tmp_path):
    """회사 밖 PC에서 app.launch처럼 켠 창을 만드는 함수: 공유 설정 없이 만들어 보인 뒤 뒤 스레드로 읽음 → 찾지 못함.
    (시험이 켜기 전에 이 PC의 설정 파일을 먼저 적어 둘 수 있게 함수로)"""
    from yesoncheck.main_window import VideoPlayer

    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))  # PC별 설정 없음
        monkeypatch.setenv("SystemDrive", str(tmp_path / "sysdrive"))  # Harmony식 폴더 없음
        monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: ([], []))
        monkeypatch.setattr(path_map_setup, "local_link_shares", lambda *a, **k: ([], []))
    else:
        monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    created = []

    def start():
        player = VideoPlayer(load_shared_config=False)
        created.append(player)
        player.show()
        player.start_shared_config_load()
        wait_until(lambda: not player.shared_config_loading)
        assert player.shared_config_problem and player.shared_config_not_found is True and player.work_paths == {}
        return player

    yield start
    for player in created:
        player.close()
    paths.activate(None)


@pytest.fixture
def show(tmp_path):
    """작품 폴더 MyShow: 바로 안에 영상 하나, s1/ep01(영상 + 하위 폴더의 영상)·s1/ep02·s2/ep10."""
    root = tmp_path / "projects" / "MyShow"
    for relative in ("top.mp4", "s1/ep01/a.mp4", "s1/ep01/shots/b.mp4", "s1/ep02/c.mp4", "s2/ep10/d.mp4"):
        write_test_video(str(root.joinpath(*relative.split("/"))), frames=3)
    (root / ".yesoncheck").mkdir()  # 숨김 폴더는 고를 폴더가 아님
    return str(root)


def register(player, name, folder, levels):
    local_works.add(LocalWork(name, folder, levels))
    player.reload_local_works()


def pick(combo, text):
    index = combo.findText(text)
    assert index >= 0, f"{text!r}이(가) 콤보에 없습니다: {combo_items(combo)}"
    combo.setCurrentIndex(index)


def listed(player):
    return [player.sidebar.item(i).text() for i in range(player.sidebar.count())]


def manager(player):
    dialog = player._local_works_dialog()
    return dialog


def rows(dialog):
    return [dialog.works_list.item(i).text() for i in range(dialog.works_list.count())]


def answer_text(monkeypatch, *answers):
    queue = list(answers)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: queue.pop(0))


def answer_item(monkeypatch, *answers):
    queue = list(answers)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: queue.pop(0))


# ---------------------------------------------------------------- 창 제목 · 작품 경로 관리

def test_window_title_carries_no_shared_settings_mark(outside, dialogs):
    player = outside()
    assert "공유 설정 오류" not in player.windowTitle() and "shared settings error" not in player.windowTitle()
    assert dialogs.messages == []


def test_work_path_manager_opens_this_pcs_list_instead_of_a_warning(outside, dialogs, monkeypatch):
    """회사 밖 PC: 'Tools → 작품 경로 관리'가 기술 글의 경고 창이 아니라 이 PC의 작품 목록 창을 엶 (비밀번호도 묻지 않음)."""
    player = outside()
    opened = []
    monkeypatch.setattr(QDialog, "exec_", lambda dialog: opened.append(dialog) or 0)

    player.manage_work_paths()

    assert [dialog.windowTitle() for dialog in opened] == [MANAGER_TITLE]
    assert dialogs.messages == []
    intro = opened[0].intro_label.text()
    assert "이 PC에만 저장" in intro and "NAS" in intro  # 왜 이 창인지 (사내 PC라면 NAS 연결을 확인)
    for word in ("Traceback", "work_paths.json", "fstab"):
        assert word not in intro


def test_why_the_shared_settings_were_not_found_is_behind_a_button(outside, dialogs):
    """찾지 못한 사유(기술 글)는 이 창의 단추 뒤에 — 사내에서 NAS가 끊긴 PC도 이 창이 열리므로 사유를 볼 길은 남김."""
    player = outside()
    dialog = manager(player)

    dialog.reason_button.click()

    [box] = dialogs.boxes
    assert box.kind == "information" and "사내 공유 설정(NAS)을 찾지 못했습니다" in box.text
    assert "Traceback" not in box.text and box.details.startswith(player._shared_config_problem_text())


def test_adding_a_work_asks_for_name_folder_and_levels(outside, dialogs, monkeypatch, show):
    player = outside()
    assert player.workPickerGroup.isHidden()  # 작품이 하나도 없는 회사 밖 PC: 작품 묶음이 보이지 않음
    dialog = manager(player)
    answer_text(monkeypatch, ("MyShow", True))
    dialogs.folders.append(show)
    answer_item(monkeypatch, (local_works.level_text(2), True))

    dialog.add_button.click()

    assert local_works.read() == [LocalWork("MyShow", show, 2)]
    [row] = rows(dialog)
    assert "MyShow" in row and show in row and local_works.level_text(2) in row
    assert combo_items(player.workComboBox) == ["작품선택", "MyShow"]
    assert not player.workPickerGroup.isHidden()  # 등록하면 사이드바에 작품 묶음이 보임
    assert work_picker.read_seen() is True  # 다음에 켤 때도 그 자리 그대로 (떴다 사라지지 않게)
    assert dialogs.errors() == []


@pytest.mark.parametrize("stop_at", ["name", "empty_name", "folder", "levels"])
def test_cancelling_while_adding_saves_nothing(outside, dialogs, monkeypatch, show, stop_at):
    player = outside()
    dialog = manager(player)
    answer_text(monkeypatch, {"name": ("MyShow", False), "empty_name": ("  ", True)}.get(stop_at, ("MyShow", True)))
    if stop_at != "folder":
        dialogs.folders.append(show)
    answer_item(monkeypatch, (local_works.level_text(1), stop_at != "levels"))

    dialog.add_button.click()

    assert local_works.read() == [] and rows(dialog) == [] and combo_items(player.workComboBox) == ["작품선택"]
    assert not os.path.exists(hover_strip.prefs_path())
    assert dialogs.messages == []  # 그만둔 것 — 경고 창도 없음 (빈 이름·고르지 않은 폴더로 저장을 시도하다 거절당하는 것이 아니라)


def test_a_name_that_is_already_there_is_refused(outside, dialogs, monkeypatch, show):
    player = outside()
    register(player, "MyShow", show, 1)
    dialog = manager(player)
    answer_text(monkeypatch, ("MyShow", True))

    dialog.add_button.click()

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", MANAGER_TITLE)]
    assert "이미 있는 작품" in dialogs.warnings[0] and local_works.read() == [LocalWork("MyShow", show, 1)]


def test_a_name_that_looks_like_the_placeholder_is_refused(outside, dialogs, monkeypatch, show):
    """'작품선택'(안내 항목의 글)을 이름으로 받으면 아무것도 고르지 않은 0번이 그 작품으로 보임 — 등록하지 않음 (리뷰)."""
    player = outside()
    dialog = manager(player)
    answer_text(monkeypatch, ("작품선택", True))
    dialogs.folders.append(show)
    answer_item(monkeypatch, (local_works.level_text(0), True))

    dialog.add_button.click()

    assert local_works.read() == [] and listed(player) == []
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", MANAGER_TITLE)]
    assert "쓸 수 없는 이름" in dialogs.warnings[0]


def test_the_chosen_folder_is_stored_the_way_it_is_on_disk(outside, dialogs, monkeypatch, show, tmp_path):
    """고른 폴더가 그대로는 없고 이름의 정규화(NFC·NFD)만 다른 실제 폴더가 있으면 그 경로로 적음 — 폴더 열기와 같은 다듬기
    (NFS 공유의 한글 폴더: 열기 창이 준 모양이 디스크의 이름과 다르면 '폴더를 열 수 없습니다'가 됨 — 리뷰)."""
    player = outside()
    dialog = manager(player)
    given, on_disk = str(tmp_path / "given_form"), show
    monkeypatch.setattr(paths, "find_unicode_variant", lambda path, *a, **k: on_disk if paths.same_path(path, given) else None)
    answer_text(monkeypatch, ("MyShow", True))
    dialogs.folders.extend([given, given])
    answer_item(monkeypatch, (local_works.level_text(1), True))

    dialog.add_button.click()
    assert local_works.read() == [LocalWork("MyShow", on_disk, 1)]

    local_works.change("MyShow", folder=str(tmp_path))
    player.reload_local_works()
    dialog.works_list.setCurrentRow(0)
    dialog.folder_button.click()
    assert local_works.read() == [LocalWork("MyShow", on_disk, 1)]


def test_a_list_that_cannot_be_read_back_after_saving_is_told(outside, dialogs, monkeypatch, show):
    """저장은 됐는데 다시 읽지 못함(그사이 파일이 깨짐): 창이 말없이 빈 목록을 보이지 않고 그 사유를 알림 (리뷰)."""
    from yesoncheck.user_files import UserFileError

    player = outside()
    dialog = manager(player)
    answer_text(monkeypatch, ("MyShow", True))
    dialogs.folders.append(show)
    answer_item(monkeypatch, (local_works.level_text(1), True))

    def broken(path=None):
        raise UserFileError("시험이 낸 오류: 목록을 읽을 수 없음")

    monkeypatch.setattr(local_works, "read", broken)
    dialog.add_button.click()

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "이 PC의 작품 목록")]
    assert "시험이 낸 오류" in dialogs.warnings[0] and rows(dialog) == []


def test_changing_the_folder_and_the_levels_of_the_selected_work(outside, dialogs, monkeypatch, show, tmp_path):
    player = outside()
    register(player, "MyShow", show, 1)
    dialog = manager(player)
    dialog.works_list.setCurrentRow(0)
    moved = str(tmp_path / "moved")
    os.makedirs(moved)
    dialogs.folders.append(moved)
    answer_item(monkeypatch, (local_works.level_text(0), True))

    dialog.folder_button.click()
    dialog.works_list.setCurrentRow(0)
    dialog.levels_button.click()

    assert local_works.read() == [LocalWork("MyShow", moved, 0)] == list(player.local_works.values())
    assert moved in rows(dialog)[0] and local_works.level_text(0) in rows(dialog)[0]


def test_buttons_that_need_a_selected_work_say_so(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 1)
    dialog = manager(player)

    for button in (dialog.folder_button, dialog.levels_button, dialog.remove_button):
        button.click()

    assert [title for _kind, title, _text in dialogs.messages] == [MANAGER_TITLE] * 3
    assert all("작품을 먼저 고르세요" in text for _kind, _title, text in dialogs.messages)
    assert local_works.read() == [LocalWork("MyShow", show, 1)]


def test_removing_a_work_asks_first_and_leaves_the_folder(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 1)
    dialog = manager(player)
    dialog.works_list.setCurrentRow(0)

    dialogs.answer_question(QMessageBox.No)
    dialog.remove_button.click()
    assert local_works.read() == [LocalWork("MyShow", show, 1)]

    dialogs.answer_question(QMessageBox.Yes)
    dialog.works_list.setCurrentRow(0)
    dialog.remove_button.click()
    assert local_works.read() == [] and rows(dialog) == [] and combo_items(player.workComboBox) == ["작품선택"]
    assert os.path.isfile(os.path.join(show, "top.mp4"))  # 목록에서만 뺌 — 폴더·영상은 그대로
    assert "폴더와 영상은 지우지 않습니다" in dialogs.questions[0]


# ---------------------------------------------------------------- 고르기: 단계 수마다

def test_two_levels_pick_folder_then_folder(outside, dialogs, show):
    """단계 2 (사내와 같은 모양): 작품 → 폴더 → 폴더, 마지막 폴더 아래의 영상을 하위 폴더까지."""
    player = outside()
    register(player, "MyShow", show, 2)

    pick(player.workComboBox, "MyShow")
    assert combo_items(player.seasonComboBox) == [FOLDER, "s1", "s2"]  # 숨김 폴더(.yesoncheck)는 없음
    assert combo_items(player.jobComboBox) == [FOLDER] and listed(player) == []

    pick(player.seasonComboBox, "s1")
    assert combo_items(player.jobComboBox) == [FOLDER, "ep01", "ep02"] and listed(player) == []

    pick(player.jobComboBox, "ep01")
    assert listed(player) == ["a.mp4", "b.mp4"]  # ep01 바로 안 + 그 하위 폴더(shots)
    assert paths.same_path(player.filename_a, os.path.join(show, "s1", "ep01", "a.mp4"))  # 첫 영상이 A에
    assert dialogs.messages == []  # 폴더 열기의 '폴더 로드 완료' 안내 창은 띄우지 않음 (고를 때마다 뜨지 않게)
    assert player.sidebar.selectedItems() == []  # job 목록처럼 — 모두 고르지 않음


def test_one_level_picks_one_folder(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 1)

    pick(player.workComboBox, "MyShow")
    assert combo_items(player.seasonComboBox) == [FOLDER]  # 둘째 칸은 쓰지 않음
    assert combo_items(player.jobComboBox) == [FOLDER, "s1", "s2"] and listed(player) == []

    pick(player.jobComboBox, "s1")
    assert listed(player) == ["a.mp4", "b.mp4", "c.mp4"]  # s1 아래 전부
    assert dialogs.messages == []


def test_no_level_lists_everything_as_soon_as_the_work_is_picked(outside, dialogs, monkeypatch, show):
    player = outside()
    register(player, "MyShow", show, 0)
    reads = []
    real_scan = video_list.scan_folder
    monkeypatch.setattr(video_list, "scan_folder", lambda folder: reads.append(folder) or real_scan(folder))

    pick(player.workComboBox, "MyShow")

    assert sorted(listed(player)) == ["a.mp4", "b.mp4", "c.mp4", "d.mp4", "top.mp4"]
    assert combo_items(player.seasonComboBox) == [FOLDER] and combo_items(player.jobComboBox) == [FOLDER]
    assert [os.path.normpath(folder) for folder in reads] == [os.path.normpath(show)]  # 콤보를 비우는 신호마다 다시 읽지 않고 한 번만
    assert dialogs.messages == []


def test_a_picked_folder_is_read_once(outside, dialogs, monkeypatch, show):
    """사람이 콤보에서 고르면 Qt는 currentIndexChanged 바로 다음에 activated도 보냄 — 같은 폴더를 두 번 읽지 않음
    (읽은 것을 기억: _job_list_loaded_for). 기억하지 않으면 그 activated를 '같은 폴더를 다시 고름'으로 보고 뒤 스레드에서 한 번 더
    읽으므로, 다시 읽기가 끝나기까지 기다린 뒤 셈."""
    player = outside()
    register(player, "MyShow", show, 1)
    pick(player.workComboBox, "MyShow")
    reads = []
    real_scan = video_list.scan_folder
    monkeypatch.setattr(video_list, "scan_folder", lambda folder: reads.append(folder) or real_scan(folder))

    pick(player.jobComboBox, "s2")  # currentIndexChanged
    player._on_job_activated(player.jobComboBox.currentIndex())  # 바로 뒤의 activated (이벤트를 처리하기 전)
    wait_refreshed(player)

    assert len(reads) == 1 and listed(player) == ["d.mp4"]


@pytest.mark.parametrize("levels, after_work, after_folder", [(0, 0, 0), (1, 1, 1), (2, 1, 2)])
def test_folders_are_listed_once_per_pick(outside, dialogs, monkeypatch, show, levels, after_work, after_folder):
    """고를 폴더 읽기(GUI 스레드의 폴더 읽기)는 고를 때마다 한 번 — 콤보를 비우는 신호마다 다시 읽지 않음
    (느린 공유에서 멈춤이 세 배가 됨 — 리뷰)."""
    player = outside()
    register(player, "MyShow", show, levels)
    reads = []
    real = local_works.subfolders
    monkeypatch.setattr(local_works, "subfolders", lambda folder: reads.append(folder) or real(folder))

    pick(player.workComboBox, "MyShow")
    assert len(reads) == after_work, reads

    if levels == 2:
        pick(player.seasonComboBox, "s1")
        assert len(reads) == after_folder, reads


def test_a_folder_that_cannot_be_read_is_told_each_time_it_is_picked(outside, dialogs, monkeypatch, show):
    """읽지 못한 폴더의 알림은 그 폴더를 고를 때마다 (다른 폴더를 고른 뒤 다시 골라도 말없이 빈 칸이 아니게 — 리뷰)."""
    player = outside()
    register(player, "MyShow", show, 2)
    real = local_works.subfolders

    def subfolders(folder):
        if os.path.basename(folder) == "s1":
            raise PermissionError(13, "Permission denied", folder)
        return real(folder)

    monkeypatch.setattr(local_works, "subfolders", subfolders)
    pick(player.workComboBox, "MyShow")

    pick(player.seasonComboBox, "s1")
    pick(player.seasonComboBox, "s2")
    pick(player.seasonComboBox, "s1")

    assert [title for _kind, title, _text in dialogs.messages] == ["작품 경로 오류"] * 2
    assert all("폴더를 읽지 못했습니다" in text and "PermissionError" in text for text in dialogs.criticals)
    assert combo_items(player.jobComboBox) == [FOLDER]


def test_going_back_to_no_work_clears_the_list(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 0)
    pick(player.workComboBox, "MyShow")
    assert listed(player)

    player.workComboBox.setCurrentIndex(0)

    assert listed(player) == [] and combo_items(player.seasonComboBox) == ["시즌선택"]


def test_changing_the_first_folder_empties_the_list_until_the_second_is_picked(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 2)
    pick(player.workComboBox, "MyShow")
    pick(player.seasonComboBox, "s1")
    pick(player.jobComboBox, "ep02")
    assert listed(player) == ["c.mp4"]

    pick(player.seasonComboBox, "s2")

    assert listed(player) == [] and combo_items(player.jobComboBox) == [FOLDER, "ep10"]


def test_picking_the_same_folder_again_rereads_the_list_and_keeps_the_video(outside, dialogs, qapp, monkeypatch, show):
    """같은 폴더를 다시 고르면 사내 job을 다시 고를 때처럼 목록만 다시 읽음 — 보던 영상(A)을 다시 열지 않음
    (사용자 2026-11-27: "같은 폴더를 다시 고를 때도 기존대로"; 처음에는 목록을 새로 불러와 첫 영상을 A에 다시 열었음)."""
    player = outside()
    register(player, "MyShow", show, 2)
    pick(player.workComboBox, "MyShow")
    pick(player.seasonComboBox, "s1")
    pick(player.jobComboBox, "ep02")
    qapp.processEvents()
    opened = []
    real_open = player.open_file
    monkeypatch.setattr(player, "open_file", lambda *args, **kwargs: opened.append(args) or real_open(*args, **kwargs))
    write_test_video(os.path.join(show, "s1", "ep02", "new.mp4"), frames=3)

    player._on_job_activated(player.jobComboBox.currentIndex())  # 같은 항목을 다시 고름
    wait_refreshed(player)

    assert listed(player) == ["c.mp4", "new.mp4"] and dialogs.messages == []
    assert opened == [] and paths.same_path(player.filename_a, os.path.join(show, "s1", "ep02", "c.mp4"))


def test_picking_the_same_folder_again_after_another_list_loads_it_afresh(outside, dialogs, qapp, show, tmp_path):
    """목록이 그 폴더의 것이 아니면(그사이 폴더 열기로 다른 폴더를 봄) 다시 고를 때는 처음 고를 때처럼 불러옴 (사내 job과 같음)."""
    player = outside()
    register(player, "MyShow", show, 2)
    pick(player.workComboBox, "MyShow")
    pick(player.seasonComboBox, "s1")
    pick(player.jobComboBox, "ep02")
    qapp.processEvents()
    other = write_test_video(str(tmp_path / "elsewhere" / "x.mp4"), frames=3)
    player.load_videos_from_folder(os.path.dirname(other))
    assert listed(player) == ["x.mp4"]

    player._on_job_activated(player.jobComboBox.currentIndex())

    assert listed(player) == ["c.mp4"] and paths.same_path(player.filename_a, os.path.join(show, "s1", "ep02", "c.mp4"))


def test_refresh_picks_up_a_new_video(outside, dialogs, show):
    """새로고침(F5)은 폴더 열기로 넣은 목록과 같은 길 — 고른 폴더를 같은 규칙으로 다시 읽음."""
    player = outside()
    register(player, "MyShow", show, 1)
    pick(player.workComboBox, "MyShow")
    pick(player.jobComboBox, "s2")
    assert listed(player) == ["d.mp4"]
    write_test_video(os.path.join(show, "s2", "ep10", "deep", "e.mp4"), frames=3)

    player._refresh_sidebar_by_user()
    wait_refreshed(player)

    assert listed(player) == ["d.mp4", "e.mp4"] and dialogs.errors() == []


def test_a_folder_without_videos_gives_an_empty_list_quietly(outside, dialogs, show):
    os.makedirs(os.path.join(show, "s3"))
    player = outside()
    register(player, "MyShow", show, 1)
    pick(player.workComboBox, "MyShow")

    pick(player.jobComboBox, "s3")

    assert listed(player) == [] and dialogs.messages == []  # job을 골랐는데 영상이 없을 때처럼 조용히


def test_a_work_folder_that_is_gone_is_told_once(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 2)
    shutil.rmtree(show)

    pick(player.workComboBox, "MyShow")

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("critical", "작품 경로 오류")]
    assert show in dialogs.criticals[0] and "작품 경로 관리" in dialogs.criticals[0]  # 어디서 고치는지
    assert combo_items(player.seasonComboBox) == [FOLDER] and combo_items(player.jobComboBox) == [FOLDER] and listed(player) == []


def test_this_pcs_folders_are_used_as_they_are_without_the_path_table(outside, dialogs, monkeypatch, show):
    """사내 작품의 경로는 공유 설정의 Mac 경로라 변환(Windows 변환표·Mac 공유 자리)을 거치지만, 이 PC의 작품은 폴더 그대로 —
    Windows의 로컬 디스크 폴더도 됨 (변환표가 없어도)."""
    player = outside()
    register(player, "MyShow", show, 1)

    def no_conversion(path):
        raise AssertionError(f"이 PC의 작품 폴더를 변환하려 했습니다: {path}")

    monkeypatch.setattr(paths, "to_native", no_conversion)

    assert player.get_work_path("MyShow") == show
    pick(player.workComboBox, "MyShow")
    pick(player.jobComboBox, "s2")
    assert listed(player) == ["d.mp4"] and dialogs.messages == []


def test_placeholders_follow_the_language(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 2)
    pick(player.workComboBox, "MyShow")
    pick(player.seasonComboBox, "s1")

    player.set_ui_language("en")

    assert player.seasonComboBox.itemText(0) == "Select folder" == player.jobComboBox.itemText(0)
    assert player.seasonComboBox.currentText() == "s1" and combo_items(player.jobComboBox)[1:] == ["ep01", "ep02"]  # 고른 것은 그대로
    player.set_ui_language("ko")
    assert player.seasonComboBox.itemText(0) == FOLDER


def test_registered_works_are_there_the_next_time_the_app_starts(outside, dialogs, show):
    local_works.add(LocalWork("MyShow", show, 1))
    local_works.add(LocalWork("Another", show, 0))

    player = outside()

    assert combo_items(player.workComboBox) == ["작품선택", "Another", "MyShow"]  # 이름 순서
    assert not player.workPickerGroup.isHidden() and dialogs.messages == []


# ---------------------------------------------------------------- English 화면 (사용자 2026-11-27: "새 창의 언어 영문도 추가")

def test_the_manager_window_is_in_english_on_an_english_screen(outside, dialogs, show):
    player = outside()
    register(player, "MyShow", show, 2)
    player.set_ui_language("en")

    dialog = manager(player)

    buttons = [button.text() for button in dialog.findChildren(QPushButton)]
    assert dialog.windowTitle() == "Manage show paths (this PC)"
    assert buttons == ["Add show", "Change folder", "Change steps", "Remove show", "Close", "Why the shared settings were not found…"]
    assert rows(dialog) == [f"MyShow: {show}\n    show → folder → folder (choose two more)"]
    assert "saved only on this PC" in dialog.intro_label.text()
    assert ui_texts.hangul([dialog.windowTitle(), dialog.intro_label.text(), *buttons, *rows(dialog)]) == []


def test_adding_a_work_asks_in_english(outside, dialogs, monkeypatch, show):
    player = outside()
    player.set_ui_language("en")
    dialog = manager(player)
    asked = []

    def get_text(parent, title, label, *args, **kwargs):
        asked.append((title, label))
        return "MyShow", True

    def get_folder(parent, caption, *args, **kwargs):
        asked.append((caption,))
        return show

    def get_item(parent, title, label, items, current, editable):
        asked.append((title, label, tuple(items), current))
        return items[2], True

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", get_folder)
    monkeypatch.setattr(QInputDialog, "getItem", get_item)

    dialog.add_button.click()

    assert local_works.read() == [LocalWork("MyShow", show, 2)]
    assert asked[0] == ("Manage show paths (this PC)", "Enter a name for the show:")
    assert asked[1] == ("Choose the folder of MyShow",)
    title, label, items, current = asked[2]
    assert title == "Manage show paths (this PC)" and label.startswith("Set how many more folders you choose after the show.")
    assert items == ("list the videos as soon as the show is chosen", "show → one more folder",
                     "show → folder → folder (choose two more)") and current == local_works.DEFAULT_LEVELS
    assert ui_texts.hangul([text for entry in asked for text in entry if isinstance(text, str)] + list(items)) == []
    assert dialogs.messages == []


def test_notices_of_the_manager_are_in_english(outside, dialogs, monkeypatch, show):
    player = outside()
    register(player, "MyShow", show, 1)
    player.set_ui_language("en")
    dialog = manager(player)

    dialog.folder_button.click()  # 고른 작품 없음
    answer_text(monkeypatch, ("MyShow", True), ("Select show", True))
    dialog.add_button.click()  # 이미 있는 이름
    dialog.add_button.click()  # 안내 글과 같은 이름
    dialog.works_list.setCurrentRow(0)
    dialogs.answer_question(QMessageBox.No)
    dialog.remove_button.click()
    dialog.reason_button.click()

    texts = [text for _kind, _title, text in dialogs.messages[:4]]
    assert texts[0] == "Select a show in the list first."
    assert texts[1] == "A show with this name already exists: MyShow"
    assert texts[2].startswith("This name cannot be used") and texts[2].endswith(": Select show")
    assert texts[3].startswith("Remove 'MyShow' from this PC's show list?") and "are not deleted" in texts[3]
    assert ui_texts.hangul(texts) == [] and {title for _kind, title, _text in dialogs.messages[:4]} == {"Manage show paths (this PC)"}
    reason = dialogs.boxes[-1]
    assert reason.title == "Shared settings" and reason.text.startswith("The in-house shared settings (NAS) were not found.")
    assert ui_texts.hangul([reason.text]) == []  # (자세히 칸의 기술 글은 한글 그대로 — 기록과 같은 글)
    assert local_works.read() == [LocalWork("MyShow", show, 1)]


def test_picker_problems_are_told_in_english(outside, dialogs, monkeypatch, show):
    player = outside()
    register(player, "MyShow", show, 2)
    register(player, "Gone", os.path.join(show, "no_such_folder"), 1)
    player.set_ui_language("en")
    real = local_works.subfolders

    def subfolders(folder):
        if os.path.basename(folder) == "s1":
            raise PermissionError(13, "Permission denied", folder)
        return real(folder)

    monkeypatch.setattr(local_works, "subfolders", subfolders)

    pick(player.workComboBox, "Gone")
    pick(player.workComboBox, "MyShow")
    pick(player.seasonComboBox, "s1")

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("critical", "Show path error")] * 2
    gone, unreadable = dialogs.criticals
    assert gone.startswith("The folder of 'Gone' cannot be opened.") and "Manage show paths" in gone
    assert unreadable.startswith("The folder could not be read.") and "PermissionError" in unreadable
    assert ui_texts.hangul([gone, unreadable]) == []


def test_a_list_that_cannot_be_read_is_told_in_english(outside, dialogs, show):
    """읽지 못한 목록의 알림: 머리 글은 화면 언어로 (그 뒤의 사유는 기록과 같은 글), 켠 뒤 언어를 바꿔도 그 언어로."""
    os.makedirs(os.path.dirname(hover_strip.prefs_path()), exist_ok=True)
    with open(hover_strip.prefs_path(), "w", encoding="utf-8") as fh:
        json.dump({"local_works": "MyShow"}, fh)
    player = outside()
    assert dialogs.boxes[0].text.startswith("이 PC의 작품 목록을 읽지 못했습니다")

    player.set_ui_language("en")
    player.manage_work_paths()

    told = dialogs.boxes[1]
    assert told.title == "This PC's show list" and told.text.startswith("This PC's show list could not be read")
    assert "The in-house shared settings (NAS) were not found." in told.text
    assert ui_texts.hangul([told.text]) == []  # 본문은 모두 화면 언어 — 기술적인 사유(한글, 기록과 같은 글)는 자세히 칸에 (리뷰)
    assert told.details.startswith("설정 파일의 local_works") and player._shared_config_problem_text() in told.details


# ---------------------------------------------------------------- 사내 PC는 그대로 · 읽지 못한 목록

def test_a_pc_that_reads_the_shared_settings_ignores_its_own_list(new_player, dialogs, monkeypatch, tmp_path, show):  # noqa: F811
    """공유 설정을 읽은 PC(사내)는 예전 그대로: NAS의 작품만 보이고 작품 경로 관리는 비밀번호부터 — 이 PC의 목록은 쓰지 않음."""
    local_works.add(LocalWork("MyShow", show, 1))
    player = new_player(make_config(str(tmp_path / "nas"), {}))
    asked = []
    monkeypatch.setattr(player, "_confirm_work_paths_password", lambda: asked.append(True) and False)
    monkeypatch.setattr(player, "manage_local_works", lambda: pytest.fail("사내 PC에서 이 PC의 작품 창이 열렸습니다"))

    player.manage_work_paths()

    assert player.shared_config_problem is None and player.local_works == {}
    assert combo_items(player.workComboBox) == ["작품선택"] and asked == [True]


def test_real_trouble_with_the_shared_settings_still_gets_the_warning(new_player, dialogs, tmp_path, show):  # noqa: F811
    """공유 설정 폴더는 열리는데 파일이 깨짐(진짜 문제 — '찾지 못함'이 아님): 예전처럼 사유의 경고 창, 이 PC의 목록 창은 열지 않고
    이 PC의 작품도 작품 콤보에 섞지 않음 (사내 PC의 고장을 이 PC의 목록으로 가리지 않게)."""
    local_works.add(LocalWork("MyShow", show, 1))
    player = new_player(make_config(str(tmp_path / "nas"), {}, raw="{ 깨짐"))
    assert player.shared_config_problem and player.shared_config_not_found is False
    assert player.local_works == {} and combo_items(player.workComboBox) == ["작품선택"]

    player.manage_work_paths()

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "작품 경로 관리")]
    assert "관리할 수 없습니다" in dialogs.warnings[0]
    assert "공유 설정 오류" not in player.windowTitle()  # 창 제목의 표시는 어느 경우에도 없음 (사유는 시작할 때의 창과 여기서)


def test_a_list_that_cannot_be_read_is_told_and_never_overwritten(outside, dialogs, monkeypatch, show, capsys):
    """이 PC의 설정 파일에서 작품 목록의 모양이 틀림: 빈 목록으로 치고 덮어쓰지 않음 — 켤 때 한 번 알리고(사유·트레이스백은 기록에),
    작품 창은 열지 않고 같은 사유를 보임."""
    stored = {"local_works": [{"name": "MyShow", "folder": show}]}  # levels가 없음
    os.makedirs(os.path.dirname(hover_strip.prefs_path()), exist_ok=True)
    with open(hover_strip.prefs_path(), "w", encoding="utf-8") as fh:
        json.dump(stored, fh)

    player = outside()  # 켤 때(공유 설정을 읽은 뒤의 알림 단계)에 한 번 알림

    assert player.local_works == {} and combo_items(player.workComboBox) == ["작품선택"]
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "이 PC의 작품 목록")]
    assert "local_works" in dialogs.warnings[0] and "Traceback" in capsys.readouterr().err
    # 이 창만 뜨는 PC에서도 '공유 설정을 찾지 못했음'과 그 사유를 볼 수 있음 (작품 창의 단추까지 가지 못하므로 — 리뷰)
    [told] = dialogs.boxes
    assert "사내 공유 설정(NAS)을 찾지 못했습니다" in told.text and "local_works" not in told.text
    assert told.details.startswith("설정 파일의 local_works") and player._shared_config_problem_text() in told.details

    monkeypatch.setattr(QDialog, "exec_", lambda dialog: pytest.fail("읽지 못한 목록으로 작품 창이 열렸습니다"))
    player.manage_work_paths()
    assert len(dialogs.warnings) == 2 and "local_works" in dialogs.warnings[1]
    with open(hover_strip.prefs_path(), encoding="utf-8") as fh:
        assert json.load(fh) == stored
