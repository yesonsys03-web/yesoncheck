"""메인 창을 작게 줄일 수 있게 하는 레이아웃 도구.

예전에는 가운데 열(세로로 쌓은 버튼들)의 최소 높이와 정보 줄 라벨의 고정 너비 때문에 메인 창의 최소 크기가
약 1142×845(논리 px)였다 — Windows 150% 배율에서는 1080p 화면보다 커서 창을 줄일 수 없었음.

- ElidedLabel: 한 줄 라벨. 최소·원하는 너비를 글꼴과 스타일시트 여백으로 재고, 좁아지면 글자를 …로 줄여 그림.
  다 들어가면 QLabel 그대로 그려서 예전과 똑같이 보임. text()는 항상 전체 글자.
- InfoRowLayout: 정보 줄 배치. 자리가 있으면 예전 QHBoxLayout + 빈칸과 같은 배치, 모자라면 정해진 순서로 줄임.
- VerticalScrollArea: 세로로만 스크롤 — 안의 내용이 길어도 창의 최소 높이를 묶지 않음.
- startup_geometry: 처음 창 크기·위치 (예전처럼 1080×720 이상, 레이아웃이 원하는 크기까지, 화면 작업 영역 안으로).
"""

import math

from PyQt5.QtCore import QEvent, QMargins, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QFontMetricsF, QPainter
from PyQt5.QtWidgets import QFrame, QLabel, QLayout, QScrollArea, QStyle, QStyleOption, QToolTip

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


# 라벨이 좁아 글자가 안쪽 여백(padding)까지 써야 할 때 양쪽에 남겨 둘 너비: 정보 줄 라벨의 테두리(1px) + 1px
TIGHT_INSET = 2
# 글자 간격(advance)이 이만큼까지만 넘치면 실제 잉크로 다시 확인 (끝 글자의 오른쪽 여유는 몇 px 안 됨)
_TRAILING_SLACK = 4

# 글꼴·스타일시트(테두리·안쪽 여백)가 바뀌면 다시 재야 하는 이벤트
_METRICS_EVENTS = (QEvent.FontChange, QEvent.StyleChange, QEvent.ContentsRectChange, QEvent.LayoutDirectionChange)


_DIGITS = "0123456789"


