"""사이드바 줄의 A·B 단추 (sidebar_ab_buttons — 사용자 요청 2026-11-20): Mov·Seq·All 목록 줄에 마우스를 올리면 그 줄 오른쪽 끝에
[A][B]가 뜸. 마우스 움직임은 뷰포트에 MouseMove를 보내고, 커서가 필요한 갈래(스크롤·목록 변경·탭)를 위해 QCursor도 그 자리로 옮김
(offscreen에서도 QCursor.setPos·pos가 동작함). 단추를 누르는 일은 아래 'A·B 누르기' 묶음.
"""

import re
import shutil

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QColor, QCursor, QMouseEvent
from PyQt5.QtWidgets import QApplication

from tests.test_sidebar_all_tab import all_item, show_all_tab
from tests.test_sidebar_keys import key_event, seq_tab
from tests.test_sidebar_open_with import folder, mov_item  # noqa: F401 (folder: fixture)
from tests.test_sidebar_seq_tab import seq_item
from tests.test_sidebar_take_colors import contrast
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import error_window, main_window_styles, sidebar_ab_buttons, ui_text
from yesoncheck.sidebar_ab_buttons import AB_COLORS, ROW_BG, ab_buttons_style


@pytest.fixture
def player(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1200, 800)
    player.show()
    qapp.processEvents()
    return player


@pytest.fixture
def loaded(player, folder, qapp):  # noqa: F811
    """목록에 tk1.mov·tk3.mov와 시퀀스 tk1·tk2."""
    drop_folder(player, "video", folder)
    qapp.processEvents()
    return player


def group(player, widget):
    return player._sidebar_ab[widget]


def row_rect(widget, item):
    return widget.visualItemRect(item)


