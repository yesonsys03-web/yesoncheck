"""사이드바 정렬 믹스인 (SidebarSortMixin) — 탭 줄 오른쪽(All 탭 옆)의 정렬 단추와 Mov 목록의 줄 옮기기. 규칙은 sidebar_sort(Qt 없음).

단추 자리(사용자 지시 "정렬버튼을 All 탭 옆으로"): 탭 위젯의 자식으로 **탭 막대 바로 오른쪽에 직접 놓음**(_fit_sidebar_sort_button — 탭 위젯·탭
막대의 크기·자리가 바뀔 때마다). 해 본 것 둘은 버림: ① 탭 위젯의 모서리 위젯으로 두면 Qt가 줄의 오른쪽 끝에 붙여 넓은 사이드바에서 All 탭과 떨어지고
(실제 Mac 화면: 380px에서 75px 틈), 단추의 폭이 탭 위젯의 최소 폭에 더해져 사이드바를 좁히다 걸림 ② 모서리 위젯이 남는 폭을 다 바라게 하면 탭 위젯의
바라는 크기가 지금 크기를 따라가 창의 처음 크기 계산이 흔들림(test_window_resize). 직접 놓으면 탭 위젯의 바라는 크기·최소 크기는 그대로.
탭 막대는 왼쪽 정렬로(TAB_BAR_LEFT_STYLE — Mac의 기본은 가운데: 좁은 사이드바에서 All 탭 오른쪽에 자리가 없음; 그래서 Mac의 넓은 사이드바에서는 탭이
가운데가 아니라 왼쪽). 사이드바의 기본 폭(약 180px)에서는 탭 막대(155px) 옆에 20여 px뿐이라, 남은 폭에 들어가는 가장 긴 글을 씀
(`정렬: 이름 ▾` → `이름 ▾` → `↕`). 지금 기준은 툴팁 첫 줄에 늘 있음.

정렬 기준(self.sidebar_sort_mode — 이름·종류·버전)은 창이 떠 있는 동안 유지되고(job·폴더를 바꿔도), 세 탭에 함께 적용:
- **Mov 목록**(원본 — 다시 읽기·선택 재생·썸네일이 이 목록의 항목을 씀): 항목 객체는 그대로 두고 **줄만 옮김**(떼었다 다시 넣음 — clear()는 항목을 지우고
  모델을 초기화해 출처·Seq 목록까지 잊으므로 쓰지 않음). 썸네일 아이콘·테이크 색·썸네일 자리·고른 것·현재 항목이 그대로 따라옴.
- **Seq 목록**: _set_seq_items가 넣을 때 정렬(SidebarSequencesMixin) — 기준을 바꾸면 여기서 지금 목록을 다시 넣음.
- **All 목록**: 다시 만들 때 정렬(SidebarAllMixin._rebuild_all_list).

**이름(기본)에서는 아무것도 하지 않음** — 목록은 읽은 쪽(video_list)이 준 순서 그대로이고, 고르지 않으면 예전과 같음.

이름 순서를 잃지 않는 법: 이름이 아닌 기준으로 처음 바꿀 때 항목마다 그때의 줄 번호를 **기본 순위**(SIDEBAR_RANK_ROLE)로 적어 둠. 묶음 안의 순서와
'이름'으로 돌아갈 때의 순서가 이 순위. 정렬해 둔 동안:
- 목록 끝에 붙은 새 항목(끌어다 놓기·폴더 불러오기 — 순위 없음)은 지금까지의 순위 뒤에 차례로(이름 순서에서도 끝에 붙던 그대로), 0ms 뒤 정렬.
- 목록 다시 읽기(SidebarRefreshMixin._apply_sidebar_read)는 계획을 **기본 순위 순서로** 세우고(_sidebar_items_in_default_order), 바꿀 것이 있을 때만
  목록을 잠깐 기본 순서로 되돌려 계획을 넣은 뒤(_sidebar_default_order) 순위를 다시 매기고 정렬 — 새 영상이 이름 순서의 제자리에 들어가고, 계획 코드는
  정렬을 모름. 바뀐 것이 없으면 목록을 건드리지 않음.
- 목록을 쓰는 중(_sidebar_refresh_holds — 썸네일 반복·우클릭 메뉴가 줄 번호를 쥠)에는 줄을 옮기지 않고 끝난 뒤에(SORT_RETRY_MS마다 다시 봄).

**시간**(파일을 고친 시각 — 최근 것부터)만은 이름이 아니라 디스크를 읽음: 줄을 옮길 때 GUI 스레드에서 os.stat(_read_sidebar_times) — 사용자가 '시간'을 고를 때
(이미 시간이어도 — 다시 고르면 다시 읽음) 모든 영상을, 그 뒤 들어온 새 영상은 그것만. 저절로 도는 목록 다시 읽기에서는 다시 읽지 않음(앱을 오갈 때마다
모든 파일을 NAS에 묻지 않게 — 다시 렌더한 영상을 위로 올리려면 '시간'을 다시 고름). 이 Mac의 NFS에서 571개 0.21초·두 번째 0.01초(job 목록을 만들 때의
폴더 읽기보다 가벼움; Windows SMB는 안 잼). 읽지 못한 파일은 맨 뒤 + 기록 한 줄. 시퀀스는 첫 프레임 파일의 시각(_sidebar_seq_time — 한 번 읽어 기억).

player_sidebar를 모듈 수준에서 import하지 말 것 (순환 — 다른 사이드바 믹스인과 같음).
"""

