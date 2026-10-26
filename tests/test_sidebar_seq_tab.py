"""사이드바 Mov·Seq 탭과 Seq 목록: 한 번 읽은 폴더 목록에서 영상과 이미지 시퀀스를 함께 목록에 넣고 (첫 불러오기·끌어다 놓기·
목록 다시 읽기), 탭 전환은 디스크를 읽지 않으며, Seq 항목을 누르면 시퀀스를 A로 엶. Mov 탭(self.sidebar)은 그대로.

시퀀스 프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA. 예시 이름만 씀 (공개 저장소). 창·대화상자는 conftest의
dialogs가 가로챔 (실제 QMessageBox를 띄우지 않음).
"""

import os
import time

import pytest
from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt5.QtGui import QDropEvent, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QTabWidget

from tests.conftest import write_test_video
from tests.test_sequence_capture import make_seq
from tests.test_sidebar_refresh import refresh
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import paths, video_list
from yesoncheck.sequence_scan import SeqInfo


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def shot(tmp_path, name="shot"):
    """tk1(6장)·tk2(5장, 4번이 빠짐) 시퀀스와 영상 tk1.mov가 든 폴더."""
    folder = tmp_path / name
    write_test_video(str(folder / "tk1.mov"))
    make_seq(str(folder), "tk1", range(1, 7))
    make_seq(str(folder), "tk2", [1, 2, 3, 5, 6])
    return folder


def seq_rows(player):
    return [(player.seq_sidebar.item(i).text(), player.seq_sidebar.item(i).data(Qt.UserRole))
            for i in range(player.seq_sidebar.count())]


def seq_labels(player):
    return [text for text, _seq in seq_rows(player)]


def seq_identities(player):
    return [os.path.basename(seq.identity) for _text, seq in seq_rows(player)]


def mov_names(player):
    return [player.sidebar.item(i).text() for i in range(player.sidebar.count())]


def seq_item(player, base):
    return next(player.seq_sidebar.item(i) for i in range(player.seq_sidebar.count())
                if player.seq_sidebar.item(i).data(Qt.UserRole).base == base)


def virtual(path):
    return paths.normalize_native(path)


def fake_seq(folder, base, first=1, last=10, count=10, pad=4):
    return SeqInfo(str(folder), base, "tga", pad, first, last, count)


def open_job(new_player, work_area):  # noqa: F811
    """작품 SMOKE·시즌 S1의 job_01(scene-001/frames에 FL_001.mov와 시퀀스 FL_001_tk1)을 고름 → (창, frames 폴더)."""
    frames = os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames")
    write_test_video(os.path.join(frames, "FL_001.mov"))
    make_seq(frames, "FL_001_tk1", range(1, 7))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    return player, frames


# ---------------------------------------------------------------- 탭


