"""업데이트 (PlayerUpdateMixin): 확인 일정·결과(새 버전 알림 띠 update_banner, Help → '업데이트 확인…'), '업데이트'를
누른 뒤의 받기·도우미에 넘기기, 다시 켜진 앱의 결과 알림.

확인(updates.check — NAS·GitHub의 latest.json 읽기)은 언제나 뒤 스레드(UpdateCheck)에서 한다. 자동 확인은 공유 설정을
불러온 뒤(_on_shared_config_loaded) 한 번, 그 뒤 켜 둔 동안 3시간마다. 소스 실행(build_info.current()가 None)은
확인하지 않는다 — 자동 확인은 스레드도 만들지 않고, 메뉴는 안내만.

결과 보이기 (설계 4-4·5-1):
- 새 버전(offer): 알림 띠. '나중에'를 누른 버전과 같거나 낮은 번호는 이번 실행 동안 다시 보이지 않음(더 큰 번호는 보임).
  Help → 업데이트 확인…은 숨긴 버전도 다시 보임 (업데이트를 시작하는 곳은 띠뿐). 받는 중(띠가 진행을 보임)에는 결과를
  기록에만 남기고 update_offer와 띠를 그대로 둠.
- 소스마다 읽은 결과는 업데이트 기록(update_install.log — Mac도 파일)에 한 줄씩 (_log_update — 기록을 쓰지 못해도 슬롯
  밖으로 예외를 내지 않음: 3시간마다의 자동 확인이 Mac 앱을 끝내지 않게). 예상된 실패(expected_problem)는 자동 확인이면
  기록에만.
- 오류(error): 자동 확인은 창 — 한 실행에 같은 문제는 한 번 ((소스, 첫 줄). 트레이스백은 첫 줄이 늘 같아 마지막 줄).
- 수동 확인: 언제나 결과 창 — 소스마다 찾은 버전·예상된 문제·오류 전부 (오류가 있으면 경고 창).

'업데이트'를 누르면 (start_update, 설계 5-2·3-4) — 누른 때의 update_offer를 끝까지 씀 (그 뒤의 확인 결과가 바꾸지 않음):
1. 바꿀 수 없는 앱이면 "업데이트할 수 없음" 안내 창, 받지 않음 — Mac: dmg 안·격리 위치에서 켬 (refuse_reason_mac), Windows:
   업데이트 상태 폴더가 설치 폴더 안이거나 설치 파일로 설치한 앱이 아님 (refuse_reason_windows).
2. 다른 창 확인 (뒤 스레드 OthersWork — 띠에 "다른 창 확인 중…"): 같은 앱 자리에서 다른 사용자의 YesonCheck가 돌면 그 창은
   닫으라고 요청할 수 없으므로 "다른 사용자(…)가 YesonCheck를 쓰고 있어 업데이트할 수 없습니다" 창, 받지 않음. 이 사용자의
   다른 창(instances.others)에는 상태를 물음(instance_link.query_status — 답하지 않는 창은 "응답 없음").
3. 다른 창이 있으면 확인 창 하나(_confirm_close_others — 닫을 창 수, 이 창을 포함해 작업 중인 창과 그 작업, 저장 안 한 검토
   결과가 있는 창, 응답 없는 창 — [모두 닫고 업데이트] [취소]). 없으면 지금처럼 진행 중인 작업(running_jobs — 창 닫기가
   멈추는 작업)이 있을 때만 멈추고 업데이트할지 물음. 작업은 넘긴 뒤 앱을 끝낼 때 창 닫기가 멈춤 — 받다 실패·취소하면 그대로
   이어짐. [취소]·아니오면 받지 않고 띠는 다시 알림.
4. 여유 공간 확인(update_install.NEEDED_BYTES) → 뒤 스레드(UpdateDownload)가 <state_dir>/downloads에 받기(크기·sha256),
   Mac은 이어서 dmg에서 새 앱을 준비("준비 중…"). 띠에 진행·[취소].
5. 다 받으면 다른 창을 다시 확인: 다른 사용자가 켰으면 멈춤. 받는 동안 이 창에서 새로 시작한 작업, 작업을 시작했거나 저장 안
   한 결과가 생긴 창(새로 켜진 창 포함)이 있으면 다시 물음. 새로 켜진 빈 창은 묻지 않고 함께 닫음. 다른 창마다 정상 종료를
   요청(request_close — 닫기 버튼과 같음)하고 그 프로세스가 모두 끝나기를 기다림(CLOSE_OTHERS_POLL_MS마다, 최대
   CLOSE_OTHERS_TIMEOUT_S — 띠에 "다른 창을 닫는 중…", 창은 쓰지 못하게, 그사이 새로 켜진 창도 묻지 않고 닫음). 끝나지 않은
   창이 있으면 받은 것을 지우고 "업데이트를 멈췄습니다 — 이 창이 닫히지 않았습니다: …" 창, 앱은 그대로.
6. 업데이트 기록(write_pending — 무작위 토큰·이 창의 pid) → 도우미(launch_helper_mac/windows — 토큰을 넘김: 도우미가 다시
   켠 앱만 결과를 판정) → 기록에 도우미 pid를 더해 다시 씀(그동안 켜는 앱은 '업데이트 중' 창만 — app.launch) → 도우미가 시작
   기록을 남기면 창을 닫고 앱을 끝냄 (기다리는 동안 띠에 "업데이트 도우미를 시작하는 중…", 창은 쓰지 못하게). 도우미를 띄우지
   못하거나, 도우미 pid를 기록에 쓰지 못하거나, 띄운 도우미가 시작 기록 없이 끝나거나 UPDATE_HELPER_START_TIMEOUT_MS 안에
   시작 기록을 남기지 않으면(정책·백신이 PowerShell 스크립트를 막음 등 — 앱이 끝나면 다시 켜 줄 것이 없음) 도우미를 끝내고
   기록을 지운 뒤 실패 창, 앱은 그대로.
실패는 "업데이트 실패" 창(본문은 이유 한 줄·출처 NAS/GitHub·위치, 전체 — 예상 못 한 예외는 트레이스백 — 는 자세히) 뒤 띠를
다시 그 알림으로. 받기 실패면 곧바로 같은 곳들을 다시 확인해 띠가 지금 있는 것을 알림. 다른 곳에서 저절로 받지 않음 — 다시
누르면 처음부터. 취소·창 닫기는 받던 것(받은 것)을 지우고 넘기지 않음. 단계마다 update_install.log.

다시 켜진 앱 (handle_update_startup — 창을 보인 뒤 한 번, 이 컴퓨터의 파일만, 도우미가 토큰과 함께 켠 앱만 — 토큰 없는 옛
기록은 아무 앱이나): 기록의 목표 버전이면 "잘 켜짐" 표시를 남기고 띠에 잠깐 "{버전}로 업데이트했습니다", 받아 둔 설치 파일을
지움, 예전 버전이 켜졌으면(도우미가 되돌림) "업데이트 실패" 창에 그 뒤의 기록 중 업데이트를 건 창과 도우미의 줄(도우미 출력 중
기록에 없는 것도 — 도우미가 기록을 쓰기 전에 실패한 이유).
"""

import dataclasses
import functools
import os
import secrets
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox

