"""도구 패널을 플레이어에 잇는 얇은 층 — `PlayerToolsMixin` (`VideoPlayerBase`의 부모, 2026-11-16 UI 개편 PR 2).

예전의 가운데 열(스크롤되는 단추·접는 상자 열)을 없애고, 주석과 OCR은 뷰어 오른쪽의 도구 패널로 옮겼다:

    메인 스플리터 = [사이드바 | 영상 | 도구 패널(열었을 때만)]

- **쪽 둘**: `"annotation"`(예전 '수정 사항 주석' 상자의 위젯 그대로 — `player_annotations.build_annotation_page`)와
  `"ocr"`(예전 'ROI 설정'·'OCR 분석'·'결과 관리' 세 상자의 위젯을 머리글과 함께 차례로 — `_build_ocr_page`).
  위젯과 처리기는 그대로이고 놓이는 자리만 바뀌었다. 한 번에 한 쪽만 보인다.
- **여닫기**: 재생 줄의 주석·OCR 토글(`toggle_tool_page`), N 키(`toggle_tool_panel` — 열려 있으면 닫고, 닫혀 있으면
  마지막에 쓰던 쪽: 처음이면 주석), 패널의 닫기 단추, Tools 메뉴. 닫아도 쪽의 위젯·상태(주석 모드·ROI·입력값·분석
  결과)는 그대로다 — 숨기기만 한다.
- **폭**: 열 때 패널 폭(처음 `tool_panel.PANEL_WIDTH`, 그 뒤로는 사용자가 손잡이로 맞춘 폭)을 **영상 칸에서** 가져오고
  닫으면 영상 칸이 되찾는다(스플리터의 늘어나는 칸이 영상뿐). 사이드바 폭은 건드리지 않는다. 창이 좁아 영상 칸에
  `VIDEO_KEEP`도 남지 않으면 패널이 그만큼 좁게(패널의 최소 너비까지).
- **열린 상태와 보임은 따로**: `tool_panel_key()`는 '열려 있는 쪽'(없으면 None)이고, 화면의 보임은 **재생 줄을 따른다**
  (`apply_tool_panel_state`) — V 키·영상만 전체 화면이 컨트롤(`control_widgets` — 사이드바·재생 줄·슬라이더)을 숨기면
  재생 줄이 숨는 그 순간 패널도 숨고, 되돌아오면 열려 있던 쪽 그대로 같은 폭으로 나타난다. 닫혀 있던 패널은 그동안
  한 번도 보이지 않는다(그래서 패널은 `control_widgets`에 넣지 않는다 — 넣으면 되돌릴 때 일단 보이게 됨).
  재생 줄의 보임은 작은 이벤트 필터(`_VisibilityWatcher`)가 지켜본다: 숨기고 되돌리는 코드가 여러 곳(V 키 처리 둘,
  `hide_all_ui_elements`·`restore_ui_elements`)이라 곳마다 부르지 않고.

**스플리터 함정**: `QSplitter.setSizes`는 숨은 칸의 저장된 폭도 고친다 — 사이드바가 숨은 동안(V 키) 0을 넣으면
'접힘'으로 적혀 되돌릴 때 사이드바가 0폭으로 나타난다. 그래서 숨길 때는 `setVisible(False)`만 하고(폭은 스플리터가
영상 칸에 줌), 폭을 정하는 `setSizes`는 열 때 사이드바가 보이는 경우에만 부른다.
"""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from yesoncheck import error_window, tool_panel
from yesoncheck.main_window_styles import OCR_OPTION_LABEL_STYLE
from yesoncheck.window_layout import VerticalScrollArea

PANEL_KEYS = ("annotation", "ocr")
VIDEO_KEEP = 200  # 패널을 열 때 영상 칸에 남겨 두는 폭 — 창이 좁으면 패널이 그만큼 좁게 열림
PAGE_MARGIN = 10
OCR_CONTROL_MINIMUM_WIDTH = 140  # 예전 접는 상자 안에서의 최소 폭 그대로


