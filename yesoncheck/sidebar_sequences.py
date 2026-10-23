"""사이드바 Seq 탭 믹스인 (SidebarSequencesMixin): 이미지 시퀀스 목록(self.seq_sidebar)과 Mov·Seq 탭 전환.

- 목록 채우기: 영상 목록을 만드는 읽기(video_list.ScanResult)가 같은 폴더 목록에서 함께 찾은 시퀀스(`ScanResult.sequences`)를
  그 읽기가 끝날 때마다 받아 넣음 — 폴더를 더 읽지 않음. 첫 불러오기(`_load_job_list`·`load_videos_from_folder`)는 `_set_seq_items`,
  끌어다 놓은 폴더는 `_add_seq_items`(목록에 덧붙임), 목록 다시 읽기(`_apply_sidebar_read`)는 `_apply_seq_read`.
  Mov 목록을 비우면(`self.sidebar.clear()` — job을 바꿈·폴더를 불러옴·읽지 못함) Seq 목록도 함께 비움(`_clear_seq_items`).
- 항목: 라벨 "베이스 (처음–끝, N프레임)"(+ 빠진 프레임이 있으면 ", 빠짐 N"), `Qt.UserRole`에 `SeqInfo`(프레임 파일 이름은 들지 않음),
  툴팁은 사람이 읽는 정보. Mov 목록 코드는 `item.toolTip()`을 경로로 읽지만 이 목록은 별도 위젯이라 그 관례가 닿지 않음.
- 누르기: `on_seq_item_clicked` → 시퀀스를 A로 엶 (`open_file('A', seq.identity)`, Mov 목록 누르기와 같은 규칙).
- 탭 전환(`_on_sidebar_tab_changed`)은 페이지 교체뿐 — GUI 스레드는 디스크를 읽지 않음 (썸네일 모드면 Seq 썸네일을 뒤 스레드로 다시
  읽을 뿐). Seq 탭에서는 'Play Selected' 단추를 끔 (선택 재생은 Mov 경로 전제).
- 썸네일: Seq 목록은 전역 표시 모드(List/Thumb 단추 — `_apply_seq_display_mode`)를 따르고, 썸네일 모드에서 읽기 전용 경량 경로
  (`_load_seq_thumbnails` — SeqThumbnailLoaderWorker가 뒤 스레드에서 디스크의 썸네일을 읽어 아이콘만 붙임)로 보여 줌. 시퀀스의 썸네일은
  짝 영상(<base>.mov, 없으면 <base>.mp4)의 기존 썸네일 파일 그대로 (같은 키 — 디코드 0회)라 만들기 반복·진행바가 없고, 생성은 Mov 탭의 일.
  짝 영상이 없을 때만 ThumbnailWorker가 첫 프레임을 디코드해 만들며 (`_pump_seq_generation` — 한 번에 하나), 다시 만들기
  (`regenerate_seq_thumbnails` — Task 11의 컨텍스트 메뉴가 부름)도 같은 대기열. 항목은 Mov 항목처럼 넣을 때의 썸네일 자리를 기억
  (`THUMBNAIL_CONTEXT_ROLE`). Mov 쪽 썸네일 메서드는 부르기만 하고 바꾸지 않음 (`_resolve_pending_thumbnail_context`·`_report_*`·
  `update_sidebar_item_thumbnail`). 뒤 스레드 일은 `_seq_thumbnail_workers`에 모아 두고 끝나면 빼며, 목록을 비우거나 목록 모드로 바꾸거나
  창을 닫으면 `_stop_seq_thumbnail_work` (결과를 버리고 도는 워커는 worker_lifecycle.release_worker가 끝날 때까지 붙잡아 둠).
  짝 영상의 썸네일은 Mov 탭이 만드므로, 읽기를 시작할 때 Mov 탭이 아직 만드는 중이면(`self.thumbnail_workers` — Thumb 단추 직후)
  `_seq_thumbnail_timer`가 만들기가 끝나길 기다렸다가(읽지 않고 보기만) 한 번 더 읽음. 탭을 다시 볼 때도 읽음.

상태(`self.sidebar_tabs`·`self.seq_sidebar`·`self._folder_sequences`·`self._seq_thumbnail_workers`·`self._seq_generation_queue`·
`self._seq_generating`·`self._seq_thumbnail_timer`)는 예전처럼 VideoPlayerBase가 만들고(위젯은 initUI), 이 믹스인은 `self.`로 씀. PlayerSidebarMixin의 부모
클래스로 붙음. 이 모듈은 player_sidebar·player_base를 모듈 수준에서 import하지 않음 (순환).

`ThumbnailWorker`는 이 모듈의 전역 이름으로 찾음 — 시험이 바꿔치기하려면 이 모듈의 이름(`sidebar_sequences.ThumbnailWorker`)을 바꿔야 닿음.
"""