from yesoncheck import build_info, instance_link, instances, timing_log, update_install, updates
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
HELPER_STARTING_TEXT = "업데이트 도우미를 시작하는 중…"
# 도우미가 시작 기록 없이 끝났거나 시간이 지남 → 앱을 끝내지 않은 이유 (_helper_start_failed)
HELPER_BLOCKED_NOTE = "앱을 끝내면 다시 켜 줄 것이 없어 끝내지 않았습니다 (보안 정책·백신이 도우미를 막았을 수 있음)."
DETAILS_HINT = "전체 기록은 아래 'Show Details…' 단추를 누르면 보입니다."
SUMMARY_MAX_CHARS = 300  # 실패 창 본문의 이유 한 줄 (넘으면 줄임 — 전체는 자세히)
BOX_TITLE_PROPERTY = "ycTitle"  # show_details_box의 창 제목 (macOS는 QMessageBox의 제목을 버리므로 따로)
DOWNLOADS_DIR_NAME = "downloads"  # <update_install.state_dir()>/downloads — 받은 설치 파일·dmg (한 번에 하나만 둠)

# 다른 YesonCheck 창 (설계 3-4)
UPDATE_OTHERS_TITLE = "다른 창도 닫고 업데이트"
OTHERS_COUNT = "다른 YesonCheck 창 {n}개도 닫힙니다."
OTHERS_JOBS_STOP = "작업 중인 창의 작업은 멈춥니다."
OTHERS_UNSAVED_LOST = "닫으면 저장 안 한 결과는 사라집니다."
CLOSE_ALL_BUTTON = "모두 닫고 업데이트"
CANCEL_BUTTON = "취소"
NO_RESPONSE = "응답 없음"
OTHER_USER_MESSAGE = "다른 사용자({user})가 YesonCheck를 쓰고 있어 업데이트할 수 없습니다"
UPDATE_STOPPED_TITLE = "업데이트 멈춤"
UPDATE_STOPPED = "업데이트를 멈췄습니다 — 이 창이 닫히지 않았습니다: {windows}"
CHECKING_OTHERS_TEXT = "다른 창 확인 중…"
CLOSING_OTHERS_TEXT = "다른 창을 닫는 중…"
UPDATE_JOB_LABEL = "업데이트 받기"  # 다른 창의 업데이트가 묻는 이 창의 작업 (이 창의 업데이트가 진행 중)
# 다른 창 하나에 상태를 묻거나 닫기를 요청하는 한도. Windows는 파이프 연결이 이보다 최대 약 5초 더 걸릴 수 있음
# (WaitNamedPipe) — 뒤 스레드에서 차례로 하므로 창은 멈추지 않음
OTHERS_LINK_TIMEOUT_MS = 3000
# 닫기를 요청한 창의 프로세스가 끝나기를 기다리는 한도: 창 기록은 닫기를 시작할 때 지워지지만, 창 닫기가 작업을 멈추고(작업마다
# 최대 10초) 붙잡아 둔 작업을 기다리는(최대 30초) 동안 프로세스는 돎
CLOSE_OTHERS_TIMEOUT_S = 40
CLOSE_OTHERS_POLL_MS = 500  # 그동안 다른 창의 프로세스·새로 켜진 창을 보는 간격
_UNSAVED_CONCERN = "저장 안 한 결과"  # 다시 물을지 가리는 것 (_concerns) 중 하나 — 작업 이름과 겹치지 않음


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


def remove_downloads():
    """지난 업데이트에서 받은 설치 파일·dmg·남은 .part(<state_dir>/downloads 안)를 지움 — 업데이트가 끝났으니 더 쓰지 않음
    (Windows 설치 파일 약 410 MB). 못 지운 것은 이유(트레이스백)째 업데이트 기록에만 — 앱은 그대로, 다음 받기가 먼저 비움."""
    try:
        folder = os.path.join(update_install.state_dir(), DOWNLOADS_DIR_NAME)
        names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    except Exception:
        _log_update(f"켜짐: 받은 것을 지우려다 받기 폴더를 읽지 못함\n{traceback.format_exc()}")
        return
    for name in names:
        path = os.path.join(folder, name)
        try:
            remove_prepared(path)
        except Exception:
            _log_update(f"켜짐: 지난 업데이트에서 받은 것을 지우지 못함 ({path}) — 다음 받기가 먼저 비움\n{traceback.format_exc()}")
        else:
            _log_update(f"켜짐: 지난 업데이트에서 받은 것을 지움 ({path})")


def show_details_box(parent, title, text, details, icon=QMessageBox.Critical):
    """짧은 본문(text)과, 'Show Details…'를 누르면 펼쳐지는 긴 글(details — 스크롤되는 칸)의 창. 업데이트 기록 80줄·설치 파일
    기록·도우미 출력을 본문에 그대로 넣으면 창이 화면보다 커져 단추를 누를 수 없게 됨. 닫을 때까지 기다림."""
    box = QMessageBox(icon, title, text, QMessageBox.Ok, parent)
    # macOS의 QMessageBox는 창 제목을 버림(Mac 안내서) → 무슨 창인지 기록하는 쪽(시험·실행 시험)이 알 수 있게 따로 둠
    box.setProperty(BOX_TITLE_PROPERTY, title)
    box.setDetailedText(details)
    box.exec_()


def _summary(text):
    """실패 창 본문에 보일 이유 한 줄: 첫 줄 (트레이스백이면 마지막 줄 — 예외 종류와 글), 너무 길면 줄임."""
    line = _problem_key(text)
    return line if len(line) <= SUMMARY_MAX_CHARS else line[:SUMMARY_MAX_CHARS - 1] + "…"


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


# ---- 다른 YesonCheck 창 (설계 3-4) ----


def _concerns(shown):
    """다시 물을지 가리는 것: 확인 창에 보인 상태(OtherWindow.shown) → 작업 이름들, 저장 안 한 결과, 응답 없음. 확인 창에 없던
    창(None)은 없음 — 새로 켜진 창은 이것이 비어 있을 때만 묻지 않고 닫음."""
    if shown is None:
        return frozenset()
    if "no_response" in shown:
        return frozenset({NO_RESPONSE})
    concerns = set(shown["jobs"])
    if shown["unsaved_ocr"]:
        concerns.add(_UNSAVED_CONCERN)
    return frozenset(concerns)


@dataclass
class OtherWindow:
    """다른 창 하나: 창 기록과 물어서 받은 상태(VideoPlayer.instance_status — 답하지 않았으면 None, error에 이유). 닫기를
    기다리는 동안 새로 켜져 묻지 않은 창은 status·error 모두 None."""

    record: instances.InstanceRecord
    status: dict | None = None
    error: str | None = None

    @property
    def pid(self):
        return self.record.pid

    @property
    def jobs(self):
        return list(self.status["jobs"]) if self.status is not None else []

    @property
    def unsaved(self):
        return self.status is not None and self.status["unsaved_ocr"]

    @property
    def label(self):
        """확인 창·멈춤 창의 한 창: "창 제목 — 영상 이름 (pid N)"(영상이 없으면 제목만), 답하지 않은 창 "pid N — 응답 없음"."""
        if self.status is None:
            return f"pid {self.pid} — {NO_RESPONSE if self.error is not None else '닫는 중에 켜진 창'}"
        video = self.status["video"]
        name = f"{self.status['title']} — {os.path.basename(video)}" if video else self.status["title"]
        return f"{name} (pid {self.pid})"

    def shown(self):
        """확인 창에 보인 상태 (_UpdateRun.approved_others의 값): 받은 상태, 답하지 않았으면 {"pid", "no_response": 이유}."""
        if self.status is not None:
            return dict(self.status)
        return {"pid": self.pid, "no_response": self.error}

    def concerns(self):
        return _concerns(self.shown())

    def describe(self):
        """업데이트 기록의 한 창: 상태 전부 또는 답하지 않은 이유."""
        if self.status is None:
            return f"{self.label} ({self.error})"
        jobs = ", ".join(self.jobs) or "없음"
        return f"{self.label}: 작업 {jobs}, 저장 안 한 결과 {'있음' if self.unsaved else '없음'}"


