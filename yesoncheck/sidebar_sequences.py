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

- 오른쪽 클릭 메뉴(`show_seq_context_menu`): 열기(A/B)·선택한 시퀀스로 MOV 만들기·썸네일 다시 만들기·정보 보기 — 다섯 개뿐 (mov 전용 합치기·
  OCR류 없음). 메뉴를 연 항목이 선택 밖이면 그 항목만 선택 (메뉴의 일은 눌린 항목에 대한 것), 선택 안이면 선택 전체가 일의 대상.
- 일괄 내보내기(`export_selected_sequences`): 선택 항목(목록 순서) -> 출력 폴더 고르기(원본 폴더면 경고하고 다시 고르게 함 —
  validate_out_dir) -> 실행마다 새 SequenceExportWorker(`self.seq_export_worker` — RUNNING_JOB_ATTRS가 창 닫기·업데이트 가드로 잡음)와
  비모달 진행 창(SequenceExportDialog — `self.seq_export_dialog`, 닫아도 작업은 계속). 취소는 stop() 뒤 한도 안에서만 wait() (GUI를 오래 막지 않음, 한도를
  넘으면 '취소하는 중'으로 두고 끝나는 걸 조금씩 봄). 워커는 취소하면 finished·error를 내지 않으므로 취소 뒤에 늦게 온 신호(아주 작은 틈의
  레이스)와 지난 실행의 신호는 무시 — 슬롯은 워커를 함께 받아 지금 실행의 것인지 봄.

