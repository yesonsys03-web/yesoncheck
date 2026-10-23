"""사이드바 Seq 탭 믹스인 (SidebarSequencesMixin): 이미지 시퀀스 목록(self.seq_sidebar)과 Mov·Seq 탭 전환.

- 목록 채우기: 영상 목록을 만드는 읽기(video_list.ScanResult)가 같은 폴더 목록에서 함께 찾은 시퀀스(`ScanResult.sequences`)를
  그 읽기가 끝날 때마다 받아 넣음 — 폴더를 더 읽지 않음. 첫 불러오기(`_load_job_list`·`load_videos_from_folder`)는 `_set_seq_items`,
  끌어다 놓은 폴더는 `_add_seq_items`(목록에 덧붙임), 목록 다시 읽기(`_apply_sidebar_read`)는 `_apply_seq_read`.
  Mov 목록을 비우면(`self.sidebar.clear()` — job을 바꿈·폴더를 불러옴·읽지 못함) Seq 목록도 함께 비움(`_clear_seq_items`).
- 항목: 라벨 "베이스 (처음–끝, N프레임)"(+ 빠진 프레임이 있으면 ", 빠짐 N"), `Qt.UserRole`에 `SeqInfo`(프레임 파일 이름은 들지 않음),
  툴팁은 사람이 읽는 정보. Mov 목록 코드는 `item.toolTip()`을 경로로 읽지만 이 목록은 별도 위젯이라 그 관례가 닿지 않음.
- 누르기: `on_seq_item_clicked` → 시퀀스를 A로 엶 (`open_file('A', seq.identity)`, Mov 목록 누르기와 같은 규칙).
- 탭 전환(`_on_sidebar_tab_changed`)은 페이지 교체뿐 — 디스크를 읽지 않음. Seq 탭에서는 'Play Selected' 단추를 끔 (선택 재생은
  Mov 경로 전제).

상태(`self.sidebar_tabs`·`self.seq_sidebar`·`self._folder_sequences`)는 예전처럼 VideoPlayerBase가 만들고(위젯은 initUI), 이 믹스인은
`self.`로 씀. PlayerSidebarMixin의 부모 클래스로 붙음. 이 모듈은 player_sidebar·player_base를 모듈 수준에서 import하지 않음 (순환).
"""

from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtWidgets import QListWidgetItem

from yesoncheck import paths, video_list


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

    def _new_seq_item(self, seq):
        item = QListWidgetItem(seq_label(seq))
        item.setData(Qt.UserRole, seq)
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
        widget.setUpdatesEnabled(False)
        try:
            widget.clear()
            for seq in seqs:
                widget.addItem(self._new_seq_item(seq))
            for i in range(widget.count()):
                item = widget.item(i)
                identity = item.data(Qt.UserRole).identity
                if identity == current_identity:
                    widget.setCurrentItem(item, QItemSelectionModel.NoUpdate)
                item.setSelected(identity in selected)
        finally:
            widget.setUpdatesEnabled(True)

    def _add_seq_items(self, seqs):
        """Seq 목록에 seqs를 덧붙임 (끌어다 놓은 폴더). 이미 있는 시퀀스는 새로 읽은 것으로 바꿈."""
        self._set_seq_items(_merged(seqs, self._current_seq_items()))

    def _clear_seq_items(self):
        """Mov 목록을 비움(clear → 모델 초기화)과 함께 Seq 목록도 비움: 지난 job·폴더의 시퀀스가 남지 않게 (새 목록을 넣는 쪽이 다시 채움)."""
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
        """Mov·Seq 탭 전환 — 페이지가 바뀔 뿐 디스크를 읽지 않음. Seq 탭에서는 'Play Selected'를 끔 (선택 재생은 영상 경로 전제)."""
        self.playSelectedButton.setEnabled(self.sidebar_tabs.widget(index) is not self.seq_sidebar)
