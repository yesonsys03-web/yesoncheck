"""업데이트 끝까지 시험 (CI — Windows·Mac Intel·Mac Apple Silicon): 빌드된 앱이 NAS 흉내 폴더의 새 버전으로 실제로
업데이트하는지(성공 경로), 새 버전이 잘 켜지지 않으면 옛 버전으로 되돌리는지(되돌리기 경로).

  Windows: python ci/update_e2e.py --platform windows --app-dist dist\\YesonCheck_Autocut --installer <원래 설치 파일>
           --iscc <ISCC.exe> --share-root C:\\yc_share\\yc_update --unc \\\\localhost\\yc_test\\yc_update --work C:\\yc_update
  Mac:     python ci/update_e2e.py --platform mac --app-dist dist/YesonCheck_Autocut_<라벨>.app --work "$RUNNER_TEMP/yc_update"

새 버전 꾸러미는 같은 빌드에서 build_info.json의 버전만 바꿔 만든다 — Windows: dist 복사본을 고쳐 installer\\yesoncheck.iss를
워크플로와 같은 ISCC 명령(/DAppVersion=… /DAppFileTag=…)으로 컴파일 (저장소와 같은 모양의 복사본 폴더에서), Mac: ditto 복사본을
고쳐 codesign --force --sign -(ad-hoc)으로 다시 서명하고 build_app.sh처럼 hdiutil create. 옛 앱은 원래 빌드 그대로 — Windows:
원래 설치 파일로 <경우>\\apps\\YesonCheck에 조용히 설치, Mac: <경우>/yc_apps/YesonCheck_Autocut_<라벨>.app에 ditto.
make_test_data.py --update-dir이 가짜 공유 설정의 updates/에 꾸러미와 latest.json(version 99.0.0, 이 플랫폼 항목)을 둔다.

경우 둘 (각각 <work>/<경우> 아래, 업데이트 상태 폴더도 따로):
- success: 꾸러미 99.0.0 → 옛 앱 --smoke-test(update 시나리오: 알림 → 받기 → 도우미에 넘김) → 도우미 기록 "업데이트 끝: 99.0.0",
  설치된 앱의 버전 99.0.0, 새 앱 프로세스가 떠 있음, 업데이트 기록(pending_update.json)이 지워짐, 백업 없음 → 새 앱을 끝냄.
- rollback: latest.json은 99.0.0인데 새 앱이 '잘 켜짐' 표시를 쓰지 않음 (Windows: 꾸러미 버전 98.0.0, Mac: 꾸러미의
  build_info는 99.0.0이고 실행 파일은 바로 exit 1 하는 스크립트) → 도우미 기록에 되돌림, 설치된 앱의 버전이 옛 것, 다시 켜진
  옛 앱이 60초 안에 업데이트 기록을 지움(실패를 알렸다는 뜻), 백업 없음 → 옛 앱을 끝냄.
앱 환경: YESONCHECK_CONFIG_DIR(가짜 공유 설정 — Windows는 UNC), YESONCHECK_UPDATE_URL=off, QT_QPA_PLATFORM=offscreen,
YC_UPDATE_DIRECT_LAUNCH=1, YC_UPDATE_OK_TIMEOUT_S=60, YC_UPDATE_NO_MESSAGEBOX=1, 업데이트 상태 폴더는 작업 폴더 아래
(Windows LOCALAPPDATA, Mac HOME). PYTHONUTF8은 뺌 (사용자 PC와 같게 — ci/run_smoke_test.ps1처럼).

단계마다 이름을 찍고, 실패하면 그 단계·트레이스백·도우미 기록(update.log)·앱 기록(Windows %LOCALAPPDATA%\\YesonCheck\\logs,
Mac은 옛 앱의 stdout·stderr — 도우미가 다시 켠 앱의 출력은 update.log에)·smoke_result.json·설치 폴더 상태를 보이고 종료 코드 1.
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
from yesoncheck import build_info, update_install  # noqa: E402

WINDOWS = sys.platform == "win32"
NEW_VERSION = "99.0.0"
BROKEN_WINDOWS_VERSION = "98.0.0"  # Windows 되돌리기 경로의 꾸러미 버전 (latest.json은 NEW_VERSION)
EXE_NAME = update_install.APP_EXECUTABLE_NAME
WINDOWS_APP_DIR_NAME = "YesonCheck"
MAC_APP_PREFIX = "YesonCheck_Autocut_"
MAC_LABELS = ("Intel", "AppleSilicon")
WINDOWS_MAC_ROOT = "/Volumes/yc_update"  # Windows 경우의 공유 설정에 적는 Mac 경로 (변환표로 UNC가 됨)

INSTALL_TIMEOUT_S = 900  # 원래 설치 파일의 조용한 설치
ISCC_TIMEOUT_S = 1800  # 설치 파일 컴파일 (CI에서 약 7분 — 둘을 함께)
SMOKE_TIMEOUT_S = 1200  # 옛 앱 실행 시험 (받기·Mac 새 앱 준비 포함)
HELPER_TIMEOUT_S = 1200  # 도우미가 끝날 때까지 (Windows 조용한 설치 포함)
PENDING_CLEARED_S = 60  # 되돌린 옛 앱이 업데이트 기록을 지울 때까지
KILL_WAIT_S = 15

# 옛 앱(그리고 도우미가 물려받아 다시 켜는 앱)의 환경
APP_ENV = {
    "YESONCHECK_UPDATE_URL": "off",
    "QT_QPA_PLATFORM": "offscreen",
    "YC_UPDATE_DIRECT_LAUNCH": "1",
    "YC_UPDATE_OK_TIMEOUT_S": "60",
    "YC_UPDATE_NO_MESSAGEBOX": "1",
    "YC_UPDATE_INSTALL_TIMEOUT_S": "900",  # 설치 파일이 멈추면 도우미가 30분이 아니라 15분 뒤 끝내고 되돌림
}


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
    return subprocess.run(cmd, check=True, timeout=timeout, **kwargs)


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
    name: str  # "success" | "rollback"
    root: str  # <work>/<name>
    share_root: str  # 가짜 공유 설정·작품 폴더를 만드는 이 컴퓨터의 경로
    config_dir: str  # 앱이 읽는 공유 설정 폴더 (Windows: UNC)
    unc: str | None  # Windows: share_root의 UNC (변환표)
    app: str  # 옛 앱 — Windows 설치 폴더, Mac .app
    package_version: str  # 꾸러미 안의 버전
    broken: bool  # 새 앱이 잘 켜지지 않는 꾸러미 (되돌리기 경로)
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


def make_cases(args, work):
    cases = []
    for name, broken in (("success", False), ("rollback", True)):
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
        cases.append(Case(name, root, share_root, config_dir, unc, app, version, broken))
    return cases


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


def list_processes():
    if WINDOWS:
        script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | "
            "Select-Object ProcessId, ExecutablePath, CommandLine)"
        )
        out = subprocess.run([update_install._windows_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, check=True, timeout=120).stdout.decode("utf-8")
        return [Proc(int(item["ProcessId"]), item.get("ExecutablePath") or "", item.get("CommandLine") or "")
                for item in json.loads(out)]
    out = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=True,
                         timeout=60).stdout
    procs = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        command = command.strip()
        procs.append(Proc(int(pid_text), command, command))
    return procs


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
    """경우마다 dist 복사본의 버전을 바꿔 설치 파일을 컴파일 (둘을 함께 — 하나에 약 7분) → 경우의 package 폴더로."""
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
        deadline = time.monotonic() + ISCC_TIMEOUT_S
        for case, _tree, _log_path, proc in jobs:
            try:
                codes[case.name] = proc.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                codes[case.name] = f"{ISCC_TIMEOUT_S}초 안에 끝나지 않음"
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
    """가짜 공유 설정·작품 폴더 + updates/(꾸러미 + latest.json) + 실행 시험 설정 (make_test_data.py --update-dir)."""
    cmd = [sys.executable, os.path.join(REPO, "ci", "make_test_data.py"), "--share-root", case.share_root,
           "--mac-root", WINDOWS_MAC_ROOT if WINDOWS else case.share_root, "--workdir", case.smoke_dir,
           "--update-dir", case.package_dir, "--update-version", NEW_VERSION, "--update-platform", platform_key]
    if case.unc:
        cmd += ["--unc", case.unc]
    run(cmd, timeout=600)
    manifest = os.path.join(case.share_root, ".yesoncheck", "updates", "latest.json")
    with open(manifest, encoding="utf-8") as fh:
        print(f"{manifest}:\n{fh.read()}", flush=True)


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
        try:
            code = proc.wait(timeout=SMOKE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(30)
            raise TimeoutError(f"옛 앱 실행 시험이 {SMOKE_TIMEOUT_S}초 안에 끝나지 않았습니다 (대화상자에서 멈췄을 수 있음)")
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


def wait_helper(case, files):
    """도우미(state 폴더의 스크립트 복사본을 실행 중인 프로세스)가 끝나기를 기다림 → 업데이트 기록(update.log) 글."""
    started = time.monotonic()
    while True:
        running = our_processes([], [files["helper"]])
        if not running:
            break
        if time.monotonic() - started > HELPER_TIMEOUT_S:
            raise TimeoutError(f"도우미가 {HELPER_TIMEOUT_S}초 안에 끝나지 않았습니다: "
                               + ", ".join(f"pid {p.pid}" for p in running))
        time.sleep(2 if WINDOWS else 1)
    print(f"도우미가 끝남 ({time.monotonic() - started:.1f}초 기다림)", flush=True)
    text = read_text(files["log"])
    helper_lines = [line for line in text.splitlines() if " 도우미: " in line]
    print("\n".join(helper_lines), flush=True)
    assert any(" 도우미: 시작: " in line for line in helper_lines), "도우미가 시작 기록 없이 끝났습니다 (도우미가 돌지 않음)"
    return text


def leftovers(case):
    """앱 폴더 옆에 남은 것 (백업·준비한 새 앱·치운 새 버전)."""
    parent = os.path.dirname(case.app)
    return sorted(name for name in os.listdir(parent) if name != os.path.basename(case.app))


def check_success(case, files, log_text):
    assert f" 도우미: 업데이트 끝: {NEW_VERSION}" in log_text, f"도우미 기록에 '업데이트 끝: {NEW_VERSION}'이 없습니다"
    version = app_version(case.app)
    assert version == NEW_VERSION, f"설치된 앱의 버전 {version} (기대 {NEW_VERSION})"
    running = app_processes(case)
    assert running, f"새 앱 프로세스가 떠 있지 않습니다: {executable(case.app)}"
    assert not os.path.exists(files["pending"]), f"새 앱이 업데이트 기록을 지우지 않았습니다: {files['pending']}"
    assert not leftovers(case), f"앱 옆에 남은 것: {leftovers(case)}"
    print(f"설치된 앱 {case.app}: 버전 {version}, 새 앱 pid {[p.pid for p in running]}, 백업 없음", flush=True)
    return kill(running)


def check_rollback(case, files, log_text):
    assert " 도우미: 업데이트 실패: " in log_text, "도우미 기록에 '업데이트 실패'가 없습니다"
    assert " 도우미: 되돌림: 옛 앱을 다시 켬" in log_text, "도우미 기록에 '되돌림: 옛 앱을 다시 켬'이 없습니다"
    assert " 도우미: 되돌리기 실패" not in log_text, "도우미가 되돌리지 못했습니다"
    version = app_version(case.app)
    assert version == case.old_version, f"설치된 앱의 버전 {version} (옛 버전 {case.old_version}이어야 함)"
    deadline = time.monotonic() + PENDING_CLEARED_S
    while os.path.exists(files["pending"]):
        assert time.monotonic() < deadline, \
            f"되돌린 옛 앱이 {PENDING_CLEARED_S}초 안에 업데이트 기록을 지우지 않았습니다 (실패를 알리지 않음): {files['pending']}"
        time.sleep(1)
    running = app_processes(case)
    assert running, f"되돌린 옛 앱 프로세스가 떠 있지 않습니다: {executable(case.app)}"
    assert not leftovers(case), f"앱 옆에 남은 것: {leftovers(case)}"
    print(f"설치된 앱 {case.app}: 옛 버전 {version}, 업데이트 기록 지워짐, 옛 앱 pid {[p.pid for p in running]}, "
          "백업 없음", flush=True)
    return kill(running)


def run_case(args, case, platform_key):
    files = state_files(case)
    step(case, "옛 앱 준비 (원래 빌드)", install_old_app, args, case)
    step(case, f"가짜 공유 설정 + updates/ (latest.json {NEW_VERSION}, 꾸러미 {case.package_version})",
         make_shared_config, case, platform_key)
    step(case, "옛 앱 실행 시험 (update: 알림 → 받기 → 도우미에 넘김)", run_old_app, case)
    log_text = step(case, "도우미가 끝나기를 기다림", wait_helper, case, files)
    if case.broken:
        step(case, "결과: 되돌림 — 옛 버전, 옛 앱이 실패를 알림", check_rollback, case, files, log_text)
    else:
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


def show_diagnostics(case):
    files = state_files(case)
    show_file("업데이트 기록 (앱·도우미, Mac은 도우미가 다시 켠 앱의 출력도)", files["log"])
    show_file("도우미가 실행한 설치 파일의 기록", files["log"] + ".inno.txt")
    if WINDOWS:
        for path in sorted(glob.glob(os.path.join(case.user_dir, "YesonCheck", "logs", "*.log"))):
            if not same_path(path, files["log"]):
                show_file("앱 기록", path)
    else:
        show_file("옛 앱 stdout", case.stdout_path)
        show_file("옛 앱 stderr", case.stderr_path)
    show_file("실행 시험 결과", os.path.join(case.smoke_dir, "smoke_result.json"))
    show_file("업데이트 기록 파일 (pending)", files["pending"])
    show_file("'잘 켜짐' 표시", files["ok"])
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
    print("===== 이 경우의 프로세스", flush=True)
    for proc in our_processes([case.root], [files["helper"]]):
        print(f"  pid {proc.pid}: {proc.command[:400]}", flush=True)


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
    args.app_dist = os.path.abspath(args.app_dist)
    if args.installer:
        args.installer = os.path.abspath(args.installer)
    return args


def main():
    args = parse_args()
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
        if WINDOWS:
            step(None, f"새 버전 설치 파일 만들기 ({NEW_VERSION}·{BROKEN_WINDOWS_VERSION}, ISCC 둘을 함께)",
                 build_windows_installers, args, cases, work)
        else:
            for case in cases:
                what = "실행 파일이 바로 끝남" if case.broken else "잘 켜짐"
                step(case, f"새 버전 dmg 만들기 ({case.package_version}, {what})", build_mac_dmg, args, case, work)
        for case in cases:
            current = case
            run_case(args, case, platform_key)
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
    print("\n업데이트 끝까지 시험 통과 (성공·되돌리기)", flush=True)
    return 0



if __name__ == "__main__":
    sys.exit(main())
