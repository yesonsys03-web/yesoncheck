"""All 탭 믹스인 (SidebarAllMixin): Mov·Seq 목록을 한 목록(self.all_sidebar)에 이름 자연 정렬로 섞어 보여 줌.

항목은 두 목록 항목의 복제(clone) — 데이터 역할(경로 툴팁·SeqInfo·썸네일 자리)을 그대로 가지며 `ALL_KIND_ROLE`로
종류("mov"/"seq")를 적음. All 목록은 늘 파생이고 원본(Mov·Seq 목록)에서만 고침: 보이는 동안 원본 모델이 바뀌면
(넣기·빼기·비우기·아이콘·색 — 선택 재생 강조도 이 길로 따라옴) 미뤄서 통째로 다시 만들므로 두 벌 상태가 어긋나지 않음.
시퀀스 항목 글자는 하늘색(`ALL_SEQ_FG`, 테마별 — 선택 강조 주황·테마 기본색과 겹치지 않게, 사용자 선택).
선택 재생은 `sidebar_playlist._playlist_selection`이 All 탭에서 mov만 고름 (시퀀스 연속 재생은 메모리 한계로 하지
않음 — 사용자 결정). 우클릭 메뉴는 맨 위 'Mov만 모두 선택' + 누른 항목 종류의 기존 메뉴(선택을 원본 목록에 비춘 뒤
그 목록의 메뉴 동작을 그대로 씀 — 동작이 Mov·Seq 탭과 달라지지 않음).
목록 아래 개수 줄(self.sidebar_count_label)도 Mov·Seq 목록에서 파생된 보기라 여기서 갱신 — 원본 목록에서 셈(글은 sidebar_counts).

player_sidebar를 모듈 수준에서 import하지 말 것 (순환 — 다른 사이드바 믹스인과 같음).
"""

import os

from PyQt5.QtCore import QItemSelection, QItemSelectionModel, Qt, QTimer
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import QMenu

from yesoncheck import paths, sidebar_sort
from yesoncheck.file_names import natural_key
from yesoncheck.sidebar_counts import count_text
from yesoncheck.sidebar_items import ALL_KIND_ROLE
from yesoncheck.sidebar_take_colors import count_line_html, take_color

# All 탭 시퀀스 항목 글자 색 — 테마별 하늘색 (주황 선택 강조·흰/검 기본색 어느 쪽과도 구분)
ALL_SEQ_FG = {"dark": "#5bc8ff", "light": "#0b6ea8"}


def _all_item_key(item):
    """다시 만들 때 선택·현재 항목을 이어 줄 열쇠: mov는 경로(툴팁), 시퀀스는 가상 경로."""
    if item.data(ALL_KIND_ROLE) == "seq":
        return ("seq", item.data(Qt.UserRole).identity)
    return ("mov", item.toolTip())


def _all_sort_key(item):
    """이름 순서(natural_key): mov는 파일 이름, 시퀀스는 base — 짝(mov·시퀀스)이 이웃하게."""
    if item.data(ALL_KIND_ROLE) == "seq":
        return natural_key(item.data(Qt.UserRole).base)
    return natural_key(item.text())


def _all_stem(item):
    """정렬 묶음을 읽을 이름(확장자 뺀): mov는 파일 이름, 시퀀스는 base."""
    if item.data(ALL_KIND_ROLE) == "seq":
        return item.data(Qt.UserRole).base
    return os.path.splitext(item.text())[0]


def _select_rows(widget, wanted):
    """목록에서 wanted(항목 → bool)인 줄만 선택 — 한 번의 select()로 (항목마다 setSelected는 큰 목록에서 제곱으로 느림)."""
    selection = QItemSelection()
    model = widget.model()
    for i in range(widget.count()):
        if wanted(widget.item(i)):
            index = model.index(i, 0)
            selection.select(index, index)
    widget.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)


