"""업데이트 끝까지 시험 (CI — Windows·Mac Intel·Mac Apple Silicon): 빌드된 앱이 NAS 흉내 폴더의 새 버전으로 실제로
업데이트하는지(성공 경로), 같은 설치의 다른 창이 켜져 있어도 그 창을 정상 종료로 닫고 업데이트하는지(다른 창 경로), 새 버전이
잘 켜지지 않으면 옛 버전으로 되돌리는지(되돌리기 경로).

  Windows: python ci/update_e2e.py --platform windows --app-dist dist\\YesonCheck_Autocut --installer <원래 설치 파일>
           --iscc <ISCC.exe> --share-root C:\\yc_share\\yc_update --unc \\\\localhost\\yc_test\\yc_update --work C:\\yc_update
  Mac:     python ci/update_e2e.py --platform mac --app-dist dist/YesonCheck_Autocut_<라벨>.app --work "$RUNNER_TEMP/yc_update"

새 버전 꾸러미는 같은 빌드에서 build_info.json의 버전만 바꿔 만든다 — Windows: dist 복사본을 고쳐 installer\\yesoncheck.iss를
워크플로와 같은 ISCC 명령(/DAppVersion=… /DAppFileTag=…)으로 컴파일 (저장소와 같은 모양의 복사본 폴더에서), Mac: ditto 복사본을
고쳐 codesign --force --sign -(ad-hoc)으로 다시 서명하고 build_app.sh처럼 hdiutil create. 옛 앱은 원래 빌드 그대로 — Windows:
원래 설치 파일로 <경우>\\apps\\YesonCheck에 조용히 설치, Mac: <경우>/yc_apps/YesonCheck_Autocut_<라벨>.app에 ditto.
make_test_data.py --update-dir이 가짜 공유 설정의 updates/에 꾸러미와 latest.json(version 99.0.0, 이 플랫폼 항목)을 둔다.
같은 꾸러미를 쓰는 경우(success·other_window — package_groups)는 하나만 만들어 복사한다.

경우 셋 (각각 <work>/<경우> 아래, 업데이트 상태 폴더도 따로):
- success: 꾸러미 99.0.0 → 옛 앱 --smoke-test(update 시나리오: 알림 → 받기 → 도우미에 넘김) → 도우미 기록 "업데이트 끝: 99.0.0",
  설치된 앱의 버전 99.0.0, 새 앱 프로세스가 떠 있음, 업데이트 기록(pending_update.json)이 지워짐, 백업 없음, (Windows) 다음
  로그인의 되살림이 남지 않음, 받은 설치 파일·dmg를 새 앱이 지움 → 새 앱을 끝냄.
- other_window: success와 같은 꾸러미. 옛 앱을 먼저 하나 더 켜 두고(사용자가 켠 다른 창 — 창 기록이 생길 때까지 기다림) 옛 앱
  --smoke-test(update 시나리오, make_test_data.py --close-others: '다른 창도 닫고 업데이트' 확인 창에 [모두 닫고 업데이트]) →
  확인 창이 다른 창 1개를 알림, 업데이트 기록에 묻기 → 받기 → 다른 창에 닫기 요청(request_close) → 그 창이 끝남 → 도우미에
  넘김 순서, 다른 창은 종료 코드 0(정상 종료), 그 뒤는 success와 같음 (켜진 앱은 새 앱 하나).
- rollback: latest.json은 99.0.0인데 새 앱이 '잘 켜짐' 표시를 쓰지 않음 (Windows: 꾸러미 버전 98.0.0, Mac: 꾸러미의
  build_info는 99.0.0이고 실행 파일은 바로 exit 1 하는 스크립트) → 도우미 기록에 되돌림, 설치된 앱의 버전이 옛 것, 다시 켜진
  옛 앱이 60초 안에 업데이트 기록을 지움(실패를 알렸다는 뜻), 백업 없음 → 옛 앱을 끝냄.
앱 환경: YESONCHECK_CONFIG_DIR(가짜 공유 설정 — Windows는 UNC), YESONCHECK_UPDATE_URL=off, QT_QPA_PLATFORM(Mac offscreen,
Windows는 실제 화면 windows — APP_ENV의 설명),
YC_UPDATE_DIRECT_LAUNCH=1, YC_UPDATE_OK_TIMEOUT_S=60, YC_UPDATE_NO_MESSAGEBOX=1, 업데이트 상태 폴더는 작업 폴더 아래
(Windows LOCALAPPDATA, Mac HOME). PYTHONUTF8은 뺌 (사용자 PC와 같게 — ci/run_smoke_test.ps1처럼).
Mac: 빌드 앱은 처음 켤 때 한 번 동영상 기본 앱을 묻는다(모달 창 — default_app.ask_at_start). 이 시험이 보통으로 켜는 앱(다른 창
경로의 다른 창)이 그 창에 멈추거나 이 러너의 LaunchServices를 읽지 않게, 경우마다 사용자 폴더(HOME)의 prefs.json에 앱과 같은
파일·키로 '이미 답함'을 남겨 둔다(answer_default_app_ask — 앱에 시험용 스위치를 두지 않음). 다른 창 경로는 그 창의 기록에
'이미 답함' 줄이 있는지도 본다(check_default_app_not_asked). 도우미가 다시 켜는 앱(--update-result)은 원래 묻지 않는다.

전체 제한 시간(--time-limit-min, 워크플로 단계의 timeout-minutes보다 몇 분 짧게)이 지나면 기다리던 단계가 실패해 단계가 끊기기
전에 진단을 보인다. 단계마다 이름을 찍고, 실패하면 그 단계·트레이스백·도우미 기록(update.log)·도우미 출력
(update_helper_console.txt)·앱 기록(빌드 앱은 창(프로세스)마다 yesoncheck_<날짜>_<pid>.log — 옛 앱·다른 창·도우미가 다시 켠
앱: Windows %LOCALAPPDATA%\\YesonCheck\\logs, Mac ~/Library/Logs/YesonCheck, 둘 다 경우의 사용자 폴더 아래 — app_logs; 기록
파일을 열기 전의 출력은 옛 앱·다른 창의 stdout·stderr, Mac 도우미가 직접 켠 앱의 것은 update.log)·smoke_result.json·설치
폴더 상태를 보이고 종료 코드 1.
끝낼 때 작업 폴더 아래의 실행 파일로 도는 프로세스(앱·설치 파일)와 작업 폴더의 도우미 스크립트를 실행 중인 프로세스를 모두 끝냄.
"""

import argparse
import contextlib
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from yesoncheck import build_info, instances, update_install  # noqa: E402

WINDOWS = sys.platform == "win32"
NEW_VERSION = "99.0.0"
BROKEN_WINDOWS_VERSION = "98.0.0"  # Windows 되돌리기 경로의 꾸러미 버전 (latest.json은 NEW_VERSION)
EXE_NAME = update_install.APP_EXECUTABLE_NAME
WINDOWS_APP_DIR_NAME = "YesonCheck"
MAC_APP_PREFIX = "YesonCheck_Autocut_"
MAC_LABELS = ("Intel", "AppleSilicon")
WINDOWS_MAC_ROOT = "/Volumes/yc_update"  # Windows 경우의 공유 설정에 적는 Mac 경로 (변환표로 UNC가 됨)
# Windows 도우미가 설치 폴더의 이름을 바꾸기 전에 등록하는 다음 로그인의 되살림 (update_helper_windows.ps1) — 끝나면 지워져야 함
RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
RECOVER_VALUE = "YesonCheckUpdateRecover"
RECOVER_FILE_NAME = "update_recover.txt"  # 도우미 스크립트 옆

# 기다림마다의 한도 — 모두 전체 제한 시간(Deadline) 안에서만
INSTALL_TIMEOUT_S = 900  # 원래 설치 파일의 조용한 설치
ISCC_TIMEOUT_S = 1800  # 설치 파일 컴파일 (CI에서 약 7분 — 둘을 함께)
SMOKE_TIMEOUT_S = 900  # 옛 앱 실행 시험 (받기·Mac 새 앱 준비 포함)
HELPER_TIMEOUT_S = 900  # 도우미가 끝날 때까지 (Windows 조용한 설치 포함)
PENDING_CLEARED_S = 60  # 되돌린 옛 앱이 업데이트 기록을 지울 때까지
SECOND_WINDOW_START_S = 180  # 다른 창(옛 앱을 하나 더 켬)이 창 기록을 남길 때까지 (켜자마자 백신 검사 등으로 느릴 수 있음)
KILL_WAIT_S = 15
STAYS_RUNNING_S = 10  # 결과 확인: 켜진 앱이 이만큼 계속 떠 있어야 함 (켜진 뒤 메시지 창 등에서 죽으면 실패)
# 전체 제한 시간 기본값 (분) — 워크플로 단계의 timeout-minutes(Windows 45, Mac 30)보다 짧게: 남은 시간에 진단·정리
DEFAULT_TIME_LIMIT_MIN = {"windows": 38, "mac": 24}

