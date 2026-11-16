"""사이드바의 조작 묶음 — `SidebarControlsMixin` (`PlayerSidebarMixin`의 부모, 2026-11-16 UI 개편 PR 2).

가운데 열을 없애며 사이드바로 옮긴 것과, 사이드바에 원래 있던 단추를 중립 색의 작은 단추로 정리한 것:

    [Yeson 작품 / 작품 ▾ / 시즌 ▾ / job ▾]   ← 작품 묶음 (이 PC에서 작품을 읽어 온 적이 있을 때만 — work_picker)
    [폴더 열기] [북마크 ▾] [새로고침]          ← 작은 단추 줄
    [목록] [썸네일]
      (탭 · 목록 · 개수 줄 — 그대로)
    [썸네일 진행 막대]                         ← 만드는 동안만
    [고른 영상 이어 재생]                      ← 선택 재생 단추 하나 (시작 / 일시정지 / 이어 재생)
    [이어 재생 끝내기]                         ← 선택 재생 중에만 (player_transport)

위젯을 만들고 줄로 묶는 일만 한다 — 누르면 하는 일은 지금의 처리기 그대로(`select_folder`·`add_bookmark`·
`show_bookmarks`·`_refresh_sidebar_by_user`·`switch_to_list_mode`·`switch_to_thumbnail_mode`·
`toggle_play_pause_selected`), 콤보의 동작도 그대로(신호는 `VideoPlayerBase.__init__`이 잇는다).

**선택 재생 단추의 어댑터** `PlaylistStateSlot`: 재생 코드는 옛 단추 이름 `playSelectedPauseButton`에 글자
'Selected Play'·'Selected Pause'와 노란 바탕을 넣는다(`player_playback`·`sidebar_playlist`의 여섯 줄). 그 줄들을
건드리지 않으려고 그 이름 자리에서 받아(`text()`는 받은 글 그대로) 진짜 단추에 화면 글자(글자 표)와 `playing`
속성(테마 시트가 강조)으로 넘긴다 — 재생 줄의 `PlayStateSlot`과 같은 방식.
"""

import sys
import traceback

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QSizePolicy,
                             QToolButton, QVBoxLayout, QWidget)

from yesoncheck import ui_text, work_picker
from yesoncheck.user_files import UserFileError

LOG_PREFIX = "[작품 고르기]"
SIDEBAR_TOOL = "sidebarTool"  # 작은 단추의 objectName — 색은 두 테마 시트의 #sidebarTool 규칙
COMBO_MINIMUM_CHARS = 6  # 콤보의 최소 너비(글자 수) — 긴 작품·job 이름이 사이드바(창)의 최소 너비를 늘리지 않게
THUMBNAIL_BAR_LINGER_MS = 1500  # 썸네일을 다 만든 뒤 진행 막대(끝난 글자)를 보여 두는 시간


class WidePopupComboBox(QComboBox):
    """펼친 목록이 내용만큼 넓은 콤보 — 사이드바 폭의 좁은 콤보에서도 긴 작품·job 이름을 목록에서는 끝까지 읽게."""

    def showPopup(self):
        view = self.view()
        wanted = view.sizeHintForColumn(0) + 2 * view.frameWidth() + view.verticalScrollBar().sizeHint().width()
        view.setMinimumWidth(max(self.width(), wanted))
        super().showPopup()


class PlaylistStateSlot:
    """옛 'Selected Play/Pause' 단추의 이름 자리에 꽂는 어댑터 (모듈 설명).

    `setText('Selected Play'|'Selected Pause')` → 진짜 단추의 글자·`playing` 속성. `setStyleSheet`는 받기만 한다
    (옛 코드의 노란 바탕 — 강조는 테마 시트가 `playing` 속성으로). 켜짐/꺼짐은 진짜 단추에 그대로.
    """

    _PLAYING = {"Selected Play": False, "Selected Pause": True}

    def __init__(self, button):
        self.button = button
        self._text = "Selected Play"
        self._show()

    def setText(self, text):
        if text not in self._PLAYING:
            raise ValueError(f"선택 재생 단추의 글은 'Selected Play'·'Selected Pause'뿐: {text!r}")
        if text == self._text:
            return
        self._text = text
        self._show()

    def text(self):
        return self._text

    def setStyleSheet(self, sheet):
        """받기만 함 — 옛 코드는 재생 중에 단추를 노랗게 칠했고 멈추면 지웠다."""

    def setEnabled(self, enabled):
        self.button.setEnabled(enabled)

    def isEnabled(self):
        return self.button.isEnabled()

    def retranslate(self):
        self._show()

    def _show(self):
        playing = self._PLAYING[self._text]
        button = self.button
        button.setText(ui_text.text("playlist.pause" if playing else "playlist.play"))
        button.setToolTip(ui_text.text("playlist.play.tip"))
        if button.property("playing") != playing:
            button.setProperty("playing", playing)
            style = button.style()  # 속성으로 고르는 시트 규칙([playing="true"])은 다시 입혀야 바뀜
            style.unpolish(button)
            style.polish(button)