def hover(qapp, widget, pos):
    """커서를 뷰포트의 pos로 옮기고 그 자리의 MouseMove를 보냄."""
    QCursor.setPos(widget.viewport().mapToGlobal(pos))
    QApplication.sendEvent(widget.viewport(), QMouseEvent(QEvent.MouseMove, QPointF(pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    qapp.processEvents()


def hover_item(qapp, widget, item):
    hover(qapp, widget, row_rect(widget, item).center())


def settle(qapp):
    for _ in range(3):
        qapp.processEvents()


def assert_on_row(player, widget, item):
    """묶음이 그 줄 오른쪽 끝(줄이 뷰포트보다 넓으면 — 긴 이름의 가로 스크롤 — 뷰포트 오른쪽 끝)·세로 가운데에, 뷰포트 안에."""
    box, rect = group(player, widget), row_rect(widget, item)
    assert box.isVisible()
    geometry = box.geometry()
    right_end = min(rect.right(), widget.viewport().rect().right())
    assert right_end - 8 <= geometry.right() <= right_end, (geometry, rect, widget.viewport().rect())
    assert geometry.left() >= 0, geometry
    assert abs(geometry.center().y() - rect.center().y()) <= 1, (geometry, rect)
    assert rect.top() <= geometry.top() and geometry.bottom() <= rect.bottom(), (geometry, rect)


# ---------------------------------------------------------------- 뜨고 숨기

def test_hover_shows_buttons_at_the_right_end_of_that_row(loaded, qapp):
    tk1 = mov_item(loaded, "tk1.mov")
    assert not group(loaded, loaded.sidebar).isVisible()
    hover_item(qapp, loaded.sidebar, tk1)
    assert_on_row(loaded, loaded.sidebar, tk1)
    box = group(loaded, loaded.sidebar)
    assert (box.button_a.text(), box.button_b.text()) == ("A", "B")


def test_buttons_follow_the_cursor_and_hide_off_rows(loaded, qapp):
    widget = loaded.sidebar
    hover_item(qapp, widget, mov_item(loaded, "tk1.mov"))
    tk3 = mov_item(loaded, "tk3.mov")
    hover_item(qapp, widget, tk3)
    assert_on_row(loaded, widget, tk3)
    below = widget.visualItemRect(widget.item(widget.count() - 1)).bottom() + 5
    assert below < widget.viewport().height()
    hover(qapp, widget, QPoint(20, below))
    assert not group(loaded, widget).isVisible()
    hover_item(qapp, widget, tk3)
    QApplication.sendEvent(widget.viewport(), QEvent(QEvent.Leave))
    assert not group(loaded, widget).isVisible()


@pytest.mark.parametrize("where", ["mov", "seq", "all_mov", "all_seq"])
def test_all_three_tabs(loaded, qapp, where):
    if where == "mov":
        widget, item = loaded.sidebar, mov_item(loaded, "tk1.mov")
    elif where == "seq":
        seq_tab(loaded, qapp)
        widget, item = loaded.seq_sidebar, seq_item(loaded, "tk1")
    else:
        show_all_tab(loaded, qapp)
        widget, item = loaded.all_sidebar, all_item(loaded, where[4:], "tk1")
    hover_item(qapp, widget, item)
    assert_on_row(loaded, widget, item)
    others = [w for w in (loaded.sidebar, loaded.seq_sidebar, loaded.all_sidebar) if w is not widget]
    assert not any(group(loaded, w).isVisible() for w in others)


def test_thumbnail_mode_centres_on_the_tall_row(loaded, qapp):
    loaded.thumbnailModeButton.click()
    settle(qapp)
    tk1 = mov_item(loaded, "tk1.mov")
    assert row_rect(loaded.sidebar, tk1).height() > 40
    hover_item(qapp, loaded.sidebar, tk1)
    assert_on_row(loaded, loaded.sidebar, tk1)


def test_scroll_moves_buttons_to_the_row_now_under_the_cursor(player, folder, tmp_path, qapp):  # noqa: F811
    many = tmp_path / "many"
    many.mkdir()
    for i in range(150):  # 줄이 낮은 환경(글꼴 없는 Windows CI — 12px)에서도 목록이 넘쳐 스크롤이 생기게
        shutil.copy(str(folder / "tk1.mov"), str(many / f"m{i:03d}.mov"))
    drop_folder(player, "video", many)
    settle(qapp)
    widget = player.sidebar
    bar = widget.verticalScrollBar()
    assert bar.maximum() > 0
    point = row_rect(widget, widget.item(2)).center()
    hover(qapp, widget, point)
    bar.setValue(bar.maximum())
    settle(qapp)
    now = widget.itemAt(point)
    assert now is not None and now is not widget.item(2)
    assert_on_row(player, widget, now)


def test_resize_keeps_buttons_at_the_right_end(loaded, qapp):
    widget, tk1 = loaded.sidebar, mov_item(loaded, "tk1.mov")
    hover_item(qapp, widget, tk1)
    sizes = loaded.mainSplitter.sizes()
    loaded.mainSplitter.setSizes([sizes[0] + 120, sizes[1] - 120] + sizes[2:])
    settle(qapp)
    QCursor.setPos(widget.viewport().mapToGlobal(row_rect(widget, tk1).center()))
    settle(qapp)
    assert_on_row(loaded, widget, tk1)


def test_buttons_follow_the_row_after_the_list_changes(loaded, qapp):
    widget = loaded.sidebar
    last = widget.item(widget.count() - 1)
    hover_item(qapp, widget, last)
    assert group(loaded, widget).isVisible()
    widget.takeItem(0)  # 줄이 한 칸씩 올라가 커서 아래(옛 마지막 줄 자리)가 비게 됨
    settle(qapp)
    assert not group(loaded, widget).isVisible()
    first = widget.item(0)
    hover_item(qapp, widget, first)
    widget.clear()
    settle(qapp)
    assert not group(loaded, widget).isVisible()


def test_buttons_hide_on_tab_change_and_window_deactivate(loaded, qapp):
    widget, tk1 = loaded.sidebar, mov_item(loaded, "tk1.mov")
    hover_item(qapp, widget, tk1)
    seq_tab(loaded, qapp)
    assert not group(loaded, widget).isVisible()
    QCursor.setPos(loaded.mapToGlobal(QPoint(loaded.width() - 5, loaded.height() - 5)))  # 목록 밖
    loaded.sidebar_tabs.setCurrentWidget(widget)
    settle(qapp)
    assert not group(loaded, widget).isVisible()
    hover_item(qapp, widget, tk1)
    QApplication.sendEvent(loaded, QEvent(QEvent.WindowDeactivate))
    assert not group(loaded, widget).isVisible()


def test_buttons_take_no_focus(loaded):
    for widget in (loaded.sidebar, loaded.seq_sidebar, loaded.all_sidebar):
        box = group(loaded, widget)
        assert box.button_a.focusPolicy() == Qt.NoFocus and box.button_b.focusPolicy() == Qt.NoFocus
        assert box.focusPolicy() == Qt.NoFocus


# ---------------------------------------------------------------- 색·글자

def _hue(color):
    return QColor(color).hsvHue()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_colors_meet_contrast_in_both_themes(theme):
    for side in ("A", "B"):
        colors = AB_COLORS[theme][side]
        for state in ("bg", "hover", "pressed"):
            assert contrast(colors["fg"], colors[state]) >= 4.5, (theme, side, state)
    assert _hue(AB_COLORS[theme]["B"]["bg"]) - _hue("#ff9900") >= 8  # 강조 주황보다 노란 쪽
    gap = abs(_hue(AB_COLORS[theme]["A"]["bg"]) - _hue(AB_COLORS[theme]["B"]["bg"]))
    assert min(gap, 360 - gap) >= 120  # 파랑·금색


@pytest.mark.parametrize("theme, sheet", [("dark", main_window_styles.DARK_STYLESHEET),
                                          ("light", main_window_styles.LIGHT_STYLESHEET)])
def test_row_background_matches_the_theme_sheet(theme, sheet):
    normal = re.search(r"QListWidget, QListView, QMenu \{[^}]*?background: (#[0-9a-fA-F]+);", sheet).group(1)
    selected = re.search(r"QListWidget::item:selected, QListView::item:selected \{[^}]*?background: (#[0-9a-fA-F]+);",
                         sheet).group(1)
    assert ROW_BG[theme] == {"normal": normal, "selected": selected}


def test_theme_switch_recolors_buttons(loaded, qapp):
    widget, tk1 = loaded.sidebar, mov_item(loaded, "tk1.mov")
    widget.clearSelection()
    hover_item(qapp, widget, tk1)
    assert group(loaded, widget).styleSheet() == ab_buttons_style("dark", ROW_BG["dark"]["normal"])
    loaded.set_light_theme()
    qapp.processEvents()
    assert group(loaded, widget).styleSheet() == ab_buttons_style("light", ROW_BG["light"]["normal"])
    tk1.setSelected(True)
    hover_item(qapp, widget, tk1)
    assert group(loaded, widget).styleSheet() == ab_buttons_style("light", ROW_BG["light"]["selected"])


def test_tooltips_follow_language(loaded):
    box = group(loaded, loaded.sidebar)
    assert box.button_a.toolTip() == ui_text.text("side_ab.open_a") == "비디오 A로 열기 ([)"
    assert box.button_b.toolTip() == "비디오 B로 열고 와이프 켜기 (])"
    ui_text.set_language("en")
    loaded.retranslate_ui()
    for widget in (loaded.sidebar, loaded.seq_sidebar, loaded.all_sidebar):
        assert group(loaded, widget).button_a.toolTip() == "Open as video A ([)"
        assert group(loaded, widget).button_b.toolTip() == "Open as video B and turn on wipe (])"


def test_filter_failure_is_reported_once(loaded, qapp, monkeypatch):
    reports = []
    monkeypatch.setattr(error_window, "report_from_handler", lambda prefix, context: reports.append((prefix, context)))

    def broken(*_args, **_kwargs):
        raise RuntimeError("시험")

    monkeypatch.setattr(loaded, "_place_ab_buttons", broken)
    tk1 = mov_item(loaded, "tk1.mov")
    hover_item(qapp, loaded.sidebar, tk1)
    hover_item(qapp, loaded.sidebar, tk1)
    assert len(reports) == 1 and reports[0][0] == sidebar_ab_buttons.AB_LOG_PREFIX


def test_list_signals_while_the_window_is_deleted_do_not_raise(loaded):
    """창이 지워질 때 목록이 지워지며 신호(rowsRemoved 등)를 내는데 그때 다시 맞춤 타이머는 이미 지워졌을 수 있음 — 건드리지 않음."""
    from PyQt5 import sip

    sip.delete(loaded._sidebar_ab_timers[loaded.sidebar])
    loaded._schedule_ab_refresh(loaded.sidebar)  # 예외 없음


def test_deleting_the_window_reports_nothing(dialogs, folder, tmp_path, qapp, monkeypatch, capsys):  # noqa: F811
    """앱을 끝낼 때처럼 창을 sip.delete로 지우는 동안 필터·신호가 지워진 목록·단추를 건드려 거짓 오류(창·트레이스백)를 내지 않음."""
    from PyQt5 import sip

    from yesoncheck.main_window import VideoPlayer

    reports = []
    monkeypatch.setattr(error_window, "report_from_handler", lambda prefix, context: reports.append((prefix, context)))
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", make_config(str(tmp_path), {}))
    window = VideoPlayer()
    window.show()
    qapp.processEvents()
    drop_folder(window, "video", folder)
    qapp.processEvents()
    hover_item(qapp, window.sidebar, mov_item(window, "tk1.mov"))
    window.close()
    for _ in range(10):
        qapp.processEvents()
    sip.delete(window)
    qapp.processEvents()
    assert reports == []
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------- A·B 누르기

def _target(loaded, qapp, where):
    """(목록, 줄, 열릴 경로의 끝) — A는 열어 둔 채(B를 열면 와이프가 켜지게 같은 종류로)."""
    seq_identity = seq_item(loaded, "tk2").data(Qt.UserRole).identity if loaded.seq_sidebar.count() else None
    if where == "mov":
        assert loaded.open_file("A", mov_item(loaded, "tk1.mov").toolTip())
        return loaded.sidebar, mov_item(loaded, "tk3.mov"), "tk3.mov"
    if where == "seq":
        assert loaded.open_file("A", seq_identity)
        seq_tab(loaded, qapp)
        return loaded.seq_sidebar, seq_item(loaded, "tk1"), "tk1.seq"
    show_all_tab(loaded, qapp)
    if where == "all_mov":
        assert loaded.open_file("A", mov_item(loaded, "tk1.mov").toolTip())
        return loaded.all_sidebar, all_item(loaded, "mov", "tk3"), "tk3.mov"
    assert loaded.open_file("A", seq_identity)
    return loaded.all_sidebar, all_item(loaded, "seq", "tk1"), "tk1.seq"


@pytest.mark.parametrize("where", ["mov", "seq", "all_mov", "all_seq"])
def test_a_is_the_same_as_clicking_the_row(loaded, qapp, where):
    widget, item, expected = _target(loaded, qapp, where)
    other = next(widget.item(i) for i in range(widget.count()) if widget.item(i) is not item)
    widget.clearSelection()
    other.setSelected(True)
    loaded.wipeCheckBox.setChecked(False)
    hover_item(qapp, widget, item)
    group(loaded, widget).button_a.click()
    qapp.processEvents()
    assert widget.selectedItems() == [item] and widget.currentItem() is item
    assert loaded.filename_a.endswith(expected)
    assert not loaded.wipeCheckBox.isChecked()


@pytest.mark.parametrize("where", ["mov", "seq", "all_mov", "all_seq"])
def test_b_opens_b_with_wipe_and_keeps_the_selection(loaded, qapp, where):
    widget, item, expected = _target(loaded, qapp, where)
    a_before = loaded.filename_a
    others = [widget.item(i) for i in range(widget.count()) if widget.item(i) is not item][:2]
    widget.clearSelection()
    for other in others:
        other.setSelected(True)
    loaded.wipeCheckBox.setChecked(False)
    hover_item(qapp, widget, item)
    group(loaded, widget).button_b.click()
    qapp.processEvents()
    assert sorted(map(id, widget.selectedItems())) == sorted(map(id, others))  # 고른 줄은 그대로
    assert loaded.filename_b.endswith(expected) and loaded.filename_a == a_before
    assert (loaded.wipeCheckBox.isChecked(), loaded.wipeXButton.isChecked(), loaded.wipeYButton.isChecked()) == (True, True, False)


def test_click_opens_the_row_under_the_button_now(loaded, qapp, capsys):
    widget = loaded.sidebar
    assert loaded.open_file("A", mov_item(loaded, "tk1.mov").toolTip())
    first = widget.item(0)
    hover_item(qapp, widget, first)
    now = widget.item(1)
    widget.takeItem(0)  # 단추 자리에 다음 줄이 올라옴 (다시 맞추기 전에 누름 — 이벤트를 돌리지 않음)
    group(loaded, widget).button_b.click()
    assert loaded.filename_b == now.toolTip()
    last = widget.item(widget.count() - 1)
    hover_item(qapp, widget, last)
    loaded._release_side("B")
    widget.takeItem(0)  # 단추 자리(옛 마지막 줄)가 빔
    group(loaded, widget).button_b.click()
    assert not loaded.filename_b
    assert "[A·B 단추] 단추 자리에 줄이 없습니다" in capsys.readouterr().out


def test_disabled_while_playing_a_selection(loaded, qapp):
    widget, tk3 = loaded.sidebar, mov_item(loaded, "tk3.mov")
    assert loaded.open_file("A", mov_item(loaded, "tk1.mov").toolTip())
    loaded.wipeCheckBox.setChecked(False)
    loaded.is_playlist_playing = True
    hover_item(qapp, widget, tk3)
    box = group(loaded, widget)
    assert not box.button_a.isEnabled() and not box.button_b.isEnabled()
    assert box.button_a.toolTip() == box.button_b.toolTip() == ui_text.text("side_ab.playlist")
    box.button_b.click()
    loaded._ab_open(widget, "B")
    loaded._ab_open(widget, "A")
    assert not loaded.filename_b and not loaded.wipeCheckBox.isChecked()
    assert loaded.filename_a.endswith("tk1.mov")
    loaded.is_playlist_playing = False
    hover_item(qapp, widget, tk3)
    assert box.button_a.isEnabled() and box.button_b.isEnabled()
    assert box.button_b.toolTip() == ui_text.text("side_ab.open_b")


def test_key_and_button_share_the_path_rule(loaded, qapp):
    assert loaded.open_file("A", seq_item(loaded, "tk2").data(Qt.UserRole).identity)
    show_all_tab(loaded, qapp)
    widget, item = loaded.all_sidebar, all_item(loaded, "seq", "tk1")
    widget.clearSelection()
    item.setSelected(True)
    widget.setCurrentItem(item)
    assert loaded.eventFilter(widget, key_event(Qt.Key_BracketRight, "]")) is True
    by_key = loaded.filename_b
    loaded._release_side("B")
    hover_item(qapp, widget, item)
    group(loaded, widget).button_b.click()
    assert by_key and loaded.filename_b == by_key


# ---------------------------------------------------------------- 단추 위의 휠·우클릭은 목록 것

def test_wheel_over_buttons_scrolls_the_list(player, folder, tmp_path, qapp):  # noqa: F811
    """단추가 커서 아래 줄 오른쪽 끝을 따라오므로 휠을 굴릴 때 커서가 단추 위일 수 있음 — 단추가 휠을 먹지 않고 목록이 스크롤됨."""
    from PyQt5.QtGui import QWheelEvent

    many = tmp_path / "many"
    many.mkdir()
    for i in range(150):  # 줄이 낮은 환경(글꼴 없는 Windows CI — 12px)에서도 목록이 넘쳐 스크롤이 생기게
        shutil.copy(str(folder / "tk1.mov"), str(many / f"m{i:03d}.mov"))
    drop_folder(player, "video", many)
    settle(qapp)
    widget = player.sidebar
    hover_item(qapp, widget, widget.item(2))
    button = group(player, widget).button_b
    bar = widget.verticalScrollBar()
    before = bar.value()
    local = QPoint(button.width() // 2, button.height() // 2)
    QApplication.sendEvent(button, QWheelEvent(QPointF(local), QPointF(button.mapToGlobal(local)), QPoint(0, 0), QPoint(0, -120),
                                               Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    qapp.processEvents()
    assert bar.value() > before


def test_right_click_on_buttons_opens_the_row_menu(loaded, qapp, monkeypatch):
    from PyQt5.QtGui import QContextMenuEvent
    from PyQt5.QtWidgets import QMenu

    shown = []
    monkeypatch.setattr(QMenu, "exec_", lambda menu, *_a: shown.append([a.text() for a in menu.actions()]))
    widget, tk3 = loaded.sidebar, mov_item(loaded, "tk3.mov")
    hover_item(qapp, widget, tk3)
    button = group(loaded, widget).button_b
    local = QPoint(button.width() // 2, button.height() // 2)
    QApplication.sendEvent(button, QContextMenuEvent(QContextMenuEvent.Mouse, local, button.mapToGlobal(local)))
    qapp.processEvents()
    assert shown and ui_text.text("side_menu.open_b") in shown[-1]
    assert widget.selectedItems() == [tk3]  # 메뉴를 연 줄


# ---------------------------------------------------------------- 리뷰에서 찾은 것

def test_long_names_keep_buttons_inside_the_viewport(loaded, folder, qapp):  # noqa: F811
    """이름이 사이드바보다 긴 영상이 하나라도 있으면 ListMode는 모든 줄을 그 폭으로 넓힘(가로 스크롤) — 단추는 뷰포트 오른쪽 끝에."""
    widget = loaded.sidebar
    long_name = "EP101_SC050_LAYOUT_TK1_" + "x" * 60 + ".mov"
    shutil.copy(str(folder / "tk1.mov"), str(folder / long_name))
    loaded.add_files_to_sidebar([str(folder / long_name)])
    settle(qapp)
    tk1 = mov_item(loaded, "tk1.mov")
    assert row_rect(widget, tk1).right() > widget.viewport().rect().right()  # 줄이 뷰포트보다 넓음
    hover_item(qapp, widget, tk1)
    assert_on_row(loaded, widget, tk1)


def test_selection_change_recolors_under_buttons(loaded, qapp):
    widget, tk1 = loaded.sidebar, mov_item(loaded, "tk1.mov")
    widget.clearSelection()
    hover_item(qapp, widget, tk1)
    assert group(loaded, widget).styleSheet() == ab_buttons_style("dark", ROW_BG["dark"]["normal"])
    widget.setCurrentItem(tk1)  # 줄을 누름·↑↓와 같은 선택 바뀜 (커서는 그대로)
    settle(qapp)
    assert group(loaded, widget).styleSheet() == ab_buttons_style("dark", ROW_BG["dark"]["selected"])


def _mouse(kind, widget, local, modifiers=Qt.NoModifier):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    return QMouseEvent(kind, QPointF(local), QPointF(widget.mapToGlobal(local)), Qt.LeftButton, buttons, modifiers)


def _double_click(widget, local):
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease):
        QApplication.sendEvent(widget, _mouse(kind, widget, local))


def test_double_click_on_a_button_opens_once(loaded, qapp, monkeypatch):
    opened = []
    real_open = loaded.open_file
    monkeypatch.setattr(loaded, "open_file", lambda *args: opened.append(args) or real_open(*args))
    widget, tk3 = loaded.sidebar, mov_item(loaded, "tk3.mov")
    hover_item(qapp, widget, tk3)
    for name in ("button_a", "button_b"):
        opened.clear()
        button = getattr(group(loaded, widget), name)
        _double_click(button, QPoint(button.width() // 2, button.height() // 2))
        qapp.processEvents()
        assert len(opened) == 1, (name, opened)


def test_a_gives_the_list_focus_like_a_click(loaded, qapp):
    loaded.activateWindow()
    QApplication.setActiveWindow(loaded)
    loaded.videoWidget.setFocus()
    qapp.processEvents()
    widget, tk3 = loaded.sidebar, mov_item(loaded, "tk3.mov")
    assert not widget.hasFocus()
    hover_item(qapp, widget, tk3)
    group(loaded, widget).button_a.click()
    qapp.processEvents()
    assert widget.hasFocus()


def test_thumbnail_gaps_do_not_hide_buttons(loaded, qapp):
    """썸네일 모드는 줄 사이에 틈(spacing)이 있음 — 틈을 지날 때 단추가 숨었다 뜨며 깜빡이지 않게 가까운 줄에 둠."""
    loaded.thumbnailModeButton.click()
    settle(qapp)
    widget = loaded.sidebar
    first, second = widget.item(0), widget.item(1)
    gap_top, gap_bottom = row_rect(widget, first).bottom() + 1, row_rect(widget, second).top() - 1
    assert gap_bottom >= gap_top  # 틈이 있음
    for y in range(gap_top, gap_bottom + 1):
        hover(qapp, widget, QPoint(widget.viewport().width() // 2, y))
        assert group(loaded, widget).isVisible(), y


@pytest.mark.parametrize("modifier", [Qt.ShiftModifier, Qt.ControlModifier])
def test_modified_click_on_buttons_is_a_click_on_the_row(loaded, qapp, modifier):
    """Shift·Ctrl+클릭이 단추 자리(줄 오른쪽 끝)에 걸려도 그 줄을 그 키로 누른 것과 같음 — 범위 고르기·더해 고르기."""
    widget, tk1, tk3 = loaded.sidebar, mov_item(loaded, "tk1.mov"), mov_item(loaded, "tk3.mov")

    def click_with(target, local):
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            QApplication.sendEvent(target, _mouse(kind, target, local, modifier))
        qapp.processEvents()

    def state():
        return sorted(item.text() for item in widget.selectedItems()), loaded.filename_a

    widget.clearSelection()
    widget.setCurrentItem(tk1)
    click_with(widget.viewport(), QPoint(20, row_rect(widget, tk3).center().y()))  # 줄 왼쪽을 그 키로 누름
    on_row = state()
    widget.clearSelection()
    widget.setCurrentItem(tk1)
    hover_item(qapp, widget, tk3)
    button = group(loaded, widget).button_a
    click_with(button, QPoint(button.width() // 2, button.height() // 2))
    assert state() == on_row
    assert len(on_row[0]) == 2  # 범위·더해 고르기가 된 상태 (tk1과 tk3)


def test_closed_window_is_not_kept_alive(dialogs, tmp_path, qapp, monkeypatch):
    """닫고 놓은 창은 남지 않음 — 단추·목록 신호에 창(self)을 붙잡는 람다를 이으면 PyQt가 람다를 강하게 쥐어(파이썬 래퍼가 그때그때
    생기는 스크롤바·모델에 이으면 GC도 그 고리를 끊지 못함) 창이 영영 남았음: 시험마다 창이 쌓여 전체 시험이 끝나지 않았고 앱도 새 창마다 샘."""
    import gc
    import weakref

    from yesoncheck.main_window import VideoPlayer

    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", make_config(str(tmp_path), {}))
    window = VideoPlayer()
    window.show()
    qapp.processEvents()
    hover(qapp, window.sidebar, QPoint(5, 5))
    window.close()
    qapp.processEvents()
    ref = weakref.ref(window)
    del window
    for _ in range(3):
        gc.collect()
        qapp.processEvents()
    assert ref() is None


def test_closing_the_window_detaches_filters_and_signals(loaded, qapp, monkeypatch):
    """창을 닫으면 A·B의 필터를 떼고 신호를 끊음 — 닫힌 창이 나중에(시험 프로세스 끝의 QApplication 정리처럼) 지워질 때 파이썬 필터·슬롯이
    불리지 않게(그 정리 중에 파이썬이 불리면 간헐 세그폴트 — 11-16 '앱을 끝낼 때의 간헐 세그폴트', 이 시험 파일을 혼자 돌릴 때 한 번 겪음)."""
    calls = []
    real_filter = sidebar_ab_buttons._AbHoverFilter.eventFilter
    monkeypatch.setattr(sidebar_ab_buttons._AbHoverFilter, "eventFilter",
                        lambda self, watched, event: calls.append(event.type()) or real_filter(self, watched, event))
    loaded.close()
    qapp.processEvents()
    calls.clear()
    widget = loaded.sidebar
    timer = loaded._sidebar_ab_timers[widget]
    QApplication.sendEvent(widget.viewport(), QMouseEvent(QEvent.MouseMove, QPointF(5, 5), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    QApplication.sendEvent(loaded, QEvent(QEvent.WindowDeactivate))
    widget.takeItem(0)  # 목록 신호 → (이어져 있으면) 다시 맞춤 타이머가 돎
    widget.clearSelection()
    assert not timer.isActive()  # 신호가 끊겨 슬롯이 불리지 않음
    qapp.processEvents()
    assert calls == []
    assert not any(box.isVisible() for box in loaded._sidebar_ab.values())


def test_buttons_fit_a_low_row(loaded, qapp):
    """줄이 낮아도(글꼴 없는 Windows CI는 12px) 묶음이 줄 안에 — 단추 높이에 바닥값을 두면 위아래로 삐져나왔음."""
    from PyQt5.QtCore import QSize

    widget, tk1 = loaded.sidebar, mov_item(loaded, "tk1.mov")
    tk1.setSizeHint(QSize(100, 12))
    settle(qapp)
    assert row_rect(widget, tk1).height() == 12
    hover_item(qapp, widget, tk1)
    assert_on_row(loaded, widget, tk1)
