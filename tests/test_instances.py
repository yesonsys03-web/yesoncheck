"""창 기록(instances): 같은 사용자의 다른 YesonCheck 창(프로세스)을 셈 — 죽은 창·pid를 물려받은 다른 프로세스는 세지 않고
그 기록을 지움(Review Focus 3), 같은 앱 자리에서 도는 다른 사용자의 프로세스 찾기(ps·tasklist 출력 읽기).

기록 폴더는 conftest가 시험마다 임시 폴더로 돌림 (진짜 기록 폴더를 건드리지 않음).
"""

import json
import os
import subprocess
import sys
import time

import pytest

from tests.conftest import ROOT
from yesoncheck import instances, paths
from yesoncheck.instances import InstanceRecord
from yesoncheck.user_files import UserFileError


def _record_path(pid):
    return os.path.join(instances.registry_dir(), f"{pid}.json")


def _write_record(pid, app_path, started, server_name="yesoncheck-test"):
    """다른 창이 남긴 것 같은 기록 파일."""
    os.makedirs(instances.registry_dir(), exist_ok=True)
    path = _record_path(pid)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "app_path": app_path, "started": started, "server_name": server_name}, fh)
    return path


def _sleeping_child():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


# ---- 기록 폴더·앱 자리 ----


def test_registry_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv(instances.REGISTRY_DIR_ENV)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows의 expanduser
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert instances.registry_dir() == os.path.join(str(tmp_path), "Library", "Caches", "YesonCheck", "instances")
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    assert instances.registry_dir() == os.path.join(str(tmp_path / "local"), "YesonCheck", "instances")
    # 시험·실행 시험용: 환경 변수가 있으면 그 폴더
    monkeypatch.setenv(instances.REGISTRY_DIR_ENV, str(tmp_path / "t"))
    assert instances.registry_dir() == str(tmp_path / "t")


