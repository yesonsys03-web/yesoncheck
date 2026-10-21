"""yesoncheck/new_window.py 시험: 새 YesonCheck 창(프로세스) 띄우기 — 파일마다 하나, 빈 목록이면 하나.

Mac 빌드 앱은 `open -n <자기 번들> [--args 파일]`을 띄우고 `open`이 끝나기를 기다린다(0이 아니거나 시간이 지나면
RuntimeError). 소스 실행·Windows 빌드 앱은 앱 프로세스를 바로 띄우고 기다리지 않는다. Popen·platform은 주입 —
Mac에서도 Windows 분기를 시험한다(Review Focus 1: 경로가 한 인자 그대로 닿는지).
"""

import inspect
import subprocess
import sys

import pytest

from yesoncheck import launch_args, new_window

MAC_BUNDLE = "/Applications/YesonCheck_Autocut.app"
WINDOWS_EXE = "C:\\Users\\studio01\\AppData\\Local\\Programs\\YesonCheck\\YesonCheck_Autocut.exe"

# 더블클릭·연결 프로그램으로 넘어오는 경로 — 공백·한글·작은따옴표·`#` (test_launch_args와 같은 모양)
ODD_PATHS = [
    "/Volumes/USA_DB/FL_901 컷/장면 #3 (최종)'s.mov",
    "C:\\Users\\studio01\\동영상\\A B #1 'x'.mp4",
    '/Volumes/USA_DB/"큰따옴표" $HOME `x`;&.mp4',
]


class FakeProc:
    """Popen이 돌려주는 프로세스 대역: communicate()가 (출력, None)을 돌려주거나 시간 초과를 흉내."""

    def __init__(self, args, returncode, output, hangs):
        self.args = args
        self._returncode = returncode
        self._output = output
        self._hangs = hangs
        self.returncode = None
        self.communicate_timeouts = []
        self.killed = False

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        if self._hangs and not self.killed:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.returncode = self._returncode
        return self._output, None

    def kill(self):
        self.killed = True


class FakePopen:
    """subprocess.Popen 대역: 부른 argv·kwargs를 차례로 기록. returncodes는 부를 때마다 하나씩 쓰는 `open`의 종료 코드."""

    def __init__(self, returncodes=(0,), output="", hangs=False, error=None):
        self.returncodes = list(returncodes)
        self.output = output
        self.hangs = hangs
        self.error = error
        self.calls = []  # [(args, kwargs)]
        self.procs = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        code = self.returncodes.pop(0) if len(self.returncodes) > 1 else self.returncodes[0]
        proc = FakeProc(args, code, self.output, self.hangs)
        self.procs.append(proc)
        return proc

    @property
    def argvs(self):
        return [args for args, _ in self.calls]


def _forbid_bundle_lookup(monkeypatch):
    def forbidden():
        raise AssertionError("running_app_location()을 부르면 안 됩니다")

    monkeypatch.setattr(new_window.update_install, "running_app_location", forbidden)


@pytest.fixture
def mac_frozen(monkeypatch):
    """Mac 빌드 앱처럼: sys.frozen, 자기 번들 위치(update_install.running_app_location)는 MAC_BUNDLE."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(new_window.update_install, "running_app_location", lambda: MAC_BUNDLE)
    return "darwin"


@pytest.fixture
def windows_frozen(monkeypatch):
    """Windows 빌드 앱처럼: sys.frozen, 실행 파일 sys.executable은 WINDOWS_EXE (설치 폴더는 보지 않음)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", WINDOWS_EXE)
    _forbid_bundle_lookup(monkeypatch)
    return "win32"


