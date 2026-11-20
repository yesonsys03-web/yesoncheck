"""사이드바 줄의 A·B 단추 (사용자 요청 2026-11-20 — 와이프를 편하게): Mov·Seq·All 목록 줄에 마우스를 올리면 그 줄 오른쪽 끝에
[A][B]가 뜨고, A는 그 줄을 누른 것과 같게, B는 B로 열고 와이프까지 켬(player_playback.open_b_and_wipe).

목록마다 뷰포트의 자식으로 단추 묶음 하나(AbButtons)를 두고 커서 아래 줄로 옮김 — 줄마다 단추를 두거나 줄 그리기(델리게이트)에
그려 넣지 않음(수백 줄에 무겁고, 테이크 색·고른 줄·썸네일 모양을 건드림). 자리는 뷰포트의 마우스 움직임(이벤트 필터)과, 커서는
그대로인데 줄이 움직이는 때(스크롤·폭 바꿈·목록 내용 바뀜·탭 바꿈 — 0ms 뒤 지금 커서 자리로 다시)에 맞춤. 목록을 떠나거나 창이
비활성이 되면 숨김. 단추는 포커스를 가져가지 않음(목록의 ↑↓·단축키 그대로). 이벤트 필터는 PyQt5 가상 함수라 본문 예외를
처음 한 번만 크게 알리고 그 뒤로는 아무것도 안 함(sidebar_sorting._ResizeWatcher와 같은 모양).

색은 테마마다 인라인 시트(테마 시트 main_window_styles는 해시로 고정 — 건드리지 않음): A 파랑·B 금색(강조 주황 #ff9900보다
노란 쪽, 글자는 어두운 색) — 글자와 바탕의 명암 대비 4.5:1 이상(시험). 묶음 밑에는 줄의 바탕색을 깔아 긴 이름의 끝이 비치지 않게.
"""

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, Qt, QTimer
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QHBoxLayout, QToolButton, QWidget

from yesoncheck import error_window, ui_text

AB_LOG_PREFIX = "[A·B 단추]"

# 단추 색 — 테마 → A/B → 바탕·마우스를 올렸을 때·눌렀을 때·글자, 꺼졌을 때(선택 재생 중)
AB_COLORS = {
    "dark": {
        "A": {"bg": "#2563eb", "hover": "#1d4ed8", "pressed": "#1e40af", "fg": "#ffffff"},
        "B": {"bg": "#f2c230", "hover": "#f7d154", "pressed": "#d9a91f", "fg": "#1a1a1a"},
        "disabled": {"bg": "#4a4a4a", "fg": "#9a9a9a"},
    },
    "light": {
        "A": {"bg": "#1d4ed8", "hover": "#1e40af", "pressed": "#1e3a8a", "fg": "#ffffff"},
        "B": {"bg": "#e0a800", "hover": "#f2c230", "pressed": "#c99700", "fg": "#1a1a1a"},
        "disabled": {"bg": "#d0d0d0", "fg": "#6b6b6b"},
    },
}

# 목록 줄의 바탕 — main_window_styles의 QListWidget 규칙(바탕)·::item:selected(고른 줄)와 짝 (시험이 시트 글자와 견줌)
ROW_BG = {
    "dark": {"normal": "#232323", "selected": "#444"},
    "light": {"normal": "#ffffff", "selected": "#e9ecef"},
}

BUTTON_WIDTH = 22
BUTTON_HEIGHT = 18  # 줄이 이보다 낮으면 줄에 맞춤
RIGHT_INSET = 3  # 줄 오른쪽 끝에서 띄우는 틈 (px)

# 필터가 보는 이벤트 (그 밖은 곧바로 흘려보냄)
_WATCHED_EVENTS = frozenset((QEvent.MouseMove, QEvent.Leave, QEvent.Hide, QEvent.Resize, QEvent.WindowDeactivate))


