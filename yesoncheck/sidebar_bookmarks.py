"""북마크 믹스인 (SidebarBookmarksMixin): 북마크 파일(`~/.yeson_bookmarks.json`) 읽기·더하기·지우기와 북마크 관리 대화 상자,
북마크 폴더 열기(영상 불러오기 + 그 폴더의 썸네일 폴더 설정).

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin)`. 그래서
VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin 앞)에 오고, 이 메서드들의 이름은 다른 믹스인·
VideoPlayerBase와 겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.bookmarks`·`self.bookmarks_file`·
`self.current_thumbnail_folder` 등)는 예전처럼 VideoPlayerBase.__init__이 만들고(`load_bookmarks`도 거기서 부름), 폴더 불러오기·썸네일·
스레드 정리는 PlayerSidebarMixin 등 다른 믹스인의 메서드를 `self.`로 불러 그대로 닿음.

player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
시험이 북마크 대화 상자의 `QDialog.exec_`를 바꿔칠 때 문자열 경로는 이 모듈 이름으로 적음: `yesoncheck.sidebar_bookmarks.QDialog.exec_`.
"""

import traceback

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from yesoncheck import bookmarks, paths, thumbnails
from yesoncheck.user_files import UserFileError


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
        dialog = QDialog(self)
        dialog.setWindowTitle("북마크 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("북마크된 폴더 목록:")
        layout.addWidget(label)
        
        # 북마크 리스트
        list_widget = QListWidget()
        for bookmark in self.bookmarks:
            item = QListWidgetItem(bookmark)
            list_widget.addItem(item)
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
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        # 더블클릭으로도 폴더 열기 가능
        list_widget.itemDoubleClicked.connect(lambda item: self.open_bookmark_folder(list_widget, dialog))
        
        dialog.exec_()

    def open_bookmark_folder(self, list_widget, dialog):
        """선택된 북마크 폴더를 엽니다"""
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
        """선택된 북마크를 삭제합니다"""
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