@dataclass
class OthersScan:
    """다른 창 확인 결과: 같은 앱 자리에서 도는 다른 사용자의 프로세스 [(pid, 사용자)]와 이 사용자의 다른 창 [OtherWindow]."""

    users: list
    windows: list


def _checked_status(status, server_name):
    """다른 창이 답한 상태의 모양 확인 — 다르면 InstanceLinkError (답하지 않은 창처럼 "응답 없음"으로: GUI 스레드에서
    KeyError가 나지 않게)."""
    jobs = status.get("jobs")
    if not (isinstance(status.get("title"), str) and isinstance(status.get("video"), str)
            and isinstance(jobs, list) and all(isinstance(job, str) for job in jobs)
            and isinstance(status.get("unsaved_ocr"), bool)):
        raise instance_link.InstanceLinkError(f"창이 알 수 없는 상태를 답했습니다 ({server_name}): {status!r}")
    return status


def scan_other_windows(app_path):
    """(뒤 스레드) 같은 앱 자리에서 도는 다른 사용자의 프로세스와 이 사용자의 다른 창의 상태 → OthersScan. 다른 사용자가
    있으면 창은 묻지 않음(업데이트하지 않으므로). 답하지 않는 창은 이유째 — 묻는 사이에 끝난 창은 뺌. 예상 못 한 오류(ps·
    tasklist 실패, 깨진 창 기록)는 그대로 올림."""
    users = instances.other_user_processes(app_path)
    if users:
        return OthersScan(users, [])
    windows = []
    for record in instances.others(app_path):
        try:
            status = _checked_status(instance_link.query_status(record.server_name, OTHERS_LINK_TIMEOUT_MS),
                                     record.server_name)
        except instance_link.InstanceLinkError as exc:
            if not instances.is_running(record):
                continue  # 묻는 사이에 끝난 창
            windows.append(OtherWindow(record, error=str(exc)))
        else:
            windows.append(OtherWindow(record, status))
    return OthersScan(users, windows)


def request_close_all(windows):
    """(뒤 스레드) 창마다 정상 종료(닫기 버튼과 같음)를 요청 → [(창, 요청하지 못한 이유 — 받았으면 None)]. 답하지 않은 창도
    늦게 받은 요청으로 닫힐 수 있으므로 답과 상관없이 프로세스가 끝나기를 기다림 (_poll_closing_others)."""
    answers = []
    for window in windows:
        try:
            instance_link.request_close(window.record.server_name, OTHERS_LINK_TIMEOUT_MS)
        except instance_link.InstanceLinkError as exc:
            answers.append((window, str(exc)))
        else:
            answers.append((window, None))
    return answers


class OthersWork(QThread):
    """다른 창에 묻는 일(scan_other_windows·request_close_all — 창마다 몇 초까지 기다릴 수 있고, Windows tasklist도 몇 초)을
    GUI 밖에서 하는 스레드. 소켓(QLocalSocket)도 이 스레드에서 만들고 씀. 위젯은 건드리지 않음. work: 인자 없이 부를 함수 —
    결과는 done, 예상 못 한 예외는 트레이스백째 failed (stderr에도).

    UpdateCheck처럼 부모 없이 만들고 실행 중에는 _running에 붙잡아 둠. 창을 닫을 때·업데이트를 멈출 때 실행 중이면
    release_worker (_end_others).
    """

    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    _running = set()

    def __init__(self, work):
        super().__init__()
        self._work = work
        self.finished.connect(self._forget)

    def start(self, *args):
        OthersWork._running.add(self)
        super().start(*args)

    def run(self):
        try:
            result = self._work()
        except Exception:
            text = traceback.format_exc()
            print(f"[업데이트 — 다른 창] 예상치 못한 오류:\n{text}", file=sys.stderr, flush=True)
            self.failed.emit(text)
            return
        self.done.emit(result)

    def _forget(self):
        self.wait()  # finished는 스레드가 끝나기 직전에 옴 → 완전히 끝날 때까지 (곧 끝남)
        OthersWork._running.discard(self)


@dataclass
class _UpdateRun:
    """'업데이트'를 누른 때 정한 것 — 그 뒤의 확인 결과가 바꾸지 않음. download: 받는 스레드 (시작한 뒤)."""

    offer: updates.Offer
    version: str  # 받는 버전 (latest.json의 version)
    current: str  # 지금 버전 (build_info)
    platform_key: str
    location: str  # 받을 곳 (NAS 경로 또는 URL)
    app_path: str = ""  # Mac: 지금 앱 번들, Windows: 설치 폴더 (update_install.running_app_location)
    others_app_path: str = ""  # 다른 창을 셀 앱 자리 (instances.current_app_path — 창 기록에 남기는 값)
    approved: tuple = ()  # 멈추고 업데이트하기로 한 작업 (워커)
    approved_others: dict = field(default_factory=dict)  # pid → 확인 창에서 보인 그 창의 상태 (OtherWindow.shown)
    download: UpdateDownload | None = None

    @property
    def mac(self):
        return self.platform_key != "windows"

    @property
    def source(self):
        return self.offer.result.source


@dataclass
class _HelperStart:
    """띄운 도우미가 시작 기록을 남기기를 기다리는 동안의 것 (_hand_off → _poll_update_helper)."""

    run: _UpdateRun
    prepared: str  # 넘긴 설치 파일·준비한 앱
    proc: object  # 도우미 프로세스 (subprocess.Popen)
    pending: update_install.Pending
    log_offset: int  # 도우미를 띄우기 바로 전의 업데이트 기록 크기 — 이 뒤에서 시작 기록을 찾음
    deadline: float  # time.monotonic() — 이때까지 시작 기록이 없으면 실패


@dataclass
class _OthersStep:
    """다른 창을 확인하거나 닫는 동안의 것 (받기 전·넘기기 전 — _update_others). work: 실행 중인 뒤 스레드(확인·닫기 요청).
    닫기를 기다리는 동안(deadline이 있음): closing — 닫기를 요청한 창, ended — 끝난 것을 기록한 창의 pid."""

    run: _UpdateRun
    prepared: str | None  # 넘기기 전이면 받은 파일·준비한 앱 (넘기지 않으면 지움), 받기 전이면 None
    work: OthersWork | None = None
    closing: list = field(default_factory=list)  # [OtherWindow]
    ended: set = field(default_factory=set)
    deadline: float | None = None  # time.monotonic() — 이때까지 끝나지 않은 창이 있으면 업데이트를 멈춤


