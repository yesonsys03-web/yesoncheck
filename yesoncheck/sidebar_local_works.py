"""PlayerSidebarMixin의 부모 믹스인 `SidebarLocalWorksMixin` — 회사 밖 PC의 작품 고르기: 사내 공유 설정(NAS)을 찾지 못한 PC에서
'Tools → 작품 경로 관리'가 그 PC만의 작품 목록을 열고, 등록한 작품을 작품 → 폴더 → 폴더로 골라 영상 목록을 봄 (2026-11-27).

저장·규칙은 Qt 없는 `local_works`(작품마다 이름·이 PC의 폴더·단계 수 0·1·2). 여기는 창에 잇는 얇은 층이고, 사내 작품의 코드는 갈래의
맨 앞에서 한 줄로 여기를 부를 뿐 (사내 PC의 동작은 그대로):

- 언제 쓰나: 공유 설정을 **찾지 못했을 때만**(shared_config_not_found) — `_apply_shared_config` → `_use_local_works`. 공유 설정을 읽은
  PC·진짜 문제(폴더는 열리는데 파일이 깨짐 등)는 이 PC의 목록을 쓰지 않음(`local_works`가 빈 dict). 앱은 '회사 밖 PC'와 '사내인데
  NAS가 끊긴 PC'를 구별하지 못하므로 뒤의 PC에서도 이 길 — 작품 창의 머리 글이 그 사실을 말하고 사유는 단추 뒤에.
- 작품 콤보: `_work_names`(공유 작품 + 이 PC의 작품, 이름 순서) — `reload_work_combo`.
- 작품 폴더: `get_work_path` → `_local_work_folder` — 이 PC의 경로 그대로(변환표·공유 자리 변환 없음), 없으면 한 번 알리고 "".
- 둘째·셋째 콤보: `update_season_list` → `_fill_local_work_pickers`, `update_job_list` → `_fill_local_job_picker` — 안내 항목은
  '시즌선택'·'job선택'이 아니라 '폴더선택'(`_picker_placeholder`), 항목은 `local_works.subfolders`. 단계 1은 사내의 시즌 없는 작품처럼
  셋째 콤보만 씀.
- 목록: `_job_picked`가 단계 수만큼 다 골랐는지를 `_local_job_picked`로 묻고, `_load_job_list` → `_load_local_work_list`가 끝 폴더를
  `load_videos_from_folder(…, quiet=True)`로 — '폴더 열기'와 같은 규칙(하위 폴더까지, 출처는 폴더라 새로고침도 같은 길)이되 안내 창·모두
  고르기 없이. 단계 0은 작품을 고를 때 `_fill_local_work_pickers`가 **한 번** 읽음(콤보를 비우는 신호마다 다시 읽지 않게).
  같은 폴더를 다시 고르면(`_on_job_activated` → `_refresh_shown_local_list`) 사내 job처럼 목록만 다시 읽음 — 보던 영상은 그대로.
- 창: `manage_work_paths` → `manage_local_works` — 비밀번호 없음. 읽지 못한 목록(`local_works_problem`)이면 열지 않고 사유를 보임
  (덮어쓰지 않게). 그 문제는 켤 때 `_report_local_works_problem`이 한 번 알림 (`resolve_shared_config_problem`).

상태(`self.local_works`·`self.local_works_problem`)는 `VideoPlayerBase.__init__`이 만듦.
**창과 알림의 글은 화면 언어를 따름**(글자 표 `ui_text`의 `local_works.*` — 딸린 창은 보통 한글로 남지만 이 창은 회사 밖 PC에서 쓰는
창이라 두 언어로; 사용자 2026-11-27). 창은 열 때마다 만들므로 그때의 언어. 기록(stderr)에 적는 글과 자세히 칸의 기술 글
(찾아본 곳·트레이스백 — 기록과 같은 글)은 한글 그대로.
"""

import os
import sys
import traceback

from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from yesoncheck import local_works, paths, ui_text
from yesoncheck.sidebar_items import SIDEBAR_SOURCE_ROLE
from yesoncheck.user_files import UserFileError

LOG_PREFIX = "[이 PC의 작품]"
BOX_TITLE_PROPERTY = "ycTitle"  # macOS의 QMessageBox는 창 제목을 버림 — 시험·실행 시험이 읽는 속성 (player_update와 같은 이름)


