"""북마크 믹스인 (SidebarBookmarksMixin): 북마크 파일(`~/.yeson_bookmarks.json`) 읽기·더하기·지우기와 북마크 관리 대화 상자,
북마크 폴더 열기(영상 불러오기 + 그 폴더의 썸네일 폴더 설정).

북마크 관리 창(`BookmarkDialog` — Bookmarks 단추, P 키 — 한글 자판 ㅔ)의 경로는 DJV처럼 그 자리에서 고침: 고른 항목을 다시
클릭하거나(SelectedClicked) 우클릭 → 경로 수정으로 편집기를 열고(더블클릭·Enter는 그대로 폴더 열기 — EditKeyPressed는 켜지 않음:
Mac에서 Enter가 편집기를 열어 예전 습관이 깨짐), 고친 경로는 commit되는 즉시 북마크 파일에 반영(`bookmarks.replace` — 자리 유지,
다른 창의 것은 남김)되어 '폴더 열기'·다음에 열 때 모두 고친 경로를 씀. 손으로 친 글은 `typed_path`로 정리(공백·`~`·끝 구분자).
편집기의 포커스 규칙(`_BookmarkPathDelegate`): Enter·창 안의 다른 곳 클릭·창 닫기(`BookmarkDialog.done`)는 저장, Esc는 취소,
**다른 앱으로 갔다 와도 편집기는 그대로**(Finder에서 경로를 복사해 오는 동안 반쯤 친 글이 저장되지 않게 — Qt 기본은 앱 비활성의
FocusOut에도 commit함). 편집기가 열린 채 단추·메뉴를 누르면 먼저 commit(`commit_bookmark_edit` — Mac은 단추가 포커스를
가져가지 않아 편집기가 저절로 닫히지 않음)하고, 거부된 편집(이미 있는 경로·파일 실패)이면 옛 경로로 열거나 지우지 않고 멈춤.
우클릭 메뉴(`bookmark_context_menu`): 경로 복사·경로 수정·폴더 열기·삭제.

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin, SidebarRefreshMixin, SidebarThumbnailsMixin)`. 그래서
VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin 앞)에 오고, 이 메서드들의 이름은 다른 믹스인·
VideoPlayerBase와 겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.bookmarks`·`self.bookmarks_file`·
`self.current_thumbnail_folder` 등)는 예전처럼 VideoPlayerBase.__init__이 만들고(`load_bookmarks`도 거기서 부름), 폴더 불러오기·썸네일·
스레드 정리는 PlayerSidebarMixin 등 다른 믹스인의 메서드를 `self.`로 불러 그대로 닿음.

player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
시험이 북마크 대화 상자의 `QDialog.exec_`를 바꿔칠 때 문자열 경로는 이 모듈 이름으로 적음: `yesoncheck.sidebar_bookmarks.QDialog.exec_`.
"""

import os
import sys
import traceback

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
)

from yesoncheck import bookmarks, error_window, paths, thumbnails
from yesoncheck.user_files import UserFileError

# 다른 앱으로 갔다(ActiveWindow) 오거나 팝업이 떠도(Popup) 편집기를 닫지 않는 포커스 이동 사유
_KEEP_EDITOR_FOCUS_REASONS = (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason)


