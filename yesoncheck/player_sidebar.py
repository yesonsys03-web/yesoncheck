"""Media library and sidebar helpers for VideoPlayer."""

import os
import shutil
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QMenu,
    QMessageBox,
)

from yesoncheck import paths, video_list
# PlayerSidebarMixin의 부모 믹스인 (북마크, 선택 재생, 공유 설정·작품 경로, 목록 다시 읽기, Seq 탭, 썸네일)
from yesoncheck.sidebar_all import SidebarAllMixin
from yesoncheck.sidebar_bookmarks import SidebarBookmarksMixin
from yesoncheck.sidebar_playlist import SidebarPlaylistMixin
from yesoncheck.sidebar_config_paths import SidebarConfigPathsMixin
from yesoncheck.sidebar_refresh import SidebarRefreshMixin
from yesoncheck.sidebar_sequences import SidebarSequencesMixin
from yesoncheck.sidebar_thumbnails import SidebarThumbnailsMixin
# 다시 내보내기만 함 (이 모듈은 안 씀): 기존 `from yesoncheck.player_sidebar import …`·`player_sidebar.X` 접근이 같은 객체로 돌게.
# 시험이 바꿔치기하는 gather_shared_config·list_works_not_opening은 믹스인이 shared_config_load.X로 불러 바꿔치기 지점을 그 모듈
# 한 곳으로 둠 (여기서 이 이름을 바꿔치기해도 닿지 않음)
from yesoncheck.shared_config_load import (
    SharedConfigLoad,
    gather_shared_config,
    list_works_not_opening,
)
# SidebarScan도 다시 내보내기만 함 (이 모듈은 안 씀 — 믹스인이 sidebar_refresh에서 바로 불러 씀): 기존 `player_sidebar.SidebarScan` 접근이 같은 객체로 돌게.
from yesoncheck.sidebar_refresh import SidebarScan
from yesoncheck.sidebar_items import (
    LIST_READ_FAILED,  # 다시 내보내기만 함 (이 모듈은 안 씀): test_sidebar_refresh가 이 경로로 가져옴
    NO_SEASON_WORKS,
    SIDEBAR_SOURCE_ROLE,
    THUMBNAIL_CONTEXT_ROLE,
    THUMBNAIL_FOLDER_PROBLEM,  # 다시 내보내기만 함 (이 모듈은 안 씀): test_sidebar_refresh가 이 경로로 가져옴
    ThumbnailContext,  # 다시 내보내기만 함 (이 모듈은 안 씀): player_playback·test_sidebar_refresh가 이 경로로 가져옴
)


