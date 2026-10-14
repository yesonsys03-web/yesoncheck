"""메인 창을 작게 줄일 수 있게 하는 레이아웃 도구.

예전에는 가운데 열(세로로 쌓은 버튼들)의 최소 높이와 정보 줄 라벨의 고정 너비 때문에 메인 창의 최소 크기가
약 1142×845(논리 px)였다 — Windows 150% 배율에서는 1080p 화면보다 커서 창을 줄일 수 없었음.

- ElidedLabel: 한 줄 라벨. 레이아웃에 알리는 최소 너비는 작고, 좁아지면 글자를 …로 줄여 그림.
  자리가 충분하면 QLabel 그대로 그려서 예전과 똑같이 보임. text()는 항상 전체 글자.
- InfoRowLayout: 정보 줄 배치. 자리가 있으면 QHBoxLayout + 빈칸과 같은 배치, 모자라면 정해진 순서로 줄임.
- VerticalScrollArea: 세로로만 스크롤 — 안의 내용이 길어도 창의 최소 높이를 묶지 않음.
- startup_geometry: 처음 창 크기·위치 (예전처럼 1080×720 이상, 레이아웃이 원하는 크기까지, 화면 작업 영역 안으로).
"""

from PyQt5.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QFrame, QLabel, QLayout, QScrollArea, QStyle, QStyleOption

# 예전 처음 창: setGeometry(100, 100, 1080, 720)
DEFAULT_WINDOW_SIZE = QSize(1080, 720)
DEFAULT_WINDOW_POS = QPoint(100, 100)
# 처음 창을 화면 작업 영역에 맞출 때 남겨 둘 창 테두리·제목 표시줄 몫. 창을 띄우기 전이라 실제 크기를 모름
# (Windows 제목 표시줄 약 31px + 크기 조절 테두리, macOS 제목 표시줄 28px).
STARTUP_FRAME_MARGINS = QMargins(8, 32, 8, 8)


def startup_geometry(natural, minimum, available):
    """처음 창의 geometry (테두리 제외 — setGeometry에 넘기는 값).

    natural: 레이아웃이 원하는 크기(sizeHint), minimum: 최소 크기(minimumSizeHint), available: 화면 작업 영역.
    크기 = max(1080×720, natural)을 작업 영역(테두리 몫 제외)에 맞게 줄이되 minimum보다 작게는 안 함.
    위치 = 예전처럼 (100, 100) — 창이 작업 영역을 넘으면 안쪽으로 옮김.
    """
    usable = available.marginsRemoved(STARTUP_FRAME_MARGINS)
    size = natural.expandedTo(DEFAULT_WINDOW_SIZE).boundedTo(usable.size()).expandedTo(minimum)
    x = max(usable.left(), min(DEFAULT_WINDOW_POS.x(), usable.right() + 1 - size.width()))
    y = max(usable.top(), min(DEFAULT_WINDOW_POS.y(), usable.bottom() + 1 - size.height()))
    return QRect(QPoint(x, y), size)