import contextlib
import os
import time

from PyQt5.QtCore import QEvent, QItemSelectionModel, QObject, Qt, QTimer
from PyQt5.QtWidgets import QAbstractItemView, QMenu, QToolButton

from yesoncheck import error_window, sequence_source, sidebar_sort, video_list
from yesoncheck.sidebar_all import _select_rows
from yesoncheck.sidebar_items import ALL_KIND_ROLE, SIDEBAR_MTIME_ROLE, SIDEBAR_RANK_ROLE

SORT_LOG_PREFIX = "[정렬]"
# 단추 모양(sort_button_style) — 색을 정하지 않음: 글자색은 창의 테마 시트(QWidget 규칙)를 따르고 테두리는 두 테마 모두에서 보이는 중간 회색.
# (시트 없이 두면 밝은 테마에서 기본 스타일이 단추를 검게 칠함 — 화면 없는 그림으로 확인. 테마 시트에 규칙을 더하지 않아 두 시트는 그대로)
SORT_BUTTON_PAD = 5  # 단추 글의 좌우 여백(px)
SORT_BUTTON_GAP = 4  # All 탭과 단추 사이의 틈(px)
# 탭 막대를 왼쪽에 — Mac의 기본은 가운데라 좁은 사이드바에서 All 탭 오른쪽에 단추 놓을 자리(양쪽에 13px씩)가 없음. 왼쪽이면 탭 막대 옆의 남는 폭이 한곳에 모임
TAB_BAR_LEFT_STYLE = "QTabWidget::tab-bar { alignment: left; }"
SORT_BUTTON_COMPACT_PAD = 2  # 가장 짧은 글(↕)일 때 — 가장 좁은 사이드바(176px: 탭 막대 155px 옆에 21px)에 들어가게


def sort_button_style(compact=False):
    """단추의 시트 — compact: 가장 짧은 글(↕)일 때의 좁은 여백."""
    pad = SORT_BUTTON_COMPACT_PAD if compact else SORT_BUTTON_PAD
    return (
        f"QToolButton {{ border: 1px solid rgba(128, 128, 128, 150); border-radius: 4px; background: transparent; padding: 2px {pad}px; }}"
        "QToolButton:hover, QToolButton:pressed { border-color: rgba(128, 128, 128, 255); }"
        "QToolButton::menu-indicator { image: none; }"  # 기본 화살표는 글자와 겹침 — 글 끝의 ▾가 대신함
    )
