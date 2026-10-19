"""yesoncheck/update_helper_mac.sh(Mac 업데이트 도우미)와 update_install.launch_helper_mac 시험.

도우미 시험은 darwin에서만 돈다(macOS /bin/bash·ps·pgrep). 가짜 앱 = tmp_path 안의 .app 폴더로,
Contents/MacOS/YesonCheck_Autocut이 작은 셸 스크립트다: "new"는 시험이 환경 변수(YC_TEST_OK_FILE)로 알려 준
'잘 켜짐' 표시 파일에 {"version": "1.1.1"}을 쓰고, "silent"는 아무것도 쓰지 않고 계속 살아 있고, "crash"는 표시
없이 곧 끝난다. 모든 가짜 앱은 켜질 때 흔적 파일(YC_TEST_TRACE_DIR/<old|new>_started)에 자기 pid를 남긴다 —
옛 앱이 다시 켜졌는지·새 앱이 끝났는지를 그것으로 본다. YC_UPDATE_DIRECT_LAUNCH=1(open 대신 실행 파일을 직접
켬)과 짧은 --timeout으로 빠르게 돈다.

launch_helper_mac 시험(subprocess.Popen을 바꿔 끼움)은 모든 플랫폼에서 돈다.
"""

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yesoncheck import update_install

HELPER = Path(__file__).resolve().parent.parent / "yesoncheck" / "update_helper_mac.sh"
TARGET = "1.1.1"
LOG_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} ")  # update_install.log()와 같은 줄 앞 시각

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="Mac 업데이트 도우미 (macOS bash·ps·pgrep)")

_TRACE_START = 'printf "%s\\n" "$$" >> "$YC_TEST_TRACE_DIR/{name}_started"\n'
FAKE_APP_SCRIPTS = {
    "old": _TRACE_START.format(name="old"),
    "new": _TRACE_START.format(name="new")
    + f"printf '{{\"version\": \"{TARGET}\"}}' > \"$YC_TEST_OK_FILE.tmp\" && mv \"$YC_TEST_OK_FILE.tmp\" \"$YC_TEST_OK_FILE\"\n",
    "silent": _TRACE_START.format(name="new") + "while :; do sleep 1; done\n",
    "crash": _TRACE_START.format(name="new") + "sleep 1\nexit 3\n",
}


# ---- 시험 도우미 (이 시험 모듈 안에만 둠) ----


def make_fake_app(app_dir, kind):
    """가짜 .app: Contents/MacOS/YesonCheck_Autocut(셸 스크립트)와 어느 앱인지 적은 Contents/Resources/kind.txt."""
    exe = Path(app_dir) / "Contents" / "MacOS" / update_install.APP_EXECUTABLE_NAME
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n" + FAKE_APP_SCRIPTS[kind], encoding="utf-8")
    exe.chmod(0o755)
    resources = Path(app_dir) / "Contents" / "Resources"
    resources.mkdir()
    (resources / "kind.txt").write_text(kind, encoding="utf-8")


def app_kind(app_dir):
    return (Path(app_dir) / "Contents" / "Resources" / "kind.txt").read_text(encoding="utf-8")


def ended_pid():
    """이미 끝난(거둬들인) 프로세스의 pid — 도우미가 기다릴 것 없이 바로 바꾸기 시작함."""
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


