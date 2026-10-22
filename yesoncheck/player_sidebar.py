"""Media library and sidebar helpers for VideoPlayer."""

import contextlib
import functools
import os
import shutil
import stat
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QWIDGETSIZE_MAX,
)

from yesoncheck.workers import ThumbnailLoaderWorker, ThumbnailWorker
import traceback

from yesoncheck import paths, thumbnails, video_list
# PlayerSidebarMixin의 부모 믹스인 (북마크, 선택 재생, 공유 설정·작품 경로)
from yesoncheck.sidebar_bookmarks import SidebarBookmarksMixin
from yesoncheck.sidebar_playlist import SidebarPlaylistMixin
from yesoncheck.sidebar_config_paths import SidebarConfigPathsMixin
# 다시 내보내기만 함 (이 모듈은 안 씀): 기존 `from yesoncheck.player_sidebar import …`·`player_sidebar.X` 접근이 같은 객체로 돌게.
# 시험이 바꿔치기하는 gather_shared_config·list_works_not_opening은 믹스인이 shared_config_load.X로 불러 바꿔치기 지점을 그 모듈
# 한 곳으로 둠 (여기서 이 이름을 바꿔치기해도 닿지 않음)
from yesoncheck.shared_config_load import (
    SharedConfigLoad,
    gather_shared_config,
    list_works_not_opening,
)
from yesoncheck.sidebar_items import (
    ACTIVATION_REFRESH_GAP_FACTOR,
    ACTIVATION_REFRESH_GAP_S,
    LIST_FOLDER_GONE,
    LIST_READ_FAILED,
    NO_SEASON_WORKS,
    SIDEBAR_SOURCE_ROLE,
    THUMBNAIL_CONTEXT_ROLE,
    THUMBNAIL_FOLDER_PROBLEM,
    THUMBNAIL_MAKE_FAILED,
    THUMBNAIL_SAVE_FAILED,
    THUMBNAIL_VIDEO_PROBLEM,
    ThumbnailContext,
)



class SidebarScan(QThread):
    """사이드바 목록 다시 읽기의 디스크 읽기(video_list.read_sources — Qt 없음)를 GUI 밖에서. 목록은 건드리지 않고 결과만
    scanned 신호로 GUI 스레드에 (창의 _on_sidebar_scanned가 목록을 맞춤).

    부모 없이 만들고 창이 붙잡음 (_sidebar_scan, 결과를 받을 때까지). 창을 닫을 때 실행 중이면 release_worker로 넘김:
    끝날 때까지 붙잡아 두고(실행 중인 QThread가 파괴되면 앱이 죽음) 앱이 끝나기 전에 wait_for_released_workers가 정해진
    시간까지 기다림 (응답 없는 NAS를 읽는 중일 수 있음).
    """

    scanned = pyqtSignal(object)  # 이 SidebarScan (read·elapsed·unexpected를 채움)

    def __init__(self, sources, files, generation, check_thumbnails=False):
        super().__init__()
        self.sources = sources  # 읽을 곳 (video_list.ListSource)
        self.files = files  # 있는지 확인할 따로 넣은 파일
        self.generation = generation  # 읽기 시작할 때의 사이드바 세대 번호 (결과를 넣을 때 목록이 그대로인지)
        # 이 읽기를 시작할 때까지 누른 새로고침 버튼·F5의 썸네일 확인 요청 (결과를 넣을 때 씀 — _on_sidebar_scanned)
        self.check_thumbnails = check_thumbnails
        self.read = None  # video_list.SourcesRead
        self.elapsed = None
        self.unexpected = None  # 예상 못 한 오류의 스택 트레이스 (GUI 스레드가 창으로)

    def run(self):
        started = time.perf_counter()
        try:
            self.read = video_list.read_sources(self.sources, self.files)
        except Exception:
            # 예상 못 한 오류도 삼키지 않음: 로그에 스택 트레이스째 남기고 GUI 스레드가 창으로 알림
            self.unexpected = traceback.format_exc()
            print(f"[목록] 다시 읽다 예상치 못한 오류:\n{self.unexpected}", file=sys.stderr, flush=True)
        self.elapsed = time.perf_counter() - started
        self.scanned.emit(self)