SORT_RETRY_MS = 200  # 목록을 쓰는 중이라 미룬 정렬을 다시 볼 간격


def _item_stem(item):
    """Mov 항목의 이름(확장자 뺀) — 경로(툴팁)의 파일 이름, 경로 없이 넣은 항목은 보이는 글."""
    return os.path.splitext(os.path.basename(item.toolTip() or item.text()))[0]


class _ResizeWatcher(QObject):
    """지켜보는 위젯(탭 위젯·탭 막대)의 크기·자리가 바뀔 때마다 on_resize()를 부르는 이벤트 필터 (이벤트는 그대로 흘려보냄). PyQt5 가상 함수에서 예외가
    빠져나가면 프로세스가 끝나므로(qFatal) 본문을 감싸 처음 한 번만 크게 알리고 그 뒤로는 부르지 않음."""

    def __init__(self, on_resize, parent):
        super().__init__(parent)
        self._on_resize = on_resize
        self._failed = False

    def eventFilter(self, watched, event):
        try:
            if event.type() in (QEvent.Resize, QEvent.Move) and not self._failed:
                self._on_resize()
        except BaseException:
            self._failed = True
            error_window.report_from_handler(SORT_LOG_PREFIX, "정렬 단추를 탭 줄에 맞추다 실패했습니다 — 단추의 글·자리는 그대로 둡니다")
        return False


def _item_time(item):
    """Mov 항목에 적어 둔 고친 시각 (_read_sidebar_times — 없으면 None)."""
    return item.data(SIDEBAR_MTIME_ROLE)