def typed_path(text):
    """관리 창에서 손으로 친 경로를 저장할 모양으로: 앞뒤 공백·감싼 따옴표(Windows 탐색기 '경로로 복사') 제거, `~` 풀기,
    구분자·`..`·끝의 구분자 정리 (빈 글은 빈 글). 처음부터 적었는지(절대 경로)는 보지 않음 — 부르는 쪽이 os.path.isabs로."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return paths.normalize_native(os.path.normpath(os.path.expanduser(text))) if text else ""


def _same_folder(a, b):
    """두 경로가 같은 폴더인지 — 끝의 구분자·`..` 차이는 무시(normpath), 그 밖은 paths.path_key(Windows: 대소문자·드라이브)."""
    return paths.path_key(os.path.normpath(a)) == paths.path_key(os.path.normpath(b))


def _open_editor(list_widget):
    """열려 있는 편집기와 그 행 → (row, editor), 없으면 (None, None). (`indexWidget`이 열린 편집기를 줌.)"""
    model = list_widget.model()
    for row in range(list_widget.count()):
        editor = list_widget.indexWidget(model.index(row, 0))
        if editor is not None:
            return row, editor
    return None, None


def commit_bookmark_edit(list_widget):
    """열려 있는 편집기의 글을 항목에 반영(→ itemChanged → 파일)하고 닫음. 편집기가 없거나, 글을 고치지 않았거나, 빈 글이거나,
    고친 글이 받아들여졌으면 True; 되돌려졌으면(이미 있는 경로·경로 형식·파일 실패 — 알림은 이미 띄웠음) False.

    단추·메뉴·창 닫기가 편집 중인 경로를 그대로 쓰게 — Mac은 단추가 포커스를 가져가지 않아 편집기가 저절로 닫히지 않음.
    (`commitData`·`closeEditor`는 보호 메서드이나 Python에서 만든 QListWidget이라 부를 수 있음.) 글을 고치지 않은 편집기(느린
    더블클릭)는 끝에 구분자가 붙어 저장된 경로처럼 정리한 글이 저장된 글과 달라도 거부가 아님 — itemChanged가 나지 않음.
    """
    row, editor = _open_editor(list_widget)
    if editor is None:
        return True
    QApplication.inputMethod().commit()  # 한글 등 조합 중인 글자를 편집기에 넣음 (단추 클릭은 포커스를 안 옮겨 저절로 안 됨)
    item = list_widget.item(row)
    raw, before = editor.text(), item.text()
    typed = typed_path(raw)
    list_widget.commitData(editor)
    list_widget.closeEditor(editor, QAbstractItemDelegate.NoHint)
    return raw == before or not typed or item.data(Qt.UserRole) == typed


def revert_bookmark_edit(list_widget):
    """열려 있는 편집기를 글을 버리고 닫음 (업데이트가 창을 닫을 때 — 반쪽 글을 저장하거나 모달을 띄우지 않게)."""
    row, editor = _open_editor(list_widget)
    if editor is not None:
        list_widget.closeEditor(editor, QAbstractItemDelegate.RevertModelCache)


def _report_unexpected(context):
    """(except 블록 안) PyQt5 가상 함수(eventFilter·done)에서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음) — 바로 기록하고
    오류 창은 Qt 루프에서 (error_window.report_from_handler — 알리다 또 실패해도 내보내지 않음)."""
    error_window.report_from_handler("[북마크]", context)


class _BookmarkPathDelegate(QStyledItemDelegate):
    """관리 창 편집기의 포커스 규칙: 다른 앱으로 갔다 와도 편집기를 닫지 않음(Cmd+Tab으로 Finder에서 경로를 복사해 오는 동안 반쯤 친
    경로가 저장되지 않게). 창 안의 다른 곳 클릭(MouseFocusReason 등)·Enter는 저장, Esc는 취소 — Qt 기본 그대로."""

    def eventFilter(self, editor, event):
        try:
            if event.type() == QEvent.FocusOut and event.reason() in _KEEP_EDITOR_FOCUS_REASONS:
                return False
            return super().eventFilter(editor, event)
        except BaseException:
            _report_unexpected("북마크 관리 창의 편집기 이벤트를 처리하지 못했습니다")
            return False


class BookmarkDialog(QDialog):
    """북마크 관리 창. 닫힐 때(닫기 단추·X·Esc — 모두 done()을 지남) 고치던 경로가 있으면 먼저 반영 (편집기 안의 Esc는 편집만 취소).
    다른 창의 업데이트가 닫을 때(`close_for_update` — 창의 `_closing_for_update`)는 반쪽 글을 저장하거나 모달을 띄우지 않고 편집을 버림
    (모달에 막힌 창은 닫히지 않아 업데이트가 90초 뒤 멈춤)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.list_widget = None  # show_bookmarks가 만든 뒤 넣음

    def done(self, result):
        try:
            if self.list_widget is not None:
                if getattr(self.parent(), "_closing_for_update", False):
                    revert_bookmark_edit(self.list_widget)
                else:
                    commit_bookmark_edit(self.list_widget)  # 거부된 편집은 이미 되돌리고 알렸음 — 창은 닫음
        except BaseException:
            _report_unexpected("북마크 관리 창을 닫으며 고치던 경로를 반영하지 못했습니다")
        super().done(result)


