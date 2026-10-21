"""창 기록: 같은 사용자의 다른 YesonCheck 창(프로세스)을 세고 찾기 (Qt 없음).

한 프로세스에 창 하나. 창마다 사용자별 기록 폴더(registry_dir)에 `<pid>.json` 하나 — pid·앱 자리·프로세스 시작 시각·
창 사이 연결 서버 이름(instance_link). 업데이트하는 창은 이 기록으로 다른 창을 세고 상태를 묻고 닫기를 요청한다.

- 기록은 창을 보인 뒤 남기고(register), 창을 닫을 때(closeEvent 맨 먼저 — 닫히는 창은 세지 않게)와 프로세스가 끝날 때
  (atexit) 지운다(unregister). 강제 종료·충돌은 기록을 남기므로 others()가 지운다: pid가 없거나(끝남·좀비) 그 pid의
  프로세스 시작 시각이 기록과 다르면(pid를 다른 프로세스가 물려받음) 죽은 창.
- 앱 자리(current_app_path): 빌드 앱은 update_install.running_app_location()(Mac .app 번들·Windows 설치 폴더),
  소스 실행은 저장소 폴더. 다른 자리에서 켜진 앱은 세지 않는다(그 앱은 이 앱의 업데이트로 바뀌지 않음).
- other_user_processes: 같은 앱 자리의 실행 파일로 도는 다른 사용자의 프로세스 (Mac ps, Windows tasklist — Windows는
  다른 사용자 프로세스의 경로를 읽을 수 없어 실행 파일 이름으로만 찾음). 출력 읽기는 순수 함수(parse_*).

예상 못 한 오류(명령 실패·깨진 기록)는 그대로 올린다. 지금 열 수 없는 기록(PermissionError — Windows에서 지우는 중인
파일)만 others()가 그 번에 건너뛰고 기록에 남긴다.
"""

import atexit
import calendar
import csv
import io
import ntpath
import os
import posixpath
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass

from yesoncheck import paths, update_install, user_files

# 시험·실행 시험용: 이 환경 변수가 있으면 그 폴더에 기록 (자식 프로세스도 같은 폴더를 쓰게)
REGISTRY_DIR_ENV = "YESONCHECK_INSTANCES_DIR"

UNKNOWN_USER = "알 수 없는 사용자"  # Windows tasklist가 다른 사용자 프로세스의 이름을 읽지 못함(N/A)

_SAME_START_S = 1.0  # 같은 프로세스로 보는 시작 시각 차이 (Mac ps는 초 단위)
_COMMAND_TIMEOUT_S = 30
_REMOVE_RETRIES = 20  # Windows: 다른 창이 기록을 읽는 중이면 지우기가 PermissionError — 0.1초 간격으로 다시
_REMOVE_RETRY_INTERVAL_S = 0.1
_RECORD_NAME = re.compile(r"\d+\.json")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_registered_path = None  # 이 프로세스가 남긴 기록 파일
_atexit_hooked = False


@dataclass(frozen=True)
class InstanceRecord:
    pid: int
    app_path: str
    started: float  # 프로세스 시작 시각(epoch 초) — pid를 물려받은 다른 프로세스와 구분
    server_name: str  # instance_link 서버의 전체 이름 (Mac 소켓 파일 경로·Windows 파이프)


def registry_dir() -> str:
    """창 기록 폴더. Mac ~/Library/Caches/YesonCheck/instances, Windows %LOCALAPPDATA%\\YesonCheck\\instances.
    만들지는 않는다 (register가 쓸 때 만듦)."""
    override = os.environ.get(REGISTRY_DIR_ENV)
    if override:
        return override
    if paths.IS_WINDOWS:
        return os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", "instances")
    return os.path.join(os.path.expanduser("~"), "Library", "Caches", "YesonCheck", "instances")


