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
- **키 넷은 이 모듈의 표로 받는다**(`KEY_SHORTCUTS` — O 영상 A 열기 · I 폴더 열기 · L 반복 재생 · W 와이프 켜기, 한글 자판의
  같은 자리 ㅐ·ㅑ·ㅣ·ㅈ도; 사용자 요청 2026-11-16): 창의 키 처리 두 곳이 `run_key_shortcut(event)`를 부르고, 하는 일은 그 메뉴
  항목의 처리기 그대로. 메뉴 막대에 없는 일의 키는 `ITEM_KEY_SHORTCUTS`(C = 사이드바 우클릭의 '파일 복사', 한글 ㅊ —
  2026-11-18)로 같은 규칙에 받음. 다른 키(Space·← → …)는 예전부터 키 처리 코드에 직접 있음.
- 메뉴는 창의 다른 위젯보다 **먼저** 만들어진다(`create_menu_bar` — `VideoPlayerBase.__init__` 앞부분). 그래서 처리기는
  이름을 그때 풀지 않는 람다이고, 만들 때 위젯을 건드리지 않는다.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAction, QMenu

from yesoncheck import error_window, ui_text

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
# 이 표로 받는 단축키: (Qt 키, 한글 자판의 같은 자리 글자, 항목의 글자 표 키) — 항목의 글자 끝에 같은 키를 적음(`(O)`)
KEY_SHORTCUTS = (
    (Qt.Key_O, "ㅐ", "menu.file.open_a"),
    (Qt.Key_I, "ㅑ", "menu.file.open_folder"),
    (Qt.Key_L, "ㅣ", "menu.playback.loop"),
    (Qt.Key_W, "ㅈ", "menu.compare.wipe"),
)
# 메뉴 막대에 없는 일의 단축키: (Qt 키, 한글 자판 글자, 그 일의 글자 표 키 — 오류 알림용, 처리기 이름) — 받는 규칙은 위 표와 같음
# (사이드바 우클릭 메뉴의 일 — 사용자 요청 2026-11-18; 지금 탭을 따르는 처리는 sidebar_keys. 비디오 A·B 열기는 [ ] — 와이프의 왼쪽·
#  오른쪽: B는 파일 이름 글자 키, O는 메뉴 막대의 파일 고르기 창이라 쓰지 않음 — 사용자 결정; [ ]는 한글 자판에서도 같은 글자)
ITEM_KEY_SHORTCUTS = (
    (Qt.Key_C, "ㅊ", "side_menu.copy", "copy_files_for_key"),
    (Qt.Key_J, "ㅓ", "side_menu.merge", "merge_videos_for_key"),
    (Qt.Key_M, "ㅡ", "side_menu.info", "show_media_info_for_key"),
    (Qt.Key_R, "ㄱ", "side_menu.thumbnails", "regenerate_thumbnails_for_key"),
    (Qt.Key_BracketLeft, "[", "side_menu.open_a", "open_in_a_for_key"),
    (Qt.Key_BracketRight, "]", "side_menu.open_b", "open_in_b_for_key"),
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

    def run_key_shortcut(self, event):
        """키 이벤트가 `KEY_SHORTCUTS`의 키면 그 메뉴 항목의 처리기를 부르고 True, 아니면 아무것도 안 하고 False.
        창의 키 처리 두 곳(`keyPressEvent`, 목록·창이 받는 `eventFilter`)이 부름.

        - Ctrl·Alt·Meta와 함께 누른 키는 아님 (Ctrl+O는 오버레이 컨트롤 위치 되돌리기 — 예전 그대로).
        - 누르고 있을 때의 자동 반복은 삼킴(True — 처리기는 부르지 않음): 반복·와이프가 깜빡이거나 파일 창이 거듭 뜨지 않게.
        - 글자를 치는 칸(프레임 번호·주석 글·OCR 패턴)은 친 글자를 자기가 받아 창까지 오지 않음.
        - 처리기의 예외는 여기서 받아 알림(기록 + 오류 창)하고 True: 가상 함수 안이라 새어 나가면 Qt가 같은 키를 다음 처리
          (`eventFilter` → `keyPressEvent`)로 넘겨 처리기가 한 번 더 돌거나(빌드 앱), 프로세스가 끝남(소스 실행)."""
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        key, text = event.key(), event.text()
        for qt_key, hangul, text_key, run in self._key_shortcut_runs():
            if key == qt_key or text == hangul:
                if not event.isAutoRepeat():
                    try:
                        run()
                    except BaseException:
                        error_window.report_from_handler(
                            "[단축키]", f"단축키 {chr(qt_key)}의 동작을 하다가 오류가 났습니다 — {ui_text.text(text_key)}")
                return True
        return False

    def _key_shortcut_runs(self):
        """(Qt 키, 한글 글자, 글자 표 키, 부를 함수) — 메뉴 항목의 키(`KEY_SHORTCUTS`)와 메뉴 막대에 없는 일의 키(`ITEM_KEY_SHORTCUTS`).
        처리기는 부를 때 찾음 — 다른 키(Space·화살표 …)마다 찾지 않고, 찾다가 난 오류도 run_key_shortcut의 try 안에서 알림."""
        for qt_key, hangul, text_key in KEY_SHORTCUTS:
            yield qt_key, hangul, text_key, lambda text_key=text_key: self._run_menu_item(self._menu_handlers()[text_key])
        for qt_key, hangul, text_key, name in ITEM_KEY_SHORTCUTS:
            yield qt_key, hangul, text_key, lambda name=name: getattr(self, name)()

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