# Qt 화면 플러그인. Windows는 offscreen을 쓰지 않고 실제 화면(windows — 사용자 PC와 같음, GitHub의 Windows 러너에는
# 데스크톱이 있음): Qt 5.15.2(Windows lock의 pyqt5-qt5)의 QMessageBox::showEvent는 Windows에서 qt_getWindowsSystemMenu로
# QGuiApplication::platformNativeInterface()->nativeResourceForWindow(...)를 부르는데, offscreen 플러그인은 nativeInterface()가
# 없어(기본 nullptr) 실제 메시지 창을 띄우는 순간 앱이 죽는다 — 되돌린 옛 앱의 '업데이트 실패' 창(CI 39286794460: 앱 기록이
# '실패 창' 줄에서 끝나고 몇 초 안에 프로세스가 사라짐). 실행 시험은 메시지 창을 바꿔 끼워 띄우지 않아 이 문제가 없었음
QT_PLATFORM = "windows" if WINDOWS else "offscreen"
# 다른 창 경로: 옛 앱이 묻는 확인 창(player_update — 실행 시험이 [모두 닫고 업데이트]로 답함)과 그 첫 줄 (다른 창 1개)
CLOSE_OTHERS_TITLE = "다른 창도 닫고 업데이트"  # player_update.UPDATE_OTHERS_TITLE
CLOSE_OTHERS_COUNT = "다른 YesonCheck 창 1개도 닫힙니다."  # player_update.OTHERS_COUNT.format(n=1)
CLOSE_ALL_BUTTON = "모두 닫고 업데이트"  # player_update.CLOSE_ALL_BUTTON
# (Mac) 처음 켤 때의 동영상 기본 앱 질문 (default_app — 드라이버는 Qt를 불러오지 않으므로 같은 값을 따로 둠, 시험이 비교):
# HOME 아래 설정 파일·'이미 답함' 키, 묻지 않고 넘어간 앱의 기록 줄
DEFAULT_APP_PREFS = ("Library", "Application Support", "YesonCheck", "prefs.json")  # default_app.prefs_path()
DEFAULT_APP_ASKED_KEY = "asked_default_video_app"  # default_app.ASKED_KEY
DEFAULT_APP_NOT_ASKED_LOG = "[기본 앱] 이미 답함 — 묻지 않음"  # default_app.ALREADY_ANSWERED_LOG

# 옛 앱(그리고 도우미가 물려받아 다시 켜는 앱)의 환경
APP_ENV = {
    "YESONCHECK_UPDATE_URL": "off",
    "QT_QPA_PLATFORM": QT_PLATFORM,
    "YC_UPDATE_DIRECT_LAUNCH": "1",
    "YC_UPDATE_OK_TIMEOUT_S": "60",
    "YC_UPDATE_NO_MESSAGEBOX": "1",
    "YC_UPDATE_INSTALL_TIMEOUT_S": "900",  # 설치 파일이 멈추면 도우미가 30분이 아니라 15분 뒤 끝내고 되돌림
}


class Deadline:
    """전체 제한 시간. left(cap): 이번 기다림에 쓸 초 (cap과 남은 시간 중 작은 것) — 다 썼으면 TimeoutError."""

    def __init__(self, minutes):
        self.minutes = minutes
        self.end = time.monotonic() + minutes * 60

    def left(self, cap):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"전체 제한 시간 {self.minutes:g}분이 지났습니다 (워크플로 단계가 끊기기 전에 멈추고 진단을 보임)")
        return min(cap, remaining)


DEADLINE = Deadline(DEFAULT_TIME_LIMIT_MIN["windows" if WINDOWS else "mac"])  # main이 --time-limit-min으로 다시 정함


class StepFailed(Exception):
    def __init__(self, name, text):
        super().__init__(name)
        self.name = name
        self.text = text


def step(case, name, func, *args):
    """단계 하나: 이름을 찍고 실행 → 결과. 예외는 StepFailed(단계 이름, 트레이스백)로."""
    title = f"[{case.name}] {name}" if case else name
    print(f"\n===== {title}", flush=True)
    started = time.monotonic()
    try:
        result = func(*args)
    except Exception:
        raise StepFailed(title, traceback.format_exc()) from None
    print(f"----- {title}: 끝 ({time.monotonic() - started:.1f}초)", flush=True)
    return result


def run(cmd, timeout, **kwargs):
    """명령 실행 (출력은 그대로 CI 로그로). 종료 코드가 0이 아니면 CalledProcessError."""
    print("$ " + subprocess.list2cmdline([str(c) for c in cmd]), flush=True)
    limit = DEADLINE.left(timeout)
    try:
        return subprocess.run(cmd, check=True, timeout=limit, **kwargs)
    except subprocess.TimeoutExpired:
        why = f"전체 제한 시간 {DEADLINE.minutes:g}분에 걸림" if limit < timeout else f"이 명령의 한도 {timeout}초"
        raise TimeoutError(f"{os.path.basename(str(cmd[0]))}이(가) {limit:.0f}초 안에 끝나지 않았습니다 ({why})")


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def under(path, root):
    """path가 root 아래인지 (Windows는 대소문자 무시)."""
    path = os.path.normcase(os.path.normpath(path))
    root = os.path.normcase(os.path.normpath(root))
    return path.startswith(root.rstrip(os.sep) + os.sep)


def free_space(*folders):
    """폴더마다 디스크 여유 (도우미·앱이 확인하는 여유: Windows 1.5 GB, Mac 3 GB — update_install.NEEDED_BYTES)."""
    lines = []
    for folder in folders:
        usage = shutil.disk_usage(folder)
        lines.append(f"{folder}: 남음 {usage.free / 1e9:.1f} GB / 전체 {usage.total / 1e9:.1f} GB")
    print("\n".join(lines), flush=True)
    return lines


# ---- 빌드 정보 ----


def build_info_dir(app):
    """앱 안의 build_info.json이 있는 폴더 — Windows <설치 폴더>\\_internal, Mac <앱>/Contents/Resources."""
    if WINDOWS:
        return os.path.join(app, "_internal")
    return os.path.join(app, "Contents", "Resources")


def app_version(app):
    return build_info.load(build_info_dir(app)).version


def patch_version(app, version):
    """앱 복사본의 build_info.json 버전만 바꿈 (나머지 항목 그대로) — 바꾼 뒤 build_info.load로 다시 읽어 확인."""
    path = os.path.join(build_info_dir(app), build_info.FILE_NAME)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["version"] = version
    os.remove(path)  # 같은 파일을 쓰는 다른 곳(하드 링크 등)을 바꾸지 않게 새 파일로
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    loaded = build_info.load(build_info_dir(app))
    assert loaded.version == version, loaded
    return loaded


def executable(app):
    if WINDOWS:
        return os.path.join(app, EXE_NAME + ".exe")
    return os.path.join(app, "Contents", "MacOS", EXE_NAME)


# ---- 경우 (성공·되돌리기) ----


@dataclass
class Case:
    name: str  # "success" | "other_window" | "rollback"
    root: str  # <work>/<name>
    share_root: str  # 가짜 공유 설정·작품 폴더를 만드는 이 컴퓨터의 경로
    config_dir: str  # 앱이 읽는 공유 설정 폴더 (Windows: UNC)
    unc: str | None  # Windows: share_root의 UNC (변환표)
    app: str  # 옛 앱 — Windows 설치 폴더, Mac .app
    package_version: str  # 꾸러미 안의 버전
    broken: bool  # 새 앱이 잘 켜지지 않는 꾸러미 (되돌리기 경로)
    other_window: bool = False  # 같은 설치의 다른 창을 켜 둔 채 업데이트 (다른 창 경로)
    old_version: str = ""

    @property
    def user_dir(self):  # Windows LOCALAPPDATA, Mac HOME
        return os.path.join(self.root, "user")

    @property
    def smoke_dir(self):
        return os.path.join(self.root, "smoke")

    @property
    def package_dir(self):
        return os.path.join(self.root, "package")

    @property
    def stdout_path(self):
        return os.path.join(self.root, "old_app_stdout.txt")

    @property
    def stderr_path(self):
        return os.path.join(self.root, "old_app_stderr.txt")

    @property
    def second_stdout_path(self):  # 다른 창의 출력 — 빌드 앱은 기록 파일(app_logs)을 열기 전의 것만 (그 뒤는 기록 파일에)
        return os.path.join(self.root, "second_window_stdout.txt")

    @property
    def second_stderr_path(self):
        return os.path.join(self.root, "second_window_stderr.txt")


