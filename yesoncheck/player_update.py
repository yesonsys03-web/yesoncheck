"""업데이트 확인 일정·결과 보이기 (PlayerUpdateMixin): 새 버전 알림 띠(update_banner)와 Help → '업데이트 확인…'.

확인(updates.check — NAS·GitHub의 latest.json 읽기)은 언제나 뒤 스레드(UpdateCheck)에서 한다. 자동 확인은 공유 설정을
불러온 뒤(_on_shared_config_loaded) 한 번, 그 뒤 켜 둔 동안 3시간마다. 소스 실행(build_info.current()가 None)은
확인하지 않는다 — 자동 확인은 스레드도 만들지 않고, 메뉴는 안내만.

결과 보이기 (설계 4-4·5-1):
- 새 버전(offer): 알림 띠. '나중에'를 누른 버전과 같거나 낮은 번호는 이번 실행 동안 다시 보이지 않음(더 큰 번호는 보임).
  Help → 업데이트 확인…은 숨긴 버전도 다시 보임 (업데이트를 시작하는 곳은 띠뿐). 받는 중(띠가 진행을 보임)에는 결과를
  기록에만 남기고 update_offer와 띠를 그대로 둠.
- 소스마다 읽은 결과는 업데이트 기록(update_install.log — Mac도 파일)에 한 줄씩. 예상된 실패(expected_problem)는
  자동 확인이면 기록에만.
- 오류(error): 자동 확인은 창 — 한 실행에 같은 문제는 한 번 ((소스, 첫 줄). 트레이스백은 첫 줄이 늘 같아 마지막 줄).
- 수동 확인: 언제나 결과 창 — 소스마다 찾은 버전·예상된 문제·오류 전부 (오류가 있으면 경고 창).
"""

import functools
import sys
import traceback

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox

from yesoncheck import build_info, timing_log, update_install, updates
from yesoncheck.player_base import release_worker

CHECK_TITLE = "업데이트 확인"
CHECK_FAILED_TITLE = "업데이트 확인 실패"
SOURCE_RUN_NOTICE = "소스에서 실행 중 — 업데이트하지 않음"
NOTES_TITLE = "바뀐 점 — {version}"
NO_NOTES = "(바뀐 점이 적혀 있지 않습니다)"
_TRACEBACK_HEAD = "Traceback (most recent call last):"
_UNEXPECTED_SOURCE = "확인"  # updates.check 자체가 예외를 올림 (소스 하나의 문제가 아님)


class UpdateCheck(QThread):
    """updates.check를 GUI 밖에서 실행하는 스레드 (위젯은 건드리지 않음). 결과(CheckResult)는 done 신호로, 예상 못 한
    예외는 트레이스백째 failed 신호로 GUI 스레드에 (삼키지 않음 — 로그(stderr)에도 남김).

    SharedConfigLoad처럼 부모 없이 만들고(창이 지워질 때 함께 파괴되지 않게) 실행 중에는 _running에 붙잡아 둠: 실행 중인
    QThread가 파괴되면 "QThread: Destroyed while thread is still running"으로 프로세스가 중단됨. 끝나면(finished) 놓음.
    창을 닫을 때 실행 중이면 창이 release_worker로 넘김 (응답 없는 NAS — 앱이 끝나기 전에 정해진 시간까지 기다림).
    check: 확인 함수 (시험에서 바꿔 끼움, 기본 updates.check).
    """

    done = pyqtSignal(object)  # updates.CheckResult
    failed = pyqtSignal(str)  # 예상 못 한 예외의 트레이스백
    _running = set()

    def __init__(self, current, platform_key, config_dir, base_url, check=None):
        super().__init__()
        self._args = (current, platform_key, config_dir, base_url)
        self._check = check or updates.check
        self.finished.connect(self._forget)

    def start(self, *args):
        UpdateCheck._running.add(self)
        super().start(*args)

    def run(self):
        try:
            result = self._check(*self._args)
        except Exception:
            text = traceback.format_exc()
            print(f"[업데이트 확인] 예상치 못한 오류:\n{text}", file=sys.stderr, flush=True)
            self.failed.emit(text)
            return
        self.done.emit(result)

    def _forget(self):
        self.wait()  # finished는 스레드가 끝나기 직전에 옴 → 완전히 끝날 때까지 (곧 끝남)
        UpdateCheck._running.discard(self)


