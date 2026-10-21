"""yesoncheck/update_helper_mac.sh(Mac 업데이트 도우미)와 update_install.launch_helper_mac 시험.

도우미 시험은 darwin에서만 돈다(macOS /bin/bash·ps·pgrep). 가짜 앱 = tmp_path 안의 .app 폴더로,
Contents/MacOS/YesonCheck_Autocut이 작은 셸 스크립트다: "new"는 시험이 환경 변수(YC_TEST_OK_FILE)로 알려 준
'잘 켜짐' 표시 파일에 {"version": "1.1.1"}을 쓰고, "silent"는 아무것도 쓰지 않고 계속 살아 있고, "crash"는 표시
없이 곧 끝난다. 모든 가짜 앱은 켜질 때 흔적 파일(YC_TEST_TRACE_DIR/<old|new>_started)에 자기 pid를, <old|new>_args에
받은 인자를 남긴다 — 옛 앱이 다시 켜졌는지·새 앱이 끝났는지·결과 판정 토큰(--update-result)을 받았는지를 그것으로 본다.
YC_UPDATE_DIRECT_LAUNCH=1(open 대신 실행 파일을 직접 켬)과 짧은 --timeout으로 빠르게 돈다. 실제 배포 경로(open -n -W)는
가짜 open(YC_UPDATE_OPEN=FAKE_OPEN)으로 시험한다. 같은 앱 번들의 다른 창은 가짜 앱 안의 Contents/MacOS/other_window를
진짜 프로세스로 띄워 흉내 낸다 (명령 줄에 앱 경로가 들어 있어 도우미의 pgrep에 보임).

launch_helper_mac 시험(subprocess.Popen을 바꿔 끼움)은 모든 플랫폼에서 돈다.
"""

import json
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
TOKEN = "0123456789abcdef"  # 앱이 넘기는 업데이트 토큰 (도우미가 다시 켜는 앱만 결과를 판정 — update_install.Pending)
LOG_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} ")  # update_install.log()와 같은 줄 앞 시각

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="Mac 업데이트 도우미 (macOS bash·ps·pgrep)")

_TRACE_START = ('printf "%s\\n" "$$" >> "$YC_TEST_TRACE_DIR/{name}_started"\n'
                'printf "%s\\n" "$*" >> "$YC_TEST_TRACE_DIR/{name}_args"\n')
FAKE_APP_SCRIPTS = {
    "old": _TRACE_START.format(name="old"),
    "new": _TRACE_START.format(name="new")
    + f"printf '{{\"version\": \"{TARGET}\"}}' > \"$YC_TEST_OK_FILE.tmp\" && mv \"$YC_TEST_OK_FILE.tmp\" \"$YC_TEST_OK_FILE\"\n",
    "silent": _TRACE_START.format(name="new") + "while :; do sleep 1; done\n",
    "crash": _TRACE_START.format(name="new") + "sleep 1\nexit 3\n",
    # 실제 /Applications 시험에서 본 것: 새 앱이 켜지자마자(몇 ms) 표시 없이 죽음
    "exit_now": _TRACE_START.format(name="new") + "exit 1\n",
    # 표시를 쓰고 계속 돎 (open -W가 끝나지 않음)
    "new_stays": _TRACE_START.format(name="new")
    + f"printf '{{\"version\": \"{TARGET}\"}}' > \"$YC_TEST_OK_FILE.tmp\" && mv \"$YC_TEST_OK_FILE.tmp\" \"$YC_TEST_OK_FILE\"\n"
    + "while :; do sleep 1; done\n",
}


# 같은 앱 번들에서 도는 다른 창 흉내: $1 파일이 생길 때까지 돎 (start_other_window)
OTHER_WINDOW_SCRIPT = '#!/bin/sh\nwhile [ ! -e "$1" ]; do sleep 0.1; done\n'


# ---- 시험 도우미 (이 시험 모듈 안에만 둠) ----


def make_fake_app(app_dir, kind):
    """가짜 .app: Contents/MacOS/YesonCheck_Autocut(셸 스크립트)·other_window(다른 창 흉내)와 어느 앱인지 적은
    Contents/Resources/kind.txt."""
    exe = Path(app_dir) / "Contents" / "MacOS" / update_install.APP_EXECUTABLE_NAME
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n" + FAKE_APP_SCRIPTS[kind], encoding="utf-8")
    exe.chmod(0o755)
    other = exe.parent / "other_window"
    other.write_text(OTHER_WINDOW_SCRIPT, encoding="utf-8")
    other.chmod(0o755)
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


def trace_args(trace_dir, name):
    """그 가짜 앱이 켜질 때마다 받은 인자 (켤 때마다 한 줄, 공백으로 이음 — 인자가 없으면 빈 줄)."""
    path = Path(trace_dir) / f"{name}_args"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def start_other_window(case):
    """같은 앱 번들(APP)에서 도는 다른 창 흉내 — APP/Contents/MacOS/other_window를 진짜 프로세스로. 흔적 폴더에
    other_stop이 생기면(stop_other_window) 끝남."""
    return subprocess.Popen(["/bin/sh", str(case.app / "Contents" / "MacOS" / "other_window"),
                             str(case.trace / "other_stop")])


def stop_other_window(case, proc):
    (case.trace / "other_stop").touch()
    try:
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


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
        env.pop("YC_OTHERS_TIMEOUT", None)
        # YC_UPDATE_NO_MESSAGEBOX: 종료 코드 2의 알림 창(osascript display alert)을 띄우지 않음 — 시험이 멈추지 않게
        env.update(YC_UPDATE_DIRECT_LAUNCH="1", YC_TEST_OK_FILE=str(ok_file), YC_TEST_TRACE_DIR=str(trace),
                   YC_UPDATE_NO_MESSAGEBOX="1")
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
    if made:
        kill_processes_under(tmp_path)
        unlock_tree(tmp_path)


def kill_processes_under(path):
    """명령줄에 path가 든 프로세스(이 시험이 켠 가짜 앱·도우미)만 끝냄 — 흔적 파일의 pid를 믿지 않음(pid는 다시
    쓰일 수 있어 엉뚱한 프로세스를 끝낼 수 있음)."""
    listing = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, check=True).stdout
    for line in listing.decode("utf-8", errors="replace").splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if str(path) in command and int(pid_text) != os.getpid():
            try:
                os.kill(int(pid_text), signal.SIGKILL)
            except ProcessLookupError:
                pass


