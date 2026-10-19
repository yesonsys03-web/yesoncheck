"""yesoncheck/update_helper_windows.ps1(Windows 업데이트 도우미)와 update_install.launch_helper_windows 시험.

도우미 시험은 win32에서만 돈다(Windows PowerShell 5.1 — CI windows-build의 소스 시험). 가짜 앱과 가짜 설치 파일은 작은
C# 프로그램 하나(FAKE_EXE_SOURCE)를 시험 세션마다 한 번 .NET Framework의 csc.exe(Windows에 늘 있음)로 만든 진짜 exe다
— 도우미는 되돌릴 때 실행 파일 경로(설치 폴더 아래)로 새 앱 프로세스를 찾아 끝내므로 진짜 exe여야 한다(.cmd는 cmd.exe로
돌아 프로세스 경로가 System32가 됨). 같은 exe가 두 역할을 한다:

- 인자 없이 켜면 가짜 앱. 옆의 kind.txt에 따라 "old"(옛 앱 — 흔적만 남기고 끝남), "new"(시험이 YC_TEST_OK_FILE로 알려 준
  '잘 켜짐' 표시에 {"version": "1.1.1"}을 임시 파일 + 이름 바꾸기로 씀), "silent"(표시 없이 계속 살아 있음),
  "silent_child"(silent + 작업 폴더가 설치 폴더인 cmd.exe 자식 — ping으로 약 5분 살아 있음, 흔적 child_started), "crash"(표시 없이 1초 뒤 종료 코드 3).
  켜질 때 흔적 파일(YC_TEST_TRACE_DIR/<old|new>_started, YC_TEST_TRACE_AS로 이름을 바꿀 수 있음)에
  자기 pid를 남기고, YC_TEST_HOLD_S가 있으면 그만큼 살아 있다(끝나기를 기다리는 "지금 앱" 흉내).
- /DIR=… 같은 인자로 켜면 가짜 설치 파일. 받은 인자를 흔적 폴더의 installer_args.txt에 적고, /LOG=에 가짜 기록을 쓰고,
  /DIR= 폴더에 자기를 YesonCheck_Autocut.exe로 복사하고 kind.txt(YC_TEST_NEW_KIND)·_internal/new.txt를 만든 뒤
  YC_TEST_INSTALLER_EXIT(없으면 0)로 끝난다 — 0이 아니면 반쯤 깔린 폴더를 남기고 실패한 셈. YC_TEST_INSTALLER_HANG=1이면
  그 뒤 작업 폴더가 /DIR=인 cmd.exe 자식(흔적 installer_child_started)을 띄우고 끝나지 않는다(멈춘 설치 파일 흉내).

도우미에게 넘기는 앱 pid는 보통 이 시험 프로세스(python.exe)의 것 — 살아 있지만 설치 폴더의 exe가 아니므로 도우미가
기다리지 않는다. 출력은 파일로 받는다(파이프로 받으면 도우미가 켠 가짜 앱이 파이프를 물려받아 끝을 기다리다 멈출 수 있음).
종료 코드 2의 알림 창은 YC_UPDATE_NO_MESSAGEBOX=1로 띄우지 않는다(시험이 멈추지 않게). 도우미는 앱처럼 상태 폴더에 둔
복사본을 실행하고(되살림 정보 파일이 그 옆에 생김), 다음 로그인의 되살림은 진짜 RunOnce가 아니라 시험마다 다른
HKCU\Software\YesonCheckTest\RunOnce-<…> 키에 등록한다(YC_UPDATE_RUNONCE_KEY, 시험이 끝나면 지움).

launch_helper_windows 시험(subprocess.Popen을 바꿔 끼움)과 스크립트·spec 글자 확인은 모든 플랫폼에서 돈다.
"""

import functools
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yesoncheck import update_install

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "yesoncheck" / "update_helper_windows.ps1"
SPEC = ROOT / "YesonCheck_Autocut.spec"
TARGET = "1.1.1"
EXE_NAME = "YesonCheck_Autocut.exe"
LOG_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} ")  # update_install.log()와 같은 줄 앞 시각
POWERSHELL = update_install._windows_powershell()
RECOVER_VALUE = "YesonCheckUpdateRecover"  # 도우미가 RunOnce에 등록하는 값 이름
RECOVER_FILE_NAME = "update_recover.txt"  # 되살림 정보 파일 (도우미 스크립트 옆)
TEST_RUNONCE_PARENT = "Software\\YesonCheckTest"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows 업데이트 도우미 (Windows PowerShell 5.1)")

# C# 5(.NET Framework csc.exe가 아는 만큼)와 ASCII만 — 설명은 이 모듈의 docstring
FAKE_EXE_SOURCE = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;

static class FakeYesonCheck
{
    static readonly Encoding Utf8 = new UTF8Encoding(false);

