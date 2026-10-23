"""목록 다시 읽기 믹스인 (SidebarRefreshMixin)과 디스크 읽기 스레드 (SidebarScan): 사이드바 목록의 항목 모델과, 목록을 디스크와
맞추는 다시 읽기 흐름 (다른 앱에서 돌아올 때·같은 job을 다시 고를 때·새로고침 버튼(F5)·없는 영상을 열 때).

- 항목 모델: 항목 만들기·넣기(`_new_sidebar_item`·`_add_sidebar_videos`), 항목마다 들어온 곳과 썸네일 자리 기억
  (`_register_sidebar_source`·`_register_unread_folder`·`_forget_sidebar_sources`), 목록 세대 번호(`_bump_sidebar_generation`),
  쓰는 동안 다시 읽기를 미루는 `_hold_sidebar_refresh`와 미룬 읽기(`_run_deferred_sidebar_refresh`).
- 다시 읽기: 활성·버튼·F5로 시작(`_on_application_state_changed`·`_refresh_sidebar_on_activation`·`_refresh_sidebar_by_user`·
  `refresh_sidebar`), 뒤 스레드(`SidebarScan`)의 결과를 GUI 스레드에서 검사해 목록에 넣기(`_on_sidebar_scanned`·`_apply_sidebar_read`·
  `_apply_sidebar_plan`), 새로고침 때의 썸네일 확인(`_check_thumbnails_after_refresh`).
- 목록 문제 알림: 읽지 못한 폴더·지워진 폴더·확인하지 못한 파일을 창으로 (`_report_list_*`·`_report_unverified_files`).

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin, SidebarRefreshMixin, SidebarThumbnailsMixin)`. 그래서 VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin 앞)에 오고,
이 메서드들의 이름은 다른 믹스인·VideoPlayerBase와 겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.sidebar`·
`self._sidebar_sources`·`self._sidebar_generation`·`self._sidebar_scan` 등)는 예전처럼 VideoPlayerBase.__init__이 만들고, 썸네일
확인·만들기(`_apply_disk_thumbnails`·`generate_thumbnail`·`_make_thumbnails` 등)는 SidebarThumbnailsMixin의 메서드를 `self.`로 불러 그대로
닿음. 이 메서드들을 부르는 쪽(VideoPlayerBase의 신호 연결·메뉴·닫기, player_playback, video_widget의 드롭)도 `self.`·플레이어 객체로
부르므로 그대로 닿음.

SidebarScan은 이 모듈의 클래스지만 기존 경로 `yesoncheck.player_sidebar.SidebarScan`에서도 같은 객체로 불림 (player_sidebar가
다시 내보냄). 시험은 디스크 읽기를 `video_list.read_sources`(모듈 속성)로 바꿔치기하므로 이 모듈 이름과 무관하게 닿음.
player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
"""

import contextlib
import os
import sys
import time
import traceback

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidgetItem,
    QMessageBox,
)

from yesoncheck import paths, video_list
from yesoncheck.sidebar_items import (
    ACTIVATION_REFRESH_GAP_FACTOR,
    ACTIVATION_REFRESH_GAP_S,
    LIST_FOLDER_GONE,
    LIST_READ_FAILED,
    SIDEBAR_SOURCE_ROLE,
    THUMBNAIL_CONTEXT_ROLE,
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


class SidebarRefreshMixin:
    """VideoPlayer의 사이드바 목록 항목 모델(출처·세대·다시 읽기 보류)과 목록 다시 읽기·목록 문제 알림."""

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
        self._apply_seq_read(read)  # Seq 목록도 같은 읽기로 (폴더를 더 읽지 않음)
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
