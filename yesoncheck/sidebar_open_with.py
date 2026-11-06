"""사이드바 우클릭 '다른 앱으로 열기' 믹스인 (SidebarOpenWithMixin) — Mov·Seq·All 메뉴 맨 아래에 붙는 무리:

  ─────
  QuickTime Player로 열기 (n개)     Mac만. 고른 것 중 영상만 넘김 — 영상이 없으면 꺼짐
  다른 앱으로 열기 (n개) ▸          DJV …               등록한 앱마다 (지금 없으면 '(찾을 수 없음)'으로 꺼짐, 툴팁 = 경로)
                                   ─────
                                   앱 등록…            Mac .app / Windows .exe를 고름 → 이 PC의 prefs.json (open_with)
                                   앱 지우기 ▸ DJV …

넘기는 파일(목록 순서): 영상은 경로, 시퀀스는 첫 프레임 파일. 세 목록 모두 메뉴를 연 항목이 고른 것 밖이면 그 항목만 고른 상태로 맞춘
뒤 고른 항목(show_*_context_menu — 같은 메뉴의 다른 동작과 같은 선택). 넘길 것은 메뉴를 만들 때 정함 — All 메뉴가 원본 목록에 비춘
선택은 쓰지 않음(All의 선택 그대로). 시퀀스는 SeqInfo로 들고 있다가 누를 때 sequence_source.first_frame_path로 실제 파일을 찾음 —
SeqInfo의 확장자는 늘 소문자라 `.TGA` 프레임은 대소문자를 가리는 NFS에서 그대로 이어 붙인 이름으로는 없는 파일(메뉴를 만들 때는 NAS를
읽지 않음). 등록한 앱이 있는지는 메뉴를 만들 때마다 GUI 스레드에서 봄(앱마다 stat 한 번 — 네트워크 위의 앱이 끊겼으면 그동안 멈춤, 알고 둠).

띄우기 전에: 지금 없는 파일이 있으면 띄우지 않고 오류 창(어느 파일인지), OPEN_CONFIRM_COUNT개를 넘으면 물음(앱 창이 파일마다 뜰 수
있음). 띄우기·등록·지우기 실패(open_with의 RuntimeError·OSError·ValueError, 설정 파일의 UserFileError·잠금 TimeoutError)는 트레이스백째
오류 창(error_window.show_unexpected) — 조용히 넘기지 않음. 설정 파일을 읽지 못하면 하위 메뉴 첫 줄이 꺼진 '설정 파일을 읽지 못했습니다'
(툴팁에 사유, 기록에 트레이스백) — 메뉴를 만드는 동안 모달을 띄우지 않음; '앱 등록…'을 누르면 같은 오류가 창으로.
Mac·Windows가 아니면 무리를 붙이지 않음. 플랫폼은 메뉴를 만들 때 sys.platform을 읽음 (시험이 바꿈).
"""

import os
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from yesoncheck import error_window, open_with, sequence_source
from yesoncheck.sidebar_items import ALL_KIND_ROLE
from yesoncheck.user_files import UserFileError

LOG_PREFIX = "[다른 앱으로 열기]"
OTHER_APPS_TEXT = "다른 앱으로 열기"
REGISTER_TEXT = "앱 등록…"
REMOVE_TEXT = "앱 지우기"
NO_APPS_TEXT = "(등록한 앱 없음)"
PREFS_PROBLEM_TEXT = "설정 파일을 읽지 못했습니다"
OPEN_CONFIRM_COUNT = 20  # 이보다 많이 열면 먼저 물음
APP_PICK_FILTERS = {"darwin": "앱 (*.app)", "win32": "프로그램 (*.exe)"}
FAILURES = (OSError, RuntimeError, ValueError, UserFileError, TimeoutError)  # UserFileError는 OSError가 아님 — 따로 적음


def _with_count(text, count):
    return f"{text} ({count}개)" if count > 1 else text


def _first_frame_name(seq):
    """누르기 전·없을 때 알릴 이름 (실제 파일은 sequence_source.first_frame_path)."""
    return os.path.join(seq.dir, seq.frame_name(seq.first))


