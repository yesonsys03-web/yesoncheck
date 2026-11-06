"""다른 앱으로 열기 (open_with — Qt 없음): 명령 만들기, 등록한 앱 목록(prefs.json), 띄우기.

진짜 앱은 띄우지 않음 — popen·kernel32를 가짜로 넣어 무엇을 어떤 환경으로 띄우는지만 봄. 플랫폼은 인자로 넣어 어느 OS에서나 돎.
설정 파일은 conftest가 시험마다 새로 만든 HOME 아래(Mac) — Windows 경로(LOCALAPPDATA)는 시험이 새 폴더로 바꿈.
"""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yesoncheck import open_with
from yesoncheck.user_files import UserFileError


@pytest.fixture
def local_appdata(tmp_path, monkeypatch):
    folder = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    return folder


def make_app(tmp_path, name="DJV"):
    """Mac 앱 번들 자리 (폴더 <name>.app)."""
    app = tmp_path / "Applications" / f"{name}.app"
    app.mkdir(parents=True)
    return str(app)


def make_exe(tmp_path, name="djv"):
    exe = tmp_path / "Program Files" / name / f"{name}.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return str(exe)


# ---------------------------------------------------------------- 명령


def test_quicktime_command_uses_the_bundle_id():
    assert open_with.quicktime_command(["/a/x.mov", "/a/y.mov"]) == [
        "/usr/bin/open", "-b", "com.apple.QuickTimePlayerX", "/a/x.mov", "/a/y.mov"]


def test_mac_app_command_passes_files_as_arguments_to_a_new_instance():
    """등록한 앱은 파일을 명령 줄 인자로 (사용자 보고 2026-11-06: DJV 3.7.5는 `open -a`의 문서 열기 이벤트를 받지 않아 앱만 켜졌음 —
    인자를 적는 가짜 앱으로 확인: 문서 열기는 인자 0개, --args는 공백·한글 경로 그대로). -n: 이미 떠 있어도 인자가 새 프로세스에 닿게."""
    assert open_with.app_command("/Applications/DJV.app", ["/a/x.mov", "/a b/y.mov"], "darwin") == [
        "/usr/bin/open", "-n", "-a", "/Applications/DJV.app", "--args", "/a/x.mov", "/a b/y.mov"]


def test_windows_app_command_passes_each_path_as_one_argument():
    assert open_with.app_command(r"C:\djv\djv.exe", [r"\\nas\a b\x.mov", r"\\nas\c\y-0001.tga"], "win32") == [
        r"C:\djv\djv.exe", r"\\nas\a b\x.mov", r"\\nas\c\y-0001.tga"]


def test_windows_command_over_the_line_limit_is_refused():
    files = [rf"\\nas\share\{'x' * 200}_{i}.mov" for i in range(200)]
    with pytest.raises(ValueError, match="명령 줄"):
        open_with.app_command(r"C:\djv\djv.exe", files, "win32")


def test_no_files_is_an_error():
    with pytest.raises(ValueError):
        open_with.quicktime_command([])
    with pytest.raises(ValueError):
        open_with.app_command("/Applications/DJV.app", [], "darwin")


def test_other_platforms_are_refused():
    with pytest.raises(RuntimeError, match="linux"):
        open_with.app_command("/usr/bin/djv", ["/a/x.mov"], "linux")


def test_quicktime_only_on_mac():
    assert open_with.quicktime_available("darwin") is True
    assert open_with.quicktime_available("win32") is False


def test_app_label_drops_the_extension():
    assert open_with.app_label("/Applications/DJV.app") == "DJV"
    assert open_with.app_label(r"C:\Program Files\VideoLAN\VLC\vlc.exe") == "vlc"


def test_app_missing(tmp_path):
    app = make_app(tmp_path)
    exe = make_exe(tmp_path)
    assert open_with.app_missing(app, "darwin") is False
    assert open_with.app_missing(app + "x", "darwin") is True
    assert open_with.app_missing(exe, "win32") is False
    assert open_with.app_missing(exe + "x", "win32") is True


# ---------------------------------------------------------------- 등록한 앱 목록