class ElidedLabel(QLabel):
    """한 줄 라벨: 레이아웃에 알리는 최소 너비는 min_width로 작게, 그보다 좁아지면 글자를 …로 줄여 그림.

    hint_width: 원하는 너비를 글자와 상관없이 고정 (예전 고정 너비 — 숫자가 바뀌어도 너비가 흔들리지 않게).
        None이면 QLabel처럼 글자 너비.
    fit_text: 이 글자가 다 들어가는 너비까지는 글자를 줄이지 않고 빈 공간만 줄일 수 있음 (InfoRowLayout이 먼저 줄임).
    shrinks_first: InfoRowLayout에서 빈 공간 다음으로 먼저 줄어듦 (긴 파일 이름이 숫자·시간보다 먼저).
    full_text_tooltip: 툴팁에 전체 글자 (줄여 그려질 때 전체를 볼 수 있게).
    """

    def __init__(self, elide_mode, min_width, hint_width=None, fit_text=None, shrinks_first=False,
                 full_text_tooltip=False, parent=None):
        super().__init__(parent)
        self._elide_mode = elide_mode
        self._min_width = min_width
        self._hint_width = hint_width
        self._fit_text = fit_text
        self.shrinks_first = shrinks_first
        self._full_text_tooltip = full_text_tooltip

    def sizeHint(self):
        width = super().sizeHint().width() if self._hint_width is None else self._hint_width
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(self._min_width, self.sizeHint().width()), super().minimumSizeHint().height())

    def comfortable_width(self):
        """글자를 줄이지 않는 가장 작은 너비 (fit_text가 없으면 원하는 너비 그대로)."""
        if self._fit_text is None:
            return self.sizeHint().width()
        return max(self.minimumSizeHint().width(), min(self._label_width(self._fit_text), self.sizeHint().width()))

    def _label_width(self, text):
        """QLabel이 text를 다 보여 주는 너비 (QLabel의 sizeHint와 같은 계산: 글자 + 안쪽 여백·테두리·들여쓰기)."""
        flags = int(self.alignment()) & ~int(Qt.AlignVCenter | Qt.AlignHCenter)
        metrics = self.fontMetrics()
        box = QRect(0, 0, 2000, 2000)
        extra = super().sizeHint().width() - metrics.boundingRect(box, flags, self.text()).width()
        return metrics.boundingRect(box, flags, text).width() + extra

    def setText(self, text):
        super().setText(text)
        if self._full_text_tooltip:
            self.setToolTip(text)

    def _text_rect(self):
        """QLabel이 글자를 그리는 영역 (QLabelPrivate::documentRect와 같은 계산)."""
        rect = self.contentsRect()
        margin = self.margin()
        rect.adjust(margin, margin, -margin, -margin)
        indent = self.indent()
        if indent < 0 and self.frameWidth():
            indent = self.fontMetrics().horizontalAdvance("x") // 2 - margin
        if indent > 0:
            align = QStyle.visualAlignment(self.layoutDirection(), self.alignment())
            if align & Qt.AlignLeft:
                rect.setLeft(rect.left() + indent)
            if align & Qt.AlignRight:
                rect.setRight(rect.right() - indent)
        return rect

    def displayed_text(self):
        """지금 너비에서 실제로 그려지는 글자 (다 들어가면 전체, 아니면 …로 줄인 것)."""
        return self.fontMetrics().elidedText(self.text(), self._elide_mode, self._text_rect().width())

    def paintEvent(self, event):
        shown = self.displayed_text()
        if shown == self.text():
            super().paintEvent(event)  # 다 들어감: QLabel 그대로 (예전과 똑같이)
            return
        painter = QPainter(self)
        self.drawFrame(painter)
        option = QStyleOption()
        option.initFrom(self)
        align = QStyle.visualAlignment(self.layoutDirection(), self.alignment())
        self.style().drawItemText(painter, self._text_rect(), int(align), option.palette, self.isEnabled(), shown,
                                  self.foregroundRole())


class VerticalScrollArea(QScrollArea):
    """세로로만 스크롤하는 영역 (가로 스크롤 없음, 테두리 없음, 배경은 창 스타일시트 그대로).

    최소 높이는 스크롤바 정도로 작음 — 안의 내용이 아무리 길어도 창의 최소 높이를 묶지 않음.
    최소 너비는 내용의 최소 너비 + 세로 스크롤바 — 스크롤바가 생겨도 내용이 오른쪽에서 잘리지 않음.
    원하는 크기(sizeHint)는 내용 전체 — QScrollArea 기본값은 글자 높이의 24배로 잘라서, 그걸 쓰면 처음 창이
    작아져 화면이 충분한데도 스크롤이 생김.
    """

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(content)

    def _content_minimum_width(self):
        content = self.widget()
        return content.minimumSizeHint().expandedTo(content.minimumSize()).width()

    def minimumSizeHint(self):
        frame = 2 * self.frameWidth()
        width = self._content_minimum_width() + self.verticalScrollBar().sizeHint().width() + frame
        return QSize(width, super().minimumSizeHint().height())

    def sizeHint(self):
        frame = 2 * self.frameWidth()
        content = self.widget()
        hint = content.sizeHint().expandedTo(content.minimumSize())
        return QSize(max(hint.width() + frame, self.minimumSizeHint().width()), hint.height() + frame)