def _problem_key(text):
    """같은 문제인지 가리는 글: 첫 줄 — 트레이스백이면 마지막 줄(예외 종류와 글)."""
    lines = text.strip().splitlines() or [""]
    return lines[-1] if lines[0] == _TRACEBACK_HEAD else lines[0]


def _source_name(result):
    return f"{result.source} ({result.location})" if result.location else result.source


def _source_state(result, current):
    """결과 창·업데이트 기록의 한 소스 줄: 찾은 버전, 또는 예상된 문제·오류의 글 전부."""
    if result.manifest is not None:
        version = result.manifest.version
        if version > current:
            compared = "새 버전"
        elif version == current:
            compared = "지금 버전과 같음"
        else:
            compared = "지금보다 예전 버전"
        return f"{_source_name(result)}: {version} — {compared}"
    if result.expected_problem is not None:
        return f"{_source_name(result)}: 확인하지 못함 — {result.expected_problem}"
    return f"{_source_name(result)}: 오류 — {result.error}"


class PlayerUpdateMixin:
    """업데이트 확인 일정과 결과 (알림 띠·결과 창). update_offer: 지금 알리는 새 버전 (updates.Offer, 없으면 None)."""

    UPDATE_CHECK_INTERVAL_MS = 3 * 60 * 60 * 1000  # 자동 확인 간격 3시간

    def setup_updates(self):
        """(창을 만들 때, 알림 띠를 만든 뒤) 확인 상태·3시간 타이머·띠 버튼. 확인은 아직 시작하지 않음."""
        self.update_offer = None
        self.update_check_running = False
        self._update_check = None  # 실행 중인 UpdateCheck
        self._update_check_manual = False  # 실행 중인 확인이 끝나면 결과 창을 보임 (수동 확인)
        self._update_check_again = False  # 실행 중에 자동 확인을 부름 → 끝나면 한 번 더 (그때의 공유 설정 폴더로)
        self._update_check_current = None  # 실행 중인 확인의 지금 버전 (updates.Version)
        self._update_dismissed = None  # '나중에'를 누른 버전 (updates.Version) — 이 번호까지는 다시 보이지 않음
        self._update_errors_shown = set()  # 이번 실행에서 창으로 보인 오류 (소스, 첫 줄)
        self._update_closed = False  # 창이 닫힘 → 확인하지 않고, 늦게 온 결과는 버림
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(self.UPDATE_CHECK_INTERVAL_MS)
        self._update_check_timer.timeout.connect(functools.partial(self.start_update_check, manual=False))
        self.update_banner.notes_clicked.connect(self.show_update_notes)
        self.update_banner.later_clicked.connect(self.dismiss_update_offer)

    def start_update_check(self, manual: bool) -> None:
        """NAS·GitHub에서 새 버전을 뒤 스레드로 확인 (결과는 _on_update_checked). 바로 돌아옴.

        manual: Help → 업데이트 확인… — 결과 창을 언제나 보임. 이미 확인 중이면 새로 시작하지 않음: manual이면 그 확인이
        끝나기를 기다렸다 결과 창, 자동이면 그 확인이 끝난 뒤 한 번 더 (예: 공유 설정을 불러오기 전에 누른 수동 확인은
        NAS를 읽지 못함 — 불러온 뒤의 자동 확인을 건너뛰면 3시간 동안 NAS를 보지 않음). 자동 확인을 처음 부르면(공유
        설정을 불러온 뒤) 3시간 타이머도 시작. 소스 실행이면 확인하지 않음 (manual이면 안내 창).
        """
        if self._update_closed:
            return
        info = build_info.current()
        if info is None:
            if manual:
                QMessageBox.information(self, CHECK_TITLE, SOURCE_RUN_NOTICE)
            else:
                timing_log.log("업데이트", "소스에서 실행 중 — 자동 업데이트 확인 안 함")
            return
        if not manual and not self._update_check_timer.isActive():
            self._update_check_timer.start()
        if self.update_check_running:
            if manual:
                self._update_check_manual = True
            else:
                self._update_check_again = True
                update_install.log("업데이트 확인 (자동): 앞의 확인이 아직 끝나지 않음 — 끝나면 다시 확인")
            return
        current = updates.Version.parse(info.version)
        check = UpdateCheck(current, build_info.platform_key(), self.work_paths_config_dir, updates.github_base_url())
        check.done.connect(self._on_update_checked)  # 창은 GUI 스레드 → 대기열을 거쳐 GUI 스레드에서 실행
        check.failed.connect(self._on_update_check_failed)
        self._update_check = check
        self._update_check_manual = manual
        self._update_check_current = current
        self.update_check_running = True
        check.start()

    def _end_update_check(self):
        """확인이 끝남 → (수동 확인이었는지, 지금 버전, 끝나면 다시 확인할지). 결과를 받는 두 슬롯이 맨 먼저 부름 —
        GUI 스레드가 아니면 상태를 바꾸기 전에 RuntimeError (_on_shared_config_loaded처럼)."""
        if QThread.currentThread() is not QApplication.instance().thread():
            raise RuntimeError("업데이트 확인 결과를 GUI 스레드가 아닌 곳에서 받았습니다")
        ended = (self._update_check_manual, self._update_check_current, self._update_check_again)
        self._update_check = None
        self._update_check_manual = False
        self._update_check_current = None
        self._update_check_again = False
        self.update_check_running = False
        return ended

    def _on_update_checked(self, result):
        """(GUI 스레드) 확인 결과: 업데이트 기록에 소스마다 한 줄, 새 버전이면 알림 띠(받는 중이면 띠·update_offer를
        그대로 둠), 수동이면 결과 창, 자동이면 이번 실행에서 처음 본 오류만 창. 확인 중에 자동 확인을 불렀으면 한 번 더."""
        manual, current, again = self._end_update_check()
        if self._update_closed:
            return  # 창을 닫은 뒤 (release_worker가 신호를 막지만 이미 대기열에 들어간 결과)
        kind = "수동" if manual else "자동"
        for source_result in result.results:
            update_install.log(f"업데이트 확인 ({kind}) {_source_state(source_result, current)}")
        offer = result.offer
        if offer is None:
            update_install.log(f"업데이트 확인 ({kind}) → 새 버전 없음 (지금 {current})")
        else:
            update_install.log(f"업데이트 확인 ({kind}) → 새 버전 {offer.manifest.version} ({offer.result.source})")
        if self.update_banner.mode() == "progress":
            # 받는 중: 받고 있는 버전(update_offer)과 띠(받기 진행)는 그대로 — 이번 결과는 위의 기록에만
            update_install.log(f"업데이트 확인 ({kind}) 받는 중이라 알림 띠와 고른 버전은 그대로 둠")
        else:
            self.update_offer = offer
            self._show_update_offer(current, manual)
        if manual:
            self._show_update_check_report(result, current)
        else:
            self._show_new_update_errors(result.results)
        if again:
            self.start_update_check(manual=False)

    def _on_update_check_failed(self, text):
        """(GUI 스레드) updates.check가 예상 못 한 예외를 올림 → 트레이스백째 창 (자동은 같은 문제 한 번).
        확인 중에 자동 확인을 불렀으면 한 번 더."""
        manual, _current, again = self._end_update_check()
        if self._update_closed:
            return
        kind = "수동" if manual else "자동"
        update_install.log(f"업데이트 확인 ({kind}) 예상치 못한 오류:\n{text}")
        if self._first_time_update_error(_UNEXPECTED_SOURCE, text) or manual:
            QMessageBox.warning(self, CHECK_FAILED_TITLE, f"업데이트를 확인하다 예상치 못한 오류가 났습니다.\n\n{text}")
        if again:
            self.start_update_check(manual=False)

    def _show_update_offer(self, current, manual):
        """update_offer를 알림 띠에 (받는 중이 아닐 때만 부름): 새 버전이 없으면 알리던 것을 숨김.
        자동 확인은 '나중에'를 누른 번호까지는 보이지 않음, 수동 확인은 다시 보임."""
        banner = self.update_banner
        offer = self.update_offer
        if offer is None:
            if banner.mode() == "offer":
                banner.hide_banner()  # 알리던 새 버전을 이번에는 찾지 못함 (NAS·인터넷에 닿지 않음 등)
            return
        version = offer.manifest.version
        if manual:
            self._update_dismissed = None
        elif self._update_dismissed is not None and version <= self._update_dismissed:
            return
        banner.show_offer(str(version), str(current))

    def _first_time_update_error(self, source, text):
        """이번 실행에서 처음 보는 문제면 기억하고 True (같은 문제의 창은 한 번만)."""
        key = (source, _problem_key(text))
        if key in self._update_errors_shown:
            return False
        self._update_errors_shown.add(key)
        return True

    def _show_new_update_errors(self, results):
        """(자동 확인) 이번 실행에서 처음 본 오류만 창 하나에, 글 전부 (예상된 실패는 기록에만 — 창 없음)."""
        new = [r for r in results if r.error is not None and self._first_time_update_error(r.source, r.error)]
        if not new:
            return
        details = "\n\n".join(f"{_source_name(r)}:\n{r.error}" for r in new)
        QMessageBox.warning(self, CHECK_FAILED_TITLE, f"새 버전을 확인하다 문제가 생겼습니다.\n\n{details}")

    def _show_update_check_report(self, result, current):
        """(수동 확인) 소스마다 찾은 버전·예상된 문제·오류 전부 — 오류가 있으면 경고 창. 여기서 보인 오류는 자동 확인이
        다시 창으로 띄우지 않음."""
        lines = [f"지금 버전: {current}", ""]
        lines += [_source_state(r, current) for r in result.results]
        lines.append("")
        offer = result.offer
        if offer is not None:
            lines.append(f"새 버전 {offer.manifest.version}이 있습니다 ({offer.result.source}에서 받음). "
                         "창 위 알림 띠에서 '업데이트'를 누르세요.")
        elif all(r.manifest is not None for r in result.results):
            lines.append("지금 버전이 최신입니다.")
        else:
            lines.append("읽은 곳에서는 새 버전을 찾지 못했습니다.")
        errors = [r for r in result.results if r.error is not None]
        for r in errors:
            self._first_time_update_error(r.source, r.error)
        show = QMessageBox.warning if errors else QMessageBox.information
        show(self, CHECK_TITLE, "\n".join(lines))

    def _offered(self):
        """알림 띠가 알리는 새 버전 (update_offer). '바뀐 점'·'나중에'는 알릴 때만 보이므로 없으면 프로그램 오류 —
        조용히 넘기지 않고 올림 (앱의 오류 창으로)."""
        if self.update_offer is None:
            raise RuntimeError(
                f"알림 띠의 버튼을 눌렀는데 알리는 새 버전(update_offer)이 없습니다 (띠: {self.update_banner.mode()})"
            )
        return self.update_offer

    def dismiss_update_offer(self):
        """'나중에': 알린 버전은 이번 실행 동안 다시 보이지 않음 (더 큰 번호가 나오면 보임, 다음에 켜면 보임)."""
        self._update_dismissed = self._offered().manifest.version
        self.update_banner.hide_banner()

    def show_update_notes(self):
        """'바뀐 점': 알린 버전의 latest.json notes를 작은 창으로."""
        manifest = self._offered().manifest
        QMessageBox.information(self, NOTES_TITLE.format(version=manifest.version), manifest.notes or NO_NOTES)

    def stop_update_checks(self):
        """(창을 닫을 때) 3시간 타이머를 멈추고, 실행 중인 확인은 결과를 버린 채 끝날 때까지 붙잡아 둠 (release_worker —
        응답 없는 NAS를 읽는 중일 수 있음, 앱이 끝나기 전에 wait_for_released_workers가 정해진 시간까지 기다림)."""
        self._update_closed = True
        self._update_check_timer.stop()
        check, self._update_check = self._update_check, None
        self.update_check_running = False
        if check is not None:
            release_worker(check, "업데이트 확인")
            UpdateCheck._running.discard(check)  # 이제 release_worker가 붙잡음 (신호를 막아 finished로는 놓지 못함)