def test_prefs_path_per_platform(local_appdata):
    assert open_with.prefs_path("darwin") == os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", "YesonCheck", "prefs.json")
    assert open_with.prefs_path("win32") == os.path.join(str(local_appdata), "YesonCheck", "prefs.json")


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_no_file_means_no_apps(platform, local_appdata):
    assert open_with.registered_apps(platform) == []


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_add_and_remove_keep_order_and_other_keys(platform, local_appdata, tmp_path):
    path = open_with.prefs_path(platform)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"playback_decoder": "ffmpeg"}, f)
    make = make_app if platform == "darwin" else make_exe
    first, second = make(tmp_path, "DJV"), make(tmp_path, "RV")

    assert open_with.add_app(first, platform) == [first]
    assert open_with.add_app(second, platform) == [first, second]
    assert open_with.add_app(first, platform) == [first, second]  # 이미 있으면 그대로 (자리도)
    assert open_with.registered_apps(platform) == [first, second]
    assert open_with.remove_app(first, platform) == [second]

    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == {"playback_decoder": "ffmpeg", "open_with_apps": [second]}


def test_add_rereads_the_file_so_another_windows_app_is_kept(tmp_path):
    """다른 창(프로세스)이 그사이 더한 앱을 지우지 않음 — 잠금 안에서 다시 읽고 고침."""
    first, second = make_app(tmp_path, "DJV"), make_app(tmp_path, "RV")
    open_with.add_app(first, "darwin")
    path = open_with.prefs_path("darwin")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    prefs["open_with_apps"].append(second)  # 다른 창이 더함
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)
    third = make_app(tmp_path, "mrViewer")
    assert open_with.add_app(third, "darwin") == [first, second, third]


@pytest.mark.parametrize("value", ["/Applications/DJV.app", ["/Applications/DJV.app", 3], {"a": 1}])
def test_bad_list_is_an_error_not_an_empty_list(value, tmp_path):
    path = open_with.prefs_path("darwin")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"open_with_apps": value}, f)
    with pytest.raises(UserFileError, match="open_with_apps"):
        open_with.registered_apps("darwin")
    with pytest.raises(UserFileError):
        open_with.add_app(make_app(tmp_path, "RV"), "darwin")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"open_with_apps": value}  # 덮어 지우지 않음


def test_broken_file_is_an_error():
    path = open_with.prefs_path("darwin")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    with pytest.raises(UserFileError):
        open_with.registered_apps("darwin")


def test_adding_something_that_is_not_an_app_is_refused(tmp_path, local_appdata):
    not_app = tmp_path / "notes"
    not_app.mkdir()
    with pytest.raises(ValueError, match=".app"):
        open_with.add_app(str(not_app), "darwin")
    with pytest.raises(ValueError, match=".exe"):
        open_with.add_app(make_app(tmp_path), "win32")
    assert open_with.registered_apps("darwin") == []


# ---------------------------------------------------------------- 띄우기 — Mac


class FakeProc:
    def __init__(self, returncode=0, output="", hang=False):
        self.returncode = returncode
        self._output = output
        self._hang = hang
        self.killed = False

    def communicate(self, timeout=None):
        if self._hang and not self.killed:
            raise subprocess.TimeoutExpired("open", timeout)
        return self._output, None

    def kill(self):
        self.killed = True


class FakePopen:
    def __init__(self, proc=None):
        self.calls = []
        self.proc = proc or FakeProc()

    def __call__(self, args, **kwargs):
        self.calls.append(SimpleNamespace(args=args, kwargs=kwargs))
        return self.proc


def test_mac_waits_for_open_and_succeeds():
    popen = FakePopen()
    open_with.open_with_quicktime(["/a/x.mov"], platform="darwin", popen=popen)
    assert popen.calls[0].args == ["/usr/bin/open", "-b", "com.apple.QuickTimePlayerX", "/a/x.mov"]
    assert popen.calls[0].kwargs["stdin"] == subprocess.DEVNULL


def test_mac_registered_app_is_launched_once_per_file():
    """DJV 3.7.5는 인자로 파일을 여럿 받아도 마지막 하나만 엶(`djv one.mov two.mov -exit -log` → `Opened ".../two.mov"`, `Files opened: 1`
    — 사용자 보고 2026-11-06: 둘을 골라 열면 하나만) → 등록한 앱은 파일마다 따로 띄움 (QuickTime처럼 고른 것이 다 열림)."""
    popen = FakePopen()
    open_with.open_with_app("/Applications/DJV.app", ["/a/x.mov", "/a/y-0001.tga"], platform="darwin", popen=popen)
    assert [call.args for call in popen.calls] == [
        ["/usr/bin/open", "-n", "-a", "/Applications/DJV.app", "--args", "/a/x.mov"],
        ["/usr/bin/open", "-n", "-a", "/Applications/DJV.app", "--args", "/a/y-0001.tga"]]