def test_tabs_exist_mov_page_is_existing_sidebar(player):
    tabs = player.sidebar_tabs
    assert isinstance(tabs, QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Mov", "Seq"]
    assert tabs.widget(0) is player.sidebar  # Mov 페이지는 기존 사이드바 그대로
    assert tabs.widget(1) is player.seq_sidebar
    assert tabs.currentIndex() == 0
    assert player.seq_sidebar.count() == 0
    # 탭이 사이드바의 자리를 그대로 이어받음: 버튼들 아래, 사이드바 컨테이너 안
    container = player.control_widgets[0]
    assert tabs.parentWidget() is container and player.sidebar.window() is player


def test_tab_bar_does_not_take_keyboard_focus(player):
    """방향키(프레임 이동)가 탭 막대에 먹혀 탭이 바뀌지 않게 — 앱의 다른 단추들처럼 포커스를 받지 않음."""
    assert player.sidebar_tabs.focusPolicy() == Qt.NoFocus
    assert player.sidebar_tabs.tabBar().focusPolicy() == Qt.NoFocus


# ---------------------------------------------------------------- 목록 채우기


def test_seq_items_populated_from_folder_scan(player, tmp_path):
    folder = shot(tmp_path)

    player.load_videos_from_folder(str(folder))

    assert mov_names(player) == ["tk1.mov"]  # Mov 목록은 예전 그대로
    assert seq_labels(player) == ["tk1 (0001–0006, 6프레임)", "tk2 (0001–0006, 5프레임), 빠짐 1"]
    first, second = (seq for _text, seq in seq_rows(player))
    assert paths.path_key(first.dir) == paths.path_key(str(folder))
    assert (first.base, first.ext, first.pad, first.first, first.last, first.count) == ("tk1", "tga", 4, 1, 6, 6)
    assert second.missing == 1
    # 툴팁은 사람이 읽는 정보 (Mov 목록처럼 경로 하나가 아님)
    tip = seq_item(player, "tk2").toolTip()
    assert tip != second.identity and str(folder) in tip and "0001–0006" in tip and "빠짐 1" in tip
    assert "빠짐" not in seq_item(player, "tk1").toolTip()


def test_seq_items_populated_from_job_scan(new_player, dialogs, work_area):  # noqa: F811
    player, frames = open_job(new_player, work_area)

    assert mov_names(player) == ["FL_001.mov"]
    assert seq_labels(player) == ["FL_001_tk1 (0001–0006, 6프레임)"]
    seq = player.seq_sidebar.item(0).data(Qt.UserRole)
    mov_dir = os.path.dirname(player.sidebar.item(0).data(Qt.UserRole))  # 앱이 보는 폴더 경로
    assert paths.path_key(seq.dir) == paths.path_key(mov_dir)


def test_sequenceless_source_empty_seq_list(player, tmp_path):
    plain = tmp_path / "plain"
    write_test_video(str(plain / "a.mov"))

    player.load_videos_from_folder(str(plain))

    assert mov_names(player) == ["a.mov"]
    assert player.seq_sidebar.count() == 0


def test_loading_a_sequenceless_source_empties_the_old_seq_list(player, tmp_path):
    player.load_videos_from_folder(str(shot(tmp_path)))
    assert player.seq_sidebar.count() == 2
    plain = tmp_path / "plain"
    write_test_video(str(plain / "a.mov"))

    player.load_videos_from_folder(str(plain))

    assert player.seq_sidebar.count() == 0


def test_clearing_the_mov_list_clears_the_seq_list(player, tmp_path):
    """job을 바꾸거나 읽지 못해 Mov 목록을 비우는 모든 길에서 (오래된 시퀀스가 남지 않게)."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    assert player.seq_sidebar.count() == 2

    player.sidebar.clear()

    assert player.seq_sidebar.count() == 0


def test_sequence_only_folder_fills_seq_list_without_no_video_warning(player, dialogs, tmp_path):
    folder = tmp_path / "renders"
    make_seq(str(folder), "tk1", range(1, 5))

    player.load_videos_from_folder(str(folder))

    assert player.sidebar.count() == 0
    assert seq_labels(player) == ["tk1 (0001–0004, 4프레임)"]
    assert dialogs.warnings == []  # 시퀀스가 있는 폴더에 '영상이 없습니다'를 띄우지 않음
    assert player.sidebar_tabs.currentIndex() == 1  # 볼 것이 Seq 탭에만 있으므로 그 탭을 보여 줌
    assert not player.playSelectedButton.isEnabled()  # 탭 전환의 부수 효과도 그대로 (Seq 탭에서는 선택 재생 끔)


def test_folder_with_videos_keeps_the_current_tab(player, tmp_path):
    """영상이 있는 폴더는 (시퀀스가 함께 있어도) 지금 보던 탭 그대로 — Mov 탭이 보이는 상태에서 시작하면 Mov 탭."""
    player.load_videos_from_folder(str(shot(tmp_path)))

    assert player.sidebar_tabs.currentIndex() == 0
    assert player.playSelectedButton.isEnabled()


def test_empty_folder_still_warns_no_videos(player, dialogs, tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()

    player.load_videos_from_folder(str(folder))

    assert dialogs.warnings == ["폴더에 지원되는 비디오 파일이 없습니다."]
    assert player.seq_sidebar.count() == 0


def test_dropped_folder_appends_its_sequences(player, dialogs, tmp_path):
    first = shot(tmp_path, "first")
    second = tmp_path / "second"
    write_test_video(str(second / "z.mov"))
    make_seq(str(second), "tk9", range(1, 4))
    player.load_videos_from_folder(str(first))

    drop_folder(player, "sidebar", second)  # 사이드바에 끌어다 놓기: 목록에 덧붙임

    assert mov_names(player) == ["tk1.mov", "z.mov"]
    assert seq_identities(player) == ["tk1.seq", "tk2.seq", "tk9.seq"]
    assert seq_labels(player)[-1] == "tk9 (0001–0003, 3프레임)"


def test_dropped_folder_on_video_area_replaces_the_seq_list(player, dialogs, tmp_path):
    player.load_videos_from_folder(str(shot(tmp_path, "first")))
    second = tmp_path / "second"
    write_test_video(str(second / "z.mov"))
    make_seq(str(second), "tk9", range(1, 4))

    drop_folder(player, "video", second)  # 영상 영역에 놓기: 목록을 비우고 새로 채움

    assert mov_names(player) == ["z.mov"]
    assert seq_identities(player) == ["tk9.seq"]


def test_dropping_the_same_folder_twice_does_not_duplicate(player, dialogs, tmp_path):
    folder = shot(tmp_path)
    player.load_videos_from_folder(str(folder))

    drop_folder(player, "sidebar", folder)

    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]


def drop_on_window(player, folder):
    """최상위 창 본문(영상 영역·Mov 목록이 아닌 곳)에 폴더를 끌어다 놓음: 실제 QDropEvent를 창의 dropEvent에 건넴 (Qt가 부르는 곳, 대역 없음)."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    assert player.parent() is None
    player.dropEvent(event)


def drop_any(player, target, folder):
    if target == "window":
        drop_on_window(player, folder)
    else:
        drop_folder(player, target, folder)


def seq_only_folder(tmp_path, name="renders"):
    folder = tmp_path / name
    make_seq(str(folder), "tk7", range(1, 5))
    return folder


@pytest.mark.parametrize("target", ["video", "sidebar", "window"])
def test_dropped_sequence_only_folder_shows_seq_tab_without_false_warning(player, dialogs, tmp_path, target):
    """시퀀스만 든 폴더를 끌어다 놓아도 Select Folder처럼: Seq 항목이 채워지고 Seq 탭이 보이며 '영상이 없습니다' 경고가 없음."""
    folder = seq_only_folder(tmp_path)

    drop_any(player, target, folder)

    assert player.sidebar.count() == 0
    assert seq_labels(player) == ["tk7 (0001–0004, 4프레임)"]
    assert player.sidebar_tabs.currentIndex() == 1
    assert dialogs.warnings == []
    assert not player.playSelectedButton.isEnabled()  # 탭 전환의 부수 효과도 그대로
    assert player._folder_sequences.get(paths.path_key(str(folder)), []) == []  # 읽어 둔 시퀀스를 썼음 (남지 않음)


@pytest.mark.parametrize("target", ["video", "sidebar", "window"])
def test_dropped_sequence_only_folder_survives_a_list_refresh(player, dialogs, tmp_path, target):
    """끌어다 놓은 폴더는 목록 다시 읽기(F5)가 다시 읽는 곳으로 기억됨 — 다시 읽어도 Seq 항목이 사라지지 않음."""
    drop_any(player, target, seq_only_folder(tmp_path))

    refresh(player)

    assert seq_labels(player) == ["tk7 (0001–0004, 4프레임)"]


def test_dropped_sequence_only_folder_on_video_area_replaces_both_lists(player, dialogs, tmp_path):
    """영상 영역에 놓기는 영상 폴더를 놓을 때처럼 목록을 비우고 새로 채움 (Mov 목록의 옛 영상·옛 시퀀스가 남지 않음)."""
    player.load_videos_from_folder(str(shot(tmp_path, "first")))
    assert player.sidebar.count() == 1 and player.seq_sidebar.count() == 2

    drop_folder(player, "video", seq_only_folder(tmp_path))

    assert player.sidebar.count() == 0
    assert seq_identities(player) == ["tk7.seq"]
    assert player.sidebar_tabs.currentIndex() == 1


def test_dropped_sequence_only_folder_on_mov_list_appends(player, dialogs, tmp_path):
    """Mov 목록에 놓기는 영상 폴더를 놓을 때처럼 덧붙임 (지금 목록 그대로 두고 시퀀스만 더함)."""
    player.load_videos_from_folder(str(shot(tmp_path, "first")))

    drop_folder(player, "sidebar", seq_only_folder(tmp_path))

    assert mov_names(player) == ["tk1.mov"]
    assert seq_identities(player) == ["tk1.seq", "tk2.seq", "tk7.seq"]
    assert player.sidebar_tabs.currentIndex() == 1


@pytest.mark.parametrize("target", ["video", "sidebar", "window"])
def test_dropped_empty_folder_still_warns_or_stays_quiet(player, dialogs, tmp_path, target):
    """영상도 시퀀스도 없는 폴더: 예전 그대로 (영상 영역·창은 '영상이 없습니다' 경고, Mov 목록은 조용히 아무것도 안 함)."""
    folder = tmp_path / "empty"
    folder.mkdir()

    drop_any(player, target, folder)

    assert dialogs.warnings == ([] if target == "sidebar" else ["폴더에 지원되는 비디오 파일이 없습니다."])
    assert player.seq_sidebar.count() == 0 and player.sidebar_tabs.currentIndex() == 0


@pytest.mark.parametrize("target", ["video", "sidebar", "window"])
def test_dropped_folder_with_videos_keeps_the_current_tab(player, dialogs, tmp_path, target):
    """영상이 든 폴더(시퀀스가 함께 있어도)는 예전 그대로: 시퀀스는 Seq 목록에 들어가고 보던 Mov 탭은 그대로, 경고 없음."""
    drop_any(player, target, shot(tmp_path))

    assert mov_names(player) == ["tk1.mov"]
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.sidebar_tabs.currentIndex() == 0
    assert dialogs.warnings == []


# ---------------------------------------------------------------- 탭 전환·단추


def test_tab_switch_does_no_io(player, tmp_path, monkeypatch):
    player.load_videos_from_folder(str(shot(tmp_path)))
    calls = []
    for name in ("scandir", "listdir", "walk", "stat", "lstat"):
        real = getattr(os, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(os, name, spy)

    player.sidebar_tabs.setCurrentIndex(1)
    player.sidebar_tabs.setCurrentIndex(0)
    player.sidebar_tabs.setCurrentIndex(1)
    QApplication.processEvents()

    assert calls == []  # 전환은 페이지 교체뿐
    assert player._sidebar_scan is None  # 목록 다시 읽기도 시작하지 않음


def test_selected_play_disabled_on_seq_tab(player):
    assert player.playSelectedButton.isEnabled()

    player.sidebar_tabs.setCurrentIndex(1)
    assert not player.playSelectedButton.isEnabled()  # 재생목록 기계장치는 mov 경로 전제

    player.sidebar_tabs.setCurrentIndex(0)
    assert player.playSelectedButton.isEnabled()


def test_both_selected_play_buttons_disabled_on_seq_tab(player):
    """'Play Selected'뿐 아니라 짝 단추 'Selected Play'(Play/Pause Selected)도: 눌리면 안 보이는 Mov 목록의 선택으로 재생을 시작하므로."""
    assert player.playSelectedButton.isEnabled() and player.playSelectedPauseButton.isEnabled()

    player.sidebar_tabs.setCurrentIndex(1)
    assert not player.playSelectedButton.isEnabled()
    assert not player.playSelectedPauseButton.isEnabled()

    player.sidebar_tabs.setCurrentIndex(0)  # Mov 탭은 예전 그대로
    assert player.playSelectedButton.isEnabled() and player.playSelectedPauseButton.isEnabled()


def test_selected_pause_button_stays_disabled_after_stop_video_on_seq_tab(player, tmp_path):
    """open_file이 부르는 stop_video가 'Selected Play'로 되돌려도 Seq 탭이면 꺼진 채 (시퀀스를 열어도 단추가 살아나지 않음)."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    player.sidebar_tabs.setCurrentIndex(1)

    player.on_seq_item_clicked(seq_item(player, "tk2"))  # 시퀀스를 엶 (open_file -> stop_video)

    assert player.is_sequence_active()
    assert player.playSelectedPauseButton.text() == "Selected Play"
    assert not player.playSelectedPauseButton.isEnabled()


def test_selected_pause_button_stays_usable_while_playlist_plays_on_seq_tab(player):
    """선택 재생이 이미 돌고 있으면 그 단추는 재생목록의 일시정지 단추 — Seq 탭으로 옮겨도 눌러서 멈출 수 있어야 함.
    선택 재생이 끝나면(stop_video·_end_playlist_mode) 그때부터 꺼짐."""
    player.is_playlist_playing = True  # Mov 탭에서 시작한 선택 재생
    player.sidebar_tabs.setCurrentIndex(1)

    assert player.playSelectedPauseButton.isEnabled()
    assert not player.playSelectedButton.isEnabled()  # 새 선택 재생을 시작하는 단추는 여전히 꺼짐

    player.stop_video()  # 선택 재생 끝
    assert not player.is_playlist_playing and not player.playSelectedPauseButton.isEnabled()

    player.is_playlist_playing = True
    player.sidebar_tabs.setCurrentIndex(0)
    player.sidebar_tabs.setCurrentIndex(1)
    assert player.playSelectedPauseButton.isEnabled()
    player._end_playlist_mode()  # 재생할 수 있는 영상이 없어 끝나는 길
    assert not player.is_playlist_playing and not player.playSelectedPauseButton.isEnabled()

    player.sidebar_tabs.setCurrentIndex(0)
    assert player.playSelectedPauseButton.isEnabled()


# ---------------------------------------------------------------- 누르기


def test_seq_item_click_opens_sequence_a(player, tmp_path):
    folder = shot(tmp_path)
    player.load_videos_from_folder(str(folder))
    assert not player.is_sequence_active()  # 불러오면 첫 영상(mov)이 A로 열림
    item = seq_item(player, "tk2")

    player.seq_sidebar.itemClicked.emit(item)  # 연결을 거쳐 (on_seq_item_clicked)

    assert player.is_sequence_active()
    assert player.filename_a == virtual(os.path.join(str(folder), "tk2.seq"))
    assert player.filenameLabel.text() == "A: tk2.seq"


def test_seq_item_click_is_ignored_while_selected_playlist_plays(player, tmp_path, monkeypatch):
    """Mov 목록의 누르기와 같은 규칙: 선택 재생 중에는 누른 영상을 열지 않음."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    opened = []
    monkeypatch.setattr(player, "open_file", lambda *args: opened.append(args))
    player.is_playlist_playing = True

    player.on_seq_item_clicked(seq_item(player, "tk1"))

    assert opened == []
    player.is_playlist_playing = False
    player.on_seq_item_clicked(seq_item(player, "tk1"))
    assert opened == [("A", seq_item(player, "tk1").data(Qt.UserRole).identity)]


# ---------------------------------------------------------------- 다시 읽기


def test_refresh_updates_both_lists(player, tmp_path):
    folder = shot(tmp_path)
    player.load_videos_from_folder(str(folder))
    assert mov_names(player) == ["tk1.mov"] and seq_identities(player) == ["tk1.seq", "tk2.seq"]

    write_test_video(str(folder / "tk3.mov"))  # 새 영상
    make_seq(str(folder), "tk3", range(1, 4))  # 새 시퀀스
    for n in range(1, 7):
        os.remove(folder / f"tk1-{n:04d}.tga")  # 지워진 시퀀스
    make_seq(str(folder), "tk2", [4])  # 빠졌던 프레임이 생김
    refresh(player)

    assert mov_names(player) == ["tk1.mov", "tk3.mov"]
    assert seq_labels(player) == ["tk2 (0001–0006, 6프레임)", "tk3 (0001–0003, 3프레임)"]


def test_refresh_without_changes_leaves_seq_items_untouched(player, tmp_path):
    player.load_videos_from_folder(str(shot(tmp_path)))
    item = seq_item(player, "tk2")
    item.setData(Qt.UserRole + 40, "표시")  # 항목을 다시 만들면 사라짐
    item.setSelected(True)

    refresh(player)

    assert seq_item(player, "tk2").data(Qt.UserRole + 40) == "표시"
    assert [i.text() for i in player.seq_sidebar.selectedItems()] == [item.text()]


def test_refresh_keeps_selection_when_the_list_changes(player, tmp_path):
    folder = shot(tmp_path)
    player.load_videos_from_folder(str(folder))
    player.seq_sidebar.setCurrentItem(seq_item(player, "tk2"))
    seq_item(player, "tk2").setSelected(True)

    make_seq(str(folder), "tk0", range(1, 4))  # tk2 앞에 새 시퀀스
    refresh(player)

    assert seq_identities(player) == ["tk0.seq", "tk1.seq", "tk2.seq"]
    assert [i.data(Qt.UserRole).base for i in player.seq_sidebar.selectedItems()] == ["tk2"]
    assert player.seq_sidebar.currentItem().data(Qt.UserRole).base == "tk2"


def test_refresh_keeps_scroll_position_when_the_list_changes(player, tmp_path):
    folder = tmp_path / "many"
    write_test_video(str(folder / "a.mov"))
    for n in range(40):
        make_seq(str(folder), f"tk{n:02d}", range(1, 4))
    player.load_videos_from_folder(str(folder))
    player.show()
    player.sidebar_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    bar = player.seq_sidebar.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    scrolled = bar.value()

    make_seq(str(folder), "tk99", range(1, 4))
    refresh(player)
    QApplication.processEvents()

    assert player.seq_sidebar.count() == 41
    assert player.seq_sidebar.verticalScrollBar().value() == scrolled


def read_of(results):
    return video_list.SourcesRead(results=results, errors={}, notes={}, gone_files=set(), unverified=[])


def test_unread_source_keeps_its_sequences_and_gone_source_drops_them(player, tmp_path):
    """Mov 목록처럼: 읽지 못한 폴더(NAS 연결 끊김)의 항목은 남기고, 지워진 폴더의 항목은 뺌."""
    keep_dir, gone_dir, other_dir = tmp_path / "keep", tmp_path / "gone", tmp_path / "other"
    keep_source = video_list.ListSource("folder", str(keep_dir))
    gone_source = video_list.ListSource("folder", str(gone_dir))
    other_source = video_list.ListSource("folder", str(other_dir))
    player._set_seq_items([fake_seq(gone_dir, "g1"), fake_seq(keep_dir, "k1"), fake_seq(other_dir, "o1")])

    player._apply_seq_read(read_of({
        keep_source: None,  # 읽지 못함
        gone_source: video_list.FOLDER_GONE,
        other_source: video_list.ScanResult([], [], [fake_seq(other_dir, "o2")]),
    }))

    assert seq_identities(player) == ["k1.seq", "o2.seq"]  # 읽은 곳은 읽은 대로, 읽지 못한 곳은 그대로, 지워진 곳은 뺌


def test_unreadable_subfolder_keeps_its_sequences(player, tmp_path):
    root = tmp_path / "root"
    source = video_list.ListSource("folder", str(root))
    player._set_seq_items([fake_seq(root, "r1"), fake_seq(root / "locked", "l1"), fake_seq(root / "open", "p1")])

    player._apply_seq_read(read_of({
        source: video_list.ScanResult([], [(str(root / "locked"), PermissionError("denied"))],
                                      [fake_seq(root, "r1"), fake_seq(root / "open", "p2")]),
    }))

    assert seq_identities(player) == ["l1.seq", "p2.seq", "r1.seq"]  # 읽은 것(r1·p2)과 읽지 못한 폴더에 남긴 것(l1), 목록 규칙의 순서


def test_overlapping_sources_do_not_duplicate_a_sequence(player, tmp_path):
    root = tmp_path / "root"
    seq = fake_seq(root / "sub", "t1")
    outer, inner = video_list.ListSource("folder", str(root)), video_list.ListSource("folder", str(root / "sub"))

    player._apply_seq_read(read_of({outer: video_list.ScanResult([], [], [seq]), inner: video_list.ScanResult([], [], [seq])}))

    assert seq_identities(player) == ["t1.seq"]


# ---------------------------------------------------------------- Mov 쪽 기계장치와의 어울림


def test_showing_control_widgets_does_not_surface_mov_list_over_seq_tab(player, tmp_path):
    """V 키·전체화면 복원이 control_widgets를 하나씩 setVisible(True)함 — 사이드바가 탭 페이지가 됐으므로 Seq 탭이 보이는 동안
    Mov 목록을 손으로 보이게 하면 안 됨 (사이드바 컨테이너가 이미 목록 전체를 숨기고 보임). 항목이 있는 목록만 그 대상이 됨
    (get_valid_control_widgets가 `if widget`을 봄 — 빈 QListWidget은 거짓)."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    assert len(player.sidebar) > 0
    player.show()
    player.sidebar_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    assert player.seq_sidebar.isVisible() and not player.sidebar.isVisible()

    player.controls_visible = True
    player.restore_ui_elements()
    QApplication.processEvents()

    assert player.seq_sidebar.isVisible() and not player.sidebar.isVisible()


def wheel_over(player, widget, monkeypatch):
    monkeypatch.setattr(widget, "underMouse", lambda: True)
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    event.accept()
    position = player.positionScroll.value()
    player.wheelEvent(event)
    return event, position


@pytest.mark.parametrize("which", ["sidebar", "seq_sidebar"])
def test_wheel_over_a_sidebar_list_does_not_step_frames(player, tmp_path, monkeypatch, which):
    """사이드바 위의 휠은 프레임 이동이 아님 — Seq 목록도 Mov 목록처럼."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    assert player.cap_a is not None

    event, position = wheel_over(player, getattr(player, which), monkeypatch)

    assert not event.isAccepted()
    assert player.positionScroll.value() == position


# (키, 부르는 대상, 불리는 메서드): 목록이 포커스를 가진 채 먹어야 하는 단축키
LIST_SHORTCUTS = [
    # 프레임 이동·전체화면·썸네일: 창 전역 (목록이 . , F R 같은 글자 키를 '입력해서 찾기'로 먹으므로 목록에도 이벤트 필터가 있어야 함)
    (Qt.Key_Right, "player", "next_frame"), (Qt.Key_Left, "player", "prev_frame"),
    (Qt.Key_Period, "player", "next_frame"), (Qt.Key_Comma, "player", "prev_frame"),
    (Qt.Key_F, "player", "toggle_fullscreen"), (Qt.Key_R, "player", "regenerate_selected_thumbnails"),
    # 재생/정지·확대·축소·화면 맞춤: 이벤트 필터의 사이드바 목록 분기 (Mov·Seq 어느 목록이든)
    (Qt.Key_Space, "player", "toggle_play_pause"),
    (Qt.Key_Plus, "video", "zoom_in"), (Qt.Key_Equal, "video", "zoom_in"), (Qt.Key_2, "video", "zoom_in"),
    (Qt.Key_Minus, "video", "zoom_out"), (Qt.Key_1, "video", "zoom_out"),
    (Qt.Key_3, "video", "reset_view"), (Qt.Key_4, "video", "show_original_size"),
]


def pump(ms=60):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def focus_list(player, which):
    """which 목록의 탭을 보이고 그 목록에 키보드 포커스를 줌 (창을 보여야 포커스가 감).

    창이 활성되면 100ms 뒤 force_focus가 포커스를 창으로 되돌리므로(앱 동작) 그 타이머가 지난 뒤에 주고, 늦게 온 것에 뺏기면 다시 줌."""
    if not player.isVisible():
        player.show()
        pump(250)
    player.sidebar_tabs.setCurrentIndex(0 if which == "sidebar" else 1)
    widget = getattr(player, which)
    for _ in range(5):
        widget.setFocus()
        pump(30)
        if QApplication.focusWidget() is widget:
            break
    assert QApplication.focusWidget() is widget
    return widget


@pytest.mark.parametrize("which", ["sidebar", "seq_sidebar"])
@pytest.mark.parametrize("key, owner, action", LIST_SHORTCUTS)
def test_global_shortcuts_work_while_a_sidebar_list_has_focus(player, tmp_path, monkeypatch, which, key, owner, action):
    """Seq 항목을 눌러 목록이 포커스를 가진 채로도 프레임 이동·전체화면·재생/정지·확대·축소 같은 단축키가 먹음.
    Mov 목록 쪽도 같은 표로 확인해 Mov 동작이 그대로임을 못 박음."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    target = player if owner == "player" else player.videoWidget
    called = []
    monkeypatch.setattr(target, action, lambda *args: called.append(action))
    widget = focus_list(player, which)

    QTest.keyClick(widget, key)

    assert called == [action]


@pytest.mark.parametrize("key, action", [
    (Qt.Key_Return, "play_selected_files"), (Qt.Key_Enter, "play_selected_files"),
    (Qt.Key_Backslash, "toggle_play_pause_selected"),
])
def test_playlist_shortcuts_stay_mov_list_only(player, tmp_path, monkeypatch, key, action):
    """선택 재생(Enter·\\)은 재생목록 기계장치가 Mov 목록 전제라 Seq 목록에서는 먹지 않음 (Mov 목록은 그대로 먹음)."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    called = []
    monkeypatch.setattr(player, action, lambda *args: called.append(action))

    QTest.keyClick(focus_list(player, "sidebar"), key)
    assert called == [action]

    called.clear()
    QTest.keyClick(focus_list(player, "seq_sidebar"), key)
    assert called == []


def test_up_down_open_the_selected_item_only_on_the_mov_list(player, tmp_path, monkeypatch):
    """위아래 화살표로 선택을 옮기면 Mov 목록은 그 영상을 A로 엶 (Seq 목록은 누를 때만 엶 — 이 일은 Mov 목록 전용)."""
    player.load_videos_from_folder(str(shot(tmp_path)))
    opened = []
    monkeypatch.setattr(player, "load_selected_item_to_video_a", lambda: opened.append("mov"))

    QTest.keyClick(focus_list(player, "sidebar"), Qt.Key_Down)
    pump()
    assert opened == ["mov"]

    opened.clear()
    QTest.keyClick(focus_list(player, "seq_sidebar"), Qt.Key_Down)
    pump()
    assert opened == []
