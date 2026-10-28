"""썸네일 믹스인 (SidebarThumbnailsMixin): 사이드바의 썸네일 — 표시 모드·폭, 썸네일 반복, 영상 단위 확인·만들기,
썸네일 폴더와 문제 알림, 백그라운드 읽기.

- 표시 모드·폭: 목록/썸네일 모드 바꾸기와 사이드바 폭(`switch_to_list_mode`·`switch_to_thumbnail_mode`·`update_sidebar_display`·
  `initialize_sidebar_width`·`_resize_sidebar_column`).
- 반복·워커 정리: 모든 영상의 썸네일 만들기 흐름(`generate_thumbnails_for_all_items`·`_make_thumbnails`), 반복을 멈출 까닭
  (`_thumbnail_pass_state`·`_thumbnail_pass_stopped`), 워커·로더 정리(`cleanup_thumbnail_workers`·`cleanup_background_threads`).
- 영상 단위 확인·만들기: 항목의 썸네일 자리(`_item_thumbnail_context`·`_resolve_pending_thumbnail_context`), 저장된 썸네일 붙이기
  (`_apply_disk_thumbnails`·`_has_disk_thumbnail`), 워커 띄우기(`generate_thumbnail` — ThumbnailWorker), 결과 슬롯(`on_thumbnail_ready`·
  `update_sidebar_item_thumbnail`), 다시 만들기·지우기(`regenerate_selected_thumbnails`·`delete_thumbnail_file`·`clear_thumbnails`).
- 썸네일 폴더·문제 알림: job/폴더의 썸네일 폴더(`get_current_job_path`·`setup_thumbnail_folder`·`_use_dropped_folder_for_thumbnails`),
  (폴더, 제목)마다 한 번 창으로(`_report_*`·`_on_thumbnail_failed`·`_on_thumbnail_save_failed`).
- 백그라운드 읽기: 목록의 썸네일 파일을 뒤 스레드(ThumbnailLoaderWorker)로 읽어 아이콘으로 (`start_background_thumbnail_loading`·
  `on_background_thumbnail_loaded`·`on_background_loading_finished`·`schedule_background_thumbnail_loading`).

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin,
SidebarConfigPathsMixin, SidebarRefreshMixin, SidebarThumbnailsMixin)`. 그래서 VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin
앞)에 오고, 이 메서드들의 이름은 다른 믹스인·VideoPlayerBase와 겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.sidebar`·
`self.thumbnail_workers`·`self.is_thumbnail_mode`·`self.current_thumbnail_folder` 등)는 예전처럼 VideoPlayerBase.__init__이 만들고,
PlayerSidebarMixin에 남은 드롭·파일 넣기(`add_files_to_sidebar`·`load_videos_from_folder`)와 다른 믹스인(목록 다시 읽기·북마크)·
VideoPlayerBase의 신호 연결·player_playback·video_widget도 이 메서드들을 `self.`·플레이어 객체로 불러 그대로 닿음.

`generate_thumbnail`은 ThumbnailWorker를, `start_background_thumbnail_loading`은 ThumbnailLoaderWorker를 이 모듈의 전역 이름으로 찾음 —
시험이 ThumbnailWorker를 바꿔치기하려면 이 모듈의 이름(`sidebar_thumbnails.ThumbnailWorker`)을 바꿔야 닿음.
player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
"""

import functools
import os
import stat
import time

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QWIDGETSIZE_MAX,
)

from yesoncheck.workers import ThumbnailLoaderWorker, ThumbnailWorker

from yesoncheck import paths, thumbnails
from yesoncheck.sidebar_items import (
    THUMBNAIL_CONTEXT_ROLE,
    THUMBNAIL_FOLDER_PROBLEM,
    THUMBNAIL_MAKE_FAILED,
    THUMBNAIL_SAVE_FAILED,
    THUMBNAIL_VIDEO_PROBLEM,
    ThumbnailContext,
)


class SidebarThumbnailsMixin:
    """VideoPlayer의 썸네일: 표시 모드·사이드바 폭, 썸네일 반복·워커 정리, 영상 단위 확인·만들기, 썸네일 폴더·문제 알림, 백그라운드 읽기."""

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

    def _resize_sidebar_column(self, list_width):
        """사이드바 목록이 list_width가 되도록 메인 스플리터의 왼쪽 칸 너비를 바꿈 — 늘어난 만큼 영상 쪽에서 가져오고
        줄어든 만큼 영상 쪽에 줌. 창이 좁아 다 못 가져오면 스플리터가 최소 너비 안에서 맞춤.

        지금 목록 폭은 보이는 탭 페이지에서 읽음 — 숨은 페이지(Seq·All 탭이 보일 때의 Mov 목록)의 width()는
        레이아웃이 돌지 않아 낡은 값이라, 그걸 쓰면 누를 때마다 차액이 누적돼 칸이 계속 커지거나 작아짐."""
        sizes = self.mainSplitter.sizes()
        page = self.sidebar_tabs.currentWidget()
        column = sizes[0] + list_width - page.width()
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
