"""Media library and sidebar helpers for VideoPlayer."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import cv2
from PyQt5.QtCore import QDateTime, QDir, Qt, QSize
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from yesoncheck.workers import ThumbnailLoaderWorker, ThumbnailWorker
import traceback

from yesoncheck import path_map_setup, paths, shared_config
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog

class PlayerSidebarMixin:

    def dragEnterEvent(self, event):
        """메인 윈도우에 파일 드래그앤드롭 이벤트"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        # 부모 위젯을 찾아서 VideoPlayer 인스턴스를 찾기
        parent = self.parent()
        while parent and not hasattr(parent, 'open_file'):
            parent = parent.parent()
        
        if parent and hasattr(parent, 'open_file'):
            video_files = []
            has_folder = False
            folder_paths = []  # 폴더 경로들을 저장할 리스트
            
            # URL들을 파일/폴더로 분류
            for url in urls:
                local_path = paths.normalize_native(url.toLocalFile())
                if os.path.isfile(local_path):
                    # 파일인 경우
                    if parent.is_video_file(local_path):
                        video_files.append(local_path)
                elif os.path.isdir(local_path):
                    # 폴더인 경우 - 재귀적으로 비디오 파일 찾기
                    has_folder = True
                    folder_paths.append(local_path)  # 폴더 경로 저장
                    folder_files = parent.get_video_files_from_folder(local_path)
                    folder_files.sort()  # 이름 순서대로 정렬
                    video_files.extend(folder_files)
            
            # 폴더가 포함된 경우 북마크에 자동 추가
            if folder_paths:
                for folder_path in folder_paths:
                    if not paths.contains_path(parent.bookmarks, folder_path):
                        parent.bookmarks.append(folder_path)
                        print(f"폴더가 북마크에 자동 추가됨: {folder_path}")
                
                # 북마크 저장
                parent.save_bookmarks()
                
                # 사용자에게 알림 (폴더가 여러 개인 경우에만)
                if len(folder_paths) > 1:
                    QMessageBox.information(parent, "북마크 추가", f"{len(folder_paths)}개의 폴더가 북마크에 자동으로 추가되었습니다.")
            
            # 비디오 파일 처리
            if has_folder:
                # 폴더가 포함된 경우: 기존 사이드바 초기화 후 모든 파일을 사이드바에 추가하고 첫 번째 파일을 Video A에 로드
                if video_files:
                    # 폴더 경로를 selected_folder_path로 설정 (썸네일 폴더 생성용)
                    parent.selected_folder_path = folder_paths[0]
                    print(f"메인 윈도우 드래그앤드롭으로 썸네일 폴더 설정: {parent.selected_folder_path}")
                    
                    # 드래그앤드롭 시 직접 썸네일 폴더 생성
                    thumbnail_folder = os.path.join(folder_paths[0], ".yesoncheck_thumb")
                    if not os.path.exists(thumbnail_folder):
                        os.makedirs(thumbnail_folder)
                        print(f"메인 윈도우 드래그앤드롭으로 썸네일 폴더 생성: {thumbnail_folder}")
                    parent.current_thumbnail_folder = thumbnail_folder
                    print(f"메인 윈도우 드래그앤드롭으로 썸네일 폴더 설정: {thumbnail_folder}")
                    
                    # 기존 사이드바 리스트 초기화
                    parent.sidebar.clear()
                    parent.add_files_to_sidebar(video_files)
                    # 첫 번째 파일을 Video A에 로드
                    parent.open_file('A', video_files[0])
                    # 백그라운드 로딩 스케줄링
                    parent.schedule_background_thumbnail_loading()
                    QMessageBox.information(parent, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
                else:
                    QMessageBox.warning(parent, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")
            else:
                # 개별 파일들만 있는 경우
                if len(video_files) == 1:
                    parent.open_file('A', video_files[0])
                elif len(video_files) == 2:
                    # 두 개 파일: Video A와 B에 각각 로드
                    parent.open_file('A', video_files[0])
                    parent.open_file('B', video_files[1])
                elif len(video_files) > 2:
                    # 여러 파일: 첫 번째는 Video A에, 나머지는 사이드바에 추가
                    parent.open_file('A', video_files[0])
                    remaining_files = video_files[1:]
                    parent.add_files_to_sidebar(remaining_files)
                    if remaining_files:
                        QMessageBox.information(parent, "파일 로드 완료", f"첫 번째 파일이 Video A에 로드되고, {len(remaining_files)}개의 파일이 사이드바에 추가되었습니다.")
        
        event.acceptProposedAction()

    def is_video_file(self, file_path):
        """파일이 지원되는 비디오 형식인지 확인"""
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.mts', '.m2ts'}
        return os.path.splitext(file_path.lower())[1] in video_extensions

    def add_files_to_sidebar(self, file_paths):
        """사이드바에 파일들을 추가 (항상 번호순 정렬)"""
        import re
        def natural_sort_key(file_path):
            filename = os.path.basename(file_path)
            return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', filename)]
        file_paths = sorted(file_paths, key=natural_sort_key)
        for file_path in file_paths:
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                item = QListWidgetItem(filename)
                item.setData(Qt.UserRole, file_path)
                item.setToolTip(file_path)  # toolTip도 설정하여 기존 코드와 호환
                self.sidebar.addItem(item)
                
                # 썸네일 모드인 경우 썸네일 생성
                if self.is_thumbnail_mode:
                    self.generate_thumbnail(file_path)
        
        if file_paths:
            QMessageBox.information(self, "완료", f"{len(file_paths)}개의 파일이 사이드바에 추가되었습니다.")

    def get_video_files_from_folder(self, folder_path):
        """폴더에서 재귀적으로 비디오 파일들을 찾아서 반환 (.으로 시작하는 파일 제외)"""
        video_files = []
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.mts', '.m2ts'}
        
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.startswith('.'):
                        continue  # .으로 시작하는 숨김 파일 제외
                    file_path = os.path.join(root, file)
                    if os.path.splitext(file.lower())[1] in video_extensions:
                        video_files.append(file_path)
            
            # 번호 순서대로 정렬 (숫자가 포함된 파일명을 올바르게 정렬)
            def natural_sort_key(file_path):
                filename = os.path.basename(file_path)
                import re
                return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', filename)]
            video_files.sort(key=natural_sort_key)
        except Exception as e:
            print(f"폴더 스캔 중 오류 발생: {e}")
        return video_files

    def show_sidebar_context_menu(self, pos):
        index = self.sidebar.indexAt(pos)
        if index.isValid():
            menu = QMenu(self.sidebar)
            open_video_a_action = menu.addAction("비디오 A 열기")
            open_video_a_action.triggered.connect(lambda: self.open_video_a(index))
            open_video_b_action = menu.addAction("비디오 B 열기")
            open_video_b_action.triggered.connect(lambda: self.open_video_b(index))

            # 구분선 추가
            menu.addSeparator()

            merge_videos_action = menu.addAction("애니매틱 하나로 합치기")
            merge_videos_action.triggered.connect(self.merge_videos)

            # 구분선 추가
            menu.addSeparator()

            copy_file_action = menu.addAction("파일 복사")
            copy_file_action.triggered.connect(self.copy_selected_files)  # copy_selected_files 메서드 호출

            # 구분선 추가
            menu.addSeparator()

            # 썸네일 재생성 메뉴 추가
            regenerate_thumbnail_action = menu.addAction("썸네일 재생성")
            regenerate_thumbnail_action.triggered.connect(lambda: self.regenerate_selected_thumbnails())

            # 구분선 추가
            menu.addSeparator()

            video_info_action = menu.addAction("미디어 정보")
            video_info_action.triggered.connect(lambda: self.show_video_info(index))

            menu.exec_(self.sidebar.viewport().mapToGlobal(pos))

    def copy_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if not selected_items:
            return

        file_paths = [item.toolTip() for item in selected_items]
        target_path = QFileDialog.getExistingDirectory(self, "Select Folder to Copy")
        target_path = paths.normalize_native(target_path)
        if target_path:
            self.copy_files_to_target(file_paths, target_path)

    def copy_files_to_target(self, file_paths, target_path):
        """선택한 파일을 폴더로 복사합니다 (메타데이터 유지). 실패한 파일은 모아서 보여 줍니다."""
        failures = []
        for file_path in file_paths:
            try:
                shutil.copy2(file_path, target_path)
                print(f"File copied to {target_path}")
            except OSError as exc:
                failures.append(f"{file_path}\n  → {exc}")
        if failures:
            QMessageBox.critical(self, "복사 실패", f"{len(failures)}개 파일을 복사하지 못했습니다:\n\n" + "\n".join(failures))

    def regenerate_selected_thumbnails(self):
        """선택된 파일들의 썸네일을 재생성합니다."""
        try:
            selected_items = self.sidebar.selectedItems()
            if not selected_items:
                QMessageBox.information(self, "알림", "선택된 파일이 없습니다.")
                return

            # 진행 상황을 보여주는 다이얼로그 생성
            progress_dialog = QProgressDialog("썸네일 재생성 중...", "취소", 0, len(selected_items), self)
            progress_dialog.setWindowTitle("썸네일 재생성")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)
            progress_dialog.setAutoReset(True)
            progress_dialog.show()

            print(f"선택된 {len(selected_items)}개 파일의 썸네일 재생성을 시작합니다.")

            for i, item in enumerate(selected_items):
                if progress_dialog.wasCanceled():
                    print("썸네일 재생성이 취소되었습니다.")
                    break

                file_path = item.toolTip()
                if file_path and os.path.isfile(file_path):
                    # 진행 상황 업데이트
                    progress_dialog.setLabelText(f"재생성 중: {os.path.basename(file_path)}")
                    progress_dialog.setValue(i)
                    
                    # 기존 썸네일 삭제
                    self.delete_thumbnail_file(file_path)
                    # 썸네일 재생성
                    self.generate_thumbnail(file_path)
                    print(f"썸네일 재생성 완료: {os.path.basename(file_path)}")

                # UI 업데이트
                QApplication.processEvents()

            progress_dialog.setValue(len(selected_items))
            QMessageBox.information(self, "완료", f"{len(selected_items)}개 파일의 썸네일 재생성이 완료되었습니다.")

        except Exception as e:
            print(f"썸네일 재생성 중 오류: {e}")
            QMessageBox.critical(self, "오류", f"썸네일 재생성 중 오류가 발생했습니다:\n{str(e)}")

    def delete_thumbnail_file(self, file_path):
        """특정 파일의 썸네일을 디스크에서 삭제합니다."""
        try:
            if not self.current_thumbnail_folder:
                return

            file_hash = paths.thumbnail_key(file_path)
            thumbnail_path = os.path.join(self.current_thumbnail_folder, f"{file_hash}.jpg")

            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                print(f"썸네일 파일 삭제: {thumbnail_path}")

            # UI에서도 썸네일 제거
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item and paths.same_path(item.data(Qt.UserRole), file_path):
                    item.setIcon(QIcon())
                    # 파일명만 표시
                    filename = os.path.basename(file_path)
                    item.setText(filename)
                    break

        except Exception as e:
            print(f"썸네일 파일 삭제 중 오류: {e}")

    def update_season_list(self):
        selected_work = self.workComboBox.currentText()
        self._work_path_problems_shown = set()
        self.seasonComboBox.clear()
        self.seasonComboBox.addItem("시즌선택")

        try:
            # JSON에서 작품 경로 가져오기
            path = self.get_work_path(selected_work)
            
            if not path:
                # 경로가 없는 경우 시즌 목록 없음
                season_list = []
            elif selected_work == "The_Johnsons":
                # The_Johnsons는 시즌이 없으므로 바로 job 목록을 가져옴
                season_list = []  # 시즌 목록 없음
                # 시즌 선택 없이 바로 job 목록 가져오기
                self.jobComboBox.clear()
                self.jobComboBox.addItem("job선택")
                try:
                    if os.path.isdir(path):
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file.startswith("TJS_")
                            and len(file) > 4
                            and file[4:].isdigit()
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                except FileNotFoundError:
                    print(f"Directory not found: {path}")
            elif selected_work == "TJS_Animatic":
                # TJS_Animatic는 시즌이 없으므로 바로 job 목록을 가져옴
                season_list = []  # 시즌 목록 없음
                # 시즌 선택 없이 바로 job 목록 가져오기
                self.jobComboBox.clear()
                self.jobComboBox.addItem("job선택")
                try:
                    if os.path.isdir(path):
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file.startswith("TJS")
                            and (file[3:].isdigit() or (len(file) > 4 and file[3] == '_' and file[4:].isdigit()))
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                except FileNotFoundError:
                    print(f"Directory not found: {path}")
            else:
                # 시즌 목록 가져오기 (작품별 패턴 매칭)
                season_list = []
                if os.path.isdir(path):
                    if selected_work == "BB":
                        season_list = [file for file in os.listdir(path) if "BB_Season" in file]
                    elif selected_work == "KOTH":
                        season_list = [file for file in os.listdir(path) if "KOTH_Season" in file]
                    elif selected_work == "Big_Mouth":
                        season_list = [file for file in os.listdir(path) if "BM_Season" in file]
                    elif selected_work == "TGN":
                        season_list = [file for file in os.listdir(path) if "GN_Season" in file]
                    elif selected_work == "MatingSeason":
                        season_list = [file for file in os.listdir(path) if "MS_Season" in file]
                    elif selected_work == "BB_Animatic":
                        season_list = [file for file in os.listdir(path) if "season" in file]
                    elif selected_work == "KOTH_Animatic":
                        season_list = [file for file in os.listdir(path) if "KOTH_SEASON" in file]
                    elif selected_work == "BM_Animatic":
                        season_list = [file for file in os.listdir(path) if "BM_SEASON" in file]
                    elif selected_work == "TGN_Animatic":
                        season_list = [file for file in os.listdir(path) if "TGN_Season" in file]
                    elif selected_work == "MS_Animatic":
                        season_list = [file for file in os.listdir(path) if "MS" in file and os.path.isdir(os.path.join(path, file))]
                    else:
                        # 일반적인 경우: 모든 디렉토리를 시즌으로 간주
                        season_list = [file for file in os.listdir(path) 
                                      if os.path.isdir(os.path.join(path, file)) 
                                      and not file.startswith('.')]

            season_list.sort()  # Sort the list
            for season in season_list:
                self.seasonComboBox.addItem(season)

        except FileNotFoundError:
            # Handle the case where the directory does not exist
            print(f"Directory not found: {path}")
            # Optionally, you can display a message to the user or log the error
        except Exception as e:
            print(f"Error updating season list: {e}")

    def update_job_list(self):
        selected_season = self.seasonComboBox.currentText()
        selected_work = self.workComboBox.currentText()
        
        # JSON에서 작품 기본 경로 가져오기
        base_path = self.get_work_path(selected_work)
        
        # The_Johnsons, TJS_Animatic는 시즌이 없으므로 시즌 선택 없이도 job 목록 가져오기
        if selected_work == "The_Johnsons":
            self.jobComboBox.clear()
            self.jobComboBox.addItem("job선택")
            path = base_path
            try:
                if os.path.isdir(path):
                    job_list = [
                        file for file in os.listdir(path)
                        if os.path.isdir(os.path.join(path, file))
                        and not file.startswith('.')
                        and file.startswith("TJS_")
                        and len(file) > 4
                        and file[4:].isdigit()
                        and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                    ]
                    job_list.sort()
                    for job in job_list:
                        self.jobComboBox.addItem(job)
            except FileNotFoundError:
                print(f"Directory not found: {path}")
            return
        
        if selected_work == "TJS_Animatic":
            self.jobComboBox.clear()
            self.jobComboBox.addItem("job선택")
            path = base_path
            try:
                if os.path.isdir(path):
                    job_list = [
                        file for file in os.listdir(path)
                        if os.path.isdir(os.path.join(path, file))
                        and not file.startswith('.')
                        and file.startswith("TJS")
                        and (file[3:].isdigit() or (len(file) > 4 and file[3] == '_' and file[4:].isdigit()))
                        and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                    ]
                    job_list.sort()
                    for job in job_list:
                        self.jobComboBox.addItem(job)
            except FileNotFoundError:
                print(f"Directory not found: {path}")
            return
        
        if selected_season != "시즌선택":
            self.jobComboBox.clear()
            self.jobComboBox.addItem("job선택")

            try:
                # JSON에서 가져온 기본 경로와 시즌을 결합
                if base_path:
                    path = os.path.join(base_path, selected_season)
                else:
                    path = None

                if path and os.path.isdir(path):
                    if selected_work == "MS_Animatic":
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and 'ANIMATIC' in file.upper()
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                        return
                    elif selected_work == "TJS_Animatic":
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and 'ANIMATIC' in file.upper()
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                        return
                    else:
                        # 일반적인 경우
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)

            except FileNotFoundError:
                # Handle the case where the directory does not exist
                print(f"Directory not found: {path}")
                # Optionally, you can display a message to the user or log the error
            except Exception as e:
                print(f"Error updating job list: {e}")

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            self.load_videos_from_folder(folder_path)

    def load_videos_from_folder(self, folder_path):
        self.playlist.clear()
        self.sidebar.clear()
        
        # 선택된 폴더 경로 저장 (썸네일 폴더 생성용)
        self.selected_folder_path = folder_path
        
        # 재귀적으로 폴더 내의 모든 비디오 파일 찾기 (드래그앤드롭과 동일한 방식)
        video_files = self.get_video_files_from_folder(folder_path)
        
        # 번호 순서대로 정렬
        import re
        def natural_sort_key(file_path):
            filename = os.path.basename(file_path)
            return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', filename)]
        video_files = sorted(video_files, key=natural_sort_key)
        
        # 사이드바에 파일들 추가
        for file_path in video_files:
            filename = os.path.basename(file_path)
            self.playlist.append(file_path)
            item = QListWidgetItem(filename)
            item.setData(Qt.UserRole, file_path)  # 파일 경로를 UserRole에 저장
            item.setToolTip(file_path)
            self.sidebar.addItem(item)
        
        if self.playlist:
            self.current_playlist_index = 0
            self.open_file('A', self.playlist[0])
            self.sidebar.selectAll()
            # 폴더 드래그앤드롭 시에는 기존 썸네일 폴더를 초기화하고 새로 설정
            self.current_thumbnail_folder = None  # 기존 썸네일 폴더 초기화
            self.setup_thumbnail_folder()
            self.schedule_background_thumbnail_loading()
            QMessageBox.information(self, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
        else:
            QMessageBox.warning(self, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")

    def play_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            selected_items.sort(key=lambda x: self.sidebar.row(x))
            self.playlist = [item.toolTip() for item in selected_items]
            self.current_playlist_index = 0
            self.is_playlist_playing = True
            print(f"Play Selected: {len(selected_items)} files selected, starting playback")
            self.play_current_playlist_item()
        else:
            print("No files selected")
            # 사용자에게 선택된 파일이 없다는 것을 알림
            QMessageBox.information(self, "Play Selected", "Please select one or more files from the sidebar first.")

    def play_current_playlist_item(self):
        if 0 <= self.current_playlist_index < len(self.playlist):
            current_file = self.playlist[self.current_playlist_index]
            print(f"Playing playlist item {self.current_playlist_index + 1}/{len(self.playlist)}: {os.path.basename(current_file)}")
            print(f"is_playlist_playing before: {self.is_playlist_playing}")
            
            # 플레이리스트 재생 상태 확실히 설정
            self.is_playlist_playing = True
            
            # 사이드바에서 현재 파일 강조
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                is_current = paths.same_path(item.toolTip(), current_file)
                font = item.font()
                font.setBold(is_current)
                item.setFont(font)
                if is_current:
                    item.setForeground(QColor("red"))  # 현재 재생 중인 항목은 빨간색
                else:
                    # 현재 테마에 맞는 색상으로 설정
                    if self.current_theme == 'dark':
                        item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
                    else:
                        item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상
            
            # 파일 열기 및 재생
            try:
                self.open_file('A', current_file)
                # 첫 번째 프레임으로 이동
                self.seek_to_frame(1)
                self.play_video()
                self.playSelectedPauseButton.setText('Selected Pause')
                self.playSelectedPauseButton.setStyleSheet("background-color: yellow;")
                print(f"Successfully started playing: {os.path.basename(current_file)}")
                print(f"is_playlist_playing after: {self.is_playlist_playing}")
            except Exception as e:
                print(f"Error playing file {current_file}: {e}")
                QMessageBox.warning(self, "Play Error", f"Failed to play file: {os.path.basename(current_file)}\nError: {str(e)}")
                # 오류 발생 시 다음 파일로 이동
                if self.current_playlist_index < len(self.playlist) - 1:
                    self.current_playlist_index += 1
                    self.play_current_playlist_item()
        else:
            print(f"Invalid playlist index: {self.current_playlist_index}, playlist length: {len(self.playlist)}")
            self.is_playlist_playing = False
            self.reset_sidebar_colors()

    def reset_sidebar_colors(self):
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            font = item.font(); font.setBold(False)
            item.setFont(font)
            # 현재 테마에 맞는 색상으로 설정
            if self.current_theme == 'dark':
                item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
            else:
                item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상

    def play_next_in_playlist(self):
        if self.current_playlist_index < len(self.playlist) - 1:
            self.current_playlist_index += 1
            print(f"Moving to next item in playlist: {self.current_playlist_index + 1}/{len(self.playlist)}")
            self.play_current_playlist_item()
        else:
            print("Reached end of playlist, stopping playback")
            self.is_playlist_playing = False
            self.stop_video()
            self.reset_sidebar_colors()
            QMessageBox.information(self, "Playlist Complete", "All selected files have been played.")

    def initialize_sidebar_width(self):
        """기본 사이드바 폭을 초기화합니다."""
        # default_sidebar_width가 없으면 초기화
        if not hasattr(self, 'default_sidebar_width') or self.default_sidebar_width is None:
            if hasattr(self, 'sidebar') and self.sidebar is not None:
                self.default_sidebar_width = self.sidebar.width()
                print(f"기본 사이드바 폭 초기화: {self.default_sidebar_width}")
            else:
                # sidebar가 아직 없으면 기본값 설정
                self.default_sidebar_width = 200

    def load_selected_item_to_video_a(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            self.open_file('A', selected_items[0].toolTip())

    def load_bookmarks(self):
        try:
            if os.path.exists(self.bookmarks_file):
                with open(self.bookmarks_file, 'r', encoding='utf-8') as f:
                    self.bookmarks = json.load(f)
            else:
                self.bookmarks = []
        except Exception as e:
            print(f"Bookmark load error: {e}")
            self.bookmarks = []

    def save_bookmarks(self):
        try:
            with open(self.bookmarks_file, 'w', encoding='utf-8') as f:
                json.dump(self.bookmarks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Bookmark save error: {e}")

    def add_bookmark(self):
        # 현재 폴더를 북마크에 추가
        folder_path = QFileDialog.getExistingDirectory(self, "북마크할 폴더 선택")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            if not paths.contains_path(self.bookmarks, folder_path):
                self.bookmarks.append(folder_path)
                self.save_bookmarks()
                QMessageBox.information(self, "북마크 추가", f"{folder_path}\n폴더가 북마크에 추가되었습니다.")
            else:
                QMessageBox.information(self, "이미 북마크됨", f"{folder_path}\n폴더는 이미 북마크에 있습니다.")

    def show_bookmarks(self):
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
        try:
            thumbnail_folder = os.path.join(folder_path, ".yesoncheck_thumb")
            if not os.path.exists(thumbnail_folder):
                os.makedirs(thumbnail_folder)
                print(f"북마크 썸네일 폴더 생성: {thumbnail_folder}")
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
                # 북마크에서 제거
                if folder_path in self.bookmarks:
                    self.bookmarks.remove(folder_path)
                    self.save_bookmarks()
                
                # 리스트에서 제거
                list_widget.takeItem(list_widget.row(current_item))
                
                QMessageBox.information(self, "삭제 완료", "북마크가 삭제되었습니다.")
        else:
            QMessageBox.warning(self, "선택 필요", "삭제할 북마크를 선택해주세요.")

    def setup_shared_config(self):
        """공유 설정 폴더를 정하고 작품 경로(Windows는 변환표도)를 읽습니다.

        창은 띄우지 않고 문제를 self.shared_config_problem에 남깁니다 (창 표시 후 resolve_shared_config_problem이 알림).
        읽기에 실패해도 공유 파일을 기본값으로 덮어쓰지 않습니다.
        """
        self.work_paths = {}
        self.shared_config_problem = None
        self.path_map_problem = None
        self.config_dir_candidates = []
        self.config_dir_search_failed = False
        self.work_paths_config_dir = None
        self.work_paths_file = None
        self.work_paths_password_file = None
        try:
            config_dir = shared_config.configured_config_dir()
        except shared_config.SharedConfigError as exc:
            self.shared_config_problem = f"{exc}\n\n{traceback.format_exc()}"
            return
        if (paths.IS_WINDOWS and not os.environ.get(shared_config.CONFIG_DIR_ENV)
                and not shared_config.is_valid_config_dir(config_dir)):
            found = self._auto_find_config_dir()
            if self.shared_config_problem:
                return
            config_dir = found or config_dir
        if config_dir is None:
            self.shared_config_problem = "공유 설정 폴더가 아직 정해지지 않았습니다."
            return
        self.work_paths_config_dir = config_dir
        self.work_paths_file = os.path.join(config_dir, shared_config.WORK_PATHS_FILENAME)
        self.work_paths_password_file = os.path.join(config_dir, shared_config.PASSWORD_FILENAME)
        problems = []
        try:
            self.work_paths = shared_config.read_work_paths(self.work_paths_file)
        except shared_config.SharedConfigError as exc:
            problems.append(f"{exc}\n\n{traceback.format_exc()}")
        if paths.IS_WINDOWS:
            try:
                path_map = paths.PathMap.load(config_dir)
            except paths.PathMapError as exc:
                paths.activate(None)
                self.path_map_problem = f"{exc}\n\n{traceback.format_exc()}"
            else:
                # 같은 공유를 PC마다 다른 주소로 연결했을 수 있음 → 이 PC 드라이브가 연결된 주소를 먼저 씀 (파일은 그대로)
                shares, share_problems = path_map_setup.connected_shares()
                for problem in share_problems:
                    print(f"[변환표] 드라이브 연결 정보를 읽지 못함: {problem}")
                paths.activate(path_map.with_preferred_aliases([share.unc for share in shares]))
        if problems:
            self.shared_config_problem = "\n\n".join(problems)

    def _auto_find_config_dir(self):
        """(Windows) 연결된 네트워크 드라이브에서 공유 설정 폴더를 찾습니다.

        딱 하나면 PC별 설정에 저장하고 그 폴더를 돌려줍니다. 여러 개면 self.config_dir_candidates에 남기고
        (창 표시 후 고르게 함) None. 하나도 못 찾으면 self.config_dir_search_failed를 True로 남기고 None.
        PC별 설정 저장 실패는 self.shared_config_problem에 남기고 None.
        """
        shares, problems = path_map_setup.connected_shares()
        for problem in problems:
            print(f"[공유 설정] 드라이브 연결 정보를 읽지 못함: {problem}")
        found = path_map_setup.find_config_dirs(shares)
        if len(found) != 1:
            self.config_dir_candidates = found
            if not found:
                self.config_dir_search_failed = True
            return None
        try:
            shared_config.save_local_settings({"config_dir": found[0]})
        except (shared_config.SharedConfigError, OSError) as exc:
            self.shared_config_problem = (
                f"공유 설정 폴더를 찾았지만 PC별 설정에 저장하지 못했습니다: {found[0]}\n{exc}\n\n{traceback.format_exc()}"
            )
            return None
        print(f"[공유 설정] 연결된 드라이브에서 공유 설정 폴더를 찾았습니다: {found[0]}")
        return found[0]

    def _update_shared_config_title(self):
        title = "Yeson Checker"
        if self.shared_config_problem:
            title += " — 공유 설정 오류 (작품 목록 없음)"
        if getattr(self, "path_map_problem", None):
            title += " — 변환표 오류 (작품 경로 관리에서 자동 설정)"
        self.setWindowTitle(title)

    def resolve_shared_config_problem(self):
        """창 표시 후 공유 설정 문제를 알립니다.

        Windows: 설정 폴더를 못 찾았으면 고르게 하고(찾은 후보가 여럿이면 그 목록에서), 변환표가 없거나
        열리지 않는 작품이 있으면 연결된 드라이브로 변환표 자동 설정을 제안합니다.
        """
        if self.shared_config_problem and paths.IS_WINDOWS and not shared_config.is_valid_config_dir(self.work_paths_config_dir):
            if self.config_dir_candidates:
                picked = self._pick_config_dir_candidate()
            else:
                reason = self.shared_config_problem
                if self.config_dir_search_failed:
                    reason = "연결된 네트워크 드라이브에서 공유 설정 폴더를 찾지 못했습니다.\n\n" + reason
                picked = self.choose_shared_config_dir(reason)
            if picked:
                return  # _use_config_dir가 문제 알림·변환표 자동 설정까지 처리함
        if self.shared_config_problem:
            QMessageBox.critical(
                self,
                "공유 설정 오류",
                f"{self._shared_config_problem_text()}\n\n작품 목록 없이 계속합니다. 파일 직접 열기와 드래그는 쓸 수 있습니다.",
            )
            return
        self._offer_path_map_setup()

    def _shared_config_problem_text(self):
        """공유 설정 오류 창에 보일 내용: 공유 설정 문제 + (함께 있으면) 변환표 문제."""
        message = self.shared_config_problem
        if self.path_map_problem:
            message += f"\n\n{self.path_map_problem}"
        return message

    def choose_shared_config_dir(self, reason=None):
        """(Windows) 공유 설정 폴더를 고르게 하고 PC별 설정에 저장합니다. 골랐으면 True."""
        if reason:
            QMessageBox.information(
                self,
                "공유 설정 폴더 선택",
                f"{reason}\n\n작품 경로 설정(work_paths.json)이 들어 있는 공유 설정 폴더(.yesoncheck)를 골라 주세요.",
            )
        while True:
            folder = QFileDialog.getExistingDirectory(self, "공유 설정 폴더(.yesoncheck) 선택")
            if not folder:
                return False
            try:
                config_dir = paths.drive_to_unc(folder)
                shared_config.validate_config_dir(config_dir)
            except (paths.PathMapError, shared_config.SharedConfigError) as exc:
                QMessageBox.warning(self, "다른 폴더를 고르세요", str(exc))
                continue
            return self._use_config_dir(config_dir)

    def _use_config_dir(self, config_dir):
        """(Windows) 고른 공유 설정 폴더를 PC별 설정에 저장하고 다시 읽습니다. 저장했으면 True."""
        try:
            shared_config.save_local_settings({"config_dir": config_dir})
        except (shared_config.SharedConfigError, OSError) as exc:
            QMessageBox.critical(self, "PC별 설정 저장 실패", f"{exc}\n\n{traceback.format_exc()}")
            return False
        self.setup_shared_config()
        self.reload_work_combo()
        if self.shared_config_problem:
            QMessageBox.critical(self, "공유 설정 오류", self._shared_config_problem_text())
        else:
            self._offer_path_map_setup()
        return True

    def _pick_config_dir_candidate(self):
        """(Windows) 연결된 드라이브에서 찾은 공유 설정 폴더가 여럿일 때 고르게 합니다. 골랐으면 True."""
        manual = "직접 고르기..."
        item, ok = QInputDialog.getItem(
            self,
            "공유 설정 폴더 선택",
            "연결된 네트워크 드라이브에서 공유 설정 폴더를 여러 개 찾았습니다. 쓸 폴더를 고르세요:",
            list(self.config_dir_candidates) + [manual],
            0,
            False,
        )
        if not ok:
            return False
        if item == manual:
            return self.choose_shared_config_dir()
        return self._use_config_dir(item)

    def _works_not_opening(self):
        """(Windows) 이 PC에서 열리지 않는 작품 목록 ['작품: 이유'].

        작품 경로의 공유 루트(\\\\서버\\공유)를 공유마다 한 번만 열어 보고, 열리지 않으면(서버가 꺼짐 등) 그 공유의
        작품 폴더는 열어 보지 않습니다 — 작품마다 SMB 시간 초과를 기다리지 않도록.
        """
        is_dir = path_map_setup._default_is_dir
        root_opens = {}  # 접은 (서버, 공유) → 열리는지
        broken = []
        for work_name, stored in sorted(self.work_paths.items()):
            try:
                native = paths.to_native(stored)
            except paths.PathMapError:
                broken.append(f"{work_name}: 변환표에 없음 ({stored})")
                continue
            root_parts = paths._unc_parts(native)[:2]
            key = tuple(paths._fold(root_parts))
            root = "\\\\" + "\\".join(root_parts)
            if key not in root_opens:
                root_opens[key] = is_dir(root)
            if not root_opens[key]:
                broken.append(f"{work_name}: 열 수 없음 ({native}) — 공유 폴더 {root}가 열리지 않음 (서버가 꺼졌거나 연결이 끊김)")
            elif not is_dir(native):
                broken.append(f"{work_name}: 열 수 없음 ({native})")
        return broken

    def _offer_path_map_setup(self):
        """(Windows) 변환표가 없거나 열리지 않는 작품이 있으면 변환표 자동 설정을 제안합니다."""
        if paths.IS_WINDOWS and (self.path_map_problem or self._works_not_opening()):
            self.auto_setup_path_map(ask_password=True, startup=True)

    def _report_path_map_problem(self, parent, note=None):
        """(Windows, startup) 저장 없이 끝날 때 변환표 문제를 한 번만 알립니다 (호출하는 쪽에서 self.path_map_problem을 확인)."""
        message = self.path_map_problem
        if note:
            message = f"{message}\n\n{note}"
        QMessageBox.critical(parent, "변환표 오류", message)

    def auto_setup_path_map(self, ask_password, startup=False, parent=None):
        """(Windows) 연결된 네트워크 드라이브로 변환표 짝을 찾아 확인 창을 띄우고, 승인되면 path_map.json에 합쳐 저장합니다.

        startup이면 기존 변환표에 더할 것이 없을 때 창을 띄우지 않고 변환표 문제만 알립니다(저장 없이 끝나는 모든
        경로에서 한 번만). 저장했으면 True(다시 읽기에 실패해도 저장은 된 것이므로 True이며, 공유 설정 오류를 따로 알립니다).

        확인 창·비밀번호는 몇 분이 걸릴 수 있으므로, 저장 직전에 path_map.json을 다시 읽어 그 내용에 합칩니다
        (그 사이 다른 PC가 쓴 항목을 지우지 않도록, 백업 여부도 다시 읽은 내용으로 정함).
        """
        parent = parent or self
        config_dir = self.work_paths_config_dir
        map_file = os.path.join(config_dir, paths.PATH_MAP_FILENAME)

        def read_map_file():
            """→ (existing, existing_error) 또는 읽지 못하면 오류 창을 띄우고 None."""
            try:
                return path_map_setup.read_existing(config_dir)
            except OSError as exc:
                QMessageBox.critical(parent, "변환표를 읽지 못함", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")
                return None

        def report_save_failure(exc):
            QMessageBox.critical(parent, "변환표 저장 실패", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")

        read = read_map_file()
        if read is None:
            return False
        existing, existing_error = read
        shares, share_problems = path_map_setup.connected_shares()
        progress = QProgressDialog("연결된 네트워크 드라이브에서 작품 폴더를 찾는 중…", "취소", 0, 100, parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)

        def on_progress(done, total):
            progress.setValue(int(done * 100 / total))
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            proposal = path_map_setup.propose_mapping(self.work_paths, shares, progress=on_progress)
        except path_map_setup.SetupCancelled:
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        finally:
            progress.close()
            progress.deleteLater()
        proposal.share_problems = share_problems + proposal.share_problems

        if startup and not path_map_setup.has_additions(existing, proposal):
            if self.path_map_problem:
                self._report_path_map_problem(
                    parent, note="연결된 네트워크 드라이브에서 새로 찾은 짝이 없습니다. NAS 드라이브 연결을 확인하세요.",
                )
            return False
        _ok, rejected = path_map_setup.split_mergeable(existing, proposal.ordered_default_choices())
        blocked = {mac_prefix: reason for mac_prefix, _unc, reason in rejected}
        dialog = PathMapSetupDialog(proposal, existing_error, parent, blocked=blocked)
        if dialog.exec_() != QDialog.Accepted:
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        chosen = dialog.chosen()
        try:
            path_map_setup.merge_path_map(existing, chosen)  # 비밀번호를 묻기 전에: 합칠 수 없는 짝을 골랐으면 여기서 알림
        except paths.PathMapError as exc:
            report_save_failure(exc)
            return False
        if ask_password and not self._confirm_work_paths_password(parent):
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        read = read_map_file()  # 확인 창·비밀번호 사이에 다른 PC가 바꿨을 수 있음 → 저장 직전 내용에 합침
        if read is None:
            return False
        fresh, fresh_error = read
        try:
            data = path_map_setup.merge_path_map(fresh, chosen)
            backup = path_map_setup.save_path_map(config_dir, data, backup_existing=fresh_error is not None)
        except (paths.PathMapError, OSError) as exc:
            report_save_failure(exc)
            return False

        self.setup_shared_config()
        self.reload_work_combo()
        message = f"변환표를 저장했습니다: {map_file}"
        if backup:
            message += f"\n원래 파일은 {backup}으로 보관했습니다."
        if self.shared_config_problem:
            # 변환표는 저장됐지만 공유 설정을 다시 읽다가 문제가 생김 (예: NAS 연결 끊김) — 저장은 됐다고 알림
            QMessageBox.critical(
                parent, "공유 설정 오류",
                f"{message}\n\n하지만 공유 설정을 다시 읽지 못했습니다:\n{self.shared_config_problem}",
            )
            return True
        broken = self._works_not_opening()
        if broken:
            QMessageBox.warning(parent, "변환표 저장됨 — 열리지 않는 작품", message + "\n\n아직 열리지 않는 작품:\n" + "\n".join(broken))
        else:
            QMessageBox.information(parent, "변환표 저장됨", message)
        return True

    def reload_work_combo(self):
        """작품 콤보박스를 self.work_paths로 다시 채웁니다."""
        self.workComboBox.blockSignals(True)
        self.workComboBox.clear()
        self.workComboBox.addItem("작품선택")
        for work_name in sorted(self.work_paths.keys()):
            self.workComboBox.addItem(work_name)
        self.workComboBox.blockSignals(False)
        self._update_shared_config_title()
        self.update_season_list()

    def save_work_paths(self, parent=None):
        """작품 경로를 공유 파일에 저장합니다. 실패하면 오류 창을 띄우고 False."""
        try:
            shared_config.write_work_paths(self.work_paths_file, self.work_paths)
            return True
        except OSError:
            QMessageBox.critical(parent or self, "작품 경로 저장 실패", f"{self.work_paths_file}\n\n{traceback.format_exc()}")
            return False

    def hash_password(self, password):
        """비밀번호를 해시화합니다."""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def load_password_hash(self):
        """저장된 비밀번호 해시. 파일이 없으면 None(최초 설정). 읽기 실패는 예외로 올립니다."""
        if not os.path.exists(self.work_paths_password_file):
            return None
        with open(self.work_paths_password_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('password_hash', None)

    def save_password_hash(self, password_hash):
        """비밀번호 해시를 저장합니다 (공유 설정 폴더는 이미 있어야 함). 실패는 예외로 올립니다."""
        with open(self.work_paths_password_file, 'w', encoding='utf-8') as f:
            json.dump({'password_hash': password_hash}, f, ensure_ascii=False, indent=2)

    def verify_password(self, password):
        """비밀번호를 확인합니다."""
        stored_hash = self.load_password_hash()
        if stored_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            return True
        return self.hash_password(password) == stored_hash

    def set_password(self, password):
        """비밀번호를 설정합니다."""
        password_hash = self.hash_password(password)
        self.save_password_hash(password_hash)

    def get_work_path(self, work_name):
        """작품 경로를 이 PC에서 여는 경로로 돌려줍니다 (Windows: 변환표로 UNC 변환).

        변환하지 못하거나 (Windows에서) 폴더가 없으면 오류 창을 한 번 띄우고 ""를 돌려줍니다.
        """
        stored = self.work_paths.get(work_name, "")
        if not stored:
            return ""
        try:
            native = paths.to_native(stored)
        except paths.PathMapError as exc:
            self._report_work_path_problem(f"작품 '{work_name}'의 경로를 이 PC 경로로 바꿀 수 없습니다.\n\n{exc}")
            return ""
        if paths.IS_WINDOWS and not os.path.isdir(native):
            self._report_work_path_problem(
                f"작품 '{work_name}' 폴더를 열 수 없습니다.\n\n이 PC 경로: {native}\n공유 설정 경로: {stored}\n\n"
                "NAS 연결과 path_map.json을 확인하세요."
            )
            return ""
        return native

    def _report_work_path_problem(self, message):
        """작품 하나를 고를 때 시즌·job·목록이 각각 같은 경로를 물으므로 같은 오류는 한 번만 보여 줍니다."""
        shown = self.__dict__.setdefault("_work_path_problems_shown", set())
        if message in shown:
            return
        shown.add(message)
        QMessageBox.critical(self, "작품 경로 오류", message)

    def _stored_work_path_or_warn(self, folder_path, parent):
        """고른 폴더를 공유 설정에 저장할 Mac 경로로 바꿉니다. 못 바꾸면 오류 창을 띄우고 None."""
        try:
            return paths.to_canonical(folder_path)
        except paths.PathMapError as exc:
            QMessageBox.critical(parent, "경로를 저장할 수 없음", f"고른 폴더를 공유 설정에 저장할 경로로 바꾸지 못했습니다.\n\n{exc}")
            return None

    def _refresh_work_path_table(self, table):
        table.clear()
        for work_name, path in sorted(self.work_paths.items()):
            text = f"{work_name}: {path}"
            if paths.IS_WINDOWS:
                try:
                    text += f"\n    → {paths.to_native(path)}"
                except paths.PathMapError:
                    text += "\n    → 변환표에 없음 (path_map.json 확인)"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, work_name)
            table.addItem(item)

    def _confirm_work_paths_password(self, parent=None):
        """작품 경로 관리 비밀번호를 확인합니다 (파일이 없으면 최초 설정). 확인되면 True. 문제는 창으로 알립니다."""
        parent = parent or self
        try:
            password_hash = self.load_password_hash()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(parent, "비밀번호 파일 오류", f"비밀번호 파일을 읽지 못했습니다:\n{self.work_paths_password_file}\n\n{exc}")
            return False

        if password_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            password, ok = QInputDialog.getText(
                parent,
                "비밀번호 설정",
                "작품 경로 관리를 위한 비밀번호를 설정하세요:\n(처음 한 번만 설정하면 됩니다)",
                echo=QLineEdit.Password
            )
            if not ok or not password:
                return False

            password_confirm, ok = QInputDialog.getText(
                parent,
                "비밀번호 확인",
                "비밀번호를 다시 입력하세요:",
                echo=QLineEdit.Password
            )
            if not ok:
                return False

            if password != password_confirm:
                QMessageBox.warning(parent, "오류", "비밀번호가 일치하지 않습니다.")
                return False

            try:
                self.set_password(password)
            except OSError as exc:
                QMessageBox.critical(parent, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
                return False
            QMessageBox.information(parent, "설정 완료", "비밀번호가 설정되었습니다.")
            return True

        # 비밀번호 입력 요청
        password, ok = QInputDialog.getText(
            parent,
            "비밀번호 입력",
            "작품 경로 관리를 위해 비밀번호를 입력하세요:",
            echo=QLineEdit.Password
        )
        if not ok:
            return False
        if not self.verify_password(password):
            QMessageBox.warning(parent, "오류", "비밀번호가 올바르지 않습니다.")
            return False
        return True

    def manage_work_paths(self):
        """작품 경로 관리 다이얼로그를 표시합니다."""
        # 공유 설정에 문제가 있으면 관리 금지 (깨진 파일을 빈 목록으로 덮어쓰거나 새 비밀번호를 받지 않도록)
        if self.shared_config_problem or self.work_paths_config_dir is None:
            QMessageBox.warning(
                self, "작품 경로 관리",
                f"공유 설정에 문제가 있어 작품 경로를 관리할 수 없습니다.\n\n{self.shared_config_problem or '공유 설정 폴더 없음'}",
            )
            return
        if not self._confirm_work_paths_password():
            return

        # 비밀번호 확인 후 다이얼로그 표시
        dialog = QDialog(self)
        dialog.setWindowTitle("작품 경로 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(700, 500)
        
        # 다크 테마 스타일 적용
        dialog.setStyleSheet("""
QDialog {
    background: #232323;
    color: #e0e0e0;
}
QLabel {
    color: #e0e0e0;
    background: transparent;
}
QPushButton {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    color: #fafafa;
    font-weight: 500;
    padding: 8px 16px;
}
QPushButton:hover {
    background: #353535;
    border: 1px solid #ff9900;
    color: #ff9900;
}
QPushButton:pressed {
    background: #1a1a1a;
    border: 1px solid #ff9900;
}
QListWidget {
    background: #232323;
    border: 1px solid #444;
    color: #fafafa;
    selection-background-color: #444;
    selection-color: #ff9900;
    alternate-background-color: #2a2a2a;
}
QListWidget::item:selected {
    background: #444;
    color: #ff9900;
}
QListWidget::item:hover {
    background: #353535;
}
QScrollBar:vertical {
    background: #232323;
    border: 1px solid #444;
    border-radius: 6px;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #ff9900;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
""")
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("작품별 경로를 관리할 수 있습니다. 경로를 수정하거나 작품을 추가/삭제할 수 있습니다.")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # 작품 경로 리스트
        table = QListWidget()
        table.setAlternatingRowColors(True)
        
        self._refresh_work_path_table(table)

        layout.addWidget(table)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 추가 버튼
        add_button = QPushButton("작품 추가")
        add_button.clicked.connect(lambda: self.add_work_path(table, dialog))
        button_layout.addWidget(add_button)
        
        # 수정 버튼
        edit_button = QPushButton("경로 수정")
        edit_button.clicked.connect(lambda: self.edit_work_path(table, dialog))
        button_layout.addWidget(edit_button)
        
        # 삭제 버튼
        delete_button = QPushButton("작품 삭제")
        delete_button.clicked.connect(lambda: self.delete_work_path(table, dialog))
        button_layout.addWidget(delete_button)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # 비밀번호 변경 버튼 레이아웃
        password_layout = QHBoxLayout()
        password_button = QPushButton("비밀번호 변경")
        password_button.clicked.connect(lambda: self.change_password(dialog))
        password_layout.addWidget(password_button)
        if paths.IS_WINDOWS:
            auto_button = QPushButton("변환표 자동 설정")
            auto_button.setToolTip(
                "이 PC에 연결된 네트워크 드라이브에서 작품 폴더가 열리는 곳을 찾아 path_map.json을 만들거나 보충합니다."
            )

            def on_auto_setup():
                self.auto_setup_path_map(ask_password=False, parent=dialog)
                if self.shared_config_problem:
                    # 다시 읽기에 실패해 work_paths가 빈 목록일 수 있음 — 관리 창을 닫아 그대로 덮어쓰지 않게 함
                    dialog.reject()
                else:
                    self._refresh_work_path_table(table)

            auto_button.clicked.connect(on_auto_setup)
            password_layout.addWidget(auto_button)
        password_layout.addStretch()
        layout.addLayout(password_layout)
        
        dialog.setLayout(layout)
        
        dialog.exec_()

    def add_work_path(self, table, dialog):
        """새로운 작품 경로를 추가합니다."""
        work_name, ok = QInputDialog.getText(
            dialog, 
            "작품 추가", 
            "작품 이름을 입력하세요:",
            text=""
        )
        if not ok or not work_name:
            return
        
        if work_name in self.work_paths:
            QMessageBox.warning(dialog, "오류", f"'{work_name}' 작품은 이미 존재합니다.")
            return
        
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택")
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            del self.work_paths[work_name]
            return

        # 콤보박스에도 추가
        if work_name not in [self.workComboBox.itemText(i) for i in range(self.workComboBox.count())]:
            self.workComboBox.addItem(work_name)
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "추가 완료", f"'{work_name}' 작품이 추가되었습니다.")

    def edit_work_path(self, table, dialog):
        """선택된 작품의 경로를 수정합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "수정할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        try:
            start_dir = paths.to_native(self.work_paths.get(work_name, ""))
        except paths.PathMapError:
            start_dir = ""  # 선택 창의 시작 위치만 정하는 값 (고른 경로는 저장 전에 다시 검사함)
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택", start_dir)
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        previous = self.work_paths.get(work_name)
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            self.work_paths[work_name] = previous
            return
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "수정 완료", f"'{work_name}' 작품의 경로가 수정되었습니다.")

    def delete_work_path(self, table, dialog):
        """선택된 작품을 삭제합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "삭제할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        reply = QMessageBox.question(
            dialog,
            "작품 삭제",
            f"'{work_name}' 작품을 삭제하시겠습니까?\n\n경로: {self.work_paths.get(work_name, '')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            previous = self.work_paths.pop(work_name, None)
            if not self.save_work_paths(dialog):
                if previous is not None:
                    self.work_paths[work_name] = previous
                return
            index = self.workComboBox.findText(work_name)
            if index >= 0:
                self.workComboBox.removeItem(index)
            self._refresh_work_path_table(table)
            QMessageBox.information(dialog, "삭제 완료", f"'{work_name}' 작품이 삭제되었습니다.")

    def change_password(self, dialog):
        """비밀번호를 변경합니다."""
        # 현재 비밀번호 확인
        current_password, ok = QInputDialog.getText(
            dialog,
            "현재 비밀번호 확인",
            "현재 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if not self.verify_password(current_password):
            QMessageBox.warning(dialog, "오류", "현재 비밀번호가 올바르지 않습니다.")
            return
        
        # 새 비밀번호 입력
        new_password, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 설정",
            "새 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok or not new_password:
            return
        
        # 새 비밀번호 확인
        new_password_confirm, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 확인",
            "새 비밀번호를 다시 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if new_password != new_password_confirm:
            QMessageBox.warning(dialog, "오류", "새 비밀번호가 일치하지 않습니다.")
            return
        
        # 비밀번호 변경
        try:
            self.set_password(new_password)
        except OSError as exc:
            QMessageBox.critical(dialog, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
            return
        QMessageBox.information(dialog, "변경 완료", "비밀번호가 변경되었습니다.")

    def switch_to_list_mode(self):
        self.listModeButton.setChecked(True)
        self.thumbnailModeButton.setChecked(False)
        self.sidebar.setViewMode(QListWidget.ListMode)
        self.sidebar.setSpacing(0)  # 리스트 아이템 사이 공란 제거
        self.is_thumbnail_mode = False
        
        # 사이드바 폭을 원래대로 되돌리기
        if self.default_sidebar_width is not None:
            self.sidebar.setFixedWidth(self.default_sidebar_width)
            print(f"사이드바 폭을 원래대로 복원: {self.default_sidebar_width}")
        
        self.update_sidebar_display()

    def switch_to_thumbnail_mode(self):
        print("썸네일 모드로 전환 시작")
        
        # 완료된 워커들만 정리 (실행 중인 워커는 유지)
        self.cleanup_thumbnail_workers()
        
        # 메모리 정리 (지연 시간 단축)
        QApplication.processEvents()
        import gc
        gc.collect()
        
        self.listModeButton.setChecked(False)
        self.thumbnailModeButton.setChecked(True)
        self.sidebar.setViewMode(QListWidget.ListMode)  # ListMode로 변경
        self.sidebar.setIconSize(QSize(self.thumbnail_size, self.thumbnail_size))
        self.sidebar.setSpacing(10)
        self.is_thumbnail_mode = True
        print(f"썸네일 모드 설정 완료: iconSize={self.sidebar.iconSize()}, viewMode={self.sidebar.viewMode()}")
        
        # 사이드바 폭을 2배로 조정
        if self.default_sidebar_width is None:
            # 기본 폭이 설정되지 않은 경우 현재 폭을 기본값으로 저장
            self.default_sidebar_width = self.sidebar.width()
            print(f"기본 사이드바 폭 저장: {self.default_sidebar_width}")
        
        # 사이드바 폭을 2배로 설정
        new_width = self.default_sidebar_width * 2
        self.sidebar.setFixedWidth(new_width)
        print(f"사이드바 폭을 2배로 조정: {self.default_sidebar_width} -> {new_width}")
        
        # 캐시된 썸네일을 즉시 적용
        cached_count = 0
        new_generation_count = 0
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is None:
                continue  # None인 경우 건너뛰기
            file_path = item.data(Qt.UserRole)
            if file_path and os.path.isfile(file_path):
                if self._has_disk_thumbnail(file_path):
                    print(f"캐시된 썸네일 즉시 적용: {file_path}")
                    file_hash = paths.thumbnail_key(file_path)
                    thumbnail_path = os.path.join(self.current_thumbnail_folder, f"{file_hash}.jpg")
                    pixmap = QPixmap(thumbnail_path)
                    if not pixmap.isNull():
                        self.update_sidebar_item_thumbnail(file_path, pixmap)
                        cached_count += 1
                    else:
                        print(f"새 썸네일 생성 예정: {file_path}")
                        new_generation_count += 1
                else:
                    print(f"새 썸네일 생성 예정: {file_path}")
                    new_generation_count += 1
        
        print(f"캐시된 썸네일 {cached_count}개 즉시 적용 완료")
        
        # 즉시 사이드바 업데이트 (지연 없이)
        self.update_sidebar_display()

    def cleanup_all_thumbnail_workers(self):
        """모든 썸네일 워커를 강제로 정리합니다."""
        try:
            print("모든 썸네일 워커 정리 시작")
            for worker in self.thumbnail_workers:
                try:
                    worker.stop()
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 정리 중 오류: {e}")
            
            self.thumbnail_workers.clear()
            print("모든 썸네일 워커 정리 완료")
        except Exception as e:
            print(f"워커 전체 정리 중 오류: {e}")

    def update_sidebar_display(self):
        """사이드바 아이템들을 현재 모드에 맞게 업데이트합니다."""
        print(f"사이드바 디스플레이 업데이트: thumbnail_mode={self.is_thumbnail_mode}, item_count={self.sidebar.count()}")
        
        if self.is_thumbnail_mode:
            self.generate_thumbnails_for_all_items()
        else:
            self.clear_thumbnails()

    def generate_thumbnails_for_all_items(self):
        """모든 사이드바 아이템에 대해 썸네일을 생성합니다."""
        print(f"모든 아이템 썸네일 생성 시작: {self.sidebar.count()}개 아이템")
        self.cleanup_thumbnail_workers()
        cached_count = 0
        new_generation_count = 0
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is None:
                continue  # None인 경우 건너뛰기
            file_path = item.data(Qt.UserRole)
            if file_path and os.path.isfile(file_path):
                if self._has_disk_thumbnail(file_path):
                    print(f"캐시된 썸네일 즉시 적용: {file_path}")
                    file_hash = paths.thumbnail_key(file_path)
                    thumbnail_path = os.path.join(self.current_thumbnail_folder, f"{file_hash}.jpg")
                    pixmap = QPixmap(thumbnail_path)
                    if not pixmap.isNull():
                        self.update_sidebar_item_thumbnail(file_path, pixmap)
                        cached_count += 1
                    else:
                        print(f"새 썸네일 생성 예정: {file_path}")
                        new_generation_count += 1
                else:
                    print(f"새 썸네일 생성 예정: {file_path}")
                    new_generation_count += 1
        print(f"썸네일 처리 완료: 캐시 사용 {cached_count}개, 새 생성 {new_generation_count}개")
        # 진행바 설정
        if new_generation_count > 0:
            self.thumbnailProgressBar.setMaximum(new_generation_count)
            self.thumbnailProgressBar.setValue(0)
            self.thumbnailProgressBar.setFormat('썸네일 생성 중: %v/%m')
            self.thumbnailProgressBar.setVisible(True)
        else:
            self.thumbnailProgressBar.setMaximum(100)
            self.thumbnailProgressBar.setValue(100)
            self.thumbnailProgressBar.setFormat('썸네일 모두 캐시됨')
            self.thumbnailProgressBar.setVisible(True)
        if new_generation_count > 0:
            batch_size = 3
            total_items = self.sidebar.count()
            generated_count = 0
            for batch_start in range(0, total_items, batch_size):
                batch_end = min(batch_start + batch_size, total_items)
                print(f"배치 처리: {batch_start+1}-{batch_end}/{total_items}")
                for i in range(batch_start, batch_end):
                    item = self.sidebar.item(i)
                    if item is None:
                        continue  # None인 경우 건너뛰기
                    file_path = item.data(Qt.UserRole)
                    if file_path and os.path.isfile(file_path):
                        if not self._has_disk_thumbnail(file_path):
                            self.generate_thumbnail(file_path)
                            generated_count += 1
                            self.thumbnailProgressBar.setValue(generated_count)
                            QApplication.processEvents()
                QApplication.processEvents()
                import time
                time.sleep(0.2)
                self.cleanup_thumbnail_workers()
                import gc
                gc.collect()
            self.thumbnailProgressBar.setValue(new_generation_count)
            self.thumbnailProgressBar.setFormat('썸네일 생성 완료')
        # 새로운 썸네일이 생성된 경우에만 팝업창 띄우기
        if new_generation_count > 0:
            total_files = self.sidebar.count()
            cached_count = total_files - new_generation_count
            QMessageBox.information(self, "썸네일 생성 완료", 
                                  f"썸네일 처리가 완료되었습니다.\n\n"
                                  f"• 전체 파일 수: {total_files}개\n"
                                  f"• 기존 캐시 사용: {cached_count}개\n"
                                  f"• 새로 생성: {new_generation_count}개")
            
        else:
            print("모든 썸네일이 캐시에 있어서 새로 생성할 필요가 없습니다.")
            self.thumbnailProgressBar.setFormat('썸네일 모두 디스크에 저장됨')
            self.thumbnailProgressBar.setValue(self.thumbnailProgressBar.maximum())

    def cleanup_thumbnail_workers(self):
        """완료된 워커들을 정리합니다."""
        try:
            # 완료된 워커들 제거
            self.thumbnail_workers = [w for w in self.thumbnail_workers if w.isRunning()]
            print(f"워커 정리 완료: 현재 워커 수 {len(self.thumbnail_workers)}")
        except Exception as e:
            print(f"워커 정리 중 오류: {e}")

    def cleanup_background_threads(self):
        """모든 백그라운드 스레드를 안전하게 정리합니다."""
        try:
            print("백그라운드 스레드 정리 시작...")
            
            # 백그라운드 썸네일 로딩 타이머 중지
            if hasattr(self, 'thumbnail_loading_timer'):
                self.thumbnail_loading_timer.stop()
                print("썸네일 로딩 타이머 중지됨")
            
            # 백그라운드 썸네일 로더 워커 중지 및 대기
            if hasattr(self, 'thumbnail_loader_worker') and self.thumbnail_loader_worker:
                if self.thumbnail_loader_worker.isRunning():
                    print("백그라운드 썸네일 로더 워커 중지 중...")
                    self.thumbnail_loader_worker.stop()
                    self.thumbnail_loader_worker.wait(5000)  # 5초 대기
                    if self.thumbnail_loader_worker.isRunning():
                        print("워커 강제 종료")
                        self.thumbnail_loader_worker.terminate()
                        self.thumbnail_loader_worker.wait(3000)
                    # deleteLater() 호출하여 안전하게 삭제
                    self.thumbnail_loader_worker.deleteLater()
                    self.thumbnail_loader_worker = None
                    print("백그라운드 썸네일 로더 워커 정리 완료")
            
            # 모든 썸네일 워커를 안전하게 중지
            print(f"썸네일 워커 {len(self.thumbnail_workers)}개 중지 중...")
            for worker in self.thumbnail_workers:
                try:
                    if worker.isRunning():
                        worker.stop()
                        worker.wait(3000)  # 3초 대기
                        if worker.isRunning():
                            worker.terminate()
                            worker.wait(2000)
                    # deleteLater() 호출하여 안전하게 삭제
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 중지 중 오류: {e}")
            
            # 워커 리스트 클리어
            self.thumbnail_workers.clear()
            
            # 추가 대기 시간
            import time
            time.sleep(0.5)
            
            # UI 업데이트 처리
            QApplication.processEvents()
            
            print("모든 백그라운드 스레드 정리 완료")
            
        except Exception as e:
            print(f"백그라운드 스레드 정리 중 오류: {e}")

    def _has_disk_thumbnail(self, file_path):
        """디스크에 썸네일이 있는지 확인합니다."""
        if not self.current_thumbnail_folder:
            return False
        file_hash = paths.thumbnail_key(file_path)
        thumbnail_path = os.path.join(self.current_thumbnail_folder, f"{file_hash}.jpg")
        return os.path.exists(thumbnail_path)

    def generate_thumbnail(self, file_path):
        import time
        print(f"썸네일 생성 시작: {file_path}")
        
        # 썸네일 폴더가 설정되지 않은 경우 드래그한 폴더에 생성
        if not self.current_thumbnail_folder:
            if hasattr(self, 'selected_folder_path') and self.selected_folder_path:
                # 드래그한 폴더가 있는 경우
                thumbnail_folder = os.path.join(self.selected_folder_path, ".yesoncheck_thumb")
                if not os.path.exists(thumbnail_folder):
                    os.makedirs(thumbnail_folder)
                    print(f"generate_thumbnail에서 썸네일 폴더 생성: {thumbnail_folder}")
                self.current_thumbnail_folder = thumbnail_folder
                print(f"generate_thumbnail에서 썸네일 폴더 설정: {thumbnail_folder}")
            else:
                # 개별 파일들을 드래그한 경우, 첫 번째 파일의 디렉토리에 썸네일 폴더 생성
                if os.path.exists(file_path):
                    file_dir = os.path.dirname(file_path)
                    thumbnail_folder = os.path.join(file_dir, ".yesoncheck_thumb")
                    if not os.path.exists(thumbnail_folder):
                        os.makedirs(thumbnail_folder)
                        print(f"generate_thumbnail에서 파일 디렉토리에 썸네일 폴더 생성: {thumbnail_folder}")
                    self.current_thumbnail_folder = thumbnail_folder
                    print(f"generate_thumbnail에서 파일 디렉토리에 썸네일 폴더 설정: {thumbnail_folder}")
                else:
                    print("썸네일 폴더를 설정할 수 없음")
                    return False
        
        # 동시 실행 제한 (1개로 더 줄임)
        # 디스크에 저장된 썸네일 확인
        if self.current_thumbnail_folder:
            file_hash = paths.thumbnail_key(file_path)
            thumbnail_path = os.path.join(self.current_thumbnail_folder, f"{file_hash}.jpg")
            
            if os.path.exists(thumbnail_path):
                print(f"디스크에서 썸네일 로드: {thumbnail_path}")
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    # UI 업데이트
                    self.update_sidebar_item_thumbnail(file_path, pixmap)
                    return
                else:
                    print(f"디스크 썸네일이 손상됨, 재생성: {thumbnail_path}")
                    try:
                        os.remove(thumbnail_path)
                    except:
                        pass
        max_workers = 1
        while len(self.thumbnail_workers) >= max_workers:
            QApplication.processEvents()
            time.sleep(0.2)  # 대기 시간을 늘려서 메모리 부하 감소
            # 완료된 워커들 정리
            self.cleanup_thumbnail_workers()

        # 워커 생성
        worker = ThumbnailWorker(file_path, self.thumbnail_size, self.current_thumbnail_folder)
        worker.thumbnail_ready.connect(self.on_thumbnail_ready)
        
        # 안전한 워커 제거 함수
        def safe_remove_worker():
            try:
                if hasattr(self, 'thumbnail_workers') and worker in self.thumbnail_workers:
                    self.thumbnail_workers.remove(worker)
                    print(f"워커 제거 완료: {file_path}")
            except Exception as e:
                print(f"워커 제거 중 에러: {e}")
            finally:
                try:
                    if worker.isRunning():
                        worker.stop()  # 안전한 중지
                        worker.wait(2000)
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 정리 중 오류: {e}")
        
        worker.finished.connect(safe_remove_worker)
        self.thumbnail_workers.append(worker)
        worker.start()
        print(f"썸네일 워커 시작: {file_path}, 현재 워커 수: {len(self.thumbnail_workers)}")

    def on_thumbnail_ready(self, file_path, pixmap):
        """썸네일 생성이 완료되었을 때 호출됩니다."""
        try:
            print(f"썸네일 생성 완료: {file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap: {file_path}")
                return
            
            # 사이드바 아이템 업데이트
            self.update_sidebar_item_thumbnail(file_path, pixmap)
            
        except Exception as e:
            print(f"썸네일 준비 완료 처리 중 오류: {file_path}, 오류: {e}")
        finally:
            # 메모리 정리
            import gc
            gc.collect()

    def update_sidebar_item_thumbnail(self, file_path, pixmap):
        """사이드바 아이템의 썸네일을 업데이트합니다."""
        try:
            print(f"썸네일 아이템 업데이트 시작: {file_path}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap으로 업데이트 시도: {file_path}")
                return
            
            # 사이드바에서 해당 파일을 찾아 썸네일 설정
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item and paths.same_path(item.data(Qt.UserRole), file_path):
                    # 아이콘 설정
                    item.setIcon(QIcon(pixmap))
                    print(f"썸네일 아이템 업데이트 완료: {file_path}")
                    break
                    
        except Exception as e:
            print(f"썸네일 아이템 업데이트 중 오류: {file_path}, 오류: {e}")
        finally:
            # 메모리 정리
            QApplication.processEvents()

    def clear_thumbnails(self):
        """리스트 모드에서 썸네일을 제거합니다."""
        try:
            # 실행 중인 워커들만 중지
            for worker in self.thumbnail_workers:
                try:
                    worker.stop()
                except:
                    pass
            self.thumbnail_workers.clear()
            
            # UI에서만 썸네일 제거 (디스크 썸네일은 유지)
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item:
                    item.setIcon(QIcon())
                    # 파일명만 표시
                    file_path = item.data(Qt.UserRole)
                    if file_path:
                        filename = os.path.basename(file_path)
                        item.setText(filename)
            print("썸네일 UI 제거 완료 (디스크 썸네일 유지)")
        except Exception as e:
            print(f"썸네일 제거 중 오류: {e}")

    def get_current_job_path(self):
        """현재 선택된 job의 경로를 반환합니다."""
        try:
            # 1. 선택된 폴더 경로가 있으면 우선 사용 (북마크, 드래그앤드롭 등)
            if hasattr(self, 'selected_folder_path') and self.selected_folder_path:
                if os.path.exists(self.selected_folder_path):
                    print(f"선택된 폴더 경로 사용: {self.selected_folder_path}")
                    return self.selected_folder_path
                else:
                    print(f"선택된 폴더 경로가 존재하지 않음: {self.selected_folder_path}")
            
            # 2. UI에서 job 선택으로 설정된 경로가 있으면 사용
            if hasattr(self, 'current_job_path') and self.current_job_path:
                if os.path.exists(self.current_job_path):
                    print(f"UI job 선택 경로 사용: {self.current_job_path}")
                    return self.current_job_path
                else:
                    print(f"UI job 선택 경로가 존재하지 않음: {self.current_job_path}")
            
            # 3. 경로를 찾을 수 없는 경우
            print("Job 경로를 찾을 수 없음")
            return None
                
        except Exception as e:
            print(f"Job 경로 조회 중 오류: {e}")
            return None

    def setup_thumbnail_folder(self):
        """현재 job에 대한 썸네일 폴더를 설정합니다."""
        try:
            # 이미 썸네일 폴더가 설정되어 있으면 그대로 사용
            if hasattr(self, 'current_thumbnail_folder') and self.current_thumbnail_folder:
                print(f"이미 설정된 썸네일 폴더 사용: {self.current_thumbnail_folder}")
                return True
            
            # job 경로를 찾아서 썸네일 폴더 설정
            job_path = self.get_current_job_path()
            if job_path:
                thumbnail_folder = os.path.join(job_path, ".yesoncheck_thumb")
                
                # 폴더가 없으면 생성
                if not os.path.exists(thumbnail_folder):
                    os.makedirs(thumbnail_folder)
                    print(f"썸네일 폴더 생성: {thumbnail_folder}")
                
                self.current_thumbnail_folder = thumbnail_folder
                print(f"썸네일 폴더 설정: {thumbnail_folder}")
                return True
            else:
                self.current_thumbnail_folder = None
                print("Job 경로를 찾을 수 없어 썸네일 폴더를 설정하지 않음")
                return False
        except Exception as e:
            print(f"썸네일 폴더 설정 중 오류: {e}")
            self.current_thumbnail_folder = None
            return False

    def start_background_thumbnail_loading(self):
        """백그라운드에서 썸네일 로딩을 시작합니다."""
        try:
            if not self.current_thumbnail_folder:
                print("썸네일 폴더가 설정되지 않음")
                return
            
            # 현재 사이드바의 파일 목록 수집
            current_files = []
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item:
                    file_path = item.data(Qt.UserRole)
                    if file_path and os.path.isfile(file_path):
                        current_files.append(file_path)
            
            if not current_files:
                print("로딩할 파일이 없음")
                return
            
            print(f"백그라운드 썸네일 로딩 시작: {len(current_files)}개 파일")
            
            # 기존 로더 워커가 있다면 중지
            if self.thumbnail_loader_worker and self.thumbnail_loader_worker.isRunning():
                self.thumbnail_loader_worker.stop()
                self.thumbnail_loader_worker.wait(3000)
                if self.thumbnail_loader_worker.isRunning():
                    self.thumbnail_loader_worker.terminate()
                    self.thumbnail_loader_worker.wait(2000)
                self.thumbnail_loader_worker.deleteLater()
                self.thumbnail_loader_worker = None
            
            # 새로운 로더 워커 생성
            self.thumbnail_loader_worker = ThumbnailLoaderWorker(self.current_thumbnail_folder, current_files)
            self.thumbnail_loader_worker.thumbnail_loaded.connect(self.on_background_thumbnail_loaded)
            self.thumbnail_loader_worker.loading_finished.connect(self.on_background_loading_finished)
            self.thumbnail_loader_worker.start()
            
        except Exception as e:
            print(f"백그라운드 썸네일 로딩 시작 중 오류: {e}")

    def on_background_thumbnail_loaded(self, file_path, pixmap):
        """백그라운드에서 썸네일이 로드되었을 때 호출됩니다."""
        try:
            # 캐시에 저장
            
            
            # UI 업데이트
            self.update_sidebar_item_thumbnail(file_path, pixmap)
            
        except Exception as e:
            print(f"백그라운드 썸네일 로드 처리 중 오류: {file_path}, 오류: {e}")

    def on_background_loading_finished(self):
        """백그라운드 로딩이 완료되었을 때 호출됩니다."""
        try:
            print("백그라운드 썸네일 로딩 완료")
            
            # 로더 워커 정리
            if self.thumbnail_loader_worker:
                # 워커가 실행 중이면 중지
                if self.thumbnail_loader_worker.isRunning():
                    self.thumbnail_loader_worker.stop()
                    self.thumbnail_loader_worker.wait(2000)
                # 안전하게 삭제
                self.thumbnail_loader_worker.deleteLater()
                self.thumbnail_loader_worker = None
            
        except Exception as e:
            print(f"백그라운드 로딩 완료 처리 중 오류: {e}")

    def schedule_background_thumbnail_loading(self):
        """백그라운드 썸네일 로딩을 스케줄링합니다."""
        try:
            # 0.5초 후에 백그라운드 로딩 시작 (3초에서 0.5초로 단축)
            self.thumbnail_loading_timer.start(500)
            print("백그라운드 썸네일 로딩 스케줄링 (0.5초 후)")
        except Exception as e:
            print(f"백그라운드 로딩 스케줄링 중 오류: {e}")

        def cleanup_thumbnail_folder(self):
            """현재 job의 썸네일 폴더를 정리합니다."""
            try:
                if self.current_thumbnail_folder and os.path.exists(self.current_thumbnail_folder):
                    # 원본 파일이 존재하지 않는 썸네일들 삭제
                    import hashlib
                    for filename in os.listdir(self.current_thumbnail_folder):
                        if filename.endswith('.jpg'):
                            thumbnail_path = os.path.join(self.current_thumbnail_folder, filename)
                            try:
                                pixmap = QPixmap(thumbnail_path)
                                if pixmap.isNull():
                                    os.remove(thumbnail_path)
                                    print(f"손상된 썸네일 삭제: {thumbnail_path}")
                            except Exception:
                                try:
                                    os.remove(thumbnail_path)
                                    print(f"손상된 썸네일 삭제: {thumbnail_path}")
                                except Exception:
                                    pass
                    print(f"썸네일 폴더 정리 완료: {self.current_thumbnail_folder}")
            except Exception as e:
                print(f"썸네일 폴더 정리 중 오류: {e}")

    def get_thumbnail_disk_usage(self):
        """현재 썸네일 폴더의 디스크 사용량을 반환합니다."""
        try:
            if not self.current_thumbnail_folder or not os.path.exists(self.current_thumbnail_folder):
                return {'total_size': 0, 'file_count': 0, 'folder_path': self.current_thumbnail_folder}
            
            total_size = 0
            file_count = 0
            
            for filename in os.listdir(self.current_thumbnail_folder):
                if filename.endswith('.jpg'):
                    file_path = os.path.join(self.current_thumbnail_folder, filename)
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
                        file_count += 1
            
            return {
                'total_size': total_size,
                'file_count': file_count,
                'folder_path': self.current_thumbnail_folder
            }
            
        except Exception as e:
            print(f"썸네일 디스크 사용량 계산 중 오류: {e}")
            return {'total_size': 0, 'file_count': 0, 'folder_path': self.current_thumbnail_folder}
