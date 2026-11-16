"""재생 줄 — 슬라이더 바로 아래, 높이가 고정된 한 줄 (2026-11-16 UI 개편).

    [A: 파일 이름 ……]   [|◀ ◀| ▶ |▶ ▶| ↻]   [ 12 ] / 334 (20F 14f)  00:00:00.458 / 00:00:13.917  24 fps  [A|B 와이프 X Y  주석 OCR]  🔊 ──

- 가운데 단추 묶음과 프레임 칸의 자리는 막대 너비만 따른다 — 파일 이름·전체 글자·fps 글자가 바뀌어도 그대로
  (오른쪽 구역의 원하는 너비가 글자와 상관없이 고정이라서: 프레임 칸은 숫자 여섯 자리, 라벨은 본보기 글자의 너비).
- **도구 토글**(`ToolToggleGroup` — 와이프·X·Y·주석·OCR): 켜짐/꺼짐 단추. 무엇에 이을지는 플레이어가 정한다.
- 좁아지면 이 차례로: ① 도구 토글의 글자가 빠져 아이콘만(그 몫만큼 줄어드는 동안 파일 이름 몫 `NAME_HINT`와 단추
  자리는 그대로) → ② 파일 이름이 줄어 사라짐 → ③ 오른쪽 구역이 `InfoRowLayout`의 차례(fps → 시간 → 전체의 뒤쪽 →
  접기: fps → 시간 → 볼륨 슬라이더 → 도구 토글)로 준다. 단추 여섯과 프레임 숫자(`n / 전체`)는 최소 너비에서도 다 보인다.
  ①이 먼저인 까닭: 토글을 글자째 두면 보통 창 너비(1400px)에서 오른쪽 구역이 막대를 거의 다 차지해 재생 단추가
  왼쪽 끝으로 밀리고 파일 이름이 사라진다 — 아이콘(툴팁·메뉴·N 키가 같은 일을 함)이 그보다 낫다.
- **어댑터**: 재생·탐색 코드(`player_playback`)는 옛 정보 줄의 이름과 글자 규약으로 표시를 고친다
  (`labelFrameCount.setText('Current: 12')`·`labelTotalFrames.setText('Total: 334 (20F 14f)')`·
  `labelPlaybackFPS.setText('재생: 24 FPS')`·`playPauseButton.setText('Pause')`). 그 줄들과 그 글자를 보는 시험을
  건드리지 않으려고 `TextSlot`·`PlayStateSlot`이 그 이름 자리에서 글자를 받아(`text()`는 받은 글 그대로) 이 막대의
  위젯에 넘긴다 — 화면에는 `shown_*`가 바꾼 모양(`12` · `/ 334 (20F 14f)` · `24 fps`)으로.

이 모듈은 플레이어를 모른다(단추를 무엇에 이을지는 `player_transport`).
"""

from PyQt5.QtCore import QEvent, QLocale, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIntValidator
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QLayout, QLineEdit, QSizePolicy, QSlider, QStyle,
                             QStyleOptionToolButton, QToolButton, QWidget)

from yesoncheck import transport_icons, ui_text
from yesoncheck.window_layout import ElidedLabel, InfoRowLayout

BAR_HEIGHT = 44
BUTTON_SIZE = 30
ICON_SIZE = 18
BUTTON_SPACING = 2
ZONE_GAP = 12  # 구역(파일 이름 | 단추 | 정보) 사이
SIDE_MARGIN = 8
INFO_SPACING = 8
VOLUME_WIDTH = 90
FRAME_DIGITS = 6  # 프레임 칸의 너비 — 숫자 여섯 자리
NAME_HINT = 200  # 막대가 '원하는' 너비에 넣는 파일 이름 몫 (글자에 따라 창의 원하는 크기가 흔들리지 않게 고정)
TOGGLE_SPACING = 2  # 도구 토글 사이
TOGGLE_GROUP_GAP = 8  # 와이프 묶음(와이프·X·Y)과 패널 토글(주석·OCR) 사이
AXIS_WIDTH = 22  # X·Y 단추의 가장 좁은 너비
ICON_COLORS = {"dark": "#d0d0d0", "light": "#333333"}

_CURRENT_PREFIX = "Current: "
_TOTAL_PREFIX = "Total: "
_TOTAL_WIPE_PREFIX = "Total "  # 와이프: 'Total A: 334 (…), B: 120 (…)'
_FPS_PREFIX = "재생: "