def make_cases(args, work):
    cases = []
    for name, broken, other_window in (("success", False, False), ("other_window", False, True), ("rollback", True, False)):
        root = os.path.join(work, name)
        if WINDOWS:
            share_root = os.path.join(args.share_root, name)
            unc = args.unc.rstrip("\\") + "\\" + name
            config_dir = unc + "\\.yesoncheck"
            app = os.path.join(root, "apps", WINDOWS_APP_DIR_NAME)
            version = BROKEN_WINDOWS_VERSION if broken else NEW_VERSION
        else:
            share_root = os.path.join(root, "share")
            unc = None
            config_dir = os.path.join(share_root, ".yesoncheck")
            app = os.path.join(root, "yc_apps", os.path.basename(args.app_dist.rstrip("/")))
            version = NEW_VERSION  # Mac 되돌리기: build_info는 99.0.0, 실행 파일이 바로 끝남
        cases.append(Case(name, root, share_root, config_dir, unc, app, version, broken, other_window))
    return cases


def package_groups(cases):
    """같은 꾸러미(버전·잘 켜지는지)를 쓰는 경우끼리 [[처음 경우, …], …] — 처음 경우만 꾸러미를 만들고 나머지는 복사
    (share_package). 순서는 cases의 순서."""
    groups = {}
    for case in cases:
        groups.setdefault((case.package_version, case.broken), []).append(case)
    return list(groups.values())


def share_package(group):
    """group의 처음 경우가 만든 꾸러미 파일(하나)을 나머지 경우의 package 폴더로 복사 → 복사한 경우 이름들."""
    source = group[0]
    names = os.listdir(source.package_dir)
    assert len(names) == 1, f"[{source.name}] 꾸러미 폴더에 파일이 하나가 아닙니다: {source.package_dir} {names}"
    for case in group[1:]:
        os.makedirs(case.package_dir)
        shutil.copyfile(os.path.join(source.package_dir, names[0]), os.path.join(case.package_dir, names[0]))
        print(f"[{case.name}] 꾸러미: [{source.name}]의 {names[0]}을(를) 복사", flush=True)
    return [case.name for case in group[1:]]


@contextlib.contextmanager
def user_dir_env(case):
    """update_install의 상태 폴더 함수들이 이 경우의 앱과 같은 곳을 가리키게 (Windows LOCALAPPDATA, Mac HOME)."""
    key = "LOCALAPPDATA" if WINDOWS else "HOME"
    old = os.environ.get(key)
    os.environ[key] = case.user_dir
    try:
        yield
    finally:
        if old is None:
            del os.environ[key]
        else:
            os.environ[key] = old


def state_files(case):
    """이 경우의 앱·도우미가 쓰는 파일 (update_install의 함수 그대로)."""
    os.makedirs(case.user_dir, exist_ok=True)
    with user_dir_env(case):
        state = update_install.state_dir()
        helper = update_install.HELPER_WINDOWS_FILE_NAME if WINDOWS else update_install.HELPER_MAC_FILE_NAME
        return {
            "state": state,
            "log": update_install.log_path(),
            "pending": os.path.join(state, update_install.PENDING_FILE_NAME),
            "ok": update_install.ok_marker_path(),
            "helper": os.path.join(state, helper),
            "console": update_install.helper_console_path(),  # 도우미의 stdout·stderr
            "recover": os.path.join(state, RECOVER_FILE_NAME),  # (Windows) 되살림 정보
            "downloads": os.path.join(state, "downloads"),  # 받은 설치 파일·dmg
        }


def app_env(case):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUTF8"}
    env.update(APP_ENV)
    env["YESONCHECK_CONFIG_DIR"] = case.config_dir
    env["LOCALAPPDATA" if WINDOWS else "HOME"] = case.user_dir
    return env


# ---- 프로세스 ----


@dataclass
class Proc:
    pid: int
    exe: str  # 실행 파일 경로 (Mac은 명령 줄의 첫 부분)
    command: str
    ppid: int = 0  # 부모 프로세스
    started: str = ""  # 만든 시각 (Windows CreationDate, Mac lstart)


def list_processes():
    if WINDOWS:
        script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | "
            "Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine, "
            "@{n='Created'; e={ if ($_.CreationDate) { $_.CreationDate.ToString('yyyy-MM-ddTHH:mm:ss.fff') } else { '' } }})"
        )
        out = subprocess.run([update_install._windows_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, check=True, timeout=120).stdout.decode("utf-8-sig")
        return [Proc(int(item["ProcessId"]), item.get("ExecutablePath") or "", item.get("CommandLine") or "",
                     int(item.get("ParentProcessId") or 0), item.get("Created") or "")
                for item in json.loads(out)]
    # lstart는 고정 폭 24자 ("Mon Oct 19 23:22:31 2026")
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,lstart=,command="], capture_output=True, text=True,
                         check=True, timeout=60).stdout
    procs = []
    for line in out.splitlines():
        pid_text, ppid_text, rest = line.strip().split(None, 2)
        started, command = rest[:24], rest[24:].strip()
        procs.append(Proc(int(pid_text), command, command, int(ppid_text), started))
    return procs


def describe_processes(procs):
    """프로세스마다 한 줄: pid·부모(pid와 명령 줄)·만든 시각·명령 줄 — 누가 언제 켰는지 알 수 있게."""
    by_pid = {p.pid: p for p in list_processes()}
    lines = []
    for proc in procs:
        parent = by_pid.get(proc.ppid)
        parent_text = f"{proc.ppid} {parent.command[:200]}" if parent else f"{proc.ppid} (이미 끝남)"
        lines.append(f"pid {proc.pid} (부모 {parent_text}) 만든 시각 {proc.started}: {proc.command[:300]}")
    return "\n".join(lines)


def contains(text, part):
    return part.lower() in text.lower() if WINDOWS else part in text


def runs_under(proc, root):
    """proc의 실행 파일이 root 아래인지 (Mac은 명령 줄의 앞부분 — 앱·도우미는 실행 파일을 전체 경로로 켬)."""
    if WINDOWS:
        return bool(proc.exe) and under(proc.exe, root)
    return any(proc.command.startswith(r.rstrip("/") + "/") for r in {root, os.path.realpath(root)})


def our_processes(roots, helper_scripts=()):
    """실행 파일이 roots 아래이거나 도우미 스크립트(helper_scripts)를 실행 중인 프로세스 (이 프로세스는 빼고)."""
    return [proc for proc in list_processes()
            if proc.pid != os.getpid()
            and (any(runs_under(proc, root) for root in roots)
                 or any(contains(proc.command, script) for script in helper_scripts))]


def app_processes(case):
    """이 경우의 설치된 앱(실행 파일) 프로세스."""
    exe = executable(case.app)
    if WINDOWS:
        return [p for p in our_processes([case.root]) if same_path(p.exe, exe)]
    return [p for p in our_processes([case.root]) if p.command == exe or p.command.startswith(exe + " ")]


def kill(procs):
    """procs를 끝내고 정말 끝났는지 확인 (Mac은 TERM → 15초 뒤 KILL, Windows는 TerminateProcess). 남으면 RuntimeError."""
    if not procs:
        return []
    for proc in procs:
        print(f"끝냄: pid {proc.pid} {proc.command[:300]}", flush=True)
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except OSError as exc:  # 그 사이에 끝났을 수 있음 — 아래에서 정말 끝났는지 확인
            print(f"  (pid {proc.pid}: {type(exc).__name__}: {exc})", flush=True)
    pids = {proc.pid for proc in procs}
    deadline = time.monotonic() + KILL_WAIT_S
    while True:
        alive = [p for p in list_processes() if p.pid in pids]
        if not alive:
            return [p.pid for p in procs]
        if time.monotonic() > deadline:
            break
        time.sleep(1)
    if not WINDOWS:
        for proc in alive:
            print(f"KILL: pid {proc.pid}", flush=True)
            with contextlib.suppress(ProcessLookupError):
                os.kill(proc.pid, signal.SIGKILL)
        time.sleep(2)
        alive = [p for p in list_processes() if p.pid in pids]
    if alive:
        raise RuntimeError("끝나지 않은 프로세스: " + ", ".join(f"pid {p.pid} {p.command[:200]}" for p in alive))
    return [p.pid for p in procs]