    static string Env(string name)
    {
        string value = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrEmpty(value)) throw new InvalidOperationException("missing environment variable " + name);
        return value;
    }

    static int Main(string[] args)
    {
        try
        {
            string self = Assembly.GetEntryAssembly().Location;
            return args.Length > 0 ? Install(self, args) : RunApp(self);
        }
        catch (Exception e)
        {
            // an unhandled exception would bring up the Windows error dialog and hang the test
            string trace = Environment.GetEnvironmentVariable("YC_TEST_TRACE_DIR");
            if (!string.IsNullOrEmpty(trace))
                File.AppendAllText(Path.Combine(trace, "fake_errors.txt"), e.ToString() + "\r\n", Utf8);
            return 99;
        }
    }

    static int RunApp(string self)
    {
        string kind = File.ReadAllText(Path.Combine(Path.GetDirectoryName(self), "kind.txt"), Utf8).Trim();
        string traceName = Environment.GetEnvironmentVariable("YC_TEST_TRACE_AS");
        if (string.IsNullOrEmpty(traceName)) traceName = kind == "old" ? "old" : "new";
        File.AppendAllText(Path.Combine(Env("YC_TEST_TRACE_DIR"), traceName + "_started"),
                           Process.GetCurrentProcess().Id + "\n", Utf8);
        string hold = Environment.GetEnvironmentVariable("YC_TEST_HOLD_S");
        if (!string.IsNullOrEmpty(hold)) Thread.Sleep(int.Parse(hold) * 1000);
        if (kind == "new")
        {
            string ok = Env("YC_TEST_OK_FILE");
            File.WriteAllText(ok + ".tmp", "{\"version\": \"" + Env("YC_TEST_TARGET") + "\"}", Utf8);
            File.Move(ok + ".tmp", ok);
            return 0;
        }
        if (kind == "silent") Thread.Sleep(Timeout.Infinite);
        if (kind == "silent_child")
        {
            StartDirHolder(Path.GetDirectoryName(self), "child");
            Thread.Sleep(Timeout.Infinite);
        }
        if (kind == "crash")
        {
            Thread.Sleep(1000);
            return 3;
        }
        return 0;
    }

    static int Install(string self, string[] args)
    {
        File.WriteAllLines(Path.Combine(Env("YC_TEST_TRACE_DIR"), "installer_args.txt"), args, Utf8);
        string dir = null;
        string log = null;
        foreach (string arg in args)
        {
            if (arg.StartsWith("/DIR=", StringComparison.Ordinal)) dir = arg.Substring(5);
            if (arg.StartsWith("/LOG=", StringComparison.Ordinal)) log = arg.Substring(5);
        }
        if (dir == null) throw new InvalidOperationException("no /DIR= argument");
        if (log != null)
            File.WriteAllText(log, "fake inno log: start\r\nfake inno log: installing into " + dir + "\r\n", Utf8);
        Directory.CreateDirectory(Path.Combine(dir, "_internal"));
        File.Copy(self, Path.Combine(dir, "YesonCheck_Autocut.exe"), true);
        File.WriteAllText(Path.Combine(dir, "kind.txt"), Env("YC_TEST_NEW_KIND"), Utf8);
        File.WriteAllText(Path.Combine(dir, "_internal", "new.txt"), "new", Utf8);
        if (Environment.GetEnvironmentVariable("YC_TEST_INSTALLER_HANG") == "1")
        {
            StartDirHolder(dir, "installer_child");
            Thread.Sleep(Timeout.Infinite);
        }
        string code = Environment.GetEnvironmentVariable("YC_TEST_INSTALLER_EXIT");
        return string.IsNullOrEmpty(code) ? 0 : int.Parse(code);
    }

    // a child outside the install folder whose working directory is the install folder (like a cmd.exe or
    // powershell.exe started by the app) - it keeps the folder from being renamed until it is killed
    static void StartDirHolder(string cwd, string traceName)
    {
        ProcessStartInfo psi = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                                                    "/c ping -n 300 127.0.0.1 >nul");
        psi.WorkingDirectory = cwd;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        Process child = Process.Start(psi);
        File.AppendAllText(Path.Combine(Env("YC_TEST_TRACE_DIR"), traceName + "_started"), child.Id + "\n", Utf8);
    }
}
'''


# ---- 시험 도우미 (이 시험 모듈 안에만 둠) ----


@pytest.fixture(autouse=True)
def runonce_test_key(monkeypatch):
    """도우미가 되살림을 등록할 키를 이 시험만의 키로 (진짜 RunOnce를 건드리지 않게) — 시험이 끝나면 지움."""
    import uuid

    key = f"{TEST_RUNONCE_PARENT}\\RunOnce-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("YC_UPDATE_RUNONCE_KEY", key)
    yield key
    if sys.platform == "win32":
        import winreg

        for path in (key, TEST_RUNONCE_PARENT):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass  # 없음 (등록하지 않음), 또는 다른 시험의 키가 아직 있는 부모


def runonce_value(case):
    """시험 키에 등록된 되살림 명령 (없으면 None)."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, case.env["YC_UPDATE_RUNONCE_KEY"]) as key:
            return winreg.QueryValueEx(key, RECOVER_VALUE)[0]
    except FileNotFoundError:
        return None


def recover_file(case):
    return case.script.parent / RECOVER_FILE_NAME


@pytest.fixture
def production_like_state_dir():
    """앱의 업데이트 상태 폴더(%LOCALAPPDATA%\\YesonCheck\\updates — 도우미 스크립트 복사본이 있는 곳)와 길이가 비슷한 짧은
    폴더: <시스템 드라이브>\\yc_t\\<8자>\\AppData\\Local\\YesonCheck\\updates (C:\\Users\\<8자 이름>\\AppData\\… 꼴).
    pytest의 tmp_path는 RunOnce 명령 줄을 260자 넘게 만들어, 보통 PC에서 줄이지 않고 들어가는지 볼 수 없음. 끝나면 지움."""
    import uuid

    root = Path(os.environ.get("SystemDrive", "C:") + "\\") / "yc_t"
    top = root / uuid.uuid4().hex[:8]
    folder = top / "AppData" / "Local" / "YesonCheck" / "updates"
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(top)
    try:
        root.rmdir()
    except OSError:
        pass  # 다른 시험의 폴더가 아직 있음


def long_recover_command(case):
    """줄이지 않은 되살림 명령 줄 (도우미의 Get-RecoverCommand 첫째)."""
    return (f'"{POWERSHELL}" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{case.script}" -Recover')


def short_path(path):
    """8.3 짧은 경로 (그 볼륨에 짧은 이름이 없으면 그대로) — Win32 GetShortPathNameW."""
    import ctypes

    buf = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf)):
        raise ctypes.WinError()
    return buf.value


@pytest.fixture(scope="session")
def fake_exe(tmp_path_factory):
    """FAKE_EXE_SOURCE를 .NET Framework 4의 csc.exe로 만든 가짜 exe (창 없는 프로그램)의 경로."""
    folder = Path(os.path.realpath(tmp_path_factory.mktemp("fake_exe")))
    source = folder / "fake_yesoncheck.cs"
    source.write_text(FAKE_EXE_SOURCE, encoding="utf-8-sig")
    exe = folder / "fake_yesoncheck.exe"
    csc = Path(os.environ.get("WINDIR") or "C:\\Windows") / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    assert csc.is_file(), f"csc.exe가 없음: {csc}"
    done = subprocess.run(
        [str(csc), "/nologo", "/target:winexe", "/optimize+", f"/out:{exe}", str(source)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=180,
    )
    assert done.returncode == 0 and exe.is_file(), (
        f"가짜 exe를 만들지 못함 (종료 코드 {done.returncode})\n"
        f"{done.stdout.decode('utf-8', 'replace')}\n{done.stderr.decode('utf-8', 'replace')}"
    )
    return exe


def make_fake_install(install_dir, fake_exe, kind):
    """가짜 설치 폴더: YesonCheck_Autocut.exe(가짜 exe)·kind.txt·_internal/<kind>.txt."""
    (install_dir / "_internal").mkdir(parents=True)
    shutil.copyfile(fake_exe, install_dir / EXE_NAME)
    (install_dir / "kind.txt").write_text(kind, encoding="utf-8")
    (install_dir / "_internal" / f"{kind}.txt").write_text(kind, encoding="utf-8")


def app_kind(install_dir):
    return (Path(install_dir) / "kind.txt").read_text(encoding="utf-8")


def wait_until(condition, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def trace_pids(case, name):
    path = case.trace / f"{name}_started"
    if not path.exists():
        return []
    return [int(x) for x in path.read_text(encoding="utf-8").split()]


def installer_args(case):
    """가짜 설치 파일이 받은 인자 (불리지 않았으면 None)."""
    path = case.trace / "installer_args.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").splitlines()


@functools.lru_cache(maxsize=None)
def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.K32EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def process_image(pid):
    """pid가 아직 도는 프로세스면 그 실행 파일 경로, 끝났거나 볼 수 없으면 None (Win32 API로 직접 봄)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None  # 없음, 또는 시스템·다른 사용자 프로세스 — 이 시험의 것이 아님
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def processes_under(path):
    """실행 파일이 path 아래이고 아직 도는 프로세스들의 pid — 이 시험이 켠 가짜 앱·가짜 설치 파일만 (모두 tmp_path 안의
    exe). Win32 API(EnumProcesses)로 직접 봄."""
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    pids = (wintypes.DWORD * 65536)()
    needed = wintypes.DWORD()
    if not kernel32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    prefix = str(path).rstrip("\\").lower() + "\\"
    return [
        pid for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]
        if (process_image(pid) or "").lower().startswith(prefix)
    ]


HOLDER_IMAGES = ("cmd.exe", "ping.exe", "conhost.exe")  # 가짜 앱이 띄우는 "설치 폴더를 잡은 자식"과 그 아래


def _process_entries():
    """지금 도는 프로세스들의 (pid, 부모 pid, 실행 파일 이름) — Toolhelp 스냅숏. 부모가 이미 끝났어도 부모 pid는 남아 있음."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = _kernel32()
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    entries = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            entries.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def holder_tree_pids(root_pids):
    """흔적에 남은 cmd.exe(root_pids 중 아직 cmd.exe인 것)와 그 자손 중 HOLDER_IMAGES인 프로세스들의 pid."""
    entries = _process_entries()
    roots = set(root_pids)
    found = {pid for pid, _parent, exe in entries if pid in roots and exe.lower() == "cmd.exe"}
    frontier = set(roots)
    while frontier:
        frontier = {
            pid for pid, parent, exe in entries
            if parent in frontier and pid not in found and exe.lower() in HOLDER_IMAGES
        }
        found |= frontier
    return found


def kill_line_pids(text, what):
    """도우미 기록의 "<what> 프로세스를 끝냄: pid A B …" 줄들의 pid (그 줄이 없으면 빈 집합)."""
    marker = f"{what} 프로세스를 끝냄: pid "
    return {int(x) for line in text.splitlines() if marker in line for x in line.split(marker, 1)[1].split()}


def kill_processes_under(path):
    """실행 파일이 path 아래인 프로세스만 끝냄 — 흔적 파일의 pid는 믿지 않음(다시 쓰여 엉뚱한 프로세스일 수 있음)."""
    for pid in processes_under(path):
        try:
            os.kill(pid, signal.SIGTERM)  # Windows에서는 TerminateProcess
        except OSError:
            pass  # 그 사이에 끝남


@pytest.fixture
def update_case(tmp_path, fake_exe):
    """가짜 설치 폴더(옛 앱)·가짜 설치 파일(새 앱 종류·종료 코드는 make로 고름)·표시·로그·흔적 폴더를 만들어 주는 함수.

    경로는 8.3 짧은 이름(CI의 RUNNER~1 등)을 푼 것 — 도우미가 프로세스의 실행 파일 경로와 견주기 때문. 끝날 때 가짜
    프로세스가 남아 있으면(도우미가 잘못돼 못 끝낸 경우) 끝낸다.
    """
    base = Path(os.path.realpath(tmp_path))
    made = []

    def make(new_kind="new", installer_exit=0, parent_name="Programs", script_dir=None):
        parent = base / parent_name
        install_dir = parent / "YesonCheck"
        make_fake_install(install_dir, fake_exe, "old")
        downloads = base / "downloads"
        downloads.mkdir()
        installer = downloads / "fake_inno.exe"
        shutil.copyfile(fake_exe, installer)
        trace = base / "trace"
        trace.mkdir()
        logs = base / "logs"
        logs.mkdir()
        state = base / "state"
        state.mkdir()
        # 앱처럼 상태 폴더의 복사본을 실행 (되살림 정보 파일이 그 옆에 생김) — script_dir: 그 폴더를 따로 (짧은 경로)
        script = (script_dir or state) / HELPER.name
        shutil.copyfile(HELPER, script)
        ok_file = state / "update_ok.json"
        ok_file.write_text('{"version": "0.0.1"}', encoding="utf-8")  # 지난번 표시 — 도우미가 켜기 전에 지워야 함
        env = dict(os.environ)
        env.pop("YC_UPDATE_OK_TIMEOUT_S", None)
        env.pop("YC_UPDATE_PID_TIMEOUT_S", None)
        env.pop("YC_UPDATE_INSTALL_TIMEOUT_S", None)
        # CI는 pytest를 PowerShell 7(pwsh)에서 띄우므로 PS7의 모듈 경로가 섞여 있음 — 5.1이 그 모듈을 불러오다 실패하지
        # 않게, 앱이 띄울 때(탐색기에서 켠 앱의 환경)처럼 5.1 기본 모듈 경로를 쓰게 함 (Windows의 os.environ 키는 대문자)
        for key in [k for k in env if k.upper() == "PSMODULEPATH"]:
            del env[key]
        env.update(
            YC_TEST_TRACE_DIR=str(trace), YC_TEST_OK_FILE=str(ok_file), YC_TEST_TARGET=TARGET,
            YC_TEST_NEW_KIND=new_kind, YC_TEST_INSTALLER_EXIT=str(installer_exit), YC_UPDATE_NO_MESSAGEBOX="1",
        )
        case = SimpleNamespace(
            base=base,
            parent=parent,
            install_dir=install_dir,
            exe=install_dir / EXE_NAME,
            backup=parent / "YesonCheck.update-backup",
            installer=installer,
            script=script,
            ok_file=ok_file,
            log=logs / "update.log",
            trace=trace,
            env=env,
            stdout=base / "helper_stdout.txt",
            stderr=base / "helper_stderr.txt",
        )
        made.append(case)
        return case

    yield make
    if made:
        kill_processes_under(base)
        # 설치 폴더를 작업 폴더로 잡은 cmd.exe 자식과 그 아래 ping.exe·conhost.exe (실행 파일이 System32라 위에서 안 잡힘)
        roots = [pid for case in made for name in ("child", "installer_child") for pid in trace_pids(case, name)]
        for pid in holder_tree_pids(roots):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass  # 그 사이에 끝남


def helper_cmd(case, pid, timeout_s):
    """도우미 명령. timeout_s가 None이면 -TimeoutSeconds를 넘기지 않음(YC_UPDATE_OK_TIMEOUT_S·180초가 기본)."""
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(case.script),
        "-AppPid", str(pid),
        "-InstallDir", str(case.install_dir),
        "-Installer", str(case.installer),
        "-Target", TARGET,
        "-OkFile", str(case.ok_file),
        "-Log", str(case.log),
    ]
    if timeout_s is not None:
        cmd += ["-TimeoutSeconds", str(timeout_s)]
    return cmd


def start_helper(case, cmd):
    """도우미를 띄움 (출력은 case.stdout·case.stderr 파일로, 작업 폴더는 설치 폴더 밖)."""
    with open(case.stdout, "wb") as out, open(case.stderr, "wb") as err:
        return subprocess.Popen(cmd, env=case.env, cwd=str(case.base), stdin=subprocess.DEVNULL, stdout=out, stderr=err)


def run_helper(case, pid=None, timeout_s=4, cmd=None, limit_s=180):
    """도우미를 끝까지 돌리고 종료 코드를 돌려줌 (limit_s초 안에). pid가 없으면 이 시험 프로세스의 것(이 앱이 아님)."""
    proc = start_helper(case, cmd or helper_cmd(case, os.getpid() if pid is None else pid, timeout_s))
    try:
        return proc.wait(timeout=limit_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(f"도우미가 {limit_s}초 안에 끝나지 않음\n" + failure_details(case, None))


def log_text(case):
    return case.log.read_text(encoding="utf-8")  # UTF-8이 아니면 여기서 실패 (5.1의 기본 ANSI·UTF-16 아님)


def log_so_far(case):
    """도는 중인 도우미의 기록 (없으면 빈 글자, 쓰는 중인 마지막 줄이 반쪽이어도 읽힘)."""
    return case.log.read_bytes().decode("utf-8", "replace") if case.log.exists() else ""


def failure_details(case, code):
    def read(path):
        return path.read_bytes().decode("utf-8", "replace") if path.exists() else "(없음)"

    return (
        f"종료 코드 {code}\nstdout:\n{read(case.stdout)}\nstderr:\n{read(case.stderr)}\n로그:\n{read(case.log)}\n"
        f"가짜 exe 오류:\n{read(case.trace / 'fake_errors.txt')}\n설치 파일 인자: {installer_args(case)}"
    )


def siblings(case):
    """설치 폴더가 든 폴더의 항목들 — 백업·치운 반쯤 깔린 폴더가 남지 않았는지."""
    return sorted(p.name for p in case.parent.iterdir())


# ---- Step 1: 브리핑의 시험 ----


@windows_only
def test_helper_installs_and_keeps_new(update_case):
    case = update_case("new")
    code = run_helper(case)
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "new"
    assert (case.install_dir / "_internal" / "new.txt").exists()
    assert not (case.install_dir / "_internal" / "old.txt").exists()  # 빈 폴더에 설치 — 옛 파일과 섞이지 않음
    assert siblings(case) == ["YesonCheck"]  # 성공 뒤 백업을 지움
    assert not case.ok_file.exists()  # 성공 뒤 표시를 지움
    assert installer_args(case) == [
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={case.install_dir}", f"/LOG={case.log}.inno.txt",
    ]
    assert trace_pids(case, "new") and not trace_pids(case, "old")
    assert not (case.trace / "fake_errors.txt").exists(), failure_details(case, code)
    raw = case.log.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # BOM이 있으면 첫 줄이 log_tail_since의 시각 형식에 맞지 않음
    text = log_text(case)
    lines = [line for line in text.splitlines() if line]
    assert lines and all(LOG_LINE_RE.match(line) for line in lines), text
    assert "업데이트 끝" in text
    # 다음 로그인의 되살림: 이름을 바꾸기 전에 등록했고, 끝나며 지움
    assert "다음 로그인에서 되살리도록 등록함" in text and "다음 로그인의 되살림 등록을 지움" in text, text
    assert runonce_value(case) is None and not recover_file(case).exists()


@windows_only
def test_helper_restores_when_installer_fails(update_case):
    case = update_case("new", installer_exit=3)
    code = run_helper(case)
    assert code == 1, failure_details(case, code)
    assert installer_args(case) is not None
    assert app_kind(case.install_dir) == "old"
    assert (case.install_dir / "_internal" / "old.txt").exists()
    assert not (case.install_dir / "_internal" / "new.txt").exists()  # 반쯤 깔린 것이 섞이지 않음
    assert siblings(case) == ["YesonCheck"]  # 백업도, 치운 반쯤 깔린 폴더도 남지 않음
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    assert not trace_pids(case, "new")
    text = log_text(case)
    assert "되돌림" in text and "종료 코드 3" in text
    assert "다음 로그인의 되살림 등록을 지움" in text and runonce_value(case) is None and not recover_file(case).exists()
    assert f"{case.log}.inno.txt" in text  # 설치 파일 자체 기록의 위치
    assert "fake inno log: installing into" in text  # 그 기록의 끝 줄들도 실패 창에 보이게


@windows_only
def test_helper_restores_when_new_app_silent(update_case):
    # 공백·한글·[]·$·'·&·() — 경로를 와일드카드나 변수로 읽거나 따옴표 처리가 틀리면 엉뚱한 곳을 건드림
    case = update_case("silent", parent_name="앱 [시험] $x 'q' & (1)")
    started = time.monotonic()
    code = run_helper(case, timeout_s=4)
    assert code == 1, failure_details(case, code)
    assert time.monotonic() - started >= 4  # -TimeoutSeconds까지 기다림
    assert installer_args(case) == [  # 따옴표로 감싼 /DIR=·/LOG=가 글자 그대로 설치 파일에 닿음
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={case.install_dir}", f"/LOG={case.log}.inno.txt",
    ]
    assert app_kind(case.install_dir) == "old"
    assert siblings(case) == ["YesonCheck"]
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    silent_pid = trace_pids(case, "new")[0]
    assert silent_pid not in processes_under(case.base), "표시 없는 새 앱이 끝나지 않음\n" + failure_details(case, code)
    assert "되돌림" in log_text(case)


@windows_only
def test_helper_rename_blocked_keeps_old(update_case):
    case = update_case("new")
    held = open(case.install_dir / "_internal" / "old.txt", "rb")  # 다른 YesonCheck 창이 파일을 잡고 있는 것처럼
    try:
        code = run_helper(case)
    finally:
        held.close()
    assert code == 1, failure_details(case, code)
    assert installer_args(case) is None  # 설치 파일을 부르지 않음
    assert app_kind(case.install_dir) == "old" and not case.backup.exists()
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    assert "다른 YesonCheck 창이 켜져 있거나 파일이 잡혀 있음" in log_text(case)
    assert "다음 로그인의 되살림 등록을 지움" in log_text(case)  # 이름을 바꾸기 전에 등록했던 것
    assert runonce_value(case) is None and not recover_file(case).exists()


# ---- 브리핑 밖 추가 시험 ----


@windows_only
def test_helper_restores_quickly_when_new_app_exits_without_marker(update_case):
    case = update_case("crash")
    started = time.monotonic()
    code = run_helper(case, timeout_s=60)
    assert code == 1, failure_details(case, code)
    assert time.monotonic() - started < 30  # 60초 다 기다리지 않음 (설계 5-5: 표시 없이 끝나면 실패)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    assert wait_until(lambda: trace_pids(case, "old")), failure_details(case, code)
    text = log_text(case)
    assert "표시 없이 끝남" in text and "종료 코드 3" in text and "되돌림" in text


@windows_only
def test_helper_waits_for_app_pid(update_case):
    case = update_case("new")
    # 지금 앱 흉내: 이 설치 폴더의 exe가 15초 동안 살아 있음 (흔적은 holder_started) — PowerShell이 늦게 떠도 기다리는
    # 쪽을 지나도록 넉넉히
    holder = subprocess.Popen(
        [str(case.exe)], env=dict(case.env, YC_TEST_HOLD_S="15", YC_TEST_TRACE_AS="holder"), cwd=str(case.base),
    )
    try:
        helper = start_helper(case, helper_cmd(case, holder.pid, 10))
        try:
            time.sleep(4)
            assert helper.poll() is None, failure_details(case, helper.returncode)
            assert app_kind(case.install_dir) == "old" and not case.backup.exists() and installer_args(case) is None
            holder.wait(timeout=30)
            code = helper.wait(timeout=120)
        finally:
            helper.kill()
    finally:
        holder.kill()
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "new"
    assert "앱이 끝나기를 기다림" in log_text(case)


@windows_only
def test_helper_changes_nothing_when_app_does_not_quit(update_case):
    case = update_case("new")
    case.env["YC_UPDATE_PID_TIMEOUT_S"] = "2"
    holder = subprocess.Popen(
        [str(case.exe)], env=dict(case.env, YC_TEST_HOLD_S="60", YC_TEST_TRACE_AS="holder"), cwd=str(case.base),
    )
    try:
        assert wait_until(lambda: trace_pids(case, "holder")), "지금 앱 흉내가 켜지지 않음"
        code = run_helper(case, pid=holder.pid)
    finally:
        holder.kill()
        holder.wait()
    assert code == 1, failure_details(case, code)
    assert installer_args(case) is None
    assert app_kind(case.install_dir) == "old" and not case.backup.exists()
    assert not trace_pids(case, "old") and not trace_pids(case, "new")  # 아무것도 켜지 않음 (앱이 아직 켜져 있음)
    assert str(holder.pid) in log_text(case)


@windows_only
def test_helper_removes_stale_backup_first(update_case):
    case = update_case("new")
    (case.backup / "_internal").mkdir(parents=True)  # 지난 업데이트가 남긴 백업 (도우미가 중간에 끝난 경우 등)
    (case.backup / "_internal" / "stale.txt").write_text("stale", encoding="utf-8")
    code = run_helper(case)
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "new" and siblings(case) == ["YesonCheck"]


@windows_only
def test_helper_refuses_when_stale_backup_cannot_be_removed(update_case):
    case = update_case("new")
    case.backup.mkdir()
    held_path = case.backup / "held.txt"
    held_path.write_text("held", encoding="utf-8")
    held = open(held_path, "rb")  # 지울 수 없게 열어 둠
    try:
        code = run_helper(case)
    finally:
        held.close()
    assert code == 1, failure_details(case, code)
    assert installer_args(case) is None
    assert app_kind(case.install_dir) == "old"
    assert wait_until(lambda: trace_pids(case, "old")), failure_details(case, code)
    assert "지난 업데이트의 백업을 지우지 못함" in log_text(case)


@windows_only
@pytest.mark.parametrize("flag, value", [("-AppPid", "abc"), ("-Target", None)])
def test_helper_rejects_bad_arguments(update_case, flag, value):
    case = update_case("new")
    cmd = helper_cmd(case, os.getpid(), 4)
    i = cmd.index(flag)
    if value is None:
        del cmd[i:i + 2]
    else:
        cmd[i + 1] = value
    code = run_helper(case, cmd=cmd)
    assert code == 2, failure_details(case, code)
    assert "잘못된 인자" in log_text(case) and "알림 창은 띄우지 않음" in log_text(case)
    assert installer_args(case) is None and app_kind(case.install_dir) == "old"
    assert not trace_pids(case, "old")


@windows_only
def test_helper_restores_when_new_app_child_holds_install_dir(update_case):
    # 새 앱이 띄운 cmd.exe(실행 파일은 System32, 작업 폴더는 설치 폴더 — 앱의 powershell.exe 확인 등과 같음)가 설치 폴더를
    # 잡고 있어도, 새 앱의 자손으로 찾아 끝내고 되돌림 (못 끝내면 이름 바꾸기가 끝내 실패해 종료 코드 2)
    case = update_case("silent_child")
    started = time.monotonic()
    code = run_helper(case, timeout_s=4)
    elapsed = time.monotonic() - started
    assert code == 1, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    child_pids = trace_pids(case, "child")
    assert child_pids, failure_details(case, code)
    assert wait_until(lambda: not holder_tree_pids(child_pids), 10), (
        "cmd.exe 자식(또는 그 아래 ping.exe·conhost.exe)이 끝나지 않음\n" + failure_details(case, code)
    )
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    text = log_text(case)
    assert "되돌림" in text
    # 자식(ping으로 약 5분)이 저절로 끝나기를 기다린 것이 아니라 자손으로 찾아 끝냈음을 확인
    assert child_pids[0] in kill_line_pids(text, "새 앱"), failure_details(case, code)
    assert "자손 프로세스를 찾지 못함" not in text and "되돌리기의 이름 바꾸기가" not in text, text
    assert elapsed < 30, f"{elapsed:.1f}초 — 자식이 끝나기를 기다린 것 같음\n" + failure_details(case, code)


@windows_only
def test_helper_restores_when_installer_hangs(update_case):
    case = update_case("new")
    case.env.update(YC_TEST_INSTALLER_HANG="1", YC_UPDATE_INSTALL_TIMEOUT_S="3")
    started = time.monotonic()
    code = run_helper(case)
    elapsed = time.monotonic() - started
    assert code == 1, failure_details(case, code)
    assert elapsed >= 3  # YC_UPDATE_INSTALL_TIMEOUT_S까지 기다림
    assert app_kind(case.install_dir) == "old"
    assert not (case.install_dir / "_internal" / "new.txt").exists()
    assert siblings(case) == ["YesonCheck"]  # 설치 파일과 그 자식(작업 폴더가 설치 폴더)을 끝내야 치울 수 있음
    assert not processes_under(case.installer.parent), "멈춘 설치 파일이 끝나지 않음"
    child_pids = trace_pids(case, "installer_child")
    assert child_pids and wait_until(lambda: not holder_tree_pids(child_pids), 10), (
        "설치 파일의 자식(또는 그 아래 ping.exe·conhost.exe)이 끝나지 않음\n" + failure_details(case, code)
    )
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    text = log_text(case)
    assert "설치 파일이 3초 안에 끝나지 않음" in text and "되돌림" in text
    # 자식(ping으로 약 5분)이 저절로 끝나기를 기다린 것이 아니라 자손으로 찾아 끝냈음을 확인
    assert child_pids[0] in kill_line_pids(text, "설치 파일"), failure_details(case, code)
    assert "자손 프로세스를 찾지 못함" not in text and "되돌리기의 이름 바꾸기가" not in text, text
    assert elapsed < 30, f"{elapsed:.1f}초 — 자식이 끝나기를 기다린 것 같음\n" + failure_details(case, code)


@windows_only
def test_helper_ok_timeout_defaults_to_env(update_case):
    case = update_case("silent")
    case.env["YC_UPDATE_OK_TIMEOUT_S"] = "3"
    started = time.monotonic()
    code = run_helper(case, timeout_s=None)  # -TimeoutSeconds 없이 — 환경 변수가 기본값 (없으면 180초)
    elapsed = time.monotonic() - started
    assert code == 1, failure_details(case, code)
    assert 3 <= elapsed < 90, elapsed
    assert "최대 3초" in log_text(case)
    assert app_kind(case.install_dir) == "old"


@windows_only
def test_helper_sweeps_failed_leftovers(update_case):
    case = update_case("new")
    leftover = case.parent / "YesonCheck.update-failed-4242"  # 지난 되돌리기에서 지우지 못한 것
    (leftover / "_internal").mkdir(parents=True)
    (leftover / "_internal" / "new.txt").write_text("new", encoding="utf-8")
    code = run_helper(case)
    assert code == 0, failure_details(case, code)
    assert siblings(case) == ["YesonCheck"]
    assert "지난 업데이트에서 치워 둔 폴더를 지움" in log_text(case)


@windows_only
def test_helper_fails_loudly_when_app_missing(update_case):
    case = update_case("new")
    case.exe.unlink()  # 설치 폴더에 앱이 없음 — 다시 켤 앱이 없으므로 알림 창(시험에서는 끔)과 종료 코드 2
    code = run_helper(case)
    assert code == 2, failure_details(case, code)
    assert installer_args(case) is None and siblings(case) == ["YesonCheck"]
    text = log_text(case)
    assert "설치 폴더에 지금 앱이 없음" in text and "알림 창은 띄우지 않음" in text


# ---- 다음 로그인의 되살림 (-Recover) ----


def recover_cmd(case):
    return [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(case.script), "-Recover"]


def interrupt_during_install(case, limit=260):
    """설치 파일이 도는 중에 컴퓨터가 꺼진 것처럼: 멈춘 설치 파일이 설치 폴더를 반쯤 채우고 자식까지 띄운 뒤 도우미·설치
    파일·그 자식을 모두 끝냄 → 그때 RunOnce(시험 키)에 등록돼 있던 명령 (limit자 안 — RunOnce 명령 줄 한도)."""
    case.env.update(YC_TEST_INSTALLER_HANG="1", YC_UPDATE_INSTALL_TIMEOUT_S="600")
    helper = start_helper(case, helper_cmd(case, os.getpid(), 4))
    command = None
    try:
        assert wait_until(lambda: trace_pids(case, "installer_child"), 120), failure_details(case, helper.poll())
        command = runonce_value(case)
        info = recover_file(case).read_text(encoding="utf-8")
    finally:
        helper.kill()
        helper.wait(30)
        kill_processes_under(case.base)  # 설치 파일 (내려받은 곳 아래)
        for pid in holder_tree_pids(trace_pids(case, "installer_child")):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass  # 그 사이에 끝남
    assert command is not None, "설치하는 동안 되살림이 등록돼 있지 않음\n" + failure_details(case, None)
    assert command.startswith('"') and command.endswith(' -Recover'), command
    assert len(command) <= limit, (len(command), command)  # RunOnce 명령 줄 한도
    assert info.splitlines() == [f"InstallDir={case.install_dir}", f"Target={TARGET}", f"OkFile={case.ok_file}",
                                 f"Log={case.log}", f"ExeName={EXE_NAME}"], info
    assert app_kind(case.install_dir) == "new" and app_kind(case.backup) == "old"  # 반쯤 깔린 채, 옛 앱은 백업 이름
    return command


@windows_only
def test_helper_recover_restores_half_installed_dir_at_next_logon(update_case, production_like_state_dir):
    case = update_case("new", script_dir=production_like_state_dir)
    command = interrupt_during_install(case)
    # 보통 PC의 경로 길이면 줄이지 않고 긴 경로 그대로 260자 안
    assert command.lower() == long_recover_command(case).lower(), command
    assert "줄여 씀" not in log_text(case)
    code = run_helper(case, cmd=command)  # 다음 로그인: Windows가 RunOnce의 명령 줄 그대로 실행
    assert code == 1, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and (case.install_dir / "_internal" / "old.txt").exists()
    assert not (case.install_dir / "_internal" / "new.txt").exists()
    assert siblings(case) == ["YesonCheck"]  # 백업도, 치운 반쯤 깔린 폴더도 남지 않음
    assert not trace_pids(case, "old") and not trace_pids(case, "new")  # 로그인 때 앱을 켜지 않음
    assert not recover_file(case).exists() and not case.ok_file.exists()
    text = log_text(case)
    assert "다음 로그인에서 되살림" in text and "반쯤 깔린 설치 폴더를 치움" in text, text
    lines = [line for line in text.splitlines() if line]
    assert all(LOG_LINE_RE.match(line) for line in lines), text


@windows_only
def test_helper_recover_ignores_marker_left_from_earlier_attempt(update_case, production_like_state_dir):
    """같은 버전을 다시 해 볼 때 지난번(되돌린 업데이트)의 '잘 켜짐' 표시가 남아 있어도 되살림 등록 전에 지움 → 설치 중에
    꺼진 뒤의 되살림은 (Inno가 실행 파일까지 복사해 둔) 반쯤 깔린 설치 폴더를 남기지 않고 백업을 되돌림."""
    case = update_case("new", script_dir=production_like_state_dir)
    case.ok_file.write_text(f'{{"version": "{TARGET}"}}', encoding="utf-8")  # 지난 시도의 새 앱이 늦게 쓴 표시
    command = interrupt_during_install(case)
    assert not case.ok_file.exists()
    text = log_text(case)
    assert text.index("'잘 켜짐' 표시를 지움 (되살림 등록 전") < text.index("다음 로그인에서 되살리도록 등록함"), text
    assert (case.install_dir / EXE_NAME).exists()  # 반쯤 깔린 설치 폴더에도 실행 파일은 있음
    code = run_helper(case, cmd=command)
    assert code == 1, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    assert "다음 로그인에서 되살림" in log_text(case)


@windows_only
def test_helper_recover_keeps_new_version_that_started_fine(update_case, production_like_state_dir):
    """새 버전이 다 깔리고(설치 파일 종료 코드 0) 새 앱이 — 되살림을 등록한 뒤에 — '잘 켜짐'을 남겼는데 도우미가 백업을 지우기
    전에 컴퓨터가 꺼짐 → 다음 로그인의 되살림은 새 버전을 그대로 두고 백업만 지움."""
    case = update_case("new", script_dir=production_like_state_dir)
    case.env["YC_TEST_HOLD_S"] = "6"  # 새 앱이 표시를 쓰기 전에 기다림 — 그사이 백업 안의 파일을 잡아 백업 지우기를 늦춤
    helper = start_helper(case, helper_cmd(case, os.getpid(), 60))
    held = None
    command = marker = None
    try:
        assert wait_until(lambda: "설치 폴더를 백업 이름으로 바꿈" in log_so_far(case), 60), failure_details(case, helper.poll())
        held = open(case.backup / "_internal" / "old.txt", "rb")  # 백업 지우기가 몇 초 동안 다시 해 봄 — 그사이에 끔
        assert wait_until(lambda: "새 앱이 잘 켜짐" in log_so_far(case), 60), failure_details(case, helper.poll())
        command = runonce_value(case)
        marker = case.ok_file.read_text(encoding="utf-8")
    finally:
        helper.kill()  # 컴퓨터가 꺼짐 흉내
        helper.wait(30)
        kill_processes_under(case.base)
        if held is not None:
            held.close()
    text = log_text(case)
    assert command is not None and f'"{TARGET}"' in marker, (command, marker, text)
    assert text.index("다음 로그인에서 되살리도록 등록함") < text.index("설치 파일이 끝남 (종료 코드 0)") < text.index(
        "새 앱이 잘 켜짐"), text
    assert "업데이트 끝" not in text and case.backup.exists() and app_kind(case.install_dir) == "new"
    code = run_helper(case, cmd=command)
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "new" and siblings(case) == ["YesonCheck"]  # 백업만 지움
    assert "남은 백업만 지움" in log_text(case) and not recover_file(case).exists() and not case.ok_file.exists()


@windows_only
def test_helper_refuses_when_old_marker_cannot_be_removed(update_case):
    """지난 '잘 켜짐' 표시를 지우지 못하면 이름을 바꾸기 전에 멈춤 — 설치하지 않고 되살림도 등록하지 않고 옛 앱을 다시 켬."""
    case = update_case("new")
    held = open(case.ok_file, "rb")  # 지울 수 없게
    try:
        code = run_helper(case)
    finally:
        held.close()
    assert code == 1, failure_details(case, code)
    assert installer_args(case) is None and app_kind(case.install_dir) == "old" and not case.backup.exists()
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    text = log_text(case)
    assert "지난 '잘 켜짐' 표시를 지우지 못해 이름을 바꾸기 전에 멈춤" in text, text
    assert "다음 로그인에서 되살리도록 등록함" not in text and runonce_value(case) is None


@windows_only
@pytest.mark.parametrize("shortened", ["short_paths", "short_options"])
def test_helper_shortens_recover_command_over_the_limit(update_case, shortened):
    """스크립트 경로가 길어 명령 줄이 RunOnce 한도를 넘으면 짧은(8.3) 경로로, 그래도 넘으면 짧은 옵션 이름으로 줄여 등록 —
    그 명령 줄 그대로 실행한 되살림이 됨. 한도는 YC_UPDATE_RUNONCE_MAX_CHARS로 낮춰 단계를 정함 (8.3 이름이 없는 볼륨이면
    둘 다 짧은 옵션 단계)."""
    case = update_case("new")
    long_command = long_recover_command(case)
    short_paths = (f'"{short_path(POWERSHELL)}" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                   f'-File "{short_path(case.script)}" -Recover')
    limit = len(long_command) - 1 if shortened == "short_paths" else len(short_paths) - 1
    case.env["YC_UPDATE_RUNONCE_MAX_CHARS"] = str(limit)
    command = interrupt_during_install(case, limit=limit)
    assert command.lower() != long_command.lower()
    if shortened == "short_options" or len(short_paths) > limit:
        assert " -NoP -EP Bypass -W Hidden -File " in command, command
    assert f"{len(long_command)}자로 RunOnce 한도 {limit}자를 넘어 줄여 씀 ({len(command)}자)" in log_text(case)
    code = run_helper(case, cmd=command)  # 줄인 명령 줄 그대로 실행 (다음 로그인)
    assert code == 1, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    assert "다음 로그인에서 되살림" in log_text(case) and not recover_file(case).exists()


@windows_only
def test_helper_updates_without_recover_when_command_cannot_fit(update_case):
    """짧은 경로·짧은 옵션으로도 한도를 넘으면 되살림을 등록하지 않고 크게 기록한 뒤 업데이트는 계속 (막지 않음)."""
    case = update_case("new")
    case.env["YC_UPDATE_RUNONCE_MAX_CHARS"] = "40"
    code = run_helper(case)
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "new" and siblings(case) == ["YesonCheck"]
    text = log_text(case)
    assert "다음 로그인의 되살림을 등록하지 않음" in text and "한도 40자를 넘음" in text, text
    assert "설치 중에 컴퓨터가 꺼지면 손으로 되돌려야 함" in text and "다음 로그인에서 되살리도록 등록함" not in text
    assert runonce_value(case) is None and not recover_file(case).exists()


@windows_only
def test_helper_recover_without_backup_does_nothing(update_case):
    case = update_case("new")
    recover_file(case).write_text(
        f"InstallDir={case.install_dir}\r\nTarget={TARGET}\r\nOkFile={case.ok_file}\r\nLog={case.log}\r\n"
        f"ExeName={EXE_NAME}\r\n", encoding="utf-8")
    code = run_helper(case, cmd=recover_cmd(case))
    assert code == 0, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    assert "할 일 없음" in log_text(case) and not recover_file(case).exists()


@windows_only
def test_helper_recover_without_info_fails_loudly(update_case):
    case = update_case("new")
    code = run_helper(case, cmd=recover_cmd(case))  # 되살림 정보 파일 없음
    assert code == 2, failure_details(case, code)
    assert "되살림 정보를 읽지 못함" in case.stderr.read_bytes().decode("utf-8", "replace") + case.stdout.read_bytes().decode(
        "utf-8", "replace"), failure_details(case, code)
    assert app_kind(case.install_dir) == "old"


# ---- launch_helper_windows·스크립트 글자 (모든 플랫폼) ----


class _RecordingPopen:
    calls = []

    def __init__(self, args, **kwargs):
        _RecordingPopen.calls.append((args, kwargs))


def test_launch_helper_windows_copies_script_and_passes_arguments(tmp_state_dir, monkeypatch):
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    installer = "C:\\Users\\studio01\\AppData\\Local\\YesonCheck\\updates\\YesonCheck_Setup_1.1.1.exe"
    update_install.launch_helper_windows(installer, "C:\\YesonCheck", "1.1.1")
    copy = os.path.join(update_install.state_dir(), "update_helper_windows.ps1")
    console = _RecordingPopen.calls[0][1].pop("stdout")  # 도우미 출력 파일 (아래에서 따로 확인)
    assert console.name == update_install.helper_console_path() and console.closed
    expected_env = {k: v for k, v in os.environ.items() if not (sys.platform == "win32" and k.upper() == "PSMODULEPATH")}
    assert _RecordingPopen.calls == [(
        [
            update_install._windows_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", copy,
            "-AppPid", str(os.getpid()),
            "-InstallDir", "C:\\YesonCheck",
            "-Installer", installer,
            "-Target", "1.1.1",
            "-OkFile", update_install.ok_marker_path(),
            "-Log", update_install.log_path(),
        ],
        {
            # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW (Win32 값 — Mac의 subprocess에는 없음). DETACHED_PROCESS(0x8)는
            # 안 됨: 콘솔이 없으면 Windows PowerShell 5.1이 스크립트를 시작하지 못하고 출력 없이 끝남
            "creationflags": 0x00000200 | 0x08000000,
            "cwd": update_install.state_dir(),  # 설치 폴더를 작업 폴더로 물려받으면 그 이름을 바꿀 수 없음
            "env": {**expected_env, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,  # stdout과 같은 파일로
        },
    )]
    assert Path(copy).read_bytes() == HELPER.read_bytes()
    # 넘기는 이름이 스크립트의 param 이름과 같음 (틀리면 PowerShell이 값을 엉뚱한 자리에 넣음)
    script = HELPER.read_text(encoding="utf-8-sig")
    args = _RecordingPopen.calls[0][0]
    for flag in args[args.index(copy) + 1::2]:
        assert f"[string]${flag[1:]} = " in script, flag
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        assert _RecordingPopen.calls[0][1]["creationflags"] == flags
        assert os.path.isfile(args[0]) and args[0].lower().endswith("\\windowspowershell\\v1.0\\powershell.exe")


def test_launch_helper_windows_resets_pyinstaller_environment_for_relaunched_app(tmp_state_dir, monkeypatch):
    """도우미가 켜는 앱(도우미의 환경을 물려받음)이 옛 앱의 하위 작업 프로세스로 켜지지 않게
    PYINSTALLER_RESET_ENVIRONMENT=1을 넘김 — 나머지 환경은 그대로, 이 앱의 환경은 그대로."""
    monkeypatch.setenv("YC_UPDATE_NO_MESSAGEBOX", "1")
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")
    env = _RecordingPopen.calls[0][1]["env"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and env["YC_UPDATE_NO_MESSAGEBOX"] == "1"
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in os.environ


PS7_STYLE_MODULE_PATH = ";".join([
    # pwsh 7이 자기 프로세스에 만드는 PSModulePath의 모양 (CI의 pwsh 단계·pwsh 터미널에서 켠 앱이 물려받음)
    r"C:\Users\studio01\Documents\PowerShell\Modules",
    r"C:\Program Files\PowerShell\Modules",
    r"c:\program files\powershell\7\Modules",
    r"C:\Program Files\WindowsPowerShell\Modules",
    r"C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules",
])


@pytest.mark.parametrize("is_windows", [True, False])
def test_helper_env_drops_inherited_module_path_on_windows(monkeypatch, is_windows):
    """Windows PowerShell 5.1 도우미가 PS7의 모듈 폴더를 물려받으면 맨 처음 쓰는 New-Object(Microsoft.PowerShell.Utility)를
    PS7 모듈에서 불러오다 실패해 기록 없이 끝남 → Windows는 PSModulePath를 빼고 넘김 (5.1이 기본값을 만듦). Mac은 그대로."""
    monkeypatch.setenv("PSModulePath", PS7_STYLE_MODULE_PATH)
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", is_windows)
    env = update_install._helper_env()
    left = [key for key in env if key.upper() == "PSMODULEPATH"]
    assert left == ([] if is_windows else [k for k in os.environ if k.upper() == "PSMODULEPATH"])
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert any(key.upper() == "PSMODULEPATH" for key in os.environ)  # 이 앱의 환경은 그대로


def test_launch_helper_windows_starts_a_fresh_console_file(tmp_state_dir, monkeypatch):
    """도우미의 stdout·stderr 파일은 띄울 때마다 새로 (지난 도우미의 출력이 이번 실패 창에 섞이지 않게)."""
    with open(update_install.helper_console_path(), "w", encoding="utf-8") as fh:
        fh.write("지난 도우미의 출력\n")
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")
    assert Path(update_install.helper_console_path()).read_bytes() == b""


def _read_or_none(path):
    return Path(path).read_bytes().decode("utf-8", "replace") if os.path.exists(path) else "(없음)"


def _wait_real_helper(proc, timeout_s=60):
    """진짜로 띄운 도우미가 끝나기를 기다림 → (종료 코드, 기록, 도우미 출력). 시간 안에 끝나지 않으면 끝내고 AssertionError."""
    try:
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(30)
        raise AssertionError(f"도우미가 {timeout_s}초 안에 끝나지 않음\n기록:\n{_read_or_none(update_install.log_path())}\n"
                             f"도우미 출력:\n{_read_or_none(update_install.helper_console_path())}") from None
    return code, _read_or_none(update_install.log_path()), _read_or_none(update_install.helper_console_path())


@windows_only
def test_real_launch_helper_windows_writes_start_line_with_ps7_module_path(tmp_state_dir, tmp_path, monkeypatch):
    """진짜 launch_helper_windows (Popen·창 없는 콘솔 플래그·DLL 찾는 곳 되돌리기·_helper_env 그대로)로 빌드된 앱처럼
    띄움 — 도우미가 스크립트를 실행해 시작 기록을 남기는지 (CI 업데이트 끝까지 시험에서 DETACHED_PROCESS로 띄운 도우미가
    기록 한 줄 없이 끝나던 것). 앱이 PS7의 PSModulePath를 물려받은 경우로. 일찍 끝나는 길: 설치 폴더에 앱이 없음 → 기록하고
    종료 코드 2 (알림 창 없이)."""
    _frozen_windows_app(monkeypatch, tmp_path)  # 번들 안 스크립트 = 저장소의 도우미, DLL 찾는 곳 되돌리기도 진짜로
    monkeypatch.setenv("PSModulePath", PS7_STYLE_MODULE_PATH)
    monkeypatch.setenv("YC_UPDATE_NO_MESSAGEBOX", "1")
    install_dir = Path(os.path.realpath(tmp_path)) / "Programs" / "YesonCheck"  # 없음
    update_install.log("업데이트 1.1.1: 업데이트 기록을 남김 (앱의 줄)")
    offset = update_install.log_size()
    try:
        proc = update_install.launch_helper_windows(str(tmp_path / "YesonCheck_Setup_1.1.1.exe"), str(install_dir), "1.1.1")
    finally:
        # launch는 띄운 뒤 DLL 찾는 곳을 (가짜) _MEIPASS로 되돌림 — 이 시험 프로세스(빌드된 앱이 아님)는 원래대로 기본
        update_install._set_dll_directory(None)
    code, text, console = _wait_real_helper(proc)
    details = f"종료 코드 {code}\n기록:\n{text}\n도우미 출력:\n{console}"
    assert code == 2, details
    assert " 도우미: 시작: 대상 버전 1.1.1" in text and "설치 폴더에 지금 앱이 없음" in text, details
    assert update_install.helper_start_logged(offset), details  # 앱이 끝나도 되는지 보는 줄 (player_update._hand_off)
    assert "알림 창은 띄우지 않음" in text, details
    # 정상 실행의 줄은 기록에만 — 실패 창에 '기록에 없는 것'으로 다시 보이지 않음 (5.1은 출력 파일에 코드 페이지로 씀)
    assert update_install.helper_console_extra() == "", details


@windows_only
def test_real_launch_helper_windows_records_early_powershell_failure(tmp_state_dir, tmp_path, monkeypatch):
    """도우미 스크립트가 기록을 쓰기 전에 실패해도(모듈을 불러오지 못함 등) PowerShell의 오류가 도우미 출력 파일에 남고,
    다시 켜진 앱의 실패 창이 그것을 보임 (helper_console_extra)."""
    broken = tmp_path / "broken_helper.ps1"
    broken.write_text("throw 'yc-early-failure-marker'\r\n", encoding="utf-8-sig")
    monkeypatch.setattr(update_install, "_bundled_file", lambda name: str(broken))
    monkeypatch.setenv("YC_UPDATE_NO_MESSAGEBOX", "1")
    proc = update_install.launch_helper_windows(str(tmp_path / "Setup.exe"), str(tmp_path / "Programs" / "YesonCheck"),
                                                "1.1.1")
    code, text, console = _wait_real_helper(proc)
    details = f"종료 코드 {code}\n기록:\n{text}\n도우미 출력:\n{console}"
    assert code != 0 and "yc-early-failure-marker" in console, details
    assert "yc-early-failure-marker" in update_install.helper_console_extra(), details
    assert not os.path.exists(update_install.log_path()), details  # 도우미는 기록을 한 줄도 쓰지 못함


class _FakeKernel32:
    """SetDllDirectoryW를 부른 값을 남김 (fail_on: 이 값이면 실패 0을 돌려줌)."""

    def __init__(self, events, fail_on=()):
        self.events = events
        self.fail_on = fail_on

    def SetDllDirectoryW(self, path):
        self.events.append(("SetDllDirectoryW", path))
        return 0 if path in self.fail_on else 1


def _frozen_windows_app(monkeypatch, tmp_path):
    """빌드된 Windows 앱처럼: sys._MEIPASS(번들 안 도우미 스크립트가 있는 곳)·paths.IS_WINDOWS."""
    meipass = tmp_path / "app" / "_internal"
    (meipass / "yesoncheck").mkdir(parents=True)
    (meipass / "yesoncheck" / "update_helper_windows.ps1").write_bytes(HELPER.read_bytes())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", True)
    return str(meipass)


def test_launch_helper_windows_launches_with_default_dll_search_when_frozen(tmp_state_dir, tmp_path, monkeypatch):
    """빌드된 앱은 부트로더가 SetDllDirectoryW(_internal)로 바꾼 DLL 찾는 곳을 자식이 물려받음 → 도우미를 띄우는 동안만
    기본(NULL)으로 되돌리고, 띄운 뒤 _internal로 다시 (도우미를 못 띄우면 앱은 계속 돎)."""
    meipass = _frozen_windows_app(monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(update_install, "_kernel32", lambda: _FakeKernel32(events))
    monkeypatch.setattr(update_install.subprocess, "Popen", lambda args, **kwargs: events.append(("Popen", args[0])))
    update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")
    assert events == [("SetDllDirectoryW", None), ("Popen", update_install._windows_powershell()),
                      ("SetDllDirectoryW", meipass)]

    # Popen이 실패해도 되돌리고, Popen의 오류를 그대로 올림
    events.clear()

    def failing_popen(args, **kwargs):
        events.append(("Popen", args[0]))
        raise OSError("PowerShell을 실행하지 못함")

    monkeypatch.setattr(update_install.subprocess, "Popen", failing_popen)
    with pytest.raises(OSError, match="PowerShell을 실행하지 못함"):
        update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")
    assert events[-1] == ("SetDllDirectoryW", meipass)


def test_launch_helper_windows_does_not_launch_when_dll_search_reset_fails(tmp_state_dir, tmp_path, monkeypatch):
    _frozen_windows_app(monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(update_install, "_kernel32", lambda: _FakeKernel32(events, fail_on=(None,)))
    monkeypatch.setattr(update_install, "_last_windows_error", lambda: 87)
    monkeypatch.setattr(update_install.subprocess, "Popen", lambda args, **kwargs: events.append(("Popen", args[0])))
    with pytest.raises(OSError, match=r"SetDllDirectoryW\(None\)가 실패했습니다 \(Windows 오류 87\)"):
        update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")
    assert events == [("SetDllDirectoryW", None)]


def test_launch_helper_windows_does_not_swallow_popen_failure(tmp_state_dir, monkeypatch):
    def failing_popen(args, **kwargs):
        raise OSError("PowerShell을 실행하지 못함")

    monkeypatch.setattr(update_install.subprocess, "Popen", failing_popen)
    with pytest.raises(OSError, match="PowerShell을 실행하지 못함"):
        update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")


def helper_code():
    """도우미 스크립트에서 주석(줄 전체·줄 끝)을 뺀 코드만 — 이 스크립트는 글자 안에 #을 쓰지 않음."""
    return "\n".join(
        re.sub(r"\s+#.*$", "", line)
        for line in HELPER.read_bytes()[3:].decode("utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_helper_script_is_utf8_bom_ps51_and_stops_on_errors():
    raw = HELPER.read_bytes()
    # Windows PowerShell 5.1은 BOM 없는 .ps1을 ANSI(한국어 Windows는 cp949)로 읽어 한글 기록 글자가 깨짐
    assert raw.startswith(b"\xef\xbb\xbf")
    code = helper_code()
    assert re.search(r"^\$ErrorActionPreference = 'Stop'$", code, re.M)
    # 5.1의 Add-Content·Out-File·Set-Content는 ANSI·UTF-16이 기본 — 로그는 UTF-8로 직접 씀
    assert not re.search(r"\b(Add-Content|Out-File|Set-Content)\b", code)
    # PowerShell 7에만 있는 문법(&&·||·??·?.) 없음
    assert not re.search(r"&&|\|\||\?\?|\?\.", code)
    # 큰따옴표 글자 안에서 변수 바로 뒤의 한글은 변수 이름으로 읽힘("$Target이") — $(...)나 + 로 이어야 함
    assert not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[가-힣]", code)
    # 종료 코드 2(앱을 다시 켜지 못함)의 마지막 알림 창 — 시험은 YC_UPDATE_NO_MESSAGEBOX=1로 끔
    assert "[System.Windows.Forms.MessageBox]::Show(" in code and "$env:YC_UPDATE_NO_MESSAGEBOX -eq '1'" in code


def test_helper_registers_recover_after_stale_backup_and_before_rename():
    """다음 로그인의 되살림은 지난 백업을 지운 뒤(남은 백업이 이번 것이어야 되살림이 옳음), 설치 폴더의 이름을 바꾸기 바로
    전에 등록. 기본은 진짜 HKCU RunOnce, 시험은 YC_UPDATE_RUNONCE_KEY."""
    code = helper_code()
    stale = code.index("$script:FailReason = '지난 업데이트의 백업을 지우지 못함")
    marker = code.index("if (-not (Remove-OkMarker '되살림 등록 전")
    register = code.index("\n    Register-Recover\n")
    rename = code.index("Move-Dir $InstallDir $Backup $RetryCount")
    assert stale < marker < register < rename  # 지난 '잘 켜짐' 표시도 등록 전에 (못 지우면 멈춤)
    # 되돌릴 때는 새 앱을 끝낸 뒤에 표시를 지움 (끝나기 전에 늦게 쓴 표시도 남지 않게)
    rollback = code[code.index("function Exit-Rollback"):code.index("if ($ExtraArgs.Count -gt 0)")]
    assert rollback.index("Stop-NewApp") < rollback.index("Remove-OkMarker") < rollback.index("Restore-Backup")
    assert "$RecoverValueName = 'YesonCheckUpdateRecover'" in code
    assert "$RunOnceKey = 'Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce'" in code
    assert "$RunOnceKey = $env:YC_UPDATE_RUNONCE_KEY" in code
    assert "[switch]$Recover" in code


def test_helper_recover_command_fits_runonce_limit_or_is_not_registered():
    """RunOnce 명령 줄은 260자 안(Microsoft 문서): 긴 경로 → 짧은(8.3) 경로 → 짧은 옵션 이름 순으로 해 보고, 다 넘으면
    등록하지 않음(업데이트는 계속). 한도는 시험만 YC_UPDATE_RUNONCE_MAX_CHARS로 바꿈."""
    code = helper_code()
    assert "if (-not $RunOnceMaxText) { $RunOnceMaxText = '260' }" in code
    assert "$RunOnceMaxText = $env:YC_UPDATE_RUNONCE_MAX_CHARS" in code
    body = code[code.index("function Get-RecoverCommand"):code.index("function Register-Recover")]
    order = [body.index(part) for part in (
        "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"' + $PSCommandPath",
        "Get-ShortPath $PSCommandPath",
        "-NoP -EP Bypass -W Hidden -File \"' + $shortScript",
    )]
    assert order == sorted(order), order
    assert body.count("-le $RunOnceMaxChars") == 2 and "return $null" in body
    register = code[code.index("function Register-Recover"):code.index("function Clear-Recover")]
    assert "if ($null -eq $command) {" in register and "-gt 260" not in register


def test_spec_bundles_windows_helper_only_on_windows():
    text = SPEC.read_text(encoding="utf-8")
    assert re.search(
        r"\[\(os\.path\.join\(project_root, 'yesoncheck', 'update_helper_windows\.ps1'\), 'yesoncheck'\)\] if IS_WINDOWS\s+"
        r"else \[\(os\.path\.join\(project_root, 'yesoncheck', 'update_helper_mac\.sh'\), 'yesoncheck'\)\]",
        text,
    )