class SidebarAllMixin:
    """VideoPlayer의 All 목록(self.all_sidebar) — 목록 만들기·누르기·메뉴·Mov만 모두 선택."""

    # ---------------------------------------------------------------- 목록 만들기

    def _init_all_tab_hooks(self):
        """initUI가 all_sidebar·탭을 만든 뒤 한 번: Mov·Seq 모델의 변화 → 미룬 다시 만들기 (All 탭이 보일 때만)."""
        self._all_rebuild_timer = QTimer(self)
        self._all_rebuild_timer.setSingleShot(True)
        self._all_rebuild_timer.setInterval(80)
        self._all_rebuild_timer.timeout.connect(self._rebuild_all_list)
        for model in (self.sidebar.model(), self.seq_sidebar.model()):
            model.rowsInserted.connect(self._schedule_all_rebuild)
            model.rowsRemoved.connect(self._schedule_all_rebuild)
            model.modelReset.connect(self._schedule_all_rebuild)
            model.dataChanged.connect(self._schedule_all_rebuild)
        # 개수 줄: 항목을 하나씩 넣을 때마다 세지 않게 미뤄서 한 번 (0ms — 이번 이벤트 처리가 끝나면 바로), 숨은 탭의 변화도 셈
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(0)
        self._count_timer.timeout.connect(self._update_sidebar_count)
        for model in (self.sidebar.model(), self.seq_sidebar.model()):
            model.rowsInserted.connect(self._schedule_sidebar_count)
            model.rowsRemoved.connect(self._schedule_sidebar_count)
            model.modelReset.connect(self._schedule_sidebar_count)
        self.sidebar_tabs.currentChanged.connect(self._schedule_sidebar_count)
        self._update_sidebar_count()
        # 테이크 색: Mov 목록에 항목이 들어올 때만(탭을 바꾸거나 Seq 목록이 바뀔 때는 아님) 미뤄서 한 번 — 항목의 경로(UserRole)는
        # 넣은 뒤에 붙으므로 이번 이벤트 처리가 끝난 뒤에 칠함
        self._take_color_timer = QTimer(self)
        self._take_color_timer.setSingleShot(True)
        self._take_color_timer.setInterval(0)
        self._take_color_timer.timeout.connect(self._apply_take_colors)
        self.sidebar.model().rowsInserted.connect(self._schedule_take_colors)
        self.sidebar.model().modelReset.connect(self._schedule_take_colors)

    def _schedule_sidebar_count(self, *_args):
        """신호의 인자는 버림 (QTimer.start(int)에 바로 이으면 탭 번호가 밀리초로 들어감)."""
        self._count_timer.start()

    def _update_sidebar_count(self):
        """목록 아래 개수 줄을 지금 보는 탭의 개수로 — 원본 Mov·Seq 목록에서 셈 (All 목록은 미뤄서 다시 만들어지므로 세지 않음)."""
        tabs = {id(self.sidebar): "mov", id(self.seq_sidebar): "seq", id(self.all_sidebar): "all"}
        tab = tabs[id(self.sidebar_tabs.currentWidget())]  # 모르는 탭은 All로 치지 않음 (탭을 더하면 여기서 KeyError)
        movies = [self.sidebar.item(i).data(Qt.UserRole) for i in range(self.sidebar.count())]
        sequences = [(seq.base, seq.ext) for seq in (self.seq_sidebar.item(i).data(Qt.UserRole)
                                                       for i in range(self.seq_sidebar.count()))]
        line = count_text(tab, movies, sequences)
        # 버전·테이크 토막을 목록과 같은 색으로(줄이 곧 범례) — 목록에 테이크 색이 없는 Seq 탭은 칠하지 않음, 칠할 토막이 없으면 평문 그대로
        colored = None if tab == "seq" else count_line_html(line, self.current_theme)
        self.sidebar_count_label.setTextFormat(Qt.PlainText if colored is None else Qt.RichText)
        self.sidebar_count_label.setText(line if colored is None else colored)

    # ---------------------------------------------------------------- 테이크·버전 색 (Mov 항목 — 규칙은 sidebar_take_colors)

    def _paint_mov_item(self, item):
        """Mov 항목 하나를 제 글자색으로: 테이크·버전 2번부터는 그 색, 아니면 따로 칠한 색을 지움(테마 시트의 기본색).
        이미 그 색이면 건드리지 않음(모델 신호 없음 — All 목록을 다시 만들지 않음)."""
        stem = os.path.splitext(os.path.basename(item.data(Qt.UserRole)))[0]
        color = take_color(stem, self.current_theme)
        brush = None if color is None else QBrush(QColor(color))
        if item.data(Qt.ForegroundRole) != brush:
            item.setData(Qt.ForegroundRole, brush)

    def _schedule_take_colors(self, *_args):
        """신호의 인자는 버림 (QTimer.start(int)에 바로 이으면 줄 번호가 밀리초로 들어감)."""
        self._take_color_timer.start()

    def _apply_take_colors(self, repaint=False):
        """Mov 목록 항목을 테이크 색으로 칠함. 목록에 항목이 들어온 뒤(_take_color_timer — 0ms 미룸)에는 **아직 칠한 적 없는 항목만**(따로 칠한 글자색이
        없는 것 — 새 항목은 늘 그렇게 들어옴): 이미 칠한 항목(테이크 색·선택 재생 강조)은 목록을 다시 읽어도 그대로 둠.
        repaint=True(테마를 바꾼 뒤 — 색이 테마마다 다름)는 전부 다시, 선택 재생이 빨갛게 한 줄(_playlist_highlighted_path)만 빼고.
        All 목록의 mov 사본은 원본을 복제하므로 따라옴(원본의 dataChanged → 다시 만들기), 시퀀스는 하늘색 그대로."""
        playing = self._playlist_highlighted_path  # 선택 재생이 빨갛게 한 줄 (SidebarPlaylistMixin)
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if playing is not None and paths.same_path(item.toolTip(), playing):
                continue
            if repaint or item.data(Qt.ForegroundRole) is None:
                self._paint_mov_item(item)
        if repaint:
            self._update_sidebar_count()  # 개수 줄의 색도 테마마다 다름

    def _schedule_all_rebuild(self, *_args):
        """All 탭이 보이는 동안만 미뤄서 다시 만듦 (숨은 동안의 변화는 탭을 열 때 한 번에)."""
        timer = getattr(self, "_all_rebuild_timer", None)
        if timer is None:  # 테마 적용 등이 initUI보다 먼저 부를 수 있음
            return
        if self.sidebar_tabs.currentWidget() is self.all_sidebar:
            timer.start()

    def _rebuild_all_list(self):
        """Mov·Seq 목록을 복제해 All 목록을 통째로 다시 만듦. 선택·현재 항목·스크롤 위치는 그대로 —
        현재 항목은 NoUpdate로 정함 (기본 SelectCurrent는 선택을 현재 항목 하나로 바꿔, 'Mov만 모두 선택' 뒤의
        다시 만들기가 선택을 시퀀스로 뒤집었음 — _set_seq_items와 같은 방법)."""
        widget = self.all_sidebar
        selected = {_all_item_key(item) for item in widget.selectedItems()}
        current = widget.currentItem()
        current_key = _all_item_key(current) if current is not None else None
        scroll = widget.verticalScrollBar().value()

        clones = []
        for i in range(self.sidebar.count()):
            clone = self.sidebar.item(i).clone()
            clone.setData(ALL_KIND_ROLE, "mov")
            clones.append(clone)
        seq_fg = QColor(ALL_SEQ_FG[self.current_theme])
        for i in range(self.seq_sidebar.count()):
            clone = self.seq_sidebar.item(i).clone()
            clone.setData(ALL_KIND_ROLE, "seq")
            clone.setForeground(seq_fg)
            clones.append(clone)
        mode = self.sidebar_sort_mode  # 정렬 기준(SidebarSortMixin) — 종류·버전이면 묶음끼리, 그 안에서 이름 순서 (이름이면 묶음이 하나 — 예전과 같음)
        timed = mode == sidebar_sort.TIME_MODE  # 시간이면 항목의 고친 시각(영상은 Mov 항목에서 복제해 온 값, 시퀀스는 첫 프레임 — SidebarSortMixin)
        clones.sort(key=lambda item: (sidebar_sort.group_key(_all_stem(item), mode, self._all_item_time(item) if timed else None),
                                      _all_sort_key(item)))

        widget.setUpdatesEnabled(False)
        try:
            widget.clear()
            for clone in clones:
                widget.addItem(clone)
            for i in range(widget.count()):
                item = widget.item(i)
                if _all_item_key(item) == current_key:
                    widget.setCurrentItem(item, QItemSelectionModel.NoUpdate)
            _select_rows(widget, lambda item: _all_item_key(item) in selected)
        finally:
            widget.setUpdatesEnabled(True)
        widget.verticalScrollBar().setValue(scroll)

    # ---------------------------------------------------------------- 누르기·선택

    def on_all_item_clicked(self, item):
        """All 항목을 누름: 종류대로 A에 엶 (선택 재생 중에는 무시 — Mov·Seq 탭과 같음)."""
        if self.is_playlist_playing:
            return
        if item.data(ALL_KIND_ROLE) == "seq":
            self.open_file('A', item.data(Qt.UserRole).identity)
        else:
            self.open_file('A', item.toolTip())

    def load_selected_all_item(self):
        """위아래 화살표로 고른 All 항목을 A에 엶 (Mov 목록의 load_selected_item_to_video_a와 같은 역할, 종류대로)."""
        item = self.all_sidebar.currentItem()
        if item is not None:
            self.on_all_item_clicked(item)

    def select_all_movs(self):
        """All 탭: mov 항목만 모두 선택 (시퀀스 선택은 풂) — 선택 재생으로 mov 전체를 이어서 재생할 때."""
        _select_rows(self.all_sidebar, lambda item: item.data(ALL_KIND_ROLE) == "mov")

    # ---------------------------------------------------------------- 우클릭 메뉴

    def _mov_row_for_path(self, path):
        """Mov 목록에서 이 경로의 줄 (없으면 None)."""
        for i in range(self.sidebar.count()):
            if paths.same_path(self.sidebar.item(i).toolTip(), path):
                return i
        return None

    def _seq_item_for_identity(self, identity):
        """Seq 목록에서 이 가상 경로의 첫 항목 (없으면 None)."""
        for i in range(self.seq_sidebar.count()):
            if self.seq_sidebar.item(i).data(Qt.UserRole).identity == identity:
                return self.seq_sidebar.item(i)
        return None

    def _mirror_all_selection_to_sources(self):
        """All 목록의 선택을 Mov·Seq 목록에 그대로 비춤 — 원본 목록의 선택을 읽는 메뉴 동작(파일 복사·MOV 만들기·
        썸네일 다시 만들기 등)이 All 탭의 선택대로 돌게. 메뉴가 닫히면 _restore_source_selections가 되돌림."""
        mov_keys = set()
        seq_identities = set()
        for item in self.all_sidebar.selectedItems():
            if item.data(ALL_KIND_ROLE) == "seq":
                seq_identities.add(item.data(Qt.UserRole).identity)
            else:
                mov_keys.add(paths.path_key(item.toolTip()))
        _select_rows(self.sidebar, lambda item: paths.path_key(item.toolTip()) in mov_keys)
        _select_rows(self.seq_sidebar, lambda item: item.data(Qt.UserRole).identity in seq_identities)

    def _snapshot_source_selections(self):
        """Mov·Seq 목록의 지금 선택 (줄 번호 — 메뉴가 떠 있는 동안 목록은 바뀌지 않음, _hold_sidebar_refresh)."""
        return ({i for i in range(self.sidebar.count()) if self.sidebar.item(i).isSelected()},
                {i for i in range(self.seq_sidebar.count()) if self.seq_sidebar.item(i).isSelected()})

    def _restore_source_selections(self, snapshot):
        """메뉴를 닫은 뒤 Mov·Seq 목록의 선택을 비추기 전으로 — All 탭의 메뉴가 다른 탭의 상태를 바꾸지 않게."""
        mov_rows, seq_rows = snapshot
        _select_rows(self.sidebar, lambda item: self.sidebar.row(item) in mov_rows)
        _select_rows(self.seq_sidebar, lambda item: self.seq_sidebar.row(item) in seq_rows)

    def show_all_context_menu(self, pos):
        """All 목록 오른쪽 클릭: 맨 위 'Mov만 모두 선택', 항목 위면 그 종류의 기존 메뉴(Mov/Seq 탭과 같은 동작 —
        선택을 원본 목록에 비춰 돌리고, 메뉴가 닫히면 원본 선택을 되돌림). 선택 밖의 항목에서 열었으면 그 항목만 선택
        (Seq 탭과 같음)."""
        # 미룬 다시 만들기가 밀려 있으면 먼저 돌림 — 낡은 목록으로 원본 항목을 못 찾아 메뉴가 조용히 빠지지 않게
        if self._all_rebuild_timer.isActive():
            self._all_rebuild_timer.stop()
            self._rebuild_all_list()
        item = self.all_sidebar.itemAt(pos)
        if item is not None and not item.isSelected():
            self.all_sidebar.clearSelection()
            item.setSelected(True)
        menu = QMenu(self.all_sidebar)
        menu.addAction("Mov만 모두 선택").triggered.connect(self.select_all_movs)
        snapshot = None
        if item is not None:
            snapshot = self._snapshot_source_selections()
            self._mirror_all_selection_to_sources()
            menu.addSeparator()
            if item.data(ALL_KIND_ROLE) == "seq":
                source_item = self._seq_item_for_identity(item.data(Qt.UserRole).identity)
                if source_item is not None:
                    self._build_seq_menu(menu, source_item)
            else:
                row = self._mov_row_for_path(item.toolTip())
                if row is not None:
                    self._build_sidebar_menu(menu, self.sidebar.model().index(row, 0))
            self._add_open_with_actions(menu, self._all_open_entries())  # All의 선택 그대로 — 비춘 선택이 아니라 (sidebar_open_with)
        # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (Mov·Seq 메뉴와 같음).
        # 고른 동작은 exec_ 안에서 동기로 돌므로 비춘 선택을 읽고, 닫힌 뒤 되돌려도 안전함
        with self._hold_sidebar_refresh():
            menu.exec_(self.all_sidebar.viewport().mapToGlobal(pos))
        if snapshot is not None:
            self._restore_source_selections(snapshot)