# ---- 새 버전 꾸러미 ----


def build_windows_installers(args, cases, work):
    """경우마다(cases — 꾸러미를 만드는 경우만, package_groups) dist 복사본의 버전을 바꿔 설치 파일을 컴파일 (둘을 함께 —
    하나에 약 7분) → 경우의 package 폴더로."""
    trees = []
    for case in cases:
        tree = os.path.join(work, "iss", case.name)
        dist_copy = os.path.join(tree, "dist", "YesonCheck_Autocut")
        print(f"[{case.name}] dist 복사: {args.app_dist} → {dist_copy}", flush=True)
        shutil.copytree(args.app_dist, dist_copy)
        print(f"[{case.name}] 꾸러미 버전: {patch_version(dist_copy, case.package_version)}", flush=True)
        # installer\yesoncheck.iss는 SourceDir=..(저장소 맨 위) 기준으로 dist\YesonCheck_Autocut·LICENSE·
        # THIRD_PARTY_NOTICES.md(·icon.ico가 있으면)를 읽음 → 같은 모양으로 둠
        os.makedirs(os.path.join(tree, "installer"))
        shutil.copyfile(os.path.join(REPO, "installer", "yesoncheck.iss"), os.path.join(tree, "installer", "yesoncheck.iss"))
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copyfile(os.path.join(REPO, name), os.path.join(tree, name))
        if os.path.exists(os.path.join(REPO, "icon.ico")):
            shutil.copyfile(os.path.join(REPO, "icon.ico"), os.path.join(tree, "icon.ico"))
        trees.append((case, tree))
    jobs = []
    try:
        for case, tree in trees:
            log_path = os.path.join(tree, "iscc_log.txt")
            cmd = [args.iscc, f"/DAppVersion={case.package_version}", f"/DAppFileTag={case.package_version}",
                   r"installer\yesoncheck.iss"]
            print(f"[{case.name}] $ {subprocess.list2cmdline(cmd)} (작업 폴더 {tree}, 출력 {log_path})", flush=True)
            with open(log_path, "wb") as log:
                jobs.append((case, tree, log_path,
                             subprocess.Popen(cmd, cwd=tree, stdout=log, stderr=subprocess.STDOUT)))
        codes = {}
        deadline = time.monotonic() + DEADLINE.left(ISCC_TIMEOUT_S)
        for case, _tree, _log_path, proc in jobs:
            try:
                codes[case.name] = proc.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                codes[case.name] = "제한 시간 안에 끝나지 않음"
    finally:
        for _case, _tree, _log_path, proc in jobs:
            if proc.poll() is None:  # 실패·시간 초과 — 띄운 컴파일러를 남기지 않음
                proc.kill()
                proc.wait(60)
    failures = []
    for case, tree, log_path, _proc in jobs:
        code = codes[case.name]
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        print(f"===== [{case.name}] ISCC 출력 끝 15줄 ({log_path})\n" + "\n".join(lines[-15:]), flush=True)
        setup = os.path.join(tree, "installer", f"YesonCheck_Setup_{case.package_version}.exe")
        if code != 0 or not os.path.isfile(setup):
            failures.append(f"[{case.name}] ISCC 실패 (종료 코드 {code}, 설치 파일 있음: {os.path.isfile(setup)})\n"
                            + "\n".join(lines[-80:]))
            continue
        os.makedirs(case.package_dir)
        shutil.move(setup, os.path.join(case.package_dir, os.path.basename(setup)))
        shutil.rmtree(os.path.join(tree, "dist"))  # 약 1.5 GB — 더 쓰지 않음
    if failures:
        raise RuntimeError("\n\n".join(failures))
    return {case.name: os.listdir(case.package_dir) for case in cases}


def mac_label(app_dist):
    name = os.path.basename(app_dist.rstrip("/"))
    label = name[len(MAC_APP_PREFIX):-len(".app")] if name.startswith(MAC_APP_PREFIX) and name.endswith(".app") else ""
    if label not in MAC_LABELS:
        raise ValueError(f"--app-dist는 {MAC_APP_PREFIX}<{'|'.join(MAC_LABELS)}>.app이어야 합니다: {app_dist}")
    return label