def _update_log_report(pending):
    """실패 창에 보일 기록: 업데이트 기록 중 pending.started 뒤의 줄 — 그 업데이트를 건 창(pending.app_pid, 옛 기록에는 없어
    모든 줄)과 도우미의 줄만 — 과, 도우미 출력 중 기록에 없는 것(도우미가 기록을 쓰기 전에 실패한 이유 — PowerShell·bash가
    스크립트를 시작하지 못함 등) → (기록 글, 도우미 출력 글 — 없으면 빈 글자). 읽다 난 오류는 그 자리에 트레이스백째
    (삼키지 않음)."""
    try:
        tail = (update_install.log_tail_since(pending.started, pending.app_pid or None)
                or "(이 업데이트 뒤의 기록이 없습니다)\n")
    except Exception:
        tail = f"(업데이트 기록을 읽지 못했습니다)\n{traceback.format_exc()}"
    try:
        extra = update_install.helper_console_extra()
        if extra:
            extra = f"\n도우미 출력 중 기록에 없는 것 ({update_install.helper_console_path()}):\n{extra}"
    except Exception:
        extra = f"\n(도우미 출력을 읽지 못했습니다)\n{traceback.format_exc()}"
    return tail, extra


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
    UPDATE_HELPER_START_TIMEOUT_MS = 15000  # 띄운 도우미가 시작 기록을 남기기를 기다리는 한도
    UPDATE_HELPER_POLL_MS = 200  # 그동안 도우미·기록을 보는 간격 (GUI 스레드는 그 사이 그대로 돎)

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
        self._update_helper = None  # 시작 기록을 기다리는 도우미 (_HelperStart)
        self._update_helper_timer = QTimer(self)
        self._update_helper_timer.setInterval(self.UPDATE_HELPER_POLL_MS)
        self._update_helper_timer.timeout.connect(self._poll_update_helper)
        self._update_others = None  # 다른 창을 확인하거나 닫는 중 (_OthersStep)
        self._update_others_timer = QTimer(self)  # 닫기를 요청한 창이 끝났는지 봄 (CLOSE_OTHERS_POLL_MS마다)
        self._update_others_timer.timeout.connect(self._poll_closing_others)
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
                _log_update("업데이트 확인 (자동): 앞의 확인이 아직 끝나지 않음 — 끝나면 다시 확인")
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
            _log_update(f"업데이트 확인 ({kind}) {_source_state(source_result, current)}")
        offer = result.offer
        if offer is None:
            _log_update(f"업데이트 확인 ({kind}) → 새 버전 없음 (지금 {current})")
        else:
            _log_update(f"업데이트 확인 ({kind}) → 새 버전 {offer.manifest.version} ({offer.result.source})")
        if self.update_banner.mode() == "progress":
            # 받는 중: 받고 있는 버전(update_offer)과 띠(받기 진행)는 그대로 — 이번 결과는 위의 기록에만
            _log_update(f"업데이트 확인 ({kind}) 받는 중이라 알림 띠와 고른 버전은 그대로 둠")
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
        _log_update(f"업데이트 확인 ({kind}) 예상치 못한 오류:\n{text}")
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

    def _update_busy(self):
        """업데이트가 진행 중 — 다른 창 확인(받기 전)부터 도우미가 시작하기를 기다릴 때까지."""
        return self._update_run is not None or self._update_others is not None or self._update_helper is not None

    def instance_status(self) -> dict:
        """다른 창의 업데이트가 묻는 이 창의 상태 (VideoPlayerBase.instance_status) — 이 창의 업데이트가 진행 중이면 작업에
        "업데이트 받기"도 (설계 3-4의 작업 목록: 그 창이 이 창을 닫으면 이 창의 업데이트는 멈춤)."""
        status = super().instance_status()
        if self._update_busy():
            status["jobs"] = [*status["jobs"], UPDATE_JOB_LABEL]
        return status

    def start_update(self) -> None:
        """알림 띠의 '업데이트': 알리는 버전(누른 때의 update_offer — 끝까지 이것)을 받아 도우미에 넘기고 앱을 끝냄.
        다른 창 확인·받기는 뒤 스레드 — 바로 돌아옴. 순서와 실패는 모듈 설명 ('업데이트'를 누르면)."""
        offer = self._offered()
        if self._update_busy():
            raise RuntimeError(f"업데이트가 이미 진행 중인데 '업데이트'가 불렸습니다 (띠: {self.update_banner.mode()})")
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
            run.others_app_path = instances.current_app_path()
        except Exception as exc:
            self._show_update_failure(run, _failure_text(exc))
            return
        try:
            if run.mac:
                reason = update_install.refuse_reason_mac(run.app_path)
            else:
                reason = update_install.refuse_reason_windows(run.app_path)
        except Exception as exc:
            self._show_update_failure(run, _failure_text(exc))
            return
        if reason is not None:
            _log_update(f"업데이트 {version}: 이 자리의 앱은 바꿀 수 없음 ({run.app_path}) — {reason}")
            QMessageBox.warning(self, CANNOT_UPDATE_TITLE, reason)
            return
        self._check_other_windows(run, None)

    def _start_update_download(self, run):
        """여유 공간을 확인하고 받기 스레드를 시작 (결과는 _on_update_ready·_on_update_download_failed·
        _on_update_cancelled), 띠에 진행·[취소]."""
        try:
            state_dir = update_install.state_dir()
            update_install.check_free_space(state_dir, update_install.NEEDED_BYTES[run.platform_key])
        except Exception as exc:
            self._show_update_failure(run, _failure_text(exc))
            return
        dest_dir = os.path.join(state_dir, DOWNLOADS_DIR_NAME)
        entry = run.offer.entry
        run.download = UpdateDownload(run.location, entry, dest_dir, run.version, run.source,
                                      app_path=run.app_path if run.mac else None)
        run.download.progress.connect(self._on_update_progress)  # GUI 스레드에서 (대기열을 거쳐)
        run.download.ready.connect(self._on_update_ready)
        run.download.failed.connect(self._on_update_download_failed)
        run.download.cancelled.connect(self._on_update_cancelled)
        self._update_run = run
        then = f", 이어서 새 앱을 {run.app_path} 옆에 준비" if run.mac else ""
        _log_update(f"업데이트 {run.version}: 받기 시작 → {dest_dir}{then}")
        self.update_banner.show_progress(0, entry.size, download_text(run.version, run.source, 0, entry.size))
        run.download.start()

    # ---- 다른 창: 확인하고 묻기·닫고 기다리기 (설계 3-4) ----

    def _check_other_windows(self, run, prepared):
        """같은 앱 자리의 다른 사용자 프로세스와 이 사용자의 다른 창의 상태를 뒤 스레드로 확인 (결과는
        _on_other_windows_checked) — 받기 전(prepared None)과 넘기기 직전(prepared: 받은 것). 그동안 띠에 "다른 창 확인 중…"
        ([취소] 없음 — 창마다 정해진 시간에 끝남)."""
        _log_update(f"업데이트 {run.version}: 다른 창 확인 ({'넘기기 전' if prepared else '받기 전'}, 앱 자리 "
                    f"{run.others_app_path})")
        work = OthersWork(functools.partial(scan_other_windows, run.others_app_path))
        work.done.connect(self._on_other_windows_checked)  # GUI 스레드에서 (대기열을 거쳐)
        work.failed.connect(self._on_others_work_failed)
        self._update_others = _OthersStep(run, prepared, work)
        self.update_banner.show_progress(0, 0, CHECKING_OTHERS_TEXT, cancellable=False)
        work.start()

    def _take_others_work(self):
        """뒤 스레드(확인·닫기 요청)가 끝남 → 그 단계(_OthersStep), 창을 닫았거나 업데이트를 멈춘 뒤면 None. 결과를 받는
        슬롯이 맨 먼저 부름 — GUI 스레드가 아니면 상태를 바꾸기 전에 RuntimeError. 결과 신호는 run()의 맨 끝이라 스레드가 곧
        끝남 → 끝날 때까지 기다림."""
        if QThread.currentThread() is not QApplication.instance().thread():
            raise RuntimeError("다른 창 확인·닫기 요청의 결과를 GUI 스레드가 아닌 곳에서 받았습니다")
        step = self._update_others
        if step is None or step.work is None or self._update_closed:
            return None  # release_worker가 신호를 막지만 이미 대기열에 들어간 결과
        step.work.wait()
        step.work = None
        return step

    def _end_others(self):
        """다른 창 단계를 끝냄 → 그 단계 (없었으면 None): 기다림 타이머를 멈추고, 실행 중인 뒤 스레드는 결과를 버린 채 끝날
        때까지 붙잡아 둠 (release_worker — 답하지 않는 창을 기다리는 중일 수 있음, 창마다 정해진 시간에 끝남)."""
        self._update_others_timer.stop()
        step, self._update_others = self._update_others, None
        if step is not None and step.work is not None:
            release_worker(step.work, "업데이트 — 다른 창 확인·닫기 요청")
            OthersWork._running.discard(step.work)  # 이제 release_worker가 붙잡음 (신호를 막아 finished로는 놓지 못함)
            step.work = None
        return step

    def _give_up_update(self, step):
        """넘기지 않음: 다른 창 단계를 끝내고 창을 다시 쓸 수 있게, 받은 것이 있으면 지운 뒤 띠를 누른 때의 알림으로 (지우지
        못하면 실패 창 — 띠는 그 창이 되돌림)."""
        self._end_others()
        self.setEnabled(True)  # 창보다 먼저 (쓰지 못하게 한 창의 자식 창도 쓰지 못함)
        if step.prepared is None or self._discard_prepared(step.run, step.prepared):
            self._restore_update_offer(step.run)

    def _on_others_work_failed(self, text):
        """(GUI 스레드) 다른 창을 확인하거나 닫기를 요청하다 예상 못 한 오류 (트레이스백)."""
        step = self._take_others_work()
        if step is None:
            return
        self._others_failed(step, text)

    def _others_failed(self, step, text):
        """다른 창을 확인하거나 닫다 예상 못 한 오류 → 넘기지 않음: 받은 것을 지우고 "업데이트 실패" 창(트레이스백째),
        띠는 다시 알림, 앱은 그대로."""
        self._end_others()
        self.setEnabled(True)
        if step.prepared is not None and not self._discard_prepared(step.run, step.prepared):
            return  # 지우지 못한 실패 창을 보였음 (오류도 기록에 남김)
        self._show_update_failure(step.run, text)

    def _on_other_windows_checked(self, scan):
        """(GUI 스레드) 다른 창 확인 결과 (OthersScan): 기록에 남기고, 다른 사용자가 쓰고 있으면 멈춤 (받은 것은 지움). 아니면
        받기 전 — 묻고 받기, 넘기기 전 — 다시 물을지 정해 다른 창을 닫거나 넘김."""
        step = self._take_others_work()
        if step is None:
            return
        run = step.run
        lines = "".join(f"\n  {window.describe()}" for window in scan.windows)
        _log_update(f"업데이트 {run.version}: 다른 창 확인 끝 — 다른 사용자의 프로세스 {len(scan.users)}개, "
                    f"다른 창 {len(scan.windows)}개{lines}")
        if scan.users:
            names = ", ".join(dict.fromkeys(user for _pid, user in scan.users))
            procs = ", ".join(f"pid {pid} ({user})" for pid, user in scan.users)
            _log_update(f"업데이트 {run.version}: 같은 앱 자리에서 다른 사용자의 YesonCheck가 돎 ({procs}) — 업데이트하지 않음")
            self._give_up_update(step)
            QMessageBox.warning(self, CANNOT_UPDATE_TITLE, OTHER_USER_MESSAGE.format(user=names))
            return
        if step.prepared is None:
            self._others_checked_before_download(step, scan.windows)
        else:
            self._others_checked_before_hand_off(step, scan.windows)

    def _others_checked_before_download(self, step, windows):
        """받기 전: 다른 창이 있으면 이 창의 작업과 합친 확인 창 하나, 없으면 지금처럼 진행 중인 작업이 있을 때만 물음.
        예면 멈추기로 한 작업·보인 창의 상태를 남기고 받기."""
        run = step.run
        jobs = self.running_jobs()
        labels = [label for label, _worker in jobs]
        if windows:
            yes = self._confirm_close_others(run, labels, windows)
        else:
            yes = self._confirm_stop_jobs(run, labels) if jobs else True
        if self._update_others is not step:
            return  # 묻는 동안 창이 닫힘 (stop_update_download가 끝냄)
        if not yes:
            self._give_up_update(step)
            return
        self._end_others()
        run.approved = tuple(worker for _label, worker in jobs)
        run.approved_others = {window.pid: window.shown() for window in windows}
        self._start_update_download(run)

    def _others_checked_before_hand_off(self, step, windows):
        """넘기기 직전 (설계 3-4·6장): 받는 동안 이 창에서 새로 시작한 작업, 확인 창에서 본 것보다 할 일이 늘어난 창(작업·저장
        안 한 결과·응답 없음 — 새로 켜진 창은 하나라도 있으면)이 있으면 다시 물음 (다른 창이 있으면 합친 확인 창, 없으면 지금처럼
        이 창의 작업만). 새로 켜진 빈 창은 묻지 않고 함께 닫음. 아니오 — 어느 창도 닫지 않고 받은 것을 지움. 다른 창이 있으면
        닫고 기다린 뒤, 없으면 바로 도우미에 넘김."""
        run = step.run
        jobs = self.running_jobs()
        new_jobs = [label for label, worker in jobs if worker not in run.approved]
        changed = [w for w in windows if not w.concerns() <= _concerns(run.approved_others.get(w.pid))]
        fresh = [w for w in windows if w.pid not in run.approved_others and not w.concerns()]
        if fresh:
            _log_update(f"업데이트 {run.version}: 받는 동안 새로 켜진 빈 창 {len(fresh)}개 — 묻지 않고 함께 닫음: "
                        + ", ".join(w.label for w in fresh))
        if new_jobs or changed:
            if changed:
                _log_update(f"업데이트 {run.version}: 받는 동안 작업·저장 안 한 결과가 생긴 창 {len(changed)}개 — 다시 "
                            "물음: " + ", ".join(w.label for w in changed))
            if windows:
                yes = self._confirm_close_others(run, [label for label, _worker in jobs], windows)
            else:
                yes = self._confirm_stop_jobs(run, new_jobs)
            if self._update_others is not step:
                return  # 묻는 동안 창이 닫힘 (stop_update_download가 받은 것을 지움)
            if not yes:
                self._give_up_update(step)
                return
            run.approved = tuple(worker for _label, worker in jobs)
            run.approved_others = {window.pid: window.shown() for window in windows}
        if not windows:
            self._end_others()
            self._hand_off(run, step.prepared)
            return
        self._close_other_windows(step, windows)

    def _confirm_close_others(self, run, own_jobs, windows):
        """다른 창도 닫고 업데이트할지 한 창으로 물음 (설계 3-4): 닫을 창 수, 작업 중인 창(이 창의 작업 own_jobs도 여기에 —
        "진행 중인 작업…" 질문을 따로 띄우지 않음)과 그 작업·"작업은 멈춥니다", 저장 안 한 OCR·애니매틱 검토 결과가 있는 창과
        "저장 안 한 결과는 사라집니다", 응답 없는 창. [모두 닫고 업데이트]면 True (기본·Esc는 [취소]). 묻고 대답을 기록에."""
        lines = [OTHERS_COUNT.format(n=len(windows))]
        busy = [f"- 이 창: {', '.join(own_jobs)}"] if own_jobs else []
        busy += [f"- {window.label}: {', '.join(window.jobs)}" for window in windows if window.jobs]
        if busy:
            lines += ["", "작업 중인 창:", *busy, OTHERS_JOBS_STOP]
        unsaved = [f"- {window.label}" for window in windows if window.unsaved]
        if unsaved:
            lines += ["", "저장 안 한 OCR·애니매틱 검토 결과가 있는 창:", *unsaved, OTHERS_UNSAVED_LOST]
        silent = [f"- {window.label}" for window in windows if window.status is None]
        if silent:
            lines += ["", "하는 일을 알 수 없는 창:", *silent]
        text = "\n".join(lines)
        _log_update(f"업데이트 {run.version}: 다른 창도 닫고 업데이트할지 물음\n{text}")
        box = QMessageBox(QMessageBox.Question, UPDATE_OTHERS_TITLE, text, QMessageBox.Yes | QMessageBox.Cancel, self)
        box.setProperty(BOX_TITLE_PROPERTY, UPDATE_OTHERS_TITLE)  # macOS는 창 제목을 버림 (show_details_box)
        box.button(QMessageBox.Yes).setText(CLOSE_ALL_BUTTON)
        box.button(QMessageBox.Cancel).setText(CANCEL_BUTTON)
        box.setDefaultButton(QMessageBox.Cancel)
        yes = box.exec_() == QMessageBox.Yes
        _log_update(f"업데이트 {run.version}: → {'모두 닫고 업데이트' if yes else '업데이트하지 않음'}")
        return yes

    def _close_other_windows(self, step, windows):
        """다른 창들에 정상 종료를 요청하고(뒤 스레드) 그 프로세스가 모두 끝나기를 CLOSE_OTHERS_POLL_MS마다 확인
        (_poll_closing_others, 최대 CLOSE_OTHERS_TIMEOUT_S, 띠에 "다른 창을 닫는 중…"). 기다리는 동안 이 창은 쓰지 못하게 함
        — 새로 시작한 작업을 넘긴 뒤 창 닫기가 묻지 않고 멈추지 않게."""
        run = step.run
        step.deadline = time.monotonic() + CLOSE_OTHERS_TIMEOUT_S
        _log_update(f"업데이트 {run.version}: 다른 창 {len(windows)}개에 닫기를 요청하고 프로세스가 끝나기를 기다림 (최대 "
                    f"{CLOSE_OTHERS_TIMEOUT_S:g}초): " + ", ".join(w.label for w in windows))
        self.setEnabled(False)
        self.update_banner.show_progress(0, 0, CLOSING_OTHERS_TEXT, cancellable=False)
        self._request_close(step, windows)
        self._update_others_timer.start(CLOSE_OTHERS_POLL_MS)

    def _request_close(self, step, windows):
        """windows에 닫기 요청을 보내는 뒤 스레드를 시작 (결과는 _on_close_requested) — 그 창들은 끝나기를 기다릴 창에."""
        step.closing.extend(windows)
        work = OthersWork(functools.partial(request_close_all, list(windows)))
        work.done.connect(self._on_close_requested)
        work.failed.connect(self._on_others_work_failed)
        step.work = work
        work.start()

    def _on_close_requested(self, answers):
        """(GUI 스레드) 닫기 요청의 답을 기록에 — 답하지 않은 창도 늦게 받은 요청으로 닫힐 수 있어 끝나기를 계속 기다림."""
        step = self._take_others_work()
        if step is None:
            return
        lines = "".join(f"\n  {window.label}: " + ("받음" if problem is None else f"답 없음 — 끝나기를 계속 기다림 ({problem})")
                        for window, problem in answers)
        _log_update(f"업데이트 {step.run.version}: 닫기 요청의 답{lines}")

    def _poll_closing_others(self):
        """(타이머 슬롯, GUI 스레드) 닫기를 요청한 창의 프로세스가 모두 끝났고(창 기록이 아니라 instances.is_running — 기록은
        닫기를 시작할 때 지워짐) 새로 켜진 창이 없으면 도우미에 넘김. 그사이 새로 켜진 창(창 기록)에는 묻지 않고 닫기를 요청.
        CLOSE_OTHERS_TIMEOUT_S가 지나도 끝나지 않은 창이 있으면 업데이트를 멈춤. 슬롯이라 예외를 밖으로 내지 않음 — 확인하다
        난 예외는 실패 창 (트레이스백째)."""
        step = self._update_others
        if step is None or step.deadline is None:
            return
        run = step.run
        try:
            if step.work is None:  # 닫기 요청을 보내는 중이 아닐 때 새로 켜진 창을 셈
                asked = {window.record for window in step.closing}
                appeared = [OtherWindow(record) for record in instances.others(run.others_app_path)
                            if record not in asked]
                if appeared:
                    _log_update(f"업데이트 {run.version}: 다른 창을 닫는 동안 새로 켜진 창 {len(appeared)}개 — 묻지 않고 "
                                "닫기를 요청: " + ", ".join(f"pid {window.pid}" for window in appeared))
                    self._request_close(step, appeared)
            running = [window for window in step.closing if instances.is_running(window.record)]
        except Exception:
            self._others_failed(step, traceback.format_exc())
            return
        running_pids = {window.pid for window in running}
        for window in step.closing:
            if window.pid not in running_pids and window.pid not in step.ended:
                step.ended.add(window.pid)
                _log_update(f"업데이트 {run.version}: 다른 창이 끝남 — {window.label}")
        if not running and step.work is None:
            _log_update(f"업데이트 {run.version}: 다른 창 {len(step.closing)}개가 모두 끝남 — 도우미에 넘김")
            self._end_others()
            self.setEnabled(True)  # _hand_off가 도우미를 띄운 뒤 다시 쓰지 못하게 함 (띄우지 못하면 창을 그대로 씀)
            self._hand_off(run, step.prepared)
            return
        if running and time.monotonic() >= step.deadline:
            self._stop_for_open_windows(step, running)

    def _stop_for_open_windows(self, step, running):
        """정해진 시간에 끝나지 않은 창이 있음 → 앱을 바꾸지 않음: 받은 것을 지우고 띠는 다시 알림, "업데이트를 멈췄습니다 —
        이 창이 닫히지 않았습니다: (창 제목·영상 이름·pid)" 창. 누른 창은 그대로."""
        run = step.run
        names = ", ".join(window.label for window in running)
        _log_update(f"업데이트 {run.version}: {CLOSE_OTHERS_TIMEOUT_S:g}초 안에 닫히지 않은 창 {len(running)}개 — "
                    f"업데이트를 멈춤 (앱은 그대로): {names}")
        self._give_up_update(step)
        QMessageBox.warning(self, UPDATE_STOPPED_TITLE,
                            f"{UPDATE_STOPPED.format(windows=names)}\n\n지금 버전({run.current})은 그대로입니다. 그 창을 "
                            "닫은 뒤 다시 '업데이트'를 누르세요.")

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
        """(GUI 스레드) 받기(+ Mac 준비)가 끝남: 그사이 취소를 눌렀으면 받은 것을 지우고 멈춤. 아니면 다른 창을 다시 확인
        (_check_other_windows — 받는 동안 새로 시작한 작업·바뀐 창은 다시 묻고, 다른 창을 닫은 뒤 도우미에 넘김)."""
        run = self._end_update_download()
        if run is None:
            return
        _log_update(f"업데이트 {run.version}: 받기 끝 — {prepared}")
        if run.download.is_cancelled():  # 다 받은 뒤, 이 결과가 오기 전에 '취소'를 누름
            if self._discard_prepared(run, prepared):
                self._update_cancelled(run)
            return
        self._check_other_windows(run, prepared)

    def _hand_off(self, run, prepared):
        """업데이트 기록(다시 켜진 앱이 결과를 판정) → 도우미(앱이 끝나기를 기다렸다 바꾸고 다시 켬) → 도우미가 시작 기록을
        남기면 창을 닫고 앱을 끝냄 (_poll_update_helper — 창 닫기가 진행 중인 작업을 멈춤). 기록·도우미가 실패하면 기록을
        지우고 실패 창, 앱은 그대로.

        도우미가 정말 시작했는지 본 뒤에만 끝냄: 띄운 도우미가 곧 끝나거나(그룹 정책 AllSigned·Constrained Language Mode·
        백신이 `powershell -ExecutionPolicy Bypass -File …`을 막음 등) 시작 기록을 남기지 않으면, 앱이 끝난 뒤 다시 켜 줄 것이
        없음. 기다리는 동안(보통 1~3초, 최대 UPDATE_HELPER_START_TIMEOUT_MS) 창은 그대로 돌되 쓰지 못하게 함 — 새로 시작한
        작업을 넘긴 뒤 창 닫기가 묻지 않고 멈추지 않게.

        기록에는 무작위 토큰(도우미가 다시 켜는 앱에 넘김 — 그 앱만 결과를 판정, 업데이트 중에 사용자가 켠 앱은 기록을
        건드리지 않음)과 이 창의 pid(실패 창에 이 창의 기록 줄만)를 남기고, 도우미를 띄운 뒤 그 pid를 더해 다시 씀(도우미가
        도는 동안 새로 켜는 앱은 '업데이트 중' 창만 — update_install.update_in_progress). 다시 쓰지 못하면 도우미를 끝내고
        실패 (_helper_start_failed)."""
        pending = update_install.Pending(target=run.version, previous=run.current, platform_key=run.platform_key,
                                         started=update_install.timestamp(), token=secrets.token_hex(8),
                                         app_pid=str(os.getpid()))
        try:
            update_install.write_pending(pending)
            _log_update(f"업데이트 {run.version}: 업데이트 기록을 남김 ({pending})")
            log_offset = update_install.log_size()  # 이 뒤에 이번 도우미의 시작 기록이 있어야 함
            if run.mac:
                proc = update_install.launch_helper_mac(prepared, run.app_path, run.version, pending.token)
            else:
                proc = update_install.launch_helper_windows(prepared, run.app_path, run.version, pending.token)
            if proc is None:
                raise RuntimeError("도우미를 띄우는 함수가 도우미 프로세스를 돌려주지 않았습니다")
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
        timeout_s = self.UPDATE_HELPER_START_TIMEOUT_MS / 1000
        wait = _HelperStart(run, prepared, proc, pending, log_offset, time.monotonic() + timeout_s)
        try:
            recorded = dataclasses.replace(pending, helper_pid=str(proc.pid))
            update_install.write_pending(recorded)
            wait.pending = recorded
        except Exception as exc:
            self._helper_start_failed(
                wait, f"업데이트 기록에 도우미(pid {proc.pid})를 적지 못했습니다.\n{_failure_text(exc)}",
                "도우미를 끝내고 업데이트를 멈췄습니다 (그동안 켜는 YesonCheck가 업데이트 중인 것을 알 수 없음).")
            return
        _log_update(f"업데이트 {run.version}: 도우미를 띄움 (pid {proc.pid}, {prepared} → {run.app_path}) — 시작 기록을 "
                    f"기다림 (최대 {timeout_s:g}초)")
        self._update_helper = wait
        self.setEnabled(False)
        self.update_banner.show_progress(0, 0, HELPER_STARTING_TEXT, cancellable=False)
        self._update_helper_timer.start()
        self._poll_update_helper()  # 벌써 남겼으면 바로

    def _end_helper_wait(self):
        self._update_helper_timer.stop()
        wait, self._update_helper = self._update_helper, None
        return wait

    def _poll_update_helper(self):
        """(타이머 슬롯, GUI 스레드) 기다리는 도우미가 아직 돌고 시작 기록을 남겼으면 앱을 끝냄. 도우미가 끝났거나(시작 기록을
        남겼어도 — 앱이 끝나기를 기다려야 할 도우미가 끝났음) 시간이 지나면 실패. 슬롯이라 예외를 밖으로 내지 않음 — 확인하다
        난 예외도 실패로 보임 (트레이스백째)."""
        wait = self._update_helper
        if wait is None:
            return
        try:
            code = wait.proc.poll()
            if code is None:
                if update_install.helper_start_logged(wait.log_offset):
                    self._end_helper_wait()
                    self._quit_for_update(wait)
                    return
                if time.monotonic() < wait.deadline:
                    return  # 계속 기다림
                why = (f"업데이트 도우미가 {self.UPDATE_HELPER_START_TIMEOUT_MS / 1000:g}초 안에 시작 기록을 남기지 "
                       "않았습니다.")
            else:
                why = f"업데이트 도우미가 시작 기록 없이 끝났습니다 (종료 코드 {code})."
        except Exception:
            why = f"업데이트 도우미가 시작했는지 확인하지 못했습니다.\n{traceback.format_exc()}"
        self._end_helper_wait()
        self._helper_start_failed(wait, why)

    def _quit_for_update(self, wait):
        """도우미가 시작함 → 창을 닫고 앱을 끝냄 (도우미는 이 프로세스가 끝나기를 기다렸다 바꾸고 다시 켬)."""
        run = wait.run
        _log_update(f"업데이트 {run.version}: 도우미가 시작함 (pid {wait.proc.pid}) — 앱을 끝냄 (도우미가 바꾸고 다시 켬)")
        self.hide()  # 창 닫기가 진행 중인 작업이 멈추기를 기다리는 동안(작업마다 최대 몇 초) 멈춘 창이 보이지 않게
        try:
            self.close()
        finally:
            QApplication.instance().quit()  # 도우미는 이 프로세스가 끝나기를 기다림 — 닫기에서 무슨 일이 있어도 끝냄

    def _stop_helper(self, proc):
        """시작하지 못한 도우미를 끝냄 → 끝났으면 None, 끝내지 못했으면 그 이유 (트레이스백째)."""
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)  # 강제로 끝냈으므로 곧 끝남
            return None
        except Exception:
            return traceback.format_exc()

    def _helper_start_failed(self, wait, why, note=HELPER_BLOCKED_NOTE):
        """도우미가 시작하지 못함(또는 그 pid를 기록에 쓰지 못함) → 도우미를 끝내고(돌고 있으면) 업데이트 기록을 지운 뒤
        "업데이트 실패" 창(why·note, 그 뒤의 기록과 도우미 출력째), 앱은 그대로·띠는 다시 알림. 도우미를 끝내지 못하면 기록은
        남겨 둠 — 그 도우미가 나중에(앱이 끝난 뒤) 바꾸면 새 앱이 그 기록(토큰)으로 '잘 켜짐'을 남겨야 함."""
        run = wait.run
        not_stopped = self._stop_helper(wait.proc)
        tail, extra = _update_log_report(wait.pending)
        # 기록에는 이유와 도우미 출력만 (출력 파일은 다음 업데이트에서 새로 쓰므로 그 내용이 남는 곳은 기록뿐)
        _log_update(f"업데이트 {run.version}: {why} 앱은 끝내지 않음{extra}")
        text = (f"{why}\n{note}\n\n"
                f"업데이트 기록 ({update_install.log_path()}, {wait.pending.started}부터):\n{tail}{extra}")
        if not_stopped is not None:
            _log_update(f"업데이트 {run.version}: 도우미(pid {wait.proc.pid})를 끝내지 못함 — 업데이트 기록은 남겨 둠\n"
                        f"{not_stopped}")
            text += (f"\n\n게다가 도우미(pid {wait.proc.pid})를 끝내지 못했습니다 — 업데이트 기록은 남겨 둡니다 (앱이 끝난 "
                     f"뒤 그 도우미가 바꿀 수 있음).\n{not_stopped}")
        else:
            try:
                update_install.clear_pending()  # 넘기지 못함 — 다음에 켤 때 이 기록으로 실패를 알리지 않게
            except Exception:
                text += ("\n\n게다가 업데이트 기록을 지우지 못했습니다 — 다음에 켤 때 업데이트 실패로 알릴 수 있습니다.\n"
                         + traceback.format_exc())
        self.setEnabled(True)  # 실패 창보다 먼저 (쓰지 못하게 한 창의 자식 창도 쓰지 못함)
        self._show_update_failure(run, text, log_text=False)

    def _on_update_download_failed(self, text):
        """(GUI 스레드) 받기·준비 실패 → 실패 창, 띠는 다시 알림. 그다음 같은 곳들(NAS·GitHub)을 곧바로 다시 확인 (자동 확인
        — 알리던 버전이 그새 내려갔거나 바뀌었으면 띠가 지금 있는 것을 알리게: 3시간 뒤의 확인까지 없는 것을 다시 받지 않게).
        다른 곳에서 저절로 받지는 않음 — 다시 '업데이트'를 누를 때의 알림으로."""
        run = self._end_update_download()
        if run is None:
            return
        self._show_update_failure(run, text, log_text=False)  # 이유는 받기 스레드가 기록함
        _log_update(f"업데이트 {run.version}: 받기에 실패해 새 버전을 다시 확인함 (알림 띠가 지금 있는 것을 보이게)")
        self.start_update_check(manual=False)

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
        """"업데이트 실패" 창: 본문은 이유 한 줄·출처(NAS/GitHub)·위치, 이유 전부(트레이스백·기록)는 자세히. 띠는 먼저
        알림으로 되돌림 — 다른 곳에서 저절로 받지 않음. log_text: 이유도 업데이트 기록에 (False — 이미 기록함: 받기 스레드·
        넘기기)."""
        reason = f"\n{text}" if log_text else " — 이유는 위의 기록"
        _log_update(f"업데이트 {run.version}: 실패 ({run.source}: {run.location}), 실패 창{reason}")
        self._restore_update_offer(run)
        show_details_box(
            self, UPDATE_FAILED_TITLE,
            f"{run.version}로 업데이트하지 못했습니다.\n\n{_summary(text)}\n\n출처: {run.source}\n위치: {run.location}\n\n"
            f"지금 버전({run.current})은 그대로입니다. 다시 '업데이트'를 누르면 처음부터 다시 받습니다.\n\n{DETAILS_HINT}",
            text,
        )

    def stop_update_download(self):
        """(창을 닫을 때) 받는 중이면 멈추라고 알리고(cancel — 받던 .part·준비하던 앱은 스레드가 지움) 끝날 때까지
        붙잡아 둠 (release_worker — 결과 신호를 막음: 닫은 뒤에는 업데이트 기록·도우미로 넘어가지 않음). 다른 창을
        확인하거나 닫는 중이면 그것을 멈추고(닫기를 요청한 창은 그대로 닫힘) 받은 것이 있으면 지움 — 못 지우면 이유째 기록에만
        (창은 닫히는 중). 도우미의 시작 기록을 기다리는 중이면 기다림만 멈춤 — 도우미와 업데이트 기록은 그대로 (앱이 끝나면
        도우미가 업데이트함)."""
        step = self._end_others()
        if step is not None:
            version = step.run.version
            if step.prepared is None:
                _log_update(f"업데이트 {version}: 다른 창을 확인하는 중에 창을 닫음 — 받지 않음")
            else:
                try:
                    remove_prepared(step.prepared)
                except Exception:
                    _log_update(f"업데이트 {version}: 넘기기 전에 창을 닫음 — 받은 것을 지우지 못함 ({step.prepared})\n"
                                f"{traceback.format_exc()}")
                else:
                    _log_update(f"업데이트 {version}: 넘기기 전에 창을 닫음 — 넘기지 않고 받은 것을 지움 ({step.prepared})")
        wait = self._end_helper_wait()
        if wait is not None:
            _log_update(f"업데이트 {wait.run.version}: 도우미의 시작 기록을 기다리는 중에 창을 닫음 — 도우미(pid "
                        f"{wait.proc.pid})는 그대로 둠 (앱이 끝나면 업데이트함)")
        run, self._update_run = self._update_run, None
        if run is None:
            return
        run.download.cancel()
        release_worker(run.download, "업데이트 받기")
        UpdateDownload._running.discard(run.download)  # 이제 release_worker가 붙잡음 (신호를 막아 finished로는 놓지 못함)
        _log_update(f"업데이트 {run.version}: 창을 닫음 — 받기를 멈춤")  # 놓은 뒤에 (기록이 실패해도 스레드는 놓임)

    # ---- 다시 켜진 앱: 지난 업데이트의 결과 ----

    def handle_update_startup(self, update_token: str | None) -> None:
        """(창을 보인 뒤 한 번 — app.launch) 지난 업데이트의 기록(pending_update.json)이 있으면 지금 버전과 비교
        (update_install.startup_result — 목표 버전이면 "잘 켜짐" 표시를 남겨 도우미가 기다림을 끝냄). update_token: 도우미가
        켠 앱이면 받은 `--update-result`의 토큰 (아니면 None — 토큰이 있는 기록은 건드리지 않음). 성공이면 띠에 잠깐
        "{버전}로 업데이트했습니다"와 받아 둔 설치 파일을 지움(remove_downloads), 실패(예전 버전이 켜짐 — 도우미가 되돌림)면 "업데이트 실패" 창에 그 뒤의 업데이트 기록과
        도우미 출력 중 기록에 없는 것(update_install.helper_console_extra).
        이 컴퓨터의 파일만 읽음 (NAS·인터넷 없음). 소스 실행은 아무것도 하지 않음. 기록이 깨졌으면 창에 보인 뒤 지움
        (켤 때마다 같은 창이 뜨지 않게). 예상 못 한 오류는 트레이스백째 창."""
        info = build_info.current()
        if info is None:
            return
        try:
            result = update_install.startup_result(info.version, update_token)
        except update_install.UpdateError as exc:
            _log_update(f"켜짐: 업데이트 기록을 읽지 못함 — 보이고 지움\n{exc}")
            try:
                update_install.clear_pending()
                cleared = "기록은 지웠습니다."
            except OSError as clear_exc:
                cleared = f"기록을 지우지도 못했습니다: {type(clear_exc).__name__}: {clear_exc}"
            show_details_box(self, UPDATE_FAILED_TITLE,
                             f"지난 업데이트의 결과를 알 수 없습니다 — 업데이트 기록이 깨졌습니다.\n\n{cleared}\n\n{DETAILS_HINT}",
                             str(exc))
            return
        except Exception:
            text = traceback.format_exc()
            _log_update(f"켜짐: 지난 업데이트의 결과를 확인하다 예상치 못한 오류\n{text}")
            show_details_box(self, UPDATE_FAILED_TITLE,
                             f"지난 업데이트의 결과를 확인하다 예상치 못한 오류가 났습니다.\n\n{_summary(text)}\n\n{DETAILS_HINT}",
                             text)
            return
        if result is None:
            return
        kind, pending = result
        if kind == "ok":
            message = UPDATED_MESSAGE.format(version=pending.target)
            _log_update(f"켜짐: {message} (전 버전 {pending.previous})")
            self.update_banner.show_message(message)
            remove_downloads()
            return
        # 도우미가 기록을 쓰기 전에 실패했으면(PowerShell·bash가 스크립트를 시작하지 못함 등) 그 이유는 도우미 출력에만 있음
        tail, extra = _update_log_report(pending)
        # 기록에도 — 도우미 출력 파일은 다음 업데이트에서 새로 쓰므로 그 내용이 남는 곳은 기록뿐
        _log_update(f"켜짐: {pending.target}로 업데이트하지 못해 {pending.previous}이(가) 켜짐 — 실패 창{extra}")
        show_details_box(
            self, UPDATE_FAILED_TITLE,
            f"{pending.target}로 업데이트하지 못했습니다 — 지금 버전 {pending.previous}이(가) 그대로 켜졌습니다.\n\n"
            f"업데이트 기록: {update_install.log_path()} ({pending.started}부터)\n\n{DETAILS_HINT}",
            f"업데이트 기록 ({update_install.log_path()}, {pending.started}부터):\n{tail}{extra}",
        )