def test_current_app_path_source_run_is_repo(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert instances.current_app_path() == ROOT


def test_current_app_path_frozen_is_running_app_location(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.setattr(sys, "executable", "/Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut")
    assert instances.current_app_path() == "/Applications/YesonCheck.app"


# ---- 등록·다른 창 세기 ----


def test_register_and_list_others(monkeypatch, tmp_path):
    app = str(tmp_path / "YesonCheck.app")
    me = os.getpid()
    # 가짜 pid 둘(살아 있는 다른 창) + 다른 자리의 앱 하나 — 프로세스 시작 시각은 표로
    times = {me: 1000.0, 41001: 2000.5, 41002: 3000.0, 41003: 4000.0}
    monkeypatch.setattr(instances, "process_start_time", times.get)

    record = instances.register(app, "yesoncheck-me")
    assert record == InstanceRecord(me, app, 1000.0, "yesoncheck-me")
    with open(_record_path(me), encoding="utf-8") as fh:
        assert json.load(fh) == {"pid": me, "app_path": app, "started": 1000.0, "server_name": "yesoncheck-me"}

    _write_record(41001, app, 2000.5, "s1")
    _write_record(41002, app + os.sep, 3000.0, "s2")  # 같은 자리 (끝의 구분자만 다름)
    elsewhere = _write_record(41003, str(tmp_path / "Other.app"), 4000.0, "s3")

    found = sorted(instances.others(app), key=lambda r: r.pid)  # 자기는 빼고
    assert found == [InstanceRecord(41001, app, 2000.5, "s1"), InstanceRecord(41002, app + os.sep, 3000.0, "s2")]
    assert os.path.exists(elsewhere)  # 다른 자리의 앱은 세지 않지만 살아 있으니 지우지 않음
    assert instances.others(str(tmp_path / "Other.app")) == [
        InstanceRecord(41003, str(tmp_path / "Other.app"), 4000.0, "s3")]

    instances.unregister()
    assert not os.path.exists(_record_path(me))
    instances.unregister()  # 두 번 불러도(closeEvent·프로세스 끝) 괜찮음


def test_others_when_no_window_registered_yet():
    assert not os.path.exists(instances.registry_dir())
    assert instances.others(ROOT) == []
    instances.unregister()  # 등록하지 않았으면 아무것도 안 함


def test_dead_pid_record_removed(tmp_path):
    app = str(tmp_path / "YesonCheck.app")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # 끝난 창 (기록을 지우지 못하고 죽음)
    assert instances.process_start_time(proc.pid) is None
    path = _write_record(proc.pid, app, 1234.0)
    assert instances.others(app) == []
    assert not os.path.exists(path)


def test_reused_pid_with_other_start_time_ignored(tmp_path):
    """죽은 창의 pid를 다른 프로세스가 물려받음: 그 pid는 살아 있지만 시작 시각이 달라 다른 창으로 세지 않고 기록을 지움."""
    app = str(tmp_path / "YesonCheck.app")
    child = _sleeping_child()
    try:
        started = instances.process_start_time(child.pid)
        assert started is not None
        assert instances.is_running(InstanceRecord(child.pid, app, started, "live"))
        assert not instances.is_running(InstanceRecord(child.pid, app, started - 3600, "old"))
        stale = _write_record(child.pid, app, started - 3600, "old")
        assert instances.others(app) == []
        assert not os.path.exists(stale)
        # 시작 시각이 맞으면 살아 있는 다른 창
        live = _write_record(child.pid, app, started, "live")
        assert instances.others(app) == [InstanceRecord(child.pid, app, started, "live")]
        assert os.path.exists(live)
    finally:
        child.kill()
        child.wait()


def test_process_start_time_is_launch_time():
    before = time.time()
    child = _sleeping_child()
    after = time.time()
    try:
        started = instances.process_start_time(child.pid)
        # Mac은 초 단위(ps lstart) — 시간대가 틀리면 몇 시간씩 어긋남
        assert before - 2 <= started <= after + 2
        assert instances.process_start_time(child.pid) == started  # 다시 물어도 같음
        own = instances.process_start_time(os.getpid())
        assert own is not None and own <= time.time()
    finally:
        child.kill()
        child.wait()


def test_parse_ps_start():
    # ps -o stat=,lstart= (LC_ALL=C, TZ=UTC0): 상태 + 시작 시각(UTC). 좀비(끝났지만 거둬들이지 않음)는 끝난 것
    assert instances.parse_ps_start("Ss   Wed Oct 21 03:27:21 2026\n") == 1792553241.0
    assert instances.parse_ps_start("S+   Thu Oct  1 00:00:05 2026") == 1790812805.0
    assert instances.parse_ps_start("Z    Wed Oct 21 03:27:21 2026") is None
    with pytest.raises(ValueError):
        instances.parse_ps_start("Ss   수 10/21 12:27:21 2026")  # 다른 언어의 날짜(LC_ALL=C를 넘기지 못함)


def test_record_removed_at_exit_and_left_by_crash_is_cleaned(tmp_path):
    """정상 종료(atexit)는 기록을 지우고, 강제 종료(os._exit — 남은 작업을 기다리다 끝냄·충돌)가 남긴 기록은 다른 창이 지움."""
    app = str(tmp_path / "YesonCheck.app")
    script = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from yesoncheck import instances\n"
        "instances.register(sys.argv[2], 'yesoncheck-child')\n"
        "print(os.getpid(), flush=True)\n"
        "if sys.argv[3] == 'crash':\n"
        "    os._exit(0)\n"
    )
    for how in ("exit", "crash"):
        result = subprocess.run([sys.executable, "-c", script, ROOT, app, how], capture_output=True, text=True,
                                timeout=60)
        assert result.returncode == 0, result.stderr
        pid = int(result.stdout.split()[0])
        if how == "exit":
            assert not os.path.exists(_record_path(pid))
        else:
            assert os.path.exists(_record_path(pid))
            assert instances.others(app) == []
            assert not os.path.exists(_record_path(pid))


def test_broken_record_raises_with_path(tmp_path):
    os.makedirs(instances.registry_dir())
    path = _record_path(41005)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"pid": "41005", "app_path": ROOT}, fh)
    with pytest.raises(UserFileError, match="41005.json"):
        instances.others(ROOT)
    assert os.path.exists(path)  # 깨진 기록은 지우지 않고 알림


def test_malformed_json_record_raises_with_path():
    os.makedirs(instances.registry_dir())
    path = _record_path(41006)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"pid": 41006, "app_path": ')  # 잘린 JSON
    with pytest.raises(UserFileError, match="41006.json"):
        instances.others(ROOT)
    assert os.path.exists(path)