class SidebarSortMixin:
    """VideoPlayer의 사이드바 정렬 — 단추(self.sidebar_sort_button)·기준 바꾸기·Mov 목록 줄 옮기기."""

    # ---------------------------------------------------------------- 단추

    def _init_sidebar_sort(self):
        """(initUI — 목록·탭을 만든 뒤) 정렬 단추를 탭 줄의 All 탭 바로 옆에 두고, 미룬 정렬 타이머를 만들어 Mov 목록에 항목이 들어오는 신호에 이음."""
        self.sidebar_tabs.setStyleSheet(TAB_BAR_LEFT_STYLE)
        button = QToolButton(self.sidebar_tabs)
        button.setPopupMode(QToolButton.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setFocusPolicy(Qt.NoFocus)  # 목록의 포커스(화살표·단축키)를 가져가지 않게
        button.setStyleSheet(sort_button_style())
        menu = QMenu(button)
        menu.setToolTipsVisible(True)
        self.sidebar_sort_actions = {}
        for mode in sidebar_sort.MODES:
            action = menu.addAction(sidebar_sort.LABELS[mode])
            action.setCheckable(True)
            action.setToolTip(sidebar_sort.TIPS[mode])
            action.triggered.connect(lambda checked, chosen=mode: self.set_sidebar_sort(chosen))
            self.sidebar_sort_actions[mode] = action
        button.setMenu(menu)
        self.sidebar_sort_button = button
        self._sidebar_sort_widths = {}  # (단추 글, 글꼴) → 그 글일 때 단추가 바라는 폭 (_sort_button_width)
        self._sidebar_sort_timer = QTimer(self)
        self._sidebar_sort_timer.setSingleShot(True)
        self._sidebar_sort_timer.timeout.connect(self._apply_sidebar_sort)
        self.sidebar.model().rowsInserted.connect(self._schedule_sidebar_sort)
        self._sidebar_sort_resize_watcher = _ResizeWatcher(self._fit_sidebar_sort_button, self.sidebar_tabs)  # 참조를 쥠 — Qt는 필터를 붙잡아 주지 않음
        self.sidebar_tabs.installEventFilter(self._sidebar_sort_resize_watcher)
        self.sidebar_tabs.tabBar().installEventFilter(self._sidebar_sort_resize_watcher)
        self._sync_sidebar_sort_button()

    def _sync_sidebar_sort_button(self):
        """단추의 글·툴팁·메뉴 체크를 지금 기준에 맞춤. 툴팁 첫 줄은 늘 긴 글(`정렬: 종류 ▾`) — 좁아서 단추에 `↕`만 보여도 기준을 알 수 있게."""
        self.sidebar_sort_button.setToolTip(f"{sidebar_sort.button_text(self.sidebar_sort_mode)}\n{sidebar_sort.BUTTON_TIP}")
        for mode, action in self.sidebar_sort_actions.items():
            action.setChecked(mode == self.sidebar_sort_mode)
        self._fit_sidebar_sort_button()

    def _fit_sidebar_sort_button(self):
        """단추를 탭 막대 바로 오른쪽(All 탭 옆 — SORT_BUTTON_GAP 틈)에 놓고, 글은 거기서 탭 줄 끝까지 남은 폭에 들어가는 가장 긴 것으로 — 들어가는
        것이 없으면 가장 짧은 것(그것도 모자라면 틈을 줄임). 폭은 어림하지 않고 그 글을 단추에 넣어 잼(_sort_button_width — 글꼴 폭으로 어림하면 1px
        어긋났음). 탭 위젯·탭 막대의 크기·자리가 바뀔 때마다(_ResizeWatcher)와 기준을 바꿀 때 부름 — 단추는 탭 위젯의 배치에 들어 있지 않아(직접 놓음)
        글·자리를 바꿔도 그 이벤트가 다시 오지 않고, 탭 위젯의 바라는 크기·최소 크기(사이드바·창의 크기 계산)도 그대로."""
        tabs, bar, button = self.sidebar_tabs, self.sidebar_tabs.tabBar(), self.sidebar_sort_button
        tabs_end = bar.x() + bar.width()
        texts = sidebar_sort.button_texts(self.sidebar_sort_mode)
        widths = [self._sort_button_width(text) for text in texts]
        gap = min(SORT_BUTTON_GAP, max(0, tabs.width() - tabs_end - widths[-1]))  # 가장 좁을 때는 틈을 줄여서라도 줄 안에
        room = tabs.width() - tabs_end - gap
        self._set_sort_button_text(next((text for text, width in zip(texts, widths) if width <= room), texts[-1]))
        button.resize(button.sizeHint())
        button.move(tabs_end + gap, bar.y() + max(0, (bar.height() - button.height()) // 2))
        button.raise_()

    def _set_sort_button_text(self, text):
        """단추에 글과 그 글의 시트(가장 짧은 글은 좁은 여백)를 넣음 — 같은 글이면 건드리지 않음."""
        button = self.sidebar_sort_button
        if button.text() != text:
            button.setStyleSheet(sort_button_style(compact=text == sidebar_sort.COMPACT_BUTTON_TEXT))
            button.setText(text)

    def _sort_button_width(self, text):
        """그 글일 때 단추가 바라는 폭 — 처음이면 단추에 잠깐 넣어 재고 기억((글, 글꼴)마다 — 창의 테마 시트가 걸리기 전(만드는 중)과 뒤는 글꼴이 다름).
        잰 뒤의 글은 부른 쪽(_fit_sidebar_sort_button)이 다시 정함."""
        button = self.sidebar_sort_button
        button.ensurePolished()
        key = (text, button.font().toString())
        if key not in self._sidebar_sort_widths:
            self._set_sort_button_text(text)
            self._sidebar_sort_widths[key] = button.sizeHint().width()
        return self._sidebar_sort_widths[key]

    # ---------------------------------------------------------------- 기준 바꾸기

    def set_sidebar_sort(self, mode):
        """정렬 기준을 mode("name"·"kind"·"version")로 — 세 탭에 바로 적용(목록을 쓰는 중이면 Mov 목록의 줄은 끝난 뒤에). 모르는 값은 ValueError
        (아무것도 바꾸지 않음). 같은 기준이면 체크만 맞춤(체크된 항목을 다시 누르면 Qt가 끔)."""
        sidebar_sort.button_text(mode)  # 모르는 값이면 여기서 ValueError
        previous = self.sidebar_sort_mode
        if mode == previous and mode != sidebar_sort.TIME_MODE:
            self._sync_sidebar_sort_button()
            return
        if mode == sidebar_sort.TIME_MODE:  # 고를 때마다(이미 시간이어도) 고친 시각을 다시 읽음 — 그사이 다시 렌더한 영상이 위로 오게
            self._sidebar_times_stale = True
            self._sidebar_seq_times.clear()
        if not self._sidebar_ranked():
            self._rank_sidebar_items(renumber=True)  # 지금의 줄 순서 = 이름(기본) 순서 — 돌아올 자리로 적어 둠
        # (순위가 이미 있으면 줄은 이름 순서가 아님 — 다른 기준으로 정렬해 뒀거나, 이름으로 되돌리기가 아직 미뤄진 채: 적어 둔 순위를 그대로 씀)
        self.sidebar_sort_mode = mode
        self._sync_sidebar_sort_button()
        print(f"{SORT_LOG_PREFIX} 사이드바: {sidebar_sort.LABELS[mode]}", flush=True)
        self._apply_sidebar_sort(show_current=True)
        self._set_seq_items(video_list.sort_sequences(self._current_seq_items()))  # 이름 순서로 되돌린 목록을 넣음 — 넣을 때 기준대로 정렬
        self._schedule_all_rebuild()

    # ---------------------------------------------------------------- Mov 목록

    def _schedule_sidebar_sort(self, *_args):
        """Mov 목록에 항목이 들어옴 → 정렬해 둔 동안만 0ms 뒤 정렬(여러 항목이 한 번에 들어와도 한 번). 신호의 인자는 버림."""
        if self.sidebar_sort_mode != sidebar_sort.DEFAULT_MODE:
            self._sidebar_sort_timer.start(0)

    def _sidebar_items(self):
        return [self.sidebar.item(i) for i in range(self.sidebar.count())]

    def _rank_sidebar_items(self, renumber=False):
        """Mov 항목의 기본 순위를 적음 → 항목 목록(줄 순서). renumber: 모든 항목을 지금의 줄 번호로(목록이 이름 순서일 때만 부름). 아니면 순위 없는
        항목(정렬해 둔 동안 목록 끝에 붙은 새 항목)만 지금까지의 순위 뒤에 줄 순서대로."""
        items = self._sidebar_items()
        if renumber:
            for row, item in enumerate(items):
                item.setData(SIDEBAR_RANK_ROLE, row)
            return items
        ranks = [item.data(SIDEBAR_RANK_ROLE) for item in items]
        following = max((rank for rank in ranks if rank is not None), default=-1) + 1
        for item, rank in zip(items, ranks):
            if rank is None:
                item.setData(SIDEBAR_RANK_ROLE, following)
                following += 1
        return items

    def _sidebar_ranked(self):
        """Mov 항목에 기본 순위가 적혀 있는가 = 줄이 이름(기본) 순서가 아닐 수 있음. 기준(sidebar_sort_mode)이 아니라 이것으로 판단: 목록을 쓰는 중이라
        줄 옮기기가 미뤄지면 기준과 줄 순서가 잠깐 어긋남(이름으로 바꿨는데 줄은 아직 종류 순서), 정렬해 둔 채 새로 불러온 목록은 아직 순위 없이 이름 순서."""
        return any(item.data(SIDEBAR_RANK_ROLE) is not None for item in self._sidebar_items())

    def _sidebar_items_in_default_order(self):
        """Mov 항목을 이름(기본) 순서로 — 순위가 없으면 줄 순서 그대로(= 이름 순서), 있으면 기본 순위 순서(목록은 건드리지 않음)."""
        if not self._sidebar_ranked():
            return self._sidebar_items()
        return self._sidebar_items_by_rank()

    def _apply_sidebar_sort(self, show_current=False):
        """Mov 목록의 줄을 지금 기준대로 옮김(이미 그 순서면 건드리지 않음). 이름(기본)이면 기본 순위 순서로 되돌리고 순위를 지움(다음에 정렬할 때 새로
        적음) — 순위를 적은 적이 없으면(처음부터 이름) 아무것도 안 함. 목록을 쓰는 중이면 미룸(SORT_RETRY_MS 뒤 다시).
        show_current: 사용자가 기준을 바꿈 — 옮긴 뒤 현재 항목(보던 영상)이 보이게, 없으면 맨 위부터. 아니면(항목이 들어옴) 맨 위에 보이던 항목을 그 자리에."""
        if self._sidebar_refresh_holds:
            self._sidebar_sort_timer.start(SORT_RETRY_MS)
            return
        mode = self.sidebar_sort_mode
        if mode == sidebar_sort.DEFAULT_MODE:
            if not self._sidebar_ranked():
                return  # 순위 없는 목록 = 정렬한 적 없이 들어온 그대로
            self._reorder_sidebar_items(self._sidebar_items_by_rank(), show_current)
            for item in self._sidebar_items():
                item.setData(SIDEBAR_RANK_ROLE, None)
            return
        time_of = None
        if mode == sidebar_sort.TIME_MODE:
            self._read_sidebar_times()
            time_of = _item_time
        self._reorder_sidebar_items(sidebar_sort.ordered(self._sidebar_items_by_rank(), mode, stem_of=_item_stem, time_of=time_of), show_current)

    def _read_sidebar_times(self):
        """(시간 정렬 — 줄을 옮기기 직전) Mov 항목마다 파일을 고친 시각(os.stat)을 항목에 적음(SIDEBAR_MTIME_ROLE): 아직 없는 항목만, 사용자가 '시간'을
        (다시) 고른 뒤 처음이면(_sidebar_times_stale) 모두 다시. 읽지 못한 파일(지워짐·연결 끊김·경로 없는 항목)은 UNKNOWN_TIME(맨 뒤)으로 적고 — 시각을
        지어내 보이는 것이 아니라 차례만 — 몇 개인지와 첫 오류를 기록(파일마다 창을 띄우지 않음: 없어진 영상은 목록 다시 읽기가 알림)."""
        refresh, self._sidebar_times_stale = self._sidebar_times_stale, False
        started = time.monotonic()
        read, failed = 0, []
        for item in self._sidebar_items():
            if not refresh and item.data(SIDEBAR_MTIME_ROLE) is not None:
                continue
            path = item.toolTip()
            try:
                mtime = os.stat(path).st_mtime
            except OSError as exc:
                failed.append(f"{path or item.text()}: {type(exc).__name__}: {exc}")
                mtime = sidebar_sort.UNKNOWN_TIME
            item.setData(SIDEBAR_MTIME_ROLE, mtime)
            read += 1
        if read:
            note = f" — 읽지 못한 {len(failed)}개는 맨 뒤에 (첫 오류: {failed[0]})" if failed else ""
            print(f"{SORT_LOG_PREFIX} 고친 시각 읽음: {read}개 {time.monotonic() - started:.2f}초{note}", flush=True)

    def _sidebar_seq_time(self, seq):
        """(시간 정렬) 시퀀스(SeqInfo)의 고친 시각 = 첫 프레임 파일의 시각 — 한 번 읽어 기억(_sidebar_seq_times, '시간'을 다시 고르면 비움).
        읽지 못하면 기록 한 줄 뒤 UNKNOWN_TIME(맨 뒤)."""
        key = (seq.identity, seq.ext, seq.pad)
        if key not in self._sidebar_seq_times:
            try:
                mtime = os.stat(sequence_source.first_frame_path(seq)).st_mtime
            except OSError as exc:
                print(f"{SORT_LOG_PREFIX} 시퀀스의 고친 시각을 읽지 못해 맨 뒤에: {seq.identity}: {type(exc).__name__}: {exc}", flush=True)
                mtime = sidebar_sort.UNKNOWN_TIME
            self._sidebar_seq_times[key] = mtime
        return self._sidebar_seq_times[key]

    def _all_item_time(self, item):
        """(시간 정렬) All 목록 항목의 고친 시각 — 시퀀스는 첫 프레임의 시각, 영상은 Mov 항목에서 복제해 온 시각(아직 안 읽었으면 None)."""
        if item.data(ALL_KIND_ROLE) == "seq":
            return self._sidebar_seq_time(item.data(Qt.UserRole))
        return item.data(SIDEBAR_MTIME_ROLE)

    def _sidebar_items_by_rank(self):
        """Mov 항목을 기본 순위 순서로 (순위 없는 새 항목은 먼저 끝에 매김) — 목록은 건드리지 않음."""
        return sorted(self._rank_sidebar_items(), key=lambda item: item.data(SIDEBAR_RANK_ROLE))

    def _reorder_sidebar_items(self, ordered, show_current=False):
        """Mov 목록의 줄을 ordered(지금 항목들의 다른 차례) 순서로 → 옮겼으면 True. 항목 객체·고른 것·현재 항목은 그대로. 스크롤: show_current면 현재
        항목을 가운데에(없으면 맨 위부터), 아니면 맨 위에 보이던 항목을 다시 맨 위에."""
        widget = self.sidebar
        items = self._sidebar_items()
        if len(items) != len(ordered) or {id(item) for item in items} != {id(item) for item in ordered}:
            raise ValueError("정렬할 항목이 지금 목록의 항목과 다릅니다 (줄을 옮기기만 해야 함)")
        if all(now is wanted for now, wanted in zip(items, ordered)):
            return False
        selected = {id(item) for item in widget.selectedItems()}
        current = widget.currentItem()
        top = None if show_current else self._top_visible_sidebar_item()
        blocked = widget.blockSignals(True)  # 줄을 옮기는 동안의 현재 항목·선택 변화가 '고름'으로 읽히지 않게 (모델 신호는 그대로 — 개수 줄·All 목록)
        widget.setUpdatesEnabled(False)
        try:
            for row in reversed(range(widget.count())):
                widget.takeItem(row)  # 떼기만 — 항목은 ordered가 쥐고 있음 (끝에서부터: 남은 줄을 밀지 않음)
            for item in ordered:
                widget.addItem(item)
            if current is not None:
                widget.setCurrentItem(current, QItemSelectionModel.NoUpdate)
            _select_rows(widget, lambda item: id(item) in selected)
        finally:
            widget.setUpdatesEnabled(True)
            widget.blockSignals(blocked)
        if show_current and current is not None:
            widget.scrollToItem(current, QAbstractItemView.PositionAtCenter)
        elif show_current:
            widget.scrollToTop()
        elif top is not None:
            widget.scrollToItem(top, QAbstractItemView.PositionAtTop)
        return True

    def _top_visible_sidebar_item(self):
        """Mov 목록에서 맨 위에 보이는 항목 (없으면 None)."""
        widget = self.sidebar
        return next((widget.item(i) for i in range(widget.count()) if widget.visualItemRect(widget.item(i)).bottom() >= 0), None)

    @contextlib.contextmanager
    def _sidebar_default_order(self):
        """(목록 다시 읽기가 계획을 넣는 동안) 정렬해 둔 Mov 목록을 잠깐 이름(기본) 순서로 — 계획의 줄 번호·넣을 자리가 그 순서 기준이라. 끝나면 새 줄
        순서로 순위를 다시 매기고 지금 기준대로 정렬(이름이면 순위를 지움). 순위가 없으면(줄이 이미 이름 순서) 아무것도 안 함."""
        if not self._sidebar_ranked():
            yield
            return
        top = self._top_visible_sidebar_item()
        self._reorder_sidebar_items(self._sidebar_items_by_rank())
        try:
            yield
        finally:
            self._rank_sidebar_items(renumber=True)
            self._apply_sidebar_sort()
            if top is not None and self.sidebar.row(top) >= 0:  # 맨 위에 보이던 영상이 남았으면 다시 맨 위로 (빠졌으면 그대로)
                self.sidebar.scrollToItem(top, QAbstractItemView.PositionAtTop)
