"""사이드바 Mov·Seq 탭과 Seq 목록: 한 번 읽은 폴더 목록에서 영상과 이미지 시퀀스를 함께 목록에 넣고 (첫 불러오기·끌어다 놓기·
목록 다시 읽기), 탭 전환은 디스크를 읽지 않으며, Seq 항목을 누르면 시퀀스를 A로 엶. Mov 탭(self.sidebar)은 그대로.

시퀀스 프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA. 예시 이름만 씀 (공개 저장소). 창·대화상자는 conftest의
dialogs가 가로챔 (실제 QMessageBox를 띄우지 않음).
"""

import os

import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
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


@pytest.mark.parametrize("key, action", [
    (Qt.Key_Right, "next_frame"), (Qt.Key_Left, "prev_frame"),
    (Qt.Key_Period, "next_frame"), (Qt.Key_Comma, "prev_frame"),  # 목록이 글자 키를 '입력해서 찾기'로 먹는 키들
    (Qt.Key_F, "toggle_fullscreen"), (Qt.Key_R, "regenerate_selected_thumbnails"),
])
def test_global_shortcuts_work_while_the_seq_list_has_focus(player, tmp_path, monkeypatch, key, action):
    """Seq 항목을 눌러 목록이 포커스를 가진 채로도 프레임 이동·전체화면 같은 전역 단축키가 먹음 — Mov 목록처럼.
    (목록은 . , F R 같은 글자 키를 '입력해서 찾기'로 먹으므로 창의 이벤트 필터를 목록에도 걸어야 함)"""
    player.load_videos_from_folder(str(shot(tmp_path)))
    called = []
    monkeypatch.setattr(player, action, lambda *args: called.append(action))
    player.show()
    player.sidebar_tabs.setCurrentIndex(1)
    player.seq_sidebar.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is player.seq_sidebar

    QTest.keyClick(player.seq_sidebar, key)

    assert called == [action]