def shown_current(raw):
    """'Current: 12' → '12'. 그 꼴이 아니면 받은 글 그대로(숨기지 않음)."""
    return raw[len(_CURRENT_PREFIX):] if raw.startswith(_CURRENT_PREFIX) else raw


def shown_total(raw):
    """'Total: 334 (20F 14f)' → '/ 334 (20F 14f)', 'Total A: …, B: …' → '/ A: …, B: …'. 그 꼴이 아니면 그대로."""
    for prefix in (_TOTAL_PREFIX, _TOTAL_WIPE_PREFIX):
        if raw.startswith(prefix):
            return "/ " + raw[len(prefix):]
    return raw


def shown_fps(raw):
    """'재생: 24 FPS · 실제 23.8' → '24 fps · 실제 23.8', '재생: 정지' → '정지'. 그 꼴이 아니면 그대로."""
    return raw[len(_FPS_PREFIX):].replace(" FPS", " fps") if raw.startswith(_FPS_PREFIX) else raw


class TextSlot:
    """옛 라벨의 이름 자리에 꽂는 어댑터: `setText`로 받은 글을 기억하고(`text()`) 바뀌었을 때만 show(글)로 넘김.
    재생 틱마다 같은 글이 와도 아무것도 하지 않는다."""

    def __init__(self, text, show):
        self._text = text
        self._show = show

    def setText(self, text):
        if text == self._text:
            return
        self._text = text
        self._show(text)

    def text(self):
        return self._text


class PlayStateSlot:
    """옛 Play 단추의 이름 자리에 꽂는 어댑터: 재생 코드가 넣는 글 'Play'/'Pause'를 재생 중인지로 바꿔 넘김."""

    _PLAYING = {"Play": False, "Pause": True}

    def __init__(self, show_playing):
        self._text = "Play"
        self._show_playing = show_playing

    def setText(self, text):
        if text not in self._PLAYING:
            raise ValueError(f"재생 단추의 글은 'Play'·'Pause'뿐: {text!r}")
        self._text = text
        self._show_playing(self._PLAYING[text])

    def text(self):
        return self._text

    def setStyleSheet(self, sheet):
        """받기만 함 — 옛 코드는 재생 중에 큰 단추를 노랗게 칠했고(`background-color: yellow;`) 멈추면 지웠다.
        재생 줄은 아이콘(재생 ↔ 일시정지)으로 알린다."""


