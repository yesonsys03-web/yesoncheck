"""공유 설정·작품 경로 믹스인 (SidebarConfigPathsMixin): 앱이 켜질 때 공유 설정(작품 경로·변환표·마운트 맵)을 읽어 창에 넣는 일과
문제 알림, (Windows) 변환표 자동 설정, 그리고 작품 경로 관리 대화 상자·작품 → 이 PC 경로 조회·관리 비밀번호.

- 공유 설정: 동기·뒤 스레드 읽기 시작(`setup_shared_config`·`start_shared_config_load`), 읽은 결과를 창 상태에 넣기
  (`_apply_shared_config`·`_on_shared_config_loaded`), 닫을 때 기다림, 창 제목, 문제 알림·설정 폴더 고르기, 작품이 안 열리는 변환표 제안,
  `auto_setup_path_map`, 작품 콤보 다시 채우기.
- 작품 경로: work_paths.json 쓰기, 비밀번호 파일, `get_work_path`(작품 → 이 PC 경로 — 변환표·마운트 맵, 실패 창),
  관리 대화 상자와 추가·수정·삭제·비밀번호 바꾸기.
공유 설정과 작품 경로를 한 파일에 둔 것은 서로 부르기 때문: `manage_work_paths` ↔ `auto_setup_path_map`·`_shared_config_busy`, `auto_setup_path_map` →
`_confirm_work_paths_password`.

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin, SidebarConfigPathsMixin, SidebarRefreshMixin, SidebarThumbnailsMixin)`.
그래서 VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin 앞)에 오고, 이 메서드들의 이름은 다른 믹스인·VideoPlayerBase와
겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.work_paths`·`self.work_paths_file`·`self.shared_config_problem` 등)는 예전처럼
VideoPlayerBase.__init__(`setup_shared_config`·`set_shared_config_loading_state` 경유)과 `_apply_shared_config`가 넣고, 작품 콤보
(`update_season_list`)·업데이트 믹스인(`start_update_check`)의 메서드는 `self.`로 불러 그대로 닿음. 이 메서드들을 부르는 쪽(작품 콤보의
`get_work_path`, VideoPlayerBase의 메뉴·시작·닫기, app·smoke_test)도 `self.`·플레이어 객체로 부르므로 그대로 닿음.

공유 설정을 읽는 함수는 `shared_config_load.X`로 불러(모듈 속성 경유) 시험의 바꿔치기 지점이 그 모듈 한 곳임 — 여기서 `from … import`로 가져오지
말 것. 시험이 변환표 확인 창을 바꿔칠 때 문자열·속성 경로는 이 모듈 이름으로 적음: `sidebar_config_paths.PathMapSetupDialog`.
player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
"""

import hashlib
import json
import os
import time
import traceback

from PyQt5.QtCore import Qt, QThread
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from yesoncheck import build_info, path_map_setup, paths, shared_config, shared_config_load, timing_log
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog
from yesoncheck.shared_config_load import SharedConfigLoad, SharedConfigState, config_dir_from_chosen_folder
from yesoncheck.sidebar_items import LOADING_NOTICE, LOADING_TITLE_SUFFIX, LOADING_WORK_ITEM, WORK_PLACEHOLDER