def test_record_that_cannot_be_opened_now_is_skipped_this_pass(monkeypatch, capsys):
    """Windows: 닫히는 창이 지운 기록이 '지우기 대기'(백신·색인이 잡고 있음)로 남으면 열 때 PermissionError — 그 기록은 이번에는
    건너뛰고(기록에 남김) 다른 창은 그대로 셈. 업데이트가 '업데이트 실패'로 끝나지 않게 (다음 확인에서 다시 읽음)."""
    from yesoncheck import user_files

    child = _sleeping_child()
    try:
        started = instances.process_start_time(child.pid)
        live = _write_record(child.pid, ROOT, started, "live")
        held = _write_record(41007, ROOT, 1234.0, "held")
        real_open = open

        def open_held_denied(path, *args, **kwargs):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(held)):
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(user_files, "open", open_held_denied, raising=False)  # read_json이 부르는 open
        assert instances.others(ROOT) == [InstanceRecord(child.pid, ROOT, started, "live")]
        assert os.path.exists(held) and os.path.exists(live)  # 지우지 않음
        out = capsys.readouterr().out
        assert "41007.json" in out and "PermissionError" in out and "이번에는 건너뜀" in out, out
    finally:
        child.kill()
        child.wait()


# ---- 다른 사용자의 같은 앱 ----

MAC_EXE = "/Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut"

# ps -axww -o pid=,uid=,user=,comm= (LC_ALL=C)
PS_SAMPLE = """\
  101   501 studio01         /Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut
  202   502 studio02         /Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut
  303   503 _longusername_x  /Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut
  404   502 studio02         /Users/studio02/Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut
  505   502 studio02         /Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut_old
  606     0 root             /usr/libexec/logd
  707   202 _coreaudiod      Core Audio Driver (BlackHole2ch.driver)
  808   502 studio02         /Applications/Yeson Check.app/Contents/MacOS/YesonCheck_Autocut
"""


def test_parse_ps_output_other_users():
    # 나(uid 501)는 빼고, 같은 실행 파일만 (다른 자리·이름이 비슷한 파일은 아님)
    assert instances.parse_ps_output(PS_SAMPLE, MAC_EXE, 501) == [(202, "studio02"), (303, "_longusername_x")]
    # 앱 이름에 공백
    spaced = "/Applications/Yeson Check.app/Contents/MacOS/YesonCheck_Autocut"
    assert instances.parse_ps_output(PS_SAMPLE, spaced, 501) == [(808, "studio02")]
    assert instances.parse_ps_output("", MAC_EXE, 501) == []
    with pytest.raises(ValueError, match="ps"):
        instances.parse_ps_output("pid uid user comm\n", MAC_EXE, 501)  # 형식이 바뀌면 숨기지 않음


def test_parse_ps_output_non_ascii_path_any_normalization():
    """한글이 든 앱 자리: ps가 보인 경로(NFD로 만든 폴더일 수 있음)와 이 앱의 경로(NFC)는 정규화해 비교."""
    import unicodedata

    exe = "/Users/studio02/예손 앱/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut"
    text = f"  909   502 studio02  {unicodedata.normalize('NFD', exe)}\n"
    assert instances.parse_ps_output(text, unicodedata.normalize("NFC", exe), 501) == [(909, "studio02")]
    assert instances.parse_ps_output(text, unicodedata.normalize("NFD", exe), 501) == [(909, "studio02")]


@pytest.mark.skipif(sys.platform == "win32", reason="Mac ps")
def test_real_ps_shows_non_ascii_executable_path(tmp_path):
    """C 로캘의 ps는 한글을 M-l…로 바꿔 보여 같은 실행 파일을 찾지 못함 → 프로세스 목록은 UTF-8 로캘로 읽음."""
    import shutil

    macos = tmp_path / "예손 앱" / "YesonCheck.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = str(macos / "YesonCheck_Autocut")
    shutil.copyfile("/bin/sleep", exe)  # copy2는 시스템 파일 표시(restricted)까지 옮겨 실행이 막힘
    os.chmod(exe, 0o755)
    child = subprocess.Popen([exe, "60"])
    try:
        text = instances._run_ps()
        assert [pid for pid, _user in instances.parse_ps_output(text, exe, -1)] == [child.pid], text[-3000:]
    finally:
        child.kill()
        child.wait()


# tasklist /V /FO CSV /NH /FI "IMAGENAME eq YesonCheck.exe" — 이름을 읽지 못한 다른 사용자의 프로세스는 N/A
TASKLIST_SAMPLE = (
    '"YesonCheck.exe","1100","Console","1","210,512 K","Running","STUDIO01\\studio01","0:00:12","YesonCheck"\r\n'
    '"YesonCheck.exe","2200","RDP-Tcp#3","2","198,004 K","Running","STUDIO01\\studio02","0:00:40","YesonCheck"\r\n'
    '"YesonCheck.exe","3300","Services","0","150,000 K","Unknown","N/A","0:00:01","N/A"\r\n'
    '"yesoncheck.EXE","4400","Console","1","1,000 K","Running","studio01\\STUDIO01","0:00:00","N/A"\r\n'
    '"python.exe","5500","Console","1","1,000 K","Running","STUDIO01\\studio02","0:00:00","N/A"\r\n'
    '"YesonCheck.exe","6600","Console","1","1,000 K","Running","STUDIO01\\studio01","0:00:00","제목, ""따옴표"""\r\n'
)


