"""사이드바 우클릭 메뉴의 단축키 — C 파일 복사·J 애니매틱 하나로 합치기·M 미디어 정보·R 썸네일 다시 만들기·[ ] 비디오 A·B로 열기
(사용자 요청 2026-11-18 — [ ]는 와이프할 영상을 키보드로 A·B에 놓으려고).

키를 받는 규칙(Ctrl·Alt·Meta 아님·자동 반복 삼킴·예외 알림)은 `player_menus.run_key_shortcut`이 정하고(`ITEM_KEY_SHORTCUTS`),
여기는 키가 할 일 — **지금 보는 탭을 따름**:
- Mov 탭: Mov 목록의 선택 (우클릭 메뉴와 같음).
- All 탭: All 목록의 선택 — C·J는 mov만(선택 재생과 같은 규칙 `_playlist_selection`, 시퀀스만 고르면 알림 창),
  M·R은 종류대로(mov는 Mov 쪽 일, 시퀀스는 Seq 쪽 일 — All 우클릭 메뉴처럼 선택을 원본 목록에 비춰 돌리고 되돌림).
- Seq 탭: 시퀀스 메뉴에 있는 일([ ] 열기·M 정보 보기·R 썸네일 다시 만들기)만. 없는 일(C·J)은 고른 시퀀스가 있으면 알림 창 —
  숨은 Mov 탭의 선택으로 몰래 돌지 않게.
고른 것이 없으면 창 없이 기록 한 줄(우클릭 메뉴는 항목 위에서만 뜨므로 같은 상황이 없음 — 조용히 넘기지 않게 기록만) — 고른 것만 봄:
현재 항목(Tab 포커스가 선택 없이 만드는 줄)으로 대신하지 않음. 예외 하나: Mov 탭의 R은 예전 R 그대로
(`regenerate_selected_thumbnails` — 고른 것이 없으면 '선택된 파일이 없습니다' 창).
All 탭에서는 먼저 밀린 All 목록 다시 만들기를 돌림(`_key_tab` — 우클릭 메뉴와 같음: 원본에서 빠진 항목을 '골랐다'고 보지 않게;
다시 만들기는 선택·현재 항목을 지킴).
딸린 창의 글은 한글, 인용하는 기능 이름은 지금 화면의 이름(키 표시 `(C)`는 뺌), 기록 줄은 한국어 이름.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from yesoncheck.player_menus import item_name
from yesoncheck.sidebar_items import ALL_KIND_ROLE


class SidebarKeysMixin:
    """VideoPlayer의 사이드바 키 C·J·M·R·[·] — 지금 탭의 선택으로 우클릭 메뉴의 그 일을 함."""

    def _key_tab(self):
        """지금 보는 사이드바 목록 — All 탭이면 밀린 다시 만들기를 먼저 돌림 (우클릭 메뉴 `show_all_context_menu`와 같음)."""
        tab = self.sidebar_tabs.currentWidget()
        if tab is self.all_sidebar and self._all_rebuild_timer.isActive():
            self._all_rebuild_timer.stop()
            self._rebuild_all_list()
        return tab

    # ---------------------------------------------------------------- [ ] 비디오 A·B로 열기

    def open_in_a_for_key(self):
        """[ 키 — 고른 항목을 비디오 A로 (우클릭 '비디오 A 열기'와 같은 일)."""
        self._open_for_key("A", "side_menu.open_a")

    def open_in_b_for_key(self):
        """] 키 — 고른 항목을 비디오 B로 (우클릭 '비디오 B 열기'와 같은 일 — 와이프할 영상을 B에 놓을 때)."""
        self._open_for_key("B", "side_menu.open_b")

    def _open_for_key(self, side, text_key):
        """고른 것 중 현재 항목(현재 항목이 고른 것 밖이면 고른 것의 첫 줄)을 side에 엶 — 영상은 경로, 시퀀스는 가상 경로.
        선택 재생 중에는 열지 않음 — 목록 클릭처럼 (사용자 요청 2026-11-18; 클릭과 달리 키는 기록 한 줄 — 눌렀는데 아무 일도 없어 보이지 않게)."""
        if self.is_playlist_playing:
            print(f"[{item_name(text_key, korean=True)}] 선택 재생 중에는 열지 않습니다 — 이어 재생을 끝낸 뒤 여세요")
            return
        tab = self._key_tab()
        item = _focused_selected_item(tab)
        if item is None:
            print(f"[{item_name(text_key, korean=True)}] 고른 항목이 없습니다")
            return
        if tab is self.seq_sidebar or (tab is self.all_sidebar and item.data(ALL_KIND_ROLE) == "seq"):
            self.open_file(side, item.data(Qt.UserRole).identity)
        else:
            self.open_file(side, item.toolTip())

    # ---------------------------------------------------------------- C·J (mov만)

    def copy_files_for_key(self):
        """C 키(한글 ㅊ) — 고른 영상을 폴더를 골라 복사 (우클릭 '파일 복사'와 같은 일)."""
        movie_paths = self._movie_paths_for_key("side_menu.copy")
        if movie_paths:
            self._copy_files_choosing_folder(movie_paths)

    def merge_videos_for_key(self):
        """J 키(한글 ㅓ) — 고른 영상을 하나로 합침 (우클릭 '애니매틱 하나로 합치기'와 같은 일 — 저장할 곳을 물음)."""
        movie_paths = self._movie_paths_for_key("side_menu.merge")
        if movie_paths:
            self._merge_files(movie_paths)

    def _movie_paths_for_key(self, text_key):
        """C·J가 다룰 영상 경로 (목록 순서) — 없으면 까닭을 알리고 None."""
        name, log_name = item_name(text_key), item_name(text_key, korean=True)
        tab = self._key_tab()
        if tab is self.seq_sidebar:
            print(f"[{log_name}] Seq 탭에는 이 기능이 없습니다 — Mov·All 탭에서 영상을 고르세요")
            if self.seq_sidebar.selectedItems():
                QMessageBox.information(
                    self, name, f"Seq 탭에서는 '{name}' 기능을 쓸 수 없습니다 — Mov·All 탭에서 영상을 고르세요.")
            return None
        items = self._playlist_selection()
        if items:
            if tab is self.all_sidebar:
                skipped = len(self.all_sidebar.selectedItems()) - len(items)
                if skipped:  # 섞어 고른 시퀀스 — 조용히 건너뛰지 않게 기록
                    print(f"[{log_name}] 시퀀스 {skipped}개는 건너뜀 (mov만 다룸)")
            return [item.toolTip() for item in items]
        if tab is self.all_sidebar and self.all_sidebar.selectedItems():
            # All 탭에서 시퀀스만 고름 — 무엇이 왜 안 되는지 알림 (조용히 무시하지 않음)
            print(f"[{log_name}] 선택에 mov가 없음 (시퀀스는 건너뜀)")
            QMessageBox.information(
                self, name,
                f"선택에 mov가 없습니다 — '{name}' 기능은 mov만 다룹니다 (시퀀스는 건너뜀).\n"
                f"mov를 선택하세요 (우클릭 → '{item_name('side_menu.all.select_movs')}').")
        else:
            print(f"[{log_name}] 고른 영상이 없습니다")
        return None

    # ---------------------------------------------------------------- M 미디어 정보

    def show_media_info_for_key(self):
        """M 키(한글 ㅡ) — 고른 항목의 정보 창: 영상은 '미디어 정보', 시퀀스는 '정보 보기'.
        고른 것이 여럿이면 그중 현재 항목(키보드로 옮겨 다니는 줄), 현재 항목이 고른 것 밖이면 고른 것의 첫 줄 — 창은 하나만."""
        tab = self._key_tab()
        item = _focused_selected_item(tab)
        if item is None:
            print(f"[{item_name('side_menu.info', korean=True)}] 고른 항목이 없습니다")
            return
        if tab is self.seq_sidebar:
            self.show_seq_info(item)
        elif tab is self.all_sidebar and item.data(ALL_KIND_ROLE) == "seq":
            source = self._seq_item_for_identity(item.data(Qt.UserRole).identity)
            if source is None:  # All 목록이 Seq 목록보다 낡았음 (다시 만들기 전) — 조용히 넘기지 않게 기록
                print(f"[{item_name('side_menu.seq.info', korean=True)}] Seq 목록에서 이 시퀀스를 찾지 못했습니다: "
                      f"{item.data(Qt.UserRole).identity}")
                return
            self.show_seq_info(source)
        else:
            self.show_media_info(item.toolTip())

    # ---------------------------------------------------------------- R 썸네일 다시 만들기

    def regenerate_thumbnails_for_key(self):
        """R 키(한글 ㄱ) — 고른 항목의 썸네일을 다시 만듦: Mov 탭은 예전 R 그대로(`regenerate_selected_thumbnails`),
        Seq 탭은 고른 시퀀스('썸네일 다시 만들기' — 고른 것만: 메뉴의 `_selected_seq_items`처럼 현재 항목으로 대신하지 않음 —
        선택 없이 Tab 포커스로 생긴 보이지 않는 줄의 공유 썸네일을 지우지 않게), All 탭은 고른 mov와 시퀀스 둘 다."""
        tab = self._key_tab()
        if tab is self.seq_sidebar:
            seq = self.seq_sidebar
            items = [seq.item(i) for i in range(seq.count()) if seq.item(i).isSelected()]
            if items:
                self.regenerate_seq_thumbnails(items)
            else:
                print(f"[{item_name('side_menu.seq.thumbnails', korean=True)}] 고른 시퀀스가 없습니다")
        elif tab is self.all_sidebar:
            self._regenerate_all_tab_thumbnails()
        else:
            self.regenerate_selected_thumbnails()

    def _regenerate_all_tab_thumbnails(self):
        """All 탭의 선택을 Mov·Seq 목록에 비춰 각 쪽의 다시 만들기를 돌리고 원본 선택을 되돌림 (All 우클릭 메뉴와 같은 길)."""
        selected = self.all_sidebar.selectedItems()
        if not selected:
            print(f"[{item_name('side_menu.thumbnails', korean=True)}] 고른 항목이 없습니다")
            return
        kinds = {item.data(ALL_KIND_ROLE) for item in selected}
        # 다시 만드는 동안 이벤트를 처리함 — 목록 다시 읽기는 끝난 뒤로 미룸 (줄 번호·항목을 쥐고 있음)
        with self._hold_sidebar_refresh():
            snapshot = self._snapshot_source_selections()
            self._mirror_all_selection_to_sources()
            try:
                if "mov" in kinds:
                    self.regenerate_selected_thumbnails()
                if "seq" in kinds:
                    seq = self.seq_sidebar
                    items = [seq.item(i) for i in range(seq.count()) if seq.item(i).isSelected()]
                    if items:
                        self.regenerate_seq_thumbnails(items)
                    else:  # All 목록이 Seq 목록보다 낡았음 — 조용히 넘기지 않게 기록
                        print(f"[{item_name('side_menu.seq.thumbnails', korean=True)}] Seq 목록에서 고른 시퀀스를 찾지 못했습니다")
            finally:
                self._restore_source_selections(snapshot)


def _focused_selected_item(widget):
    """고른 항목 중 현재 항목, 현재 항목이 고른 것 밖이면 고른 것의 첫 줄(목록 순서), 고른 것이 없으면 None."""
    current = widget.currentItem()
    if current is not None and current.isSelected():
        return current
    selected = widget.selectedItems()
    if not selected:
        return None
    return min(selected, key=widget.row)