def wait_until(condition, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def pid_gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def trace_pids(trace_dir, name):
    path = Path(trace_dir) / f"{name}_started"
    if not path.exists():
        return []
    return [int(x) for x in path.read_text(encoding="utf-8").split()]


@pytest.fixture
def update_case(tmp_path):
    """가짜 옛 앱(APP)·새 앱(STAGED, 종류는 make로 고름)·표시·로그·흔적 폴더를 만들어 주는 함수.

    끝날 때 가짜 앱 프로세스가 남아 있으면(도우미가 잘못돼 못 끝낸 경우) 끝내고, 시험이 잠근 폴더를 다시 연다.
    """
    made = []

    def make(new_kind, apps_dir_name="Applications", staged_in_apps_dir=True):
        apps_dir = tmp_path / apps_dir_name
        apps_dir.mkdir()
        app = apps_dir / "YesonCheck_Autocut_Intel.app"
        make_fake_app(app, "old")
        staged_parent = apps_dir if staged_in_apps_dir else tmp_path / "state"
        staged_parent.mkdir(exist_ok=True)
        staged = staged_parent / f".YesonCheck_Autocut_Intel.app.update-{TARGET}"
        make_fake_app(staged, new_kind)
        trace = tmp_path / "trace"
        trace.mkdir()
        logs = tmp_path / "logs"
        logs.mkdir()
        ok_file = tmp_path / "state" / "update_ok.json"
        ok_file.parent.mkdir(exist_ok=True)
        ok_file.write_text('{"version": "0.0.1"}', encoding="utf-8")  # 지난번 표시 — 도우미가 켜기 전에 지워야 함
        env = dict(os.environ)
        env.pop("YC_UPDATE_OK_TIMEOUT_S", None)
        env.pop("YC_UPDATE_PID_TIMEOUT_S", None)
        env.pop("YC_UPDATE_OSASCRIPT", None)
        env.update(YC_UPDATE_DIRECT_LAUNCH="1", YC_TEST_OK_FILE=str(ok_file), YC_TEST_TRACE_DIR=str(trace))
        case = SimpleNamespace(
            apps_dir=apps_dir,
            app=app,
            staged=staged,
            backup=apps_dir / "YesonCheck_Autocut_Intel.update-backup.app",
            ok_file=ok_file,
            log=logs / "update.log",
            trace=trace,
            env=env,
        )
        made.append(case)
        return case

    yield make
    for case in made:
        for name in ("old", "new"):
            for pid in trace_pids(case.trace, name):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if case.apps_dir.exists():
            case.apps_dir.chmod(0o755)


def helper_cmd(case, pid, timeout_s):
    return [
        "/bin/bash", str(HELPER),
        "--pid", str(pid),
        "--app", str(case.app),
        "--staged", str(case.staged),
        "--target", TARGET,
        "--ok", str(case.ok_file),
        "--log", str(case.log),
        "--timeout", str(timeout_s),
    ]


def run_helper(case, pid=None, timeout_s=4):
    """도우미를 끝까지 돌림 (넉넉히 60초 안에)."""
    return subprocess.run(
        helper_cmd(case, ended_pid() if pid is None else pid, timeout_s),
        env=case.env, capture_output=True, text=True, timeout=60,
    )


def log_text(case):
    return case.log.read_text(encoding="utf-8")


def failure_details(case, result):
    log = log_text(case) if case.log.exists() else "(로그 없음)"
    return f"종료 코드 {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\n로그:\n{log}"


# ---- Step 1: 브리핑의 시험 ----


@darwin_only
def test_helper_swaps_and_keeps_new(update_case):
    case = update_case("new")
    result = run_helper(case)
    assert result.returncode == 0, failure_details(case, result)
    assert app_kind(case.app) == "new"
    assert not case.backup.exists() and not case.staged.exists()
    assert not case.ok_file.exists()  # 성공 뒤 표시를 지움
    assert trace_pids(case.trace, "new") and not trace_pids(case.trace, "old")
    lines = [line for line in log_text(case).splitlines() if line]
    assert lines and all(LOG_LINE_RE.match(line) for line in lines), log_text(case)


@darwin_only
def test_helper_restores_when_new_app_silent(update_case):
    case = update_case("silent", apps_dir_name="앱 (시험)+[1]")  # 괄호·+·[] — pgrep/pkill 정규식이 글자 그대로 맞아야 함
    started = time.monotonic()
    result = run_helper(case, timeout_s=4)
    assert result.returncode == 1, failure_details(case, result)
    assert time.monotonic() - started >= 4  # --timeout까지 기다림
    assert app_kind(case.app) == "old"
    assert not case.backup.exists() and not case.staged.exists()
    assert [p.name for p in case.apps_dir.iterdir()] == [case.app.name]  # 치운 새 앱도 남지 않음
    assert wait_until(lambda: trace_pids(case.trace, "old")), "옛 앱이 다시 켜지지 않음\n" + log_text(case)
    silent_pid = trace_pids(case.trace, "new")[0]
    assert wait_until(lambda: pid_gone(silent_pid)), "표시 없는 새 앱이 끝나지 않음\n" + log_text(case)
    assert "되돌림" in log_text(case)


@darwin_only
def test_helper_waits_for_pid(update_case):
    case = update_case("new")
    sleeper = subprocess.Popen(["/bin/sleep", "3"])
    helper = subprocess.Popen(
        helper_cmd(case, sleeper.pid, 10), env=case.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        time.sleep(1.5)
        assert helper.poll() is None
        assert app_kind(case.app) == "old" and not case.backup.exists() and case.staged.exists()
        sleeper.wait()  # 거둬들임 (안 그러면 좀비로 남아 도우미에게 살아 있는 것처럼 보일 수 있음)
        out, err = helper.communicate(timeout=30)
    finally:
        sleeper.kill()
        helper.kill()
    assert helper.returncode == 0, f"{out}\n{err}\n{log_text(case)}"
    assert app_kind(case.app) == "new"


@darwin_only
def test_helper_uses_osascript_when_not_writable(update_case, tmp_path):
    case = update_case("new", apps_dir_name="응용 프로그램", staged_in_apps_dir=False)
    fake = tmp_path / "fake_osascript"
    fake.write_text(
        '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "$YC_TEST_TRACE_DIR/osascript_args"; done\nexit 0\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    case.env["YC_UPDATE_OSASCRIPT"] = str(fake)
    case.apps_dir.chmod(0o555)
    try:
        result = run_helper(case)
    finally:
        case.apps_dir.chmod(0o755)
    args = (case.trace / "osascript_args").read_text(encoding="utf-8")
    assert "with administrator privileges" in args
    assert f"mv '{case.app}' '{case.backup}'" in args
    assert f"mv '{case.staged}' '{case.app}'" in args
    # 기록만 하는 가짜라 실제로는 아무것도 옮겨지지 않음 → 알아채고 옛 앱을 그대로 켬
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old"
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


# ---- 브리핑 밖 추가 시험 ----


@darwin_only
def test_helper_restores_quickly_when_new_app_exits_without_marker(update_case):
    case = update_case("crash")
    started = time.monotonic()
    result = run_helper(case, timeout_s=60)
    assert result.returncode == 1, failure_details(case, result)
    assert time.monotonic() - started < 30  # 60초 다 기다리지 않음 (설계 5-5: 표시 없이 끝나면 실패)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)
    assert "되돌림" in log_text(case)


@darwin_only
def test_helper_changes_nothing_when_app_does_not_quit(update_case):
    case = update_case("new")
    case.env["YC_UPDATE_PID_TIMEOUT_S"] = "2"
    sleeper = subprocess.Popen(["/bin/sleep", "30"])
    try:
        result = run_helper(case, pid=sleeper.pid)
    finally:
        sleeper.kill()
        sleeper.wait()
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and case.staged.exists() and not case.backup.exists()
    assert not trace_pids(case.trace, "old") and not trace_pids(case.trace, "new")  # 아무것도 켜지 않음
    assert str(sleeper.pid) in log_text(case)


FAKE_ADMIN_OSASCRIPT = r'''#!{python}
"""관리자 암호 창 흉내: 받은 AppleScript에서 셸 명령을 꺼내, 잠긴 폴더를 잠깐 열고 그대로 실행한다."""
import os
import subprocess
import sys

trace = os.environ["YC_TEST_TRACE_DIR"]
with open(os.path.join(trace, "osascript_args"), "a", encoding="utf-8") as fh:
    fh.write(repr(sys.argv[1:]) + "\n")
assert len(sys.argv) == 3 and sys.argv[1] == "-e", sys.argv
script = sys.argv[2]
head = 'do shell script "'
assert script.startswith(head), script
command, i = [], len(head)
while script[i] != '"':
    if script[i] == "\\":
        i += 1
    command.append(script[i])
    i += 1
assert script[i + 1:].rstrip().endswith("with administrator privileges"), script
locked = os.environ["YC_TEST_LOCKED_DIR"]
os.chmod(locked, 0o755)
try:
    done = subprocess.run(["/bin/sh", "-c", "".join(command)], capture_output=True, text=True)
finally:
    os.chmod(locked, 0o555)
if done.returncode != 0:
    sys.stderr.write(f"execution error: {{done.stderr}} ({{done.returncode}})\n")
    sys.exit(1)
'''


@darwin_only
@pytest.mark.parametrize("new_kind", ["new", "silent"])
def test_helper_admin_path_quotes_paths_and_finishes(update_case, tmp_path, new_kind):
    # 따옴표·$·역슬래시·공백·한글이 든 폴더 이름 — 셸·AppleScript 따옴표 처리가 틀리면 mv가 엉뚱한 곳으로 감
    case = update_case(new_kind, apps_dir_name='앱 "큰" \'작은\' $HOME \\ (1)', staged_in_apps_dir=False)
    fake = tmp_path / "fake_admin_osascript"
    fake.write_text(FAKE_ADMIN_OSASCRIPT.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    case.env.update(YC_UPDATE_OSASCRIPT=str(fake), YC_TEST_LOCKED_DIR=str(case.apps_dir))
    case.apps_dir.chmod(0o555)
    try:
        result = run_helper(case, timeout_s=4)
    finally:
        case.apps_dir.chmod(0o755)
    calls = (case.trace / "osascript_args").read_text(encoding="utf-8").splitlines()
    if new_kind == "new":
        assert result.returncode == 0, failure_details(case, result)
        assert app_kind(case.app) == "new"
        assert len(calls) == 2  # 바꾸기 + 백업 지우기
    else:
        assert result.returncode == 1, failure_details(case, result)
        assert app_kind(case.app) == "old"
        assert len(calls) == 2  # 바꾸기 + 되돌리기
        assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)
    assert not case.backup.exists() and not case.staged.exists()
    assert [p.name for p in case.apps_dir.iterdir()] == [case.app.name]


# ---- launch_helper_mac (모든 플랫폼) ----


class _RecordingPopen:
    calls = []

    def __init__(self, args, **kwargs):
        _RecordingPopen.calls.append((args, kwargs))


def test_launch_helper_mac_copies_script_and_passes_arguments(tmp_state_dir, monkeypatch):
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_mac("/Applications/.X.app.update-1.1.1", "/Applications/X.app", "1.1.1")
    copy = os.path.join(update_install.state_dir(), "update_helper_mac.sh")
    assert _RecordingPopen.calls == [(
        [
            "/bin/bash", copy,
            "--pid", str(os.getpid()),
            "--app", "/Applications/X.app",
            "--staged", "/Applications/.X.app.update-1.1.1",
            "--target", "1.1.1",
            "--ok", update_install.ok_marker_path(),
            "--log", update_install.log_path(),
        ],
        {
            "start_new_session": True,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        },
    )]
    assert Path(copy).read_bytes() == HELPER.read_bytes()


def test_launch_helper_mac_uses_bundled_script_when_frozen(tmp_state_dir, tmp_path, monkeypatch):
    bundled = tmp_path / "meipass" / "yesoncheck" / "update_helper_mac.sh"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"# bundled copy\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_mac("/A/.X.app.update-1.1.1", "/A/X.app", "1.1.1")
    copy = Path(update_install.state_dir()) / "update_helper_mac.sh"
    assert copy.read_bytes() == b"# bundled copy\n"
    assert _RecordingPopen.calls[0][0][1] == str(copy)


def test_launch_helper_mac_does_not_swallow_popen_failure(tmp_state_dir, monkeypatch):
    def failing_popen(args, **kwargs):
        raise OSError("bash를 실행하지 못함")

    monkeypatch.setattr(update_install.subprocess, "Popen", failing_popen)
    with pytest.raises(OSError, match="bash를 실행하지 못함"):
        update_install.launch_helper_mac("/A/.X.app.update-1.1.1", "/A/X.app", "1.1.1")


def test_helper_script_runs_under_bash_without_errexit():
    text = HELPER.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n")
    # set -e를 쓰면 중간 실패에서 그냥 끝나 되돌리기가 돌지 않음 — 실패마다 직접 처리해야 함
    assert re.search(r"^set -u$", text, re.M) and not re.search(r"^set -[a-z]*e", text, re.M)