def build_mac_dmg(args, case, work):
    """ditto 복사본의 버전을 바꾸고(되돌리기 경로는 실행 파일을 바로 exit 1 하는 스크립트로) ad-hoc으로 다시 서명 →
    build_app.sh처럼 hdiutil create → 경우의 package 폴더에 YesonCheck_Autocut_<라벨>_<버전>.dmg."""
    label = mac_label(args.app_dist)
    stage = os.path.join(work, "dmg_stage", case.name)
    app_copy = os.path.join(stage, os.path.basename(args.app_dist.rstrip("/")))
    os.makedirs(stage)
    run(["ditto", args.app_dist, app_copy], timeout=900)
    print("꾸러미 버전:", patch_version(app_copy, case.package_version), flush=True)
    if case.broken:
        exe = executable(app_copy)
        os.remove(exe)
        with open(exe, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n# 업데이트 끝까지 시험: 잘 켜지지 않는 새 앱 ('잘 켜짐' 표시 없이 바로 끝남)\nexit 1\n")
        os.chmod(exe, 0o755)
        print(f"실행 파일을 바로 끝나는 스크립트로 바꿈: {exe}", flush=True)
    run(["codesign", "--force", "--sign", "-", app_copy], timeout=600)
    run(["codesign", "--verify", "--strict", app_copy], timeout=600)
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    os.makedirs(case.package_dir)
    dmg = os.path.join(case.package_dir, f"{MAC_APP_PREFIX}{label}_{case.package_version}.dmg")
    run(["hdiutil", "create", "-volname", f"{MAC_APP_PREFIX}{label}", "-srcfolder", stage, "-fs", "HFS+",
         "-format", "UDZO", "-ov", dmg], timeout=1800)
    shutil.rmtree(stage)
    print(f"{dmg} ({os.path.getsize(dmg):,} bytes)", flush=True)
    return dmg


# ---- 경우 하나의 단계 ----


def install_old_app(args, case):
    """옛 앱 = 원래 빌드: Windows는 원래 설치 파일로 조용히 설치, Mac은 ditto. → 그 버전."""
    os.makedirs(os.path.dirname(case.app), exist_ok=True)
    if WINDOWS:
        log = os.path.join(case.root, "install_old_app_log.txt")
        try:
            run([args.installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={case.app}", f"/LOG={log}"],
                timeout=INSTALL_TIMEOUT_S)
        except Exception:
            if os.path.exists(log):
                with open(log, encoding="utf-8", errors="replace") as fh:
                    print(f"===== 설치 기록 ({log})\n{fh.read()}", flush=True)
            raise
    else:
        run(["ditto", args.app_dist, case.app], timeout=900)
    assert os.path.isfile(executable(case.app)), f"옛 앱의 실행 파일이 없습니다: {executable(case.app)}"
    case.old_version = app_version(case.app)
    assert case.old_version == app_version(args.app_dist), \
        f"설치한 옛 앱의 버전 {case.old_version}이 빌드({app_version(args.app_dist)})와 다릅니다"
    print(f"옛 앱: {case.app} (버전 {case.old_version})", flush=True)
    return case.old_version


def make_shared_config(case, platform_key):
    """가짜 공유 설정·작품 폴더 + updates/(꾸러미 + latest.json) + 실행 시험 설정 (make_test_data.py --update-dir, 다른 창
    경로는 --close-others — 확인 창에 [모두 닫고 업데이트])."""
    cmd = [sys.executable, os.path.join(REPO, "ci", "make_test_data.py"), "--share-root", case.share_root,
           "--mac-root", WINDOWS_MAC_ROOT if WINDOWS else case.share_root, "--workdir", case.smoke_dir,
           "--update-dir", case.package_dir, "--update-version", NEW_VERSION, "--update-platform", platform_key]
    if case.unc:
        cmd += ["--unc", case.unc]
    if case.other_window:
        cmd += ["--close-others"]
    run(cmd, timeout=600)
    manifest = os.path.join(case.share_root, ".yesoncheck", "updates", "latest.json")
    with open(manifest, encoding="utf-8") as fh:
        print(f"{manifest}:\n{fh.read()}", flush=True)


def answer_default_app_ask(case):
    """(Mac) 이 경우의 사용자 폴더(HOME)의 prefs.json에 동영상 기본 앱 질문에 이미 답했다고 남김(앱이 [예]·[아니요] 뒤에 쓰는 것과
    같은 키 — default_app.record_asked) → 그 경로. 이 경우에서 켜는 빌드 앱은 묻지 않고(모달 창에 멈추지 않음) LaunchServices도
    읽지 않는다(default_app._ask_at_start). 새 폴더라 파일이 없어야 함."""
    path = os.path.join(case.user_dir, *DEFAULT_APP_PREFS)
    assert not os.path.exists(path), f"이 경우의 사용자 폴더에 이미 prefs.json이 있습니다: {path}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({DEFAULT_APP_ASKED_KEY: True}, fh)
    print(f"{path}: {read_text(path)}", flush=True)
    return path


def check_default_app_not_asked(case, pid):
    """(Mac) 보통으로 켠 다른 창(pid)이 동영상 기본 앱을 묻지 않았음: 그 창의 기록(yesoncheck_<날짜>_<pid>.log)에 '이미 답함'
    줄 — 빌드 앱이 묻기 판단까지 갔고 answer_default_app_ask의 prefs.json을 읽었다는 뜻."""
    logs = [path for path in app_logs(case) if path.endswith(f"_{pid}.log")]
    assert len(logs) == 1, f"다른 창(pid {pid})의 기록이 하나가 아닙니다: {logs}"
    text = read_text(logs[0])
    assert DEFAULT_APP_NOT_ASKED_LOG in text, \
        f"다른 창(pid {pid})의 기록에 '{DEFAULT_APP_NOT_ASKED_LOG}'이 없습니다 (묻는 창이 떴을 수 있음): {logs[0]}"
    print(f"다른 창(pid {pid}): 동영상 기본 앱을 묻지 않음 ({logs[0]})", flush=True)


def instance_record_path(case, pid):
    """이 경우의 앱이 남기는 창 기록 (instances.register — Windows LOCALAPPDATA, Mac HOME 아래)."""
    with user_dir_env(case):
        return os.path.join(instances.registry_dir(), f"{pid}.json")


def start_second_window(case):
    """같은 설치의 다른 창: 옛 앱을 인자 없이(사용자가 켠 것처럼 — 실행 시험이 아님) 켜고 그 창 기록(다른 창의 업데이트가 이
    창을 세고 상태를 묻고 닫기를 요청하는 곳)이 생기기를 기다림 → Popen. 기록 전에 끝나면 실패."""
    exe = executable(case.app)
    print("$ " + subprocess.list2cmdline([exe]), flush=True)
    with open(case.second_stdout_path, "wb") as out, open(case.second_stderr_path, "wb") as err:
        # 옛 앱처럼: Windows는 바로 가기처럼 작업 폴더를 설치 폴더로
        proc = subprocess.Popen([exe], env=app_env(case), cwd=case.app if WINDOWS else case.root, stdout=out, stderr=err)
    record = instance_record_path(case, proc.pid)
    started = time.monotonic()
    limit = DEADLINE.left(SECOND_WINDOW_START_S)
    while not os.path.isfile(record):
        code = proc.poll()
        if code is not None:
            raise AssertionError(f"다른 창(pid {proc.pid})이 창 기록을 남기기 전에 끝났습니다 (종료 코드 {code})")
        if time.monotonic() - started > limit:
            raise TimeoutError(f"다른 창(pid {proc.pid})이 {limit:.0f}초 안에 창 기록을 남기지 않았습니다: {record}")
        time.sleep(0.5)
    print(f"다른 창: pid {proc.pid}, 창 기록 {record} ({time.monotonic() - started:.1f}초)\n{read_text(record)}", flush=True)
    return proc


def run_old_app(case):
    """옛 앱 --smoke-test(update 시나리오) → 종료 코드 0, 모든 확인 통과, 대화상자 없음."""
    exe = executable(case.app)
    env = app_env(case)
    shown = {k: env[k] for k in [*APP_ENV, "YESONCHECK_CONFIG_DIR", "LOCALAPPDATA" if WINDOWS else "HOME"]}
    print(f"환경: {json.dumps(shown, ensure_ascii=False)}", flush=True)
    free_space(case.user_dir)
    cmd = [exe, "--smoke-test", case.smoke_dir]
    print("$ " + subprocess.list2cmdline(cmd), flush=True)
    started = time.monotonic()
    with open(case.stdout_path, "wb") as out, open(case.stderr_path, "wb") as err:
        # Windows: 바로 가기처럼 작업 폴더를 설치 폴더로 (도우미가 그 폴더의 이름을 바꿀 수 있어야 함)
        proc = subprocess.Popen(cmd, env=env, cwd=case.app if WINDOWS else case.root, stdout=out, stderr=err)
        limit = DEADLINE.left(SMOKE_TIMEOUT_S)
        try:
            code = proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(30)
            raise TimeoutError(f"옛 앱 실행 시험이 {limit:.0f}초 안에 끝나지 않았습니다 (대화상자에서 멈췄을 수 있음)") from None
    print(f"옛 앱이 끝남: 종료 코드 {code} ({time.monotonic() - started:.1f}초)", flush=True)
    result_path = os.path.join(case.smoke_dir, "smoke_result.json")
    assert os.path.isfile(result_path), f"smoke_result.json이 없습니다 (종료 코드 {code})"
    with open(result_path, encoding="utf-8") as fh:
        report = json.load(fh)
    for check in report["checks"]:
        print(f"  {'통과' if check['ok'] else '실패'}: {check['name']}", flush=True)
    failed = [c for c in report["checks"] if not c["ok"]]
    assert code == 0 and report.get("ok") and not failed and not report["dialogs"], \
        f"옛 앱 실행 시험 실패 (종료 코드 {code})\n{json.dumps(report, ensure_ascii=False, indent=2)}"
    return report


def check_close_others_answer(case, report):
    """실행 시험이 답한 창(smoke_test의 report["answered"]): 다른 창 경로만 '다른 창도 닫고 업데이트' 확인 창 — 다른 창 1개를
    알리고 [모두 닫고 업데이트]로 답함 (받은 뒤 다시 물었으면 둘). 다른 경우에는 없어야 함 (다른 창이 없음)."""
    answered = report.get("answered")
    assert answered is not None, "실행 시험 결과에 answered가 없습니다 (smoke_test가 이 시험과 다름)"
    if not case.other_window:
        assert not answered, f"다른 창이 없는데 확인 창에 답했습니다: {answered}"
        return answered
    assert answered, f"'{CLOSE_OTHERS_TITLE}' 확인 창이 뜨지 않았습니다 (다른 창을 세지 못함)"
    for box in answered:
        assert box["title"] == CLOSE_OTHERS_TITLE and box["answer"] == CLOSE_ALL_BUTTON, f"다른 확인 창에 답함: {box}"
        assert box["text"].startswith(CLOSE_OTHERS_COUNT), f"확인 창이 다른 창 1개를 알리지 않았습니다: {box['text']!r}"
    print(f"확인 창 {len(answered)}번: {answered[0]['text']!r} → [{CLOSE_ALL_BUTTON}]", flush=True)
    return answered


def wait_helper(case, files):
    """도우미(state 폴더의 스크립트 복사본을 실행 중인 프로세스)가 끝나기를 기다림 → 업데이트 기록(update.log) 글."""
    started = time.monotonic()
    limit = DEADLINE.left(HELPER_TIMEOUT_S)
    while True:
        running = our_processes([], [files["helper"]])
        if not running:
            break
        if time.monotonic() - started > limit:
            raise TimeoutError(f"도우미가 {limit:.0f}초 안에 끝나지 않았습니다: "
                               + ", ".join(f"pid {p.pid}" for p in running))
        time.sleep(2 if WINDOWS else 1)
    print(f"도우미가 끝남 ({time.monotonic() - started:.1f}초 기다림)", flush=True)
    text = read_text(files["log"])
    helper_lines = [line for line in text.splitlines() if " 도우미: " in line]
    print("\n".join(helper_lines), flush=True)
    assert any(" 도우미: 시작: " in line for line in helper_lines), (
        f"도우미가 시작 기록 없이 끝났습니다 (도우미가 돌지 않음) — 도우미 출력 ({files['console']}):\n"
        + (read_text(files["console"]) if os.path.isfile(files["console"]) else "(없음)"))
    return text


def leftovers(case):
    """앱 폴더 옆에 남은 것 (백업·준비한 새 앱·치운 새 버전)."""
    parent = os.path.dirname(case.app)
    return sorted(name for name in os.listdir(parent) if name != os.path.basename(case.app))


def helper_lines(log_text):
    """업데이트 기록에서 도우미가 쓴 줄의 내용 (" 도우미: " 뒤)."""
    return [line.split(" 도우미: ", 1)[1] for line in log_text.splitlines() if " 도우미: " in line]


def _assert_in_order(lines, expected, what):
    """lines에 expected의 글이 이 순서로 (각각 앞의 것보다 뒤의 줄에) 있는지."""
    position = 0
    for part in expected:
        found = next((i for i in range(position, len(lines)) if part in lines[i]), None)
        assert found is not None, (f"{what}에 {part!r}이(가) (앞 단계 뒤에) 없습니다\n기대 순서: {expected}\n"
                                   f"{what}:\n" + "\n".join(lines))
        position = found + 1


def assert_helper_sequence(log_text, expected):
    """도우미 줄에 expected의 글이 이 순서로 (각각 앞의 것보다 뒤의 줄에) 있는지."""
    _assert_in_order(helper_lines(log_text), expected, "도우미 기록")


def assert_log_sequence(log_text, expected):
    """업데이트 기록 전체(앱·도우미 줄)에 expected의 글이 이 순서로 있는지."""
    _assert_in_order(log_text.splitlines(), expected, "업데이트 기록")


def one_app_process(case, what):
    """이 경우의 설치된 앱 프로세스가 정확히 하나이고 STAYS_RUNNING_S초 동안 계속 떠 있는지 → [그 프로세스].

    앱(PyInstaller onedir)은 프로세스 하나로 돈다 — Windows·Mac 부트로더는 onedir에서 자식을 만들지 않음(onefile만,
    pyi_main.c). 둘이면 두 번 켜진 것이거나, 앱이 죽어 Windows 오류 보고가 만든 복제(process reflection, 같은 명령 줄)일 수
    있음 — 어느 쪽이든 실패. 실패 메시지에 부모·만든 시각."""
    running = app_processes(case)
    assert len(running) == 1, (f"{what} 프로세스가 하나가 아닙니다 ({len(running)}개): {executable(case.app)}\n"
                               + describe_processes(running))
    print(f"{what}: {describe_processes(running)}", flush=True)
    deadline = time.monotonic() + DEADLINE.left(STAYS_RUNNING_S)
    while time.monotonic() < deadline:
        time.sleep(1)
        now = app_processes(case)
        assert [p.pid for p in now] == [running[0].pid], (
            f"{what}(pid {running[0].pid})가 {STAYS_RUNNING_S}초 동안 혼자 떠 있지 않았습니다 — 지금: "
            + (describe_processes(now) or "없음 (끝났거나 죽음)"))
    return running


def success_sequence(windows):
    """성공 경로에서 도우미 기록에 이 순서로 있어야 하는 글 (update_helper_windows.ps1·update_helper_mac.sh의 Write-Log·log).
    Windows는 설치 폴더의 이름을 바꾸기 전에 다음 로그인의 되살림을 등록하고, 끝나며 지움."""
    if windows:
        replaced = ["다음 로그인에서 되살리도록 등록함", "설치 폴더를 백업 이름으로 바꿈", "설치 파일이 끝남 (종료 코드 0)",
                    "새 앱을 켬 (pid"]
        cleared = ["다음 로그인의 되살림 등록을 지움"]
    else:
        replaced = ["옛 앱을 백업 이름으로 옮김", "새 앱을 앱 자리로 옮김", "새 앱을 켬 (직접 실행, pid"]
        cleared = []
    return [*replaced, f"새 앱이 잘 켜짐 (버전 {NEW_VERSION})", "백업을 지움", *cleared, f"업데이트 끝: {NEW_VERSION}"]


def rollback_sequence(windows):
    """되돌리기 경로: 되돌린 이유가 '새 앱을 켰는데 잘 켜짐 표시가 없음'이어야 함 — 이름 바꾸기·설치 실패처럼 새 앱을 켜기
    전의 실패로 되돌린 것은 통과가 아님 (Windows: 98.0.0 앱은 떠 있지만 표시를 쓰지 않아 시간이 지남, Mac: 실행 파일이
    바로 끝남)."""
    if windows:
        launched = ["다음 로그인에서 되살리도록 등록함", "설치 파일이 끝남 (종료 코드 0)", "새 앱을 켬 (pid",
                    f"업데이트 실패: {APP_ENV['YC_UPDATE_OK_TIMEOUT_S']}초 안에 '잘 켜짐' 표시가 없음"]
        cleared = ["다음 로그인의 되살림 등록을 지움"]
        relaunched = "옛 앱을 켬 (pid"
    else:
        launched = ["새 앱을 켬 (직접 실행, pid", "업데이트 실패: 새 앱이 '잘 켜짐' 표시 없이 끝남"]
        cleared = []
        relaunched = "옛 앱을 켬 (직접 실행, pid"
    return [*launched, "되돌림 시작", "백업을 제자리로 되돌림", *cleared, "되돌림: 옛 앱을 다시 켬", relaunched]


def close_others_sequence():
    """다른 창 경로에서 업데이트 기록에 이 순서로 있어야 하는 글: 옛 앱(업데이트를 누른 창 — player_update의 _log_update)이
    다른 창도 닫을지 묻고 → 모두 닫기로 → 받고 → 다른 창 1개에 닫기를 요청하고 → 그 창이 끝난 뒤 → 도우미에 넘김, 그다음
    도우미가 시작."""
    v = NEW_VERSION
    return [f"업데이트 {v}: 다른 창도 닫고 업데이트할지 물음", f"업데이트 {v}: → {CLOSE_ALL_BUTTON}", f"업데이트 {v}: 받기 시작",
            f"업데이트 {v}: 다른 창 1개에 닫기를 요청하고", f"업데이트 {v}: 다른 창이 끝남 — ",
            f"업데이트 {v}: 다른 창 1개가 모두 끝남 — 도우미에 넘김", " 도우미: 시작: "]


def check_second_window_closed(case, second, log_text):
    """다른 창은 업데이트(옛 앱)의 닫기 요청으로 정상 종료했음: 그 프로세스가 종료 코드 0으로 끝났고, 업데이트 기록에
    close_others_sequence가 이 순서로."""
    code = second.poll()
    assert code is not None, f"다른 창(pid {second.pid})이 아직 돕니다 — 업데이트가 닫지 않았습니다"
    assert code == 0, f"다른 창(pid {second.pid})이 종료 코드 {code}로 끝났습니다 (정상 종료가 아님)"
    assert_log_sequence(log_text, close_others_sequence())
    assert not os.path.exists(instance_record_path(case, second.pid)), "다른 창의 창 기록이 남아 있습니다"
    print(f"다른 창(pid {second.pid}): 닫기 요청으로 끝남 (종료 코드 0)", flush=True)
    return code


def check_recover_cleared(files):
    """(Windows) 도우미가 끝난 뒤 다음 로그인의 되살림이 남아 있지 않은지 — 진짜 HKCU RunOnce 값과 되살림 정보 파일."""
    if not WINDOWS:
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUNONCE_KEY) as key:
            value = winreg.QueryValueEx(key, RECOVER_VALUE)[0]
    except FileNotFoundError:
        value = None
    assert value is None, f"도우미가 끝났는데 RunOnce에 되살림이 남아 있습니다: HKCU\\{RUNONCE_KEY} {RECOVER_VALUE} = {value}"
    assert not os.path.exists(files["recover"]), f"되살림 정보 파일이 남아 있습니다: {files['recover']}"


def check_success(case, files, log_text):
    assert_helper_sequence(log_text, success_sequence(WINDOWS))
    assert not any(line.startswith("업데이트 실패") for line in helper_lines(log_text)), "도우미가 실패를 기록했습니다"
    version = app_version(case.app)
    assert version == NEW_VERSION, f"설치된 앱의 버전 {version} (기대 {NEW_VERSION})"
    running = one_app_process(case, "새 앱")
    assert not os.path.exists(files["pending"]), f"새 앱이 업데이트 기록을 지우지 않았습니다: {files['pending']}"
    assert not leftovers(case), f"앱 옆에 남은 것: {leftovers(case)}"
    check_recover_cleared(files)
    left = os.listdir(files["downloads"]) if os.path.isdir(files["downloads"]) else []
    assert not left, f"업데이트한 새 앱이 받은 파일을 지우지 않았습니다 ({files['downloads']}): {left}"
    print(f"설치된 앱 {case.app}: 버전 {version}, 새 앱 pid {[p.pid for p in running]}, 백업 없음, 받은 파일 없음", flush=True)
    return kill(running)


def check_rollback(case, files, log_text):
    assert_helper_sequence(log_text, rollback_sequence(WINDOWS))
    assert not any(line.startswith("되돌리기 실패") for line in helper_lines(log_text)), "도우미가 되돌리지 못했습니다"
    version = app_version(case.app)
    assert version == case.old_version, f"설치된 앱의 버전 {version} (옛 버전 {case.old_version}이어야 함)"
    deadline = time.monotonic() + DEADLINE.left(PENDING_CLEARED_S)
    while os.path.exists(files["pending"]):
        assert time.monotonic() < deadline, \
            f"되돌린 옛 앱이 {PENDING_CLEARED_S}초 안에 업데이트 기록을 지우지 않았습니다 (실패를 알리지 않음): {files['pending']}"
        time.sleep(1)
    running = one_app_process(case, "되돌린 옛 앱")
    assert not leftovers(case), f"앱 옆에 남은 것: {leftovers(case)}"
    check_recover_cleared(files)
    print(f"설치된 앱 {case.app}: 옛 버전 {version}, 업데이트 기록 지워짐, 옛 앱 pid {[p.pid for p in running]}, "
          "백업 없음", flush=True)
    return kill(running)


def check_state_free_space(files, platform_key):
    """업데이트 상태 폴더(작업 폴더 아래로 돌린 곳)의 여유 공간이 앱이 확인하는 크기(update_install.NEEDED_BYTES) 이상인지 —
    모자라면 앱이 '여유 공간이 모자랍니다' 창을 띄워 실행 시험이 실패하므로 여기서 먼저 분명하게."""
    needed = update_install.NEEDED_BYTES[platform_key]
    free = shutil.disk_usage(files["state"]).free
    print(f"{files['state']}: 남음 {free / 1e9:.2f} GB (앱이 확인하는 크기 {needed / 1e9:.2f} GB)", flush=True)
    assert free >= needed, f"업데이트 상태 폴더의 여유 공간이 모자랍니다: 남음 {free:,} bytes, 필요 {needed:,} bytes ({files['state']})"


def remove_large_files(case):
    """다음 경우의 여유 공간: 이 경우의 앱(설치 폴더·.app), 꾸러미, 공유 설정의 updates/, 받은 파일을 지움 (기록은 둠).
    앱 프로세스는 결과 확인에서 끝냈음."""
    files = state_files(case)
    for path in (os.path.dirname(case.app), case.package_dir,
                 os.path.join(case.share_root, ".yesoncheck", "updates"), files["downloads"]):
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"지움: {path}", flush=True)
    free_space(case.root)