class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin):

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
            read_failed = False  # 읽지 못한 폴더가 있음 (창으로 알림 — '지원되는 비디오 파일이 없습니다'는 띄우지 않음)
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
                    if folder_files is None:
                        read_failed = True
                        parent._register_unread_folder(local_path)  # 연결이 돌아오면 새로고침(F5)으로 들어옴
                        continue
                    folder_files.sort()  # 이름 순서대로 정렬
                    video_files.extend(folder_files)
            
            # 폴더가 포함된 경우 북마크에 자동 추가
            if folder_paths:
                parent.add_dropped_folders_to_bookmarks(folder_paths)
            
            # 비디오 파일 처리
            if has_folder:
                # 폴더가 포함된 경우: 기존 사이드바 초기화 후 모든 파일을 사이드바에 추가하고 첫 번째 파일을 Video A에 로드
                if video_files:
                    # 첫 폴더의 썸네일 폴더를 씀 (전에 고른 job·폴더가 아니라)
                    parent._use_dropped_folder_for_thumbnails(folder_paths[0])
                    
                    # 기존 사이드바 리스트 초기화
                    parent.sidebar.clear()
                    parent.add_files_to_sidebar(video_files, folder_paths)
                    # 첫 번째 파일을 Video A에 로드
                    parent.open_file('A', video_files[0])
                    # 백그라운드 로딩 스케줄링
                    parent.schedule_background_thumbnail_loading()
                    QMessageBox.information(parent, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
                elif not read_failed:
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
        return os.path.splitext(file_path.lower())[1] in video_list.VIDEO_EXTENSIONS

    def add_files_to_sidebar(self, file_paths, folders=()):
        """사이드바에 파일들을 추가 (항상 번호순 정렬).

        folders: 끌어다 놓은 폴더 — 그 아래 파일은 그 폴더에서 들어온 것으로 기억 (목록 다시 읽기가 그 폴더를 같은 규칙으로
        다시 읽음). 나머지는 따로 넣은 파일 (다시 읽을 때 파일이 있는 동안만 목록에).
        폴더 A와 그 안의 A/sub를 함께 끌어다 놓으면 A/sub의 영상은 폴더마다 한 번씩 두 번 들어오므로 하나는 A, 하나는 A/sub에서
        들어온 것으로 (같은 영상의 n번째는 그 영상을 담은 n번째 폴더) — 다시 읽어도 출처마다 한 번씩이라 늘지 않음.
        """
        file_paths = sorted(file_paths, key=video_list.natural_key)
        sources = [self._register_sidebar_source(video_list.ListSource("folder", folder)) for folder in folders]
        unclaimed = {}  # path_key → 그 영상을 담은 폴더 중 아직 항목을 정하지 않은 것

        def source_of(file_path):
            key = paths.path_key(file_path)
            if key not in unclaimed:
                unclaimed[key] = [source for source in sources if video_list.is_under(file_path, source.folder)]
            return unclaimed[key].pop(0) if unclaimed[key] else None

        # 항목마다 지금의 썸네일 자리를 기억 (이미 목록에 있는 영상이면 그 항목의 자리)
        items = self._add_sidebar_videos(
            [(os.path.basename(file_path), file_path, source_of(file_path))
             for file_path in file_paths if os.path.exists(file_path)])
        # 썸네일 모드인 경우 썸네일 생성. 영상·자리를 미리 꺼내 둠: 만드는 동안 이벤트를 처리하므로 목록이 바뀌면
        # (job·폴더를 바꿈) 항목이 지워짐 → 그때는 멈춤. 그동안 목록 다시 읽기는 끝난 뒤로 미룸
        if self.is_thumbnail_mode:
            with self._hold_sidebar_refresh():
                state = self._thumbnail_pass_state()  # 목록 모드로 바꾸거나 창을 닫아도 멈춤
                jobs = {}  # 같은 영상을 한 번에 여러 번 넣었으면 한 번만 (아이콘은 경로가 같은 모든 항목에)
                for item in items:
                    jobs.setdefault(paths.path_key(item.data(Qt.UserRole)),
                                    (item.data(Qt.UserRole), item.data(THUMBNAIL_CONTEXT_ROLE)))
                for file_path, context in jobs.values():
                    stopped = self._thumbnail_pass_stopped(state)
                    if stopped:
                        print(f"넣은 영상의 썸네일 만들기를 멈춤 ({stopped})")
                        break
                    self.generate_thumbnail(file_path, context=context)
        self._sidebar_read_done(None)  # 끌어다 놓은 폴더·파일을 방금 읽음 (앱이 다시 활성돼도 곧바로 또 읽지 않게)
        
        if file_paths:
            QMessageBox.information(self, "완료", f"{len(file_paths)}개의 파일이 사이드바에 추가되었습니다.")

    def get_video_files_from_folder(self, folder_path):
        """폴더에서 재귀적으로 비디오 파일들을 찾아서 반환 (.으로 시작하는 파일 제외, 번호 순서).

        규칙은 video_list.scan_folder (목록 다시 읽기도 같은 규칙). 폴더를 읽지 못하면 창으로 알리고 None — 부른 쪽은
        '지원되는 비디오 파일이 없습니다'를 띄우지 않음 (예전에는 로그에만 남기고 빈 목록이 되어 그 창이 떴음). 그 안의 폴더를
        읽지 못하면 읽은 영상을 돌려주고 창으로 알림. 창은 다시 읽기와 같은 문구·기록 ((제목, 폴더, 오류)마다 한 번).
        """
        started = time.perf_counter()
        try:
            result = video_list.scan_folder(folder_path)
        except OSError as e:
            self._report_list_source_problem(folder_path, e)
            return None
        self._sidebar_scan_seconds = time.perf_counter() - started
        self._report_list_read(folder_path, result)
        return [file_path for _name, file_path in result.videos]

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

            # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (index는 줄 번호 — 목록이 바뀌면 다른 영상을 가리킴)
            with self._hold_sidebar_refresh():
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

            # 이벤트를 처리하는 동안 목록이 바뀌면(job·폴더를 바꿈) 항목이 지워지므로 경로를 미리 꺼내 두고, 항목은 목록이
            # 그대로인지 확인한 뒤에만 씀. 그동안 목록 다시 읽기는 끝난 뒤로 미룸 (항목을 쥐고 있음)
            with self._hold_sidebar_refresh():
                generation = self._sidebar_generation
                stopped = False
                for i, (file_path, item) in enumerate([(item.toolTip(), item) for item in selected_items]):
                    if progress_dialog.wasCanceled():
                        print("썸네일 재생성이 취소되었습니다.")
                        break

                    if file_path and os.path.isfile(file_path):
                        # 진행 상황 업데이트 (모달 진행 창의 setValue는 이벤트를 처리함)
                        progress_dialog.setLabelText(f"재생성 중: {os.path.basename(file_path)}")
                        progress_dialog.setValue(i)
                        if self._sidebar_generation != generation:
                            print("사이드바 목록이 바뀌어(job·폴더를 바꿈) 썸네일 재생성을 멈춤")
                            stopped = True
                            break
                    
                        # 기존 썸네일 삭제 (이 항목의 썸네일 폴더에서)
                        self.delete_thumbnail_file(file_path, item)
                        # 썸네일 재생성
                        self.generate_thumbnail(file_path, item)
                        print(f"썸네일 재생성 완료: {os.path.basename(file_path)}")

                    # UI 업데이트
                    QApplication.processEvents()

            progress_dialog.setValue(len(selected_items))
            if stopped or self._closing_for_update:  # 다른 창의 업데이트가 이 창을 닫는 중이면 알림 없이
                return
            QMessageBox.information(self, "완료", f"{len(selected_items)}개 파일의 썸네일 재생성이 완료되었습니다.")

        except Exception as e:
            print(f"썸네일 재생성 중 오류: {e}")
            QMessageBox.critical(self, "오류", f"썸네일 재생성 중 오류가 발생했습니다:\n{str(e)}")

    def delete_thumbnail_file(self, file_path, item=None):
        """특정 파일의 썸네일을 그 항목의 썸네일 폴더에서 삭제합니다 (item: 사이드바 항목, 없으면 경로로 찾음)."""
        try:
            if item is None:
                item = self._sidebar_item_for(file_path)
            context = self._item_thumbnail_context(item, file_path)
            if context.pending_base is not None:
                context = self._resolve_pending_thumbnail_context(context)
            if not context.folder:
                return  # 저장한 썸네일 없음 (화면에만)

            thumbnail_path = thumbnails.thumbnail_path(context.folder, file_path)

            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                print(f"썸네일 파일 삭제: {thumbnail_path}")

            # UI에서도 썸네일 제거
            if item is not None:
                item.setIcon(QIcon())
                # 파일명만 표시
                item.setText(os.path.basename(file_path))

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

        # 시즌이 있는 작품: job 목록은 늘 비우고 시즌을 골랐을 때만 그 시즌의 job (작품 → 시즌 → job). 작품을 바꾸거나
        # '시즌선택'으로 돌리면 'job선택'만. 예전에는 '시즌선택'이 아닌 글자를 시즌으로 여겨, 시즌 목록을 비울 때(clear가 빈
        # 글자로 보냄) 작품 폴더의 하위 폴더를 job으로 넣고 이어서 온 '시즌선택'에서는 그 목록을 그대로 두었음
        self.jobComboBox.clear()
        self.jobComboBox.addItem("job선택")
        if self._picked(self.seasonComboBox):
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
        
        # 재귀적으로 폴더 내의 모든 비디오 파일 찾기 (드래그앤드롭과 동일한 방식, 번호 순서)
        video_files = self.get_video_files_from_folder(folder_path)
        read_failed = video_files is None  # 폴더를 읽지 못함 (창으로 알림) — 연결이 돌아오면 다시 읽기(F5)로 목록이 생김
        video_files = video_files or []
        
        if video_files:
            # 폴더 드래그앤드롭 시에는 기존 썸네일 폴더를 초기화하고 새로 설정 — 항목을 넣기 전에 (항목마다 이 자리를 기억)
            self.current_thumbnail_folder = None  # 기존 썸네일 폴더 초기화
            self._thumbnail_folder_problem = None  # 전에 연 job의 썸네일 폴더 문제는 이제 상관없음
            self.setup_thumbnail_folder()
            source = self._register_sidebar_source(video_list.ListSource("folder", folder_path))
        else:
            source = self._register_unread_folder(folder_path)  # 빈 폴더·읽지 못한 폴더
        
        # 사이드바에 파일들 추가
        self.playlist.extend(video_files)
        self._add_sidebar_videos([(os.path.basename(file_path), file_path, source) for file_path in video_files])
        self._sidebar_read_done(None)  # 방금 읽음 (앱이 다시 활성돼도 곧바로 또 읽지 않게)
        
        if self.playlist:
            self.current_playlist_index = 0
            self.open_file('A', self.playlist[0])
            self.sidebar.selectAll()
            self.schedule_background_thumbnail_loading()
            QMessageBox.information(self, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
        elif not read_failed:
            QMessageBox.warning(self, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")

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

    def _resize_sidebar_column(self, list_width):
        """사이드바 목록이 list_width가 되도록 메인 스플리터의 왼쪽 칸 너비를 바꿈 — 늘어난 만큼 영상 쪽에서 가져오고
        줄어든 만큼 영상 쪽에 줌. 창이 좁아 다 못 가져오면 스플리터가 최소 너비 안에서 맞춤."""
        sizes = self.mainSplitter.sizes()
        column = sizes[0] + list_width - self.sidebar.width()
        sizes[2] = max(0, sizes[2] - (column - sizes[0]))
        sizes[0] = column
        self.mainSplitter.setSizes(sizes)

    def switch_to_list_mode(self):
        self.listModeButton.setChecked(True)
        self.thumbnailModeButton.setChecked(False)
        self.sidebar.setViewMode(QListWidget.ListMode)
        self.sidebar.setSpacing(0)  # 리스트 아이템 사이 공란 제거
        self.is_thumbnail_mode = False
        
        # 사이드바 폭을 원래대로 되돌리기 (고정 너비가 아니라 스플리터 칸 너비 — 창을 줄이면 같이 줄어듦)
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(QWIDGETSIZE_MAX)
        if self.default_sidebar_width is not None:
            self._resize_sidebar_column(self.default_sidebar_width)
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
        
        # 사이드바 폭을 2배로 설정: 예전처럼 2배 너비로 시작하지만 고정 너비(setFixedWidth)가 아니라 스플리터 칸 너비 —
        # 고정 너비는 창의 최소 너비를 그만큼 늘려 창을 줄일 수 없게 했음. 최소 너비는 썸네일 한 개가 보일 만큼.
        new_width = self.default_sidebar_width * 2
        self.sidebar.setMaximumWidth(QWIDGETSIZE_MAX)
        self.sidebar.setMinimumWidth(self.thumbnail_size + 2 * self.sidebar.spacing() + 2 * self.sidebar.frameWidth()
                                     + self.sidebar.verticalScrollBar().sizeHint().width())
        self._resize_sidebar_column(new_width)
        print(f"사이드바 폭을 2배로 조정: {self.default_sidebar_width} -> {new_width}")
        
        # 즉시 사이드바 업데이트 (지연 없이): generate_thumbnails_for_all_items가 캐시된 썸네일을 바로 적용하고
        # (캐시 사용·새 생성 개수 로그) 나머지를 만듦 — 여기서 같은 확인을 먼저 하지 않음 (영상마다 NAS를 한 번만).
        # 항목 자리의 미뤄 둔 썸네일 폴더 문제도 거기서 창으로 ((폴더, 제목)마다 한 번)
        self.update_sidebar_display()

    def update_sidebar_display(self):
        """사이드바 아이템들을 현재 모드에 맞게 업데이트합니다."""
        print(f"사이드바 디스플레이 업데이트: thumbnail_mode={self.is_thumbnail_mode}, item_count={self.sidebar.count()}")
        
        if self.is_thumbnail_mode:
            with self._hold_sidebar_refresh():  # 그동안 목록 다시 읽기는 끝난 뒤로 미룸 (반복이 멈추지 않게)
                self.generate_thumbnails_for_all_items()
        else:
            self.clear_thumbnails()

    def generate_thumbnails_for_all_items(self):
        """모든 사이드바 아이템에 대해 썸네일을 생성합니다."""
        print(f"모든 아이템 썸네일 생성 시작: {self.sidebar.count()}개 아이템")
        self.cleanup_thumbnail_workers()
        # 이벤트를 처리하며 만드는 동안 목록이 바뀌거나(job·폴더를 바꿈) 목록 모드로 바꾸거나 창을 닫으면 나머지는 만들지
        # 않고 멈춤
        state = self._thumbnail_pass_state()
        # 첫 번째 단계에서 새로 만들 영상(과 그 자리)을 정해 두고 두 번째 단계는 그 목록만 (NAS에서 다시 확인하지 않고,
        # 지워졌을 수 있는 항목도 쓰지 않음)
        to_generate, _checked = self._apply_disk_thumbnails()
        new_generation_count = len(to_generate)
        print(f"썸네일 처리 완료: 캐시 사용 {self.sidebar.count() - new_generation_count}개, 새 생성 {new_generation_count}개")
        _started, stopped = self._make_thumbnails(to_generate, state)
        if stopped:
            return
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

    def _thumbnail_pass_state(self):
        """썸네일 반복을 시작할 때의 상태 (세대 번호, 썸네일 모드) — _thumbnail_pass_stopped가 지금과 비교."""
        return (self._sidebar_generation, self.is_thumbnail_mode)

    def _thumbnail_pass_stopped(self, state):
        """썸네일을 확인·만드는 반복(이벤트를 처리함)을 멈출 까닭 → 짧은 문구 (계속하면 None).

        창을 닫음, 목록이 바뀜 (job·폴더를 바꿈 — 지워진 항목·예전 목록의 영상을 쓰지 않게), 썸네일 모드에서 시작했는데
        목록 모드로 바꿈 (목록 모드에 아이콘을 붙이거나 워커를 띄우지 않게 — 목록 모드에서 시작한 썸네일 재생성은 그대로).
        """
        generation, thumbnail_mode = state
        if self._sidebar_scan_closed:
            return "창을 닫음"
        if self._sidebar_generation != generation:
            return "목록이 바뀜"
        if thumbnail_mode and not self.is_thumbnail_mode:
            return "목록 모드로 바꿈"
        return None

    def _make_thumbnails(self, to_generate, state):
        """정해 둔 영상들의 썸네일을 3개씩 만들며 진행바(thumbnailProgressBar)에 보임 → (워커를 띄운 수, 멈춘 까닭 — 끝까지
        했으면 None). 썸네일 버튼과 새로고침 버튼·F5가 같은 반복.

        to_generate: [(영상, 그 항목의 자리)] (_apply_disk_thumbnails가 정함 — NAS에서 다시 확인하지 않고, 지워졌을 수 있는
        항목도 쓰지 않음). state: 반복을 시작할 때의 상태 (_thumbnail_pass_state) — 만드는 동안(이벤트를 처리함) 목록이
        바뀌거나 목록 모드로 바꾸거나 창을 닫으면 나머지는 만들지 않고 멈춤 (그 전 확인에서 멈췄어도).
        """
        import gc
        total = len(to_generate)
        bar = self.thumbnailProgressBar
        if total > 0:
            bar.setMaximum(total)
            bar.setValue(0)
            bar.setFormat('썸네일 생성 중: %v/%m')
        else:
            bar.setMaximum(100)
            bar.setValue(100)
            bar.setFormat('썸네일 모두 디스크에 저장됨')
        bar.setVisible(True)
        batch_size = 3
        started = 0
        done = 0
        stopped = self._thumbnail_pass_stopped(state)
        for batch_start in range(0, total, batch_size):
            if stopped:
                break
            batch = to_generate[batch_start:batch_start + batch_size]
            print(f"배치 처리: {batch_start+1}-{batch_start + len(batch)}/{total}")
            for file_path, context in batch:
                stopped = self._thumbnail_pass_stopped(state)
                if stopped:
                    break
                if self.generate_thumbnail(file_path, context=context):
                    started += 1
                done += 1
                bar.setValue(done)
                QApplication.processEvents()
            stopped = stopped or self._thumbnail_pass_stopped(state)
            if stopped:
                break
            QApplication.processEvents()
            time.sleep(0.2)
            self.cleanup_thumbnail_workers()
            gc.collect()
        if stopped:
            print(f"썸네일 만들기를 멈춤 ({stopped}, {done}/{total}개에서)")
            bar.setFormat(f'썸네일 생성 멈춤 ({stopped})')
            return started, stopped
        if total > 0:
            bar.setValue(total)
            bar.setFormat('썸네일 생성 완료')
        return started, None

    def cleanup_thumbnail_workers(self):
        """완료된 워커들을 정리합니다: 목록에서 빼는 것은 그 워커의 finished를 GUI 스레드가 받을 때(generate_thumbnail의
        safe_remove_worker — 멈춘 워커는 멈춘 쪽이 목록을 비움). 끝났다고(isRunning) 여기서 먼저 놓으면 GUI 스레드가 아직 받지
        않은 신호 중 partial·람다로 이은 것(failed → 실패 창, finished → safe_remove_worker)이 QThread와 함께 사라져 실패 창이
        뜨지 않았음 (3개마다 0.2초 쉬는 동안 끝난 빠른 실패. 메서드로 이은 thumbnail_ready·save_failed는 전달됐음)."""
        print(f"워커 정리 완료: 현재 워커 수 {len(self.thumbnail_workers)}")

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

    def _bump_sidebar_generation(self):
        """사이드바 목록을 비움(clear → 모델 초기화): 썸네일을 만드는 반복이 지워진 항목을 쓰지 않고 멈추게 세대를 올림."""
        self._sidebar_generation += 1

    def _new_item_thumbnail_context(self, file_path):
        """지금 사이드바에 넣는 영상의 썸네일 자리: 지금의 썸네일 폴더·폴더 문제.

        아무것도 정하지 않았으면(예: 처음 끌어다 놓은 파일) 예전처럼 불러온 폴더 또는 영상 폴더 아래에 — 처음 쓸 때 만듦.
        """
        if self.current_thumbnail_folder:
            return ThumbnailContext(folder=self.current_thumbnail_folder)
        if self._thumbnail_folder_problem is not None:
            return ThumbnailContext(problem=self._thumbnail_folder_problem)
        return ThumbnailContext(pending_base=getattr(self, "selected_folder_path", None) or os.path.dirname(file_path))

    def _add_sidebar_videos(self, entries):
        """영상들을 사이드바 끝에 넣음 — entries: [(표시 이름, 경로, 들어온 곳(ListSource 또는 None))] → 넣은 항목 목록.

        항목마다 썸네일 자리(ThumbnailContext)를 지금 상태로 기억 (같은 영상이 이미 있으면 _new_sidebar_item의 규칙).
        """
        known = self._known_sidebar_videos()
        added = []
        for label, file_path, source in entries:
            item = self._new_sidebar_item(label, file_path, self._new_item_thumbnail_context(file_path), source, known)
            self.sidebar.addItem(item)
            added.append(item)
        return added

    def _known_sidebar_videos(self):
        """지금 목록의 영상 → {path_key: [썸네일 자리, 그 영상의 항목들]} (_new_sidebar_item이 씀)."""
        known = {}
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and item.data(Qt.UserRole):
                entry = known.setdefault(paths.path_key(item.data(Qt.UserRole)), [item.data(THUMBNAIL_CONTEXT_ROLE), []])
                entry[1].append(item)
        return known

    def _new_sidebar_item(self, label, file_path, context, source, known):
        """사이드바 항목을 만듦 (목록에는 부르는 쪽이 넣음). context: 이 영상이 들어온 곳의 썸네일 자리.

        이미 목록에 있는 영상(known)이면 그 항목의 자리를 그대로 씀. 다만 그 자리에 썸네일 폴더가 없고(폴더 문제·
        아직 정하지 않음) context에는 폴더가 있으면(예: 그 영상의 폴더를 끌어다 놓음) context를 쓰고 원래 항목도 그 자리로
        올림. 폴더가 정해진 자리는 다른 폴더로 바꾸지 않음. known은 이 항목까지 넣어 갱신.
        """
        key = paths.path_key(file_path)
        entry = known.get(key)
        if entry is None:
            entry = known[key] = [context, []]
        elif entry[0] is not None and (entry[0].folder or not context.folder):
            context = entry[0]  # 이미 있는 영상: 그 항목의 자리
        else:
            print(f"이미 목록에 있는 영상의 썸네일을 이제 이 폴더에: {context.folder} ({file_path})")
            for existing in entry[1]:
                existing.setData(THUMBNAIL_CONTEXT_ROLE, context)
            entry[0] = context
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, file_path)  # 파일 경로를 UserRole에 저장
        item.setData(THUMBNAIL_CONTEXT_ROLE, context)
        item.setData(SIDEBAR_SOURCE_ROLE, source)
        item.setToolTip(file_path)  # toolTip도 설정하여 기존 코드와 호환
        entry[1].append(item)
        return item

    def _register_sidebar_source(self, source, context=None):
        """목록에 영상을 넣는 곳(job 폴더·폴더)을 기억 → source. 목록 다시 읽기가 이곳을 처음과 같은 규칙으로 다시 읽음.

        context: 이곳에서 새로 생긴 영상의 썸네일 자리 (없으면 지금 넣는 영상과 같은 지금 상태의 자리 — 처음 불러올 때와
        같음). 같은 곳을 또 넣으면 처음 기억한 자리를 그대로. 목록을 비우면(clear) 함께 잊음.
        """
        if context is None:
            context = self._new_item_thumbnail_context(source.folder)
        self._sidebar_sources.setdefault(source, context)
        return source

    def _register_unread_folder(self, folder_path):
        """읽지 못한(또는 빈) 폴더도 목록에 영상을 넣는 곳으로 기억 → 연결이 돌아오면(영상이 생기면) 다시 읽기(F5·앱이 다시
        활성)로 목록에 들어옴. 그 영상의 썸네일은 처음 쓸 때 이 폴더 아래에 (영상이 있을 때 불러온 것과 같게)."""
        return self._register_sidebar_source(video_list.ListSource("folder", folder_path),
                                             ThumbnailContext(pending_base=folder_path))

    def _forget_sidebar_sources(self):
        """사이드바 목록을 비움(clear → 모델 초기화): 목록에 영상을 넣은 곳도 잊음 (새 목록을 넣는 쪽이 다시 기억).
        방금 job 목록을 읽었다는 표시도 지움 (목록이 바뀌었으므로 그 job을 다시 고르면 다시 불러옴). 예전 목록에서 누른
        새로고침의 썸네일 확인 요청도 버림 (새 목록은 처음 불러올 때의 흐름대로)."""
        self._sidebar_sources.clear()
        self._job_list_loaded_for = None
        self._sidebar_thumbnail_check_requested = False

    @contextlib.contextmanager
    def _hold_sidebar_refresh(self):
        """사이드바 항목·줄 번호를 쓰는 동안(썸네일 반복·job 목록 만들기·오른쪽 클릭 메뉴 — 이벤트를 처리함): 목록 다시 읽기는
        끝난 뒤로 미룸. 그동안 온 다시 읽기 결과도 버리고 끝난 뒤 다시 읽음.

        다시 읽기가 목록을 바꾸면 세대 번호가 올라 썸네일 반복이 '썸네일 생성 멈춤'으로 끝나고, 메뉴의 줄 번호(QModelIndex)가
        다른 영상을 가리킬 수 있으므로 — 그 대신 하던 일을 끝까지 하고 바로 뒤에 다시 읽음.
        """
        self._sidebar_refresh_holds += 1
        try:
            yield
        finally:
            self._sidebar_refresh_holds -= 1
            if not self._sidebar_refresh_holds and self._sidebar_refresh_deferred:
                QTimer.singleShot(0, self._run_deferred_sidebar_refresh)

    def _run_deferred_sidebar_refresh(self):
        if self._sidebar_refresh_deferred:
            self.refresh_sidebar()

    def _job_selection(self):
        return (self.workComboBox.currentText(), self.seasonComboBox.currentText(), self.jobComboBox.currentText())

    @staticmethod
    def _picked(combo):
        """시즌·job 콤보에서 항목을 골랐는지: 0번은 안내 항목('시즌선택'·'job선택'), -1은 비었거나 비우는 중 (clear가 빈
        글자로 currentIndexChanged를 보냄 — 안내 글자와만 비교하면 빈 글자를 고른 것으로 여김)."""
        return combo.currentIndex() > 0

    def _job_picked(self):
        """작품 → 시즌 → job 순서로 job까지 골랐는지 (시즌이 없는 작품은 작품 → job)."""
        return self._picked(self.jobComboBox) and (
            self.workComboBox.currentText() in NO_SEASON_WORKS or self._picked(self.seasonComboBox))

    def _on_job_activated(self, _index):
        """job 목록에서 고름 (같은 job을 다시 골라도 옴 — currentIndexChanged는 job이 바뀔 때만 와서 예전에는 아무 일도
        없었음). 다른 job이면 Qt가 바로 앞에 보낸 currentIndexChanged(update_playlist)가 이미 그 job을 읽었으므로 그대로
        (update_playlist가 읽은 (작품, 시즌, job)을 기억 — 그 안에서 창이 떠 이벤트를 처리해도 지워지지 않음),
        같은 job이면 목록을 다시 읽음. 목록이 폴더 불러오기·끌어다 놓기로 바뀌어 job 목록이 아니면 그 job을 새로 불러옴.
        'job선택'을 고르면 아무것도 읽지 않음."""
        loaded, self._job_list_loaded_for = self._job_list_loaded_for, None
        if loaded == self._job_selection() or not self._job_picked():
            return
        job_sources = {source for source in self._sidebar_sources if source.kind == "job"}
        if any(self.sidebar.item(i).data(SIDEBAR_SOURCE_ROLE) in job_sources for i in range(self.sidebar.count())):
            self.refresh_sidebar()
        else:
            # job 목록이 아니거나(폴더를 불러옴·끌어다 놓음) 고를 때 읽지 못해 영상이 없음 → 처음 고를 때처럼 불러옴
            # (job 경로·썸네일 폴더·첫 영상까지 — 다시 읽기는 영상만 넣음)
            self.update_playlist()

    def _clear_job_list_loaded_for(self):
        """update_playlist가 끝난 뒤의 첫 이벤트 처리: 코드로 job을 바꿔(activated가 오지 않음) 남은 표시를 지움. 사용자가
        고른 것이면 Qt가 update_playlist 바로 다음(이벤트를 처리하기 전) activated를 보내 이미 썼음."""
        self._job_list_loaded_for = None

    def _on_application_state_changed(self, state):
        """앱이 다시 활성됨(다른 앱에서 돌아옴 — QGuiApplication.applicationStateChanged): 다른 앱·PC에서 NAS의 영상을
        지우거나 넣고 돌아왔을 수 있으므로 조금 뒤 목록 다시 읽기. 이 앱의 창 사이를 오가거나 이 앱의 창(메시지 창 등)을
        닫을 때는 앱이 활성인 채라 오지 않음 (예전에는 창마다 활성이 바뀔 때 읽었음)."""
        if state == Qt.ApplicationActive:
            self._sidebar_refresh_timer.start()

    def _refresh_sidebar_on_activation(self):
        """(앱이 다시 활성된 뒤 조금 뒤) 목록 다시 읽기. 그사이 앱이 다시 비활성이 됐거나 창이 보이지 않거나 모달 대화상자·팝업이
        떠 있으면 하지 않음. 방금 읽었으면(ACTIVATION_REFRESH_GAP_S초, 마지막 읽기가 오래 걸렸으면 그 시간의
        ACTIVATION_REFRESH_GAP_FACTOR배 안 — job을 고르거나 폴더를 불러온 것도 읽은 것) 하지 않음."""
        if (QApplication.applicationState() != Qt.ApplicationActive or not self.isVisible()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return
        gap = max(ACTIVATION_REFRESH_GAP_S, ACTIVATION_REFRESH_GAP_FACTOR * self._sidebar_scan_seconds)
        if self._sidebar_refreshed_at is not None and time.monotonic() - self._sidebar_refreshed_at < gap:
            print(f"앱이 다시 활성됨: {gap:.1f}초 안에 목록을 읽어서 건너뜀")
            return
        self.refresh_sidebar()

    def _refresh_sidebar_by_user(self):
        """새로고침 버튼·F5: 목록 다시 읽기. 썸네일 모드면 다시 읽은 결과를 넣은 뒤 모든 영상의 썸네일도 썸네일 버튼처럼
        확인 — 저장된 썸네일(영상보다 새것)은 그대로 쓰고, 같은 이름으로 다시 렌더링해 썸네일보다 새 영상·썸네일이 없거나
        읽을 수 없는 영상만 다시 만듦 (목록이 바뀌지 않아도). 저절로 다시 읽을 때(앱이 다시 활성·같은 job을 다시 고름·없는
        영상을 엶·선택 재생)는 예전처럼 새 영상만 — 앱을 오갈 때마다 모든 영상을 NAS에서 확인하지 않게. 앱이 다시 활성될
        때의 간격(ACTIVATION_REFRESH_GAP_S)은 보지 않고 바로 읽음.

        요청(_sidebar_thumbnail_check_requested)은 다음에 시작하는 읽기에 실려(SidebarScan.check_thumbnails) 그 결과를 넣을 때
        (_apply_sidebar_read) 한 번 씀. 읽는 중에 누르면 그 읽기에는 싣지 않고 남겨 뒤이은 읽기에서, 목록을 쓰는 중이라 미루면
        미룬 읽기에서. 결과를 버리고 다시 읽으면(목록을 쓰는 중·폴더를 덧붙임) 요청으로 되돌려 다시 읽을 때. 목록을 비우면
        (job을 바꿈·폴더를 불러옴 — _forget_sidebar_sources, 읽는 중이면 그 결과도 버림) 버림. 읽기가 예상 못 한 오류로 끝나면
        (오류 창) 버림. 목록 모드에서 누르면 요청하지 않음 (예전처럼 목록만).
        """
        if self.is_thumbnail_mode:
            self._sidebar_thumbnail_check_requested = True
        self.refresh_sidebar()

    def _sidebar_read_done(self, seconds):
        """목록을 디스크에서 읽음 (처음 불러오기·다시 읽기): 앱이 다시 활성될 때 곧바로 또 읽지 않게 때·걸린 시간을 남김."""
        self._sidebar_refreshed_at = time.monotonic()
        if seconds is not None:
            self._sidebar_scan_seconds = seconds

    def refresh_sidebar(self):
        """사이드바 목록 다시 읽기 (새로고침 버튼·F5·창이 다시 활성·같은 job을 다시 고름·디스크에 없는 영상을 엶).

        목록에 영상을 넣은 곳(job 폴더·폴더)마다 처음 불러올 때와 같은 규칙(video_list)으로 다시 읽어 디스크에 없는 영상은
        빼고 새 영상은 정렬 자리에 넣음 (그곳에서 처음 불러올 때와 같은 썸네일 자리). 따로 끌어다 놓은 파일은 있는 동안만.
        디스크 읽기는 GUI 밖 스레드(SidebarScan)에서 — Windows SMB의 큰 job이나 응답 없는 NAS에서도 창이 멈추지 않음.
        결과는 GUI 스레드에서 넣음 (_on_sidebar_scanned). 한 번에 하나만 읽고, 읽는 동안 온 요청은 끝난 뒤 한 번 더.
        목록을 쓰는 중(_hold_sidebar_refresh)이면 끝난 뒤로 미룸. 선택 재생(Play Selected)은 목록 줄이 아니라 경로 목록
        (self.playlist)으로 재생하므로 미루지 않음.
        """
        if self._sidebar_scan_closed:
            return  # 창이 닫힘 (미뤄 둔 다시 읽기의 타이머가 늦게 옴) — 닫힌 창이 붙잡는 읽기 스레드를 만들지 않음
        if self._sidebar_refresh_holds:
            if not self._sidebar_refresh_deferred:
                print("목록을 쓰는 중이라(썸네일 만들기·job 목록 만들기·메뉴) 목록 다시 읽기를 끝난 뒤로 미룸")
            self._sidebar_refresh_deferred = True
            return
        self._sidebar_refresh_deferred = False
        if self._sidebar_scan is not None:
            self._sidebar_rescan_queued = True
            return
        if not self._sidebar_sources and not self.sidebar.count():
            self._sidebar_thumbnail_check_requested = False  # 읽을 것도, 썸네일을 확인할 영상도 없음
            return
        files = []
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(SIDEBAR_SOURCE_ROLE) is None and item.data(Qt.UserRole):
                files.append(item.data(Qt.UserRole))
        self._sidebar_refreshed_at = time.monotonic()
        # 지금까지의 썸네일 확인 요청은 이 읽기에 실음 (읽는 동안 누른 새로고침은 다시 요청해 뒤이은 읽기에서)
        scan = SidebarScan(tuple(self._sidebar_sources), files, self._sidebar_generation,
                           self._sidebar_thumbnail_check_requested)
        self._sidebar_thumbnail_check_requested = False
        scan.scanned.connect(self._on_sidebar_scanned)  # 창은 GUI 스레드 → 대기열을 거쳐 GUI 스레드에서 실행
        self._sidebar_scan = scan
        scan.start()

    def _on_sidebar_scanned(self, scan):
        """(GUI 스레드) 목록 다시 읽기의 디스크 읽기가 끝남 → 목록을 맞추고 문제를 알림.

        읽는 동안 목록이 바뀌었으면(세대 번호·목록에 영상을 넣은 곳이 다름 — job을 바꿈·폴더를 불러옴·끌어다 놓음) 결과를
        버리고 다시 읽음. 목록을 쓰는 중이면 버리고 끝난 뒤 다시 읽음. 창이 닫힌 뒤에 온 결과는 버림.
        이 읽기에 실린 새로고침의 썸네일 확인(scan.check_thumbnails)은 결과를 넣을 때 씀. 버리고 다시 읽으면(폴더를 덧붙임·
        목록을 쓰는 중) 요청으로 되돌려 다시 읽을 때, 목록을 새로 불러왔거나(새 목록은 처음 불러올 때의 흐름대로) 예상 못 한
        오류(창으로 알림 — 몇 시간 뒤 저절로 다시 읽을 때 모든 영상을 확인하지 않게)면 버림.
        """
        if scan is not self._sidebar_scan or self._sidebar_scan_closed:
            return  # 창을 닫으며 놓은 읽기 (release_worker가 신호를 막지만 이미 대기열에 들어간 결과)
        self._sidebar_scan = None
        scan.wait()  # 결과를 보낸 뒤 곧 끝남
        try:
            if scan.unexpected is not None:
                # 이 읽기에 실린 썸네일 확인도 버림 (오류 창을 봄 — 나중에 저절로 다시 읽을 때 모든 영상을 확인하지 않게)
                QMessageBox.critical(self, "목록 다시 읽기 오류",
                                     f"사이드바 목록을 다시 읽다 예상치 못한 오류가 났습니다.\n\n{scan.unexpected}")
                return
            if scan.generation != self._sidebar_generation:
                # 읽는 동안 목록을 비우고 새로 불러옴(job을 바꿈·폴더를 불러옴): 새 목록은 방금 디스크에서 읽었으므로 버리기만 —
                # 읽는 동안 다시 읽어 달라는 요청이 왔으면(_sidebar_rescan_queued) 아래에서 한 번 더. 이 읽기에 실린 썸네일
                # 확인도 버림 (새 목록은 처음 불러올 때의 흐름대로)
                print("목록 다시 읽기: 읽는 동안 목록을 새로 불러와 결과를 버림")
                return
            if set(scan.sources) != set(self._sidebar_sources):
                print("목록 다시 읽기: 읽는 동안 목록에 폴더를 덧붙여 결과를 버리고 다시 읽음")
                self._sidebar_rescan_queued = True
                self._sidebar_thumbnail_check_requested |= scan.check_thumbnails  # 다시 읽을 때 씀
                return
            if self._sidebar_refresh_holds:
                print("목록 다시 읽기: 목록을 쓰는 중이라 결과를 버리고 끝난 뒤 다시 읽음")
                self._sidebar_refresh_deferred = True
                self._sidebar_thumbnail_check_requested |= scan.check_thumbnails  # 다시 읽을 때 씀
                return
            self._apply_sidebar_read(scan.read, scan.elapsed, scan.check_thumbnails)
        finally:
            # 예외가 나도 남김: 오류 창 → 앱이 다시 활성 → 다시 읽기 → 오류 창이 되풀이되지 않게
            self._sidebar_read_done(scan.elapsed)
            if self._sidebar_rescan_queued:
                self._sidebar_rescan_queued = False
                self.refresh_sidebar()

    def _apply_sidebar_read(self, read, elapsed, check_thumbnails=False):
        """(GUI 스레드) 다시 읽은 결과(video_list.SourcesRead)로 목록을 맞춤. 바뀐 것이 없으면 목록을 건드리지 않음
        (깜빡임 없음, 세대 번호 그대로). 남는 항목은 그대로 둠: 썸네일 자리·아이콘·선택·현재 항목·재생 중 표시(빨간 글자),
        맨 위에 보이던 영상도 그 자리에. 읽지 못한 폴더(NAS 연결 끊김·권한)의 영상은 빼지 않고 실제 오류를 창으로
        ((제목, 폴더, 오류)마다 한 번 — 그 폴더를 다시 읽으면 기록을 지워 다음에 또 끊기면 다시 알림). 폴더가 지워졌으면
        그 영상을 빼고 알림. 썸네일 모드면 새 영상의 썸네일만 붙이거나 만듦 — check_thumbnails(이 읽기에 실린 새로고침
        버튼·F5의 요청 — _refresh_sidebar_by_user)면 모든 영상의 썸네일 (다시 렌더링한 영상도, _check_thumbnails_after_refresh).
        그사이 목록 모드로 바꿨으면 요청은 버리기만.
        """
        rows = [(self.sidebar.item(i).data(Qt.UserRole), self.sidebar.item(i).data(SIDEBAR_SOURCE_ROLE))
                for i in range(self.sidebar.count())]
        plan = video_list.plan_refresh(rows, read.results, read.gone_files)
        added = []
        if video_list.plan_changes(plan):
            added = self._apply_sidebar_plan(plan)
            print(f"목록 다시 읽기: 뺌 {len(plan[0])}개, 넣음 {len(added)}개 → {self.sidebar.count()}개 "
                  f"(읽은 곳 {len(read.results)}곳, {elapsed:.2f}초)")
        else:
            print(f"목록 다시 읽기: 바뀐 것 없음 ({len(rows)}개, 읽은 곳 {len(read.results)}곳, {elapsed:.2f}초)")
        for source, result in read.results.items():
            if isinstance(result, video_list.ScanResult):
                self._report_list_read(source.folder, result)
            else:
                self._report_list_source_problem(source.folder, read.errors[source],
                                                 gone=result is video_list.FOLDER_GONE, note=read.notes[source])
        self._report_unverified_files(read.unverified)
        if self.is_thumbnail_mode and (added or check_thumbnails):
            with self._hold_sidebar_refresh():
                if check_thumbnails:
                    self._check_thumbnails_after_refresh(read)  # 새 영상도 여기서 한 번
                else:
                    # 저절로 다시 읽음: 새 영상만 — 저장된 썸네일을 바로 붙이고 없는 것만 만듦 (남은 영상의 썸네일은 다시
                    # 보지 않음 — 앱을 오갈 때마다 모든 영상을 NAS에서 확인하지 않게)
                    state = self._thumbnail_pass_state()
                    to_generate, _checked = self._apply_disk_thumbnails(added)
                    for file_path, context in to_generate:
                        stopped = self._thumbnail_pass_stopped(state)
                        if stopped:
                            print(f"새 영상의 썸네일 만들기를 멈춤 ({stopped})")
                            break
                        self.generate_thumbnail(file_path, context=context)

    def _check_thumbnails_after_refresh(self, read):
        """새로고침 버튼·F5로 다시 읽은 결과(read)를 넣은 뒤 (썸네일 모드, 목록 다시 읽기는 미룬 채 — _apply_sidebar_read):
        모든 영상의 썸네일을 썸네일 버튼처럼 확인 — 저장된 썸네일(영상보다 새것)은 바로 붙이고, 같은 이름으로 다시 렌더링해
        썸네일보다 새 영상·썸네일이 없거나 읽을 수 없는 영상만 진행바와 함께 다시 만듦 (_make_thumbnails).

        건너뜀 (로그에 몇 개·왜): 이번 읽기에서 확인하지 못한 영상 — 읽지 못한 목록 폴더·하위 폴더 아래, 있는지 확인하지 못한
        따로 넣은 파일 (그 문제는 목록 창으로 이미 알림. NAS가 끊겼으면 영상마다 GUI 스레드에서 기다리고 "영상 확인 실패"
        창이 또 뜸). 썸네일 폴더를 만들지 못해 화면에만 보이는 영상 중 아이콘이 이미 있는 것 (저장된 썸네일이 없어
        새로고침마다 다시 만들게 됨 — 아이콘이 없는 것만 만듦).
        """
        confirmed = {source: {paths.path_key(path) for _name, path in result.videos}
                     for source, result in read.results.items() if isinstance(result, video_list.ScanResult)}
        unverified = {paths.path_key(path) for path, _error, _note in read.unverified}
        items = []
        unread = 0
        shown = 0
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            file_path = item.data(Qt.UserRole)
            if not file_path:
                continue
            key = paths.path_key(file_path)
            source = item.data(SIDEBAR_SOURCE_ROLE)
            if source is None:
                unconfirmed = key in unverified  # 따로 넣은 파일: 있는 것은 읽기에서 확인함
            else:
                unconfirmed = key not in confirmed.get(source, ())  # 그 출처를 다시 읽어 나온 영상만 확인함
            context = item.data(THUMBNAIL_CONTEXT_ROLE)
            if unconfirmed:
                unread += 1
            elif context is not None and context.problem is not None and not item.icon().isNull():
                shown += 1
            else:
                items.append(item)
        if unread:
            print(f"새로고침: 이번에 읽지 못한 곳의 영상 {unread}개는 썸네일을 확인하지 않음 "
                  f"(목록 폴더·그 안의 폴더를 읽지 못했거나 따로 넣은 파일을 확인하지 못함 — 창으로 알림)")
        if shown:
            print(f"새로고침: 썸네일 폴더가 없어 화면에만 보이는 영상 {shown}개는 아이콘이 있어 다시 만들지 않음")
        state = self._thumbnail_pass_state()
        to_generate, checked = self._apply_disk_thumbnails(items)
        started, _stopped = self._make_thumbnails(to_generate, state)
        print(f"새로고침: 썸네일 확인 {checked}개, 다시 만듦 {started}개")

    def _apply_sidebar_plan(self, plan):
        """video_list.plan_refresh의 계획대로 사이드바를 바꿈 → 새로 넣은 항목 목록. 남는 항목은 건드리지 않음.

        먼저 세대 번호를 올림: 썸네일 반복·백그라운드 처리가 예전 줄 번호나 뺀 항목을 쓰지 않게 (반복은 미뤄 두므로 보통은
        돌고 있지 않음). 맨 위에 보이던 영상이 남으면 다시 맨 위로, 빠졌으면 스크롤 위치를 그대로.
        """
        removed, final = plan
        self._bump_sidebar_generation()
        anchor = next((self.sidebar.item(i) for i in range(self.sidebar.count())
                       if self.sidebar.visualItemRect(self.sidebar.item(i)).bottom() >= 0), None)
        scroll = self.sidebar.verticalScrollBar().value()
        added = []
        self.sidebar.setUpdatesEnabled(False)
        try:
            for row in reversed(removed):
                print(f"목록에서 뺌 (디스크에 없음): {self.sidebar.takeItem(row).data(Qt.UserRole)}")
            known = self._known_sidebar_videos()
            for index, entry in enumerate(final):
                if isinstance(entry, int):
                    continue
                source, label, file_path = entry
                item = self._new_sidebar_item(label, file_path, self._sidebar_sources[source], source, known)
                self.sidebar.insertItem(index, item)
                added.append(item)
                print(f"목록에 넣음 (새 영상): {file_path}")
        finally:
            self.sidebar.setUpdatesEnabled(True)
        if anchor is not None and self.sidebar.row(anchor) >= 0:
            self.sidebar.scrollToItem(anchor, QAbstractItemView.PositionAtTop)
        else:
            self.sidebar.verticalScrollBar().setValue(scroll)
        return added

    def _report_list_source_problem(self, folder, error, gone=None, note=""):
        """목록에 영상을 넣는(넣은) 폴더를 읽지 못함 → 창 ((제목, 폴더, 오류)마다 한 번). 처음 불러올 때와 다시 읽을 때 같은
        문구·같은 기록 — 같은 문제가 두 번 뜨지 않음. gone: 지워졌는지 (None이면 여기서 video_list.check_gone으로 확인),
        note: 없어진 것으로 보지 않은 까닭 (확인한 위 폴더와 그 상태 — 창·로그에 덧붙임)."""
        if gone is None:
            gone, note = video_list.check_gone(folder, error)
        reason = f"{type(error).__name__}: {error}" + (f"\n{note}" if note else "")
        if gone:
            title = LIST_FOLDER_GONE
            text = ("영상 목록 폴더가 디스크에 없습니다 (지워졌거나 이름이 바뀜). 이 폴더의 영상은 목록에서 뺍니다.\n"
                    f"폴더: {folder}\n이유: {reason}")
        else:
            title = LIST_READ_FAILED
            text = ("영상 목록 폴더를 읽지 못했습니다 (NAS 연결 끊김·권한 등). 목록은 그대로 두고, 연결을 확인한 뒤 "
                    f"새로고침(F5)을 누르면 다시 읽습니다.\n폴더: {folder}\n이유: {reason}")
        self._report_list_problem(title, folder, (type(error).__name__, str(error)), text)

    def _report_list_read(self, folder, result):
        """목록 폴더를 읽음: 전에 알린 이 폴더의 문제 기록은 지우고(다시 생기면 또 알림), 읽지 못한 하위 폴더가 있으면 알림
        (처음 불러올 때와 다시 읽을 때 같은 문구 — 폴더가 많으면(공유가 끊김 등) 10개까지만)."""
        detail = tuple((paths.path_key(sub), type(e).__name__, str(e)) for sub, e in result.unreadable)
        key = (LIST_READ_FAILED, paths.path_key(folder), detail)
        self._list_problems_shown = {shown for shown in self._list_problems_shown
                                     if shown[1] != key[1] or (result.unreadable and shown == key)}
        if not result.unreadable:
            return
        lines = [f"{sub}\n  → {type(e).__name__}: {e}" for sub, e in result.unreadable]
        if len(lines) > 10:
            lines = lines[:10] + [f"… 외 {len(lines) - 10}개"]
        self._report_list_problem(
            LIST_READ_FAILED, folder, detail,
            "목록 폴더 안에서 읽지 못한 폴더가 있어 그 안의 영상은 확인하지 못했습니다 — 목록에 새로 넣지도 빼지도 "
            f"않습니다 (권한·NAS 연결 끊김 등).\n목록 폴더: {folder}\n\n" + "\n".join(lines))

    def _report_unverified_files(self, unverified):
        """따로 넣은 영상 중 있는지 확인하지 못한 것(공유가 끊김·권한) → 목록에 그대로 두고 창으로 (같은 문제는 한 번).
        unverified: [(경로, OSError, 없어진 것으로 보지 않은 까닭)]."""
        detail = tuple((paths.path_key(path), type(e).__name__, str(e)) for path, e, _note in unverified)
        self._list_problems_shown = {shown for shown in self._list_problems_shown
                                     if shown[1] is not None or (unverified and shown[2] == detail)}
        if unverified:
            self._report_list_problem(
                LIST_READ_FAILED, None, detail,
                "따로 넣은 영상을 확인하지 못해 목록에 그대로 둡니다 (NAS 연결 끊김·권한 등).\n\n"
                + "\n".join(f"{path}\n  → {type(e).__name__}: {e}" + (f"\n  → {note}" if note else "")
                            for path, e, note in unverified))

    def _report_list_problem(self, title, folder, detail, text):
        """영상 목록을 만들거나 다시 읽다 생긴 문제를 알림: 로그에는 매번, 창은 (제목, 폴더, 오류 종류·내용)마다 한 번 —
        창이 다시 활성될 때마다 다시 읽어도 창이 계속 뜨지 않게. 그 폴더를 다시 읽을 수 있게 되면 기록을 지움
        (_report_list_read)."""
        print(f"{title}\n{text}")
        key = (title, paths.path_key(folder) if folder else None, detail)
        if key in self._list_problems_shown:
            return
        # 창을 띄우기 전에 넣음: 창이 떠 있는 동안 같은 문제가 다시 와도 창을 또 띄우지 않게
        self._list_problems_shown.add(key)
        QMessageBox.warning(self, title, text)

    def _sidebar_item_for(self, file_path):
        """사이드바에서 그 영상의 (첫) 항목. 없으면 None."""
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and paths.same_path(item.data(Qt.UserRole), file_path):
                return item
        return None

    def _item_thumbnail_context(self, item, file_path):
        """항목의 썸네일 자리. 사이드바에 없는 영상(item=None)이면 지금 상태의 자리."""
        context = item.data(THUMBNAIL_CONTEXT_ROLE) if item is not None else None
        if context is None:
            context = self._new_item_thumbnail_context(file_path)
            if item is not None:
                print(f"썸네일 자리가 없는 사이드바 항목 — 지금 상태로 정함: {file_path}")
                item.setData(THUMBNAIL_CONTEXT_ROLE, context)
        return context

    def _resolve_pending_thumbnail_context(self, context):
        """아직 정하지 않은 썸네일 자리를 정함: pending_base 아래 썸네일 폴더를 만들고, 같은 자리를 기다리던 항목 모두에 기억.

        만들지 못하면 폴더 문제(화면에만, 창은 썸네일을 쓸 때). 예전처럼, 아무 상태도 정하지 않은 때면 새로 넣을 항목의
        자리로도 씀 (예: 처음 끌어다 놓은 파일들의 썸네일 폴더를 그다음에 끌어다 놓은 파일도 씀).
        """
        base = context.pending_base
        try:
            folder = thumbnails.ensure_folder(base)
        except OSError as e:
            resolved = ThumbnailContext(
                problem=self._thumbnail_folder_problem_for(os.path.join(base, thumbnails.FOLDER_NAME), e))
        else:
            resolved = ThumbnailContext(folder=folder)
            print(f"generate_thumbnail에서 썸네일 폴더 설정: {folder}")
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and item.data(THUMBNAIL_CONTEXT_ROLE) == context:
                item.setData(THUMBNAIL_CONTEXT_ROLE, resolved)
        for source, source_context in self._sidebar_sources.items():  # 그곳에서 새로 생길 영상도 같은 자리
            if source_context == context:
                self._sidebar_sources[source] = resolved
        if not self.current_thumbnail_folder and self._thumbnail_folder_problem is None:
            self.current_thumbnail_folder = resolved.folder
            self._thumbnail_folder_problem = resolved.problem
        return resolved

    def _apply_disk_thumbnails(self, items=None):
        """사이드바 영상마다 그 항목의 썸네일 폴더에 있는 썸네일(영상보다 새것)을 바로 적용하고, (새로 만들어야 할
        [(영상, 그 항목의 자리)], 확인한 영상 수)를 돌려줌. 항목 자리의 미뤄 둔 썸네일 폴더 문제는 여기서 창으로
        ((폴더, 제목)마다 한 번). items: 그 항목만 (목록 다시 읽기로 새로 넣은 항목 — 남은 항목의 썸네일은 다시 보지 않음,
        새로고침이 고른 항목). 없으면 모든 항목.

        새로 만들 것: 썸네일이 없거나, 영상보다 오래됐거나, 영상보다 새것이지만 읽을 수 없는(깨진) 썸네일, 화면에만인 항목.
        캐시 적용이 이벤트를 처리하는 동안 목록이 바뀌거나(job·폴더를 바꿈) 목록 모드로 바꾸거나 창을 닫으면 거기서 멈춤
        (_thumbnail_pass_stopped). 같은 영상이 여러 번 있으면 한 번만 (아이콘은 경로가 같은 모든 항목에 붙음).
        """
        state = self._thumbnail_pass_state()
        to_generate = []
        seen = set()
        if items is None:
            items = (self.sidebar.item(i) for i in range(self.sidebar.count()))
        for item in items:
            stopped = self._thumbnail_pass_stopped(state)
            if stopped:
                print(f"썸네일 확인을 멈춤 ({stopped})")
                break
            if item is None:
                continue  # None인 경우 건너뛰기
            file_path = item.data(Qt.UserRole)
            if not file_path:
                continue
            key = paths.path_key(file_path)
            if key in seen:
                continue  # 같은 영상의 다른 항목 (같은 자리 — 이미 처리함)
            seen.add(key)  # 확인한 영상 (그 수를 돌려줌)
            context = self._item_thumbnail_context(item, file_path)
            if not self._video_is_available(file_path, context):
                continue
            if context.pending_base is not None:
                context = self._resolve_pending_thumbnail_context(context)
            self._report_context_problem(context)
            fresh = self._has_disk_thumbnail(file_path, context)
            if fresh is None:
                continue  # 영상을 확인하지 못함 (없어졌거나 읽을 수 없음)
            if fresh:
                pixmap = QPixmap(thumbnails.thumbnail_path(context.folder, file_path))
                if not pixmap.isNull():
                    print(f"캐시된 썸네일 즉시 적용: {file_path}")
                    self.update_sidebar_item_thumbnail(file_path, pixmap)
                    continue
                print(f"디스크 썸네일을 읽을 수 없어 새로 만듦: {file_path}")
            else:
                print(f"새 썸네일 생성 예정: {file_path}")
            to_generate.append((file_path, context))
        return to_generate, len(seen)

    def _video_is_available(self, file_path, context):
        """썸네일을 만들 영상 파일이 있는지 os.stat으로 확인 (os.path.isfile은 오류를 숨기고 False를 돌려줌).

        확인하지 못하면 False: 없어졌으면 로그만, 다른 오류는 창으로 알림 (_report_video_problem).
        """
        try:
            info = os.stat(file_path)
        except OSError as e:
            self._report_video_problem(file_path, e, context)
            return False
        return stat.S_ISREG(info.st_mode)

    def _report_video_problem(self, file_path, error, context):
        """영상을 확인하지 못함 → 그 영상의 썸네일은 건너뜀. 없어진 것만 로그로 끝내고, 다른 오류(권한·시간 초과·
        끊긴 공유 등)는 "영상 확인 실패" 창으로 — 조용히 건너뛰지 않음.

        없어진 것: FileNotFoundError이고 영상의 폴더는 확인됨. Windows는 끊긴 SMB 공유(ERROR_BAD_NETPATH·BAD_NET_NAME)도
        FileNotFoundError로 올리고 Mac autofs도 그럴 수 있어, 폴더까지 확인하지 못하면 두 오류를 함께 알림.
        창은 목록 단위로 한 번: 그 항목 자리의 썸네일 폴더(또는 만들지 못한 폴더·정할 폴더) — 영상 폴더마다 창이 뜨지 않게.
        """
        reason = f"이유: {type(error).__name__}: {error}"
        if isinstance(error, FileNotFoundError):
            folder = os.path.dirname(file_path)
            try:
                os.stat(folder)
            except OSError as folder_error:
                reason += f"\n영상 폴더도 확인하지 못함: {type(folder_error).__name__}: {folder_error}"
            else:
                print(f"영상이 없어져 썸네일을 건너뜀: {file_path} ({type(error).__name__}: {error})")
                return
        self._report_thumbnail_problem(
            context.folder
            or (context.problem[0] if context.problem else None)
            or context.pending_base,
            THUMBNAIL_VIDEO_PROBLEM,
            "썸네일을 만들 영상을 확인하지 못해 이 영상의 썸네일은 건너뜁니다 (권한·연결 끊김 등).\n"
            f"영상: {file_path}\n{reason}",
        )

    def _has_disk_thumbnail(self, file_path, context):
        """그 항목의 썸네일 폴더에 영상보다 새 썸네일이 있는지 확인합니다 (영상이 바뀌었으면 False → 새로 만듦).

        썸네일 폴더가 없는 자리(폴더 문제)면 False. 영상을 확인하지 못하면 None (건너뜀): 없어졌으면 로그만,
        다른 오류는 창으로 (_report_video_problem). 썸네일 파일을 확인하지 못하면(권한 등) 창으로 알리고
        ((폴더, 제목)마다 한 번) False → 새로 만듦.
        """
        if not context.folder:
            return False
        thumbnail_path = thumbnails.thumbnail_path(context.folder, file_path)
        try:
            return thumbnails.is_fresh(thumbnail_path, file_path)
        except OSError as e:
            if e.filename == file_path:  # 영상 쪽 오류 (썸네일이 없는 것은 is_fresh가 False로 돌려줌)
                self._report_video_problem(file_path, e, context)
                return None
            self._report_thumbnail_problem(
                context.folder,
                THUMBNAIL_FOLDER_PROBLEM,
                "썸네일 파일을 확인하지 못해 새로 만듭니다.\n"
                f"썸네일 파일: {thumbnail_path}\n이유: {type(e).__name__}: {e}",
            )
            return False

    def generate_thumbnail(self, file_path, item=None, context=None):
        """영상 하나의 썸네일: 그 항목의 썸네일 자리(ThumbnailContext)에서 읽거나 만들어 저장 (폴더가 없는 자리면 화면에만).

        context: 미리 꺼내 둔 그 항목의 자리 (반복에서 — 이벤트를 처리하는 동안 항목이 지워질 수 있음). 없으면 item의 자리,
        item도 없으면 경로로 찾고, 사이드바에 없는 영상이면 지금 상태의 자리. 아이콘은 경로로 찾아 붙임.
        다른 썸네일을 기다리는 동안 목록이 바뀌거나(job·폴더를 바꿈) 썸네일 모드에서 목록 모드로 바꾸거나 창을 닫으면 만들지
        않음 (_thumbnail_pass_stopped). → 워커를 띄웠으면 True, 아니면 False (저장된 썸네일을 붙임·영상을 확인하지 못함·멈춤).
        워커가 썸네일을 만들지 못하면(failed) 창으로 ((폴더, 제목)마다 한 번 — _on_thumbnail_failed).
        """
        import time
        print(f"썸네일 생성 시작: {file_path}")
        state = self._thumbnail_pass_state()
        
        if context is None:
            if item is None:
                item = self._sidebar_item_for(file_path)
            context = self._item_thumbnail_context(item, file_path)
        if context.pending_base is not None:
            # 썸네일 폴더를 아직 정하지 않음 (예: 처음 끌어다 놓은 파일 — 예전의 드래그한 폴더·영상 폴더): 영상이 있을 때만 만듦
            if not self._video_is_available(file_path, context):
                return False
            context = self._resolve_pending_thumbnail_context(context)
        # 이 항목 자리의 미뤄 둔 썸네일 폴더 문제(폴더를 만들지 못함·권한을 바꾸지 못함)를 창으로 ((폴더, 제목)마다 한 번)
        self._report_context_problem(context)
        # 폴더가 없으면(썸네일 폴더 문제) 다른 폴더로 대신하지 않고 화면에만
        thumbnail_folder = context.folder
        
        # 동시 실행 제한 (1개로 더 줄임)
        # 디스크에 저장된 썸네일 확인 (영상보다 오래된 썸네일은 워커가 새로 만들어 바꿈)
        if thumbnail_folder:
            thumbnail_path = thumbnails.thumbnail_path(thumbnail_folder, file_path)
            fresh = self._has_disk_thumbnail(file_path, context)
            if fresh is None:
                return False  # 영상을 확인하지 못함 (없어졌거나 읽을 수 없음)
            
            if fresh:
                print(f"디스크에서 썸네일 로드: {thumbnail_path}")
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    # UI 업데이트
                    self.update_sidebar_item_thumbnail(file_path, pixmap)
                    return False
                else:
                    print(f"디스크 썸네일이 손상됨, 재생성: {thumbnail_path}")
                    try:
                        os.remove(thumbnail_path)
                    except FileNotFoundError:
                        pass  # 그사이 다른 PC가 지움 — 새로 만들면 됨
                    except OSError as e:
                        # 지우지 못해도 워커가 새 썸네일로 바꿔 저장함 (임시 파일 + os.replace — 그것도 못 하면 저장 실패 창)
                        self._report_thumbnail_problem(
                            thumbnail_folder,
                            THUMBNAIL_FOLDER_PROBLEM,
                            "읽을 수 없는(깨진) 썸네일 파일을 지우지 못했습니다. 새로 만든 썸네일로 바꿔 저장해 봅니다.\n"
                            f"썸네일 파일: {thumbnail_path}\n이유: {type(e).__name__}: {e}",
                        )
        max_workers = 1
        while len(self.thumbnail_workers) >= max_workers:
            QApplication.processEvents()
            time.sleep(0.2)  # 대기 시간을 늘려서 메모리 부하 감소
            # 완료된 워커들 정리
            self.cleanup_thumbnail_workers()
        stopped = self._thumbnail_pass_stopped(state)
        if stopped:
            print(f"이 영상의 썸네일은 만들지 않음 ({stopped}): {file_path}")
            return False

        # 워커 생성 (썸네일 폴더가 없으면 저장하지 않고 화면에만)
        worker = ThumbnailWorker(file_path, self.thumbnail_size, thumbnail_folder)
        worker.thumbnail_ready.connect(self.on_thumbnail_ready)
        worker.save_failed.connect(self._on_thumbnail_save_failed)
        # 만들지 못함 → 그 항목 자리의 폴더(화면에만인 자리는 만들지 못한 폴더)마다 한 번 창으로
        worker.failed.connect(functools.partial(
            self._on_thumbnail_failed,
            context.folder or (context.problem[0] if context.problem else None) or context.pending_base))
        
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
        return True

    def _use_dropped_folder_for_thumbnails(self, folder_path):
        """끌어다 놓은 폴더(여러 개면 첫 폴더)의 썸네일은 그 폴더의 썸네일 폴더에 (전에 고른 job·폴더가 아니라).

        영상 영역·사이드바·창 어디에 끌어다 놓아도 같음. 전에 연 job의 썸네일 폴더 문제는 이제 상관없음.
        썸네일 폴더를 만들지 못하면 job 폴더처럼 기억만 하고(화면에만, 창은 썸네일을 쓸 때) 예외는 올리지 않음.
        """
        # 폴더 경로를 selected_folder_path로 설정 (썸네일 폴더 생성용)
        self.selected_folder_path = folder_path
        print(f"드래그앤드롭으로 썸네일 폴더 설정: {folder_path}")
        self._thumbnail_folder_problem = None
        try:
            self.current_thumbnail_folder = thumbnails.ensure_folder(folder_path)
        except OSError as e:
            self.current_thumbnail_folder = None
            self._remember_thumbnail_folder_problem(os.path.join(folder_path, thumbnails.FOLDER_NAME), e)
            return
        print(f"드래그앤드롭으로 썸네일 폴더 설정: {self.current_thumbnail_folder}")

    def _thumbnail_folder_problem_for(self, folder, error):
        """썸네일 폴더를 만들지 못한 문제 (폴더, 창 제목, 내용) → 그 자리의 썸네일은 저장하지 않고 화면에만. 로그는 바로."""
        text = ("썸네일 폴더를 만들지 못해 이 작업의 썸네일은 저장하지 않습니다.\n"
                "이번에는 화면에만 보이고, 다음에 썸네일 모드를 켜면 다시 만듭니다.\n"
                f"이유: {type(error).__name__}: {error}")
        print(f"{THUMBNAIL_FOLDER_PROBLEM}: {folder}\n{text}")
        return (folder, THUMBNAIL_FOLDER_PROBLEM, text)

    def _remember_thumbnail_folder_problem(self, folder, error):
        """썸네일 폴더를 만들지 못함 → 새로 넣는 항목의 썸네일은 저장하지 않고 화면에만 (다른 폴더로 대신하지 않음).

        로그에는 바로 남기고, 창은 썸네일을 쓸 때(썸네일 모드·썸네일 생성) _report_context_problem이 띄움.
        """
        self._thumbnail_folder_problem = self._thumbnail_folder_problem_for(folder, error)

    def _report_context_problem(self, context):
        """썸네일을 쓸 때(썸네일 모드·썸네일 생성) 그 항목 자리의 미뤄 둔 썸네일 폴더 문제를 창으로 ((폴더, 제목)마다 한 번).

        폴더를 만들지 못함(context.problem) 또는 폴더는 쓰지만 권한을 바꾸지 못함(thumbnails.share_problem).
        이미 알린 (폴더, 제목)이면 아무것도 하지 않음 (영상마다 불리므로 로그도 다시 남기지 않음).
        """
        if context.problem is not None:
            problem = context.problem
        elif context.folder and thumbnails.share_problem(context.folder):
            problem = (
                context.folder,
                THUMBNAIL_FOLDER_PROBLEM,
                "썸네일 폴더의 권한을 바꾸지 못했습니다. 이 PC에서는 썸네일을 저장하지만, 다른 NAS 계정을 쓰는 PC"
                "(Windows 등)는 이 폴더에 저장하지 못해 매번 다시 만들 수 있습니다.\n"
                f"이유: {thumbnails.share_problem(context.folder)}",
            )
        else:
            return
        if (problem[0], problem[1]) not in self._thumbnail_problems_shown:
            self._report_thumbnail_problem(*problem)

    def _on_thumbnail_save_failed(self, folder, detail):
        """ThumbnailWorker.save_failed: 저장하지 못한 썸네일도 이번 실행에서는 아이콘으로 보임."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_SAVE_FAILED,
            "썸네일 파일을 저장하지 못했습니다.\n"
            f"이번에는 화면에만 보이고, 다음에 썸네일 모드를 켜면 다시 만듭니다.\n{detail}",
        )

    def _on_thumbnail_failed(self, folder, detail):
        """ThumbnailWorker.failed: 영상의 썸네일을 만들지 못함 (OpenCV가 열지 못함·첫 프레임을 읽지 못함·예상 못 한 오류) →
        창 ((폴더, 제목)마다 한 번 — 영상마다 뜨지 않게, 로그에는 매번). folder: 그 항목 자리의 썸네일 폴더."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_MAKE_FAILED,
            "영상의 썸네일을 만들지 못해 이 영상은 아이콘 없이 둡니다 (영상이 손상되었거나 지원하지 않는 형식이거나 "
            f"읽을 수 없음).\n{detail}",
        )

    def _report_thumbnail_problem(self, folder, title, text):
        """썸네일 문제를 알림: 로그에는 매번, 창은 이번 실행에서 (폴더, 제목)마다 한 번
        ("썸네일 폴더 문제"를 알린 폴더라도 나중의 "썸네일 저장 실패"는 따로 알림).

        title: THUMBNAIL_SAVE_FAILED·THUMBNAIL_FOLDER_PROBLEM·THUMBNAIL_VIDEO_PROBLEM·THUMBNAIL_MAKE_FAILED.
        text: 무슨 일이 있었고 썸네일이 어떻게 되는지와 이유.
        창에는 NAS 권한 확인 안내와 폴더 경로를 덧붙임.
        """
        print(f"{title}: {folder}\n{text}")
        if (folder, title) in self._thumbnail_problems_shown:
            return
        # 창을 띄우기 전에 넣음: 창이 떠 있는 동안 다음 저장 실패 시그널이 들어와도 창을 또 띄우지 않게
        self._thumbnail_problems_shown.add((folder, title))
        QMessageBox.warning(
            self,
            title,
            f"{text}\n\n"
            "NAS에서 이 폴더의 권한(이 PC가 쓰는 NAS 계정의 읽기·쓰기 권한)을 확인하세요.\n\n"
            f"폴더: {folder}",
        )

    def on_thumbnail_ready(self, file_path, pixmap):
        """썸네일 생성이 완료되었을 때 호출됩니다. 예외는 잡지 않음 (앱의 sys.excepthook이 스택 트레이스째 로그와 창으로)."""
        try:
            print(f"썸네일 생성 완료: {file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap: {file_path}")
                return
            
            # 사이드바 아이템 업데이트
            self.update_sidebar_item_thumbnail(file_path, pixmap)
        finally:
            # 메모리 정리
            import gc
            gc.collect()

    def update_sidebar_item_thumbnail(self, file_path, pixmap):
        """사이드바 아이템의 썸네일을 업데이트합니다. 예외는 잡지 않음 (앱의 sys.excepthook이 스택 트레이스째 로그와 창으로 —
        예전에는 로그에만 남기고 아이콘 없이 지나감)."""
        try:
            print(f"썸네일 아이템 업데이트 시작: {file_path}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap으로 업데이트 시도: {file_path}")
                return
            
            # 사이드바에서 해당 파일을 찾아 썸네일 설정 (같은 영상이 여러 번 있으면 모든 항목에)
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item and paths.same_path(item.data(Qt.UserRole), file_path):
                    # 아이콘 설정
                    item.setIcon(QIcon(pixmap))
                    print(f"썸네일 아이템 업데이트 완료: {file_path}")
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
                # 폴더가 없으면 생성
                thumbnail_folder = thumbnails.ensure_folder(job_path)
                
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
            # 현재 사이드바의 영상마다 그 항목의 썸네일 폴더에 있는 썸네일 (썸네일 폴더가 정해진 항목만 —
            # 폴더 문제·아직 정하지 않은 항목은 읽을 썸네일이 없음)
            thumbnail_files = []
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item:
                    file_path = item.data(Qt.UserRole)
                    if file_path and os.path.isfile(file_path):
                        folder = self._item_thumbnail_context(item, file_path).folder
                        if folder:
                            thumbnail_files.append((file_path, thumbnails.thumbnail_path(folder, file_path)))
            
            if not thumbnail_files:
                print("로딩할 썸네일이 없음 (썸네일 폴더가 정해진 영상 없음)")
                return
            
            print(f"백그라운드 썸네일 로딩 시작: {len(thumbnail_files)}개 파일")
            
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
            self.thumbnail_loader_worker = ThumbnailLoaderWorker(thumbnail_files)
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