class SidebarBookmarksMixin:
    """VideoPlayer의 북마크 — 파일 읽기·더하기·지우기, 관리 대화 상자, 북마크 폴더 열기."""

    def load_bookmarks(self):
        """북마크 파일을 읽어 self.bookmarks에. 읽지 못하면 빈 목록 + 기록(스택 트레이스) + 창 (파일은 건드리지 않음).

        시작할 때 불리므로 창은 show_user_file_problems가 창을 보인 뒤에 알림.
        """
        try:
            self.bookmarks = bookmarks.load(self.bookmarks_file)
        except UserFileError as exc:
            traceback.print_exc()
            self.bookmarks = []
            self._report_user_file_problem("bookmarks-read", "북마크 파일을 읽지 못함", self._bookmarks_problem_text(exc))

    def _bookmarks_problem_text(self, exc):
        detail = str(exc) if isinstance(exc, UserFileError) else f"{self.bookmarks_file}\n{type(exc).__name__}: {exc}"
        return f"북마크를 읽거나 바꾸지 못했습니다 (북마크 파일은 그대로 둡니다):\n{detail}\n\n파일을 고치거나 옮긴 뒤 다시 시도해 주세요."

    def _refresh_bookmarks(self):
        """다른 창이 그동안 더하거나 지웠을 수 있으므로 북마크 파일을 다시 읽어 self.bookmarks에. 읽지 못하면 창 + False."""
        try:
            self.bookmarks = bookmarks.load(self.bookmarks_file)
        except UserFileError as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "북마크 파일을 읽지 못함", self._bookmarks_problem_text(exc))
            return False
        return True

    def _change_bookmarks(self, change, folders):
        """folders를 차례로 북마크 파일에 반영하고 (change: bookmarks.add 또는 bookmarks.remove) self.bookmarks를 합친 목록으로.

        읽지 못한 파일(UserFileError)은 덮어 지우지 않고, 잠그지 못하거나(TimeoutError) 쓰지 못한(OSError) 경우와 함께
        기록 + 창으로 알리고 False.
        """
        try:
            for folder in folders:
                self.bookmarks = change(self.bookmarks_file, folder)
        except (UserFileError, TimeoutError, OSError) as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "북마크를 바꾸지 못함", self._bookmarks_problem_text(exc))
            return False
        return True

    def add_dropped_folders_to_bookmarks(self, folder_paths):
        """끌어다 놓은 폴더를 북마크에 자동 추가 (파일을 다시 읽고 더함)."""
        before = list(self.bookmarks)
        if not self._change_bookmarks(bookmarks.add, folder_paths):
            return
        for folder_path in folder_paths:
            if not paths.contains_path(before, folder_path):
                print(f"폴더가 북마크에 자동 추가됨: {folder_path}")

        # 사용자에게 알림 (폴더가 여러 개인 경우에만)
        if len(folder_paths) > 1:
            QMessageBox.information(self, "북마크 추가", f"{len(folder_paths)}개의 폴더가 북마크에 자동으로 추가되었습니다.")

    def add_bookmark(self):
        # 현재 폴더를 북마크에 추가
        if not self._refresh_bookmarks():  # 읽지 못하는 파일이면 폴더를 고르게 하기 전에 알림
            return
        folder_path = QFileDialog.getExistingDirectory(self, "북마크할 폴더 선택")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            if not self._refresh_bookmarks():  # 고르는 동안 다른 창이 바꿨을 수 있음
                return
            if not paths.contains_path(self.bookmarks, folder_path):
                if not self._change_bookmarks(bookmarks.add, [folder_path]):
                    return
                QMessageBox.information(self, "북마크 추가", f"{folder_path}\n폴더가 북마크에 추가되었습니다.")
            else:
                QMessageBox.information(self, "이미 북마크됨", f"{folder_path}\n폴더는 이미 북마크에 있습니다.")

    def show_bookmarks(self):
        if not self._refresh_bookmarks():  # 다른 창이 바꾼 것까지 보이게 열 때마다 다시 읽음
            return
        if not self.bookmarks:
            QMessageBox.information(self, "북마크 없음", "저장된 북마크가 없습니다.")
            return
        
        # 북마크 선택 다이얼로그 생성
        dialog = BookmarkDialog(self)
        dialog.setWindowTitle("북마크 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("북마크된 폴더 목록:")
        layout.addWidget(label)
        
        # 북마크 리스트 — 경로를 그 자리에서 고칠 수 있음(DJV식): 고른 항목을 다시 클릭(SelectedClicked)하거나 우클릭 → 경로 수정.
        # 편집 트리거는 그것뿐 — 더블클릭·Enter는 폴더 열기 그대로(EditKeyPressed를 켜면 Mac에서 Enter가 편집기를 엶). Qt는 SelectedClicked
        # 편집을 더블클릭 간격만큼 미뤘다가 더블클릭이 오면 취소하는데 그 취소는 doubleClicked 신호 뒤라, 열기를 Qt 루프로 미뤄
        # (singleShot 0) 열기의 0.5초 대기 동안 편집 타이머가 터져 닫히는 창에 편집기가 열리지 않게 함. itemChanged는 항목을 다 넣은 뒤에 이음.
        list_widget = QListWidget()
        for bookmark in self.bookmarks:
            list_widget.addItem(self._bookmark_item(bookmark))
        list_widget.setEditTriggers(QAbstractItemView.SelectedClicked)
        list_widget.setItemDelegate(_BookmarkPathDelegate(list_widget))
        list_widget.itemChanged.connect(lambda item: self._bookmark_item_edited(list_widget, item))
        dialog.list_widget = list_widget
        list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        list_widget.customContextMenuRequested.connect(lambda pos: self._show_bookmark_context_menu(list_widget, dialog, pos))
        layout.addWidget(list_widget)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 폴더 열기 버튼
        open_button = QPushButton("폴더 열기")
        open_button.clicked.connect(lambda: self.open_bookmark_folder(list_widget, dialog))
        button_layout.addWidget(open_button)
        
        # 삭제 버튼
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(lambda: self.delete_bookmark(list_widget))
        button_layout.addWidget(delete_button)
        
        # 닫기 버튼 (reject → done: 고치던 경로를 먼저 반영 — BookmarkDialog)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.reject)
        button_layout.addWidget(close_button)

        # 단추는 클릭으로 포커스를 가져가지 않음(Mac 기본과 같게): 포커스를 가져가는 스타일(Windows·Fusion)에서는 누르는 순간 편집기가
        # 먼저 닫혀(FocusOut commit) 거부된 편집을 모른 채 옛 경로를 열게 됨 — 모든 플랫폼이 clicked의 commit_bookmark_edit 길을 타게
        for button in (open_button, delete_button, close_button):
            button.setFocusPolicy(Qt.TabFocus)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        # 더블클릭으로도 폴더 열기 가능 (Qt 루프로 미룸 — 위 설명)
        list_widget.itemDoubleClicked.connect(
            lambda item: QTimer.singleShot(0, lambda: self.open_bookmark_folder(list_widget, dialog)))
        
        dialog.exec_()

    def open_bookmark_folder(self, list_widget, dialog):
        """선택된 북마크 폴더를 엽니다 (고치던 경로가 있으면 먼저 반영 — 그 경로를 엶; 거부된 편집이면 옛 경로를 열지 않고 멈춤)"""
        if not self._commit_bookmark_edit(list_widget):
            return
        current_item = list_widget.currentItem()
        if current_item:
            folder_path = current_item.text()
            
            # 기존 백그라운드 스레드들을 안전하게 정리
            self.cleanup_background_threads()
            
            # 스레드 정리 후 추가 대기 시간
            import time
            time.sleep(0.5)
            
            # UI 업데이트 처리
            QApplication.processEvents()
            
            self.load_videos_from_folder(folder_path)
            # 북마크 폴더는 해당 폴더에 썸네일 생성
            self.setup_thumbnail_folder_for_bookmark(folder_path)
            self.schedule_background_thumbnail_loading()
            dialog.close()

    # ---- 경로 그 자리에서 고치기 · 우클릭 메뉴 ----

    @staticmethod
    def _bookmark_item(path):
        """관리 창의 항목: 편집 가능, 고치기 전 경로를 UserRole에 기억 (itemChanged 때 무엇을 무엇으로 바꾸는지)."""
        item = QListWidgetItem(path)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setData(Qt.UserRole, path)
        return item

    @staticmethod
    def _set_bookmark_item(list_widget, item, path):
        """항목의 글과 기억해 둔 경로를 path로 — itemChanged를 다시 부르지 않게 (되돌리기·정리한 글 넣기)."""
        blocked = list_widget.blockSignals(True)
        try:
            item.setText(path)
            item.setData(Qt.UserRole, path)
        finally:
            list_widget.blockSignals(blocked)

    @staticmethod
    def _commit_bookmark_edit(list_widget):
        """열려 있는 편집기의 글을 반영하고 닫음 → 받아들여졌으면 True (모듈의 commit_bookmark_edit)."""
        return commit_bookmark_edit(list_widget)

    def _bookmark_item_edited(self, list_widget, item):
        """관리 창에서 경로를 고친 뒤(편집기 commit → itemChanged): 북마크 파일에 바로 반영하고 self.bookmarks를 합친 목록으로.

        친 글은 typed_path로 정리. 빈 글은 되돌림(알림 없음). 처음부터 적지 않은 경로(절대 경로 아님)·이미 있는 경로(끝 구분자만 다른 것도)로 고치면 알림 + 되돌림. 파일을
        읽거나 쓰지 못하면(깨짐·잠금·권한) 기록 + 창 + 되돌림(파일은 덮지 않음). 고친 폴더가 지금 없으면(오타·떨어진 공유) 저장은 하고
        경고 — 조용히 받지도, 막지도 않음.
        """
        old = item.data(Qt.UserRole)
        new = typed_path(item.text())
        if not new:
            self._set_bookmark_item(list_widget, item, old)
            return
        if not os.path.isabs(new):
            self._set_bookmark_item(list_widget, item, old)
            QMessageBox.information(self, "경로 형식", f"{new}\n폴더 경로는 처음부터(절대 경로) 적어 주세요.")
            return
        if new == old:
            self._set_bookmark_item(list_widget, item, old)  # 글만 정리(공백 등)
            return
        if not self._refresh_bookmarks():  # 다른 창이 바꿨을 수 있고, 읽지 못하는 파일은 덮지 않음
            self._set_bookmark_item(list_widget, item, old)
            return
        if any(_same_folder(folder, new) for folder in self.bookmarks if not _same_folder(folder, old)):
            self._set_bookmark_item(list_widget, item, old)
            QMessageBox.information(self, "이미 북마크됨", f"{new}\n폴더는 이미 북마크에 있습니다.")
            return
        if not self._change_bookmarks(lambda path, folder: bookmarks.replace(path, old, folder), [new]):
            self._set_bookmark_item(list_widget, item, old)
            return
        self._set_bookmark_item(list_widget, item, new)
        print(f"북마크 경로 고침: {old} → {new}")
        if not os.path.isdir(new):
            QMessageBox.warning(
                self,
                "폴더를 찾을 수 없음",
                f"{new}\n고친 경로를 북마크에 저장했지만 지금 이 폴더를 찾을 수 없습니다 (오타이거나 공유가 연결되지 않았을 수 있음).",
            )

    def bookmark_context_menu(self, list_widget, dialog):
        """고른 북마크의 우클릭 메뉴: 경로 복사·경로 수정·폴더 열기·삭제 (띄우는 것은 부르는 쪽 — 시험은 항목을 바로 누름)."""
        menu = QMenu(list_widget)
        item = list_widget.currentItem()
        if item is None:
            return menu
        menu.addAction("경로 복사").triggered.connect(lambda: QApplication.clipboard().setText(item.text()))
        menu.addAction("경로 수정").triggered.connect(lambda: list_widget.editItem(item))
        menu.addSeparator()
        menu.addAction("폴더 열기").triggered.connect(lambda: self.open_bookmark_folder(list_widget, dialog))
        menu.addAction("삭제").triggered.connect(lambda: self.delete_bookmark(list_widget))
        return menu

    def _show_bookmark_context_menu(self, list_widget, dialog, pos):
        item = list_widget.itemAt(pos)
        if item is None:
            return
        if not self._commit_bookmark_edit(list_widget):
            return
        list_widget.setCurrentItem(item)
        menu = self.bookmark_context_menu(list_widget, dialog)
        menu.exec_(list_widget.viewport().mapToGlobal(pos))
        menu.deleteLater()  # 창(과 목록)은 창이 사는 동안 남으므로 메뉴를 그때마다 지움

    def setup_thumbnail_folder_for_bookmark(self, folder_path):
        """북마크 폴더용 썸네일 폴더를 설정합니다."""
        self._thumbnail_folder_problem = None  # 전에 연 job의 썸네일 폴더 문제는 이제 상관없음
        try:
            thumbnail_folder = thumbnails.ensure_folder(folder_path)
            self.current_thumbnail_folder = thumbnail_folder
            print(f"북마크 썸네일 폴더 설정: {thumbnail_folder}")
            return True
        except Exception as e:
            print(f"북마크 썸네일 폴더 설정 중 오류: {e}")
            self.current_thumbnail_folder = None
            return False

    def delete_bookmark(self, list_widget):
        """선택된 북마크를 삭제합니다 (고치던 경로가 있으면 먼저 반영 — 그 경로를 지움; 거부된 편집이면 멈춤)"""
        if not self._commit_bookmark_edit(list_widget):
            return
        current_item = list_widget.currentItem()
        if current_item:
            folder_path = current_item.text()
            reply = QMessageBox.question(
                self, 
                "북마크 삭제", 
                f"다음 폴더를 북마크에서 삭제하시겠습니까?\n\n{folder_path}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 북마크에서 제거 (파일을 다시 읽고 지움 — 다른 창이 더한 것은 남음)
                if not self._change_bookmarks(bookmarks.remove, [folder_path]):
                    return
                
                # 리스트에서 제거
                list_widget.takeItem(list_widget.row(current_item))
                
                QMessageBox.information(self, "삭제 완료", "북마크가 삭제되었습니다.")
        else:
            QMessageBox.warning(self, "선택 필요", "삭제할 북마크를 선택해주세요.")
