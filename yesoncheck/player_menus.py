"""메인 메뉴 — `PlayerMenusMixin` (`VideoPlayerBase`의 부모, 2026-11-16 UI 개편 PR 2).

Settings·Help 앞에 메뉴 다섯: **File · View · Playback · Compare · Tools**. 가운데 열을 없애며 단추가 사라진 기능
(영상 A/B 열기·작품 경로 관리 …)과, 그동안 단축키로만 닿던 기능(창에 맞춤·테마·컨트롤 숨기기 …)을 눈에 보이는 곳에 올린다.

- **항목은 지금의 처리기를 그대로 부른다** — 새 동작 없음 (`_menu_handlers`).
- **단축키는 글자로만 적는다**(`재생/일시정지 (Space)`): QAction에 단축키를 걸지 않는다. 키는 지금처럼 창의 키 처리
  (`eventFilter`·`keyPressEvent`)가 받는다 — 걸면 같은 키가 두 번 처리되거나(메뉴와 키 처리), Mac의 메뉴 막대가 키를
  가로채 한글 자판 대응(ㅍ·ㅜ·ㅔ …)·목록 포커스의 처리와 어긋난다.
- **체크·켜짐은 메뉴를 열 때 맞춘다**(`_sync_menu_states` — 메뉴의 `aboutToShow`): 반복·와이프·X/Y·패널·글자는 단추나 키로도
  바뀌므로, 바뀔 때마다 따라가지 않고 보이는 순간에 지금 상태를 읽는다. 항목을 고른 뒤에도 한 번(Qt가 체크를 먼저 뒤집음).
- 글자는 글자 표(`ui_text`) — 제목은 두 언어 모두 영어(지금의 Settings·Help처럼), 항목은 지금 언어.
- 메뉴는 창의 다른 위젯보다 **먼저** 만들어진다(`create_menu_bar` — `VideoPlayerBase.__init__` 앞부분). 그래서 처리기는
  이름을 그때 풀지 않는 람다이고, 만들 때 위젯을 건드리지 않는다.
"""

from PyQt5.QtWidgets import QAction, QMenu

from yesoncheck import ui_text

SEPARATOR = None
# (메뉴 키, 항목의 글자 표 키들 — None은 구분선)
MENUS = (
    ("file", ("menu.file.open_a", "menu.file.open_b", "menu.file.open_folder", SEPARATOR,
              "menu.file.bookmark_add", "menu.file.bookmark_manage")),
    ("view", ("menu.view.fit", "menu.view.original", "menu.view.zoom_in", "menu.view.zoom_out", SEPARATOR,
              "menu.view.fullscreen", "menu.view.video_only", "menu.view.controls", SEPARATOR,
              "menu.view.theme", "menu.view.overlay_text")),
    ("playback", ("menu.playback.play", "menu.playback.prev", "menu.playback.next", "menu.playback.first",
                  "menu.playback.last", SEPARATOR, "menu.playback.loop", SEPARATOR,
                  "menu.playback.playlist", "menu.playback.playlist_end")),
    ("compare", ("menu.compare.wipe", "menu.compare.x", "menu.compare.y")),
    ("tools", ("menu.tools.annotation", "menu.tools.ocr", "menu.tools.toggle", SEPARATOR, "menu.tools.work_paths")),
)
CHECKABLE = frozenset({"menu.view.overlay_text", "menu.playback.loop", "menu.compare.wipe", "menu.compare.x",
                       "menu.compare.y", "menu.tools.annotation", "menu.tools.ocr"})


