"""업데이트 (PlayerUpdateMixin): 확인 일정·결과(새 버전 알림 띠 update_banner, Help → '업데이트 확인…'), '업데이트'를
누른 뒤의 받기·도우미에 넘기기, 다시 켜진 앱의 결과 알림.

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

'업데이트'를 누르면 (start_update, 설계 5-2) — 누른 때의 update_offer를 끝까지 씀 (그 뒤의 확인 결과가 바꾸지 않음):
1. (Mac) 바꿀 수 없는 위치(dmg 안·격리 위치)에서 켠 앱이면 "업데이트할 수 없음" 안내 창, 받지 않음.
2. 진행 중인 작업(running_jobs — 창 닫기가 멈추는 작업)이 있으면 멈추고 업데이트할지 물음. 작업은 넘긴 뒤 앱을 끝낼 때
   창 닫기가 멈춤 — 받다 실패·취소하면 그대로 이어짐. 받는 동안 새로 시작한 작업은 넘기기 전에 다시 물음.
3. 여유 공간 확인(update_install.NEEDED_BYTES) → 뒤 스레드(UpdateDownload)가 <state_dir>/downloads에 받기(크기·sha256),
   Mac은 이어서 dmg에서 새 앱을 준비("준비 중…"). 띠에 진행·[취소].
4. 다 되면 업데이트 기록(write_pending) → 도우미(launch_helper_mac/windows) → 창을 닫고 앱을 끝냄. 도우미를 띄우지
   못하면 기록을 지우고 실패 창, 앱은 그대로.
실패는 "업데이트 실패" 창(출처 NAS/GitHub·위치·이유 — 예상 못 한 예외는 트레이스백) 뒤 띠를 다시 그 알림으로. 다른 곳에서
저절로 받지 않음 — 다시 누르면 처음부터. 취소·창 닫기는 받던 것을 지우고 넘기지 않음. 단계마다 update_install.log.

다시 켜진 앱 (handle_update_startup — 창을 보인 뒤 한 번, 이 컴퓨터의 파일만): 기록의 목표 버전이면 "잘 켜짐" 표시를
남기고 띠에 잠깐 "{버전}로 업데이트했습니다", 예전 버전이 켜졌으면(도우미가 되돌림) "업데이트 실패" 창에 그 뒤의 기록
(도우미 출력 중 기록에 없는 것도 — 도우미가 기록을 쓰기 전에 실패한 이유).
"""

import functools
import os
import shutil
import sys
import threading
import traceback
from dataclasses import dataclass

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
UPDATE_FAILED_TITLE = "업데이트 실패"
CANNOT_UPDATE_TITLE = "업데이트할 수 없음"
BUSY_TITLE = "업데이트"
BUSY_QUESTION = "진행 중인 작업({jobs})을 멈추고 업데이트할까요?"
UPDATED_MESSAGE = "{version}로 업데이트했습니다"
DOWNLOAD_TEXT = "{version} 받는 중 ({source})… {done} / {total} MB"
STAGING_TEXT = "준비 중…"
CANCELLING_TEXT = "취소하는 중…"
DOWNLOADS_DIR_NAME = "downloads"  # <update_install.state_dir()>/downloads — 받은 설치 파일·dmg (한 번에 하나만 둠)


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


def download_text(version, source, done, total):
    """받는 중인 띠의 글: "1.1.1 받는 중 (NAS)… 120.0 / 730.0 MB"."""
    return DOWNLOAD_TEXT.format(version=version, source=source, done=f"{done / 1e6:,.1f}", total=f"{total / 1e6:,.1f}")


