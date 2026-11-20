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
from tests.test_sidebar_keys import seq_tab
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
    box, rect = group(player, widget), row_rect(widget, item)
    assert box.isVisible()
    geometry = box.geometry()
    assert rect.right() - 8 <= geometry.right() <= rect.right(), (geometry, rect)
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
    for i in range(40):
        shutil.copy(str(folder / "tk1.mov"), str(many / f"m{i:02d}.mov"))
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