class FrameField(QLineEdit):
    """프레임 칸: 지금 프레임 번호를 보이고, 누르면 숫자를 쳐서 그 프레임으로 간다.

    - `show_number(글)`: 보일 글. 편집 중(포커스가 있는 동안)에는 기억만 하고 치던 글자를 덮지 않는다.
    - Enter: 숫자면 `frameEntered(값)`, 그리고 편집 끝. 빈 글이면 되돌리고 편집 끝. Esc: 되돌리고 편집 끝.
      편집 끝 = 기억한 글로 되돌림 + 포커스 놓음 + `editingEnded`(창이 포커스를 되찾아 단축키가 다시 먹게).
    - 창 안의 다른 곳을 눌러 포커스가 떠나면 되돌리기만 한다(`editingEnded` 없음 — 눌린 위젯의 포커스를 뺏지 않게).
      다른 앱·창으로 가서 창이 비활성이 되면 편집 끝(`editingEnded`) — 돌아왔을 때 포커스가 칸에 남지 않게.
    너비는 숫자 여섯 자리로 고정(글자가 바뀌어도 옆 위젯이 움직이지 않게).
    """

    frameEntered = pyqtSignal(int)
    editingEnded = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frameField")
        self._number = "0"
        self._select_after_press = False
        validator = QIntValidator(0, 9_999_999, self)
        validator.setLocale(QLocale.c())  # 숫자만 (지역 설정의 자릿수 구분 기호 없이)
        self.setValidator(validator)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setText(self._number)
        self.setToolTip(ui_text.text("transport.frame"))

    def show_number(self, text):
        self._number = text
        if not self.hasFocus() and self.text() != text:
            self.setText(text)

    def sizeHint(self):
        base = super().sizeHint()
        metrics = self.fontMetrics()
        widest = max("0123456789", key=metrics.horizontalAdvance)
        frame = max(8, base.width() - metrics.horizontalAdvance("x") * 17)  # QLineEdit의 원하는 너비 = 'x' 17자 + 테두리·여백
        return QSize(metrics.horizontalAdvance(widest * FRAME_DIGITS) + frame, base.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def _end_editing(self):
        self.setText(self._number)
        self.clearFocus()
        self.editingEnded.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self._end_editing()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            typed = self.text()
            number = int(typed) if typed.isascii() and typed.isdigit() else None
            self._end_editing()  # 먼저 끝냄 — 이동한 쪽이 show_number로 새 번호를 넣을 수 있게
            if number is not None:
                self.frameEntered.emit(number)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()  # 치면 번호가 통째로 바뀜
        self._select_after_press = event.reason() == Qt.MouseFocusReason

    def mousePressEvent(self, event):
        super().mousePressEvent(event)  # 누른 자리에 커서를 놓으며 선택을 풂 — 처음 누름이면 다시 전체 선택
        if self._select_after_press:
            self._select_after_press = False
            self.selectAll()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._select_after_press = False
        if self.text() != self._number:
            self.setText(self._number)
        self.deselect()
        if event.reason() == Qt.ActiveWindowFocusReason:
            # 다른 앱·창으로 가서 창이 비활성이 됨: 편집을 끝냄 — 포커스가 칸에 남으면 돌아왔을 때 단축키가 칸으로 감.
            # (창 안의 다른 위젯을 눌러 떠날 때는 신호 없음 — 그 위젯의 포커스를 뺏지 않게)
            self.editingEnded.emit()


class _VolumeSlider(QSlider):
    """볼륨 슬라이더: 원하는 너비 VOLUME_WIDTH, 자리가 모자라면 0까지 (재생 줄에서 가장 나중에 줄어듦)."""

    shrink_order = 9  # InfoRowLayout — 라벨들의 줄임·접기(1~8) 뒤

    def sizeHint(self):
        return QSize(VOLUME_WIDTH, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


class ToolToggle(QToolButton):
    """재생 줄의 도구 토글(와이프·주석·OCR): 아이콘 + 글자, 켜짐/꺼짐. `set_compact(True)`면 아이콘만(너비 BUTTON_SIZE).

    `full_width()`는 지금 모양과 상관없이 '글자까지 보일 때' Qt가 바라는 너비 — 묶음이 그 값으로 자리를 정한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transportToggle")
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._compact = False

    def full_width(self):
        """글자 옆 아이콘 모양일 때의 원하는 너비 — `QToolButton::sizeHint`(Qt 5.15)와 같은 계산을 그 모양으로."""
        self.ensurePolished()
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.toolButtonStyle = Qt.ToolButtonTextBesideIcon
        metrics = self.fontMetrics()
        text = metrics.size(Qt.TextShowMnemonic, self.text())
        width = option.iconSize.width() + 4 + text.width() + metrics.horizontalAdvance(" ") * 2
        height = max(option.iconSize.height(), text.height())
        option.rect.setSize(QSize(width, height))
        wanted = self.style().sizeFromContents(QStyle.CT_ToolButton, option, QSize(width, height), self)
        return max(BUTTON_SIZE, wanted.width())

    def is_compact(self):
        return self._compact

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)

    def sizeHint(self):
        return QSize(BUTTON_SIZE if self._compact else self.full_width(), BUTTON_SIZE)

    def minimumSizeHint(self):
        return self.sizeHint()


class ToolToggleGroup(QWidget):
    """도구 토글 묶음 — 재생 줄 오른쪽 구역의 한 항목: [와이프 X Y] [주석 OCR]. 자식은 손으로 놓는다(레이아웃 없음).

    너비에 따라 세 모양:
      원하는 너비(sizeHint) 이상 → 글자까지
      `compact_width()` 이상 → 아이콘만, 오른쪽에 붙임(막대가 좁아지는 동안 토글이 제자리에 있게)
      그보다 좁으면 → 아무것도 보이지 않음 (잘린 단추를 보이지 않게)
    줄이는 차례(`shrink_stages` — InfoRowLayout): 글자는 다른 무엇보다 먼저(-1: 라벨의 빈 공간보다도),
    통째로 사라지는 것은 맨 나중(11: 볼륨 슬라이더 뒤). 너비 계산은 `refit()`까지 저장해 둔다 — 재생 중 틱마다
    라벨 글자가 바뀔 때 오른쪽 구역이 크기를 다시 묻는다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wipeButton = ToolToggle(self)
        self.wipeXButton = self._axis_button()
        self.wipeYButton = self._axis_button()
        self.annotationButton = ToolToggle(self)
        self.ocrButton = ToolToggle(self)
        self._widths = None  # (글자까지일 때의 너비들, 아이콘만일 때의 너비들) — 자식 차례대로
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _axis_button(self):
        button = QToolButton(self)
        button.setObjectName("transportToggle")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setEnabled(False)  # 와이프를 켜야 켜짐
        return button

    def toggles(self):
        """글자가 아이콘으로 줄어드는 토글 셋."""
        return (self.wipeButton, self.annotationButton, self.ocrButton)

    def _children(self):
        return (self.wipeButton, self.wipeXButton, self.wipeYButton, self.annotationButton, self.ocrButton)

    def _measure(self):
        if self._widths is None:
            axis = [max(AXIS_WIDTH, QToolButton.sizeHint(button).width()) for button in (self.wipeXButton, self.wipeYButton)]
            full = [self.wipeButton.full_width(), axis[0], axis[1], self.annotationButton.full_width(),
                    self.ocrButton.full_width()]
            compact = [BUTTON_SIZE, axis[0], axis[1], BUTTON_SIZE, BUTTON_SIZE]
            self._widths = (full, compact)
        return self._widths

    @staticmethod
    def _total(widths):
        return sum(widths) + TOGGLE_SPACING * (len(widths) - 2) + TOGGLE_GROUP_GAP

    def sizeHint(self):
        return QSize(self._total(self._measure()[0]), BUTTON_SIZE)

    def minimumSizeHint(self):
        return QSize(0, BUTTON_SIZE)

    def compact_width(self):
        """아이콘만일 때의 너비."""
        return self._total(self._measure()[1])

    def text_saving(self):
        """글자를 빼면 줄어드는 너비 (원하는 너비 − 아이콘만일 때의 너비)."""
        return self.sizeHint().width() - self.compact_width()

    def shrink_stages(self):
        return [(-1, self.compact_width()), (11, 0)]

    def refit(self):
        """글자·글꼴·스타일이 바뀐 뒤: 너비를 다시 재고 자식을 다시 놓음."""
        self._widths = None
        self.updateGeometry()
        self._arrange()

    def _arrange(self):
        full, compact = self._measure()
        width = self.width()
        if width >= self._total(full):
            widths, shown, x = full, True, 0
        elif width >= self._total(compact):
            widths, shown, x = compact, True, width - self._total(compact)
        else:
            widths, shown, x = compact, False, 0
        for toggle in self.toggles():
            toggle.set_compact(widths is compact)
        top = max(0, (self.height() - BUTTON_SIZE) // 2)
        for index, (button, button_width) in enumerate(zip(self._children(), widths)):
            button.setGeometry(x, top, button_width, BUTTON_SIZE)
            button.setVisible(shown)
            x += button_width + (TOGGLE_GROUP_GAP if index == 2 else TOGGLE_SPACING)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self.refit()


class TransportRowLayout(QLayout):
    """세 구역 한 줄: 왼쪽(늘어나는 것 — 파일 이름) | 가운데(고정 — 단추 묶음) | 오른쪽(정보).

    안쪽 너비 W, 가운데 너비 cw에서:
      오른쪽 = 원하는 너비. 왼쪽에 `NAME_HINT`를 남기고는 그만큼 못 받으면 줄일 수 있는 몫(compactable() — 도구 토글의
               글자)까지는 오른쪽이 먼저 줄고, 그 뒤로는 왼쪽이 다 줄 때까지 그 너비를 지킴(그다음 최소 너비까지). 오른쪽 끝에 붙임
      가운데 = 막대의 한가운데 — 오른쪽 구역과 겹치면 그만큼 왼쪽으로
      왼쪽 = 남은 자리 전부. 그 위젯의 최소 너비(floor_width)보다 좁으면 0 (보이지 않음)
    최소 너비 = cw + 간격 + 오른쪽의 최소 너비 — 왼쪽 구역은 창의 최소 너비를 늘리지 않는다.
    """

    def __init__(self, left, center, right, gap, compactable=None, parent=None):
        super().__init__(parent)
        self._items = []
        self._left, self._center, self._right = left, center, right
        self._gap = gap
        self._compactable = compactable
        for widget in (left, center, right):
            self.addWidget(widget)

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

    def _extra(self):
        margins = self.contentsMargins()
        return margins.left() + margins.right(), margins.top() + margins.bottom()

    def _height(self):
        return max(self._left.sizeHint().height(), self._center.sizeHint().height(), self._right.sizeHint().height())

    def sizeHint(self):
        extra_w, extra_h = self._extra()
        width = NAME_HINT + self._gap + self._center.sizeHint().width() + self._gap + self._right.sizeHint().width()
        return QSize(width + extra_w, self._height() + extra_h)

    def minimumSize(self):
        extra_w, extra_h = self._extra()
        width = self._center.sizeHint().width() + self._gap + self._right.minimumSizeHint().width()
        return QSize(width + extra_w, self._height() + extra_h)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        area = rect.marginsRemoved(self.contentsMargins())
        width, gap = max(0, area.width()), self._gap
        center_w = min(self._center.sizeHint().width(), width)
        room = max(0, width - center_w - gap)  # 가운데 묶음을 빼고 오른쪽 구역이 쓸 수 있는 자리
        wanted = self._right.sizeHint().width()
        compact = wanted - (max(0, self._compactable()) if self._compactable is not None else 0)
        spare = width - center_w - 2 * gap - NAME_HINT  # 파일 이름 몫을 남기고 오른쪽 구역이 쓸 수 있는 자리
        right_w = max(0, min(wanted, max(compact, spare), room))
        center_x = max(0, min((width - center_w) // 2, width - right_w - gap - center_w))
        left_w = max(0, center_x - gap)
        floor = self._left.floor_width() if hasattr(self._left, "floor_width") else self._left.minimumSizeHint().width()
        if left_w < floor:
            left_w = 0
        top, height = area.top(), area.height()
        self._left.setGeometry(QRect(area.left(), top, left_w, height))
        self._center.setGeometry(QRect(area.left() + center_x, top, center_w, height))
        self._right.setGeometry(QRect(area.left() + width - right_w, top, right_w, height))


class TransportBar(QWidget):
    """재생 줄 위젯 (모듈 설명). 공개 자식: filenameLabel · firstButton · prevButton · playButton · nextButton ·
    lastButton · loopButton · frameField · totalLabel · timeLabel · fpsLabel · toolGroup(wipeButton · wipeXButton ·
    wipeYButton · annotationButton · ocrButton) · volumeIcon · volumeSlider."""

    _BUTTONS = (("firstButton", "first", "transport.first"), ("prevButton", "prev", "transport.prev"),
                ("playButton", "play", "transport.play"), ("nextButton", "next", "transport.next"),
                ("lastButton", "last", "transport.last"), ("loopButton", "loop", "transport.loop"))
    _TOGGLES = (("wipeButton", "wipe", "transport.wipe"), ("annotationButton", "annotate", "transport.annotate"),
                ("ocrButton", "ocr", "transport.ocr"))
    _AXES = (("wipeXButton", "transport.wipe.x"), ("wipeYButton", "transport.wipe.y"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transportBar")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 테마 시트의 QWidget#transportBar 바탕·테두리를 칠하게
        self.setFixedHeight(BAR_HEIGHT)
        self._theme = "dark"
        self._playing = False

        self.filenameLabel = ElidedLabel(Qt.ElideMiddle, keep_ends=(4, 4), shrink_order=1, collapse_order=7,
                                         full_text_tooltip=True)

        center = QWidget()
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(BUTTON_SPACING)
        for name, _kind, _key in self._BUTTONS:
            button = QToolButton()
            button.setObjectName("transportButton")
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.NoFocus)
            setattr(self, name, button)
            center_layout.addWidget(button)
        self.loopButton.setCheckable(True)
        for button in (self.prevButton, self.nextButton):
            button.setAutoRepeat(True)  # 누르고 있으면 키를 누르고 있을 때처럼 이어서 넘어감

        self.frameField = FrameField()
        self.totalLabel = ElidedLabel(Qt.ElideRight, keep_text="/ 00000 (000F 00f)", keep_prefix="/ 00000",
                                      hint_text="/ 00000 (000F 00f)", shrink_order=4)
        self.totalLabel.setText("/ 0")
        self.timeLabel = ElidedLabel(Qt.ElideRight, keep_text="00:00:00.000 / 00:00:00.000",
                                     keep_prefix="00:00:00.000 /", hint_text="00:00:00.000 / 00:00:00.000",
                                     shrink_order=3, collapse_order=8)
        self.timeLabel.setText("00:00:00.000 / 00:00:00.000")
        self.fpsLabel = ElidedLabel(Qt.ElideRight, keep_text="00.000 fps · 실제 00.0", keep_prefix="",
                                    hint_text="00.000 fps · 실제 00.0", shrink_order=2, collapse_order=6)
        self.toolGroup = ToolToggleGroup()
        for name in ("wipeButton", "wipeXButton", "wipeYButton", "annotationButton", "ocrButton"):
            setattr(self, name, getattr(self.toolGroup, name))
        self.volumeIcon = QLabel()
        self.volumeIcon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.volumeSlider = _VolumeSlider(Qt.Horizontal)
        self.volumeSlider.setObjectName("volumeSlider")  # 테마 시트의 QSlider#volumeSlider 규칙 (가는 중립 색 슬라이더)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(50)  # 막대 혼자의 처음 값 — 창에서는 플레이어가 실제 볼륨으로 맞춤 (player_transport)
        self.volumeSlider.setFocusPolicy(Qt.NoFocus)
        self.volumeSlider.valueChanged.connect(self._show_volume)

        right = QWidget()
        right_layout = InfoRowLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(INFO_SPACING)
        for widget in (self.frameField, self.totalLabel, self.timeLabel, self.fpsLabel, self.toolGroup,
                       self.volumeIcon, self.volumeSlider):
            right_layout.addWidget(widget)

        layout = TransportRowLayout(self.filenameLabel, center, right, ZONE_GAP,
                                    compactable=self.toolGroup.text_saving)
        layout.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0)
        self.setLayout(layout)

        self.apply_theme(self._theme)
        self.retranslate()

    # --- 재생 코드가 어댑터로 넘기는 글 ---
    def show_current(self, raw):
        self.frameField.show_number(shown_current(raw))

    def show_total(self, raw):
        self.totalLabel.setText(shown_total(raw))

    def show_fps(self, raw):
        self.fpsLabel.setText(shown_fps(raw))

    def show_playing(self, playing):
        self._playing = bool(playing)
        self._refresh_play_button()

    # --- 모양 ---
    def _refresh_play_button(self):
        kind, key = ("pause", "transport.pause") if self._playing else ("play", "transport.play")
        self.playButton.setIcon(transport_icons.icon(kind, QColor(ICON_COLORS[self._theme]), ICON_SIZE))
        self.playButton.setToolTip(ui_text.text(key))

    def _show_volume(self, value):
        self.volumeSlider.setToolTip(ui_text.text("transport.volume", percent=value))

    def apply_theme(self, theme):
        """테마('dark'·'light')의 색으로 아이콘을 다시 그림. 모르는 테마는 KeyError — 바꾸기 전에."""
        color = QColor(ICON_COLORS[theme])
        self._theme = theme
        for name, kind, _key in self._BUTTONS:
            if name != "playButton":
                getattr(self, name).setIcon(transport_icons.icon(kind, color, ICON_SIZE))
        for name, kind, _key in self._TOGGLES:
            getattr(self, name).setIcon(transport_icons.icon(kind, color, ICON_SIZE))
        self._refresh_play_button()
        self.volumeIcon.setPixmap(transport_icons.pixmap("volume", color, ICON_SIZE, transport_icons.ICON_DPR))

    def retranslate(self):
        """글자 표에서 글자·툴팁을 다시 읽음 (언어가 바뀐 뒤)."""
        for name, _kind, key in self._BUTTONS:
            if name != "playButton":
                getattr(self, name).setToolTip(ui_text.text(key))
        for name, key in [(name, key) for name, _kind, key in self._TOGGLES] + list(self._AXES):
            button = getattr(self, name)
            button.setText(ui_text.text(key))
            button.setToolTip(ui_text.text(key + ".tip"))
        self.toolGroup.refit()
        self._refresh_play_button()
        self.frameField.setToolTip(ui_text.text("transport.frame"))
        self._show_volume(self.volumeSlider.value())