def test_windows_registered_app_is_launched_once_per_file(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    popen = FakePopen()
    open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov", r"\\nas\y.mov"], platform="win32", popen=popen)
    assert [call.args for call in popen.calls] == [[r"C:\djv\djv.exe", r"\\nas\x.mov"], [r"C:\djv\djv.exe", r"\\nas\y.mov"]]


def test_failure_after_some_files_says_how_many_opened():
    class FailSecond(FakePopen):
        def __call__(self, args, **kwargs):
            proc = super().__call__(args, **kwargs)
            return FakeProc(returncode=1, output="LSOpenURLsWithRole() failed") if len(self.calls) == 2 else proc

    popen = FailSecond()
    with pytest.raises(RuntimeError) as err:
        open_with.open_with_app("/Applications/DJV.app", ["/a/1.mov", "/a/2.mov", "/a/3.mov"], platform="darwin", popen=popen)
    assert len(popen.calls) == 2  # 실패한 뒤로는 띄우지 않음
    assert "3개 중 1개는 열었고" in str(err.value) and "/a/2.mov" in str(err.value)
    assert "LSOpenURLsWithRole" in str(err.value.__cause__)


def test_mac_open_failure_is_an_error_with_command_and_output():
    popen = FakePopen(FakeProc(returncode=1, output="Unable to find application named 'DJV'\n"))
    with pytest.raises(RuntimeError) as err:
        open_with.open_with_app("/Applications/DJV.app", ["/a/x.mov"], platform="darwin", popen=popen)
    text = str(err.value)
    assert "종료 코드 1" in text and "/Applications/DJV.app" in text and "Unable to find application" in text


def test_mac_open_that_hangs_is_killed_and_reported():
    proc = FakeProc(hang=True)
    with pytest.raises(RuntimeError, match="초 안에"):
        open_with.open_with_app("/Applications/DJV.app", ["/a/x.mov"], platform="darwin", popen=FakePopen(proc))
    assert proc.killed


def test_quicktime_off_mac_is_refused():
    with pytest.raises(RuntimeError, match="QuickTime"):
        open_with.open_with_quicktime(["/a/x.mov"], platform="win32", popen=FakePopen())


# ---------------------------------------------------------------- 띄우기 — Windows


class FakeDllDirectory:
    """open_with._WindowsDllDirectory와 같은 모양 (get·set) — set이 부른 값을 calls에."""

    def __init__(self, current, fail_reset=False, fail_restore=False):
        self.current = current
        self.calls = []
        self.fail_reset = fail_reset
        self.fail_restore = fail_restore

    def get(self):
        return self.current

    def set(self, path):
        self.calls.append(path)
        if (path is None and self.fail_reset) or (path is not None and self.fail_restore):
            raise OSError(f"SetDllDirectoryW({path!r})가 실패했습니다 (오류 5)")
        self.current = path


def frozen(monkeypatch, meipass):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)


def test_windows_source_run_does_not_wait_and_keeps_environment(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    popen = FakePopen()
    dll = FakeDllDirectory(None)
    open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=popen, dll_directory=dll)
    call = popen.calls[0]
    assert call.args == [r"C:\djv\djv.exe", r"\\nas\x.mov"]
    assert call.kwargs.get("env") is None
    assert call.kwargs["cwd"] == r"C:\djv"  # 앱 폴더에서 (자기 폴더 기준으로 파일을 찾는 앱)
    assert dll.calls == []  # 소스 실행은 DLL 검색 경로를 바꾸지 않았음