def run_case(args, case, platform_key):
    files = state_files(case)
    step(case, "옛 앱 준비 (원래 빌드)", install_old_app, args, case)
    step(case, "업데이트 상태 폴더의 여유 공간", check_state_free_space, files, platform_key)
    step(case, f"가짜 공유 설정 + updates/ (latest.json {NEW_VERSION}, 꾸러미 {case.package_version})",
         make_shared_config, case, platform_key)
    if not WINDOWS:
        step(case, "동영상 기본 앱 질문에 이미 답한 것으로 (prefs.json — 켜는 앱이 묻는 창에 멈추지 않게)",
             answer_default_app_ask, case)
    second = None
    if case.other_window:
        second = step(case, "같은 설치의 다른 창을 켬 (사용자가 켠 것처럼 — 창 기록이 생길 때까지)", start_second_window, case)
    report = step(case, "옛 앱 실행 시험 (update: 알림 → 받기 → 도우미에 넘김)", run_old_app, case)
    step(case, "확인 창 (다른 창 경로만 '다른 창도 닫고 업데이트' → 모두 닫고 업데이트)", check_close_others_answer, case, report)
    log_text = step(case, "도우미가 끝나기를 기다림", wait_helper, case, files)
    if case.broken:
        step(case, "결과: 되돌림 — 옛 버전, 옛 앱이 실패를 알림", check_rollback, case, files, log_text)
    else:
        if second is not None:
            step(case, "결과: 다른 창은 업데이트의 닫기 요청으로 정상 종료", check_second_window_closed, case, second, log_text)
            if not WINDOWS:
                step(case, "다른 창은 동영상 기본 앱을 묻지 않았음 (prefs.json)", check_default_app_not_asked, case, second.pid)
        step(case, f"결과: {NEW_VERSION}로 업데이트 — 새 앱이 켜짐", check_success, case, files, log_text)
    print(f"===== [{case.name}] 업데이트 기록 전체 ({files['log']})\n{read_text(files['log'])}", flush=True)


