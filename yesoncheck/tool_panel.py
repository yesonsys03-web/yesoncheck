"""도구 패널 — 뷰어 오른쪽 칸 (2026-11-16 UI 개편): 머리(이름 + 닫기) 아래에 쪽 하나.

    ┌ 수정 사항 주석 ──────── ✕ ┐
    │ (쪽: 주석 또는 OCR)        │

- 한 번에 한 쪽만 보인다(`show_page(키)`). 쪽은 `add_page(키, 제목의 글자 표 키, 위젯)`으로 넣고, 보이지 않는 쪽의
  위젯·상태는 그대로 살아 있다(주석 모드·ROI·입력값이 패널을 닫거나 쪽을 바꾼다고 사라지지 않게).
- 닫기 단추는 `closeRequested`만 낸다 — 칸을 숨기고 뷰어에 자리를 돌려주는 일은 받는 쪽(`player_tools`)이 한다.
- 원하는 너비는 `PANEL_WIDTH`, 최소 너비는 가장 넓은 쪽의 최소 너비(보이지 않는 쪽도 — 쪽을 바꿔도 칸이 튀지 않게).
- 색은 두 테마 시트의 `QWidget#toolPanel …` 규칙, 닫기 아이콘은 `apply_theme`이 테마 색으로 다시 그림.

이 모듈은 플레이어를 모른다.
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from yesoncheck import transport_icons, ui_text

PANEL_WIDTH = 340  # 패널을 처음 열 때의 폭
HEADER_HEIGHT = 30
CLOSE_SIZE = 24
ICON_SIZE = 14
ICON_COLORS = {"dark": "#d0d0d0", "light": "#333333"}
_TEXT_KEY = "ycTextKey"  # 머리글 라벨이 기억하는 글자 표 키 (언어가 바뀌면 다시 읽음)


def section_title(text_key):
    """쪽 안의 묶음 머리글(예: OCR 쪽의 'ROI 설정'). 글은 글자 표에서 — 모르는 키는 KeyError(만들기 전에)."""
    text = ui_text.text(text_key)
    label = QLabel(text)
    label.setObjectName("toolPanelSection")
    label.setProperty(_TEXT_KEY, text_key)
    return label


class ToolPanel(QWidget):
    """도구 패널 위젯 (모듈 설명)."""

    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 테마 시트의 QWidget#toolPanel 바탕·테두리를 칠하게
        self._title_keys = {}  # 쪽의 키 → 제목의 글자 표 키 (넣은 차례)
        self._pages = {}  # 쪽의 키 → 위젯
        self._theme = "dark"

        self._title = QLabel()
        self._title.setObjectName("toolPanelTitle")
        self._title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # 긴 제목이 칸의 최소 너비를 늘리지 않게
        self._close = QToolButton()
        self._close.setObjectName("toolPanelClose")
        self._close.setFixedSize(CLOSE_SIZE, CLOSE_SIZE)
        self._close.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._close.setAutoRaise(True)
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.clicked.connect(self.closeRequested)

        header = QWidget()
        header.setObjectName("toolPanelHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 4, 0)
        header_layout.setSpacing(4)
        header_layout.addWidget(self._title, 1)
        header_layout.addWidget(self._close)

        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 0, 0, 0)  # 왼쪽 1px — 시트의 테두리 자리
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self._stack, 1)

        self.apply_theme(self._theme)
        self.retranslate()

    def add_page(self, key, title_key, widget):
        """쪽을 넣음. 같은 키가 이미 있으면 ValueError, 제목 키가 글자 표에 없으면 KeyError — 둘 다 넣기 전에."""
        if key in self._pages:
            raise ValueError(f"이미 있는 쪽: {key!r}")
        ui_text.text(title_key)
        self._title_keys[key] = title_key
        self._pages[key] = widget
        self._stack.addWidget(widget)
        self._show_title()
        self.updateGeometry()

    def keys(self):
        return tuple(self._pages)

    def current(self):
        """보이는 쪽의 키 — 쪽이 없으면 None."""
        shown = self._stack.currentWidget()
        for key, widget in self._pages.items():
            if widget is shown:
                return key
        return None

    def show_page(self, key):
        """그 쪽을 보임. 모르는 키는 KeyError — 바꾸기 전에."""
        widget = self._pages[key]
        self._stack.setCurrentWidget(widget)
        self._show_title()

    def _show_title(self):
        key = self.current()
        self._title.setText(ui_text.text(self._title_keys[key]) if key is not None else "")

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(max(PANEL_WIDTH, self.minimumSizeHint().width()), base.height())

    def apply_theme(self, theme):
        """테마('dark'·'light')의 색으로 닫기 아이콘을 다시 그림. 모르는 테마는 KeyError — 바꾸기 전에."""
        color = QColor(ICON_COLORS[theme])
        self._theme = theme
        self._close.setIcon(transport_icons.icon("close", color))

    def retranslate(self):
        """글자 표에서 제목·툴팁·묶음 머리글을 다시 읽음 (언어가 바뀐 뒤)."""
        self._show_title()
        self._close.setToolTip(ui_text.text("panel.close.tip"))
        for label in self.findChildren(QLabel, "toolPanelSection"):
            text_key = label.property(_TEXT_KEY)
            if text_key:
                label.setText(ui_text.text(text_key))