class SidebarControlsMixin:
    # ------------------------------------------------------------ 만들기 (initUI가 부름)
    def _build_work_picker(self):
        """작품 묶음 `workPickerGroup`: 라벨 + 작품·시즌·job 콤보 (콤보는 initUI가 만들어 둔 것)."""
        self.workLabel = QLabel(ui_text.text("sidebar.works"))
        self.workLabel.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.workLabel.setFocusPolicy(Qt.NoFocus)
        group = QWidget()
        group.setObjectName("workPicker")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.workLabel)
        for combo in (self.workComboBox, self.seasonComboBox, self.jobComboBox):
            # 콤보의 너비는 사이드바 폭을 따름: 최소 너비를 글자 몇 자로 묶어, 긴 이름이 들어와도 사이드바가 넓어지지 않게.
            # 잘린 이름은 툴팁으로(_show_combo_tooltips), 펼친 목록은 내용 너비로(WidePopupComboBox)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(COMBO_MINIMUM_CHARS)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setFocusPolicy(Qt.NoFocus)
            combo.currentIndexChanged.connect(self._show_combo_tooltips)
            layout.addWidget(combo)
        self.workPickerGroup = group
        self._work_picker_seen = self._read_work_picker_seen()
        self._sync_work_picker()
        return group

    def _build_sidebar_tools(self):
        """작은 단추 줄: 폴더 열기 · 북마크 ▾(추가·관리) · 새로고침. 한 줄 위젯을 돌려줌."""
        self.openFolderButton = QPushButton()
        self.openFolderButton.clicked.connect(lambda: self.select_folder())
        self.bookmarkMenuButton = QToolButton()
        self.bookmarkMenuButton.setPopupMode(QToolButton.InstantPopup)
        self.bookmarkMenuButton.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(self.bookmarkMenuButton)
        self._bookmark_add_action = menu.addAction("")
        self._bookmark_add_action.triggered.connect(lambda: self.add_bookmark())
        self._bookmark_manage_action = menu.addAction("")
        self._bookmark_manage_action.triggered.connect(lambda: self.show_bookmarks())
        self.bookmarkMenuButton.setMenu(menu)
        # 목록 다시 읽기: 다른 PC·Finder에서 NAS의 영상을 지우거나 넣었을 때 (창이 다시 활성될 때도 저절로 읽음)
        self.refreshListButton = QPushButton()
        self.refreshListButton.clicked.connect(lambda: self._refresh_sidebar_by_user())
        return self._tool_row(self.openFolderButton, self.bookmarkMenuButton, self.refreshListButton)

    def _build_view_mode_row(self):
        """목록 | 썸네일 토글 (예전 List·Thumb 단추 — 이름과 처리기는 그대로)."""
        self.listModeButton = QPushButton()
        self.listModeButton.setCheckable(True)
        self.listModeButton.setChecked(True)
        self.listModeButton.clicked.connect(self.switch_to_list_mode)
        self.thumbnailModeButton = QPushButton()
        self.thumbnailModeButton.setCheckable(True)
        self.thumbnailModeButton.clicked.connect(self.switch_to_thumbnail_mode)
        # Seq 목록도 같은 표시 모드를 따름: 위의 Mov 쪽 슬롯이 모드를 바꾼 다음에 불리도록 그 뒤에 이음 (Mov 쪽 메서드는 그대로)
        self.listModeButton.clicked.connect(self._apply_seq_display_mode)
        self.thumbnailModeButton.clicked.connect(self._apply_seq_display_mode)
        return self._tool_row(self.listModeButton, self.thumbnailModeButton)

    def _tool_row(self, *buttons):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for button in buttons:
            button.setObjectName(SIDEBAR_TOOL)
            button.setFocusPolicy(Qt.NoFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout.addWidget(button)
        return row

    def _build_thumbnail_progress_bar(self):
        """썸네일 진행 막대 — 만드는 동안만 보임(`_make_thumbnails`가 보이고, 끝나면 잠깐 뒤 이 타이머가 숨김)."""
        bar = QProgressBar()
        bar.setObjectName("thumbnailProgress")
        bar.setMinimum(0)
        bar.setMaximum(100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFixedHeight(18)
        bar.hide()
        self.thumbnailProgressBar = bar
        self._thumbnail_bar_timer = QTimer(self)
        self._thumbnail_bar_timer.setSingleShot(True)
        self._thumbnail_bar_timer.setInterval(THUMBNAIL_BAR_LINGER_MS)
        self._thumbnail_bar_timer.timeout.connect(bar.hide)
        return bar

    def _build_playlist_button(self):
        """선택 재생 단추 하나: 선택 재생이 아니면 시작, 선택 재생 중이면 일시정지 ↔ 이어 재생 (`toggle_play_pause_selected`)."""
        button = QPushButton()
        button.setObjectName("playlistButton")
        button.setFocusPolicy(Qt.NoFocus)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(lambda: self.toggle_play_pause_selected())
        self.playlistButton = button
        self.playSelectedPauseButton = PlaylistStateSlot(button)  # 재생 코드가 쓰는 옛 이름 (어댑터)
        return button

    def retranslate_sidebar_controls(self):
        """글자 표에서 사이드바 조작 묶음의 글자·툴팁을 다시 읽음 (만든 직후와 언어가 바뀐 뒤)."""
        self.workLabel.setText(ui_text.text("sidebar.works"))
        self.openFolderButton.setText(ui_text.text("sidebar.open_folder"))
        self.bookmarkMenuButton.setText(ui_text.text("sidebar.bookmarks"))
        self._bookmark_add_action.setText(ui_text.text("sidebar.bookmark.add"))
        self._bookmark_manage_action.setText(ui_text.text("sidebar.bookmark.manage"))
        self.refreshListButton.setText(ui_text.text("sidebar.refresh"))
        self.refreshListButton.setToolTip(ui_text.text("sidebar.refresh.tip"))
        self.listModeButton.setText(ui_text.text("sidebar.mode.list"))
        self.thumbnailModeButton.setText(ui_text.text("sidebar.mode.thumb"))
        self.playSelectedPauseButton.retranslate()

    # ------------------------------------------------------------ 작품 묶음의 보임
    def _read_work_picker_seen(self):
        """이 PC에서 작품을 읽어 온 적이 있는지 (창을 만들 때 한 번). 설정 파일을 읽지 못하면 기록하고 **보이는 쪽**으로 —
        사내 PC에서 작품 고르기가 사라지지 않게. 창은 띄우지 않는다: 같은 파일을 읽는 다른 설정이 켤 때 이미 알렸다."""
        try:
            return work_picker.read_seen()
        except (UserFileError, ValueError, OSError):
            print(f"{LOG_PREFIX} 설정 파일을 읽지 못해 작품 묶음을 보입니다 (파일은 그대로):", file=sys.stderr, flush=True)
            traceback.print_exc()
            return None  # 모름 — 보이되, 파일에 적지도 않음

    def _sync_work_picker(self):
        """작품 묶음의 보임을 맞춤: 작품이 있으면 보이고 그 사실을 기억, 없으면 기억대로 (모듈 설명 — work_picker)."""
        if not hasattr(self, "workPickerGroup"):
            return  # 창을 만드는 중 — 묶음이 생긴 뒤 _build_work_picker가 다시 부름
        if self.work_paths and self._work_picker_seen is False:
            self._work_picker_seen = True
            try:
                work_picker.remember_seen()
            except (UserFileError, OSError, TimeoutError):
                print(f"{LOG_PREFIX} 작품을 읽어 왔음을 설정 파일에 적지 못했습니다 (이 창에서는 보임):", file=sys.stderr, flush=True)
                traceback.print_exc()
        self.workPickerGroup.setVisible(bool(self.work_paths) or self._work_picker_seen is not False)

    def _show_combo_tooltips(self, *_args):
        """콤보마다 고른 글자를 툴팁으로 — 사이드바 폭에서 잘린 긴 작품·job 이름을 읽을 수 있게."""
        for combo in (self.workComboBox, self.seasonComboBox, self.jobComboBox):
            combo.setToolTip(combo.currentText())