class SidebarConfigPathsMixin:
    """VideoPlayer의 공유 설정 읽기·문제 알림·변환표 자동 설정과 작품 경로 관리·비밀번호."""

    def setup_shared_config(self):
        """공유 설정 폴더를 정하고 작품 경로(Windows는 변환표도)를 읽어 창에 넣습니다 (동기: 이 스레드에서 바로 읽음).

        = gather_shared_config(파일·NAS) + _apply_shared_config(창·활성 변환표). 창은 띄우지 않고 문제를
        self.shared_config_problem에 남깁니다 (창 표시 후 resolve_shared_config_problem이 알림).
        읽기에 실패해도 공유 파일을 기본값으로 덮어쓰지 않습니다. 시작할 때는 start_shared_config_load(백그라운드).
        """
        self._apply_shared_config(SharedConfigState())  # 먼저 빈 상태로 (예상 못 한 예외가 나도 이전 값이 남지 않게)
        self._apply_shared_config(shared_config_load.gather_shared_config())

    def _first_work_item(self):
        """작품 목록의 첫 항목: 불러오는 동안은 "공유 설정 불러오는 중…", 그 뒤는 "작품선택" (골라도 아무 일 없음)."""
        return LOADING_WORK_ITEM if getattr(self, "shared_config_loading", False) else WORK_PLACEHOLDER

    def set_shared_config_loading_state(self):
        """공유 설정을 아직 읽지 않은 빈 '불러오는 중' 상태 (파일·NAS 접근 없음). start_shared_config_load가 채움."""
        self._apply_shared_config(SharedConfigState())
        self.shared_config_loading = True

    def _apply_shared_config(self, state):
        """(GUI 스레드) gather_shared_config 결과를 창에 넣고 (Windows) 이 PC의 변환표를 활성화합니다."""
        self.work_paths = state.work_paths
        self.shared_config_problem = state.shared_config_problem
        self.path_map_problem = state.path_map_problem
        self.config_dir_candidates = state.config_dir_candidates
        self.config_dir_search_failed = state.config_dir_search_failed
        self.config_dir_search_problems = state.config_dir_search_problems
        self.work_paths_config_dir = state.config_dir
        if state.config_dir is None:
            self.work_paths_file = None
            self.work_paths_password_file = None
        else:
            self.work_paths_file = os.path.join(state.config_dir, shared_config.WORK_PATHS_FILENAME)
            self.work_paths_password_file = os.path.join(state.config_dir, shared_config.PASSWORD_FILENAME)
        if state.activate_path_map:
            paths.activate(state.path_map)
        if state.mount_map is not None:
            paths.activate_mount_map(state.mount_map)

    def start_shared_config_load(self):
        """(창 표시 후) 공유 설정을 백그라운드 스레드에서 읽고, 끝나면 GUI 스레드에서 넣은 뒤 문제를 알립니다.

        읽는 동안(NAS가 느리거나 서버가 꺼진 드라이브가 있으면 수십 초) 창은 그대로 쓸 수 있고, 작품 경로 관리·
        공유 설정 폴더 변경은 안내만 합니다.
        """
        if self._shared_config_closed:
            timing_log.startup("창이 이미 닫혀 공유 설정을 불러오지 않음")
            return
        if self._shared_config_load is not None:
            raise RuntimeError("공유 설정을 이미 불러오는 중입니다 (start_shared_config_load를 두 번 부름)")
        self.shared_config_loading = True
        self.setWindowTitle(build_info.title_base() + LOADING_TITLE_SUFFIX)
        timing_log.startup("공유 설정 불러오기 시작 (백그라운드)")
        load = SharedConfigLoad()
        load.loaded.connect(self._on_shared_config_loaded)  # 창은 GUI 스레드 → 대기열을 거쳐 GUI 스레드에서 실행
        self._shared_config_load = load
        load.start()

    def _on_shared_config_loaded(self, state):
        """(GUI 스레드) 백그라운드에서 읽은 공유 설정을 넣고 작품 목록을 채운 뒤 문제를 알립니다.

        창이 닫힌 뒤에 온 결과는 버립니다 (활성 변환표도 바꾸지 않음).
        """
        self._shared_config_load = None  # 스레드 객체는 끝날 때까지 SharedConfigLoad._running이 붙잡음
        if self._shared_config_closed:
            timing_log.startup(f"공유 설정 불러오기 끝 ({state.elapsed:.2f}초) — 창이 이미 닫혀 결과를 버림")
            return
        if QThread.currentThread() is not QApplication.instance().thread():
            raise RuntimeError("공유 설정 결과를 GUI 스레드가 아닌 곳에서 넣으려 했습니다")
        self._apply_shared_config(state)
        self.shared_config_loading = False
        self.shared_config_load_seconds = state.elapsed
        self.reload_work_combo()
        problem = "있음" if (state.shared_config_problem or state.path_map_problem) else "없음"
        timing_log.startup(
            f"공유 설정 불러오기 끝 ({state.elapsed:.2f}초): 설정 폴더 {state.config_dir or '없음'}, "
            f"작품 {len(state.work_paths)}개, 문제 {problem}"
        )
        self.resolve_shared_config_problem(works_not_opening=state.works_not_opening)
        # 새 버전 확인: 공유 설정(NAS의 updates 폴더 위치)을 안 뒤 처음 (뒤 스레드), 그 뒤 3시간마다 — PlayerUpdateMixin
        self.start_update_check(manual=False)

    def wait_for_shared_config_load(self, timeout_ms):
        """(창을 닫을 때) 실행 중인 공유 설정 불러오기를 timeout_ms까지만 기다립니다 → 끝났으면 True.

        끝나지 않으면(NAS 응답 대기 등) 로그만 남기고 False — 스레드는 SharedConfigLoad._running이 끝날 때까지
        붙잡고 있어 파괴되지 않고, 늦게 온 결과는 _on_shared_config_loaded가 버립니다.
        """
        load = self._shared_config_load
        if load is None or not load.isRunning():
            return True
        timing_log.log("닫기", "공유 설정 불러오기가 끝나기를 기다리는 중…")
        if load.wait(timeout_ms):
            timing_log.log("닫기", "공유 설정 불러오기 끝남")
            return True
        timing_log.log("닫기", f"공유 설정 불러오기가 {timeout_ms / 1000:g}초 안에 끝나지 않았습니다 — "
                             "결과는 버리고 계속 닫습니다 (NAS 응답을 기다리는 중일 수 있음)")
        return False

    def _shared_config_busy(self):
        """공유 설정을 불러오는 중이면 안내하고 True (반쯤 읽은 상태로는 아무것도 하지 않음)."""
        if getattr(self, "shared_config_loading", False):
            QMessageBox.information(self, "공유 설정", LOADING_NOTICE)
            return True
        return False

    def _update_shared_config_title(self):
        if getattr(self, "shared_config_loading", False):
            self.setWindowTitle(build_info.title_base() + LOADING_TITLE_SUFFIX)
            return
        title = build_info.title_base()  # 빌드된 앱은 "Yeson Checker 1.1.0", 소스 실행은 "Yeson Checker"
        if self.shared_config_problem:
            title += " — 공유 설정 오류 (작품 목록 없음)"
        if getattr(self, "path_map_problem", None):
            title += " — 변환표 오류 (작품 경로 관리에서 자동 설정)" if paths.IS_WINDOWS else " — 변환표 오류"
        self.setWindowTitle(title)

    def resolve_shared_config_problem(self, works_not_opening=None):
        """창 표시 후 공유 설정 문제를 알립니다.

        Windows: 설정 폴더를 못 찾았으면 고르게 하고(찾은 후보가 여럿이면 그 목록에서), 변환표가 없거나
        열리지 않는 작품이 있으면 연결된 드라이브로 변환표 자동 설정을 제안합니다.
        works_not_opening: 시작할 때 백그라운드에서 미리 계산한 '열리지 않는 작품' (None이면 여기서 확인).
        """
        if self.shared_config_problem and paths.IS_WINDOWS and not shared_config.is_valid_config_dir(self.work_paths_config_dir):
            if self.config_dir_candidates:
                picked = self._pick_config_dir_candidate()
            else:
                reason = self.shared_config_problem
                if self.config_dir_search_failed:
                    reason = "연결된 네트워크 드라이브에서 공유 설정 폴더를 찾지 못했습니다.\n\n" + reason
                reason += self._config_dir_search_problems_text()
                picked = self.choose_shared_config_dir(reason)
            if picked:
                return  # _use_config_dir가 문제 알림·변환표 자동 설정까지 처리함
        if self.shared_config_problem:
            QMessageBox.critical(
                self,
                "공유 설정 오류",
                f"{self._shared_config_problem_text()}\n\n작품 목록 없이 계속합니다. 파일 직접 열기와 드래그는 쓸 수 있습니다.",
            )
            return
        if not paths.IS_WINDOWS and self.path_map_problem:
            # (Mac) path_map.json을 읽지 못해 공유 설정의 앞부분을 /<이름>으로만 정함 (_load_mac_mount_map)
            QMessageBox.warning(self, "변환표 오류", self.path_map_problem)
            return
        self._offer_path_map_setup(works_not_opening)

    def _config_dir_search_problems_text(self):
        """공유 설정 폴더 자동 찾기 중 확인하지 못한 곳 (폴더를 고르게 할 때 덧붙임)."""
        problems = getattr(self, "config_dir_search_problems", None)
        if not problems:
            return ""
        return "\n\n확인하지 못한 곳:\n" + "\n".join(problems)

    def _shared_config_problem_text(self):
        """공유 설정 오류 창에 보일 내용: 공유 설정 문제 + (함께 있으면) 변환표 문제."""
        message = self.shared_config_problem
        if self.path_map_problem:
            message += f"\n\n{self.path_map_problem}"
        return message

    def choose_shared_config_dir(self, reason=None):
        """(Windows) 공유 설정 폴더를 고르게 하고 PC별 설정에 저장합니다. 골랐으면 True.

        네트워크 드라이브·UNC 폴더, 또는 실제 위치가 UNC인 로컬 링크(Harmony용 C:\\USA_DB 아래)를 고를 수 있음.
        """
        if self._shared_config_busy():
            return False
        if reason:
            QMessageBox.information(
                self,
                "공유 설정 폴더 선택",
                f"{reason}\n\n작품 경로 설정(work_paths.json)이 들어 있는 공유 설정 폴더(.yesoncheck)를 골라 주세요.",
            )
        while True:
            folder = QFileDialog.getExistingDirectory(self, "공유 설정 폴더(.yesoncheck) 선택")
            if not folder:
                return False
            try:
                config_dir = config_dir_from_chosen_folder(folder)
                shared_config.validate_config_dir(config_dir)
            except (paths.PathMapError, shared_config.SharedConfigError) as exc:
                QMessageBox.warning(self, "다른 폴더를 고르세요", str(exc))
                continue
            return self._use_config_dir(config_dir)

    def _use_config_dir(self, config_dir):
        """(Windows) 고른 공유 설정 폴더를 PC별 설정에 저장하고 다시 읽습니다. 저장했으면 True."""
        try:
            shared_config.save_local_settings({"config_dir": config_dir})
        except (shared_config.SharedConfigError, OSError) as exc:
            QMessageBox.critical(self, "PC별 설정 저장 실패", f"{exc}\n\n{traceback.format_exc()}")
            return False
        self.setup_shared_config()
        self.reload_work_combo()
        if self.shared_config_problem:
            QMessageBox.critical(self, "공유 설정 오류", self._shared_config_problem_text())
        else:
            self._offer_path_map_setup()
        return True

    def _pick_config_dir_candidate(self):
        """(Windows) 연결된 드라이브에서 찾은 공유 설정 폴더가 여럿일 때 고르게 합니다. 골랐으면 True."""
        manual = "직접 고르기..."
        item, ok = QInputDialog.getItem(
            self,
            "공유 설정 폴더 선택",
            "연결된 네트워크 드라이브에서 공유 설정 폴더를 여러 개 찾았습니다. 쓸 폴더를 고르세요:"
            + self._config_dir_search_problems_text(),
            list(self.config_dir_candidates) + [manual],
            0,
            False,
        )
        if not ok:
            return False
        if item == manual:
            return self.choose_shared_config_dir()
        return self._use_config_dir(item)

    def _works_not_opening(self):
        """(Windows) 이 PC에서 열리지 않는 작품 목록 ['작품: 이유'] (활성 변환표로, 이 스레드에서 바로 확인).

        GUI 스레드에서 공유 루트마다 최대 SHARE_PROBE_TIMEOUT_S초를 기다릴 수 있어 그동안 대기 커서."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return shared_config_load.list_works_not_opening(self.work_paths, paths.to_native)
        finally:
            QApplication.restoreOverrideCursor()

    def _offer_path_map_setup(self, works_not_opening=None):
        """(Windows) 변환표가 없거나 열리지 않는 작품이 있으면 변환표 자동 설정을 제안합니다.

        works_not_opening: 시작할 때 백그라운드에서 미리 계산한 목록 (None이면 여기서 확인).
        """
        if not paths.IS_WINDOWS:
            return
        if self.path_map_problem:
            needed = True
        elif works_not_opening is not None:
            needed = bool(works_not_opening)
        else:
            needed = bool(self._works_not_opening())
        if needed:
            self.auto_setup_path_map(ask_password=True, startup=True)

    def _report_path_map_problem(self, parent, note=None):
        """(Windows, startup) 저장 없이 끝날 때 변환표 문제를 한 번만 알립니다 (호출하는 쪽에서 self.path_map_problem을 확인)."""
        message = self.path_map_problem
        if note:
            message = f"{message}\n\n{note}"
        QMessageBox.critical(parent, "변환표 오류", message)

    def auto_setup_path_map(self, ask_password, startup=False, parent=None):
        """(Windows) 연결된 네트워크 드라이브로 변환표 짝을 찾아 확인 창을 띄우고, 승인되면 path_map.json에 합쳐 저장합니다.

        startup이면 기존 변환표에 더할 것이 없을 때 창을 띄우지 않고 변환표 문제만 알립니다(저장 없이 끝나는 모든
        경로에서 한 번만). 저장했으면 True(다시 읽기에 실패해도 저장은 된 것이므로 True이며, 공유 설정 오류를 따로 알립니다).

        확인 창·비밀번호는 몇 분이 걸릴 수 있으므로, 저장 직전에 path_map.json을 다시 읽어 그 내용에 합칩니다
        (그 사이 다른 PC가 쓴 항목을 지우지 않도록, 백업 여부도 다시 읽은 내용으로 정함).
        """
        parent = parent or self
        config_dir = self.work_paths_config_dir
        map_file = os.path.join(config_dir, paths.PATH_MAP_FILENAME)

        def read_map_file():
            """→ (existing, existing_error) 또는 읽지 못하면 오류 창을 띄우고 None."""
            try:
                return path_map_setup.read_existing(config_dir)
            except OSError as exc:
                QMessageBox.critical(parent, "변환표를 읽지 못함", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")
                return None

        def report_save_failure(exc):
            QMessageBox.critical(parent, "변환표 저장 실패", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")

        read = read_map_file()
        if read is None:
            return False
        existing, existing_error = read
        shares, share_problems = path_map_setup.available_shares()  # 네트워크 드라이브 + 시스템 드라이브의 UNC 링크
        progress = QProgressDialog("연결된 네트워크 드라이브에서 작품 폴더를 찾는 중…", "취소", 0, 100, parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        progress.setValue(0)  # 0.5초 뒤 저절로 보이게 — 응답 없는 공유 루트를 기다리는 동안에도 '취소'를 누를 수 있게

        def on_progress(done, total):
            progress.setValue(int(done * 100 / total))
            QApplication.processEvents()
            return not progress.wasCanceled()

        def on_wait():
            # 공유 루트가 응답하기를 기다리는 동안(최대 SHARE_PROBE_TIMEOUT_S초): 진행 창을 그리고 취소를 받음
            QApplication.processEvents()
            return not progress.wasCanceled()

        timing_log.log("변환표 자동 설정", f"작품 {len(self.work_paths)}개의 폴더를 공유 {len(shares)}개에서 찾는 중…")
        started = time.perf_counter()
        try:
            proposal = path_map_setup.propose_mapping(self.work_paths, shares, progress=on_progress, on_wait=on_wait)
            timing_log.log("변환표 자동 설정", f"찾기 끝 ({timing_log.since(started)}): 짝 {len(proposal.pairs)}개")
        except path_map_setup.SetupCancelled:
            timing_log.log("변환표 자동 설정", f"찾기 취소됨 ({timing_log.since(started)})")
            if startup and self.path_map_problem and not self._closing_for_update:
                self._report_path_map_problem(parent)
            return False
        finally:
            progress.close()
            progress.deleteLater()
        if self._closing_for_update:  # 찾는 동안 다른 창의 업데이트가 이 창을 닫음 → 확인 창·알림 없이 끝
            timing_log.log("변환표 자동 설정", "창을 닫는 중이라 저장하지 않음")
            return False
        proposal.share_problems = share_problems + proposal.share_problems

        if startup and not path_map_setup.has_additions(existing, proposal):
            if self.path_map_problem:
                self._report_path_map_problem(
                    parent, note="연결된 네트워크 드라이브에서 새로 찾은 짝이 없습니다. NAS 드라이브 연결을 확인하세요.",
                )
            return False
        _ok, rejected = path_map_setup.split_mergeable(existing, proposal.ordered_default_choices())
        blocked = {mac_prefix: reason for mac_prefix, _unc, reason in rejected}
        dialog = PathMapSetupDialog(proposal, existing_error, parent, blocked=blocked)
        if dialog.exec_() != QDialog.Accepted:
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        chosen = dialog.chosen()
        try:
            path_map_setup.merge_path_map(existing, chosen)  # 비밀번호를 묻기 전에: 합칠 수 없는 짝을 골랐으면 여기서 알림
        except paths.PathMapError as exc:
            report_save_failure(exc)
            return False
        if ask_password and not self._confirm_work_paths_password(parent):
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        read = read_map_file()  # 확인 창·비밀번호 사이에 다른 PC가 바꿨을 수 있음 → 저장 직전 내용에 합침
        if read is None:
            return False
        fresh, fresh_error = read
        try:
            data = path_map_setup.merge_path_map(fresh, chosen)
            backup = path_map_setup.save_path_map(config_dir, data, backup_existing=fresh_error is not None)
        except (paths.PathMapError, OSError) as exc:
            report_save_failure(exc)
            return False

        self.setup_shared_config()
        self.reload_work_combo()
        message = f"변환표를 저장했습니다: {map_file}"
        if backup:
            message += f"\n원래 파일은 {backup}으로 보관했습니다."
        if self.shared_config_problem:
            # 변환표는 저장됐지만 공유 설정을 다시 읽다가 문제가 생김 (예: NAS 연결 끊김) — 저장은 됐다고 알림
            QMessageBox.critical(
                parent, "공유 설정 오류",
                f"{message}\n\n하지만 공유 설정을 다시 읽지 못했습니다:\n{self.shared_config_problem}",
            )
            return True
        broken = self._works_not_opening()
        if broken:
            QMessageBox.warning(parent, "변환표 저장됨 — 열리지 않는 작품", message + "\n\n아직 열리지 않는 작품:\n" + "\n".join(broken))
        else:
            QMessageBox.information(parent, "변환표 저장됨", message)
        return True

    def reload_work_combo(self):
        """작품 콤보박스를 self.work_paths로 다시 채웁니다."""
        self.workComboBox.blockSignals(True)
        self.workComboBox.clear()
        self.workComboBox.addItem(self._first_work_item())
        for work_name in sorted(self.work_paths.keys()):
            self.workComboBox.addItem(work_name)
        self.workComboBox.blockSignals(False)
        self._update_shared_config_title()
        self.update_season_list()

    def save_work_paths(self, parent=None):
        """작품 경로를 공유 파일에 저장합니다. 실패하면 오류 창을 띄우고 False."""
        try:
            shared_config.write_work_paths(self.work_paths_file, self.work_paths)
            return True
        except OSError:
            QMessageBox.critical(parent or self, "작품 경로 저장 실패", f"{self.work_paths_file}\n\n{traceback.format_exc()}")
            return False

    def hash_password(self, password):
        """비밀번호를 해시화합니다."""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def load_password_hash(self):
        """저장된 비밀번호 해시. 파일이 없으면 None(최초 설정). 읽기 실패는 예외로 올립니다."""
        if not os.path.exists(self.work_paths_password_file):
            return None
        with open(self.work_paths_password_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('password_hash', None)

    def save_password_hash(self, password_hash):
        """비밀번호 해시를 저장합니다 (공유 설정 폴더는 이미 있어야 함). 실패는 예외로 올립니다."""
        with open(self.work_paths_password_file, 'w', encoding='utf-8') as f:
            json.dump({'password_hash': password_hash}, f, ensure_ascii=False, indent=2)

    def verify_password(self, password):
        """비밀번호를 확인합니다."""
        stored_hash = self.load_password_hash()
        if stored_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            return True
        return self.hash_password(password) == stored_hash

    def set_password(self, password):
        """비밀번호를 설정합니다."""
        password_hash = self.hash_password(password)
        self.save_password_hash(password_hash)

    def get_work_path(self, work_name):
        """작품 경로를 이 PC에서 여는 경로로 돌려줍니다 (Windows: 변환표로 UNC 변환, Mac: 공유를 제자리가 아닌 곳에 붙인
        Mac은 그곳 — mac_mounts).

        변환하지 못하거나 폴더가 없으면 오류 창을 한 번 띄우고 ""를 돌려줍니다.
        """
        stored = self.work_paths.get(work_name, "")
        if not stored:
            return ""
        try:
            native = paths.to_native(stored)
        except paths.PathMapError as exc:
            self._report_work_path_problem(f"작품 '{work_name}'의 경로를 이 PC 경로로 바꿀 수 없습니다.\n\n{exc}")
            return ""
        if paths.IS_WINDOWS and not os.path.isdir(native):
            self._report_work_path_problem(
                f"작품 '{work_name}' 폴더를 열 수 없습니다.\n\n이 PC 경로: {native}\n공유 설정 경로: {stored}\n\n"
                "NAS 연결과 path_map.json을 확인하세요."
            )
            return ""
        if not paths.IS_WINDOWS and not os.path.isdir(native):
            # (Mac) 빈 시즌 목록만 보이지 않게: 어디를 찾아봤는지(이 Mac에서 공유가 붙은 곳)와 함께 알림
            self._report_work_path_problem(
                f"작품 '{work_name}' 폴더를 열 수 없습니다.\n\n이 Mac 경로: {native}\n공유 설정 경로: {stored}\n\n"
                f"{paths.describe_mac_path(stored)}\n\nNAS 연결을 확인하세요."
            )
            return ""
        return native

    def _report_work_path_problem(self, message):
        """작품 하나를 고를 때 시즌·job·목록이 각각 같은 경로를 물으므로 같은 오류는 한 번만 보여 줍니다."""
        shown = self.__dict__.setdefault("_work_path_problems_shown", set())
        if message in shown:
            return
        shown.add(message)
        QMessageBox.critical(self, "작품 경로 오류", message)

    def _stored_work_path_or_warn(self, folder_path, parent):
        """고른 폴더를 공유 설정에 저장할 Mac 경로로 바꿉니다. 못 바꾸면 오류 창을 띄우고 None."""
        try:
            return paths.to_canonical(folder_path)
        except paths.PathMapError as exc:
            QMessageBox.critical(parent, "경로를 저장할 수 없음", f"고른 폴더를 공유 설정에 저장할 경로로 바꾸지 못했습니다.\n\n{exc}")
            return None

    def _refresh_work_path_table(self, table):
        table.clear()
        for work_name, path in sorted(self.work_paths.items()):
            text = f"{work_name}: {path}"
            if paths.IS_WINDOWS:
                try:
                    text += f"\n    → {paths.to_native(path)}"
                except paths.PathMapError:
                    text += "\n    → 변환표에 없음 (path_map.json 확인)"
            else:
                # (Mac) 공유를 다른 곳에 붙인 Mac에서만 이 Mac에서 여는 경로를 덧붙임 (같으면 예전처럼 한 줄)
                try:
                    native = paths.to_native(path)
                except paths.PathMapError:
                    text += "\n    → 이 Mac에서 열 곳을 정하지 못함 (맞는 공유가 여럿 — 시작 로그의 [공유] 줄 확인)"
                else:
                    if native != path:
                        text += f"\n    → {native}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, work_name)
            table.addItem(item)

    def _confirm_work_paths_password(self, parent=None):
        """작품 경로 관리 비밀번호를 확인합니다 (파일이 없으면 최초 설정). 확인되면 True. 문제는 창으로 알립니다."""
        parent = parent or self
        try:
            password_hash = self.load_password_hash()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(parent, "비밀번호 파일 오류", f"비밀번호 파일을 읽지 못했습니다:\n{self.work_paths_password_file}\n\n{exc}")
            return False

        if password_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            password, ok = QInputDialog.getText(
                parent,
                "비밀번호 설정",
                "작품 경로 관리를 위한 비밀번호를 설정하세요:\n(처음 한 번만 설정하면 됩니다)",
                echo=QLineEdit.Password
            )
            if not ok or not password:
                return False

            password_confirm, ok = QInputDialog.getText(
                parent,
                "비밀번호 확인",
                "비밀번호를 다시 입력하세요:",
                echo=QLineEdit.Password
            )
            if not ok:
                return False

            if password != password_confirm:
                QMessageBox.warning(parent, "오류", "비밀번호가 일치하지 않습니다.")
                return False

            try:
                self.set_password(password)
            except OSError as exc:
                QMessageBox.critical(parent, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
                return False
            QMessageBox.information(parent, "설정 완료", "비밀번호가 설정되었습니다.")
            return True

        # 비밀번호 입력 요청
        password, ok = QInputDialog.getText(
            parent,
            "비밀번호 입력",
            "작품 경로 관리를 위해 비밀번호를 입력하세요:",
            echo=QLineEdit.Password
        )
        if not ok:
            return False
        if not self.verify_password(password):
            QMessageBox.warning(parent, "오류", "비밀번호가 올바르지 않습니다.")
            return False
        return True

    def manage_work_paths(self):
        """작품 경로 관리 다이얼로그를 표시합니다."""
        if self._shared_config_busy():
            return
        # 공유 설정에 문제가 있으면 관리 금지 (깨진 파일을 빈 목록으로 덮어쓰거나 새 비밀번호를 받지 않도록)
        if self.shared_config_problem or self.work_paths_config_dir is None:
            QMessageBox.warning(
                self, "작품 경로 관리",
                f"공유 설정에 문제가 있어 작품 경로를 관리할 수 없습니다.\n\n{self.shared_config_problem or '공유 설정 폴더 없음'}",
            )
            return
        if not self._confirm_work_paths_password():
            return

        # 비밀번호 확인 후 다이얼로그 표시
        dialog = QDialog(self)
        dialog.setWindowTitle("작품 경로 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(700, 500)
        
        # 다크 테마 스타일 적용
        dialog.setStyleSheet("""