class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin, SidebarRefreshMixin, SidebarSequencesMixin, SidebarAllMixin, SidebarThumbnailsMixin):

    def dragEnterEvent(self, event):
        """메인 윈도우에 파일 드래그앤드롭 이벤트"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        # 대상 VideoPlayer 찾기. 이 믹스인은 VideoPlayer 자신의 일부라 self가 open_file을 가진 최상위 창이면 self가 대상 (최상위 창은 parent()가
        # None이라 아래 부모 탐색만으로는 대상을 찾지 못해 창 본문에 놓은 파일이 말없이 아무 일도 없었음). 다른 위젯에 붙은 경우만 부모를 따라 올라감
        parent = self if hasattr(self, 'open_file') else self.parent()
        while parent and not hasattr(parent, 'open_file'):
            parent = parent.parent()
        
        if parent and hasattr(parent, 'open_file'):
            video_files = []
            has_folder = False
            read_failed = False  # 읽지 못한 폴더가 있음 (창으로 알림 — '지원되는 비디오 파일이 없습니다'는 띄우지 않음)
            folder_paths = []  # 폴더 경로들을 저장할 리스트
            frame_files = []  # 영상이 아닌 파일 — 이미지 시퀀스 프레임이면 그 시퀀스를 엶 (parent._dropped_frames가 이름을 봄). video_widget의 핸들러와 같은 코드를 유지
            
            # URL들을 파일/폴더로 분류
            for url in urls:
                local_path = paths.normalize_native(url.toLocalFile())
                if os.path.isfile(local_path):
                    # 파일인 경우
                    if parent.is_video_file(local_path):
                        video_files.append(local_path)
                    else:
                        frame_files.append(local_path)
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
            
            # 이미지 시퀀스 프레임 파일 (한 장뿐인 프레임·프레임이 아닌 파일은 빠짐 — 예전처럼 무시)
            frames = parent._dropped_frames(frame_files)
            
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
                elif parent._dropped_folders_have_sequences(folder_paths):
                    # 시퀀스만 든 폴더: 영상 폴더를 놓을 때처럼 목록을 새로 채우되 Seq 탭을 보여 줌 ('영상이 없습니다' 경고 없음)
                    parent.sidebar.clear()
                    parent._show_dropped_sequence_folders(folder_paths)
                elif not read_failed:
                    QMessageBox.warning(parent, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")
            else:
                # 개별 파일들만 있는 경우
                if frames:
                    # 프레임: 영상 파일이 함께 없으면 영상 파일을 놓을 때처럼 그 시퀀스를 열고 Seq 탭을 보여 줌. 영상이 함께 있으면 영상은 아래에서 예전대로,
                    # 시퀀스는 Seq 목록에만 더함
                    parent._add_dropped_frames(frames, show_tab=not video_files, open_them=not video_files)
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
            
            # 폴더와 함께 놓은 프레임의 시퀀스는 Seq 목록에만 더함 (폴더 처리는 위에서 예전대로)
            if has_folder and frames:
                parent._add_dropped_frames(frames)
        
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
        # 끌어다 놓은 폴더에서 함께 찾은 이미지 시퀀스는 Seq 목록에 덧붙임 (get_video_files_from_folder가 읽을 때 기억해 둠)
        self._add_seq_items(self._take_folder_sequences(folders))
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
            self._note_folder_sequences(folder_path, [])
            self._report_list_source_problem(folder_path, e)
            return None
        self._sidebar_scan_seconds = time.perf_counter() - started
        self._report_list_read(folder_path, result)
        self._note_folder_sequences(folder_path, result.sequences)  # 같은 읽기에서 찾은 시퀀스 (Seq 목록용 — 돌려주는 값은 영상 경로만)
        return [file_path for _name, file_path in result.videos]

    def show_sidebar_context_menu(self, pos):
        index = self.sidebar.indexAt(pos)
        if index.isValid():
            menu = QMenu(self.sidebar)
            self._build_sidebar_menu(menu, index)
            # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (index는 줄 번호 — 목록이 바뀌면 다른 영상을 가리킴)
            with self._hold_sidebar_refresh():
                menu.exec_(self.sidebar.viewport().mapToGlobal(pos))

    def _build_sidebar_menu(self, menu, index):
        """Mov 항목 메뉴의 동작들 (index는 Mov 목록의 줄 — All 탭도 선택을 비춘 뒤 같은 동작을 씀)."""
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
        sequences = self._take_folder_sequences([folder_path])  # 같은 읽기에서 함께 찾은 이미지 시퀀스
        
        if video_files or sequences:
            # 폴더 드래그앤드롭 시에는 기존 썸네일 폴더를 초기화하고 새로 설정 — 항목을 넣기 전에 (항목마다 이 자리를 기억).
            # 시퀀스만 든 폴더도 초기화: Seq 항목이 전에 연 job·폴더의 썸네일 폴더를 이어받아 첫 프레임 썸네일을 엉뚱한 곳에 쓰지 않게
            # (이 폴더의 썸네일 폴더는 처음 쓸 때 만듦 — 영상이 없으면 폴더를 열기만 해서는 만들지 않음)
            self.current_thumbnail_folder = None  # 기존 썸네일 폴더 초기화
            self._thumbnail_folder_problem = None  # 전에 연 job의 썸네일 폴더 문제는 이제 상관없음
        if video_files:
            self.setup_thumbnail_folder()
            source = self._register_sidebar_source(video_list.ListSource("folder", folder_path))
        else:
            source = self._register_unread_folder(folder_path)  # 빈 폴더·읽지 못한 폴더
        
        # 사이드바에 파일들 추가
        self.playlist.extend(video_files)
        self._add_sidebar_videos([(os.path.basename(file_path), file_path, source) for file_path in video_files])
        self._set_seq_items(sequences)
        self._sidebar_read_done(None)  # 방금 읽음 (앱이 다시 활성돼도 곧바로 또 읽지 않게)
        
        if self.playlist:
            self.current_playlist_index = 0
            self.open_file('A', self.playlist[0])
            self.sidebar.selectAll()
            self.schedule_background_thumbnail_loading()
            QMessageBox.information(self, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
        elif sequences:
            # 시퀀스만 든 폴더: '영상이 없습니다'를 띄우지 않고 Seq 탭을 보여 줌 (탭 페이지 교체뿐 — 디스크를 읽지 않음).
            # 영상이 있는 폴더는 지금 보던 탭 그대로
            self.sidebar_tabs.setCurrentIndex(1)
        elif not read_failed:
            QMessageBox.warning(self, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")

    def load_selected_item_to_video_a(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            self.open_file('A', selected_items[0].toolTip())

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
