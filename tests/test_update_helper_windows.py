"""yesoncheck/update_helper_windows.ps1(Windows 업데이트 도우미)와 update_install.launch_helper_windows 시험.

도우미 시험은 win32에서만 돈다(Windows PowerShell 5.1 — CI windows-build의 소스 시험). 가짜 앱과 가짜 설치 파일은 작은
C# 프로그램 하나(FAKE_EXE_SOURCE)를 시험 세션마다 한 번 .NET Framework의 csc.exe(Windows에 늘 있음)로 만든 진짜 exe다
— 도우미는 되돌릴 때 실행 파일 경로(설치 폴더 아래)로 새 앱 프로세스를 찾아 끝내므로 진짜 exe여야 한다(.cmd는 cmd.exe로
돌아 프로세스 경로가 System32가 됨). 같은 exe가 두 역할을 한다:

- 인자 없이 켜면 가짜 앱. 옆의 kind.txt에 따라 "old"(옛 앱 — 흔적만 남기고 끝남), "new"(시험이 YC_TEST_OK_FILE로 알려 준
  '잘 켜짐' 표시에 {"version": "1.1.1"}을 임시 파일 + 이름 바꾸기로 씀), "silent"(표시 없이 계속 살아 있음),
  "silent_child"(silent + 작업 폴더가 설치 폴더인 cmd.exe 자식 — 흔적 child_started), "crash"(표시 없이 1초 뒤 종료 코드 3).
  켜질 때 흔적 파일(YC_TEST_TRACE_DIR/<old|new>_started, YC_TEST_TRACE_AS로 이름을 바꿀 수 있음)에
  자기 pid를 남기고, YC_TEST_HOLD_S가 있으면 그만큼 살아 있다(끝나기를 기다리는 "지금 앱" 흉내).
- /DIR=… 같은 인자로 켜면 가짜 설치 파일. 받은 인자를 흔적 폴더의 installer_args.txt에 적고, /LOG=에 가짜 기록을 쓰고,
  /DIR= 폴더에 자기를 YesonCheck_Autocut.exe로 복사하고 kind.txt(YC_TEST_NEW_KIND)·_internal/new.txt를 만든 뒤
  YC_TEST_INSTALLER_EXIT(없으면 0)로 끝난다 — 0이 아니면 반쯤 깔린 폴더를 남기고 실패한 셈. YC_TEST_INSTALLER_HANG=1이면
  그 뒤 작업 폴더가 /DIR=인 cmd.exe 자식(흔적 installer_child_started)을 띄우고 끝나지 않는다(멈춘 설치 파일 흉내).

도우미에게 넘기는 앱 pid는 보통 이 시험 프로세스(python.exe)의 것 — 살아 있지만 설치 폴더의 exe가 아니므로 도우미가
기다리지 않는다. 출력은 파일로 받는다(파이프로 받으면 도우미가 켠 가짜 앱이 파이프를 물려받아 끝을 기다리다 멈출 수 있음).
종료 코드 2의 알림 창은 YC_UPDATE_NO_MESSAGEBOX=1로 띄우지 않는다(시험이 멈추지 않게).

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
                                                    "/c ping -n 60 127.0.0.1 >nul");
        psi.WorkingDirectory = cwd;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        Process child = Process.Start(psi);
        File.AppendAllText(Path.Combine(Env("YC_TEST_TRACE_DIR"), traceName + "_started"), child.Id + "\n", Utf8);
    }
}
'''


# ---- 시험 도우미 (이 시험 모듈 안에만 둠) ----


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

    def make(new_kind="new", installer_exit=0, parent_name="Programs"):
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
        for case in made:  # 설치 폴더를 작업 폴더로 잡은 cmd.exe 자식 (실행 파일은 System32라 위에서 안 잡힘)
            for name in ("child", "installer_child"):
                for pid in trace_pids(case, name):
                    if (process_image(pid) or "").lower().endswith("\\cmd.exe"):
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except OSError:
                            pass  # 그 사이에 끝남


def helper_cmd(case, pid, timeout_s):
    """도우미 명령. timeout_s가 None이면 -TimeoutSeconds를 넘기지 않음(YC_UPDATE_OK_TIMEOUT_S·180초가 기본)."""
    cmd = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
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
    code = run_helper(case, timeout_s=4)
    assert code == 1, failure_details(case, code)
    assert app_kind(case.install_dir) == "old" and siblings(case) == ["YesonCheck"]
    child_pids = trace_pids(case, "child")
    assert child_pids, failure_details(case, code)
    assert not (process_image(child_pids[0]) or "").lower().endswith("\\cmd.exe"), "cmd.exe 자식이 끝나지 않음"
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    assert "되돌림" in log_text(case)


@windows_only
def test_helper_restores_when_installer_hangs(update_case):
    case = update_case("new")
    case.env.update(YC_TEST_INSTALLER_HANG="1", YC_UPDATE_INSTALL_TIMEOUT_S="3")
    started = time.monotonic()
    code = run_helper(case)
    assert code == 1, failure_details(case, code)
    assert time.monotonic() - started >= 3  # YC_UPDATE_INSTALL_TIMEOUT_S까지 기다림
    assert app_kind(case.install_dir) == "old"
    assert not (case.install_dir / "_internal" / "new.txt").exists()
    assert siblings(case) == ["YesonCheck"]  # 설치 파일과 그 자식(작업 폴더가 설치 폴더)을 끝내야 치울 수 있음
    assert not processes_under(case.installer.parent), "멈춘 설치 파일이 끝나지 않음"
    child_pids = trace_pids(case, "installer_child")
    assert child_pids and not (process_image(child_pids[0]) or "").lower().endswith("\\cmd.exe"), (
        "설치 파일의 자식이 끝나지 않음\n" + failure_details(case, code)
    )
    assert wait_until(lambda: trace_pids(case, "old")), "옛 앱이 다시 켜지지 않음\n" + failure_details(case, code)
    text = log_text(case)
    assert "설치 파일이 3초 안에 끝나지 않음" in text and "되돌림" in text


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
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW (Win32 값 — Mac의 subprocess에는 없음)
            "creationflags": 0x00000008 | 0x00000200 | 0x08000000,
            "cwd": update_install.state_dir(),  # 설치 폴더를 작업 폴더로 물려받으면 그 이름을 바꿀 수 없음
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        },
    )]
    assert Path(copy).read_bytes() == HELPER.read_bytes()
    # 넘기는 이름이 스크립트의 param 이름과 같음 (틀리면 PowerShell이 값을 엉뚱한 자리에 넣음)
    script = HELPER.read_text(encoding="utf-8-sig")
    args = _RecordingPopen.calls[0][0]
    for flag in args[args.index(copy) + 1::2]:
        assert f"[string]${flag[1:]} = " in script, flag
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        assert _RecordingPopen.calls[0][1]["creationflags"] == flags
        assert os.path.isfile(args[0]) and args[0].lower().endswith("\\windowspowershell\\v1.0\\powershell.exe")


def test_launch_helper_windows_does_not_swallow_popen_failure(tmp_state_dir, monkeypatch):
    def failing_popen(args, **kwargs):
        raise OSError("PowerShell을 실행하지 못함")

    monkeypatch.setattr(update_install.subprocess, "Popen", failing_popen)
    with pytest.raises(OSError, match="PowerShell을 실행하지 못함"):
        update_install.launch_helper_windows("C:\\Temp\\YesonCheck_Setup_1.1.1.exe", "C:\\YesonCheck", "1.1.1")


def test_helper_script_is_utf8_bom_ps51_and_stops_on_errors():
    raw = HELPER.read_bytes()
    # Windows PowerShell 5.1은 BOM 없는 .ps1을 ANSI(한국어 Windows는 cp949)로 읽어 한글 기록 글자가 깨짐
    assert raw.startswith(b"\xef\xbb\xbf")
    # 주석(줄 전체·줄 끝)을 뺀 코드만 — 이 스크립트는 글자 안에 #을 쓰지 않음
    code = "\n".join(
        re.sub(r"\s+#.*$", "", line)
        for line in raw[3:].decode("utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert re.search(r"^\$ErrorActionPreference = 'Stop'$", code, re.M)
    # 5.1의 Add-Content·Out-File·Set-Content는 ANSI·UTF-16이 기본 — 로그는 UTF-8로 직접 씀
    assert not re.search(r"\b(Add-Content|Out-File|Set-Content)\b", code)
    # PowerShell 7에만 있는 문법(&&·||·??·?.) 없음
    assert not re.search(r"&&|\|\||\?\?|\?\.", code)
    # 큰따옴표 글자 안에서 변수 바로 뒤의 한글은 변수 이름으로 읽힘("$Target이") — $(...)나 + 로 이어야 함
    assert not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[가-힣]", code)
    # 종료 코드 2(앱을 다시 켜지 못함)의 마지막 알림 창 — 시험은 YC_UPDATE_NO_MESSAGEBOX=1로 끔
    assert "[System.Windows.Forms.MessageBox]::Show(" in code and "$env:YC_UPDATE_NO_MESSAGEBOX -eq '1'" in code


def test_spec_bundles_windows_helper_only_on_windows():
    text = SPEC.read_text(encoding="utf-8")
    assert re.search(
        r"\[\(os\.path\.join\(project_root, 'yesoncheck', 'update_helper_windows\.ps1'\), 'yesoncheck'\)\] if IS_WINDOWS\s+"
        r"else \[\(os\.path\.join\(project_root, 'yesoncheck', 'update_helper_mac\.sh'\), 'yesoncheck'\)\]",
        text,
    )