def _t(key, **values):
    """이 창의 화면 글 (지금 화면 언어) — 글자 표의 `local_works.<key>`."""
    return ui_text.text(f"local_works.{key}", **values)


class SidebarLocalWorksMixin:
    """VideoPlayer의 '이 PC의 작품' — 읽기·작품 고르기 갈래·작품 창."""

    # ---------------------------------------------------------------- 읽기

    def _use_local_works(self, wanted):
        """(_apply_shared_config) 공유 설정을 찾지 못한 PC면 이 PC의 작품 목록을 읽어 둠, 아니면 비움. 읽지 못하면 빈 목록 +
        local_works_problem(그 사유 — 기록에는 바로 트레이스백째, 알림은 _report_local_works_problem·작품 창)."""
        self.local_works = {}
        self.local_works_problem = None
        if not wanted:
            return
        try:
            self.local_works = {work.name: work for work in local_works.read()}
        except (UserFileError, OSError, TimeoutError) as exc:
            self.local_works_problem = str(exc)  # 알림 창의 머리 글은 보일 때의 화면 언어로 붙임 (_show_local_works_problem)
            print(f"{LOG_PREFIX} {ui_text.korean('local_works.read_failed')}\n\n{exc}", file=sys.stderr, flush=True)
            traceback.print_exc()

    def reload_local_works(self):
        """이 PC의 작품 목록을 다시 읽고 작품 콤보를 다시 채움 (작품 창이 고친 뒤)."""
        self._use_local_works(True)
        self.reload_work_combo()

    def _report_local_works_problem(self):
        """(창 표시 후 — resolve_shared_config_problem) 이 PC의 작품 목록을 읽지 못했으면 한 번 알림."""
        if self.local_works_problem:
            self._show_local_works_problem(self)

    def _show_local_works_problem(self, parent):
        """읽지 못한 목록의 사유 창. 이 PC는 작품 창(과 그 '찾지 못한 까닭' 단추)까지 가지 못하므로, 공유 설정을 찾지 못했다는 것과
        그 사유(자세히 칸)도 여기서 보임 — 사내에서 NAS가 끊긴 PC가 빈 작품 목록의 까닭을 볼 길."""
        title = _t("problem.title")
        body = f"{_t('read_failed')}\n\n{self.local_works_problem}\n\n{_t('not_found')}"
        box = QMessageBox(QMessageBox.Warning, title, body, QMessageBox.Ok, parent)
        box.setProperty(BOX_TITLE_PROPERTY, title)
        box.setDetailedText(f"{self._shared_config_problem_text()}{self._config_dir_search_problems_text()}")
        try:
            box.exec_()
        finally:
            box.deleteLater()

    def _local_work(self, name):
        """name이 이 PC의 작품이면 그 LocalWork, 아니면 None."""
        return self.local_works.get(name)

    def _work_names(self):
        """작품 콤보에 넣을 이름들: 공유 설정의 작품 + 이 PC의 작품 (이름 순서)."""
        return sorted(set(self.work_paths) | set(self.local_works))

    def _local_work_folder(self, work):
        """work의 폴더(이 PC의 경로 그대로). 없으면 한 번 알리고 ""."""
        if os.path.isdir(work.folder):
            return work.folder
        self._report_work_path_problem(_t("folder_gone", name=work.name, folder=work.folder), title=_t("path_problem.title"))
        return ""

    # ---------------------------------------------------------------- 작품 고르기

    def _picker_placeholder(self, key):
        """둘째·셋째 콤보의 안내 항목 글: 고른 작품이 이 PC의 작품이면 '폴더선택', 아니면 key('picker.season'·'picker.job')의 글."""
        if self._local_work(self.workComboBox.currentText()) is not None:
            return ui_text.text("picker.folder")
        return ui_text.text(key)

    def _reset_picker(self, combo):
        """combo를 안내 항목 하나로 (신호는 그대로 나감 — 사내 작품의 콤보 비우기와 같음)."""
        combo.clear()
        combo.addItem(ui_text.text("picker.folder"))

    def _add_subfolders(self, combo, folder):
        """folder의 고를 폴더들을 combo에 더함. 읽지 못하면 한 번 알림 (콤보는 안내 항목만)."""
        try:
            names = local_works.subfolders(folder)
        except OSError as exc:
            self._report_work_path_problem(f"{_t('folder_unreadable')}\n\n{folder}\n\n{type(exc).__name__}: {exc}",
                                           title=_t("path_problem.title"))
            return
        combo.addItems(names)

    def _fill_local_work_pickers(self, work):
        """(update_season_list — 이 PC의 작품을 고름) 둘째 콤보를 비우고 단계 수에 맞게 채움: 2 = 작품 폴더의 하위 폴더, 1·0 = 안내
        항목만(단계 1은 셋째 콤보를 _fill_local_job_picker가). 단계 0은 여기서 작품 폴더의 영상을 한 번 읽어 목록에.
        둘째 콤보를 비우고 채우는 동안은 그 신호(→ update_job_list)를 막고 셋째 콤보를 아래에서 한 번만 채움 — 신호마다 채우면 고를
        폴더를 세 번 읽음(GUI 스레드의 폴더 읽기 — 느린 공유에서 멈춤이 세 배). 셋째 콤보의 신호는 그대로라 보이던 목록이 비워짐."""
        self._work_path_problems_shown = set()
        blocked = self.seasonComboBox.blockSignals(True)
        try:
            self._reset_picker(self.seasonComboBox)
            folder = self._local_work_folder(work)
            if folder and work.levels == 2:
                self._add_subfolders(self.seasonComboBox, folder)
        finally:
            self.seasonComboBox.blockSignals(blocked)
        self._fill_local_job_picker(work)  # → update_playlist(목록 비움)
        if folder and work.levels == 0:
            self._show_local_folder(folder)

    def _fill_local_job_picker(self, work):
        """(update_job_list) 셋째 콤보: 단계 1 = 작품 폴더의 하위 폴더, 단계 2 = 둘째 콤보에서 고른 폴더의 하위 폴더(고르기 전에는
        안내 항목만), 단계 0 = 안내 항목만."""
        self._reset_picker(self.jobComboBox)
        if work.levels == 0 or (work.levels == 2 and not self._picked(self.seasonComboBox)):
            return
        if work.levels == 2:
            # 둘째 콤보에서 폴더를 고름: 읽지 못한 폴더의 알림은 고를 때마다 (작품을 고를 때만 지우면, 다른 폴더를 고른 뒤 다시 골라도
            # 같은 글이라 말없이 빈 칸)
            self._work_path_problems_shown = set()
        folder = self._local_work_folder(work)
        if not folder:
            return
        if work.levels == 2:
            folder = os.path.join(folder, self.seasonComboBox.currentText())
        self._add_subfolders(self.jobComboBox, folder)

    def _local_picks(self, work):
        """work에서 지금 고른 폴더 이름들(고른 차례) — 단계 수만큼 다 고르지 않았으면 None."""
        if work.levels == 0:
            return []
        if not self._picked(self.jobComboBox):
            return None
        if work.levels == 1:
            return [self.jobComboBox.currentText()]
        if not self._picked(self.seasonComboBox):
            return None
        return [self.seasonComboBox.currentText(), self.jobComboBox.currentText()]

    def _local_job_picked(self, work):
        """(_job_picked) 콤보로 끝 폴더까지 골랐는지. 단계 0은 콤보로 고르는 것이 없어 늘 False — 그 목록은 작품을 고를 때
        _fill_local_work_pickers가 넣음 (콤보를 비우는 신호가 올 때마다 작품 폴더 전체를 다시 읽지 않게)."""
        return work.levels > 0 and self._local_picks(work) is not None

    def _load_local_work_list(self, work):
        """(_load_job_list — _job_picked가 참일 때) 고른 끝 폴더의 영상을 목록에."""
        folder = self._local_work_folder(work)
        if folder:
            self._show_local_folder(local_works.picked_folder(work, self._local_picks(work)))

    def _show_local_folder(self, folder):
        """folder 아래의 영상을 '폴더 열기'와 같은 규칙으로 목록에 — 안내 창·모두 고르기 없이. 읽은 것을 기억해 Qt가 바로 다음에 보내는
        activated(_on_job_activated)가 같은 폴더를 또 읽지 않게 (목록을 비울 때 지워지므로 넣은 뒤에)."""
        self.load_videos_from_folder(folder, quiet=True)
        self._job_list_loaded_for = self._job_selection()

    def _refresh_shown_local_list(self, work):
        """(_on_job_activated — 같은 폴더를 다시 고름, _job_picked가 참) 목록이 지금 고른 끝 폴더의 것이면 다시 읽기만 하고 True —
        사내 job을 다시 고를 때처럼 보던 영상(A·재생 자리·와이프 B)은 그대로 (사용자 2026-11-27 "같은 폴더를 다시 고를 때도 기존대로";
        처음에는 목록을 새로 불러와 첫 영상을 A에 다시 열었음). 목록이 그 폴더의 것이 아니면(그사이 다른 폴더를 불러옴·끌어다 놓음,
        고를 때 영상이 없었음) False — 부른 쪽이 처음 고를 때처럼 불러옴."""
        folder = local_works.picked_folder(work, self._local_picks(work))
        sources = {source for source in self._sidebar_sources
                   if source.kind == "folder" and paths.same_path(source.folder, folder)}
        if not any(self.sidebar.item(row).data(SIDEBAR_SOURCE_ROLE) in sources for row in range(self.sidebar.count())):
            return False
        self.refresh_sidebar()
        return True

    # ---------------------------------------------------------------- 작품 창

    def manage_local_works(self):
        """'Tools → 작품 경로 관리' (공유 설정을 찾지 못한 PC): 이 PC의 작품 목록 창. 목록을 읽지 못했으면 열지 않고 사유를 보임."""
        if self.local_works_problem:
            self._show_local_works_problem(self)
            return
        dialog = self._local_works_dialog()
        try:
            dialog.exec_()
        finally:
            dialog.deleteLater()

    def _local_works_dialog(self):
        """이 PC의 작품 목록 창을 만듦 (띄우는 일은 manage_local_works — 시험은 단추를 바로 누름). 글은 지금 화면 언어.
        창의 속성: intro_label, works_list, add_button, folder_button, levels_button, remove_button, reason_button, close_button."""
        dialog = QDialog(self)
        dialog.setWindowTitle(_t("title"))
        dialog.setModal(True)
        dialog.setMinimumSize(700, 460)
        layout = QVBoxLayout(dialog)
        dialog.intro_label = QLabel(_t("intro"))
        dialog.intro_label.setWordWrap(True)
        layout.addWidget(dialog.intro_label)
        dialog.works_list = QListWidget()
        dialog.works_list.setAlternatingRowColors(True)
        layout.addWidget(dialog.works_list)
        buttons = QHBoxLayout()
        for attribute, key, slot in (
            ("add_button", "add", self._add_local_work),
            ("folder_button", "folder", self._change_local_work_folder),
            ("levels_button", "levels", self._change_local_work_levels),
            ("remove_button", "remove", self._remove_local_work),
        ):
            button = QPushButton(_t(key))
            button.clicked.connect(lambda _checked=False, slot=slot: slot(dialog))
            setattr(dialog, attribute, button)
            buttons.addWidget(button)
        dialog.close_button = QPushButton(_t("close"))
        dialog.close_button.clicked.connect(dialog.close)
        buttons.addWidget(dialog.close_button)
        layout.addLayout(buttons)
        bottom = QHBoxLayout()
        dialog.reason_button = QPushButton(_t("reason"))
        dialog.reason_button.clicked.connect(lambda _checked=False: self._show_shared_config_reason(dialog))
        bottom.addWidget(dialog.reason_button)
        bottom.addStretch()
        layout.addLayout(bottom)
        self._refresh_local_works_list(dialog)
        return dialog

    def _refresh_local_works_list(self, dialog):
        dialog.works_list.clear()
        for name in sorted(self.local_works):
            work = self.local_works[name]
            dialog.works_list.addItem(f"{work.name}: {work.folder}\n    {local_works.level_text(work.levels)}")

    def _selected_local_work(self, dialog):
        """창의 목록에서 고른 작품 — 고르지 않았으면 안내하고 None."""
        row = dialog.works_list.currentRow()
        names = sorted(self.local_works)
        if not 0 <= row < len(names):
            QMessageBox.information(dialog, _t("title"), _t("pick_first"))
            return None
        return self.local_works[names[row]]

    def _ask_levels(self, dialog, current):
        """단계 수를 고르게 함 → 고른 수, 취소면 None."""
        texts = [local_works.level_text(levels) for levels in local_works.LEVELS]
        text, ok = QInputDialog.getItem(dialog, _t("title"), _t("ask.levels"), texts, local_works.LEVELS.index(current), False)
        if not ok or text not in texts:
            return None
        return local_works.LEVELS[texts.index(text)]

    def _save_local_works(self, dialog, save):
        """save()로 설정 파일을 고치고 창·작품 콤보를 다시 채움 → 됐으면 True. 틀린 값(ValueError·LookupError — 창이 미리 거르지 못한
        것: 그사이 다른 창이 고침 등)은 그 글로 안내, 파일 문제(깨진 파일·잠금·쓰기 실패)는 트레이스백째 기록과 창으로 — 파일은 그대로."""
        try:
            save()
        except (ValueError, LookupError) as exc:
            QMessageBox.warning(dialog, _t("title"), str(exc))
            return False
        except (UserFileError, OSError, TimeoutError):
            print(f"{LOG_PREFIX} {ui_text.korean('local_works.save_failed')}", file=sys.stderr, flush=True)
            traceback.print_exc()
            QMessageBox.critical(dialog, _t("title"), f"{_t('save_failed')}\n\n{traceback.format_exc()}")
            return False
        self.reload_local_works()
        self._refresh_local_works_list(dialog)
        if self.local_works_problem:  # 저장은 됐는데 다시 읽지 못함 — 말없이 빈 목록을 보이지 않음
            self._show_local_works_problem(dialog)
        return True

    @staticmethod
    def _folder_as_on_disk(folder):
        """고른 폴더를 적어 둘 경로로: 구분자를 다듬고, 그대로는 없는데 이름의 정규화(NFC·NFD)만 다른 실제 폴더가 있으면 그 경로
        ('폴더 열기'와 같은 다듬기 — NFS 공유의 한글 폴더는 열기 창이 준 모양이 디스크의 이름과 다르면 없다고 나옴)."""
        folder = paths.normalize_native(os.path.normpath(folder))
        return paths.find_unicode_variant(folder) or folder

    def _add_local_work(self, dialog):
        name, ok = QInputDialog.getText(dialog, _t("title"), _t("ask.name"))
        name = name.strip() if ok else ""
        if not name:
            return
        # 화면 언어로 알릴 수 있게 저장 전에 거름 (저장 함수도 같은 것을 다시 봄 — 그쪽 글은 한글)
        if name in self.local_works:
            QMessageBox.warning(dialog, _t("title"), _t("name.exists", name=name))
            return
        if name in local_works.reserved_names():
            QMessageBox.warning(dialog, _t("title"), _t("name.reserved", name=name))
            return
        folder = QFileDialog.getExistingDirectory(dialog, _t("ask.folder", name=name))
        if not folder:
            return
        levels = self._ask_levels(dialog, local_works.DEFAULT_LEVELS)
        if levels is None:
            return
        work = local_works.LocalWork(name, self._folder_as_on_disk(folder), levels)
        self._save_local_works(dialog, lambda: local_works.add(work))

    def _change_local_work_folder(self, dialog):
        work = self._selected_local_work(dialog)
        if work is None:
            return
        folder = QFileDialog.getExistingDirectory(dialog, _t("ask.folder", name=work.name), work.folder)
        if folder:
            self._save_local_works(dialog, lambda: local_works.change(work.name, folder=self._folder_as_on_disk(folder)))

    def _change_local_work_levels(self, dialog):
        work = self._selected_local_work(dialog)
        if work is None:
            return
        levels = self._ask_levels(dialog, work.levels)
        if levels is not None:
            self._save_local_works(dialog, lambda: local_works.change(work.name, levels=levels))

    def _remove_local_work(self, dialog):
        work = self._selected_local_work(dialog)
        if work is None:
            return
        answer = QMessageBox.question(dialog, _t("title"), _t("remove.ask", name=work.name, folder=work.folder),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._save_local_works(dialog, lambda: local_works.remove(work.name))

    def _show_shared_config_reason(self, dialog):
        """공유 설정을 찾지 못한 사유: 본문은 쉬운 말, 기술 글(찾아본 곳·트레이스백 — 기록과 같은 한글 글)은 자세히 칸에."""
        title = _t("reason.title")
        box = QMessageBox(QMessageBox.Information, title, f"{_t('not_found')} {_t('not_found.local')}", QMessageBox.Ok, dialog)
        box.setProperty(BOX_TITLE_PROPERTY, title)
        box.setDetailedText(f"{self._shared_config_problem_text()}{self._config_dir_search_problems_text()}")
        try:
            box.exec_()
        finally:
            box.deleteLater()
