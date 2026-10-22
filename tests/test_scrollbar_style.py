"""메인 창 스타일시트의 스크롤바: 화살표 버튼이 핸들이 움직이는 범위를 가리지 않아야 함.

사용자 보고 (2026-10-22): 사이드바 영상 목록의 세로 스크롤바 핸들이 맨 위에서는 위쪽 화살표 버튼 밑에 깔려 끌리지 않고,
휠로 조금 내린 뒤에야 끌림. 메인 창 스타일시트(`player_base`의 처음 스타일시트와 `set_dark_theme`)가 QScrollBar의 테두리·
배경·핸들만 정하고 화살표 버튼(::add-line·::sub-line)은 숨기지도 여백을 두지도 않아, QStyleSheetStyle이 핸들을 스크롤바
전체 폭에 놓는 동안 기본 스타일은 양 끝에 버튼을 그림 → 맨 위(값 0)에서 핸들(cocoa y=1..39)이 위쪽 버튼(y=0..14)과 겹치고
핸들 윗부분을 누르면 SC_ScrollBarSubLine으로 판정됨. 가로 스크롤바(볼륨 막대 overlayVolume 포함)는 왼쪽 끝에서 같은 겹침.

시험은 진짜 VideoPlayer에 걸린 스타일시트 아래에서 QStyle이 알려 주는 구역 사각형과 누르기 판정을 본다.
"""

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QApplication, QScrollBar, QStyle, QStyleOptionSlider

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


# 핸들의 끝에서 안쪽으로 들일 칸 수. QStyleSheetStyle은 앞뒤 쪽 넘기기 구역(SubPage·AddPage)을 핸들 쪽으로 1칸 겹쳐 돌려주므로(스타일시트
# 스크롤바 어디서나 같음 — 버튼과 무관) 핸들 맨 끝 한 줄은 쪽 넘기기로 판정됨. 버튼이 가리던 구역은 그보다 훨씬 넓었음(cocoa 15칸).
EDGE_INSET = 3


def overlaps(a, b):
    """두 구역이 겹치는가. 크기 0인 구역(숨긴 버튼)은 겹치지 않음 — QRect.intersects는 높이(폭)만 0인 구역을 겹친다고 할 수 있음."""
    return not a.isEmpty() and not b.isEmpty() and a.intersects(b)


@pytest.fixture(params=["처음 스타일시트", "set_dark_theme"])
def window(request, new_player, dialogs, tmp_path):
    """스타일시트를 두 가지 경로로 건 메인 창: 처음 걸리는 것, 그리고 set_dark_theme가 다시 거는 것."""
    player = new_player(make_config(str(tmp_path), {}))
    if request.param == "set_dark_theme":
        player.setStyleSheet("")  # 처음 것을 지워 set_dark_theme의 것만 남김
        assert player.styleSheet() == ""
        player.set_dark_theme()
    assert "QScrollBar:vertical" in player.styleSheet()
    player.resize(1200, 800)
    player.show()
    QApplication.processEvents()
    yield player
    assert dialogs.errors() == []


class Zones:
    """스크롤바의 지금 모양에서 QStyle이 알려 주는 구역들과 누르기 판정."""

    def __init__(self, scrollbar):
        QApplication.processEvents()
        self.scrollbar = scrollbar
        self.horizontal = scrollbar.orientation() == Qt.Horizontal
        opt = QStyleOptionSlider()
        opt.initFrom(scrollbar)
        opt.subControls = QStyle.SC_All
        opt.orientation = scrollbar.orientation()
        opt.minimum, opt.maximum = scrollbar.minimum(), scrollbar.maximum()
        opt.sliderPosition = opt.sliderValue = scrollbar.value()
        opt.singleStep, opt.pageStep = scrollbar.singleStep(), scrollbar.pageStep()
        opt.upsideDown = False
        self._opt = opt
        self._style = scrollbar.style()
        self.sub_line = self._rect(QStyle.SC_ScrollBarSubLine)
        self.add_line = self._rect(QStyle.SC_ScrollBarAddLine)
        self.slider = self._rect(QStyle.SC_ScrollBarSlider)
        self.groove = self._rect(QStyle.SC_ScrollBarGroove)

    def _rect(self, sub_control):
        return self._style.subControlRect(QStyle.CC_ScrollBar, self._opt, sub_control, self.scrollbar)

    def hit(self, point):
        return self._style.hitTestComplexControl(QStyle.CC_ScrollBar, self._opt, point, self.scrollbar)

    def slider_point(self, where):
        """핸들 위의 점: 'start'(맨 앞 끝: 세로면 맨 위, 가로면 맨 왼쪽)·'center'·'end'(맨 뒤 끝). 끝은 가장자리에서 EDGE_INSET 안쪽."""
        s = self.slider
        if self.horizontal:
            x = {"start": s.left() + EDGE_INSET, "center": s.center().x(), "end": s.right() - EDGE_INSET}[where]
            return QPoint(x, s.center().y())
        y = {"start": s.top() + EDGE_INSET, "center": s.center().y(), "end": s.bottom() - EDGE_INSET}[where]
        return QPoint(s.center().x(), y)

    def describe(self):
        def r(q):
            return f"{q.x()}..{q.x() + q.width() - 1}" if self.horizontal else f"{q.y()}..{q.y() + q.height() - 1}"

        return (f"값 {self.scrollbar.value()}/{self.scrollbar.maximum()} — 앞 버튼 {r(self.sub_line)}, "
                f"핸들 {r(self.slider)}, 뒤 버튼 {r(self.add_line)}, 홈 {r(self.groove)}")