`ThumbnailWorker`·`SequenceExportWorker`·`ImageSequenceCapture`는 이 모듈의 전역 이름으로 찾음 — 시험이 바꿔치기하려면 이 모듈의
이름(`sidebar_sequences.ThumbnailWorker` 등)을 바꿔야 닿음.
"""

import functools
import os
import traceback

import cv2
from PyQt5.QtCore import QItemSelectionModel, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from yesoncheck import paths, sequence_source, thumbnails, video_list
from yesoncheck.sequence_export_worker import SequenceExportWorker, validate_out_dir
from yesoncheck.sequence_source import ImageSequenceCapture
from yesoncheck.sidebar_items import THUMBNAIL_CONTEXT_ROLE, THUMBNAIL_MAKE_FAILED, THUMBNAIL_VIDEO_PROBLEM
from yesoncheck.thumbnail_workers import SeqThumbnailLoaderWorker, ThumbnailWorker
from yesoncheck.worker_lifecycle import release_worker

SEQ_FOLLOWUP_MS = 300  # Mov 탭이 썸네일을 만드는 중에 시작한 Seq 썸네일 읽기를, 만들기가 끝났는지 이 간격으로 보며 기다림
SEQ_EXPORT_TITLE = "시퀀스 MOV 만들기"
SEQ_EXPORT_PROGRESS_MS = 50  # 프레임마다 오는 진행 신호를 막대에는 이 간격으로 모아 반영 (마지막 값은 반드시 반영)
SEQ_EXPORT_CANCEL_WAIT_MS = 5000  # 취소 단추: stop() 뒤 GUI 스레드가 워커가 끝나길 기다리는 최대 시간 (ffmpeg를 끝내고 부분 출력을 지우는 시간)
SEQ_EXPORT_CANCEL_POLL_MS = 200  # 그 안에 끝나지 않으면 이 간격으로 끝났는지만 봄 (기다리며 막지 않음)
SEQ_EXPORT_LOG_PREFIX = "[시퀀스 MOV]"


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


class SequenceExportDialog(QDialog):
    """시퀀스 -> mov 일괄 내보내기의 비모달 진행 창 (보기만 — 워커와 잇는 일은 SidebarSequencesMixin이 함).

    위에서부터: 저장 위치, `n/m 항목`, 지금 항목 이름, 프레임 진행 막대(항목 합산 — 워커의 progress 그대로), 상태, 로그, 취소·닫기 단추.
    state: running(만드는 중) -> finished(완료) / failed(실패 — 요약이 로그에 남음) / cancelling(취소하는 중) -> cancelled(취소됨).
    취소 단추는 cancel_requested 신호만 내고 바로 꺼짐 (연결은 부르는 쪽). 창을 닫아도(X·Esc·닫기) 작업은 계속됨 — 닫기는 창을 숨길 뿐이고
    (취소가 아님 — 앱 종료의 모든 창 닫기를 막지도 않음), 다시 보려면 'MOV 만들기'를 한 번 더 고르면 되며(이미 만드는 중이라고 알리며 이 창을
    앞으로 가져옴) 끝나거나 실패하면 창이 저절로 다시 나타남. 진행 막대는 프레임마다 오는 신호를
    SEQ_EXPORT_PROGRESS_MS 간격으로 모아 반영하고 flush_progress()가 마지막 값을 바로 반영 (끝·취소·실패는 늘 flush한 뒤 상태를 바꿈).
    """

    cancel_requested = pyqtSignal()

    def __init__(self, parent, item_count, out_dir):
        super().__init__(parent)
        self.setWindowTitle(SEQ_EXPORT_TITLE)
        self.setWindowModality(Qt.NonModal)
        self.resize(560, 380)
        self.item_count = item_count
        self.state = "running"
        self._pending_frames = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(SEQ_EXPORT_PROGRESS_MS)
        self._flush_timer.timeout.connect(self.flush_progress)

        layout = QVBoxLayout(self)
        self.out_label = QLabel(f"저장 위치: {out_dir}")
        self.out_label.setWordWrap(True)
        layout.addWidget(self.out_label)
        self.items_label = QLabel(f"0/{item_count} 항목")
        layout.addWidget(self.items_label)
        self.current_label = QLabel("")
        layout.addWidget(self.current_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)  # 첫 진행 신호가 오기 전에는 '0 / 1'이 보이지 않게
        layout.addWidget(self.progress_bar)
        self.state_label = QLabel("")
        layout.addWidget(self.state_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        buttons.addWidget(self.cancel_button)
        self.close_button = QPushButton("닫기")  # 창만 닫음 (작업은 그대로)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._show_state("만드는 중…")
        self.add_log(f"{item_count}개 시퀀스를 mov로 만듭니다: {out_dir}")
        self.add_log("창을 닫아도 작업은 계속됩니다 (멈추려면 취소).")

    def _show_state(self, text, bold_red=False):
        self.state_label.setText(text)
        self.state_label.setStyleSheet("font-weight: bold; color: #d9534f;" if bold_red else "font-weight: bold;")
        self.cancel_button.setEnabled(self.state == "running")

    def _on_cancel_clicked(self):
        self.cancel_button.setEnabled(False)  # 두 번 눌러도 한 번만
        self.cancel_requested.emit()

    def add_log(self, text):
        self.log.appendPlainText(text)

    def set_item(self, index, base):
        """index번째(0부터) 항목을 시작함."""
        self.items_label.setText(f"{index + 1}/{self.item_count} 항목")
        self.current_label.setText(f"지금: {base}")
        self.add_log(f"[{index + 1}/{self.item_count}] {base}")

    def set_frames(self, done, total):
        """항목 합산 프레임 진행: 막대에는 SEQ_EXPORT_PROGRESS_MS마다 모아서 반영."""
        self._pending_frames = (done, total)
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush_progress(self):
        self._flush_timer.stop()
        if self._pending_frames is None:
            return
        done, total = self._pending_frames
        self._pending_frames = None
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat("%v / %m 프레임")
        self.progress_bar.setTextVisible(True)

    def _end(self, state, text, log_text, bold_red=False):
        self.flush_progress()
        self.state = state
        self._show_state(text, bold_red=bold_red)
        self.add_log(log_text)

    def set_finished(self, message):
        self.items_label.setText(f"{self.item_count}/{self.item_count} 항목")
        self.current_label.setText("")
        self._end("finished", "완료", message)

    def set_failed(self, summary):
        """실패 요약(워커의 error 글)을 로그에 그대로 — 창은 닫지 않음."""
        self._end("failed", "실패 — 아래 내용을 확인하세요", f"오류:\n{summary}", bold_red=True)

    def set_cancelling(self):
        self.state = "cancelling"
        self._show_state("취소하는 중…")
        self.add_log("취소하는 중… (ffmpeg를 끝내고 만들던 파일을 지웁니다)")

    def set_cancelled(self, failures):
        """취소됨: 취소 전에 이미 실패한 항목이 있었으면 그 이유도 보임 (워커는 취소하면 오류 신호를 내지 않음)."""
        lines = ["취소됨 — 만들던 파일은 지웠습니다. 이미 만든 mov는 그대로 있습니다."]
        if failures:
            lines.append(f"취소 전에 실패한 항목 {len(failures)}개:")
            lines += [f"[{base}] {reason}" for base, reason in failures]
        self._end("cancelled", "취소됨", "\n".join(lines))


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

    def _set_seq_items(self, seqs, source_contexts=None):
        """Seq 목록을 seqs(SeqInfo 목록)로 바꿈. 같으면 목록을 건드리지 않음 (깜빡임 없음). 바뀌면 선택·현재 항목은 같은 시퀀스
        (폴더·이름)에 그대로 (스크롤 위치는 항목을 한 번에 다시 넣으므로 Qt가 그대로 둠 — 시험이 지킴).

        새 시퀀스의 썸네일 자리: 이미 있던 시퀀스는 그 항목의 자리 그대로, source_contexts({_seq_key: ThumbnailContext} — 다시 읽기에서
        새 시퀀스가 들어온 곳이 처음 불러올 때 기억한 자리, Mov 항목이 쓰는 것과 같음)에 있으면 그것, 아니면 지금 상태의 자리."""
        seqs = list(seqs)
        if seqs == self._current_seq_items():
            return
        widget = self.seq_sidebar
        selected = {item.data(Qt.UserRole).identity for item in widget.selectedItems()}
        current = widget.currentItem()
        current_identity = current.data(Qt.UserRole).identity if current is not None else None
        # 이미 있던 시퀀스는 그 항목의 썸네일 자리 그대로, 새 시퀀스는 들어온 곳이 기억한 자리 또는 지금의 자리 (Mov 항목과 같은 규칙 — 재검토 L1)
        contexts = dict(source_contexts or {})
        contexts.update({_seq_key(widget.item(i).data(Qt.UserRole)): widget.item(i).data(THUMBNAIL_CONTEXT_ROLE)
                         for i in range(widget.count())})
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
        source_contexts = {}  # 새로 읽은 시퀀스 -> 그것이 들어온 곳이 기억한 썸네일 자리 (Mov 항목이 새 영상에 쓰는 self._sidebar_sources와 같음)
        for source, result in read.results.items():
            if isinstance(result, video_list.ScanResult):
                fresh.extend(result.sequences)
                recorded = self._sidebar_sources.get(source)  # 기억하지 않은 곳(합성한 읽기)은 지금 상태의 자리
                if recorded is not None:
                    for seq in result.sequences:
                        source_contexts.setdefault(_seq_key(seq), recorded)
                kept.extend(seq for seq in current
                            if any(video_list.is_under(seq.dir, folder) for folder, _error in result.unreadable))
            elif result is None:
                kept.extend(seq for seq in current if video_list.is_under(seq.dir, source.folder))
        self._set_seq_items(_merged(fresh, kept), source_contexts)

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

    # ---------------------------------------------------------------- 오른쪽 클릭 메뉴·정보

    def _selected_seq_items(self):
        """고른 Seq 항목들 (목록 순서 — 누른 순서가 아님). 고른 것이 없으면 현재 항목 하나, 그것도 없으면 빈 목록."""
        widget = self.seq_sidebar
        items = [widget.item(i) for i in range(widget.count()) if widget.item(i).isSelected()]
        if not items and widget.currentItem() is not None:
            items = [widget.currentItem()]
        return items

    def show_seq_context_menu(self, pos):
        """Seq 목록의 오른쪽 클릭 메뉴 (항목 위에서만): 열기(A/B) / 선택한 시퀀스로 MOV 만들기 / 썸네일 다시 만들기 / 정보 보기.
        mov 전용 동작(합치기·OCR류·파일 복사)은 넣지 않음. 선택 밖의 항목에서 열었으면 그 항목만 선택."""
        item = self.seq_sidebar.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.seq_sidebar.clearSelection()
            item.setSelected(True)
        identity = item.data(Qt.UserRole).identity
        menu = QMenu(self.seq_sidebar)
        menu.addAction("비디오 A로 열기").triggered.connect(lambda: self.open_file('A', identity))
        menu.addAction("비디오 B로 열기").triggered.connect(lambda: self.open_file('B', identity))
        menu.addSeparator()
        menu.addAction("선택한 시퀀스로 MOV 만들기…").triggered.connect(lambda: self.export_selected_sequences())
        menu.addSeparator()
        menu.addAction("썸네일 다시 만들기").triggered.connect(lambda: self.regenerate_seq_thumbnails(self._selected_seq_items()))
        menu.addSeparator()
        menu.addAction("정보 보기").triggered.connect(lambda: self.show_seq_info(item))
        # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (Mov 목록 메뉴와 같음 — 항목이 바뀌지 않게)
        with self._hold_sidebar_refresh():
            menu.exec_(self.seq_sidebar.viewport().mapToGlobal(pos))

    def show_seq_info(self, item):
        """'정보 보기': 범위·개수·빠짐은 목록의 값, 프레임 속도·해상도는 시퀀스를 잠깐 열어 읽음 (바로 놓음 — 첫 프레임을 디코드하므로
        GUI 스레드에서 한 번 디스크를 읽음). 읽지 못하면 이유를 스택 트레이스째 창과 로그에 (아는 값은 그대로 보임)."""
        seq = item.data(Qt.UserRole)
        width = height = 0
        fps = 0.0
        movie = None
        details = ""
        problem = None
        try:
            cap = ImageSequenceCapture(seq.identity)
            try:
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                else:
                    problem = "폴더에서 이 시퀀스를 찾지 못했습니다 (프레임이 없어졌거나 2장 미만)"
            finally:
                cap.release()
            movie = sequence_source.paired_movies(seq.dir, {seq.base})[seq.base]
        except (OSError, ValueError, cv2.error) as exc:
            problem = f"{type(exc).__name__}: {exc}"
            details = traceback.format_exc()
            traceback.print_exc()
        missing = f"{seq.missing}프레임" if seq.missing > 0 else "없음"
        lines = [
            f"이름: {seq.base}",
            f"폴더: {seq.dir}",
            f"범위: {seq.first:0{seq.pad}d}–{seq.last:0{seq.pad}d}",
            f"개수: {seq.count}프레임",
            f"빠짐: {missing}",
            f"형식: {seq.ext.upper()} ({seq.pad}자리 번호)",
        ]
        if problem is None:
            source = f"짝 영상 {os.path.basename(movie)}" if movie else "짝 영상 없음 — 기본값"
            lines += [f"프레임 속도: {fps:.2f} fps ({source})", f"해상도: {width} x {height}"]
        else:
            lines.append(f"프레임 속도·해상도: 읽지 못했습니다 — {problem}")
        box = QMessageBox(self)
        box.setWindowTitle("시퀀스 정보")
        box.setIcon(QMessageBox.Information if problem is None else QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText("\n".join(lines))
        if details:
            box.setDetailedText(details)
        box.exec_()

    # ---------------------------------------------------------------- 시퀀스 -> mov 일괄 내보내기

    def export_selected_sequences(self):
        """고른 시퀀스들을 mov로: 출력 폴더 고르기(원본 폴더면 거부) -> 새 워커 + 비모달 진행 창. 이미 만드는 중이면 그 창을 앞으로."""
        worker = self.seq_export_worker
        if worker is not None and worker.isRunning():
            QMessageBox.information(self, SEQ_EXPORT_TITLE, "이미 시퀀스 MOV를 만드는 중입니다. 끝나거나 취소한 뒤에 다시 하세요.")
            dialog = self.seq_export_dialog
            if dialog is not None:
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            return
        seqs = [item.data(Qt.UserRole) for item in self._selected_seq_items()]
        if not seqs:
            QMessageBox.information(self, SEQ_EXPORT_TITLE, "MOV로 만들 시퀀스를 Seq 목록에서 고르세요.")
            return
        ffmpeg = self.require_ffmpeg()  # 없으면 안내 창이 이미 뜸
        if ffmpeg is None:
            return
        out_dir = self._ask_seq_export_dir(seqs)
        if out_dir is None:
            return
        self._start_seq_export(seqs, out_dir, ffmpeg)

    def _ask_seq_export_dir(self, seqs):
        """출력 폴더를 고르게 함 → 경로, 고르지 않고 닫으면 None. 원본 폴더(validate_out_dir가 거부)면 경고하고 다시 고르게 함."""
        start = ""
        while True:
            chosen = QFileDialog.getExistingDirectory(self, "MOV를 저장할 폴더 선택", start)
            if not chosen:
                return None
            out_dir = paths.normalize_native(chosen)
            reason = validate_out_dir(seqs, out_dir)
            if reason is None:
                return out_dir
            QMessageBox.warning(self, "원본 폴더는 고를 수 없습니다", reason)
            start = os.path.dirname(os.path.normpath(out_dir))

    def _start_seq_export(self, seqs, out_dir, ffmpeg):
        """실행마다 새 워커·새 창 (멈춘 워커는 다시 쓸 수 없음). 슬롯은 워커를 함께 받아 지금 실행의 신호인지 봄."""
        old = self.seq_export_dialog
        if old is not None:  # 지난 실행의 창 (끝난 뒤에도 보이게 둔 것)
            old.hide()
            old.deleteLater()
        old_worker = self.seq_export_worker
        if old_worker is not None:  # 끝난 지난 실행의 워커 (export_selected_sequences가 도는 워커는 막음): 시그널 연결과 함께 놓음
            old_worker.deleteLater()
        worker = SequenceExportWorker(seqs, out_dir, ffmpeg)
        dialog = SequenceExportDialog(self, len(seqs), out_dir)
        dialog.cancel_requested.connect(functools.partial(self.cancel_seq_export, worker))
        worker.item_started.connect(functools.partial(self._on_seq_export_item_started, worker))
        worker.progress.connect(functools.partial(self._on_seq_export_progress, worker))
        worker.finished.connect(functools.partial(self._on_seq_export_finished, worker))
        worker.error.connect(functools.partial(self._on_seq_export_error, worker))
        self.seq_export_worker = worker
        self.seq_export_dialog = dialog
        dialog.show()
        worker.start()

    def _seq_export_is_live(self, worker):
        """worker가 지금 실행의 것이고 취소하지 않았는지 — 지난 실행의 신호와 취소 뒤 늦게 온 신호는 무시."""
        return worker is self.seq_export_worker and not worker.cancelled

    def _on_seq_export_item_started(self, worker, index, base):
        if self._seq_export_is_live(worker):
            self.seq_export_dialog.set_item(index, base)

    def _on_seq_export_progress(self, worker, done, total):
        if self._seq_export_is_live(worker):
            self.seq_export_dialog.set_frames(done, total)

    def _on_seq_export_finished(self, worker):
        if self._seq_export_is_live(worker):
            dialog = self.seq_export_dialog
            dialog.set_finished(f"완료: {len(worker.items)}개 시퀀스를 만들었습니다 — {worker.out_dir}")
            dialog.show()  # 닫아 둔 창이면 다시 나타나 끝났음을 알림

    def _on_seq_export_error(self, worker, text):
        """실패 요약: 진행 창에 그대로 남기고(닫지 않음) 오류 창도 띄움 — 스택 트레이스가 든 요약이므로 콘솔에도."""
        if not self._seq_export_is_live(worker):
            return
        print(f"{SEQ_EXPORT_LOG_PREFIX} 실패:\n{text}", flush=True)
        self.seq_export_dialog.set_failed(text)
        self.seq_export_dialog.show()  # 닫아 둔 창이면 다시 나타남 (오류 창을 닫은 뒤에도 요약이 읽히게)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("시퀀스 MOV 만들기 실패")
        box.setText(f"시퀀스 MOV 만들기가 실패했습니다: {text.partition(chr(10))[0]}")  # 첫 줄: 무엇이 틀렸는지
        box.setDetailedText(text)  # 항목별 이유 전체
        box.exec_()

    def cancel_seq_export(self, worker):
        """진행 창의 취소 단추: stop()으로 ffmpeg를 끝내고 만들던 파일을 지우게 한 뒤, 끝나길 SEQ_EXPORT_CANCEL_WAIT_MS까지만 기다림.
        그 안에 끝나지 않으면(느린 NAS의 파일 지우기·ffprobe) GUI를 막지 않고 '취소하는 중'으로 두며 끝났는지만 조금씩 봄."""
        dialog = self.seq_export_dialog
        if worker is not self.seq_export_worker or dialog.state != "running":
            return
        dialog.set_cancelling()
        worker.stop()
        if worker.wait(SEQ_EXPORT_CANCEL_WAIT_MS):
            dialog.set_cancelled(list(worker.failures))
            return
        print(f"{SEQ_EXPORT_LOG_PREFIX} 취소가 {SEQ_EXPORT_CANCEL_WAIT_MS / 1000:g}초 안에 끝나지 않음 — 끝날 때까지 기다림", flush=True)
        timer = QTimer(dialog)  # 창이 사라지면 함께 사라짐 (닫힌 창을 뒤늦게 건드리지 않게)
        timer.setInterval(SEQ_EXPORT_CANCEL_POLL_MS)
        timer.timeout.connect(functools.partial(self._poll_seq_export_cancel, worker, dialog, timer))
        timer.start()

    def _poll_seq_export_cancel(self, worker, dialog, timer):
        if worker.isRunning():
            return
        timer.stop()
        timer.deleteLater()
        dialog.set_cancelled(list(worker.failures))
