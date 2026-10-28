"""사이드바 All 탭: Mov·Seq 목록을 한 목록에 이름 자연 정렬로 섞어 보여 주고(시퀀스 글자는 하늘색),
항목을 누르면 종류대로 열며, 선택 재생은 선택 중 mov만 이어서 재생한다 (시퀀스는 건너뜀 — 전체 재생의 메모리 한계).
'Mov만 모두 선택'으로 mov만 골라 전체 재생할 수 있다. Mov·Seq 목록이 바뀌면 All 탭도 따라 바뀐다.

시퀀스 프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA. 창·대화상자는 conftest의 dialogs가 가로챔.
"""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from tests.conftest import write_test_video
from tests.test_sidebar_seq_tab import shot
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.sidebar_items import ALL_KIND_ROLE


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def show_all_tab(player, qapp):
    player.sidebar_tabs.setCurrentWidget(player.all_sidebar)
    qapp.processEvents()


def all_rows(player):
    widget = player.all_sidebar
    return [(widget.item(i).text(), widget.item(i).data(ALL_KIND_ROLE)) for i in range(widget.count())]


def all_item(player, kind, needle):
    widget = player.all_sidebar
    return next(widget.item(i) for i in range(widget.count())
                if widget.item(i).data(ALL_KIND_ROLE) == kind and needle in widget.item(i).text())


def wait_rebuild(qapp):
    """모델 변경 → 미룬 다시 만들기(디바운스)가 돌 때까지."""
    for _ in range(3):
        QTest.qWait(80)
        qapp.processEvents()


# ---------------------------------------------------------------- 목록


def test_all_tab_exists_after_mov_and_seq(player):
    tabs = player.sidebar_tabs
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert labels == ["Mov", "Seq", "All"]