class PlayerMenusMixin:
    def _add_main_menus(self, menubar):
        """File·View·Playback·Compare·Tools 메뉴를 menubar에 차례로 더한다 (Settings·Help보다 먼저 부를 것)."""
        handlers = self._menu_handlers()
        self.main_menus = {}  # 메뉴 키 → QMenu
        self.menu_actions = {}  # 항목의 글자 표 키 → QAction
        for menu_key, items in MENUS:
            menu = menubar.addMenu(ui_text.text("menu." + menu_key))
            menu.aboutToShow.connect(self._sync_menu_states)
            self.main_menus[menu_key] = menu
            for text_key in items:
                if text_key is SEPARATOR:
                    menu.addSeparator()
                    continue
                action = menu.addAction(ui_text.text(text_key))
                action.setMenuRole(QAction.NoRole)  # Mac: 글자(Settings·About …)를 보고 앱 메뉴로 옮기지 않게
                action.setCheckable(text_key in CHECKABLE)
                action.triggered.connect(lambda _checked=False, run=handlers[text_key]: self._run_menu_item(run))
                self.menu_actions[text_key] = action

    def _menu_handlers(self):
        """항목의 글자 표 키 → 부를 것 (지금의 처리기 — 고를 때 이름을 풂)."""
        return {
            "menu.file.open_a": lambda: self.open_file('A'),
            "menu.file.open_b": lambda: self.open_file('B'),
            "menu.file.open_folder": lambda: self.select_folder(),
            "menu.file.bookmark_add": lambda: self.add_bookmark(),
            "menu.file.bookmark_manage": lambda: self.show_bookmarks(),
            "menu.view.fit": lambda: self.videoWidget.reset_view(),
            "menu.view.original": lambda: self.videoWidget.show_original_size(),
            "menu.view.zoom_in": lambda: self.videoWidget.zoom_in(self.videoWidget.rect().center()),
            "menu.view.zoom_out": lambda: self.videoWidget.zoom_out(self.videoWidget.rect().center()),
            "menu.view.fullscreen": lambda: self.toggle_fullscreen(),
            "menu.view.video_only": lambda: self.toggle_video_only_fullscreen(),
            "menu.view.controls": lambda: self.toggle_controls(),
            "menu.view.theme": lambda: self.toggle_theme(),
            "menu.view.overlay_text": lambda: self.toggle_overlay_text(),
            "menu.playback.play": lambda: self.toggle_play_pause(),
            "menu.playback.prev": lambda: self.prev_frame(),
            "menu.playback.next": lambda: self.next_frame(),
            "menu.playback.first": lambda: self.go_to_first(),
            "menu.playback.last": lambda: self.go_to_last(),
            "menu.playback.loop": lambda: self.loopCheckBox.toggle(),
            # 꺼져 있어야 할 항목은 처리기도 막음 — 켜짐은 메뉴를 열 때만 맞추고, QAction.trigger()는 꺼진 항목도 실행함
            "menu.playback.playlist": lambda: self._playlist_can_start() and self.play_selected_files(),
            "menu.playback.playlist_end": lambda: self.is_playlist_playing and self.end_playlist(),
            "menu.compare.wipe": lambda: self.wipeCheckBox.toggle(),
            "menu.compare.x": lambda: self.wipeXButton.isEnabled() and self.wipeXButton.toggle(),
            "menu.compare.y": lambda: self.wipeYButton.isEnabled() and self.wipeYButton.toggle(),
            "menu.tools.annotation": lambda: self.toggle_tool_page("annotation"),
            "menu.tools.ocr": lambda: self.toggle_tool_page("ocr"),
            "menu.tools.toggle": lambda: self.toggle_tool_panel(),
            "menu.tools.work_paths": lambda: self.manage_work_paths(),
        }

    def _run_menu_item(self, run):
        try:
            run()
        finally:
            self._sync_menu_states()  # Qt가 체크를 먼저 뒤집어 둠 — 실제 상태로 되맞춤 (처리기가 거절했어도)

    def _sync_menu_states(self):
        """체크와 켜짐을 지금 상태에 맞춤 (메뉴를 열 때·항목을 고른 뒤)."""
        actions = self.menu_actions
        wipe_on = self.wipeCheckBox.isChecked()
        panel = self.tool_panel_key()
        checks = {
            "menu.view.overlay_text": bool(self.show_overlay),
            "menu.playback.loop": self.loopCheckBox.isChecked(),
            "menu.compare.wipe": wipe_on,
            "menu.compare.x": self.wipeXButton.isChecked(),
            "menu.compare.y": self.wipeYButton.isChecked(),
            "menu.tools.annotation": panel == "annotation",
            "menu.tools.ocr": panel == "ocr",
        }
        for text_key, on in checks.items():
            actions[text_key].setChecked(on)
        actions["menu.compare.x"].setEnabled(wipe_on)  # 재생 줄의 X·Y 단추와 같음 — 와이프를 켜야 고를 수 있음
        actions["menu.compare.y"].setEnabled(wipe_on)
        actions["menu.playback.playlist_end"].setEnabled(bool(self.is_playlist_playing))
        actions["menu.playback.playlist"].setEnabled(self._playlist_can_start())

    def _playlist_can_start(self):
        """선택 재생을 시작할 수 있는 탭인지 — Mov·All 목록의 선택으로 시작하므로 Seq 탭에서는 아님 (사이드바의 단추와 같은 규칙)."""
        return self.sidebar_tabs.currentWidget() is not self.seq_sidebar

    # ------------------------------------------------------------ 영상 영역의 우클릭 메뉴
    def build_video_context_menu(self):
        """영상 영역에서 우클릭하면 뜨는 메뉴: 메뉴 막대의 메뉴 전부(File … Help)를 하위 메뉴로 (사용자 요청 2026-11-16).
        메뉴 막대의 항목을 그대로 넣음 — 같은 메뉴 객체라 항목·체크·켜짐·처리기가 따로 놀지 않고, 하위 메뉴가 펼쳐질 때
        (`aboutToShow`)의 상태 맞춤도 그대로. 메뉴 막대가 보이지 않을 때(영상만 전체 화면)에도 모든 기능에 닿는 길."""
        menu = QMenu(self)
        menu.addActions(self.menuBar().actions())
        return menu

    def show_video_context_menu(self, position):
        """영상 영역(뷰포트 좌표 position)에 우클릭 메뉴를 띄움."""
        menu = self.build_video_context_menu()
        try:
            menu.exec_(self.videoWidget.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def retranslate_main_menus(self):
        """글자 표에서 메뉴 제목·항목 글자를 다시 읽음 (언어가 바뀐 뒤)."""
        for menu_key, menu in self.main_menus.items():
            menu.setTitle(ui_text.text("menu." + menu_key))
        for text_key, action in self.menu_actions.items():
            action.setText(ui_text.text(text_key))
