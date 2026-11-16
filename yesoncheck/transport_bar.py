"""재생 줄 — 슬라이더 바로 아래, 높이가 고정된 한 줄 (2026-11-16 UI 개편).

    [A: 파일 이름 ……]      [|◀ ◀| ▶ |▶ ▶| ↻]      [ 12 ] / 334 (20F 14f)  00:00:00.458 / 00:00:13.917  24 fps  🔊 ──

- 가운데 단추 묶음과 프레임 칸의 자리는 막대 너비만 따른다 — 파일 이름·전체 글자·fps 글자가 바뀌어도 그대로
  (오른쪽 구역의 원하는 너비가 글자와 상관없이 고정이라서: 프레임 칸은 숫자 여섯 자리, 라벨은 본보기 글자의 너비).
- 좁아지면 파일 이름이 먼저 줄어 사라지고, 그다음 오른쪽 구역이 `InfoRowLayout`의 차례(fps → 시간 → 전체의 뒤쪽 →
  접기: fps → 시간 → 볼륨 슬라이더)로 준다. 단추 여섯과 프레임 숫자(`n / 전체`)는 최소 너비에서도 다 보인다.
- **어댑터**: 재생·탐색 코드(`player_playback`)는 옛 정보 줄의 이름과 글자 규약으로 표시를 고친다
  (`labelFrameCount.setText('Current: 12')`·`labelTotalFrames.setText('Total: 334 (20F 14f)')`·
  `labelPlaybackFPS.setText('재생: 24 FPS')`·`playPauseButton.setText('Pause')`). 그 줄들과 그 글자를 보는 시험을
  건드리지 않으려고 `TextSlot`·`PlayStateSlot`이 그 이름 자리에서 글자를 받아(`text()`는 받은 글 그대로) 이 막대의
  위젯에 넘긴다 — 화면에는 `shown_*`가 바꾼 모양(`12` · `/ 334 (20F 14f)` · `24 fps`)으로.

이 모듈은 플레이어를 모른다(단추를 무엇에 이을지는 `player_transport`).
"""

from PyQt5.QtCore import QLocale, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIntValidator
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QLayout, QLineEdit, QSizePolicy, QSlider, QToolButton,
                             QWidget)

from . import transport_icons, ui_text
from .window_layout import ElidedLabel, InfoRowLayout

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
    - 다른 곳을 눌러 포커스가 떠나면 되돌리기만 한다(`editingEnded` 없음 — 눌린 위젯의 포커스를 뺏지 않게).
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


class _VolumeSlider(QSlider):
    """볼륨 슬라이더: 원하는 너비 VOLUME_WIDTH, 자리가 모자라면 0까지 (재생 줄에서 가장 나중에 줄어듦)."""

    shrink_order = 9  # InfoRowLayout — 라벨들의 줄임·접기(1~8) 뒤

    def sizeHint(self):
        return QSize(VOLUME_WIDTH, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


class TransportRowLayout(QLayout):
    """세 구역 한 줄: 왼쪽(늘어나는 것 — 파일 이름) | 가운데(고정 — 단추 묶음) | 오른쪽(정보).

    안쪽 너비 W, 가운데 너비 cw에서:
      오른쪽 = 원하는 너비(모자라면 최소 너비까지), 오른쪽 끝에 붙임
      가운데 = 막대의 한가운데 — 오른쪽 구역과 겹치면 그만큼 왼쪽으로
      왼쪽 = 남은 자리 전부. 그 위젯의 최소 너비(floor_width)보다 좁으면 0 (보이지 않음)
    최소 너비 = cw + 간격 + 오른쪽의 최소 너비 — 왼쪽 구역은 창의 최소 너비를 늘리지 않는다.
    """

    def __init__(self, left, center, right, gap, parent=None):
        super().__init__(parent)
        self._items = []
        self._left, self._center, self._right = left, center, right
        self._gap = gap
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
        right_w = min(self._right.sizeHint().width(), max(self._right.minimumSizeHint().width(), room), room)
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
    lastButton · loopButton · frameField · totalLabel · timeLabel · fpsLabel · volumeIcon · volumeSlider."""

    _BUTTONS = (("firstButton", "first", "transport.first"), ("prevButton", "prev", "transport.prev"),
                ("playButton", "play", "transport.play"), ("nextButton", "next", "transport.next"),
                ("lastButton", "last", "transport.last"), ("loopButton", "loop", "transport.loop"))

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
        self.volumeIcon = QLabel()
        self.volumeIcon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.volumeSlider = _VolumeSlider(Qt.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(50)
        self.volumeSlider.setFocusPolicy(Qt.NoFocus)
        self.volumeSlider.valueChanged.connect(self._show_volume)

        right = QWidget()
        right_layout = InfoRowLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(INFO_SPACING)
        for widget in (self.frameField, self.totalLabel, self.timeLabel, self.fpsLabel, self.volumeIcon,
                       self.volumeSlider):
            right_layout.addWidget(widget)

        layout = TransportRowLayout(self.filenameLabel, center, right, ZONE_GAP)
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
        self._refresh_play_button()
        self.volumeIcon.setPixmap(transport_icons.pixmap("volume", color, ICON_SIZE, transport_icons.ICON_DPR))

    def retranslate(self):
        """글자 표에서 툴팁을 다시 읽음 (언어가 바뀐 뒤)."""
        for name, _kind, key in self._BUTTONS:
            if name != "playButton":
                getattr(self, name).setToolTip(ui_text.text(key))
        self._refresh_play_button()
        self.frameField.setToolTip(ui_text.text("transport.frame"))
        self._show_volume(self.volumeSlider.value())