class ElidedLabel(QLabel):
    """한 줄(왼쪽 정렬) 라벨: 너비는 글꼴과 스타일시트 여백으로 재고(플랫폼·테마마다 글꼴이 다름), 좁으면 줄여 그림.

    그리기 (QLabel처럼, 잉크 기준 — 끝의 글자 간격 때문에 1px 넘친다고 줄이지 않음):
      1) 글자가 QLabel의 글자 영역(테두리·안쪽 여백·들여쓰기 안)에 들어가면 QLabel 그대로 (예전과 똑같이)
      2) 안 들어가도 테두리 안(양쪽 TIGHT_INSET)에 들어가면 글자를 필요한 만큼만 왼쪽으로 옮겨 전부 그림
      3) 그래도 넘치면 테두리 안에서 …로 줄임 (전체 글자는 툴팁)

    최소(줄인) 너비 floor_width()는 따로 잰 글자 너비가 아니라 위의 그리기 방법 그대로 찾은 값 — 그 너비에서 지켜야
    할 글자를 실제로 그리는 가장 작은 너비 (이분 탐색, 글꼴·스타일이 바뀔 때만). 글자 안의 '0'은 '이 글꼴에서 가장
    넓은 숫자'로 바꿔 재므로 어떤 숫자가 와도 들어감:
    keep_text: 지켜야 할 글자의 본보기 (예: 'Total: 00000 (000F 00f)').
    keep_prefix: keep_text를 줄여 그려도 남아야 하는 앞부분 (None이면 keep_text 전부, ""이면 '…'라도 보이면 됨).
    keep_ends: (앞, 뒤) — 지금 글자를 가운데 줄여도 앞·뒤로 이만큼 글자가 남는 너비 (파일 이름: 'A: H….mov').
    셋 다 없으면 테두리만.

    hint_width: 원하는 너비 (예전 고정 너비 — 숫자가 바뀌어도 흔들리지 않게). fit_text가 더 넓으면 그 너비.
        None이면 QLabel처럼 지금 글자의 너비.
    hint_text: hint_width 대신 — 이 글자에 대한 QLabel의 원하는 너비로 고정 (모양이 늘 같은 글자, 예: 시간
        '00:00:00.000 / 00:00:00.000' — 예전과 같은 너비이면서 매 프레임 글자 너비를 다시 재지 않음).
    fit_text: 이 글자를 QLabel 그대로 그리는 너비까지는 빈 공간만 줄임 (InfoRowLayout이 가장 먼저 줄이는 몫).
    shrink_order: InfoRowLayout에서 빈 공간 다음으로 floor_width까지 줄이는 순서 (작을수록 먼저).
    collapse_order: 정하면 모든 라벨이 floor_width가 된 뒤 이 순서에 너비 0까지 (창이 최소 너비 근처일 때만 — 그래서
        창의 최소 너비가 이 라벨만큼 작아짐). None이면 floor_width가 최소 너비.
    full_text_tooltip: 툴팁에 언제나 전체 글자 (파일 이름). 아니면 줄여 그려질 때만 전체 글자를 툴팁으로.
    """

    def __init__(self, elide_mode, keep_text=None, keep_prefix=None, keep_ends=None, hint_width=None,
                 hint_text=None, fit_text=None, shrink_order=0, collapse_order=None, full_text_tooltip=False,
                 parent=None):
        super().__init__(parent)
        self._elide_mode = elide_mode
        self._keep_text = keep_text
        self._keep_prefix = keep_prefix
        self._keep_ends = keep_ends
        self._hint_width = hint_width
        self._hint_text = hint_text
        self._fit_text = fit_text
        self.shrink_order = shrink_order
        self._collapse_order = collapse_order
        self._full_text_tooltip = full_text_tooltip
        # 글꼴·여백이 바뀔 때만 다시 잼 (재생 중 매 프레임 바뀌는 글자 때문에 크기를 자주 물어봄):
        # (왼쪽 여백, 오른쪽 여백, 최소, 빈 공간을 뺀 너비, 고정 원하는 너비, 한 줄 높이, QFontMetricsF)
        self._widths = None
        self._shown = None  # (글자, 라벨 너비, (그릴 글자, 글자 왼쪽 x, QLabel 그대로 그려도 되는지))
        self._char_widths = {}  # 글자 하나씩의 너비 (글꼴별) — 다 들어가는지 빨리 어림
        self._ends_floor = None  # keep_ends: (글자, 최소 너비) — 지금 글자에 따라 다름

    # --- 너비 재기 (글꼴·여백이 바뀔 때만) ---
    def changeEvent(self, event):
        if event.type() in _METRICS_EVENTS:
            self._widths = None
            self._shown = None
            self._char_widths = {}
            self._ends_floor = None
        super().changeEvent(event)

    def text_insets(self):
        """(왼쪽, 오른쪽): 라벨 가장자리에서 QLabel이 글자를 그리는 영역까지 — 테두리·안쪽 여백·margin과,
        테두리가 있을 때 QLabel이 넣는 들여쓰기 (QLabelPrivate::documentRect와 같은 계산)."""
        return self._metrics()[:2]

    def _metrics(self):
        if self._widths is None:
            self.ensurePolished()  # 스타일시트의 테두리·안쪽 여백·글꼴이 적용된 뒤에 재야 함
            margins = self.contentsMargins()
            margin = self.margin()
            left = margins.left() + margin
            right = margins.right() + margin
            metrics = self.fontMetrics()
            indent = self.indent()
            if indent < 0 and self.frameWidth():
                indent = metrics.horizontalAdvance("x") // 2 - margin
            if indent > 0:
                align = QStyle.visualAlignment(self.layoutDirection(), self.alignment())
                if align & Qt.AlignLeft:
                    left += indent
                if align & Qt.AlignRight:
                    right += indent
            metrics_f = QFontMetricsF(self.font())
            # 아래 너비 찾기는 _compute_placement를 쓰므로 여백·글꼴을 먼저 저장 (최소·고정 너비는 잠시 비움)
            self._widths = (left, right, None, None, None, None, metrics_f)
            widest = max(_DIGITS, key=metrics_f.horizontalAdvance)
            floor = self._keep_floor(widest)
            fit = None
            if self._fit_text is not None:
                probe = self._fit_text.replace("0", widest)
                fit = self._smallest_width(probe, lambda placement: placement[2])  # QLabel 그대로 그려짐
            fixed = None
            if self._hint_width is not None:
                fixed = max(self._hint_width, fit or 0, floor)
            elif self._hint_text is not None:
                fixed = max(self._qlabel_width(self._hint_text, margins, margin), floor)
            # 한 줄 라벨의 높이는 글자와 상관없음 (QLabel은 글자가 바뀔 때마다 다시 잼 — 그 계산을 건너뜀)
            height = super().sizeHint().height()
            self._widths = (left, right, floor, fit, fixed, height, metrics_f)
        return self._widths

    def _keep_floor(self, widest):
        """keep_text/keep_prefix의 최소 너비 (keep_ends는 글자마다 floor_width에서)."""
        if self._keep_text is None:
            return 2 * TIGHT_INSET
        probe = self._keep_text.replace("0", widest)
        if self._keep_prefix is None:
            return self._smallest_width(probe, lambda placement: placement[0] == probe)
        if self._keep_prefix == "":
            return self._smallest_width(probe, lambda placement: placement[0] != "")
        prefix = self._keep_prefix.replace("0", widest)
        return self._smallest_width(probe, lambda placement: placement[0].startswith(prefix))

    def _smallest_width(self, text, wanted):
        """_compute_placement(text, 너비)가 wanted를 만족하는 가장 작은 너비 (너비가 늘면 보이는 글자도 늘어남)."""
        left, right = self._metrics()[:2]
        metrics = self._metrics()[6]
        high = left + right + self._ink_width(metrics, text) + 1  # 이 너비면 QLabel 그대로 다 그려짐
        if not wanted(self._compute_placement(text, high)):
            raise RuntimeError(f"{text!r}을(를) 너비 {high}px로도 원하는 대로 그리지 못함 (여백 {left}·{right})")
        low = 0  # 이 너비로는 안 됨 (또는 0)
        if wanted(self._compute_placement(text, low)):
            return low
        while high - low > 1:
            middle = (low + high) // 2
            if wanted(self._compute_placement(text, middle)):
                high = middle
            else:
                low = middle
        return high

    def floor_width(self):
        """InfoRowLayout이 접기 전까지 줄이는 가장 작은 너비 (지켜야 할 글자를 실제로 그리는 최소 너비)."""
        if self._keep_ends is None:
            return self._metrics()[2]
        text = self.text()
        cached = self._ends_floor
        if cached is not None and cached[0] == text:
            return cached[1]
        if not text:
            floor = 2 * TIGHT_INSET
        else:
            keep_left, keep_right = self._keep_ends

            def wanted(placement):
                shown = placement[0]
                if shown == text:
                    return True
                head, ellipsis, tail = shown.partition("…")
                return bool(ellipsis) and len(head) >= keep_left and len(tail) >= keep_right

            floor = self._smallest_width(text, wanted)
        self._ends_floor = (text, floor)
        return floor

    def _qlabel_width(self, text, margins, margin):
        """QLabel이 text에 대해 내는 원하는 너비 (QLabelPrivate::sizeForWidth의 한 줄 계산 — 들여쓰기는 'x' 한 글자)."""
        metrics = self.fontMetrics()
        extra = 2 * margin
        indent = self.indent()
        if indent < 0 and self.frameWidth():
            indent = metrics.horizontalAdvance("x") - 2 * margin
        if indent > 0 and int(self.alignment()) & int(Qt.AlignLeft | Qt.AlignRight):
            extra += indent
        flags = int(self.alignment()) & ~int(Qt.AlignVCenter | Qt.AlignHCenter)
        text_width = metrics.boundingRect(QRect(0, 0, 2000, 2000), flags, text).width()
        return text_width + extra + margins.left() + margins.right()

    @staticmethod
    def _ink_width(metrics, text):
        """text를 잘림 없이 그리는 데 드는 너비: 글자 간격과 실제 잉크 중 큰 쪽을 소수점까지 재서 올림."""
        if not text:
            return 0
        return math.ceil(max(metrics.horizontalAdvance(text), metrics.tightBoundingRect(text).right()))

    def sizeHint(self):
        _left, _right, floor, _fit, fixed, height, _metrics = self._metrics()
        if fixed is not None:
            return QSize(fixed, height)
        return QSize(max(super().sizeHint().width(), floor), height)

    def minimumSizeHint(self):
        height = self._metrics()[5]
        return QSize(0 if self._collapse_order is not None else self.floor_width(), height)

    def shrink_stages(self):
        """InfoRowLayout이 빈 공간 다음에 줄이는 단계: [(순서, 그 단계에서 줄일 수 있는 가장 작은 너비)]."""
        stages = [(self.shrink_order, self.floor_width())]
        if self._collapse_order is not None:
            stages.append((self._collapse_order, 0))
        return stages

    def comfortable_width(self):
        """빈 공간을 다 내준 너비: fit_text를 QLabel 그대로 그리는 가장 작은 너비 (None이면 원하는 너비 그대로).
        InfoRowLayout이 원하는 너비와 최소 너비 사이로 자름."""
        return self._metrics()[3]

    # --- 그리기 ---
    def _compute_placement(self, text, width):
        """(그릴 글자, 글자 왼쪽 x, QLabel 그대로 그려도 되는지) — 너비 width에서 text를 어떻게 그리는지.
        글자열 전체를 재는 일(셰이핑)은 꼭 필요할 때 한 번씩만 (재생 중 매 프레임 불림)."""
        left, right = self._widths[:2]
        metrics = self._widths[6]
        normal = width - left - right
        tight = width - 2 * TIGHT_INSET
        if not text or self._loose_width(text, metrics) + 1 <= normal:
            return (text, left, True)  # 글자 하나씩 너비를 더한 값(커닝 없이 — 실제보다 크거나 같음)으로도 들어감
        advance = metrics.horizontalAdvance(text)
        ink = advance
        if advance > normal and advance - normal <= _TRAILING_SLACK:
            ink = metrics.tightBoundingRect(text).right()  # 끝의 글자 간격만 넘치는지 잉크로 확인
        if ink <= normal:
            return (text, left, True)
        if max(advance, ink) <= tight:
            return (text, max(TIGHT_INSET, min(left, int(width - TIGHT_INSET - max(advance, ink)))), False)
        return (metrics.elidedText(text, self._elide_mode, max(0, tight)), TIGHT_INSET, False)

    def _placement(self):
        """지금 글자·너비의 그리기 방법 (글자·너비가 바뀔 때만 다시 계산)."""
        self._metrics()
        text = self.text()
        width = self.width()
        cached = self._shown
        if cached is not None and cached[0] == text and cached[1] == width:
            return cached[2]
        placement = self._compute_placement(text, width)
        self._shown = (text, width, placement)
        return placement

    def displayed_text(self):
        """지금 너비에서 실제로 그려지는 글자: 다 들어가면 전체, 넘치면 …로 줄인 것."""
        return self._placement()[0]

    def _loose_width(self, text, metrics):
        """글자 하나씩의 너비를 더한 값 — 재생 중 매 프레임 바뀌는 숫자마다 글자열 전체를 다시 재지 않으려고.
        커닝·합자가 없으니 실제 너비보다 크거나 같음: 이 값으로 들어가면 확실히 들어감, 아니면 정확히 잼."""
        widths = self._char_widths
        total = 0.0
        for char in text:
            width = widths.get(char)
            if width is None:
                width = widths[char] = metrics.horizontalAdvance(char)
            total += width
        return total

    def paintEvent(self, event):
        shown, x, plain = self._placement()
        if plain:
            super().paintEvent(event)  # 다 들어감: QLabel 그대로 (예전과 똑같이)
            return
        painter = QPainter(self)
        self.drawFrame(painter)
        rect = self.contentsRect()
        margin = self.margin()
        rect.adjust(margin, margin, -margin, -margin)
        rect.setLeft(x)
        rect.setRight(self.width() - TIGHT_INSET - 1)
        option = QStyleOption()
        option.initFrom(self)
        align = (int(self.alignment()) & ~int(Qt.AlignHorizontal_Mask)) | int(Qt.AlignLeft)
        self.style().drawItemText(painter, rect, align, option.palette, self.isEnabled(), shown,
                                  self.foregroundRole())

    def tooltip_text(self):
        """마우스를 올렸을 때 보일 툴팁: 전체 글자 (full_text_tooltip이면 언제나, 아니면 줄여 그려질 때만), 없으면 ""."""
        text = self.text()
        if self._full_text_tooltip or self.displayed_text() != text:
            return text
        return ""

    def event(self, event):
        if event.type() == QEvent.ToolTip and not self.toolTip():  # setToolTip으로 정한 툴팁이 있으면 그대로
            tip = self.tooltip_text()
            if tip:
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)