# ---- 실패했을 때 보이는 것 ----


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def show_file(title, path):
    if os.path.isfile(path):
        print(f"===== {title} ({path})\n{read_text(path)}", flush=True)
    else:
        print(f"===== {title}: 없음 ({path})", flush=True)


APP_LOG_PATTERN = "yesoncheck_*.log"  # 빌드 앱의 기록 (app.LOG_FILE_PATTERN — 창(프로세스)마다 yesoncheck_<날짜>_<pid>.log)


def app_logs(case):
    """이 경우의 앱 기록 (app.setup_app_logging — 옛 앱·다른 창·도우미가 다시 켠 앱이 각각 하나): 업데이트 기록(update.log)과
    같은 폴더(Windows <LOCALAPPDATA>\\YesonCheck\\logs, Mac <HOME>/Library/Logs/YesonCheck — 경우의 사용자 폴더 아래)의
    yesoncheck_*.log, 오래된 것(수정 시각)부터."""
    folder = os.path.dirname(state_files(case)["log"])
    return sorted(glob.glob(os.path.join(folder, APP_LOG_PATTERN)), key=os.path.getmtime)


def show_diagnostics(case):
    files = state_files(case)
    show_file("업데이트 기록 (앱·도우미 — Mac은 도우미가 직접 켠 앱이 기록 파일을 열기 전의 출력도)", files["log"])
    show_file("도우미 출력 (stdout·stderr — 기록을 쓰기 전의 실패도)", files["console"])
    show_file("도우미가 실행한 설치 파일의 기록", files["log"] + ".inno.txt")
    logs = app_logs(case)
    if not logs:
        print(f"===== 앱 기록: 없음 ({os.path.join(os.path.dirname(files['log']), APP_LOG_PATTERN)})", flush=True)
    for path in logs:
        show_file("앱 기록 (옛 앱·다른 창·도우미가 다시 켠 앱 중 하나 — 첫 줄의 pid)", path)
    show_file("옛 앱 stdout (기록 파일을 열기 전의 출력)", case.stdout_path)
    show_file("옛 앱 stderr (기록 파일을 열기 전의 출력)", case.stderr_path)
    if case.other_window:
        show_file("다른 창 stdout (기록 파일을 열기 전의 출력)", case.second_stdout_path)
        show_file("다른 창 stderr (기록 파일을 열기 전의 출력)", case.second_stderr_path)
    show_file("실행 시험 결과", os.path.join(case.smoke_dir, "smoke_result.json"))
    show_file("업데이트 기록 파일 (pending)", files["pending"])
    show_file("'잘 켜짐' 표시", files["ok"])
    if WINDOWS:
        show_file("되살림 정보", files["recover"])
    with user_dir_env(case):
        registry = instances.registry_dir()
    print(f"===== 창 기록 ({registry})", flush=True)
    for name in sorted(os.listdir(registry)) if os.path.isdir(registry) else []:
        print(f"  {name}: {read_text(os.path.join(registry, name))}", flush=True)
    parent = os.path.dirname(case.app)
    print(f"===== 설치 폴더 상태 ({parent})", flush=True)
    if os.path.isdir(parent):
        for name in sorted(os.listdir(parent)):
            path = os.path.join(parent, name)
            try:
                version = app_version(path)
            except Exception as exc:
                version = f"(빌드 정보 없음: {type(exc).__name__}: {str(exc).splitlines()[0]})"
            print(f"  {name}: 실행 파일 {'있음' if os.path.exists(executable(path)) else '없음'}, 버전 {version}", flush=True)
    else:
        print("  (폴더 없음)", flush=True)
    downloads = os.path.join(files["state"], "downloads")
    if os.path.isdir(downloads):
        print(f"받은 파일 ({downloads}): {os.listdir(downloads)}", flush=True)
    print("===== 이 경우의 프로세스 (부모·만든 시각)", flush=True)
    print(describe_processes(our_processes([case.root], [files["helper"]])) or "  (없음)", flush=True)
    if WINDOWS:
        show_windows_crash_reports()