def ab_buttons_style(theme: str, row_background: str) -> str:
    """묶음(바탕 = 줄의 바탕)과 A·B 단추의 인라인 시트. 모르는 테마는 KeyError."""
    colors = AB_COLORS[theme]
    disabled = colors["disabled"]
    rules = [f"QWidget#sidebarAb {{ background: {row_background}; }}"]
    for side, name in (("A", "sidebarAbA"), ("B", "sidebarAbB")):
        c = colors[side]
        rules += [
            f"QToolButton#{name} {{ background: {c['bg']}; color: {c['fg']}; border: none; border-radius: 4px;"
            f" font-weight: bold; padding: 0px; }}",
            f"QToolButton#{name}:hover {{ background: {c['hover']}; }}",
            f"QToolButton#{name}:pressed {{ background: {c['pressed']}; }}",
            f"QToolButton#{name}:disabled {{ background: {disabled['bg']}; color: {disabled['fg']}; }}",
        ]
    return "\n".join(rules)


class AbButtons(QWidget):
    """목록 뷰포트 위에 뜨는 [A][B] 묶음 — 자리·색만 (누르면 하는 일은 SidebarAbButtonsMixin)."""

    def __init__(self, viewport):
        super().__init__(viewport)
        self.setObjectName("sidebarAb")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 시트의 바탕(줄의 바탕)을 칠함
        self.setFocusPolicy(Qt.NoFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(2)
        self.button_a = self._add_button(layout, "A", "sidebarAbA")
        self.button_b = self._add_button(layout, "B", "sidebarAbB")
        self._style_key = None
        self.hide()

    def _add_button(self, layout, text, name):
        button = QToolButton(self)
        button.setObjectName(name)
        button.setText(text)
        button.setFocusPolicy(Qt.NoFocus)  # 목록의 포커스(↑↓·단축키)를 가져가지 않게
        button.setAutoRaise(False)
        layout.addWidget(button)
        return button

    def restyle(self, theme: str, selected: bool):
        """테마와 그 줄이 고른 줄인지에 맞춰 시트를 다시 넣음 (같으면 아무것도 안 함 — 마우스 움직임마다 부름)."""
        key = (theme, selected)
        if key == self._style_key:
            return
        self._style_key = key
        self.setStyleSheet(ab_buttons_style(theme, ROW_BG[theme]["selected" if selected else "normal"]))

    def place(self, row):
        """row(뷰포트 좌표의 줄 사각형) 오른쪽 끝·세로 가운데에 놓고 보임."""
        height = max(12, min(BUTTON_HEIGHT, row.height() - 4))
        for button in (self.button_a, self.button_b):
            button.setFixedSize(BUTTON_WIDTH, height)
        margins = self.layout().contentsMargins()
        width = 2 * BUTTON_WIDTH + self.layout().spacing() + margins.left() + margins.right()
        box_height = height + margins.top() + margins.bottom()
        self.setGeometry(row.right() + 1 - RIGHT_INSET - width, row.top() + (row.height() - box_height) // 2, width, box_height)
        self.raise_()
        self.show()


class _AbHoverFilter(QObject):
    """목록 뷰포트·창의 이벤트를 플레이어의 _ab_event에 넘기는 필터 (이벤트는 그대로 흘려보냄). PyQt5 가상 함수에서 예외가 빠져나가면
    프로세스가 끝나므로(qFatal) 본문을 감싸 처음 한 번만 크게 알리고 그 뒤로는 부르지 않음."""

    def __init__(self, on_event, parent):
        super().__init__(parent)
        self._on_event = on_event
        self._failed = False

    def eventFilter(self, watched, event):
        if self._failed:
            return False
        try:
            self._on_event(watched, event)
        except BaseException:
            self._failed = True
            error_window.report_from_handler(AB_LOG_PREFIX, "A·B 단추를 목록 줄에 맞추다 실패했습니다 — 그 뒤로는 단추를 옮기지 않습니다")
        return False


class SidebarAbButtonsMixin:
    """VideoPlayer의 사이드바 A·B 단추 — 목록마다 묶음 하나(self._sidebar_ab[목록])."""

    def _init_sidebar_ab_buttons(self):
        """(initUI — 세 목록·탭을 만든 뒤) 목록마다 묶음·필터·다시 맞춤 타이머를 만들고 신호에 이음."""
        self._sidebar_ab = {}
        self._sidebar_ab_timers = {}
        self._sidebar_ab_viewports = {}  # 뷰포트 → 목록 (필터가 Qt를 부르지 않고 찾게 — 그림 이벤트마다 불림)
        self._sidebar_ab_filter = _AbHoverFilter(self._ab_event, self)
        for widget in (self.sidebar, self.seq_sidebar, self.all_sidebar):
            box = AbButtons(widget.viewport())
            self._sidebar_ab[widget] = box
            viewport = widget.viewport()
            self._sidebar_ab_viewports[viewport] = widget
            viewport.setMouseTracking(True)  # 단추 없이 움직여도 MouseMove가 오게
            viewport.installEventFilter(self._sidebar_ab_filter)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(lambda w=widget: self._place_ab_buttons(w))
            self._sidebar_ab_timers[widget] = timer
            widget.verticalScrollBar().valueChanged.connect(lambda _value, w=widget: self._schedule_ab_refresh(w))
            model = widget.model()
            for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
                signal.connect(lambda *_args, w=widget: self._schedule_ab_refresh(w))
        self.installEventFilter(self._sidebar_ab_filter)  # 창의 WindowDeactivate
        self.sidebar_tabs.currentChanged.connect(self._on_ab_tab_changed)
        self.retranslate_sidebar_ab_buttons()

    def _ab_event(self, watched, event):
        kind = event.type()
        if kind not in _WATCHED_EVENTS:
            return
        if watched is self:
            if kind == QEvent.WindowDeactivate:
                self._hide_ab_buttons()
            return
        widget = self._sidebar_ab_viewports.get(watched)
        if widget is None:
            return
        if kind == QEvent.MouseMove:
            self._place_ab_buttons(widget, event.pos())
        elif kind in (QEvent.Leave, QEvent.Hide):
            self._sidebar_ab[widget].hide()
        elif kind == QEvent.Resize:
            self._schedule_ab_refresh(widget)

    def _schedule_ab_refresh(self, widget):
        """줄이 움직인 뒤(줄 자리가 정해진 다음 — 0ms) 지금 커서 자리로 다시 맞춤."""
        timer = self._sidebar_ab_timers[widget]
        if sip.isdeleted(timer):
            return  # 창이 지워지는 중(목록이 지워지며 신호를 냄 — 타이머가 먼저 지워짐) — 맞출 단추도 없음
        timer.start()

    def _on_ab_tab_changed(self, _index):
        self._hide_ab_buttons()
        current = self.sidebar_tabs.currentWidget()
        if current in self._sidebar_ab:
            self._schedule_ab_refresh(current)

    def _hide_ab_buttons(self):
        for box in self._sidebar_ab.values():
            box.hide()

    def _place_ab_buttons(self, widget, pos=None):
        """pos(뷰포트 좌표 — None이면 지금 커서 자리) 아래 줄의 오른쪽 끝에 묶음을 놓거나, 줄이 없으면 숨김."""
        box = self._sidebar_ab[widget]
        viewport = widget.viewport()
        if pos is None:
            pos = viewport.mapFromGlobal(QCursor.pos())
        item = widget.itemAt(pos) if widget.isVisible() and viewport.rect().contains(pos) else None
        if item is None:
            box.hide()
            return
        box.restyle(self.current_theme, item.isSelected())
        box.place(widget.visualItemRect(item))

    def _apply_sidebar_ab_theme(self):
        """(테마를 바꿀 때) 보이는 묶음의 색을 새 테마로 — 숨은 묶음은 다음에 뜰 때 맞춤."""
        for widget, box in self._sidebar_ab.items():
            if box.isVisible():
                self._place_ab_buttons(widget)

    def retranslate_sidebar_ab_buttons(self):
        """툴팁을 지금 언어로 (player_language.RETRANSLATORS)."""
        for box in self._sidebar_ab.values():
            box.button_a.setToolTip(ui_text.text("side_ab.open_a"))
            box.button_b.setToolTip(ui_text.text("side_ab.open_b"))