def assert_handle_free_at_start(scrollbar):
    """값이 최솟값일 때: 핸들이 앞(위·왼쪽) 버튼과 겹치지 않고, 핸들의 앞쪽 끝·가운데를 누르면 핸들이 잡힘."""
    scrollbar.setValue(scrollbar.minimum())
    z = Zones(scrollbar)
    assert scrollbar.maximum() > scrollbar.minimum(), "스크롤바가 움직일 수 있어야 시험이 됨"
    small = (z.slider.width() if z.horizontal else z.slider.height()) * 2 < (z.groove.width() if z.horizontal else z.groove.height())
    assert small, f"핸들이 작아야 시험이 됨 — {z.describe()}"
    assert not overlaps(z.slider, z.sub_line), f"핸들이 앞 버튼과 겹침 — {z.describe()}"
    for where in ("start", "center"):
        point = z.slider_point(where)
        assert z.hit(point) == QStyle.SC_ScrollBarSlider, (
            f"핸들 {where} {point.x()},{point.y()}를 눌렀는데 핸들이 아님({z.hit(point)}) — {z.describe()}")


def assert_handle_free_at_end(scrollbar):
    """값이 최댓값일 때: 핸들이 뒤(아래·오른쪽) 버튼과 겹치지 않고, 핸들의 뒤쪽 끝·가운데를 누르면 핸들이 잡힘."""
    scrollbar.setValue(scrollbar.maximum())
    z = Zones(scrollbar)
    assert scrollbar.maximum() > scrollbar.minimum(), "스크롤바가 움직일 수 있어야 시험이 됨"
    assert not overlaps(z.slider, z.add_line), f"핸들이 뒤 버튼과 겹침 — {z.describe()}"
    for where in ("end", "center"):
        point = z.slider_point(where)
        assert z.hit(point) == QStyle.SC_ScrollBarSlider, (
            f"핸들 {where} {point.x()},{point.y()}를 눌렀는데 핸들이 아님({z.hit(point)}) — {z.describe()}")


def sidebar_scrollbar(window):
    """영상이 많아 세로로 스크롤되는 사이드바 목록의 세로 스크롤바 (핸들이 작음)."""
    for i in range(200):
        window.sidebar.addItem(f"item {i}")
    QApplication.processEvents()
    return window.sidebar.verticalScrollBar()


def window_horizontal_scrollbar(window):
    """메인 창 아래에 놓인 가로 스크롤바 (핸들이 작음)."""
    scrollbar = QScrollBar(Qt.Horizontal, window)
    scrollbar.setRange(0, 1000)
    scrollbar.setPageStep(100)
    scrollbar.resize(300, 15)
    scrollbar.show()
    QApplication.processEvents()
    return scrollbar


def test_sidebar_vertical_handle_is_free_at_top(window):
    assert_handle_free_at_start(sidebar_scrollbar(window))


def test_sidebar_vertical_handle_is_free_at_bottom(window):
    assert_handle_free_at_end(sidebar_scrollbar(window))


def test_horizontal_handle_is_free_at_left(window):
    assert_handle_free_at_start(window_horizontal_scrollbar(window))


def test_horizontal_handle_is_free_at_right(window):
    assert_handle_free_at_end(window_horizontal_scrollbar(window))


def test_volume_bar_handle_is_free_at_left(window):
    """영상 위 오버레이의 볼륨 막대(overlayVolume — 가로 QScrollBar): 자기 스타일시트에는 버튼 규칙이 없어 창 것이 내려옴."""
    window.overlayVolume.ensurePolished()
    assert_handle_free_at_start(window.overlayVolume)


def test_volume_bar_handle_is_free_at_right(window):
    window.overlayVolume.ensurePolished()
    assert_handle_free_at_end(window.overlayVolume)