import functools
import os

from PyQt5.QtCore import QItemSelectionModel, QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QListWidgetItem

from yesoncheck import paths, sequence_source, thumbnails, video_list
from yesoncheck.sidebar_items import THUMBNAIL_CONTEXT_ROLE, THUMBNAIL_MAKE_FAILED, THUMBNAIL_VIDEO_PROBLEM
from yesoncheck.thumbnail_workers import SeqThumbnailLoaderWorker, ThumbnailWorker
from yesoncheck.worker_lifecycle import release_worker

SEQ_FOLLOWUP_MS = 300  # Mov 탭이 썸네일을 만드는 중에 시작한 Seq 썸네일 읽기를, 만들기가 끝났는지 이 간격으로 보며 기다림


def seq_label(seq):
    """Seq 목록 항목의 글자: `base (0001–0306, 300프레임)`, 빠진 프레임이 있으면 뒤에 `, 빠짐 N`."""
    text = f"{seq.base} ({seq.first:0{seq.pad}d}–{seq.last:0{seq.pad}d}, {seq.count}프레임)"
    if seq.missing > 0:
        text += f", 빠짐 {seq.missing}"
    return text


def seq_tooltip(seq):
    """Seq 항목의 툴팁: 사람이 읽는 정보 (폴더 경로·프레임 범위·빠진 프레임 수). 경로 하나가 아님."""
    lines = [seq.base, f"폴더: {seq.dir}", f"범위: {seq.first:0{seq.pad}d}–{seq.last:0{seq.pad}d} ({seq.count}프레임)"]
    if seq.missing > 0:
        lines.append(f"빠짐 {seq.missing}프레임")
    return "\n".join(lines)


def _seq_key(seq):
    """같은 시퀀스인지 (폴더·이름·확장자·자릿수 — 프레임 수가 달라도 같은 시퀀스의 새 읽기)."""
    return paths.path_key(seq.identity), seq.ext, seq.pad


def _merged(*groups):
    """시퀀스 묶음들을 하나로: 같은 시퀀스는 앞선 묶음의 것을 씀(그래서 새로 읽은 쪽을 앞에), 순서는 영상 목록과 같은 규칙."""
    unique = {}
    for group in groups:
        for seq in group:
            unique.setdefault(_seq_key(seq), seq)
    return video_list.sort_sequences(unique.values())