def test_windows_built_app_cleans_what_pyinstaller_changed(monkeypatch):
    """빌드 앱: 다른 Qt 앱이 이 앱의 Qt 플러그인·DLL을 읽지 않게 — PyInstaller 문서 'Launching external programs'."""
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)
    monkeypatch.setenv("QT_PLUGIN_PATH", meipass + r"\PyQt5\Qt5\plugins")
    monkeypatch.setenv("QML2_IMPORT_PATH", meipass + r"\PyQt5\Qt5\qml")
    # paddle은 불러올 때 자기 폴더(_MEIPASS 아래)를 PATH 앞에 넣음 — 그 아래 폴더도 뺌 (끝 \\·..도 같은 폴더)
    monkeypatch.setenv("PATH", ";".join([meipass + "\\", meipass + r"\paddle\base", meipass + r"\paddle\base\..\libs",
                                         r"C:\Windows\system32", r"C:\Tools", r"C:\Program Files\YesonCheck_internal_tools"]))
    monkeypatch.setenv("TCL_LIBRARY", meipass + r"\tcl\tcl8.6")  # 런타임 훅이 _MEIPASS 아래를 가리키게 한 다른 변수
    monkeypatch.setenv("YC_SAFE", r"C:\Data;D:\Other")
    popen = FakePopen()
    dll = FakeDllDirectory(meipass)
    open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=popen, dll_directory=dll)
    env = popen.calls[0].kwargs["env"]
    assert "QT_PLUGIN_PATH" not in env and "QML2_IMPORT_PATH" not in env and "TCL_LIBRARY" not in env
    assert env["PATH"].split(";") == [r"C:\Windows\system32", r"C:\Tools", r"C:\Program Files\YesonCheck_internal_tools"]
    assert env["YC_SAFE"] == r"C:\Data;D:\Other"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert dll.calls == [None, meipass]  # 띄우는 동안만 풀고 원래 값으로 되돌림
    assert os.environ["QT_PLUGIN_PATH"].endswith("plugins")  # 이 앱의 환경은 그대로


def test_windows_several_files_reset_the_dll_directory_once(monkeypatch):
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)
    popen = FakePopen()
    dll = FakeDllDirectory(meipass)
    open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov", r"\\nas\y.mov"], platform="win32", popen=popen,
                            dll_directory=dll)
    assert len(popen.calls) == 2 and dll.calls == [None, meipass]


def test_windows_dll_directory_is_restored_to_what_it_was(monkeypatch):
    """되돌리는 값은 _MEIPASS라고 짐작하지 않고 띄우기 전에 읽은 값."""
    frozen(monkeypatch, r"C:\Program Files\YesonCheck\_internal")
    dll = FakeDllDirectory(r"C:\elsewhere")
    open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=FakePopen(), dll_directory=dll)
    assert dll.calls == [None, r"C:\elsewhere"]


def test_windows_dll_directory_is_restored_even_when_launch_fails(monkeypatch):
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)
    dll = FakeDllDirectory(meipass)

    def broken_popen(args, **kwargs):
        raise FileNotFoundError(2, "지정된 파일을 찾을 수 없습니다", args[0])

    with pytest.raises(FileNotFoundError):
        open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=broken_popen,
                                dll_directory=dll)
    assert dll.calls == [None, meipass]


def test_windows_dll_directory_reset_failure_is_an_error(monkeypatch):
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)
    popen = FakePopen()
    with pytest.raises(OSError, match="SetDllDirectoryW"):
        open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=popen,
                                dll_directory=FakeDllDirectory(meipass, fail_reset=True))
    assert popen.calls == []  # 정리하지 못한 채 띄우지 않음


def test_windows_restore_failure_after_launch_says_the_app_opened(monkeypatch):
    """띄운 뒤 되돌리기만 실패: 열지 못한 것이 아니라 열었지만 되돌리지 못함 (DllDirectoryRestoreError)."""
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)
    popen = FakePopen()
    with pytest.raises(open_with.DllDirectoryRestoreError, match="띄웠지만"):
        open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=popen,
                                dll_directory=FakeDllDirectory(meipass, fail_restore=True))
    assert len(popen.calls) == 1


def test_windows_restore_failure_after_failed_launch_keeps_the_launch_error(monkeypatch):
    meipass = r"C:\Program Files\YesonCheck\_internal"
    frozen(monkeypatch, meipass)

    def broken_popen(args, **kwargs):
        raise FileNotFoundError(2, "지정된 파일을 찾을 수 없습니다", args[0])

    with pytest.raises(OSError) as err:
        open_with.open_with_app(r"C:\djv\djv.exe", [r"\\nas\x.mov"], platform="win32", popen=broken_popen,
                                dll_directory=FakeDllDirectory(meipass, fail_restore=True))
    assert not isinstance(err.value, open_with.DllDirectoryRestoreError)
    assert isinstance(err.value.__context__, FileNotFoundError)  # 띄우기 실패가 사슬에 남음


@pytest.mark.skipif(sys.platform != "win32", reason="진짜 kernel32 (Windows CI)")
def test_real_windows_dll_directory_binding_round_trips(tmp_path):
    dll = open_with._WindowsDllDirectory()
    before = dll.get()
    try:
        dll.set(str(tmp_path))
        assert dll.get() == str(tmp_path)
        dll.set(None)
        assert dll.get() is None
    finally:
        dll.set(before)
    assert dll.get() == before