def current_app_path() -> str:
    """이 프로세스의 앱 자리 — 빌드 앱은 update_install.running_app_location(), 소스 실행은 저장소 폴더."""
    if getattr(sys, "frozen", False):
        return update_install.running_app_location()
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _same_place(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# ---- 기록 ----


def register(app_path: str, server_name: str) -> InstanceRecord:
    """이 프로세스의 기록을 남김 (원자적 쓰기). 프로세스가 끝날 때 지우도록 atexit에 한 번 걸어 둠."""
    global _registered_path, _atexit_hooked
    pid = os.getpid()
    started = process_start_time(pid)
    if started is None:
        raise RuntimeError(f"이 프로세스(pid {pid})의 시작 시각을 읽지 못했습니다")
    record = InstanceRecord(pid, app_path, started, server_name)
    path = os.path.join(registry_dir(), f"{pid}.json")
    user_files.write_json_atomic(path, asdict(record))
    _registered_path = path
    if not _atexit_hooked:
        atexit.register(unregister)
        _atexit_hooked = True
    return record


def unregister() -> None:
    """이 프로세스의 기록을 지움. 남기지 않았거나 이미 지웠으면 아무것도 안 함."""
    global _registered_path
    path, _registered_path = _registered_path, None
    if path is None:
        return
    if not _remove(path):
        print(f"[창 기록] 이 창의 기록이 이미 없습니다: {path}", flush=True)


def _remove(path) -> bool:
    """기록 파일을 지움 → 지웠으면 True, 이미 없으면 False. Windows에서 다른 창이 읽는 중(PermissionError)이면 다시 시도."""
    retries_left = _REMOVE_RETRIES
    while True:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            if not paths.IS_WINDOWS or retries_left == 0:
                raise
            retries_left -= 1
            time.sleep(_REMOVE_RETRY_INTERVAL_S)


def _read_record(path):
    """기록 파일 → InstanceRecord, 읽는 사이에 지워졌으면 None. 형식이 틀리거나 읽지 못하면 UserFileError (경로 — 열 수
    없었으면 원인 PermissionError가 __cause__)."""
    data = user_files.read_json(path, None)
    if data is None:
        return None
    try:
        pid, app_path, started, server_name = data["pid"], data["app_path"], data["started"], data["server_name"]
    except (TypeError, KeyError) as exc:
        raise user_files.UserFileError(f"창 기록의 형식이 잘못되었습니다: {path}\n{data!r}") from exc
    if not (isinstance(pid, int) and not isinstance(pid, bool) and isinstance(app_path, str)
            and isinstance(started, (int, float)) and not isinstance(started, bool) and isinstance(server_name, str)):
        raise user_files.UserFileError(f"창 기록의 형식이 잘못되었습니다: {path}\n{data!r}")
    return InstanceRecord(pid, app_path, float(started), server_name)


def is_running(record: InstanceRecord) -> bool:
    """기록의 프로세스가 아직 도는지 — pid가 살아 있고 시작 시각이 같음 (pid를 물려받은 다른 프로세스가 아님)."""
    started = process_start_time(record.pid)
    return started is not None and abs(started - record.started) < _SAME_START_S


def others(app_path: str) -> list[InstanceRecord]:
    """같은 앱 자리에서 도는 이 사용자의 다른 창 기록 (자기 제외). 죽은 창의 기록은 지운다(다른 자리의 앱 것도).

    지금 열 수 없는 기록(PermissionError — Windows에서 닫히는 창이 지운 파일을 백신·색인이 잡고 있으면 '지우기 대기'로
    남음)은 이번에는 건너뛰고 기록(print)에 남긴다 — 다음에 부를 때 다시 읽음(업데이트는 0.5초마다 다시 셈). 깨진 기록(JSON·
    형식)과 그 밖의 읽기 오류는 그대로 올린다.
    """
    folder = registry_dir()
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return []
    found = []
    for name in names:
        if not _RECORD_NAME.fullmatch(name):
            continue  # 쓰는 중인 임시 파일(.tmp-…) 등
        path = os.path.join(folder, name)
        try:
            record = _read_record(path)
        except user_files.UserFileError as exc:
            if not isinstance(exc.__cause__, PermissionError):
                raise
            print(f"[창 기록] 기록을 지금 열 수 없어 이번에는 건너뜀 (지우는 중일 수 있음): {path} — "
                  f"{type(exc.__cause__).__name__}: {exc.__cause__}", flush=True)
            continue
        if record is None or record.pid == os.getpid():
            continue
        if not is_running(record):
            _remove(path)  # 다른 창이 먼저 지웠어도 괜찮음
            print(f"[창 기록] 끝난 창의 기록을 지움: pid {record.pid}", flush=True)
            continue
        if _same_place(record.app_path, app_path):
            found.append(record)
    return found


# ---- 프로세스 시작 시각 ----


def process_start_time(pid: int) -> float | None:
    """pid 프로세스의 시작 시각(epoch 초). 그런 프로세스가 없거나 끝났으면(좀비 포함) None.

    Mac은 ps -o stat=,lstart=(초 단위), Windows는 GetProcessTimes. Windows에서 열 수 없는 프로세스(ERROR_ACCESS_DENIED —
    다른 사용자·시스템 프로세스)도 None: 이 사용자의 창일 수 없음.
    """
    if sys.platform == "win32":
        return _windows_process_start_time(pid)
    result = subprocess.run(
        ["/bin/ps", "-o", "stat=,lstart=", "-p", str(pid)],
        capture_output=True, text=True, env=_start_time_env(), timeout=_COMMAND_TIMEOUT_S,
    )
    if result.returncode == 1 and not result.stdout.strip():
        return None  # 그런 pid가 없음
    if result.returncode != 0:
        raise RuntimeError(f"ps가 실패했습니다 (pid {pid}, 종료 코드 {result.returncode}): {result.stderr.strip()}")
    return parse_ps_start(result.stdout)


def _start_time_env():
    """ps 시작 시각을 읽을 수 있게: 영어 날짜(LC_ALL=C — 한국어 로캘이면 '수 10/21 …'), UTC(TZ=UTC0 — 창마다
    시간대가 달라도 같은 값)."""
    return dict(os.environ, LC_ALL="C", TZ="UTC0")


def parse_ps_start(text: str) -> float | None:
    """`ps -o stat=,lstart=`(LC_ALL=C, TZ=UTC0) 한 줄 → 시작 시각(epoch 초), 좀비(Z)면 None. 형식이 다르면 ValueError."""
    parts = text.split()
    if len(parts) != 6 or parts[2] not in _MONTHS:
        raise ValueError(f"ps 시작 시각을 읽지 못했습니다: {text!r}")
    stat, _weekday, month, day, clock, year = parts
    if "Z" in stat:
        return None
    hour, minute, second = (int(v) for v in clock.split(":"))
    return float(calendar.timegm((int(year), _MONTHS.index(month) + 1, int(day), hour, minute, second)))


_kernel32 = None


def _windows_kernel32():
    """argtypes를 정한 kernel32 (전역 ctypes.windll을 바꾸지 않게 따로 불러옴)."""
    global _kernel32
    if _kernel32 is None:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetExitCodeProcess.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.GetProcessTimes.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87  # 그런 pid가 없음
_STILL_ACTIVE = 259
_FILETIME_UNIX_EPOCH = 116444736000000000  # 1601-01-01부터 1970-01-01까지 (100ns 단위)


def _windows_process_start_time(pid):
    import ctypes
    from ctypes import wintypes

    k = _windows_kernel32()
    handle = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in (_ERROR_INVALID_PARAMETER, _ERROR_ACCESS_DENIED):
            return None
        raise ctypes.WinError(error)
    try:
        # 끝났지만 누가 핸들을 쥐고 있어 남은 프로세스 객체도 열림 → 끝난 것으로
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != _STILL_ACTIVE:
            return None
        creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited), ctypes.byref(kernel),
                                 ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return (ticks - _FILETIME_UNIX_EPOCH) / 10_000_000
    finally:
        k.CloseHandle(handle)