class SidebarSequencesMixin:
    """VideoPlayer의 Seq 목록(self.seq_sidebar)과 Mov·Seq 탭 (self.sidebar_tabs)."""

    # ---------------------------------------------------------------- 목록

    def _current_seq_items(self):
        """지금 Seq 목록의 SeqInfo들 (목록 순서)."""
        return [self.seq_sidebar.item(i).data(Qt.UserRole) for i in range(self.seq_sidebar.count())]

    def _new_seq_item(self, seq, context):
        item = QListWidgetItem(seq_label(seq))
        item.setData(Qt.UserRole, seq)
        item.setData(THUMBNAIL_CONTEXT_ROLE, context)
        item.setToolTip(seq_tooltip(seq))
        return item

    def _set_seq_items(self, seqs):
        """Seq 목록을 seqs(SeqInfo 목록)로 바꿈. 같으면 목록을 건드리지 않음 (깜빡임 없음). 바뀌면 선택·현재 항목은 같은 시퀀스
        (폴더·이름)에 그대로 (스크롤 위치는 항목을 한 번에 다시 넣으므로 Qt가 그대로 둠 — 시험이 지킴)."""
        seqs = list(seqs)
        if seqs == self._current_seq_items():
            return
        widget = self.seq_sidebar
        selected = {item.data(Qt.UserRole).identity for item in widget.selectedItems()}
        current = widget.currentItem()
        current_identity = current.data(Qt.UserRole).identity if current is not None else None
        # 이미 있던 시퀀스는 그 항목의 썸네일 자리 그대로, 새 시퀀스는 지금의 자리 (Mov 항목과 같은 규칙 — 재검토 L1)
        contexts = {_seq_key(widget.item(i).data(Qt.UserRole)): widget.item(i).data(THUMBNAIL_CONTEXT_ROLE)
                    for i in range(widget.count())}
        widget.setUpdatesEnabled(False)
        try:
            widget.clear()
            for seq in seqs:
                context = contexts.get(_seq_key(seq)) or self._new_item_thumbnail_context(seq.identity)
                widget.addItem(self._new_seq_item(seq, context))
            for i in range(widget.count()):
                item = widget.item(i)
                identity = item.data(Qt.UserRole).identity
                if identity == current_identity:
                    widget.setCurrentItem(item, QItemSelectionModel.NoUpdate)
                item.setSelected(identity in selected)
        finally:
            widget.setUpdatesEnabled(True)
        self._load_seq_thumbnails()  # 썸네일 모드면 새 목록의 썸네일도 (목록 모드면 아무것도 안 함)

    def _add_seq_items(self, seqs):
        """Seq 목록에 seqs를 덧붙임 (끌어다 놓은 폴더). 이미 있는 시퀀스는 새로 읽은 것으로 바꿈."""
        self._set_seq_items(_merged(seqs, self._current_seq_items()))

    def _clear_seq_items(self):
        """Mov 목록을 비움(clear → 모델 초기화)과 함께 Seq 목록도 비움: 지난 job·폴더의 시퀀스가 남지 않게 (새 목록을 넣는 쪽이 다시 채움).
        읽던·만들던 Seq 썸네일 일도 멈춤 (지난 목록의 결과가 새 목록에 붙지 않게)."""
        self._stop_seq_thumbnail_work()
        self.seq_sidebar.clear()

    def _note_folder_sequences(self, folder_path, sequences):
        """폴더를 읽어 찾은 시퀀스를 기억 — 영상 경로만 돌려주는 get_video_files_from_folder와, 그 뒤 목록을 비우고 채우는 부른 쪽
        (끌어다 놓기·폴더 불러오기)를 잇는 자리. 쓰는 쪽이 _take_folder_sequences로 꺼냄."""
        self._folder_sequences[paths.path_key(folder_path)] = list(sequences)

    def _take_folder_sequences(self, folders):
        """_note_folder_sequences로 기억한 폴더들의 시퀀스를 꺼냄 (읽지 못한 폴더·읽은 적 없는 폴더는 없음)."""
        found = []
        for folder in folders:
            found.extend(self._folder_sequences.pop(paths.path_key(folder), ()))
        return found

    def _apply_seq_read(self, read):
        """목록 다시 읽기의 결과(video_list.SourcesRead)로 Seq 목록을 맞춤 — Mov 목록과 같은 읽기, 폴더를 더 읽지 않음.

        읽은 곳은 읽은 대로. 읽지 못한 곳(NAS 연결 끊김·권한)과 읽은 곳의 읽지 못한 하위 폴더 아래의 시퀀스는 지금 목록 그대로 둠
        (Mov 목록이 그곳의 영상을 빼지 않는 것과 같음 — ScanResult.keeps는 영상만 알아서 쓰지 않음). 지워진 폴더의 시퀀스는 뺌.
        """
        current = self._current_seq_items()
        fresh = []
        kept = []
        for source, result in read.results.items():
            if isinstance(result, video_list.ScanResult):
                fresh.extend(result.sequences)
                kept.extend(seq for seq in current
                            if any(video_list.is_under(seq.dir, folder) for folder, _error in result.unreadable))
            elif result is None:
                kept.extend(seq for seq in current if video_list.is_under(seq.dir, source.folder))
        self._set_seq_items(_merged(fresh, kept))

    # ---------------------------------------------------------------- 누르기·탭

    def on_seq_item_clicked(self, item):
        """Seq 항목을 누름: 그 시퀀스를 A로 엶 (Mov 목록을 누를 때처럼 선택 재생 중에는 무시)."""
        if self.is_playlist_playing:
            return
        self.open_file('A', item.data(Qt.UserRole).identity)

    def _on_sidebar_tab_changed(self, index):
        """Mov·Seq 탭 전환 — 페이지가 바뀔 뿐 GUI 스레드는 디스크를 읽지 않음. Seq 탭에서는 'Play Selected'를 끔 (선택 재생은 영상
        경로 전제). 썸네일 모드에서 Seq 탭을 보면 그 사이 Mov 탭이 만든 썸네일도 보이게 Seq 썸네일을 뒤 스레드로 다시 읽음."""
        on_seq_page = self.sidebar_tabs.widget(index) is self.seq_sidebar
        self.playSelectedButton.setEnabled(not on_seq_page)
        if on_seq_page:
            self._load_seq_thumbnails()

    # ---------------------------------------------------------------- 썸네일 (짝 영상의 썸네일 재사용 — 읽기 전용 경량 경로)

    def _seq_thumbnail_folder(self, item):
        """항목의 썸네일 폴더를 읽기 전용으로 (만들지 않음): 정한 폴더, 아직 정하지 않은 자리면 쓰게 될 폴더 경로, 폴더 문제면 None."""
        context = item.data(THUMBNAIL_CONTEXT_ROLE)
        if context.folder:
            return context.folder
        if context.pending_base is not None:
            return os.path.join(context.pending_base, thumbnails.FOLDER_NAME)
        return None

    def _seq_items_with_identity(self, identity):
        """그 가상 경로의 Seq 항목들 (같은 이름의 다른 확장자·자릿수 시퀀스는 같은 썸네일 파일을 씀)."""
        items = (self.seq_sidebar.item(i) for i in range(self.seq_sidebar.count()))
        return [item for item in items if item.data(Qt.UserRole).identity == identity]

    def _apply_seq_display_mode(self, *_checked):
        """List/Thumb 단추 (Mov 쪽 슬롯 다음에 이어 놓음 → is_thumbnail_mode가 이미 바뀌어 있음): Seq 목록을 전역 표시 모드에 맞춤.
        어느 탭이 보이든 같음 — 두 목록이 모드 하나를 따름. 사이드바 폭은 두 탭이 같은 칸이라 Mov 쪽이 바꾼 그대로."""
        widget = self.seq_sidebar
        if self.is_thumbnail_mode:
            widget.setIconSize(QSize(self.thumbnail_size, self.thumbnail_size))
            widget.setSpacing(10)
            self._load_seq_thumbnails()
        else:
            widget.setSpacing(0)
            self._stop_seq_thumbnail_work()
            for i in range(widget.count()):
                widget.item(i).setIcon(QIcon())

    def _load_seq_thumbnails(self, followup=False):
        """썸네일 모드면 Seq 목록의 썸네일을 뒤 스레드로 읽어 아이콘만 붙임 (목록 모드면 아무것도 하지 않음).

        읽기 전용 경량 경로: GUI 스레드는 디스크를 읽지 않고 (항목에 기억한 썸네일 자리만 봄), SeqThumbnailLoaderWorker가 짝 영상을 찾아
        그 영상의 썸네일 jpg를 읽어 옴 — 디코드 0회, 만들기 반복·진행바 없음. 읽던 일이 있으면 결과를 버리고 새로 읽음.
        짝 영상의 썸네일은 Mov 탭이 만드는데, 이 읽기를 시작할 때 Mov 탭이 아직 만드는 중이면(Thumb 단추 직후) 그 사이 생기는 썸네일을
        놓치지 않게 만들기가 끝난 뒤 한 번 더 읽음 (followup: 그 한 번 더 — 또 예약하지 않음).
        """
        if not self.is_thumbnail_mode or self._sidebar_scan_closed:  # 목록 모드이거나 창을 닫음 (닫은 뒤에는 새 일을 시작하지 않음)
            return
        self._stop_seq_loader()
        jobs = []
        for i in range(self.seq_sidebar.count()):
            item = self.seq_sidebar.item(i)
            folder = self._seq_thumbnail_folder(item)
            if folder:  # 썸네일 폴더 문제가 있는 자리는 읽을 썸네일이 없음
                jobs.append((item.data(Qt.UserRole), folder))
        if not jobs:
            return
        worker = SeqThumbnailLoaderWorker(jobs)
        worker.image_loaded.connect(self._on_seq_thumbnail_image)
        worker.needs_generation.connect(self._on_seq_thumbnail_missing)
        worker.failed.connect(self._on_seq_thumbnails_failed)
        self._start_seq_worker(worker)
        if not followup and self.thumbnail_workers:
            self._seq_thumbnail_timer.start(SEQ_FOLLOWUP_MS)

    def _load_seq_thumbnails_after_mov(self):
        """_seq_thumbnail_timer: Mov 탭이 썸네일을 다 만들었으면 Seq 썸네일을 한 번 더 읽고, 아직이면 조금 뒤에 다시 봄 (읽지 않고 기다리기만)."""
        if self.thumbnail_workers:
            self._seq_thumbnail_timer.start(SEQ_FOLLOWUP_MS)
        else:
            self._load_seq_thumbnails(followup=True)

    def _on_seq_thumbnail_image(self, identity, image):
        """읽은 썸네일을 그 시퀀스의 아이콘으로 (GUI 스레드에서 QPixmap으로)."""
        if not self.is_thumbnail_mode:
            return
        icon = QIcon(QPixmap.fromImage(image))
        for item in self._seq_items_with_identity(identity):
            item.setIcon(icon)

    def _on_seq_thumbnail_missing(self, identity):
        """짝 영상이 없고 쓸 만한 썸네일도 없는 시퀀스: 첫 프레임으로 만들 대기열에 (썸네일 모드에서 읽다가 알게 됨; 탭을 오가며 다시
        읽어 같은 시퀀스를 또 알려도 대기열에는 한 번)."""
        items = self._seq_items_with_identity(identity)
        if (not items or not self.is_thumbnail_mode or self._sidebar_scan_closed
                or any(job[0] == identity for job in self._seq_generation_queue)):
            return
        self._queue_seq_generation(items[0], None)
        self._pump_seq_generation()

    def _on_seq_thumbnails_failed(self, folder, detail):
        """SeqThumbnailLoaderWorker.failed: 짝 영상·썸네일·첫 프레임 파일을 확인하지 못함 → 창 ((폴더, 제목)마다 한 번), 스택 트레이스째."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_VIDEO_PROBLEM,
            "시퀀스의 썸네일을 읽지 못해 읽지 못한 시퀀스는 아이콘 없이 둡니다 (짝 영상·썸네일·첫 프레임을 확인하지 못함 — 권한·연결 끊김 등).\n"
            f"{detail}",
        )

    # ---- 만들기 (짝 영상이 없을 때의 첫 프레임 폴백, 다시 만들기) — 한 번에 하나씩

    def _seq_writable_context(self, item):
        """항목의 썸네일 자리를 저장할 수 있게 정함: 아직 정하지 않은 자리면 폴더를 만들고(Mov와 같은 자리를 기다리던 항목 모두에 기억),
        미뤄 둔 폴더 문제는 창으로 ((폴더, 제목)마다 한 번)."""
        context = item.data(THUMBNAIL_CONTEXT_ROLE)
        if context.pending_base is not None:
            resolved = self._resolve_pending_thumbnail_context(context)
            for i in range(self.seq_sidebar.count()):
                other = self.seq_sidebar.item(i)
                if other.data(THUMBNAIL_CONTEXT_ROLE) == context:
                    other.setData(THUMBNAIL_CONTEXT_ROLE, resolved)
            context = resolved
        self._report_context_problem(context)
        return context

    def _queue_seq_generation(self, item, movie):
        """item의 썸네일을 만들 일을 대기열에: 짝 영상(movie)이 있으면 그 영상에서, 없으면 첫 프레임 파일에서."""
        seq = item.data(Qt.UserRole)
        context = self._seq_writable_context(item)
        if movie is None:
            self._seq_generation_queue.append((seq.identity, seq.identity, seq, context))
        else:
            self._seq_generation_queue.append((seq.identity, movie, None, context))

    def _pump_seq_generation(self):
        """대기열의 다음 썸네일을 ThumbnailWorker로 만듦 — 한 번에 하나 (끝나면 다음). 만들기 반복·진행바 없음."""
        if self._seq_generating is not None or not self._seq_generation_queue or self._sidebar_scan_closed:
            return
        identity, file_path, seq, context = self._seq_generation_queue.pop(0)
        worker = ThumbnailWorker(file_path, self.thumbnail_size, context.folder, seq)
        worker.thumbnail_ready.connect(functools.partial(self._on_seq_thumbnail_ready, identity))
        worker.save_failed.connect(self._on_thumbnail_save_failed)
        folder = context.folder or (context.problem[0] if context.problem else None) or context.pending_base
        worker.failed.connect(functools.partial(self._on_seq_thumbnail_make_failed, folder))
        self._seq_generating = worker
        self._start_seq_worker(worker)

    def _on_seq_thumbnail_ready(self, identity, path, pixmap):
        """만든 썸네일: 그 시퀀스의 아이콘으로 (썸네일 모드에서만 — 목록 모드는 아이콘이 없음). path가 짝 영상이면 Mov 목록의 그 영상
        아이콘도 새 썸네일로 (같은 파일을 바꿨으므로)."""
        if pixmap.isNull() or not self.is_thumbnail_mode:
            return
        icon = QIcon(pixmap)
        for item in self._seq_items_with_identity(identity):
            item.setIcon(icon)
        if path != identity:
            self.update_sidebar_item_thumbnail(path, pixmap)

    def _on_seq_thumbnail_make_failed(self, folder, detail):
        """ThumbnailWorker.failed (Seq): 시퀀스·짝 영상의 썸네일을 만들지 못함 → 창 ((폴더, 제목)마다 한 번)."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_MAKE_FAILED,
            "썸네일을 만들지 못해 이 시퀀스는 아이콘 없이 둡니다 (프레임이나 짝 영상이 손상되었거나 지원하지 않는 형식이거나 읽을 수 없음).\n"
            f"{detail}",
        )

    def regenerate_seq_thumbnails(self, items):
        """Seq 항목들의 썸네일을 지우고 다시 만듦 (Task 11의 Seq 컨텍스트 메뉴 '썸네일 다시 만들기'가 부름; items: seq_sidebar의 항목들).

        짝 영상이 있으면 그 영상의 썸네일 — Mov 탭과 같은 파일을 같은 ThumbnailWorker 흐름으로 다시 만들고 Mov 목록의 아이콘도 바뀜.
        없으면 첫 프레임으로. 한 번에 하나씩 대기열로 만들며, 목록 모드에서도 파일은 다시 만듦 (아이콘은 썸네일 모드에서만).
        지우기·폴더 만들기 오류는 삼키지 않고 그대로 올림.
        """
        for item in items:
            seq = item.data(Qt.UserRole)
            movie = sequence_source.paired_movies(seq.dir, {seq.base})[seq.base]
            self._queue_seq_generation(item, movie)
            _identity, file_path, _seq, context = self._seq_generation_queue[-1]
            if context.folder:
                try:
                    os.remove(thumbnails.thumbnail_path(context.folder, file_path))
                except FileNotFoundError:
                    pass  # 아직 없거나 그사이 다른 PC가 지움
        self._pump_seq_generation()

    # ---- 뒤 스레드 일 관리

    def _start_seq_worker(self, worker):
        worker.finished.connect(functools.partial(self._on_seq_worker_finished, worker))
        self._seq_thumbnail_workers.append(worker)
        worker.start()

    def _on_seq_worker_finished(self, worker):
        """워커가 끝남: 목록에서 빼고 정리. 만들던 워커였으면 대기열의 다음 것. (멈춰서 이미 놓은 워커의 늦은 신호는 무시)"""
        if worker not in self._seq_thumbnail_workers:
            return
        self._seq_thumbnail_workers.remove(worker)
        worker.wait(2000)  # finished는 run이 끝나는 길목에서 옴: 스레드가 완전히 끝난 뒤에 지움
        worker.deleteLater()
        if worker is self._seq_generating:
            self._seq_generating = None
            self._pump_seq_generation()

    def _stop_seq_loader(self):
        """읽던 SeqThumbnailLoaderWorker가 있으면 멈추고 결과를 버림 (만들던 워커는 그대로)."""
        for worker in [w for w in self._seq_thumbnail_workers if w is not self._seq_generating]:
            self._seq_thumbnail_workers.remove(worker)
            worker.stop()
            release_worker(worker, "Seq 썸네일 읽기")

    def _stop_seq_thumbnail_work(self):
        """Seq 썸네일 일을 모두 멈춤 (목록을 비움·목록 모드로 바꿈·창을 닫음): 대기열을 비우고, 도는 워커는 결과를 버리고 끝날 때까지
        붙잡아 둠 (release_worker — 기다리지 않음. 첫 프레임을 만들던 워커는 그 한 장만 마저 저장함)."""
        self._seq_thumbnail_timer.stop()
        self._seq_generation_queue.clear()
        generating, self._seq_generating = self._seq_generating, None
        workers, self._seq_thumbnail_workers = self._seq_thumbnail_workers, []
        for worker in workers:
            if worker is not generating:
                worker.stop()
            release_worker(worker, "Seq 썸네일 만들기" if worker is generating else "Seq 썸네일 읽기")