QDialog {
    background: #232323;
    color: #e0e0e0;
}
QLabel {
    color: #e0e0e0;
    background: transparent;
}
QPushButton {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    color: #fafafa;
    font-weight: 500;
    padding: 8px 16px;
}
QPushButton:hover {
    background: #353535;
    border: 1px solid #ff9900;
    color: #ff9900;
}
QPushButton:pressed {
    background: #1a1a1a;
    border: 1px solid #ff9900;
}
QListWidget {
    background: #232323;
    border: 1px solid #444;
    color: #fafafa;
    selection-background-color: #444;
    selection-color: #ff9900;
    alternate-background-color: #2a2a2a;
}
QListWidget::item:selected {
    background: #444;
    color: #ff9900;
}
QListWidget::item:hover {
    background: #353535;
}
QScrollBar:vertical {
    background: #232323;
    border: 1px solid #444;
    border-radius: 6px;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #ff9900;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
""")
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("작품별 경로를 관리할 수 있습니다. 경로를 수정하거나 작품을 추가/삭제할 수 있습니다.")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # 작품 경로 리스트
        table = QListWidget()
        table.setAlternatingRowColors(True)
        
        self._refresh_work_path_table(table)

        layout.addWidget(table)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 추가 버튼
        add_button = QPushButton("작품 추가")
        add_button.clicked.connect(lambda: self.add_work_path(table, dialog))
        button_layout.addWidget(add_button)
        
        # 수정 버튼
        edit_button = QPushButton("경로 수정")
        edit_button.clicked.connect(lambda: self.edit_work_path(table, dialog))
        button_layout.addWidget(edit_button)
        
        # 삭제 버튼
        delete_button = QPushButton("작품 삭제")
        delete_button.clicked.connect(lambda: self.delete_work_path(table, dialog))
        button_layout.addWidget(delete_button)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # 비밀번호 변경 버튼 레이아웃
        password_layout = QHBoxLayout()
        password_button = QPushButton("비밀번호 변경")
        password_button.clicked.connect(lambda: self.change_password(dialog))
        password_layout.addWidget(password_button)
        if paths.IS_WINDOWS:
            auto_button = QPushButton("변환표 자동 설정")
            auto_button.setToolTip(
                "이 PC에 연결된 네트워크 드라이브에서 작품 폴더가 열리는 곳을 찾아 path_map.json을 만들거나 보충합니다."
            )

            def on_auto_setup():
                self.auto_setup_path_map(ask_password=False, parent=dialog)
                if self.shared_config_problem:
                    # 다시 읽기에 실패해 work_paths가 빈 목록일 수 있음 — 관리 창을 닫아 그대로 덮어쓰지 않게 함
                    dialog.reject()
                else:
                    self._refresh_work_path_table(table)

            auto_button.clicked.connect(on_auto_setup)
            password_layout.addWidget(auto_button)
        password_layout.addStretch()
        layout.addLayout(password_layout)
        
        dialog.setLayout(layout)
        
        dialog.exec_()

    def add_work_path(self, table, dialog):
        """새로운 작품 경로를 추가합니다."""
        work_name, ok = QInputDialog.getText(
            dialog, 
            "작품 추가", 
            "작품 이름을 입력하세요:",
            text=""
        )
        if not ok or not work_name:
            return
        
        if work_name in self.work_paths:
            QMessageBox.warning(dialog, "오류", f"'{work_name}' 작품은 이미 존재합니다.")
            return
        
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택")
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            del self.work_paths[work_name]
            return

        # 콤보박스에도 추가
        if work_name not in [self.workComboBox.itemText(i) for i in range(self.workComboBox.count())]:
            self.workComboBox.addItem(work_name)
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "추가 완료", f"'{work_name}' 작품이 추가되었습니다.")

    def edit_work_path(self, table, dialog):
        """선택된 작품의 경로를 수정합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "수정할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        try:
            start_dir = paths.to_native(self.work_paths.get(work_name, ""))
        except paths.PathMapError:
            start_dir = ""  # 선택 창의 시작 위치만 정하는 값 (고른 경로는 저장 전에 다시 검사함)
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택", start_dir)
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        previous = self.work_paths.get(work_name)
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            self.work_paths[work_name] = previous
            return
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "수정 완료", f"'{work_name}' 작품의 경로가 수정되었습니다.")

    def delete_work_path(self, table, dialog):
        """선택된 작품을 삭제합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "삭제할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        reply = QMessageBox.question(
            dialog,
            "작품 삭제",
            f"'{work_name}' 작품을 삭제하시겠습니까?\n\n경로: {self.work_paths.get(work_name, '')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            previous = self.work_paths.pop(work_name, None)
            if not self.save_work_paths(dialog):
                if previous is not None:
                    self.work_paths[work_name] = previous
                return
            index = self.workComboBox.findText(work_name)
            if index >= 0:
                self.workComboBox.removeItem(index)
            self._refresh_work_path_table(table)
            QMessageBox.information(dialog, "삭제 완료", f"'{work_name}' 작품이 삭제되었습니다.")

    def change_password(self, dialog):
        """비밀번호를 변경합니다."""
        # 현재 비밀번호 확인
        current_password, ok = QInputDialog.getText(
            dialog,
            "현재 비밀번호 확인",
            "현재 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if not self.verify_password(current_password):
            QMessageBox.warning(dialog, "오류", "현재 비밀번호가 올바르지 않습니다.")
            return
        
        # 새 비밀번호 입력
        new_password, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 설정",
            "새 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok or not new_password:
            return
        
        # 새 비밀번호 확인
        new_password_confirm, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 확인",
            "새 비밀번호를 다시 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if new_password != new_password_confirm:
            QMessageBox.warning(dialog, "오류", "새 비밀번호가 일치하지 않습니다.")
            return
        
        # 비밀번호 변경
        try:
            self.set_password(new_password)
        except OSError as exc:
            QMessageBox.critical(dialog, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
            return
        QMessageBox.information(dialog, "변경 완료", "비밀번호가 변경되었습니다.")