# ---- 다른 사용자의 같은 앱 ----


def other_user_processes(app_path: str) -> list[tuple[int, str]]:
    """같은 앱 자리의 실행 파일로 도는 다른 사용자의 프로세스 [(pid, 사용자 이름)] — 소스 실행이면 [].

    Mac: app_path/Contents/MacOS/<이 앱의 실행 파일>을 ps로. Windows: 다른 사용자 프로세스의 경로는 읽을 수 없어
    이 앱의 실행 파일 이름(YesonCheck.exe)으로 tasklist — 이름을 읽지 못하면 "알 수 없는 사용자".
    """
    if not getattr(sys, "frozen", False):
        return []
    if paths.IS_WINDOWS:
        exe_name = ntpath.basename(sys.executable)
        return parse_tasklist_csv(_run_tasklist(exe_name), exe_name, _windows_me())
    exe_path = posixpath.join(app_path, "Contents", "MacOS", posixpath.basename(sys.executable))
    return parse_ps_output(_run_ps(), exe_path, _mac_me())


def _mac_me():
    return os.getuid()


def _windows_me():
    """tasklist가 보이는 이 사용자 이름 (도메인\\사용자)."""
    return f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"


def _run_ps():
    """모든 프로세스의 `pid uid 사용자 실행 파일` (줄을 자르지 않음). UTF-8 로캘로: C 로캘의 ps는 한글 등 ASCII가 아닌
    글자를 M-l…로 바꿔 보여 한글이 든 앱 자리의 실행 파일을 찾지 못함. UTF-8이 아닌 바이트는 그대로(surrogateescape)."""
    result = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,uid=,user=,comm="], capture_output=True,
                            encoding="utf-8", errors="surrogateescape",
                            env=dict(os.environ, LC_ALL="en_US.UTF-8"), timeout=_COMMAND_TIMEOUT_S)
    if result.returncode != 0:
        raise RuntimeError(f"ps가 실패했습니다 (종료 코드 {result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _run_tasklist(exe_name):
    """exe_name으로 도는 프로세스의 tasklist /V CSV. 출력은 콘솔 코드 페이지 — UTF-8이 아니면 OEM 코드 페이지로 읽음."""
    tasklist = os.path.join(os.environ["SystemRoot"], "System32", "tasklist.exe")
    result = subprocess.run([tasklist, "/V", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {exe_name}"],
                            capture_output=True, timeout=_COMMAND_TIMEOUT_S,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"tasklist가 실패했습니다 (종료 코드 {result.returncode}): {result.stderr!r}")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return result.stdout.decode("oem")


def parse_ps_output(text: str, exe_path: str, me: int) -> list[tuple[int, str]]:
    """`ps -axww -o pid=,uid=,user=,comm=` 출력에서 exe_path로 도는, uid가 me가 아닌 프로세스 [(pid, 사용자 이름)].

    실행 파일 경로에는 공백이 있을 수 있음(줄의 나머지 전부) — 경로는 NFC로 맞춰 비교(Finder가 만든 한글 폴더는 NFD일 수
    있음). pid·uid가 숫자가 아니면 ValueError (형식이 바뀜).
    """
    exe_key = _path_key(exe_path)
    found = []
    for line in text.splitlines():
        fields = line.split(None, 3)
        if not fields:
            continue
        try:
            pid, uid = int(fields[0]), int(fields[1])
        except (ValueError, IndexError) as exc:
            raise ValueError(f"ps 출력을 읽지 못했습니다: {line!r}") from exc
        if len(fields) < 4 or uid == me:
            continue
        if _path_key(fields[3]) == exe_key:
            found.append((pid, fields[2]))
    return found


def _path_key(path):
    return unicodedata.normalize("NFC", posixpath.normpath(path))


def parse_tasklist_csv(text: str, exe_name: str, me: str) -> list[tuple[int, str]]:
    """`tasklist /V /FO CSV /NH` 출력에서 exe_name(대소문자 무시)으로 도는, 사용자가 me(도메인\\사용자, 대소문자
    무시)가 아닌 프로세스 [(pid, 사용자 이름)] — 이름을 읽지 못한 N/A는 "알 수 없는 사용자".

    따옴표로 시작하지 않는 줄은 tasklist의 안내(찾는 프로세스가 없음 — 언어마다 다름)라 건너뜀. CSV 줄의 칸 수가
    다르면 ValueError (형식이 바뀜).
    """
    me_key = me.casefold()
    found = []
    for line in text.splitlines():
        if not line.strip() or not line.lstrip().startswith('"'):
            continue
        row = next(csv.reader(io.StringIO(line)))
        if len(row) != 9:
            raise ValueError(f"tasklist 출력을 읽지 못했습니다 (칸 {len(row)}개): {line!r}")
        image, pid_text, user = row[0], row[1], row[6]
        if image.casefold() != exe_name.casefold():
            continue
        user_key = user.casefold()
        if user_key == me_key or ("\\" not in user and user_key == me_key.rpartition("\\")[2]):
            continue
        found.append((int(pid_text), UNKNOWN_USER if user == "N/A" else user))
    return found