def _take_equally(widths, floors, indices, excess):
    """indices 항목의 너비에서 excess를 똑같이 뺌 (각 항목은 floors 밑으로 안 감). 다 못 빼면 남은 양을 돌려줌."""
    active = [i for i in indices if widths[i] > floors[i]]
    while excess > 0 and active:
        share = -(-excess // len(active))  # 올림
        for i in list(active):
            take = min(share, widths[i] - floors[i], excess)
            widths[i] -= take
            excess -= take
            if widths[i] <= floors[i]:
                active.remove(i)
            if excess == 0:
                break
    return excess


class InfoRowLayout(QLayout):
    """한 줄 배치: 왼쪽부터 차례로 놓고, 오른쪽 정렬(setAlignment(widget, Qt.AlignRight)) 항목은 오른쪽 끝에.
    자리가 남으면 그 사이가 빈칸 — 예전 QHBoxLayout(… addStretch … 시간 라벨)과 같은 배치.

    자리가 모자라면 이 순서로 줄임 (QHBoxLayout은 모든 항목에서 똑같이 빼서, 글자가 꽉 찬 시간·파일 이름 라벨이
    빈 공간이 많은 숫자 라벨과 같이 줄어 글자가 잘림. stretch는 전체 너비를 비율로 나눠 원하는 너비를 무시함):
      1) 빈 공간: 원하는 너비 − 글자가 다 들어가는 너비 (ElidedLabel.comfortable_width — 숫자 라벨)
      2) 먼저 줄일 항목(ElidedLabel.shrinks_first — 파일 이름)을 최소 너비까지
      3) 모든 항목을 똑같이 최소 너비까지
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Horizontal

    def _visible_items(self):
        return [item for item in self._items if not item.isEmpty()]

    def _total(self, items, sizes):
        margins = self.contentsMargins()
        spacing = max(0, self.spacing()) * max(0, len(items) - 1)
        width = sum(size.width() for size in sizes) + spacing + margins.left() + margins.right()
        height = max((size.height() for size in sizes), default=0) + margins.top() + margins.bottom()
        return QSize(width, height)

    def sizeHint(self):
        items = self._visible_items()
        return self._total(items, [item.sizeHint() for item in items])

    def minimumSize(self):
        items = self._visible_items()
        return self._total(items, [item.minimumSize() for item in items])

    def widths_for(self, available):
        """너비 available(여백·간격 제외)에서 각 항목(보이는 것만, 순서대로)의 너비."""
        items = self._visible_items()
        widths = [item.sizeHint().width() for item in items]
        minimums = [min(item.minimumSize().width(), width) for item, width in zip(items, widths)]
        comfortable = []
        for item, width, minimum in zip(items, widths, minimums):
            widget = item.widget()
            fit = widget.comfortable_width() if hasattr(widget, "comfortable_width") else width
            comfortable.append(max(minimum, min(fit, width)))
        first = [i for i, item in enumerate(items) if getattr(item.widget(), "shrinks_first", False)]
        everyone = list(range(len(items)))
        excess = sum(widths) - available
        for indices, floors in ((everyone, comfortable), (first, minimums), (everyone, minimums)):
            if excess <= 0:
                break
            excess = _take_equally(widths, floors, indices, excess)
        return widths

    def setGeometry(self, rect):
        super().setGeometry(rect)
        items = self._visible_items()
        if not items:
            return
        area = rect.marginsRemoved(self.contentsMargins())
        spacing = max(0, self.spacing())
        widths = self.widths_for(area.width() - spacing * (len(items) - 1))
        right = [i for i, item in enumerate(items) if item.alignment() & Qt.AlignRight]
        x = area.left()
        for i, item in enumerate(items):
            if i in right:
                continue
            item.setGeometry(QRect(x, area.top(), widths[i], area.height()))
            x += widths[i] + spacing
        x = area.right() + 1
        for i in reversed(right):
            x -= widths[i]
            items[i].setGeometry(QRect(x, area.top(), widths[i], area.height()))
            x -= spacing
