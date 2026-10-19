"""새 버전 알림 띠: 창 맨 위 전체 너비, 알릴 것이 있을 때만 보임 (설계 5-1, 시안 A — 파랑 띠·흰 글자·주황 '업데이트').

세 가지 모양:
- 새 버전 알림 (show_offer): "⬆ 새 버전 1.1.1이 나왔습니다 · 지금 1.1.0" + [바뀐 점] [업데이트] [나중에]
- 받는 중 (show_progress): 글자 + 진행 막대 + [취소] (멈출 수 없는 단계는 [취소] 없이)
- 잠깐 알림 (show_message): 글자만, 정한 시간 뒤 저절로 숨김 (예: "1.1.1로 업데이트했습니다")

글자는 ElidedLabel(최소 너비 0)이라 창이 좁으면 …로 줄여 그림(툴팁에 전체) — 띠가 보여도 창의 최소 너비가 늘지 않음
(2026-10-14 최소 크기 작업, tests/test_window_resize.py). 버튼은 누르는 일을 알리기만 함(신호) — 무엇을 할지는
창(PlayerUpdateMixin)이 정함. 버튼은 포커스를 받지 않음 (스페이스 등 창의 단축키가 띠의 버튼을 누르지 않게).
"""

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QPushButton, QSizePolicy

from yesoncheck.window_layout import ElidedLabel

OFFER_TEXT = "⬆ 새 버전 {new}이 나왔습니다 · 지금 {current}"
PROGRESS_STEPS = 1000  # 진행 막대는 천분율 (바이트 수는 QProgressBar의 int 범위를 넘을 수 있음)
PROGRESS_MAX_WIDTH = 160

# 창 스타일시트(QWidget·QPushButton 공통 모양) 위에 띠만의 모양 — 가까운 부모의 스타일시트가 이김
BANNER_STYLE = """
QFrame#updateBanner { background: #2f6fed; border: none; }
QFrame#updateBanner QLabel { background: transparent; color: #ffffff; font-weight: 600; }
QFrame#updateBanner QPushButton {
    background: rgba(255, 255, 255, 46); color: #ffffff; border: none; border-radius: 4px;
    padding: 3px 10px; font-weight: 700;
}
QFrame#updateBanner QPushButton:hover { background: rgba(255, 255, 255, 80); color: #ffffff; border: none; }
QFrame#updateBanner QPushButton:pressed { background: rgba(255, 255, 255, 30); color: #ffffff; border: none; }
QFrame#updateBanner QPushButton#updateBannerUpdate { background: #ffb020; color: #222222; }
QFrame#updateBanner QPushButton#updateBannerUpdate:hover { background: #ffc04d; color: #222222; }
QFrame#updateBanner QPushButton#updateBannerUpdate:pressed { background: #e89c10; color: #222222; }
QFrame#updateBanner QProgressBar {
    background: rgba(255, 255, 255, 46); border: none; border-radius: 4px; max-height: 10px;
}
QFrame#updateBanner QProgressBar::chunk { background: #ffb020; border-radius: 4px; }
"""


class UpdateBanner(QFrame):
    """창 맨 위의 알림 띠. 만든 뒤에는 숨김 — show_offer·show_progress·show_message가 보이고 hide_banner가 숨김."""

    notes_clicked = pyqtSignal()
    update_clicked = pyqtSignal()
    later_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBanner")
        self.setStyleSheet(BANNER_STYLE)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 최소 너비 0 (collapse_order): 좁으면 …로 줄이고, 띠 때문에 창의 최소 너비가 늘지 않음
        self.text_label = ElidedLabel(Qt.ElideRight, collapse_order=0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, PROGRESS_STEPS)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(PROGRESS_MAX_WIDTH)
        self.notes_button = self._button("바뀐 점", self.notes_clicked)
        self.update_button = self._button("업데이트", self.update_clicked)
        self.update_button.setObjectName("updateBannerUpdate")
        self.later_button = self._button("나중에", self.later_clicked)
        self.cancel_button = self._button("취소", self.cancel_clicked)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)
        layout.addWidget(self.text_label, 1)
        layout.addWidget(self.progress_bar)
        for button in (self.notes_button, self.update_button, self.later_button, self.cancel_button):
            layout.addWidget(button)
        self._hide_timer = QTimer(self)  # show_message의 저절로 숨김
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_banner)
        self._mode = "hidden"
        self.hide()

    @staticmethod
    def _button(text, signal):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(signal)
        return button

    def _show(self, mode, text, widgets):
        """mode 모양으로 보임: text(줄이기 전 전체 — 툴팁에도), widgets만 보이고 나머지 버튼·진행 막대는 숨김."""
        self._hide_timer.stop()
        self._mode = mode
        self.text_label.setText(text)
        self.text_label.setToolTip(text)
        for widget in (self.progress_bar, self.notes_button, self.update_button, self.later_button, self.cancel_button):
            widget.setVisible(widget in widgets)
        self.show()

    def show_offer(self, new: str, current: str) -> None:
        """새 버전 알림: "⬆ 새 버전 {new}이 나왔습니다 · 지금 {current}" + [바뀐 점] [업데이트] [나중에]."""
        self._show("offer", OFFER_TEXT.format(new=new, current=current),
                   (self.notes_button, self.update_button, self.later_button))

    def show_progress(self, done: int, total: int, text: str, cancellable: bool = True) -> None:
        """받는 중: text + 진행 막대(done/total, total이 0 이하면 움직이는 막대) + [취소] (cancellable이 False면 [취소] 없이 —
        멈출 수 없는 단계, 예: 도우미가 시작하기를 기다림)."""
        if total > 0:
            self.progress_bar.setRange(0, PROGRESS_STEPS)
            self.progress_bar.setValue(min(PROGRESS_STEPS, max(0, done * PROGRESS_STEPS // total)))
        else:
            self.progress_bar.setRange(0, 0)  # 전체 크기를 모름
        widgets = (self.progress_bar, self.cancel_button) if cancellable else (self.progress_bar,)
        self._show("progress", text, widgets)

    def show_message(self, text: str, hide_after_ms: int = 10000) -> None:
        """잠깐 알림: 글자만 보이고 hide_after_ms 뒤 저절로 숨김."""
        self._show("message", text, ())
        self._hide_timer.start(hide_after_ms)

    def hide_banner(self) -> None:
        self._hide_timer.stop()
        self._mode = "hidden"
        self.hide()

    def mode(self) -> str:
        """지금 모양: "offer"(새 버전 알림)·"progress"(받는 중)·"message"(잠깐 알림)·"hidden"."""
        return self._mode

    def full_text(self) -> str:
        """띠의 글자 전체 (창이 좁아 …로 줄여 그려도 줄이기 전 그대로)."""
        return self.text_label.text()