class _VisibilityWatcher(QObject):
    """위젯이 숨겨지거나 다시 보이게 될 때(setVisible) callback()을 부르는 이벤트 필터."""

    def __init__(self, callback, parent):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.ShowToParent, QEvent.HideToParent):
            try:
                self._callback()
            except BaseException:  # 가상 함수 밖으로 예외를 내보내면 PyQt5가 프로세스를 끝냄
                error_window.report_from_handler("[도구 패널]", "컨트롤을 숨기거나 되돌리며 도구 패널을 맞추다가 오류가 났습니다.")
        return False


class PlayerToolsMixin:
    # ------------------------------------------------------------ 만들기 (initUI가 부름)
    def _init_tool_panel(self):
        """도구 패널(숨긴 채)과 두 쪽을 만들고 재생 줄의 토글·닫기 단추에 잇는다."""
        panel = tool_panel.ToolPanel()
        panel.add_page("annotation", "panel.annotation", self.build_annotation_page())
        panel.add_page("ocr", "panel.ocr", self._build_ocr_page())
        panel.hide()
        panel.closeRequested.connect(self.close_tool_panel)
        self.toolPanel = panel
        bar = self.transportBar
        bar.annotationButton.clicked.connect(lambda: self.toggle_tool_page("annotation"))
        bar.ocrButton.clicked.connect(lambda: self.toggle_tool_page("ocr"))
        self._tool_panel_watcher = _VisibilityWatcher(self.apply_tool_panel_state, self)
        bar.installEventFilter(self._tool_panel_watcher)  # 재생 줄이 숨거나 되돌아오면 패널도 (모듈 설명)
        return panel

    def _build_ocr_page(self):
        """OCR 쪽: 'ROI 설정'·'OCR 분석'·'결과 관리'의 위젯을 머리글 아래 차례로 (예전의 접는 상자 셋 — 위젯은 initUI가 만든 것)."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(5)

        mode_label = QLabel('OCR 분석 방식:')
        mode_label.setStyleSheet(OCR_OPTION_LABEL_STYLE)
        self.ocrPatternLabel.setStyleSheet(OCR_OPTION_LABEL_STYLE)
        sections = (
            ("ocr.section.roi", (self.ocrSelectRoiButton, self.ocrClearRoiButton, self.ocrTrackingCheckBox)),
            ("ocr.section.analysis", (mode_label, self.ocrModeComboBox, self.ocrPatternLabel, self.ocrPatternLineEdit,
                                      self.ocrAnalyzeButton, self.ocrAnalyzeRangeButton)),
            ("ocr.section.results", (self.ocrReopenResultButton, self.ocrSaveResultButton, self.ocrLoadResultButton)),
        )
        for index, (title_key, widgets) in enumerate(sections):
            if index:
                layout.addSpacing(8)
            layout.addWidget(tool_panel.section_title(title_key))
            for widget in widgets:
                if not isinstance(widget, QLabel):
                    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    widget.setMinimumWidth(OCR_CONTROL_MINIMUM_WIDTH)
                layout.addWidget(widget)
        layout.addStretch(1)
        # 패턴 칸은 All 방식일 때만 보임 — 쪽에 넣으며 부모가 바뀌어도 숨은 채로 (on_ocr_mode_changed가 정함)
        self.ocrPatternLabel.setVisible(False)
        self.ocrPatternLineEdit.setVisible(False)
        return VerticalScrollArea(content)  # 패널이 낮으면 세로로 스크롤 — 창의 최소 높이를 묶지 않음

    # ------------------------------------------------------------ 여닫기
    def tool_panel_key(self):
        """열려 있는 쪽의 키 — 닫혀 있으면 None. (컨트롤이 숨은 동안에는 열려 있어도 화면에는 없음)"""
        return self._tool_panel_key

    def show_tool_panel(self, key):
        """그 쪽으로 패널을 엶. 모르는 키는 KeyError — 바꾸기 전에."""
        self.toolPanel.show_page(key)
        self._tool_panel_key = key
        self._last_tool_panel = key
        self.apply_tool_panel_state()

    def close_tool_panel(self):
        """패널을 닫음 (쪽의 위젯·상태는 그대로)."""
        self._tool_panel_key = None
        self.apply_tool_panel_state()

    def toggle_tool_page(self, key):
        """재생 줄의 토글·Tools 메뉴: 그 쪽이 열려 있으면 닫고, 아니면 그 쪽으로 엶."""
        if self._tool_panel_key == key:
            self.close_tool_panel()
        else:
            self.show_tool_panel(key)

    def toggle_tool_panel(self):
        """N 키: 열려 있으면 닫고, 닫혀 있으면 마지막에 쓰던 쪽으로 엶 (처음이면 주석)."""
        if self._tool_panel_key is not None:
            self.close_tool_panel()
        else:
            self.show_tool_panel(self._last_tool_panel)

    def apply_tool_panel_state(self):
        """패널의 보임·폭과 재생 줄 토글의 체크를 지금 상태에 맞춤: 열린 쪽이 있고 재생 줄이 숨지 않았을 때만 보임
        (모듈 설명). 여닫을 때와, 재생 줄이 숨거나 되돌아올 때(V 키·영상만 전체 화면) 불린다."""
        if self._tool_panel_key is not None and not self.transportBar.isHidden():
            self._show_tool_column()
        else:
            self._hide_tool_column()
        bar = self.transportBar
        bar.annotationButton.setChecked(self._tool_panel_key == "annotation")
        bar.ocrButton.setChecked(self._tool_panel_key == "ocr")

    def _show_tool_column(self):
        panel, splitter = self.toolPanel, self.mainSplitter
        if not panel.isHidden():
            return  # 이미 보임 — 사용자가 맞춘 폭을 건드리지 않음
        side = splitter.sizes()[0]
        panel.setVisible(True)
        if splitter.widget(0).isHidden():
            return  # 사이드바가 숨은 동안에는 setSizes를 부르지 않음 (모듈 설명의 함정)
        room = sum(splitter.sizes()) - side  # 영상 칸과 패널이 나눠 쓸 폭 (손잡이 제외)
        minimum = panel.minimumSizeHint().width()
        width = max(minimum, min(max(self._tool_panel_width, minimum), room - VIDEO_KEEP))
        # 창이 좁아 다 못 담으면 영상 칸에는 그 최소 너비를 적음(0을 적지 않음) — 스플리터가 그 안에서 맞추고, 창은
        # 레이아웃의 새 최소 너비(사이드바 + 영상 + 패널)까지 저절로 넓어짐
        video = max(splitter.widget(1).minimumSizeHint().width(), room - width)
        splitter.setSizes([side, video, width])

    def _hide_tool_column(self):
        panel = self.toolPanel
        if panel.isHidden():
            return
        width = self.mainSplitter.sizes()[2]
        if width > 0:
            self._tool_panel_width = width  # 다음에 열 때 같은 폭으로
        panel.setVisible(False)  # 폭은 스플리터가 영상 칸(늘어나는 칸)에 줌 — 사이드바는 그대로

    # ------------------------------------------------------------ 컨트롤 전체 (V 키) · 글자 (B 키)
    def toggle_controls(self):
        """V 키: 사이드바·도구 패널·슬라이더·재생 줄을 숨기고 영상 위 오버레이 컨트롤을 띄움 — 다시 누르면 되돌림.
        (도구 패널은 재생 줄을 따라 숨고 나타남 — apply_tool_panel_state)"""
        self.controls_visible = not self.controls_visible
        for widget in self.get_valid_control_widgets():
            widget.setVisible(self.controls_visible)
        if hasattr(self, 'overlayFrame'):
            if not self.controls_visible:
                self.overlayFrame.setVisible(True)
                self.overlayFrame.raise_()
                self.overlay_is_bottom_center = True  # V 키로 띄울 때는 아래 가운데에
                self.show_overlay_controls()
            else:
                self.hide_overlay_controls()

    def toggle_overlay_text(self):
        """B 키: 영상 위의 파일 이름·프레임 번호 글자를 켜고 끔."""
        self.show_overlay = not self.show_overlay
        self.update_frame()