def test_parse_tasklist_csv_na_user():
    me = "STUDIO01\\studio01"
    assert instances.parse_tasklist_csv(TASKLIST_SAMPLE, "YesonCheck.exe", me) == [
        (2200, "STUDIO01\\studio02"), (3300, "알 수 없는 사용자")]
    # 찾는 프로세스가 없을 때 tasklist가 쓰는 안내(언어마다 다름) → 없음
    assert instances.parse_tasklist_csv(
        "INFO: No tasks are running which match the specified criteria.\r\n", "YesonCheck.exe", me) == []
    assert instances.parse_tasklist_csv("정보: 지정된 조건에 맞는 작업이 없습니다.\r\n", "YesonCheck.exe", me) == []
    with pytest.raises(ValueError, match="tasklist"):
        instances.parse_tasklist_csv('"YesonCheck.exe","1100","Console"\r\n', "YesonCheck.exe", me)


def test_other_user_processes_source_run_is_empty(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(instances, "_run_ps", lambda: pytest.fail("소스 실행에서는 프로세스를 찾지 않음"))
    monkeypatch.setattr(instances, "_run_tasklist", lambda exe_name: pytest.fail("소스 실행에서는 프로세스를 찾지 않음"))
    assert instances.other_user_processes(ROOT) == []


def test_other_user_processes_mac_uses_bundle_executable(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Somewhere/Else.app/Contents/MacOS/YesonCheck_Autocut")
    monkeypatch.setattr(instances, "_mac_me", lambda: 501)
    monkeypatch.setattr(instances, "_run_ps", lambda: PS_SAMPLE)
    # 실행 파일 이름은 이 앱의 것, 자리는 받은 app_path
    assert instances.other_user_processes("/Applications/YesonCheck.app") == [(202, "studio02"),
                                                                              (303, "_longusername_x")]


def test_other_user_processes_windows_uses_exe_name(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Users\\studio01\\AppData\\Local\\Programs\\YesonCheck\\YesonCheck.exe")
    monkeypatch.setenv("USERDOMAIN", "STUDIO01")
    monkeypatch.setenv("USERNAME", "studio01")
    asked = []
    monkeypatch.setattr(instances, "_run_tasklist", lambda exe_name: asked.append(exe_name) or TASKLIST_SAMPLE)
    found = instances.other_user_processes("C:\\Users\\studio01\\AppData\\Local\\Programs\\YesonCheck")
    assert asked == ["YesonCheck.exe"]
    assert found == [(2200, "STUDIO01\\studio02"), (3300, "알 수 없는 사용자")]


@pytest.mark.skipif(sys.platform == "win32", reason="Mac ps (Windows는 tasklist 시험)")
def test_real_ps_output_parses_own_process():
    text = instances._run_ps()
    own = [line.split(None, 3) for line in text.splitlines() if line.split()[:1] == [str(os.getpid())]]
    assert len(own) == 1, text[:2000]
    _pid, uid, user, comm = own[0]
    assert int(uid) == os.getuid()
    assert os.getpid() not in [pid for pid, _user in instances.parse_ps_output(text, comm, os.getuid())]
    # 다른 사용자인 셈 치면 보임 (실제 ps 출력의 형식 확인)
    assert (os.getpid(), user) in instances.parse_ps_output(text, comm, -1)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows tasklist (Mac은 ps 시험)")
def test_real_tasklist_output_parses_own_process():
    exe_name = os.path.basename(sys._base_executable)  # venv의 python.exe가 띄운 실제 인터프리터
    text = instances._run_tasklist(exe_name)
    assert f'"{os.getpid()}"' in text, text[:2000]
    assert os.getpid() not in [pid for pid, _user in instances.parse_tasklist_csv(text, exe_name, instances._windows_me())]
    # 다른 사용자인 셈 치면 보임 — 사용자 이름을 읽어 옴 (실제 출력의 형식·인코딩 확인)
    others = dict(instances.parse_tasklist_csv(text, exe_name, "NOBODY\\nobody"))
    assert others[os.getpid()].casefold() == instances._windows_me().casefold()