def remove_prepared(path):
    """받은 설치 파일·dmg 또는 준비한 앱(폴더)을 지움. 실패는 그대로 올림."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def empty_folder(folder):
    """folder를 (없으면 만들고) 비움 — 지난번에 받은 설치 파일, 앱이 받다 죽어 남은 .part."""
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        remove_prepared(os.path.join(folder, name))


def _log_update(line):
    """업데이트 기록에 한 줄 (update_install.log). 기록을 쓰지 못해도 그 뒤의 일(받기 스레드 놓기·앱 끝내기·실패 창)을
    멈추지 않음 — 그 줄과 쓰지 못한 이유(트레이스백)를 둘 다 stderr에 (삼키지 않음). 슬롯·받기 스레드에서 씀: 슬롯에서
    예외가 나가면 Mac(excepthook 없음)에서는 PyQt가 앱을 끝냄. 기록을 쓸 수 있는지는 start_update가 맨 처음에 확인함."""
    try:
        update_install.log(line)
    except Exception:
        print(f"[업데이트 기록] 이 줄을 쓰지 못함:\n{line}\n쓰지 못한 이유:\n{traceback.format_exc()}",
              file=sys.stderr, flush=True)


def _failure_text(exc):
    """실패 창·기록의 이유: UpdateError(예상한 문제 — 무엇이 왜인지 적혀 있음)는 그 글, 그 밖은 트레이스백.
    except 안에서 부름."""
    if isinstance(exc, update_install.UpdateError):
        return str(exc)
    return traceback.format_exc()


class UpdateDownload(QThread):
    """업데이트 파일을 GUI 밖에서 받는 스레드: 받기 폴더(dest_dir)를 비우고 update_install.download(크기·sha256 확인),
    Mac(app_path를 줌)이면 이어서 update_install.stage_mac으로 dmg에서 새 앱을 지금 앱 옆에 준비하고 dmg는 지움.
    위젯은 건드리지 않음.

    신호 (GUI 스레드로): progress(받은 바이트, 전체 바이트, 띠의 글 — 준비 중에는 전체 0 = 움직이는 막대), ready(Windows
    설치 파일 또는 Mac 준비한 앱의 경로), failed(UpdateError의 글, 예상 못 한 예외는 트레이스백), cancelled(). 넷 중
    마지막 하나(ready·failed·cancelled)는 run()의 맨 끝. 실패·취소는 run()이 업데이트 기록에 남김 (창을 닫아 신호가
    막혀도).

    cancel(): 멈추라고 알림 — 받기는 다음 조각에서 멈추고(.part를 지움), 중간에 멈출 수 없는 Mac 준비(hdiutil·ditto)는
    끝난 뒤 준비한 앱을 지움. 다 받은 뒤에 본 취소도 받은 것을 지우고 cancelled (넘기지 않음).

    UpdateCheck처럼 부모 없이 만들고 실행 중에는 _running에 붙잡아 둠. 창을 닫을 때 실행 중이면 cancel() 뒤 release_worker
    (stop_update_download).
    """

    progress = pyqtSignal("qint64", "qint64", str)  # 파일은 2 GiB 미만이지만 32비트 int의 끝에 가까움 → 64비트
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    _running = set()

    def __init__(self, location, entry, dest_dir, version, source, app_path=None):
        super().__init__()
        self._location = location  # NAS 경로 또는 URL (updates.asset_location)
        self._entry = entry  # updates.FileEntry
        self._dest_dir = dest_dir
        self._version = version
        self._source = source  # "NAS"·"GitHub" (띠의 글)
        self._app_path = app_path  # Mac: 지금 앱 번들 (그 옆에 새 앱을 준비), Windows: None
        self._cancel = threading.Event()
        self.finished.connect(self._forget)

    def start(self, *args):
        UpdateDownload._running.add(self)
        super().start(*args)

    def cancel(self):
        self._cancel.set()

    def is_cancelled(self):
        return self._cancel.is_set()

    def run(self):
        try:
            prepared = self._download_and_prepare()
        except update_install.Cancelled as exc:
            _log_update(f"업데이트 {self._version}: 받기 멈춤 — {exc} (받던 것은 지움)")
            self.cancelled.emit()
            return
        except Exception as exc:
            # 실패는 여기서 기록 — 창을 닫은 뒤(release_worker가 신호를 막음)에도 남게. 창 쪽은 이유를 다시 적지 않음
            text = _failure_text(exc)
            _log_update(f"업데이트 {self._version}: 받기 실패 ({self._source}: {self._location})\n{text}")
            self.failed.emit(text)
            return
        self.ready.emit(prepared)

    def _download_and_prepare(self):
        empty_folder(self._dest_dir)
        self._report(0)
        path = update_install.download(self._location, self._entry, self._dest_dir,
                                       lambda done, _total: self._report(done), self._cancel.is_set)
        if self._app_path is not None:
            self.progress.emit(0, 0, STAGING_TEXT)
            staged = update_install.stage_mac(path, self._app_path, self._version)
            os.remove(path)  # 새 앱을 꺼낸 dmg는 더 쓰지 않음
            path = staged
        if self._cancel.is_set():  # 받기를 끝낸 뒤·준비하는 동안 취소 (준비는 중간에 멈출 수 없음)
            remove_prepared(path)
            raise update_install.Cancelled("받은 뒤 취소되었습니다")
        return path

    def _report(self, done):
        total = self._entry.size
        self.progress.emit(done, total, download_text(self._version, self._source, done, total))

    def _forget(self):
        self.wait()  # finished는 스레드가 끝나기 직전에 옴 → 완전히 끝날 때까지 (곧 끝남)
        UpdateDownload._running.discard(self)


@dataclass
class _UpdateRun:
    """'업데이트'를 누른 때 정한 것 — 그 뒤의 확인 결과가 바꾸지 않음. download: 받는 스레드 (시작한 뒤)."""

    offer: updates.Offer
    version: str  # 받는 버전 (latest.json의 version)
    current: str  # 지금 버전 (build_info)
    platform_key: str
    location: str  # 받을 곳 (NAS 경로 또는 URL)
    app_path: str = ""  # Mac: 지금 앱 번들, Windows: 설치 폴더 (update_install.running_app_location)
    approved: tuple = ()  # 멈추고 업데이트하기로 한 작업 (워커)
    download: UpdateDownload | None = None

    @property
    def mac(self):
        return self.platform_key != "windows"

    @property
    def source(self):
        return self.offer.result.source


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
        self._update_run = None  # 받는 중인 업데이트 (_UpdateRun) — 받기가 끝나 결과를 처리하면 None
        self.update_banner.notes_clicked.connect(self.show_update_notes)
        self.update_banner.update_clicked.connect(self.start_update)
        self.update_banner.later_clicked.connect(self.dismiss_update_offer)
        self.update_banner.cancel_clicked.connect(self.cancel_update)

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

    # ---- '업데이트'를 누른 뒤: 받기·넘기기 ----

    def start_update(self) -> None:
        """알림 띠의 '업데이트': 알리는 버전(누른 때의 update_offer — 끝까지 이것)을 받아 도우미에 넘기고 앱을 끝냄.
        받기는 뒤 스레드 — 바로 돌아옴. 순서와 실패는 모듈 설명 ('업데이트'를 누르면)."""
        offer = self._offered()
        if self._update_run is not None:
            raise RuntimeError(f"이미 {self._update_run.version}을 받는 중인데 '업데이트'가 불렸습니다")
        info = build_info.current()
        if info is None:
            raise RuntimeError("소스 실행에서 '업데이트'가 불렸습니다 (알림 띠는 빌드된 앱에서만 보임)")
        version = str(offer.manifest.version)
        location = updates.asset_location(offer.result, offer.manifest, offer.entry)
        run = _UpdateRun(offer, version, info.version, build_info.platform_key(), location)
        try:
            # 업데이트 기록을 쓸 수 있어야 시작 — 도우미의 기록과 다시 켜진 앱의 실패 창도 이 파일 (뒤의 기록은 _log_update)
            update_install.log(f"업데이트 {version}: 시작 — 지금 {run.current}, {run.source}에서 받음 ({location})")
            run.app_path = update_install.running_app_location()
        except Exception as exc:
            self._show_update_failure(run, _failure_text(exc))
            return
        if run.mac:
            reason = update_install.refuse_reason_mac(run.app_path)
            if reason is not None:
                _log_update(f"업데이트 {version}: 이 자리의 앱은 바꿀 수 없음 ({run.app_path}) — {reason}")
                QMessageBox.warning(self, CANNOT_UPDATE_TITLE, reason)
                return
        jobs = self.running_jobs()
        if jobs:
            if not self._confirm_stop_jobs(run, [label for label, _worker in jobs]):
                return
            run.approved = tuple(worker for _label, worker in jobs)
        try:
            state_dir = update_install.state_dir()
            update_install.check_free_space(state_dir, update_install.NEEDED_BYTES[run.platform_key])
        except Exception as exc:
            self._show_update_failure(run, _failure_text(exc))
            return
        dest_dir = os.path.join(state_dir, DOWNLOADS_DIR_NAME)
        run.download = UpdateDownload(location, offer.entry, dest_dir, version, run.source,
                                      app_path=run.app_path if run.mac else None)
        run.download.progress.connect(self._on_update_progress)  # GUI 스레드에서 (대기열을 거쳐)
        run.download.ready.connect(self._on_update_ready)
        run.download.failed.connect(self._on_update_download_failed)
        run.download.cancelled.connect(self._on_update_cancelled)
        self._update_run = run
        then = f", 이어서 새 앱을 {run.app_path} 옆에 준비" if run.mac else ""
        _log_update(f"업데이트 {version}: 받기 시작 → {dest_dir}{then}")
        self.update_banner.show_progress(0, offer.entry.size, download_text(version, run.source, 0, offer.entry.size))
        run.download.start()

    def _confirm_stop_jobs(self, run, labels):
        """진행 중인 작업(labels)을 멈추고 업데이트할지 물음 → 예면 True. 묻고 대답을 기록에."""
        jobs = ", ".join(labels)
        _log_update(f"업데이트 {run.version}: 진행 중인 작업({jobs}) — 멈추고 업데이트할지 물음")
        answer = QMessageBox.question(self, BUSY_TITLE, BUSY_QUESTION.format(jobs=jobs),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        yes = answer == QMessageBox.Yes
        _log_update(f"업데이트 {run.version}: → {'멈추고 업데이트' if yes else '업데이트하지 않음'}")
        return yes

    def cancel_update(self) -> None:
        """띠의 [취소]: 받기를 멈추라고 알림 — 멈추면 띠가 다시 알림으로 (_on_update_cancelled). Mac 준비 중이면 준비가
        끝난 뒤 지우고 멈춤. [취소]는 받는 중에만 보이므로 받는 중이 아니면 프로그램 오류 (조용히 넘기지 않음)."""
        run = self._update_run
        if run is None:
            raise RuntimeError(f"받는 중이 아닌데 '취소'가 눌렸습니다 (띠: {self.update_banner.mode()})")
        if run.download.is_cancelled():
            return  # 이미 멈추는 중 (두 번 누름)
        _log_update(f"업데이트 {run.version}: 취소를 누름")
        run.download.cancel()
        self.update_banner.show_progress(0, 0, CANCELLING_TEXT)

    def _on_update_progress(self, done, total, text):
        """(GUI 스레드) 받기·준비 진행을 띠에. 취소를 누른 뒤에는 "취소하는 중…" 그대로."""
        run = self._update_run
        if run is None or run.download.is_cancelled():
            return
        self.update_banner.show_progress(done, total, text)

    def _end_update_download(self):
        """받기가 끝남 → 그 업데이트(_UpdateRun), 창을 닫은 뒤면 None. 결과를 받는 세 슬롯이 맨 먼저 부름 — GUI 스레드가
        아니면 상태를 바꾸기 전에 RuntimeError. 결과 신호는 run()의 맨 끝이라 스레드가 곧 끝남 → 끝날 때까지 기다림
        (넘긴 뒤 앱을 끝낼 때 실행 중인 스레드가 남지 않게)."""
        if QThread.currentThread() is not QApplication.instance().thread():
            raise RuntimeError("업데이트 받기 결과를 GUI 스레드가 아닌 곳에서 받았습니다")
        run, self._update_run = self._update_run, None
        if run is None or self._update_closed:
            return None  # 창을 닫은 뒤 (release_worker가 신호를 막지만 이미 대기열에 들어간 결과)
        run.download.wait()
        return run

    def _on_update_ready(self, prepared):
        """(GUI 스레드) 받기(+ Mac 준비)가 끝남: 그사이 취소를 눌렀으면 받은 것을 지우고 멈춤. 받는 동안 새로 시작한
        작업이 있으면 다시 물음(아니오 — 받은 것을 지우고 띠를 알림으로). 그다음 도우미에 넘김."""
        run = self._end_update_download()
        if run is None:
            return
        _log_update(f"업데이트 {run.version}: 받기 끝 — {prepared}")
        if run.download.is_cancelled():  # 다 받은 뒤, 이 결과가 오기 전에 '취소'를 누름
            if self._discard_prepared(run, prepared):
                self._update_cancelled(run)
            return
        new_jobs = [label for label, worker in self.running_jobs() if worker not in run.approved]
        if new_jobs and not self._confirm_stop_jobs(run, new_jobs):
            if self._discard_prepared(run, prepared):
                self._restore_update_offer(run)
            return
        self._hand_off(run, prepared)

    def _hand_off(self, run, prepared):
        """업데이트 기록(다시 켜진 앱이 결과를 판정) → 도우미(앱이 끝나기를 기다렸다 바꾸고 다시 켬) → 창을 닫고 앱을 끝냄
        (창 닫기가 진행 중인 작업을 멈춤). 기록·도우미가 실패하면 기록을 지우고 실패 창, 앱은 그대로."""
        pending = update_install.Pending(target=run.version, previous=run.current, platform_key=run.platform_key,
                                         started=update_install.timestamp())
        try:
            update_install.write_pending(pending)
            _log_update(f"업데이트 {run.version}: 업데이트 기록을 남김 ({pending})")
            if run.mac:
                update_install.launch_helper_mac(prepared, run.app_path, run.version)
            else:
                update_install.launch_helper_windows(prepared, run.app_path, run.version)
        except Exception as exc:
            text = f"업데이트 도우미를 띄우지 못했습니다.\n{_failure_text(exc)}"
            _log_update(f"업데이트 {run.version}: {text}")  # 기록을 지우기 전에 (지우다 실패해도 이유가 남게)
            try:
                update_install.clear_pending()  # 넘기지 못함 — 다음에 켤 때 이 기록으로 실패를 알리지 않게
            except Exception:
                text += ("\n\n게다가 업데이트 기록을 지우지 못했습니다 — 다음에 켤 때 업데이트 실패로 알릴 수 있습니다.\n"
                         + traceback.format_exc())
            self._show_update_failure(run, text, log_text=False)
            return
        _log_update(f"업데이트 {run.version}: 도우미를 띄움 ({prepared} → {run.app_path}) — 앱을 끝냄 "
                    "(도우미가 바꾸고 다시 켬)")
        self.hide()  # 창 닫기가 진행 중인 작업이 멈추기를 기다리는 동안(작업마다 최대 몇 초) 멈춘 창이 보이지 않게
        try:
            self.close()
        finally:
            QApplication.instance().quit()  # 도우미는 이 프로세스가 끝나기를 기다림 — 닫기에서 무슨 일이 있어도 끝냄

    def _on_update_download_failed(self, text):
        """(GUI 스레드) 받기·준비 실패 → 실패 창, 띠는 다시 알림."""
        run = self._end_update_download()
        if run is None:
            return
        self._show_update_failure(run, text, log_text=False)  # 이유는 받기 스레드가 기록함

    def _on_update_cancelled(self):
        """(GUI 스레드) 취소로 멈춤 (받던 것은 스레드가 지웠음) → 띠는 다시 알림."""
        run = self._end_update_download()
        if run is None:
            return
        self._update_cancelled(run)

    def _update_cancelled(self, run):
        _log_update(f"업데이트 {run.version}: 취소됨 — 알림 띠를 되돌림")
        self._restore_update_offer(run)

    def _discard_prepared(self, run, prepared):
        """넘기지 않기로 한 받은 파일·준비한 앱을 지움 → 지웠으면 True, 못 지웠으면 실패 창 뒤 False."""
        try:
            remove_prepared(prepared)
        except Exception as exc:
            self._show_update_failure(run, f"받은 것을 지우지 못했습니다: {prepared}\n{_failure_text(exc)}")
            return False
        _log_update(f"업데이트 {run.version}: 넘기지 않음 — 받은 것을 지움 ({prepared})")
        return True

    def _restore_update_offer(self, run):
        """띠를 누른 때의 알림으로 되돌림 (다시 '업데이트'를 누르면 처음부터)."""
        self.update_offer = run.offer
        self.update_banner.show_offer(run.version, run.current)

    def _show_update_failure(self, run, text, log_text=True):
        """"업데이트 실패" 창: 출처(NAS/GitHub)·위치·이유 전부. 띠는 먼저 알림으로 되돌림 — 다른 곳에서 저절로 받지 않음.
        log_text: 이유도 업데이트 기록에 (False — 이미 기록함: 받기 스레드·넘기기)."""
        reason = f"\n{text}" if log_text else " — 이유는 위의 기록"
        _log_update(f"업데이트 {run.version}: 실패 ({run.source}: {run.location}), 실패 창{reason}")
        self._restore_update_offer(run)
        QMessageBox.critical(
            self, UPDATE_FAILED_TITLE,
            f"{run.version}로 업데이트하지 못했습니다.\n\n출처: {run.source}\n위치: {run.location}\n\n{text}\n\n"
            f"지금 버전({run.current})은 그대로입니다. 다시 '업데이트'를 누르면 처음부터 다시 받습니다.",
        )

    def stop_update_download(self):
        """(창을 닫을 때) 받는 중이면 멈추라고 알리고(cancel — 받던 .part·준비하던 앱은 스레드가 지움) 끝날 때까지
        붙잡아 둠 (release_worker — 결과 신호를 막음: 닫은 뒤에는 업데이트 기록·도우미로 넘어가지 않음)."""
        run, self._update_run = self._update_run, None
        if run is None:
            return
        run.download.cancel()
        release_worker(run.download, "업데이트 받기")
        UpdateDownload._running.discard(run.download)  # 이제 release_worker가 붙잡음 (신호를 막아 finished로는 놓지 못함)
        _log_update(f"업데이트 {run.version}: 창을 닫음 — 받기를 멈춤")  # 놓은 뒤에 (기록이 실패해도 스레드는 놓임)

    # ---- 다시 켜진 앱: 지난 업데이트의 결과 ----

    def handle_update_startup(self) -> None:
        """(창을 보인 뒤 한 번 — app.launch) 지난 업데이트의 기록(pending_update.json)이 있으면 지금 버전과 비교
        (update_install.startup_result — 목표 버전이면 "잘 켜짐" 표시를 남겨 도우미가 기다림을 끝냄). 성공이면 띠에 잠깐
        "{버전}로 업데이트했습니다", 실패(예전 버전이 켜짐 — 도우미가 되돌림)면 "업데이트 실패" 창에 그 뒤의 업데이트 기록과
        도우미 출력 중 기록에 없는 것(update_install.helper_console_extra).
        이 컴퓨터의 파일만 읽음 (NAS·인터넷 없음). 소스 실행은 아무것도 하지 않음. 기록이 깨졌으면 창에 보인 뒤 지움
        (켤 때마다 같은 창이 뜨지 않게). 예상 못 한 오류는 트레이스백째 창."""
        info = build_info.current()
        if info is None:
            return
        try:
            result = update_install.startup_result(info.version)
        except update_install.UpdateError as exc:
            _log_update(f"켜짐: 업데이트 기록을 읽지 못함 — 보이고 지움\n{exc}")
            try:
                update_install.clear_pending()
                cleared = "기록은 지웠습니다."
            except OSError as clear_exc:
                cleared = f"기록을 지우지도 못했습니다: {type(clear_exc).__name__}: {clear_exc}"
            QMessageBox.critical(self, UPDATE_FAILED_TITLE,
                                 f"지난 업데이트의 결과를 알 수 없습니다 — 업데이트 기록이 깨졌습니다.\n\n{exc}\n\n{cleared}")
            return
        except Exception:
            text = traceback.format_exc()
            _log_update(f"켜짐: 지난 업데이트의 결과를 확인하다 예상치 못한 오류\n{text}")
            QMessageBox.critical(self, UPDATE_FAILED_TITLE,
                                 f"지난 업데이트의 결과를 확인하다 예상치 못한 오류가 났습니다.\n\n{text}")
            return
        if result is None:
            return
        kind, pending = result
        if kind == "ok":
            message = UPDATED_MESSAGE.format(version=pending.target)
            _log_update(f"켜짐: {message} (전 버전 {pending.previous})")
            self.update_banner.show_message(message)
            return
        try:
            tail = update_install.log_tail_since(pending.started) or "(이 업데이트 뒤의 기록이 없습니다)\n"
        except Exception:
            tail = f"(업데이트 기록을 읽지 못했습니다)\n{traceback.format_exc()}"
        # 도우미가 기록을 쓰기 전에 실패했으면(PowerShell·bash가 스크립트를 시작하지 못함 등) 그 이유는 도우미 출력에만 있음
        try:
            extra = update_install.helper_console_extra()
            if extra:
                extra = f"\n도우미 출력 중 기록에 없는 것 ({update_install.helper_console_path()}):\n{extra}"
        except Exception:
            extra = f"\n(도우미 출력을 읽지 못했습니다)\n{traceback.format_exc()}"
        _log_update(f"켜짐: {pending.target}로 업데이트하지 못해 {pending.previous}이(가) 켜짐 — 실패 창")
        QMessageBox.critical(
            self, UPDATE_FAILED_TITLE,
            f"{pending.target}로 업데이트하지 못했습니다 — 지금 버전 {pending.previous}이(가) 그대로 켜졌습니다.\n\n"
            f"업데이트 기록 ({update_install.log_path()}, {pending.started}부터):\n{tail}{extra}",
        )