def show_windows_crash_reports():
    """(Windows, 진단) 지난 90분의 앱 오류·Windows 오류 보고 이벤트(Application 기록)와 WER 보고서(Report.wer) 중
    YesonCheck_Autocut의 것 — 앱이 기록 없이 죽었을 때 예외 코드·오류 모듈."""
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "try { Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddMinutes(-90)} -ErrorAction Stop "
        "| Where-Object { $_.ProviderName -in @('Application Error','Windows Error Reporting','Application Hang') "
        "-and $_.Message -like '*YesonCheck*' } | ForEach-Object { '--- ' + $_.TimeCreated.ToString('o') + ' ' + "
        "$_.ProviderName + ' ' + $_.Id; $_.Message } } catch { '(이벤트 기록을 읽지 못함: ' + $_ + ')' }; "
        "foreach ($root in @(\"$env:ProgramData\\Microsoft\\Windows\\WER\", "
        "\"$env:LOCALAPPDATA\\Microsoft\\Windows\\WER\")) { foreach ($kind in @('ReportArchive','ReportQueue')) { "
        "Get-ChildItem -Path (Join-Path $root $kind) -Filter '*YesonCheck*' -Directory -ErrorAction SilentlyContinue "
        "| ForEach-Object { '--- ' + $_.FullName; Get-Content (Join-Path $_.FullName 'Report.wer') -ErrorAction Continue } } }"
    )
    done = subprocess.run([update_install._windows_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, timeout=120)
    print("===== Windows 앱 오류 이벤트·오류 보고 (YesonCheck, 지난 90분)\n"
          + (done.stdout + done.stderr).decode("utf-8-sig", errors="replace").strip(), flush=True)


# ---- 시작 ----


def parse_args():
    parser = argparse.ArgumentParser(description="빌드된 앱으로 업데이트 끝까지 시험 (성공·되돌리기)")
    parser.add_argument("--platform", required=True, choices=["windows", "mac"])
    parser.add_argument("--app-dist", required=True,
                        help=r"빌드된 앱 — Windows dist\YesonCheck_Autocut, Mac dist/YesonCheck_Autocut_<라벨>.app")
    parser.add_argument("--installer", help="(Windows) 이 빌드의 원래 설치 파일 — 옛 앱을 설치")
    parser.add_argument("--iscc", help="(Windows) Inno Setup 컴파일러 ISCC.exe — 새 버전 설치 파일을 만듦")
    parser.add_argument("--share-root", help=r"(Windows) 시험용 SMB 공유 안의 폴더 (예: C:\yc_share\yc_update)")
    parser.add_argument("--unc", help=r"(Windows) --share-root의 UNC (예: \\localhost\yc_test\yc_update)")
    parser.add_argument("--work", required=True, help="작업 폴더 (있으면 지우고 새로 만듦)")
    parser.add_argument("--time-limit-min", type=float,
                        help="전체 제한 시간 (분) — 워크플로 단계의 timeout-minutes보다 짧게 "
                             f"(기본 Windows {DEFAULT_TIME_LIMIT_MIN['windows']}, Mac {DEFAULT_TIME_LIMIT_MIN['mac']})")
    args = parser.parse_args()
    if (args.platform == "windows") != WINDOWS:
        parser.error(f"--platform {args.platform}을 이 컴퓨터({sys.platform})에서 돌릴 수 없습니다")
    windows_only = ["installer", "iscc", "share_root", "unc"]
    if WINDOWS:
        missing = [f"--{name.replace('_', '-')}" for name in windows_only if not getattr(args, name)]
        if missing:
            parser.error(f"Windows에는 {', '.join(missing)}이 있어야 합니다")
    elif any(getattr(args, name) for name in windows_only):
        parser.error("--installer·--iscc·--share-root·--unc는 Windows에만 씁니다")
    if args.time_limit_min is None:
        args.time_limit_min = DEFAULT_TIME_LIMIT_MIN[args.platform]
    elif args.time_limit_min <= 0:
        parser.error("--time-limit-min은 0보다 커야 합니다")
    args.app_dist = os.path.abspath(args.app_dist)
    if args.installer:
        args.installer = os.path.abspath(args.installer)
    return args


def main():
    global DEADLINE
    args = parse_args()
    DEADLINE = Deadline(args.time_limit_min)
    print(f"전체 제한 시간 {args.time_limit_min:g}분", flush=True)
    work = os.path.abspath(args.work)
    cases = make_cases(args, work)
    current = None
    failed = False
    try:
        platform_key = build_info.load(build_info_dir(args.app_dist)).platform_key
        print(f"앱: {args.app_dist} (버전 {app_version(args.app_dist)}, 플랫폼 {platform_key}), 작업 폴더 {work}", flush=True)
        if os.path.exists(work):
            step(None, "지난 작업 폴더 지우기", shutil.rmtree, work)
        os.makedirs(work)
        for case in cases:
            if os.path.exists(case.share_root):
                step(case, "지난 공유 폴더 지우기", shutil.rmtree, case.share_root)
            os.makedirs(case.share_root)
        step(None, "디스크 여유 (시작)", free_space, work, cases[0].share_root)
        groups = package_groups(cases)
        if WINDOWS:
            step(None, f"새 버전 설치 파일 만들기 ({NEW_VERSION}·{BROKEN_WINDOWS_VERSION}, ISCC 둘을 함께)",
                 build_windows_installers, args, [group[0] for group in groups], work)
        else:
            for group in groups:
                what = "실행 파일이 바로 끝남" if group[0].broken else "잘 켜짐"
                step(group[0], f"새 버전 dmg 만들기 ({group[0].package_version}, {what})", build_mac_dmg, args, group[0], work)
        for group in groups:
            if len(group) > 1:
                step(group[0], "같은 꾸러미를 쓰는 경우에 복사: " + ", ".join(c.name for c in group[1:]), share_package, group)
        for index, case in enumerate(cases):
            current = case
            run_case(args, case, platform_key)
            if index + 1 < len(cases):
                step(case, "큰 파일 지우기 (다음 경우의 여유 공간)", remove_large_files, case)
        current = None
        step(None, "디스크 여유 (끝)", free_space, work)
    except StepFailed as exc:
        failed = True
        print(f"\n##### 실패한 단계: {exc.name}\n{exc.text}", flush=True)
        if current is not None:
            try:
                show_diagnostics(current)
            except Exception:
                print(f"(진단 정보를 다 보이지 못함)\n{traceback.format_exc()}", flush=True)
    except Exception:
        failed = True
        print(f"\n##### 실패\n{traceback.format_exc()}", flush=True)
    finally:
        try:
            helper_scripts = [state_files(case)["helper"] for case in cases if os.path.isdir(case.user_dir)]
            left = our_processes([work], helper_scripts)
            if left:
                print("\n===== 끝내기 전에 남은 프로세스를 끝냄", flush=True)
                kill(left)
        except Exception:
            failed = True
            print(f"\n##### 남은 프로세스를 끝내지 못함\n{traceback.format_exc()}", flush=True)
    if failed:
        print("\n업데이트 끝까지 시험 실패", flush=True)
        return 1
    print("\n업데이트 끝까지 시험 통과 (성공·다른 창·되돌리기)", flush=True)
    return 0



if __name__ == "__main__":
    sys.exit(main())