class SidebarOpenWithMixin:
    """VideoPlayer 사이드바 메뉴의 '다른 앱으로 열기' 무리 (모듈 설명)."""

    # ---------------------------------------------------------------- 넘길 것 [("mov", 경로) 또는 ("seq", SeqInfo)]

    def _mov_open_entries(self):
        """Mov 목록: 고른 항목(목록 순서 — show_sidebar_context_menu가 메뉴를 연 줄을 고른 상태로 맞춤)."""
        widget = self.sidebar
        return [("mov", widget.item(i).data(Qt.UserRole)) for i in range(widget.count()) if widget.item(i).isSelected()]

    def _seq_open_entries(self):
        return [("seq", item.data(Qt.UserRole)) for item in self._selected_seq_items()]

    def _all_open_entries(self):
        widget = self.all_sidebar
        entries = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item.isSelected():
                if item.data(ALL_KIND_ROLE) == "seq":
                    entries.append(("seq", item.data(Qt.UserRole)))
                else:
                    entries.append(("mov", item.data(Qt.UserRole)))
        return entries

    # ---------------------------------------------------------------- 메뉴

    def _add_open_with_actions(self, menu, entries):
        """menu 끝에 구분선 + 'QuickTime Player로 열기'(Mac) + '다른 앱으로 열기 ▸'. entries: [(종류, 경로)] (목록 순서)."""
        platform = sys.platform
        if platform not in open_with.APP_SUFFIX or not entries:
            return
        movies = [entry for entry in entries if entry[0] == "mov"]
        menu.addSeparator()
        menu.setToolTipsVisible(True)
        if open_with.quicktime_available(platform):
            action = menu.addAction(_with_count(f"{open_with.QUICKTIME_LABEL}로 열기", len(movies)))
            action.triggered.connect(lambda: self._open_entries_with(None, movies))
            if not movies:
                action.setEnabled(False)
                action.setToolTip("고른 것이 시퀀스뿐입니다 — 등록한 앱으로 여세요")
            elif len(movies) < len(entries):
                action.setToolTip("시퀀스는 넘기지 않습니다 (영상만)")
        submenu = menu.addMenu(_with_count(OTHER_APPS_TEXT, len(entries)))
        submenu.setToolTipsVisible(True)
        self._fill_open_with_menu(submenu, entries, platform)

    def _fill_open_with_menu(self, submenu, entries, platform):
        try:
            apps = open_with.registered_apps(platform)
        except FAILURES as exc:
            print(f"{LOG_PREFIX} {PREFS_PROBLEM_TEXT}: {open_with.prefs_path(platform)}\n{traceback.format_exc()}",
                  file=sys.stderr, flush=True)
            problem = submenu.addAction(PREFS_PROBLEM_TEXT)
            problem.setEnabled(False)
            problem.setToolTip(f"{type(exc).__name__}: {exc}")
            apps = None
        if apps == []:
            submenu.addAction(NO_APPS_TEXT).setEnabled(False)
        for app in apps or []:
            label = open_with.app_label(app)
            missing = open_with.app_missing(app, platform)
            action = submenu.addAction(f"{label} (찾을 수 없음)" if missing else label)
            action.setToolTip(app)
            action.setEnabled(not missing)
            action.triggered.connect(lambda _checked=False, app=app: self._open_entries_with(app, entries))
        submenu.addSeparator()
        submenu.addAction(REGISTER_TEXT).triggered.connect(lambda: self._register_open_with_app(platform))
        if apps:
            remove = submenu.addMenu(REMOVE_TEXT)
            remove.setToolTipsVisible(True)
            for app in apps:
                action = remove.addAction(open_with.app_label(app))
                action.setToolTip(app)
                action.triggered.connect(lambda _checked=False, app=app: self._remove_open_with_app(app, platform))

    # ---------------------------------------------------------------- 동작

    def _open_entries_with(self, app, entries):
        """app(None = QuickTime Player)으로 entries를 엶 (모듈 설명의 '띄우기 전에'·실패 규칙)."""
        label = open_with.QUICKTIME_LABEL if app is None else open_with.app_label(app)
        files, missing = [], []
        try:
            for kind, value in entries:
                if kind == "mov":
                    (files if os.path.exists(value) else missing).append(value)
                    continue
                try:
                    files.append(sequence_source.first_frame_path(value))
                except FileNotFoundError:
                    missing.append(_first_frame_name(value))
        except FAILURES:  # 시퀀스 폴더를 읽지 못함 (권한·NAS 끊김 — first_frame_path가 폴더를 읽을 때)
            error_window.show_unexpected(LOG_PREFIX, f"{label}(으)로 열 시퀀스의 첫 프레임을 찾지 못했습니다")
            return
        if missing:
            listed = "\n".join(missing[:10]) + (f"\n… 외 {len(missing) - 10}개" if len(missing) > 10 else "")
            error_window.show_error(LOG_PREFIX, f"{label}(으)로 열지 않았습니다 — 지금 없는 파일이 있습니다 ({len(missing)}개):\n{listed}")
            return
        if len(files) > OPEN_CONFIRM_COUNT:
            answer = QMessageBox.question(self, OTHER_APPS_TEXT, f"파일 {len(files)}개를 {label}(으)로 엽니다. 계속할까요?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        try:
            if app is None:
                open_with.open_with_quicktime(files)
            else:
                open_with.open_with_app(app, files)
        except open_with.DllDirectoryRestoreError:
            error_window.show_unexpected(LOG_PREFIX, f"{label}(으)로 열었지만 이 창의 DLL 검색 경로를 되돌리지 못했습니다 — "
                                                     "이 창에서 나중에 불러오는 기능(OCR·애니매틱2 등)이 실패할 수 있으니 YesonCheck를 다시 켜세요")
            return
        except FAILURES:
            error_window.show_unexpected(LOG_PREFIX, f"{label}(으)로 열지 못했습니다 (파일 {len(files)}개, 첫 파일 {files[0]})")
            return
        print(f"{LOG_PREFIX} {label}: 파일 {len(files)}개 — {files[0]}", flush=True)

    def _register_open_with_app(self, platform):
        start = "/Applications" if platform == "darwin" else os.environ.get("ProgramFiles", "")
        app, _filter = QFileDialog.getOpenFileName(self, f"{OTHER_APPS_TEXT} — 앱 고르기", start, APP_PICK_FILTERS[platform])
        if not app:
            return
        app = os.path.normpath(app)
        try:
            open_with.add_app(app, platform)
        except FAILURES:
            error_window.show_unexpected(LOG_PREFIX, f"앱을 등록하지 못했습니다: {app}")
            return
        print(f"{LOG_PREFIX} 앱 등록: {app} ({open_with.prefs_path(platform)})", flush=True)

    def _remove_open_with_app(self, app, platform):
        try:
            open_with.remove_app(app, platform)
        except FAILURES:
            error_window.show_unexpected(LOG_PREFIX, f"등록한 앱을 지우지 못했습니다: {app}")
            return
        print(f"{LOG_PREFIX} 앱 지움: {app}", flush=True)