class VerticalScrollArea(QScrollArea):
    """세로로만 스크롤하는 영역 (가로 스크롤 없음, 테두리 없음, 배경은 창 스타일시트 그대로).

    최소 높이는 QScrollArea 그대로 작음 — 안의 내용이 아무리 길어도 창의 최소 높이를 묶지 않음.
    최소 너비는 내용의 최소 너비 + 세로 스크롤바 — 스크롤바가 생겨도 내용이 오른쪽에서 잘리지 않음 (setMinimumWidth).
    원하는 크기(sizeHint)는 내용 전체: QScrollArea 기본값은 높이를 글자 높이의 24배로 잘라서, 그걸 쓰면 창이 높아질 때
    남는 높이를 아래 Play·Stop 버튼과 똑같이 나눠 가져 예전과 달리 가운데 열이 스크롤되고 버튼이 커짐.
    두 값은 내용의 레이아웃이 바뀔 때(접기 상자 펼침 등)·스타일이 바뀔 때만 다시 잼 — 재생 중 매 프레임 창 전체
    레이아웃을 다시 할 때마다 여러 번 불리므로 저장해 둔 값을 돌려줌.
    """

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self._full_size = QSize()
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(content)
        content.installEventFilter(self)
        self.update_size_hints()

    def update_size_hints(self):
        content = self.widget()
        frame = 2 * self.frameWidth()
        minimum = content.minimumSizeHint().expandedTo(content.minimumSize())
        width = minimum.width() + self.verticalScrollBar().sizeHint().width() + frame
        hint = content.sizeHint().expandedTo(content.minimumSize())
        full = QSize(max(hint.width() + frame, width), hint.height() + frame)
        if width != self.minimumWidth():
            self.setMinimumWidth(width)
        if full != self._full_size:
            self._full_size = full
            self.updateGeometry()

    def sizeHint(self):
        return QSize(self._full_size)

    def eventFilter(self, watched, event):
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            self.update_size_hints()  # 내용의 레이아웃이 바뀜 (펼침·접힘·글꼴)
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        # 스크롤바 너비·테두리가 바뀜 (만드는 중 setWidget 전에도 오므로 내용이 생긴 뒤부터)
        if event.type() in _METRICS_EVENTS and self.widget() is not None:
            self.update_size_hints()


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

    자리가 모자라면 이 순서로 줄임 (QHBoxLayout은 모든 항목에서 똑같이 빼서 글자가 꽉 찬 라벨도 같이 잘림):
      1) 빈 공간: 원하는 너비 − 글자가 다 들어가는 너비 (comfortable_width — 숫자 라벨), 모두 똑같이
      2) 단계 순서대로 (shrink_stages() → [(순서, 그 단계의 가장 작은 너비)], 없으면 [(shrink_order, 최소 너비)]):
         순서가 작은 단계부터, 같은 순서끼리는 똑같이
    크기 계산은 invalidate()까지 저장해 둠 — 재생 중 매 프레임 바뀌는 숫자 라벨 때문에 자주 불림.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._cache = None  # (보이는 항목, 원하는 너비, 최소, 빈 공간을 뺀 너비, 줄이는 순서, sizeHint, minimumSize)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Horizontal

    def invalidate(self):
        self._cache = None
        super().invalidate()

    def _data(self):
        if self._cache is None:
            items = [item for item in self._items if not item.isEmpty()]
            hint_sizes = [item.sizeHint() for item in items]
            min_sizes = [item.minimumSize() for item in items]
            hints = [size.width() for size in hint_sizes]
            minimums = [min(size.width(), hint) for size, hint in zip(min_sizes, hints)]
            comfortable = []
            stages = []  # 항목별 [(순서, 가장 작은 너비)]
            for item, hint, minimum in zip(items, hints, minimums):
                widget = item.widget()
                fit = widget.comfortable_width() if hasattr(widget, "comfortable_width") else None
                comfortable.append(hint if fit is None else max(minimum, min(fit, hint)))
                if hasattr(widget, "shrink_stages"):
                    stages.append([(order, max(minimum, floor)) for order, floor in widget.shrink_stages()])
                else:
                    stages.append([(getattr(widget, "shrink_order", 0), minimum)])
            margins = self.contentsMargins()
            extra_w = max(0, self.spacing()) * max(0, len(items) - 1) + margins.left() + margins.right()
            extra_h = margins.top() + margins.bottom()
            size_hint = QSize(sum(hints) + extra_w, max((s.height() for s in hint_sizes), default=0) + extra_h)
            minimum_size = QSize(sum(minimums) + extra_w, max((s.height() for s in min_sizes), default=0) + extra_h)
            self._cache = (items, hints, minimums, comfortable, stages, size_hint, minimum_size)
        return self._cache

    def sizeHint(self):
        return self._data()[5]

    def minimumSize(self):
        return self._data()[6]

    def widths_for(self, available):
        """너비 available(여백·간격 제외)에서 각 항목(보이는 것만, 순서대로)의 너비."""
        _items, hints, _minimums, comfortable, stages, _hint, _minimum = self._data()
        widths = list(hints)
        excess = sum(widths) - available
        if excess > 0:
            excess = _take_equally(widths, comfortable, range(len(widths)), excess)
        for order in sorted({order for item_stages in stages for order, _floor in item_stages}):
            if excess <= 0:
                break
            floors = list(widths)
            indices = []
            for i, item_stages in enumerate(stages):
                for stage_order, floor in item_stages:
                    if stage_order == order:
                        floors[i] = min(widths[i], floor)
                        indices.append(i)
            excess = _take_equally(widths, floors, indices, excess)
        return widths

    def setGeometry(self, rect):
        super().setGeometry(rect)
        items = self._data()[0]
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
