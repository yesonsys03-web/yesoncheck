"""Media library and sidebar helpers for VideoPlayer."""

import os
import shutil
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QMenu,
    QMessageBox,
)

from yesoncheck import error_window, mac_open_panel, paths, sequence_scan, ui_text, video_list
# PlayerSidebarMixin의 부모 믹스인 (북마크, 선택 재생, 공유 설정·작품 경로, 목록 다시 읽기, Seq 탭, 썸네일)
from yesoncheck.sidebar_ab_buttons import SidebarAbButtonsMixin
from yesoncheck.sidebar_all import SidebarAllMixin
from yesoncheck.sidebar_bookmarks import SidebarBookmarksMixin
from yesoncheck.sidebar_open_with import SidebarOpenWithMixin
from yesoncheck.sidebar_sorting import SidebarSortMixin
from yesoncheck.sidebar_playlist import SidebarPlaylistMixin
from yesoncheck.sidebar_config_paths import SidebarConfigPathsMixin
from yesoncheck.sidebar_controls import SidebarControlsMixin
from yesoncheck.sidebar_keys import SidebarKeysMixin
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


def one_dialog_picks_both():
    """기본(네이티브) 열기 창 하나에서 폴더와 파일을 모두 고를 수 있는 플랫폼인지 — Mac만.

    Windows의 기본 창은 폴더 고르기와 파일 고르기가 따로라(한 창에서 둘 다는 못 함) '폴더 열기' 단추가 두 항목을 띄움.
    """
    return sys.platform == "darwin"


def _as_on_disk(path):
    """고른 경로가 그대로는 없으면 이름의 유니코드 정규화(NFC·NFD)만 다른 실제 경로를, 아니면 그대로.

    NFS 공유는 한글 이름을 바이트 그대로 견줌 — Mac의 열기 창이 준 경로의 모양(자모로 풀린 NFD인지)이 디스크의 이름과 다르면
    없다고 나옴. 받은 경로가 있으면 늘 그것(고른 바로 그 항목), 없을 때만 찾음 — 받은 첫 파일을 열 때와 같은 도우미
    paths.find_unicode_variant: 하나로 정하지 못하면 None — 그때는 '찾을 수 없음'으로 알림.
    """
    return paths.find_unicode_variant(path) or path


def _frame_of_sequences(file_path, sequences):
    """file_path가 sequences(SeqInfo들) 중 하나의 프레임인지 — 이름 규칙으로만 봄 (디스크를 읽지 않음)."""
    folder, name = os.path.split(file_path)
    parsed = sequence_scan.parse_frame_name(name)
    if parsed is None:
        return False
    base, _number, ext, pad = parsed
    key = paths.path_key(folder)
    return any(paths.path_key(seq.dir) == key and (seq.base, seq.ext, seq.pad) == (base, ext, pad) for seq in sequences)