@pytest.fixture
def source_run(monkeypatch):
    """소스 실행: sys.frozen 없음, 번들 위치는 절대 묻지 않음 (running_app_location은 소스 실행에서 UpdateError)."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    _forbid_bundle_lookup(monkeypatch)
    return "darwin"


MODES = ["mac_frozen", "windows_frozen", "source_run"]


class Mode:
    """세 가지 실행 모양 중 하나: 이름과 spawn에 넘길 platform."""

    def __init__(self, name, platform):
        self.name = name
        self.platform = platform

    def argv(self, file):
        """파일 하나를 띄울 때의 기대 argv (file이 None이면 파일 없음)."""
        tail = [] if file is None else [file]
        if self.name == "mac_frozen":
            return ["/usr/bin/open", "-n", MAC_BUNDLE, *(["--args", file] if file is not None else [])]
        if self.name == "windows_frozen":
            return [WINDOWS_EXE, *tail]
        return [sys.executable, "-m", "yesoncheck.app", *tail]

    def app_args(self, argv):
        """argv에서 새 앱이 자기 sys.argv로 받는 인자(열 파일들) 부분."""
        if self.name == "mac_frozen":
            return argv[argv.index("--args") + 1:] if "--args" in argv else []
        return argv[1:] if self.name == "windows_frozen" else argv[3:]


@pytest.fixture(params=MODES)
def mode(request):
    """세 가지 실행 모양을 차례로."""
    return Mode(request.param, request.getfixturevalue(request.param))


def test_mac_frozen_uses_open_n_with_own_bundle(mac_frozen):
    popen = FakePopen()
    new_window.spawn([ODD_PATHS[0]], platform=mac_frozen, popen=popen)
    assert popen.argvs == [["/usr/bin/open", "-n", MAC_BUNDLE, "--args", ODD_PATHS[0]]]
    # open이 끝나기를 정해진 시간 안에서 기다림 (LaunchServices가 앱을 띄운 뒤 open이 돌아옴)
    assert popen.procs[0].communicate_timeouts == [new_window.OPEN_TIMEOUT_S]
    assert 0 < new_window.OPEN_TIMEOUT_S <= 60
    # 파일이 없으면 --args 없이
    popen = FakePopen()
    new_window.spawn([], platform=mac_frozen, popen=popen)
    assert popen.argvs == [["/usr/bin/open", "-n", MAC_BUNDLE]]


def test_one_process_per_file(mode):
    files = ["/Volumes/USA_DB/a.mov", "/Volumes/USA_DB/b.mp4", "/Volumes/USA_DB/c.MOV"]
    popen = FakePopen()
    new_window.spawn(files, platform=mode.platform, popen=popen)
    assert popen.argvs == [mode.argv(f) for f in files]


def test_empty_list_spawns_one_process_without_file(mode):
    popen = FakePopen()
    new_window.spawn([], platform=mode.platform, popen=popen)
    assert popen.argvs == [mode.argv(None)]


def test_paths_with_space_korean_quote_hash_passed_as_single_args(mode):
    popen = FakePopen()
    new_window.spawn(ODD_PATHS, platform=mode.platform, popen=popen)
    assert len(popen.calls) == len(ODD_PATHS)
    for (args, kwargs), path in zip(popen.calls, ODD_PATHS):
        # 목록 그대로(셸 없음) — 경로 하나가 인자 하나, 나누거나 따옴표를 벗기거나 덧붙이지 않음
        assert isinstance(args, list) and args == mode.argv(path)
        assert args.count(path) == 1
        assert not kwargs.get("shell")
        # 새 앱이 받는 쪽(launch_args.parse)에서도 그 경로 하나가 열 파일 하나로 보임
        assert launch_args.parse(["YesonCheck", *mode.app_args(args)]).files == [path]


def test_open_failure_raises_with_output(mac_frozen):
    popen = FakePopen(returncodes=(1,), output="The application cannot be opened for an unexpected reason (error -600)")
    with pytest.raises(RuntimeError) as excinfo:
        new_window.spawn([ODD_PATHS[0]], platform=mac_frozen, popen=popen)
    message = str(excinfo.value)
    assert "/usr/bin/open" in message and MAC_BUNDLE in message and ODD_PATHS[0] in message  # 명령
    assert "error -600" in message  # open의 출력
    assert "종료 코드 1" in message


def test_open_timeout_raises_with_command_and_output(mac_frozen):
    popen = FakePopen(output="LaunchServices is busy", hangs=True)
    with pytest.raises(RuntimeError) as excinfo:
        new_window.spawn([ODD_PATHS[0]], platform=mac_frozen, popen=popen)
    message = str(excinfo.value)
    assert "/usr/bin/open" in message and MAC_BUNDLE in message
    assert "LaunchServices is busy" in message
    assert str(new_window.OPEN_TIMEOUT_S) in message
    assert popen.procs[0].killed  # 멈춘 open은 끝냄 (남기지 않음)


def test_open_failure_stops_remaining_files(mac_frozen):
    popen = FakePopen(returncodes=(0, 1), output="boom")
    files = ["/a.mov", "/b.mov", "/c.mov"]
    with pytest.raises(RuntimeError):
        new_window.spawn(files, platform=mac_frozen, popen=popen)
    assert len(popen.calls) == 2  # 실패한 파일 다음은 띄우지 않음 (앞 파일의 창은 이미 떴음)


def test_source_run_starts_module_directly_without_waiting(source_run):
    popen = FakePopen()
    new_window.spawn([ODD_PATHS[0]], platform=source_run, popen=popen)
    assert popen.argvs == [[sys.executable, "-m", "yesoncheck.app", ODD_PATHS[0]]]
    assert popen.procs[0].communicate_timeouts == []  # 기다리지 않음 — 그 프로세스가 새 창


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_source_run_is_the_same_on_every_platform(source_run, platform):
    popen = FakePopen()
    new_window.spawn([], platform=platform, popen=popen)
    assert popen.argvs == [[sys.executable, "-m", "yesoncheck.app"]]


def test_windows_frozen_starts_own_exe_without_waiting(windows_frozen):
    popen = FakePopen()
    new_window.spawn([ODD_PATHS[1]], platform=windows_frozen, popen=popen)
    (args, kwargs), = popen.calls
    assert args == [WINDOWS_EXE, ODD_PATHS[1]]
    assert popen.procs[0].communicate_timeouts == []
    # 같은 실행 파일이 이 앱의 하위 작업으로 취급되지 않게 (PyInstaller 부트로더 — update_install._helper_env와 같은 이유)
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_frozen_on_unsupported_platform_raises(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    popen = FakePopen()
    with pytest.raises(RuntimeError, match="linux"):
        new_window.spawn(["/a.mov"], platform="linux", popen=popen)
    assert popen.calls == []


def test_popen_failure_propagates_unchanged(mode):
    error = FileNotFoundError(2, "No such file or directory", "/usr/bin/open")
    with pytest.raises(FileNotFoundError) as excinfo:
        new_window.spawn(["/a.mov"], platform=mode.platform, popen=FakePopen(error=error))
    assert excinfo.value is error  # 감싸거나 삼키지 않음


def test_default_popen_and_platform_are_real():
    params = inspect.signature(new_window.spawn).parameters
    assert params["popen"].default is subprocess.Popen
    assert params["platform"].default == sys.platform
    assert list(params) == ["files", "platform", "popen"]