def unlock_tree(path):
    """시험이 잠근(chmod 555) 폴더를 모두 다시 열어 tmp_path를 지울 수 있게."""
    for root, dirs, _files in os.walk(path):
        for name in dirs:
            full = os.path.join(root, name)
            if not os.path.islink(full):
                os.chmod(full, 0o755)


def lock(path):
    """폴더를 이 사용자가 바꿀 수 없게 (chmod 555) — 다른 계정·root 것인 폴더 흉내."""
    Path(path).chmod(0o555)


def helper_cmd(case, pid, timeout_s, staged=None, token=TOKEN):
    """도우미 명령 — 앱(launch_helper_mac)처럼 --token을 넘김 (token=None이면 넘기지 않음: 토큰을 모르는 옛 앱)."""
    return [
        "/bin/bash", str(HELPER),
        "--pid", str(pid),
        "--app", str(case.app),
        "--staged", str(case.staged) if staged is None else staged,
        "--target", TARGET,
        "--ok", str(case.ok_file),
        "--log", str(case.log),
        "--timeout", str(timeout_s),
    ] + ([] if token is None else ["--token", token])


def run_helper(case, pid=None, timeout_s=4, staged=None, token=TOKEN):
    """도우미를 끝까지 돌림 (넉넉히 90초 안에)."""
    return subprocess.run(
        helper_cmd(case, ended_pid() if pid is None else pid, timeout_s, staged, token),
        env=case.env, capture_output=True, text=True, timeout=90,
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
    case = update_case("silent", apps_dir_name="앱 (시험)+[1]")  # 괄호·+·[] — pgrep 정규식이 글자 그대로 맞아야 함
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
"""관리자 암호 창 흉내: 받은 AppleScript에서 셸 명령을 꺼내 기록하고, 잠긴 폴더들을 잠깐 열어 그대로 실행한다.

YC_TEST_LOCKED_DIRS(줄마다 하나) = root 권한이면 바꿀 수 있는, 시험이 잠근 폴더들. YC_TEST_ADMIN_REFUSE가 명령에
들어 있으면 사용자가 암호 창에서 '취소'를 누른 것처럼 실행하지 않고 끝난다. 명령은 진짜 do shell script처럼
PATH=/usr/bin:/bin:/usr/sbin:/sbin으로 돌리고(YC_TEST_ADMIN_PATH가 있으면 그 폴더를 앞에 — 가짜 mv 등), 실패하면
진짜 osascript처럼 stderr의 여러 줄을 \r로 이어 "execution error: … (종료 코드)"로 보인다.
"""
import json
import os
import subprocess
import sys

assert len(sys.argv) == 3 and sys.argv[1] == "-e", sys.argv
script = sys.argv[2]
head = 'do shell script "'
assert script.startswith(head), script
chars, i = [], len(head)
while script[i] != '"':
    if script[i] == "\\":
        i += 1
    chars.append(script[i])
    i += 1
assert script[i + 1:].rstrip().endswith("with administrator privileges"), script
command = "".join(chars)
with open(os.path.join(os.environ["YC_TEST_TRACE_DIR"], "admin_commands"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(command, ensure_ascii=False) + "\n")
refuse = os.environ.get("YC_TEST_ADMIN_REFUSE")
if refuse and refuse in command:
    sys.stderr.write("execution error: User canceled. (-128)\n")
    sys.exit(1)
locked = [d for d in os.environ.get("YC_TEST_LOCKED_DIRS", "").split("\n") if d]
for d in locked:
    if os.path.isdir(d):
        os.chmod(d, 0o755)
env = dict(os.environ, PATH="/usr/bin:/bin:/usr/sbin:/sbin")
if os.environ.get("YC_TEST_ADMIN_PATH"):
    env["PATH"] = os.environ["YC_TEST_ADMIN_PATH"] + ":" + env["PATH"]
try:
    done = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, env=env)
finally:
    for d in locked:
        if os.path.isdir(d):
            os.chmod(d, 0o555)
if done.returncode != 0:
    message = done.stderr.rstrip("\n").replace("\n", "\r")
    sys.stderr.write(f"execution error: {{message}} ({{done.returncode}})\n")
    sys.exit(1)
'''


def use_fake_admin(case, tmp_path, locked_dirs, refuse=None):
    """관리자 암호 창 대신 FAKE_ADMIN_OSASCRIPT를 쓰게 함. locked_dirs는 '관리자'가 바꿀 수 있는 잠긴 폴더들
    (부를 때의 경로 — 도우미가 옮긴 뒤의 이름일 수 있음). 잠그는 것은 부른 쪽이 lock()으로."""
    fake = tmp_path / "fake_admin_osascript"
    fake.write_text(FAKE_ADMIN_OSASCRIPT.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    case.env.update(YC_UPDATE_OSASCRIPT=str(fake), YC_TEST_LOCKED_DIRS="\n".join(str(d) for d in locked_dirs))
    if refuse:
        case.env["YC_TEST_ADMIN_REFUSE"] = refuse


def admin_commands(case):
    path = case.trace / "admin_commands"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@darwin_only
@pytest.mark.parametrize("new_kind", ["new", "silent"])
def test_helper_admin_path_quotes_paths_and_finishes(update_case, tmp_path, new_kind):
    # 따옴표·$·역슬래시·공백·한글이 든 폴더 이름 — 셸·AppleScript 따옴표 처리가 틀리면 mv가 엉뚱한 곳으로 감
    case = update_case(new_kind, apps_dir_name='앱 "큰" \'작은\' $HOME \\ (1)', staged_in_apps_dir=False)
    use_fake_admin(case, tmp_path, [case.apps_dir])
    lock(case.apps_dir)
    result = run_helper(case, timeout_s=4)
    unlock_tree(tmp_path)
    calls = admin_commands(case)
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


@darwin_only
def test_helper_admin_swap_undoes_itself_when_second_move_fails(update_case, tmp_path):
    case = update_case("new", apps_dir_name="응용 프로그램", staged_in_apps_dir=False)
    use_fake_admin(case, tmp_path, [case.apps_dir])  # 준비한 새 앱의 폴더는 '관리자'도 못 바꿈 → 두 번째 mv 실패
    lock(case.apps_dir)
    lock(case.staged.parent)
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    # 같은 관리자 명령 안에서 옛 앱을 되돌려 놓음 — 되돌리려고 암호 창을 또 띄우지 않음
    assert len([c for c in admin_commands(case) if "mv " in c]) == 1, admin_commands(case)
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


@darwin_only
def test_helper_deletes_stale_backup_user_cannot_delete_with_admin(update_case, tmp_path):
    # 지난 업데이트의 백업이 다른 계정·root 것이라 사용자로 못 지우면, 그대로 두면 모든 다음 업데이트가 막힘
    case = update_case("new")
    make_fake_app(case.backup, "old")
    locked = case.backup / "Contents" / "Resources"
    use_fake_admin(case, tmp_path, [locked])
    lock(locked)
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 0, failure_details(case, result)
    assert app_kind(case.app) == "new" and not case.backup.exists()
    assert admin_commands(case) == [f"rm -rf '{case.backup}'"]


@darwin_only
def test_helper_deletes_backup_user_cannot_delete_with_admin_after_success(update_case, tmp_path):
    case = update_case("new")
    lock(case.app / "Contents" / "Resources")  # 옛 앱 안 — 바꾼 뒤에는 백업 안
    use_fake_admin(case, tmp_path, [case.backup / "Contents" / "Resources"])
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 0, failure_details(case, result)
    assert app_kind(case.app) == "new" and not case.backup.exists()
    assert admin_commands(case) == [f"rm -rf '{case.backup}'"]


@darwin_only
def test_helper_deletes_staged_with_admin_after_cancelled_prompt(update_case, tmp_path):
    case = update_case("new", apps_dir_name="응용 프로그램", staged_in_apps_dir=False)
    locked = case.staged / "Contents" / "Resources"
    use_fake_admin(case, tmp_path, [locked], refuse="mv ")  # 바꾸기 암호 창은 '취소'
    lock(case.apps_dir)
    lock(locked)
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.staged.exists()
    calls = admin_commands(case)
    assert len(calls) == 2 and "mv " in calls[0] and calls[1] == f"rm -rf '{case.staged}'", calls
    assert "User canceled" in log_text(case)


@darwin_only
def test_helper_restore_ignores_undeletable_leftover_from_earlier_run(update_case):
    case = update_case("crash")
    leftover = case.apps_dir / ".YesonCheck_Autocut_Intel.app.update-failed"  # 지난번 이름, 사용자로 못 지움
    make_fake_app(leftover, "new")
    lock(leftover / "Contents" / "Resources")
    result = run_helper(case, timeout_s=30)
    unlock_tree(case.apps_dir)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    assert sorted(p.name for p in case.apps_dir.iterdir()) == sorted([case.app.name, leftover.name])
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


FAKE_FAILING_MV = """#!/bin/sh
# 다른 볼륨에서 옮기다(복사 뒤 지우기) 중간에 실패한 mv 흉내: 대상에 반쯤 복사된 앱을 남기고 실패
if [ "$1" = "$YC_TEST_FAIL_MV_SOURCE" ]; then
    mkdir -p "$2/Contents" && echo partial > "$2/Contents/partial.txt"
    echo "mv: $2: 복사하다 실패 (시험)" >&2
    exit 1
fi
exec /bin/mv "$@"
"""


@darwin_only
@pytest.mark.parametrize("mode", ["admin", "user"])
def test_helper_partial_move_leaves_app_for_restore(update_case, tmp_path, mode):
    # 준비한 새 앱이 다른 볼륨(state_dir)에 있으면 mv는 복사+지우기 — 중간에 실패하면 앱 자리에 반쪽이 남는다.
    # 그때 'mv 백업 앱'을 하면 백업이 반쪽 앱 *안으로* 들어가 옛 앱을 잃음 (관리자·사용자 방식 둘 다 확인)
    case = update_case("new", apps_dir_name="응용 프로그램", staged_in_apps_dir=False)
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    (fake_bin / "mv").write_text(FAKE_FAILING_MV, encoding="utf-8")
    (fake_bin / "mv").chmod(0o755)
    case.env["YC_TEST_FAIL_MV_SOURCE"] = str(case.staged)
    if mode == "admin":
        use_fake_admin(case, tmp_path, [case.apps_dir])
        case.env["YC_TEST_ADMIN_PATH"] = str(fake_bin)
        lock(case.apps_dir)
    else:
        case.env["PATH"] = f"{fake_bin}:{case.env['PATH']}"  # 도우미가 사용자로 부르는 mv
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    assert not (case.app / case.backup.name).exists() and not (case.app / "Contents" / "partial.txt").exists()
    assert [p.name for p in case.apps_dir.iterdir()] == [case.app.name]
    # 관리자: 바꾸기(실패) + 되돌리기(반쪽 앱을 치우고 백업을 제자리로)
    assert len(admin_commands(case)) == (2 if mode == "admin" else 0)
    assert "복사하다 실패" in log_text(case)
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


FAKE_MV_FAILING_FOR_SOURCE = """#!/bin/sh
# 이 원본을 옮기는 mv만 실패 (되돌리기의 '백업을 제자리로'를 막음)
if [ "$1" = "$YC_TEST_FAIL_MV_SOURCE" ]; then
    echo "mv: $1: 옮기지 못함 (시험)" >&2
    exit 1
fi
exec /bin/mv "$@"
"""

FAKE_ALERT_OSASCRIPT = '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "$YC_TEST_TRACE_DIR/osascript_args"; done\nexit 0\n'


def fail_restore(case, tmp_path):
    """되돌리기의 '백업을 제자리로' mv가 실패하게 (사용자로 부르는 mv를 가짜로)."""
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    (fake_bin / "mv").write_text(FAKE_MV_FAILING_FOR_SOURCE, encoding="utf-8")
    (fake_bin / "mv").chmod(0o755)
    case.env["PATH"] = f"{fake_bin}:{case.env['PATH']}"
    case.env["YC_TEST_FAIL_MV_SOURCE"] = str(case.backup)


@darwin_only
def test_helper_failed_rollback_shows_last_resort_alert(update_case, tmp_path):
    """되돌리기마저 실패하면(종료 코드 2) 앱 자리에 앱이 없을 수 있어 다음 실행에서 알릴 수 없음 → 마지막으로 알림 창
    (osascript display alert)에 백업 앱 자리를 (Windows의 메시지 창과 같음)."""
    case = update_case("crash")
    fail_restore(case, tmp_path)
    fake = tmp_path / "fake_alert_osascript"
    fake.write_text(FAKE_ALERT_OSASCRIPT, encoding="utf-8")
    fake.chmod(0o755)
    case.env["YC_UPDATE_OSASCRIPT"] = str(fake)
    del case.env["YC_UPDATE_NO_MESSAGEBOX"]
    result = run_helper(case, timeout_s=30)
    assert result.returncode == 2, failure_details(case, result)
    args = (case.trace / "osascript_args").read_text(encoding="utf-8")
    assert "display alert" in args and "as critical" in args, args
    assert str(case.backup) in args and str(case.app) in args and str(case.log) in args, args
    assert "되돌리기 실패" in log_text(case) and "옮기지 못함 (시험)" in log_text(case)
    assert case.backup.exists() and app_kind(case.backup) == "old"  # 손으로 되돌릴 수 있게 남아 있음


@darwin_only
def test_helper_failed_rollback_alert_skipped_in_tests(update_case, tmp_path):
    case = update_case("crash")
    fail_restore(case, tmp_path)
    result = run_helper(case, timeout_s=30)
    assert result.returncode == 2, failure_details(case, result)
    assert "알림 창은 띄우지 않음 (YC_UPDATE_NO_MESSAGEBOX=1)" in log_text(case)
    assert not (case.trace / "osascript_args").exists()


@darwin_only
def test_helper_alerts_when_app_missing_at_start(update_case, tmp_path):
    case = update_case("new")
    (case.app / "Contents" / "MacOS" / update_install.APP_EXECUTABLE_NAME).unlink()
    fake = tmp_path / "fake_alert_osascript"
    fake.write_text(FAKE_ALERT_OSASCRIPT, encoding="utf-8")
    fake.chmod(0o755)
    case.env["YC_UPDATE_OSASCRIPT"] = str(fake)
    del case.env["YC_UPDATE_NO_MESSAGEBOX"]
    result = run_helper(case)
    assert result.returncode == 2, failure_details(case, result)
    args = (case.trace / "osascript_args").read_text(encoding="utf-8")
    assert "display alert" in args and str(case.app) in args, args
    assert case.staged.exists()  # 아무것도 바꾸지 않음


@darwin_only
@pytest.mark.parametrize("how", ["same", "trailing_slash", "symlink", "inside"])
def test_helper_refuses_staged_that_is_the_app(update_case, tmp_path, how):
    # --staged가 --app과 같은 곳이면 바꾸기가 실패해 되돌린 뒤 '준비한 새 앱 지우기'가 되돌린 앱을 지움 → 시작 전에 거절
    case = update_case("new")
    if how == "symlink":
        alias = tmp_path / "alias.app"
        alias.symlink_to(case.app)
        staged = str(alias)
    else:
        staged = {"same": str(case.app), "trailing_slash": str(case.app) + "/",
                  "inside": str(case.app / "Contents")}[how]
    result = run_helper(case, staged=staged)
    assert result.returncode == 2, failure_details(case, result)
    assert app_kind(case.app) == "old" and (case.app / "Contents" / "MacOS" / "YesonCheck_Autocut").exists()
    assert not case.backup.exists() and case.staged.exists()
    assert "잘못된 인자" in log_text(case)
    assert not trace_pids(case.trace, "old") and not trace_pids(case.trace, "new")


@darwin_only
def test_helper_cancelled_admin_swap_deletes_staged_without_second_prompt(update_case, tmp_path):
    # 바꾸기 암호 창을 취소한 사용자에게, 사용자로 지울 수 있는 준비한 새 앱 때문에 암호 창을 또 띄우지 않음
    case = update_case("new", apps_dir_name="응용 프로그램", staged_in_apps_dir=False)
    use_fake_admin(case, tmp_path, [case.apps_dir], refuse="mv ")
    lock(case.apps_dir)
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.staged.exists()
    assert len(admin_commands(case)) == 1, admin_commands(case)


@darwin_only
def test_helper_log_truncates_admin_output_joined_with_cr(update_case, tmp_path):
    # 진짜 osascript는 오류 여러 줄을 \r로 이어 한 줄로 냄 — 그래도 로그에는 앞 몇 줄만
    case = update_case("new")
    make_fake_app(case.backup, "old")
    resources = case.backup / "Contents" / "Resources"
    for i in range(30):
        (resources / f"f{i:02d}").write_text("x", encoding="utf-8")
    use_fake_admin(case, tmp_path, [])  # '관리자'도 못 지움
    lock(resources)
    result = run_helper(case)
    unlock_tree(tmp_path)
    assert result.returncode == 1, failure_details(case, result)  # 남은 백업을 못 지워 바꾸지 않음
    log = log_text(case)
    assert "\r" not in case.log.read_bytes().decode("utf-8")
    assert log.count("Permission denied") <= 10 and log.count("줄 더") == 2, log


# ---- open 방식 (실제 배포 경로: YC_UPDATE_DIRECT_LAUNCH 없이) — 가짜 open으로 ----

FAKE_OPEN = """#!/bin/sh
# open 흉내: open [-n] [-W] <앱> [--args 인자…] (--args 뒤는 앱의 인자). -W면 켠 앱이 끝날 때까지 기다렸다가 0으로 끝남
# (진짜 open -W와 같음 — 앱의 종료 코드와 상관없이 0). YC_TEST_OPEN_FAILS=<n>: 처음 n번은 진짜 open이 켜지 못할 때처럼
# 오류 글과 종료 코드 1
printf '%s\\n' "$*" >> "$YC_TEST_TRACE_DIR/open_calls"
wait_app=0
while :; do
    case "$1" in
        -W) wait_app=1 ;;
        -n) ;;
        -*) echo "가짜 open: 모르는 옵션 $1" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done
app=$1
shift
if [ $# -gt 0 ]; then
    if [ "$1" != "--args" ]; then
        echo "가짜 open: 앱 뒤에 --args가 아닌 인자 $1" >&2
        exit 2
    fi
    shift
fi
calls=$(wc -l < "$YC_TEST_TRACE_DIR/open_calls" | tr -d ' ')
if [ "$calls" -le "${YC_TEST_OPEN_FAILS:-0}" ]; then
    echo "LSOpenURLsWithRole() failed with error -10810 for the file $app." >&2
    exit 1
fi
if [ "$wait_app" = 1 ]; then
    printf '%s\\n' "$$" > "$YC_TEST_TRACE_DIR/open_w_pid"
    "$app/Contents/MacOS/YesonCheck_Autocut" "$@" </dev/null >/dev/null 2>&1
    exit 0
fi
"$app/Contents/MacOS/YesonCheck_Autocut" "$@" </dev/null >/dev/null 2>&1 &
exit 0
"""


def use_fake_open(case, tmp_path, fails=0):
    """직접 실행 대신 open 방식으로 — open 명령은 FAKE_OPEN (YC_UPDATE_OPEN)."""
    fake = tmp_path / "fake_open"
    fake.write_text(FAKE_OPEN, encoding="utf-8")
    fake.chmod(0o755)
    case.env.pop("YC_UPDATE_DIRECT_LAUNCH")
    case.env.update(YC_UPDATE_OPEN=str(fake), YC_TEST_OPEN_FAILS=str(fails))


def open_calls(case):
    path = case.trace / "open_calls"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def open_w_pid(case):
    path = case.trace / "open_w_pid"
    return int(path.read_text(encoding="utf-8")) if path.exists() else None


@darwin_only
def test_helper_open_mode_rolls_back_quickly_when_new_app_dies_at_once(update_case, tmp_path):
    # 실제 /Applications 시험: 새 앱이 몇 ms 만에 죽자 pgrep은 그것을 못 보고 180초를 다 기다림 → open -n -W가 끝나면 바로 실패
    case = update_case("exit_now")
    use_fake_open(case, tmp_path)
    started = time.monotonic()
    result = run_helper(case, timeout_s=30)
    elapsed = time.monotonic() - started
    assert result.returncode == 1, failure_details(case, result)
    assert elapsed < 10, f"{elapsed:.1f}초 — '잘 켜짐' 제한 시간(30초)을 기다림\n" + log_text(case)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    assert "표시 없이 끝남" in log_text(case) and "되돌림" in log_text(case)
    # 옛 앱은 그냥 open -n — 둘 다 결과 판정 토큰과 함께
    assert open_calls(case) == [f"-n -W {case.app} --args --update-result {TOKEN}",
                                f"-n {case.app} --args --update-result {TOKEN}"]
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


@darwin_only
def test_helper_open_mode_success_leaves_open_w_running(update_case, tmp_path):
    # 성공 뒤 새 앱이 도는 동안 open -W도 살아 있음 — 도우미는 그것을 기다리지 않고 끝나며, 끝날 때 그것을 끝내지도 않음
    case = update_case("new_stays")
    use_fake_open(case, tmp_path)
    result = run_helper(case, timeout_s=30)
    assert result.returncode == 0, failure_details(case, result)
    assert app_kind(case.app) == "new_stays" and not case.backup.exists()
    waiter = open_w_pid(case)
    assert waiter is not None and not pid_gone(waiter), log_text(case)
    assert not pid_gone(trace_pids(case.trace, "new")[0])
    assert open_calls(case) == [f"-n -W {case.app} --args --update-result {TOKEN}"]


@darwin_only
def test_helper_open_mode_launch_failure_rolls_back(update_case, tmp_path):
    case = update_case("new")
    use_fake_open(case, tmp_path, fails=1)  # 새 앱을 켜는 open만 실패, 옛 앱은 켜짐
    started = time.monotonic()
    result = run_helper(case, timeout_s=30)
    assert result.returncode == 1, failure_details(case, result)
    assert time.monotonic() - started < 10
    assert app_kind(case.app) == "old" and not case.backup.exists()
    assert "새 앱을 켜지 못함" in log_text(case) and "-10810" in log_text(case)
    assert not trace_pids(case.trace, "new")
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


@darwin_only
def test_helper_open_mode_rollback_ends_open_w_with_the_app(update_case, tmp_path):
    case = update_case("silent")
    use_fake_open(case, tmp_path)
    result = run_helper(case, timeout_s=3)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old"
    waiter = open_w_pid(case)
    assert waiter is not None and wait_until(lambda: pid_gone(waiter)), log_text(case)
    assert wait_until(lambda: pid_gone(trace_pids(case.trace, "new")[0])), log_text(case)
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


# ---- 여러 창: 모든 창이 끝난 뒤에만 바꿈, 되돌릴 때는 도우미가 켠 앱만 끝냄, 켜는 앱에 결과 판정 토큰 ----


@darwin_only
def test_waits_for_other_app_process_before_swap(update_case):
    """누른 창(--pid)이 끝나도 같은 앱 번들의 다른 프로세스(다른 창)가 돌면 바꾸지 않고 기다림 — 바꾸면 그 창이 다음 지연
    import에서 죽음(PyInstaller가 PYZ를 경로로 다시 엶). 그 창이 끝나면 바꿈."""
    case = update_case("new")
    other = start_other_window(case)
    helper = subprocess.Popen(helper_cmd(case, ended_pid(), 10), env=case.env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1.5)
        assert helper.poll() is None, "다른 창이 도는데 도우미가 끝남\n" + log_text(case)
        assert app_kind(case.app) == "old" and not case.backup.exists() and case.staged.exists(), log_text(case)
        assert f"다른 YesonCheck 창이 끝나기를 기다림 (pid {other.pid}(" in log_text(case), log_text(case)
        stop_other_window(case, other)
        out, err = helper.communicate(timeout=30)
    finally:
        if other.poll() is None:
            other.kill()
            other.wait()
        helper.kill()
    assert helper.returncode == 0, f"{out}\n{err}\n{log_text(case)}"
    assert app_kind(case.app) == "new" and not case.backup.exists()
    log = log_text(case)
    assert log.index("다른 YesonCheck 창이 모두 끝남") < log.index("옛 앱을 백업 이름으로 옮김"), log


@darwin_only
def test_does_not_swap_when_other_process_keeps_running(update_case):
    """다른 창이 YC_OTHERS_TIMEOUT초 안에 끝나지 않으면 바꾸지 않음(번들 그대로, 다른 창은 끝내지 않음) — 기록에 남기고 옛
    앱을 결과 판정 토큰과 함께 켬(옛 앱이 '업데이트 실패' 창으로 기록을 보임), 준비한 새 앱은 지움."""
    case = update_case("new")
    case.env["YC_OTHERS_TIMEOUT"] = "2"
    other = start_other_window(case)
    try:
        started = time.monotonic()
        result = run_helper(case)
        elapsed = time.monotonic() - started
        other_still_running = other.poll() is None
    finally:
        stop_other_window(case, other)
    assert result.returncode == 1, failure_details(case, result)
    assert elapsed >= 2, f"{elapsed:.1f}초 — YC_OTHERS_TIMEOUT(2초)을 기다리지 않음\n" + log_text(case)
    assert other_still_running, "다른 창을 끝냄\n" + log_text(case)
    assert app_kind(case.app) == "old" and not case.backup.exists() and not case.staged.exists()
    assert [p.name for p in case.apps_dir.iterdir()] == [case.app.name]
    log = log_text(case)
    assert f"다른 YesonCheck 창이 끝나지 않아 바꾸지 않음: pid {other.pid}(" in log, log
    assert "옛 앱을 백업 이름으로 옮김" not in log and "앱은 바뀌지 않았음" in log, log
    assert not trace_pids(case.trace, "new")
    assert wait_until(lambda: trace_args(case.trace, "old") == [f"--update-result {TOKEN}"]), (
        f"옛 앱 인자: {trace_args(case.trace, 'old')}\n{log_text(case)}")


FAKE_PGREP_FAILING_FOR_ALL_USERS = """#!/bin/sh
# 모든 사용자의 프로세스를 찾는 pgrep(-U 없이)만 실패 — 이 사용자의 것(-U)은 진짜 pgrep
case " $* " in
    *" -U "*) exec /usr/bin/pgrep "$@" ;;
esac
echo "pgrep: 시험 오류" >&2
exit 3
"""


@darwin_only
def test_does_not_swap_when_other_processes_cannot_be_listed(update_case, tmp_path):
    """다른 창을 찾는 pgrep이 실패하면 '다른 창 없음'으로 보지 않음 — 바꾸지 않고 기록, 옛 앱을 토큰과 함께 켬."""
    case = update_case("new")
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    (fake_bin / "pgrep").write_text(FAKE_PGREP_FAILING_FOR_ALL_USERS, encoding="utf-8")
    (fake_bin / "pgrep").chmod(0o755)
    case.env["PATH"] = f"{fake_bin}:{case.env['PATH']}"
    result = run_helper(case)
    assert result.returncode == 1, failure_details(case, result)
    assert app_kind(case.app) == "old" and not case.backup.exists() and not case.staged.exists()
    log = log_text(case)
    assert "pgrep 오류 (종료 코드 3" in log and "다른 YesonCheck 창이 있는지 확인하지 못해 바꾸지 않음" in log, log
    assert not trace_pids(case.trace, "new")
    assert wait_until(lambda: trace_args(case.trace, "old") == [f"--update-result {TOKEN}"]), log_text(case)


FAKE_PGREP_FAILING_FOR_THIS_USER = """#!/bin/sh
# 이 사용자의 프로세스를 찾는 pgrep(-U — 새 앱을 켜기 전부터 도는 프로세스 PIDS_BEFORE·새 앱 찾기)만 실패 — 바꾸기 전 모든
# 사용자의 것(-U 없이)은 진짜 pgrep
case " $* " in
    *" -U "*) echo "pgrep: 시험 오류" >&2; exit 3 ;;
esac
exec /usr/bin/pgrep "$@"
"""


@darwin_only
def test_does_not_launch_when_pids_before_cannot_be_listed(update_case, tmp_path):
    """새 앱을 켜기 직전에 도는 이 사용자의 앱 프로세스(PIDS_BEFORE)를 pgrep 오류로 알 수 없으면 새 앱을 켜지 않고 되돌림 —
    빈 목록으로 보면 켜기 전부터 돌던 창이 '새 앱'으로 보여 되돌릴 때 끝내질 수 있음. 켜기 전의 되돌리기(끝낼 새 앱 없음):
    백업을 제자리로, 옛 앱을 토큰과 함께 켬, 기록에 이유."""
    case = update_case("new")
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    (fake_bin / "pgrep").write_text(FAKE_PGREP_FAILING_FOR_THIS_USER, encoding="utf-8")
    (fake_bin / "pgrep").chmod(0o755)
    case.env["PATH"] = f"{fake_bin}:{case.env['PATH']}"
    result = run_helper(case)
    assert result.returncode == 1, failure_details(case, result)
    assert not trace_pids(case.trace, "new"), "새 앱을 켬\n" + log_text(case)
    assert app_kind(case.app) == "old" and not case.backup.exists() and not case.staged.exists(), log_text(case)
    log = log_text(case)
    assert "pgrep 오류 (종료 코드 3" in log, log
    assert "새 앱을 켜기 전부터 도는 YesonCheck 프로세스를 확인하지 못해 새 앱을 켜지 않음" in log, log
    assert "새 앱 프로세스를 끝냄" not in log and "새 앱 프로세스는 이미 끝나 있음" not in log, log
    assert wait_until(lambda: trace_args(case.trace, "old") == [f"--update-result {TOKEN}"]), log_text(case)


FAKE_MV_SPAWNING_OTHER_WINDOW = """#!/bin/sh
# 바꾸기의 두 번째 mv(준비한 새 앱 → 앱 자리) 바로 뒤에 사용자가 앱을 켠 것처럼, 앱 자리의 other_window를 띄움 — 도우미가
# 새 앱을 켜기 전부터 도는 같은 번들 프로세스. 출력은 막음 (도우미의 $(…)가 이 프로세스를 기다리지 않게)
/bin/mv "$@" || exit
if [ "$1" = "$YC_TEST_SPAWN_AFTER_MV_FROM" ]; then
    nohup /bin/sh "$2/Contents/MacOS/other_window" "$YC_TEST_TRACE_DIR/other_stop" >/dev/null 2>&1 </dev/null &
    printf '%s\\n' "$!" > "$YC_TEST_TRACE_DIR/other_pid"
fi
"""


@darwin_only
def test_rollback_kills_only_launched_pids(update_case, tmp_path):
    """되돌릴 때 도우미가 켠 새 앱만 끝냄 — 새 앱을 켜기 전부터 돌던 같은 번들 프로세스(바꾸는 사이에 사용자가 켠 창)는
    살아 있음 (앱 경로로 모두 pkill하지 않음)."""
    case = update_case("silent")
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    (fake_bin / "mv").write_text(FAKE_MV_SPAWNING_OTHER_WINDOW, encoding="utf-8")
    (fake_bin / "mv").chmod(0o755)
    case.env["PATH"] = f"{fake_bin}:{case.env['PATH']}"  # 도우미가 사용자로 부르는 mv
    case.env["YC_TEST_SPAWN_AFTER_MV_FROM"] = str(case.staged)
    result = run_helper(case, timeout_s=3)
    assert result.returncode == 1, failure_details(case, result)
    other_pid = int((case.trace / "other_pid").read_text(encoding="utf-8"))
    silent_pid = trace_pids(case.trace, "new")[0]
    assert not pid_gone(other_pid), "새 앱을 켜기 전부터 돌던 프로세스를 끝냄\n" + log_text(case)
    assert wait_until(lambda: pid_gone(silent_pid)), "표시 없는 새 앱이 끝나지 않음\n" + log_text(case)
    assert app_kind(case.app) == "old" and not case.backup.exists()
    log = log_text(case)
    assert f"새 앱 프로세스를 끝냄 (TERM): {silent_pid}" in log and str(other_pid) in log, log
    assert wait_until(lambda: trace_pids(case.trace, "old")), log_text(case)


@darwin_only
@pytest.mark.parametrize("mode", ["direct", "open"])
def test_launch_passes_update_result_token(update_case, tmp_path, mode):
    """도우미가 켜는 앱(새 앱, 되돌린 옛 앱)에는 모두 --update-result TOKEN — 그 앱만 지난 업데이트의 결과를 판정함
    (launch_args, update_install.startup_result). open 방식은 open -n [-W] APP --args …, 직접 실행도 같은 인자."""
    case = update_case("crash")  # 새 앱이 표시 없이 끝남 → 되돌려 옛 앱도 켬
    if mode == "open":
        use_fake_open(case, tmp_path)
    result = run_helper(case, timeout_s=30)
    assert result.returncode == 1, failure_details(case, result)
    assert trace_args(case.trace, "new") == [f"--update-result {TOKEN}"], log_text(case)
    assert wait_until(lambda: trace_args(case.trace, "old") == [f"--update-result {TOKEN}"]), (
        f"옛 앱 인자: {trace_args(case.trace, 'old')}\n{log_text(case)}")
    if mode == "open":
        assert open_calls(case) == [f"-n -W {case.app} --args --update-result {TOKEN}",
                                    f"-n {case.app} --args --update-result {TOKEN}"]


@darwin_only
@pytest.mark.parametrize("mode", ["direct", "open"])
def test_launch_without_token_passes_no_arguments(update_case, tmp_path, mode):
    """--token이 없으면(토큰을 모르는 옛 앱이 띄운 도우미) 인자 없이 켬 — 빈 --update-result는 앱이 거절함."""
    case = update_case("crash")
    if mode == "open":
        use_fake_open(case, tmp_path)
    result = run_helper(case, timeout_s=30, token=None)
    assert result.returncode == 1, failure_details(case, result)
    assert trace_args(case.trace, "new") == [""], log_text(case)
    assert wait_until(lambda: trace_args(case.trace, "old") == [""]), log_text(case)
    if mode == "open":
        assert open_calls(case) == [f"-n -W {case.app}", f"-n {case.app}"]


# ---- launch_helper_mac (모든 플랫폼) ----


class _RecordingPopen:
    calls = []

    def __init__(self, args, **kwargs):
        _RecordingPopen.calls.append((args, kwargs))


def test_launch_helper_mac_copies_script_and_passes_arguments(tmp_state_dir, monkeypatch):
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_mac("/Applications/.X.app.update-1.1.1", "/Applications/X.app", "1.1.1", TOKEN)
    copy = os.path.join(update_install.state_dir(), "update_helper_mac.sh")
    console = _RecordingPopen.calls[0][1].pop("stdout")  # 도우미 출력 파일 (아래에서 따로 확인)
    assert console.name == update_install.helper_console_path() and console.closed
    # _helper_env의 규칙 — Windows(이 시험은 모든 플랫폼에서 돎)에서는 PSModulePath를 뺌
    expected_env = {k: v for k, v in os.environ.items() if not (sys.platform == "win32" and k.upper() == "PSMODULEPATH")}
    assert _RecordingPopen.calls == [(
        [
            "/bin/bash", copy,
            "--pid", str(os.getpid()),
            "--app", "/Applications/X.app",
            "--staged", "/Applications/.X.app.update-1.1.1",
            "--target", "1.1.1",
            "--ok", update_install.ok_marker_path(),
            "--log", update_install.log_path(),
            "--token", TOKEN,
        ],
        {
            "start_new_session": True,
            "env": {**expected_env, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,  # stdout과 같은 파일로
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
    update_install.launch_helper_mac("/A/.X.app.update-1.1.1", "/A/X.app", "1.1.1", TOKEN)
    copy = Path(update_install.state_dir()) / "update_helper_mac.sh"
    assert copy.read_bytes() == b"# bundled copy\n"
    assert _RecordingPopen.calls[0][0][1] == str(copy)


def test_launch_helper_mac_resets_pyinstaller_environment_for_relaunched_app(tmp_state_dir, monkeypatch):
    """도우미가 다시 켜는 앱(직접 실행은 도우미의 환경을 물려받음)이 옛 앱의 하위 작업 프로세스로 켜지지 않게
    PYINSTALLER_RESET_ENVIRONMENT=1을 넘김 — 나머지 환경(시험이 정한 YC_UPDATE_* 등)은 그대로, 이 앱의 환경은 그대로."""
    monkeypatch.setenv("YC_UPDATE_DIRECT_LAUNCH", "1")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/A/X.app/Contents/MacOS/YesonCheck_Autocut")
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    _RecordingPopen.calls = []
    monkeypatch.setattr(update_install.subprocess, "Popen", _RecordingPopen)
    update_install.launch_helper_mac("/A/.X.app.update-1.1.1", "/A/X.app", "1.1.1", TOKEN)
    env = _RecordingPopen.calls[0][1]["env"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["YC_UPDATE_DIRECT_LAUNCH"] == "1" and env["_PYI_ARCHIVE_FILE"].endswith("YesonCheck_Autocut")
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in os.environ


def _read_or_none(path):
    return Path(path).read_text(encoding="utf-8", errors="replace") if os.path.exists(path) else "(없음)"


def _wait_real_helper(proc, timeout_s=30):
    """진짜로 띄운 도우미가 끝나기를 기다림 → (종료 코드, 기록, 도우미 출력)."""
    try:
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(30)
        raise AssertionError(f"도우미가 {timeout_s}초 안에 끝나지 않음\n기록:\n{_read_or_none(update_install.log_path())}\n"
                             f"도우미 출력:\n{_read_or_none(update_install.helper_console_path())}") from None
    return code, _read_or_none(update_install.log_path()), _read_or_none(update_install.helper_console_path())


real_launch = pytest.mark.skipif(sys.platform == "win32", reason="/bin/bash 도우미 (Mac)")


@real_launch
def test_real_launch_helper_mac_records_console_and_log(tmp_state_dir, tmp_path, monkeypatch):
    """진짜 launch_helper_mac (Popen 그대로): 도우미의 stdout·stderr가 helper_console_path에 남고(기록과 같은 줄 — 실패 창에는
    다시 보이지 않음), 기록도 씀. 일찍 끝나는 길: 이 시험 프로세스(살아 있음)가 끝나기를 0초만 기다림 → 바꾸지 않고 종료 1."""
    monkeypatch.setenv("YC_UPDATE_PID_TIMEOUT_S", "0")
    app = tmp_path / "Applications" / "X.app"
    update_install.log("업데이트 1.1.1: 업데이트 기록을 남김 (앱의 줄)")
    offset = update_install.log_size()
    proc = update_install.launch_helper_mac(str(tmp_path / "Applications" / ".X.app.update-1.1.1"), str(app), "1.1.1", TOKEN)
    code, text, console = _wait_real_helper(proc)
    details = f"종료 코드 {code}\n기록:\n{text}\n도우미 출력:\n{console}"
    assert code == 1 and " 도우미: 시작: 대상 버전 1.1.1" in text and "아무것도 바꾸지 않음" in text, details
    assert update_install.helper_start_logged(offset), details  # 앱이 끝나도 되는지 보는 줄 (player_update._hand_off)
    assert " 도우미: 시작: 대상 버전 1.1.1" in console, details  # Mac 도우미는 기록의 줄을 stdout에도 씀
    assert update_install.helper_console_extra() == "", details


@real_launch
def test_real_launch_helper_mac_records_early_failure(tmp_state_dir, tmp_path, monkeypatch):
    """도우미가 기록을 쓰기 전에 실패해도(bash 오류 등) 그 출력이 남고, 다시 켜진 앱의 실패 창이 그것을 보임."""
    broken = tmp_path / "broken_helper.sh"
    broken.write_text("echo yc-early-failure-marker >&2\nexit 3\n", encoding="utf-8")
    monkeypatch.setattr(update_install, "_bundled_file", lambda name: str(broken))
    proc = update_install.launch_helper_mac(str(tmp_path / ".X.app.update-1.1.1"), str(tmp_path / "X.app"), "1.1.1", TOKEN)
    code, text, console = _wait_real_helper(proc)
    assert code == 3 and console == "yc-early-failure-marker\n", (code, text, console)
    assert update_install.helper_console_extra() == "yc-early-failure-marker\n"
    assert not os.path.exists(update_install.log_path())


def test_launch_helper_mac_does_not_swallow_popen_failure(tmp_state_dir, monkeypatch):
    def failing_popen(args, **kwargs):
        raise OSError("bash를 실행하지 못함")

    monkeypatch.setattr(update_install.subprocess, "Popen", failing_popen)
    with pytest.raises(OSError, match="bash를 실행하지 못함"):
        update_install.launch_helper_mac("/A/.X.app.update-1.1.1", "/A/X.app", "1.1.1", TOKEN)


def test_helper_script_runs_under_bash_without_errexit():
    text = HELPER.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n")
    # set -e를 쓰면 중간 실패에서 그냥 끝나 되돌리기가 돌지 않음 — 실패마다 직접 처리해야 함
    assert re.search(r"^set -u$", text, re.M) and not re.search(r"^set -[a-z]*e", text, re.M)


def test_helper_kills_only_pids_and_waits_for_every_users_processes():
    # 앱 경로로 모두 끝내지(pkill) 않음 — 도우미가 켠 새 앱의 pid만. 새 앱 찾기(app_pids)는 이 사용자의 프로세스만, 바꾸기 전
    # 기다리기(all_app_pids)는 모든 사용자의 프로세스 (다른 사용자의 창도 바꾸면 죽음)
    lines = HELPER.read_text(encoding="utf-8").splitlines()
    calls = [line for line in lines if re.search(r"(^\s*|\$\()(pgrep|pkill) ", line)]  # 명령으로 부르는 줄 (주석·로그 글자 말고)
    assert not [line for line in calls if "pkill" in line], calls
    assert len(calls) == 2, calls
    assert len([line for line in calls if '-U "$MY_UID"' in line]) == 1, calls