class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin, SidebarControlsMixin, SidebarRefreshMixin, SidebarSequencesMixin, SidebarAllMixin, SidebarSortMixin, SidebarOpenWithMixin, SidebarThumbnailsMixin, SidebarKeysMixin, SidebarAbButtonsMixin):

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
                # 개별 파일들만 있는 경우: 열고 목록에도 넣음 ('폴더 열기'로 고른 파일과 같은 한 곳)
                parent.open_dropped_files(video_files, frames)
            
            # 폴더와 함께 놓은 프레임의 시퀀스는 Seq 목록에만 더함 (폴더 처리는 위에서 예전대로)
            if has_folder and frames:
                parent._add_dropped_frames(frames)
        
        event.acceptProposedAction()

    def is_video_file(self, file_path):
        """파일이 지원되는 비디오 형식인지 확인"""
        return os.path.splitext(file_path.lower())[1] in video_list.VIDEO_EXTENSIONS

    def open_dropped_files(self, video_files, frames):
        """폴더 없이 가져온 파일들을 엶 — 영상 영역·창 본문에 놓은 파일과 '폴더 열기'로 고른 파일이 함께 지나는 한 곳.

        영상: 첫째를 A로(둘이면 둘째를 B로) 열고 **모두 Mov 목록에 넣음** — 지금 목록은 그대로 두고 끝에 더하며, 이미 목록에 있는
        영상은 다시 넣지 않음 (사용자 지시 2026-11-25: 사이드바에 놓으면 목록에 보이는데 영상 영역에 놓으면 보이지 않았음 — 전에는
        하나·둘이면 열기만, 셋 이상이면 첫째를 뺀 나머지만 목록에). 하나·둘이면 안내 창 없이(영상이 열리는 것이 답), 셋 이상이면
        예전처럼 안내 — 더한 것이 없으면(모두 이미 목록에 있음) '추가되었습니다'라고 하지 않음.
        프레임(이미지 시퀀스 — _dropped_frames가 고른 것): 영상이 함께 없으면 그 시퀀스를 열고 Seq 탭을 보여 줌, 함께 있으면 Seq 목록에만.
        """
        if frames:
            self._add_dropped_frames(frames, show_tab=not video_files, open_them=not video_files)
        if not video_files:
            return
        self.open_file('A', video_files[0])
        if len(video_files) == 2:
            self.open_file('B', video_files[1])
        many = len(video_files) > 2
        new_files = self._list_new_videos(video_files, announce=many)
        if many and new_files:
            QMessageBox.information(self, "파일 로드 완료", f"첫 번째 파일이 Video A에 로드되고, {len(new_files)}개의 파일이 사이드바에 추가되었습니다.")

    def list_opened_video(self, file_path):
        """밖에서 받아 연 파일(동영상 더블클릭 — Windows 연결 프로그램·Mac Finder·다음으로 열기, 새 창이 받은 파일: app.open_startup_file)을
        Mov 목록에도 넣음 (사용자 지시 2026-11-25 — Windows 확인에서 "더블클릭해서 오픈했을 때 사이드바 리스트에 표시되지 않아").

        영상 파일일 때만(시퀀스의 프레임은 전처럼 열리기만), 이미 목록에 있으면 다시 넣지 않고, 안내 창 없이. 디스크에 없는 파일은
        넣지 않음 — 열지 못한 사유는 open_file이 이미 창으로 알림.
        """
        file_path = paths.normalize_native(file_path)
        if self.is_video_file(file_path):
            self._list_new_videos([file_path], announce=False)

    def _list_new_videos(self, video_files, announce):
        """영상들 중 아직 Mov 목록에 없는 것만 끝에 더함 → 더한 경로들 (같은 영상은 한 번 — path_key로 견줌)."""
        listed = set(self._known_sidebar_videos())
        new_files = []
        for file_path in video_files:
            key = paths.path_key(file_path)
            if key not in listed:
                listed.add(key)
                new_files.append(file_path)
        if new_files:
            self.add_files_to_sidebar(new_files, announce=announce)
        return new_files

    def add_files_to_sidebar(self, file_paths, folders=(), announce=True):
        """사이드바에 파일들을 추가 (항상 번호순 정렬). announce=False면 끝의 '추가되었습니다' 안내 창을 띄우지 않음.

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
        
        if file_paths and announce:
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
            # 메뉴를 연 줄이 고른 것 밖이면 그 줄만 고름 (Seq·All 메뉴와 같음 — 마우스 오른쪽 누름은 Qt가 이미 고르지만 메뉴 키·시험은 아님;
            # 같은 메뉴의 동작(파일 복사·다른 앱으로 열기 등)이 모두 같은 선택을 쓰게)
            clicked = self.sidebar.item(index.row())
            if clicked is not None and not clicked.isSelected():
                self.sidebar.clearSelection()
                clicked.setSelected(True)
            menu = QMenu(self.sidebar)
            self._build_sidebar_menu(menu, index)
            self._add_open_with_actions(menu, self._mov_open_entries())  # 맨 아래 '다른 앱으로 열기' (sidebar_open_with)
            # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (index는 줄 번호 — 목록이 바뀌면 다른 영상을 가리킴)
            with self._hold_sidebar_refresh():
                menu.exec_(self.sidebar.viewport().mapToGlobal(pos))

    def _build_sidebar_menu(self, menu, index):
        """Mov 항목 메뉴의 동작들 (index는 Mov 목록의 줄 — All 탭도 선택을 비춘 뒤 같은 동작을 씀)."""
        open_video_a_action = menu.addAction(ui_text.text("side_menu.open_a"))
        open_video_a_action.triggered.connect(lambda: self.open_video_a(index))
        open_video_b_action = menu.addAction(ui_text.text("side_menu.open_b"))
        open_video_b_action.triggered.connect(lambda: self.open_video_b(index))

        # 구분선 추가
        menu.addSeparator()

        merge_videos_action = menu.addAction(ui_text.text("side_menu.merge"))
        merge_videos_action.triggered.connect(self.merge_videos)

        # 구분선 추가
        menu.addSeparator()

        copy_file_action = menu.addAction(ui_text.text("side_menu.copy"))
        copy_file_action.triggered.connect(self.copy_selected_files)  # copy_selected_files 메서드 호출

        # 구분선 추가
        menu.addSeparator()

        # 썸네일 재생성 메뉴 추가
        regenerate_thumbnail_action = menu.addAction(ui_text.text("side_menu.thumbnails"))
        regenerate_thumbnail_action.triggered.connect(lambda: self.regenerate_selected_thumbnails())

        # 구분선 추가
        menu.addSeparator()

        video_info_action = menu.addAction(ui_text.text("side_menu.info"))
        video_info_action.triggered.connect(lambda: self.show_video_info(index))

    def copy_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if not selected_items:
            return
        self._copy_files_choosing_folder([item.toolTip() for item in selected_items])

    def _copy_files_choosing_folder(self, file_paths):
        """폴더를 고르게 한 뒤 file_paths를 그 폴더로 복사 (고르지 않으면 아무것도 안 함)."""
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
        self.seasonComboBox.addItem(ui_text.text("picker.season"))

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
                self.jobComboBox.addItem(ui_text.text("picker.job"))
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
                self.jobComboBox.addItem(ui_text.text("picker.job"))
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
            self.jobComboBox.addItem(ui_text.text("picker.job"))
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
            self.jobComboBox.addItem(ui_text.text("picker.job"))
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
        self.jobComboBox.addItem(ui_text.text("picker.job"))
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

    def open_folder_clicked(self):
        """'폴더 열기' 단추 — 단추 하나로 폴더도 파일도 (사용자 지시 2026-11-25).

        Mac: 기본 열기 창 하나에서 폴더나 파일(여러 개)을 고름 (select_folder). 그 밖(Windows): 기본 창이 폴더와 파일을 함께 고르지 못해
        단추 바로 아래에 '폴더 고르기…'·'파일 고르기…'를 띄움 (옆의 북마크 단추와 같은 모양).
        """
        if one_dialog_picks_both():
            self.select_folder()
            return
        menu = self.open_folder_menu()
        menu.exec_(self.openFolderButton.mapToGlobal(self.openFolderButton.rect().bottomLeft()))
        menu.deleteLater()

    def open_folder_menu(self):
        """(Windows) '폴더 열기' 단추의 두 항목 — 띄우는 일은 부른 쪽 (시험은 항목을 바로 누름)."""
        menu = QMenu(self)
        menu.addAction(ui_text.text("sidebar.open_folder.folder")).triggered.connect(lambda: self.select_folder())
        menu.addAction(ui_text.text("sidebar.open_folder.files")).triggered.connect(lambda: self.select_files())
        return menu

    def select_folder(self):
        """File → 폴더 열기…·I 키 (Mac은 '폴더 열기' 단추도).

        Mac: 한 창에서 폴더나 파일(여러 개 — mac_open_panel) — 폴더면 예전 그대로 그 폴더를 불러오고, 파일이면 그 파일만 가져옴
        (open_picked_paths).
        창을 띄우지 못하면(PyObjC가 없는 환경 등) 트레이스백과 함께 오류 창 — 단추의 슬롯에서 예외가 새면 소스 실행의 앱이 죽음.
        그 밖: 예전 그대로 폴더 창 (파일은 단추의 '파일 고르기…').
        """
        if one_dialog_picks_both():
            try:
                picked = mac_open_panel.pick_folders_or_files(ui_text.text("sidebar.open_folder.pick"))
            except Exception:
                error_window.show_unexpected("[폴더 열기]", "폴더나 파일을 고르는 창을 띄우지 못했습니다.")
                return
            if getattr(self, "_closing_for_update", False):
                # 창이 떠 있는 동안 다른 창의 업데이트가 이 창을 닫음 (close_for_update가 열기 창을 취소함) — 닫히는 창에 아무것도 열지 않음
                print("[폴더 열기] 창이 닫히는 중이라 고른 것을 열지 않음", flush=True)
                return
            self.open_picked_paths(picked)
            return
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            self.load_videos_from_folder(folder_path)

    def select_files(self):
        """(Windows) '폴더 열기' → '파일 고르기…': 고른 파일만 가져옴 (여러 개 고를 수 있음, 필터 없음 — 이미지 시퀀스의 프레임도 고르게)."""
        chosen, _filter = QFileDialog.getOpenFileNames(self, ui_text.text("sidebar.open_folder.files.title"))
        self.open_picked_paths(chosen)

    def open_picked_paths(self, picked):
        """'폴더 열기'로 고른 경로들 (빈 글 = 취소).

        폴더면 예전 그대로 그 폴더를 불러옴 (load_videos_from_folder). 폴더는 한 번에 하나 — 폴더와 함께 다른 것(다른 폴더·파일)을
        골랐으면 첫 폴더를 불러오고 나머지는 가져오지 않았다고 알림 (여러 폴더는 창에 끌어다 놓기).
        파일이면 그 파일만 가져옴 — 영상 영역에 놓을 때와 같은 규칙 (open_dropped_files: A로 열고 Mov 목록에 더함, 프레임이면 그 시퀀스).
        가져오지 못한 것은 창 하나로 알림 (고른 것을 조용히 빼지 않음 — 가져올 수 있는 것은 그대로 가져옴): 폴더로도 파일로도 확인되지
        않는 경로(그새 지워짐·공유가 끊김 — 폴더 읽기에 넘기지 않음: 그쪽은 읽기 전에 목록부터 비우고 '읽지 못한 폴더'로 기억함)와
        영상도 시퀀스 프레임도 아닌 파일(한 장뿐인 프레임 포함).
        """
        picked = [_as_on_disk(paths.normalize_native(path)) for path in picked if path]
        if not picked:
            return
        folders = [path for path in picked if os.path.isdir(path)]
        if folders:
            rest = [path for path in picked if path != folders[0]]
            if rest:
                names = "\n".join(os.path.basename(path.rstrip("/\\")) or path for path in rest)
                QMessageBox.warning(self, "경고", f"폴더는 한 번에 하나만 불러옵니다. 함께 고른 것은 가져오지 않았습니다:\n{names}")
            self.load_videos_from_folder(folders[0])
            return
        files = [path for path in picked if os.path.isfile(path)]
        missing = [path for path in picked if path not in files]
        video_files = [path for path in files if self.is_video_file(path)]
        others = [path for path in files if not self.is_video_file(path)]
        frames = self._dropped_frames(others)
        unusable = [path for path in others if not _frame_of_sequences(path, frames.sequences)]
        problems = []
        if missing:
            problems.append("찾을 수 없어 가져오지 않았습니다:\n" + "\n".join(missing))
        if unusable:
            problems.append("영상 파일이나 이미지 시퀀스의 프레임이 아니어서 가져오지 않았습니다:\n"
                            + "\n".join(os.path.basename(path) for path in unusable))
        if problems:
            QMessageBox.warning(self, "경고", "\n\n".join(problems))
        if video_files or frames:
            self.open_dropped_files(video_files, frames)

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
        """(작품, 시즌, job) — '읽은 job'의 표지로 견줌. 고르지 않은 칸은 안내 글이 아니라 None(안내 글은 언어를 따름)."""
        return tuple(combo.currentText() if self._picked(combo) else None
                     for combo in (self.workComboBox, self.seasonComboBox, self.jobComboBox))

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