def test_all_tab_lists_both_kinds_sorted_together(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    rows = all_rows(player)
    kinds = [kind for _text, kind in rows]
    assert kinds.count("mov") == 1 and kinds.count("seq") == 2
    # 자연 정렬: tk1 시퀀스·tk1.mov가 이웃하고 tk2가 뒤
    texts = [text for text, _kind in rows]
    assert [t.split()[0].rstrip(".mov") if t.endswith(".mov") else t.split()[0] for t in texts] == ["tk1", "tk1", "tk2"]


def test_all_seq_items_are_sky_colored_and_mov_default(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    seq_color = all_item(player, "seq", "tk1").foreground().color().name()
    mov_color = all_item(player, "mov", "tk1.mov").foreground().color().name()
    assert seq_color == "#5bc8ff"  # 어두운 테마의 하늘색
    assert mov_color != seq_color


def test_all_seq_color_follows_theme(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    player.set_light_theme()
    wait_rebuild(qapp)
    assert all_item(player, "seq", "tk1").foreground().color().name() == "#0b6ea8"
    player.set_dark_theme()
    wait_rebuild(qapp)
    assert all_item(player, "seq", "tk1").foreground().color().name() == "#5bc8ff"


def test_all_rebuilds_when_mov_list_changes_while_visible(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    extra = tmp_path / "extra.mov"
    write_test_video(str(extra))
    player.add_files_to_sidebar([str(extra)])
    wait_rebuild(qapp)
    assert any(kind == "mov" and "extra.mov" in text for text, kind in all_rows(player))


# ---------------------------------------------------------------- 열기


def test_all_click_opens_by_kind(player, qapp, tmp_path, monkeypatch):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    opened = []
    monkeypatch.setattr(player, "open_file", lambda slot, path: opened.append((slot, path)) or True)

    player.on_all_item_clicked(all_item(player, "mov", "tk1.mov"))
    player.on_all_item_clicked(all_item(player, "seq", "tk2"))

    assert len(opened) == 2
    assert opened[0][0] == "A" and opened[0][1].endswith("tk1.mov")
    assert opened[1][0] == "A" and opened[1][1].endswith("tk2.seq")


# ---------------------------------------------------------------- 선택 재생 (mov만)


def test_play_selected_from_all_queues_movs_only(player, qapp, tmp_path, monkeypatch):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    player.all_sidebar.selectAll()
    started = []
    monkeypatch.setattr(player, "play_current_playlist_item", lambda: started.append(True))

    player.play_selected_files()

    assert started == [True]
    assert len(player.playlist) == 1 and player.playlist[0].endswith("tk1.mov")


def test_play_selected_from_all_with_only_seqs_informs(player, qapp, tmp_path, dialogs):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    all_item(player, "seq", "tk2").setSelected(True)

    player.play_selected_files()

    assert player.is_playlist_playing is False
    assert player.playlist == []
    assert dialogs.messages[-1][2].startswith("선택에 mov가 없습니다")  # 새 안내 글 (예전 'Please select…'가 아님)


def test_mov_tab_play_selected_unchanged(player, qapp, tmp_path, monkeypatch):
    drop_folder(player, "video", shot(tmp_path))
    player.sidebar_tabs.setCurrentWidget(player.sidebar)
    player.sidebar.selectAll()
    started = []
    monkeypatch.setattr(player, "play_current_playlist_item", lambda: started.append(True))

    player.play_selected_files()

    assert started == [True]
    assert len(player.playlist) == 1 and player.playlist[0].endswith("tk1.mov")


def test_play_buttons_enabled_on_all_tab(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    assert player.playSelectedButton.isEnabled()
    player.sidebar_tabs.setCurrentWidget(player.seq_sidebar)
    qapp.processEvents()
    assert not player.playSelectedButton.isEnabled()


# ---------------------------------------------------------------- Mov만 모두 선택


def test_select_all_movs_selects_only_movs(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    player.all_sidebar.selectAll()  # 시퀀스까지 전부 선택된 상태에서
    player.select_all_movs()
    selected = player.all_sidebar.selectedItems()
    assert len(selected) == 1
    assert all(item.data(ALL_KIND_ROLE) == "mov" for item in selected)


def test_rebuild_keeps_selection_when_current_item_unselected(player, qapp, tmp_path):
    """'Mov만 모두 선택' 뒤(현재 항목은 선택에서 빠진 시퀀스일 수 있음) 다시 만들기가 선택을 바꾸지 않는다 —
    재생 강조·썸네일이 일으키는 다시 만들기마다 선택이 시퀀스로 뒤집히면 다음 선택 재생이 '선택에 mov가 없습니다'가 됨."""
    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    player.all_sidebar.setCurrentItem(all_item(player, "seq", "tk2"))  # 현재 항목 = 시퀀스
    player.select_all_movs()

    player._rebuild_all_list()

    selected = player.all_sidebar.selectedItems()
    assert [item.data(ALL_KIND_ROLE) for item in selected] == ["mov"]


def test_rebuild_keeps_scroll_position(player, qapp):
    from PyQt5.QtWidgets import QListWidgetItem

    for i in range(80):  # 스크롤이 생기게 가짜 mov 항목을 많이
        item = QListWidgetItem(f"clip_{i:03d}.mov")
        item.setToolTip(f"/tmp/clip_{i:03d}.mov")
        player.sidebar.addItem(item)
    player.resize(900, 400)
    player.show()  # offscreen — 레이아웃이 잡혀야 스크롤 범위가 생김
    show_all_tab(player, qapp)
    player._rebuild_all_list()
    bar = player.all_sidebar.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    value = bar.value()
    assert value > 0

    player._rebuild_all_list()

    assert bar.value() == value


def test_no_rebuild_scheduled_while_all_hidden(player, qapp, tmp_path):
    drop_folder(player, "video", shot(tmp_path))
    player.sidebar_tabs.setCurrentWidget(player.sidebar)
    qapp.processEvents()
    extra = tmp_path / "extra2.mov"
    write_test_video(str(extra))
    player.add_files_to_sidebar([str(extra)])
    assert not player._all_rebuild_timer.isActive()


def test_enter_on_all_list_plays_selected(player, qapp, tmp_path, monkeypatch):
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtCore import Qt as QtCore_Qt

    drop_folder(player, "video", shot(tmp_path))
    show_all_tab(player, qapp)
    calls = []
    monkeypatch.setattr(player, "play_selected_files", lambda: calls.append(True))
    ev = QKeyEvent(QEvent.KeyPress, QtCore_Qt.Key_Return, QtCore_Qt.NoModifier)
    assert player.eventFilter(player.all_sidebar, ev) is True
    assert calls == [True]


def test_context_menu_does_not_change_source_tab_selection(player, qapp, tmp_path, monkeypatch):
    """All 탭 우클릭이 메뉴 동작을 위해 선택을 원본 목록에 비추더라도, 메뉴가 닫히면 Mov·Seq 탭의 선택은
    이전 그대로여야 한다 (All 탭이 다른 탭의 상태를 바꾸면 안 됨)."""
    from PyQt5.QtWidgets import QMenu

    drop_folder(player, "video", shot(tmp_path))
    player.sidebar.selectAll()  # Mov 탭: 전부 선택된 상태 (폴더 불러오기 직후와 같음)
    before = [player.sidebar.item(i).isSelected() for i in range(player.sidebar.count())]
    show_all_tab(player, qapp)
    monkeypatch.setattr(QMenu, "exec_", lambda self, *args: None)

    seq_item = all_item(player, "seq", "tk2")
    rect = player.all_sidebar.visualItemRect(seq_item)
    player.show_all_context_menu(rect.center())

    after = [player.sidebar.item(i).isSelected() for i in range(player.sidebar.count())]
    assert after == before
