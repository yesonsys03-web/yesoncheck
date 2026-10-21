"""업데이트 설치 준비: 받기(다운로드+sha256 검사)·Mac dmg 준비(hdiutil+ditto)·업데이트 기록 (Qt 없음).

이 모듈은 파일·프로세스 작업만 한다 — 창을 띄우는 일, 로그 메시지를 어떻게 보여 줄지, 백그라운드 스레드로
옮기는 일은 부른 쪽(player_base 등)이 한다. NAS 경로는 그냥 복사(1 MB 단위), URL은 requests로 스트리밍
받는다. 받은 뒤 크기·sha256을 확인하고, 틀리거나 취소되면 받던 파일(.part)을 지운다. 예상 못 한 예외는
삼키지 않고 그대로 올린다.

Mac에서는 dmg를 hdiutil로 열고 안의 .app 하나를 ditto로(심볼릭 링크가 많아 shutil 대신) 앱 옆의 숨김 이름으로
복사한 뒤 항상 떼어내고, 복사한 앱의 버전을 build_info로 확인한다. 업데이트를 건 뒤 기록
(state_dir()/pending_update.json — 무작위 토큰·도우미 pid·건 창의 pid 포함)을 남겨 두면, 도우미가 그 토큰과 함께
다시 켠 앱(`--update-result TOKEN`)만 현재 버전과 비교해 성공(ok)·실패(failed)를 판정해 지운다(startup_result) — 업데이트
중에 사용자가 켠 다른 앱은 기록을 건드리지 않고(update_in_progress로 알아채고 켜지지 않음, app.launch) 진짜 새 앱이 '잘
켜짐'을 쓴다. 토큰 없는 옛 기록(1.1.x 앱이 씀 — 1.1.x 도우미는 토큰 없이 켬)은 예전 규칙 그대로 판정한다. 이 기록·로그
(update.log)는 재시작 뒤 앱과, 종료를 기다리다 새 앱을 켜는 도우미(다른 프로세스)와 다른 창들이 함께 쓴다 — log()는
매번 열고 닫고(핸들을 오래 들고 있으면 Windows에서 도우미가 로그 파일에 쓰지 못함), 줄마다 쓴 프로세스의 pid를 붙인다
(log_tail_since가 그 업데이트의 줄만 고르게).

requests는 URL에서 받을 때(_copy_from_url) 불러온다 — 앱의 시작이 requests를 기다리지 않게 (updates와 같음).
"""

import contextlib
import dataclasses
import datetime
import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from yesoncheck import build_info, paths, user_files
from yesoncheck.updates import FileEntry

PENDING_FILE_NAME = "pending_update.json"
OK_MARKER_FILE_NAME = "update_ok.json"
LOG_FILE_NAME = "update.log"
APP_EXECUTABLE_NAME = "YesonCheck_Autocut"
HELPER_MAC_FILE_NAME = "update_helper_mac.sh"  # Mac 도우미 (빌드된 앱에는 spec이 yesoncheck/ 아래에 넣음)
HELPER_WINDOWS_FILE_NAME = "update_helper_windows.ps1"  # Windows 도우미 (빌드된 앱에는 spec이 yesoncheck/ 아래에 넣음)
HELPER_CONSOLE_FILE_NAME = "update_helper_console.txt"  # 도우미의 stdout·stderr (state_dir 안, 띄울 때마다 새로)
# 두 도우미(update_helper_mac.sh·update_helper_windows.ps1)가 인자를 확인한 뒤 맨 처음 쓰는 기록 줄의 시각 뒤 글
# ("<시각> 도우미: 시작: 대상 버전 …") — 앱은 이 줄을 본 뒤에만 끝난다 (helper_start_logged)
HELPER_START_TEXT = " 도우미: 시작: "
# 도우미가 쓰는 기록 줄의 시각 뒤 글 ("<시각> 도우미: …" — pid 없음). 앱의 줄은 "<시각> [pid N] …" (log)
HELPER_LINE_TEXT = " 도우미:"
# 도우미 pid가 업데이트 기록을 쓴 때(Pending.started)부터 이 초 안에 시작한 프로세스일 때만 그 도우미로 봄 (_helper_alive
# — pid는 끝난 뒤 다른 프로세스가 물려받음, Windows는 특히 빨리). 앱은 기록을 쓰고 1초 안팎에 도우미를 띄우고 그 pid를 더해
# 다시 씀 — 도우미 pid가 아직 없는 기록도 이 초 동안은 업데이트 중으로 봄 (_hand_off가 다시 쓰기 전)
HELPER_START_WINDOW_S = 60
# 도우미가 가장 오래 도는 시간보다 넉넉히: 앱이 끝나기 기다림 300초 + (Windows) 설치 파일 기다림 1800초 + '잘 켜짐' 기다림
# 180초 + 되돌리기. 기록이 이보다 오래되었으면 그 도우미는 더는 앱을 다시 켜지 않음 — 업데이트 중이 아님(pid를 물려받은
# 오래 도는 프로세스 때문에 앱이 계속 켜지지 않는 일이 없게)
HELPER_MAX_LIFETIME_S = 45 * 60

# Windows 도우미를 띄우는 플래그: 창 없는 자기 콘솔(CREATE_NO_WINDOW — 창 모드 앱에는 콘솔이 없음), 새 프로세스 그룹.
# 프로세스는 부모가 끝나도 남으므로 앱이 끝난 뒤에도 돈다. DETACHED_PROCESS는 쓰지 않음: 콘솔이 아예 없으면 Windows
# PowerShell 5.1(ConsoleHost)이 스크립트를 시작하지 못하고 아무 출력 없이 끝난다(CI에서 봄; 그 플래그와 함께면
# CREATE_NO_WINDOW는 무시됨 — Win32 문서). Mac의 subprocess에는 이 상수들이 없으므로 Win32 문서의 값으로 대신한다 —
# 모듈을 Mac에서도 불러오고 launch_helper_windows 시험을 모든 플랫폼에서 돌리려고
_WINDOWS_HELPER_CREATIONFLAGS = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
)

NEEDED_BYTES = {"windows": 1_500_000_000, "mac-x86_64": 3_000_000_000, "mac-arm64": 3_000_000_000}

_CHUNK_BYTES = 1024 * 1024  # NAS 복사·sha256 계산·requests 스트리밍 모두 1 MB 단위
_DOWNLOAD_TIMEOUT_S = 10  # 연결·읽기 각각
_LOG_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")  # log()가 줄 앞에 붙이는 시각
_PID_TEXT_RE = re.compile(r"[0-9]+")  # 업데이트 기록의 helper_pid·app_pid


class UpdateError(Exception):
    """예상할 수 있는 업데이트 오류 (메시지에 한국어로 무엇이 왜 잘못됐는지)."""


class Cancelled(Exception):
    """사용자가 업데이트(다운로드)를 취소함."""


# ---- 상태·로그 폴더 ----


def state_dir() -> str:
    """업데이트가 쓰는 폴더 (받은 파일·기록·ok 표시). Windows %LOCALAPPDATA%\\YesonCheck\\updates,
    Mac ~/Library/Caches/YesonCheck/updates. 없으면 만든다."""
    if paths.IS_WINDOWS:
        d = os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", "updates")
    else:
        d = os.path.join(os.path.expanduser("~"), "Library", "Caches", "YesonCheck", "updates")
    os.makedirs(d, exist_ok=True)
    return d


def log_path() -> str:
    """업데이트 로그 파일. Windows %LOCALAPPDATA%\\YesonCheck\\logs\\update.log,
    Mac ~/Library/Logs/YesonCheck/update.log. 폴더가 없으면 만든다."""
    if paths.IS_WINDOWS:
        d = os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", "logs")
    else:
        d = os.path.join(os.path.expanduser("~"), "Library", "Logs", "YesonCheck")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, LOG_FILE_NAME)


def timestamp() -> str:
    """지금 시각을 log()가 줄 앞에 쓰는 형식 그대로: ISO 8601, 초 단위, 시간대 없음.

    Task 6의 Pending.started도 이 형식으로 적어야 log_tail_since의 글자 비교(사전식 = 시간 순서)가
    맞는다.
    """
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(line: str) -> None:
    """시각(timestamp())과 이 프로세스의 pid를 붙여("<시각> [pid N] 줄") log_path()에 한 줄 덧붙이고 stdout에도 보임.

    매번 열고 닫는다(긴 시간 핸들을 들고 있지 않음) — 업데이트 뒤 다시 켜는 도우미(별도 프로세스)가
    Windows에서 같은 파일에 덧붙여 쓸 수 있어야 하기 때문. pid는 여러 창이 함께 쓰는 기록에서 그 업데이트의 줄만 고르려고
    (log_tail_since).
    """
    stamped = f"{timestamp()} [pid {os.getpid()}] {line}"
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write(stamped + "\n")
    print(stamped)


def log_size() -> int:
    """업데이트 기록(log_path())의 지금 크기 (bytes, 없으면 0) — helper_start_logged에 넘길 '여기부터'."""
    try:
        return os.path.getsize(log_path())
    except FileNotFoundError:
        return 0


def helper_start_logged(offset: int) -> bool:
    """업데이트 기록의 offset바이트 뒤에 도우미의 시작 줄(HELPER_START_TEXT — 두 도우미가 맨 처음 쓰는 줄)이 있는지.

    앱은 도우미를 띄우기 바로 전의 log_size()를 offset으로 넘겨, 지난 도우미의 줄이 아닌 이번 도우미의 줄만 본다. 기록이
    없으면 False. 바이트로 찾음 — 도우미가 쓰는 중인 마지막 줄이 반쪽이어도 읽기가 실패하지 않게. 읽기 오류는 그대로 올림."""
    try:
        with open(log_path(), "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except FileNotFoundError:
        return False
    return HELPER_START_TEXT.encode("utf-8") in data


def log_tail_since(started: str, pid: int | str | None, max_lines: int = 80) -> str:
    """로그에서 시각이 started 이상이고 pid 프로세스(그 업데이트를 건 창 — Pending.app_pid)나 도우미가 쓴 줄만, 최근
    max_lines줄까지. 다른 창이 그사이 쓴 줄은 뺀다. pid가 None이면(옛 기록 — 1.1.x 앱의 줄에는 pid가 없음) 쓴 곳을 가리지
    않음. 로그 파일이 없으면 빈 글자.

    log()가 쓴 줄은 "<ISO 시각> [pid N] …", 도우미의 줄은 "<ISO 시각> 도우미: …"로 시작하지만, 트레이스백처럼 그 뒤에 시각
    없이 여러 줄이 이어지는 경우가 있다(실패 로그를 통째로 보여 줘야 함 — "업데이트 실패" 창의 자료). 시각으로 시작하는
    줄만 포함 여부를 다시 정하고, 시각이 없는 줄(들여쓴 트레이스백 줄 등)은 바로 앞의 시각 있는 줄과 같은 여부를 따른다.
    started는 초 단위까지만 비교한다(앞 19자리 "YYYY-MM-DDTHH:MM:SS") — 더 긴(마이크로초·시간대) 값이 들어와도 같은 초의
    줄을 빼먹지 않게.
    """
    try:
        with open(log_path(), encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return ""
    cutoff = started[:19]
    own = None if pid is None else f" [pid {pid}] "
    matched = []
    include = False
    for line in lines:
        if _LOG_TIMESTAMP_RE.match(line):
            rest = line[19:]
            include = line[:19] >= cutoff and (
                own is None or rest.startswith(own) or rest.startswith(HELPER_LINE_TEXT))
        if include:
            matched.append(line)
    return "".join(matched[-max_lines:])


# ---- 빈 공간 ----


def check_free_space(directory: str, needed: int) -> None:
    """directory가 있는 디스크의 남은 공간이 needed(bytes)보다 적으면 UpdateError (여유 공간 모자람)."""
    free = shutil.disk_usage(directory).free
    if free < needed:
        raise UpdateError(
            f"여유 공간이 모자랍니다: {directory} (필요 {needed:,} bytes, 남음 {free:,} bytes)"
        )


# ---- 받기 ----


def _is_url(location):
    return location.startswith("http://") or location.startswith("https://")


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_not_exceeding(downloaded, total, part_path):
    """받은 바이트가 entry.size를 넘으면 바로 멈춤 (끝까지 받은 뒤 _verify_download에서 걸릴 때까지
    기다리지 않음 — 소스가 기대보다 훨씬 크면 디스크·시간을 낭비하지 않게)."""
    if downloaded > total:
        raise UpdateError(
            f"받은 바이트가 기대보다 많습니다 (기대 {total:,} bytes, 지금까지 {downloaded:,} bytes): {part_path}"
        )


def _copy_from_nas(location, entry, part_path, progress, cancelled):
    """NAS(로컬 디스크로 보이는 공유) 경로를 1 MB 단위로 복사."""
    total = entry.size
    downloaded = 0
    with open(location, "rb") as src, open(part_path, "wb") as dst:
        while True:
            if cancelled():
                raise Cancelled("다운로드가 취소되었습니다")
            chunk = src.read(_CHUNK_BYTES)
            if not chunk:
                break
            dst.write(chunk)
            downloaded += len(chunk)
            _check_not_exceeding(downloaded, total, part_path)
            progress(downloaded, total)


def _copy_from_url(location, entry, part_path, progress, cancelled):
    """requests 스트리밍으로 받기 (연결·읽기 제한 각 10초)."""
    import requests  # 처음 쓸 때 (모듈 설명)

    total = entry.size
    downloaded = 0
    timeout = (_DOWNLOAD_TIMEOUT_S, _DOWNLOAD_TIMEOUT_S)
    with requests.get(location, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(part_path, "wb") as dst:
            for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                if cancelled():
                    raise Cancelled("다운로드가 취소되었습니다")
                if not chunk:
                    continue
                dst.write(chunk)
                downloaded += len(chunk)
                _check_not_exceeding(downloaded, total, part_path)
                progress(downloaded, total)


def _verify_download(part_path, entry):
    actual_size = os.path.getsize(part_path)
    if actual_size != entry.size:
        raise UpdateError(
            f"받은 파일의 크기가 다릅니다 (기대 {entry.size:,} bytes, 실제 {actual_size:,} bytes): {part_path}"
        )
    actual_sha256 = _sha256_of(part_path)
    if actual_sha256 != entry.sha256:
        raise UpdateError(
            f"받은 파일의 sha256이 다릅니다 (기대 {entry.sha256}, 실제 {actual_sha256}): {part_path}"
        )


def _remove_part(part_path):
    try:
        os.remove(part_path)
    except FileNotFoundError:
        pass


def download(
    location: str,
    entry: FileEntry,
    dest_dir: str,
    progress: Callable[[int, int], None],
    cancelled: Callable[[], bool],
) -> str:
    """entry를 location(NAS 경로 또는 URL)에서 dest_dir로 받음. "<name>.part"로 받다가 크기·sha256이
    맞으면 "<name>"으로 이름을 바꾸고 그 경로를 돌려준다.

    받는 동안 chunk마다 progress(받은 바이트, 전체 바이트)를 부르고 cancelled()를 본다. 취소되면
    Cancelled, 크기·sha256이 다르면 UpdateError(기대·실제 값을 메시지에) — 두 경우 모두 .part를 지운다.
    그 밖의 예상 못 한 예외도 .part를 지운 뒤 그대로 다시 올린다(삼키지 않음).
    """
    os.makedirs(dest_dir, exist_ok=True)
    part_path = os.path.join(dest_dir, entry.name + ".part")
    final_path = os.path.join(dest_dir, entry.name)
    try:
        if _is_url(location):
            _copy_from_url(location, entry, part_path, progress, cancelled)
        else:
            _copy_from_nas(location, entry, part_path, progress, cancelled)
        _verify_download(part_path, entry)
        os.replace(part_path, final_path)  # 검사까지 통과한 뒤에만 이름을 바꿈
    except Exception:
        _remove_part(part_path)  # 취소·크기·sha256 불일치·이름 바꾸기 실패 등 모든 실패에서 .part를 지움
        raise
    return final_path


# ---- 이 앱이 어디서 도는지 (Mac/Windows) ----


def running_app_location() -> str:
    """지금 실행 중인 앱의 위치. Mac은 .app 번들 경로, Windows는 설치 폴더. 소스 실행이면 UpdateError."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("소스 실행에서는 업데이트를 설치할 수 없습니다 (빌드된 앱에서만 가능)")
    if paths.IS_WINDOWS:
        return os.path.dirname(sys.executable)
    # Mac: sys.executable = <X>.app/Contents/MacOS/YesonCheck_Autocut → 번들은 3단계 위
    return os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))


def refuse_reason_mac(app_path: str) -> str | None:
    """app_path가 업데이트를 설치할 수 없는 위치면 사용자에게 보여 줄 한국어 안내, 아니면 None.

    AppTranslocation(격리 위치에서 실행 — 처음 열 때 응용 프로그램 폴더로 옮기지 않은 경우)과 /Volumes/
    아래(dmg를 마운트한 채로 그 안에서 바로 연 경우) 모두, 고치는 방법은 같다: 앱을 끄고 응용 프로그램
    (Applications) 폴더로 옮긴 뒤 거기서 다시 연다.
    """
    if "/AppTranslocation/" in app_path:
        return (
            "이 앱이 임시 격리 위치에서 실행되고 있어 업데이트를 설치할 수 없습니다. "
            "앱을 완전히 끄고 응용 프로그램 폴더(Applications)로 옮긴 뒤 거기서 다시 열어 주세요."
        )
    if app_path.startswith("/Volumes/"):
        return (
            "이 앱이 설치 디스크 이미지(dmg) 안에서 바로 실행되고 있어 업데이트를 설치할 수 없습니다. "
            "먼저 앱을 응용 프로그램 폴더(Applications)로 끌어다 놓은 뒤, 거기서 다시 열어 주세요."
        )
    return None


_WINDOWS_UNINSTALLER_RE = re.compile(r"unins\d{3}\.exe", re.IGNORECASE)  # Inno 설치 파일이 남기는 제거 프로그램


def _same_or_inside(path, folder):
    """path가 folder와 같거나 그 안인지 (Windows는 대소문자 무시, 링크·짧은 이름을 푼 뒤)."""
    path = os.path.normcase(os.path.realpath(path))
    folder = os.path.normcase(os.path.realpath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def refuse_reason_windows(install_dir: str) -> str | None:
    """install_dir(Windows 설치 폴더)를 업데이트할 수 없으면 사용자에게 보여 줄 한국어 안내, 아니면 None.

    - 업데이트 상태 폴더(state_dir — 도우미 스크립트·받은 설치 파일)나 기록 폴더가 설치 폴더 안: 도우미가 그 안에서 돌고 기록을
      쓰므로 설치 폴더의 이름을 바꿀 수 없음 (예: %LOCALAPPDATA%\\YesonCheck에 설치) — 도우미는 '다른 YesonCheck 창'으로 잘못
      알렸을 것. 설치 파일로 다른 폴더에 다시 설치해야 함.
    - 설치 파일로 설치한 앱이 아님 (제거 프로그램 unins000.exe가 없음 — 빌드 결과를 풀어 놓은 폴더 등): 설치 파일이 그 폴더를
      설치된 곳으로 등록해 제거 항목·바로 가기를 바꿔 버림.
    state_dir·log_path가 폴더를 만들다 난 오류는 그대로 올림.
    """
    for what, folder in (("업데이트 파일을 두는 폴더", state_dir()), ("업데이트 기록 폴더", os.path.dirname(log_path()))):
        if _same_or_inside(folder, install_dir):
            return (
                f"{what}({folder})가 이 앱의 설치 폴더({install_dir}) 안에 있어 업데이트할 수 없습니다 — 업데이트하는 동안 "
                "설치 폴더의 이름을 바꿔야 하기 때문입니다. 설치 파일(YesonCheck_Setup_….exe)로 다른 폴더(기본 C:\\YesonCheck)에 "
                "다시 설치한 뒤 그 앱을 쓰세요."
            )
    try:
        names = os.listdir(install_dir)
    except OSError as exc:
        raise UpdateError(f"설치 폴더를 읽지 못했습니다: {install_dir}\n{type(exc).__name__}: {exc}") from exc
    if not any(_WINDOWS_UNINSTALLER_RE.fullmatch(name) for name in names):
        return (
            f"이 앱은 설치 파일로 설치한 것이 아니어서(설치 폴더에 제거 프로그램 unins000.exe가 없음: {install_dir}) 업데이트할 수 "
            "없습니다 — 업데이트하면 이 폴더가 설치된 곳으로 등록되어 제거 항목·바로 가기가 바뀝니다. 설치 파일"
            "(YesonCheck_Setup_….exe)로 설치한 앱에서 업데이트하세요."
        )
    return None


# ---- Mac: dmg에서 새 앱 준비 ----


def _stage_dest_path(app_path, target_version):
    """새 앱을 준비해 둘 경로: <app 폴더>/.<app 이름>.update-<버전> — 그 폴더에 못 쓰면 state_dir() 아래."""
    app_name = os.path.basename(app_path)
    parent = os.path.dirname(app_path)
    hidden_name = f".{app_name}.update-{target_version}"
    base_dir = parent if os.access(parent, os.W_OK) else state_dir()
    return os.path.join(base_dir, hidden_name)


def _hdiutil_attach(dmg_path, mount_point):
    try:
        subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount_point, dmg_path],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise UpdateError(f"업데이트 디스크 이미지(dmg)를 열지 못했습니다: {dmg_path}\n{exc.stderr}") from exc


def _hdiutil_detach(mount_point):
    result = subprocess.run(["hdiutil", "detach", mount_point], capture_output=True, text=True)
    if result.returncode != 0:
        raise UpdateError(f"업데이트 디스크 이미지(dmg)를 분리하지 못했습니다: {mount_point}\n{result.stderr}")


def _copy_app_from_mount(mount_point, dest_path):
    apps = [name for name in os.listdir(mount_point) if name.endswith(".app")]
    if len(apps) != 1:
        raise UpdateError(
            f"업데이트 디스크 이미지 안에 .app이 정확히 하나가 아닙니다 ({len(apps)}개 찾음): {mount_point}"
        )
    source_app = os.path.join(mount_point, apps[0])
    if os.path.lexists(dest_path):  # 지난번에 남은 것 먼저 지움
        if os.path.isdir(dest_path) and not os.path.islink(dest_path):
            shutil.rmtree(dest_path)
        else:
            os.remove(dest_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        subprocess.run(["ditto", source_app, dest_path], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise UpdateError(f"새 앱을 복사하지 못했습니다 (ditto): {exc.stderr}") from exc


def _verify_staged_app(dest_path, target_version):
    try:
        exe_path = os.path.join(dest_path, "Contents", "MacOS", APP_EXECUTABLE_NAME)
        if not os.path.isfile(exe_path):
            raise UpdateError(f"준비한 앱에 실행 파일이 없습니다: {exe_path}")
        try:
            info = build_info.load(os.path.join(dest_path, "Contents", "Resources"))
        except RuntimeError as exc:
            raise UpdateError(str(exc)) from exc
        if info.version != target_version:
            raise UpdateError(
                f"준비한 앱의 버전이 다릅니다 (기대 {target_version}, 실제 {info.version}): {dest_path}"
            )
    except Exception as exc:
        # 준비한 폴더를 지운다 — 지우다 실패한 것이 있으면 삼키지 않고 원래 오류 메시지에 덧붙인다
        cleanup_errors = []

        def _on_rmtree_error(func, path, exc_info):
            cleanup_errors.append(f"{func.__name__}({path}): {exc_info[1]}")

        shutil.rmtree(dest_path, onerror=_on_rmtree_error)
        if cleanup_errors:
            raise UpdateError(
                f"{exc}\n(게다가 준비했던 폴더를 지우지 못함: {'; '.join(cleanup_errors)})"
            ) from exc
        raise


def stage_mac(dmg_path: str, app_path: str, target_version: str) -> str:
    """dmg를 열어 안의 .app을 app_path 옆(또는 못 쓰면 state_dir() 아래) 숨김 이름으로 준비하고 그 경로를 돌려줌.

    항상 dmg를 떼어낸다(성공·실패 모두). 떼어내지 못하면 그대로 UpdateError(마운트된 이미지를 남겨 두지
    않음) — 아직 마운트된 상태일 수 있으니 임시 마운트 폴더는 떼어내기가 성공했을 때만 지운다(실패를
    삼키지 않음 — rmdir 실패도 그대로 올림). 복사가 실패한 데다 떼어내기도 실패하면(흔치 않지만) 둘
    다 사용자에게 보여야 하므로 두 오류 글을 모두 담은 UpdateError 하나로 올린다(복사 오류만 있으면
    복사 오류, 떼어내기 오류만 있으면 떼어내기 오류 — 하나만 있을 때는 그대로). 복사한 앱의
    build_info.json 버전이 target_version과 다르면(또는 실행 파일이 없으면) 준비한 폴더를 지우고
    UpdateError.
    """
    mount_point = tempfile.mkdtemp(prefix="yesoncheck_update_mount_")
    dest_path = _stage_dest_path(app_path, target_version)
    try:
        _hdiutil_attach(dmg_path, mount_point)
    except Exception:
        os.rmdir(mount_point)  # 마운트가 안 됐으니(비어 있음) 바로 지움
        raise

    copy_error = None
    try:
        _copy_app_from_mount(mount_point, dest_path)
    except Exception as exc:
        copy_error = exc
    try:
        _hdiutil_detach(mount_point)  # 복사 성공·실패 모두 항상 떼어냄
    except Exception as detach_exc:
        if copy_error is not None:
            # 둘 다 실패 — 어느 쪽도 가리지 않고 둘 다 사용자에게 보임 (마운트는 못 지웠으니 그대로 둠)
            raise UpdateError(
                f"{copy_error}\n(게다가 업데이트 디스크 이미지도 떼어내지 못함: {detach_exc})"
            ) from detach_exc
        raise  # 떼어내기만 실패 — 그대로 올림(마운트된 채 남기지 않음을 알리는 오류)
    os.rmdir(mount_point)  # 떼어내기가 성공한 뒤에만 — 비어 있어야 하고, 실패해도 그대로 올림(삼키지 않음)
    if copy_error is not None:
        raise copy_error
    _verify_staged_app(dest_path, target_version)
    return dest_path


# ---- 앱이 끝난 뒤 바꾸고 다시 켜는 도우미 (Mac·Windows) ----


def _bundled_file(name: str) -> str:
    """yesoncheck 패키지 옆에 둔 데이터 파일의 경로: 빌드된 앱은 sys._MEIPASS/yesoncheck/(spec datas),
    소스 실행은 저장소의 yesoncheck/ — 둘 다 "<맨 위>/yesoncheck/<name>"."""
    top = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(top, "yesoncheck", name)


def _copy_helper_to_state_dir(name: str) -> str:
    """번들 안의 도우미 스크립트 name을 state_dir()/name으로 복사하고 그 경로를 돌려줌.

    도우미는 바뀔 앱(Mac 번들·Windows 설치 폴더) 밖에서 돌아야 하므로 복사본을 실행한다. 임시 파일 + os.replace —
    돌고 있는 이전 도우미의 파일을 그 자리에서 덮어쓰지 않음(bash는 스크립트를 조금씩 읽음).
    """
    dest = os.path.join(state_dir(), name)
    fd, tmp_path = tempfile.mkstemp(dir=state_dir(), prefix=".tmp-")
    os.close(fd)
    try:
        shutil.copyfile(_bundled_file(name), tmp_path)
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return dest


PYINSTALLER_RESET_ENV = "PYINSTALLER_RESET_ENVIRONMENT"


def _helper_env() -> dict:
    """도우미에 넘길 환경 변수: 이 앱의 것 그대로 + PYINSTALLER_RESET_ENVIRONMENT=1, Windows는 PSModulePath를 뺌.

    도우미가 다시 켜는 앱(새 버전 또는 되돌린 옛 버전)은 도우미의 환경을 물려받는다 — Windows는 언제나, Mac은 직접
    실행(YC_UPDATE_DIRECT_LAUNCH=1, 시험)일 때. 빌드된 앱(PyInstaller 6.14)의 부트로더는 _PYI_ARCHIVE_FILE·
    _PYI_PARENT_PROCESS_LEVEL을 환경에 남기고, 같은 자리의 실행 파일이 그 환경을 물려받으면 자기를 이 앱의 하위 작업
    프로세스로 본다(6.9부터). 이 변수가 1이면 부트로더가 그 환경을 지우고 새로 시작한 앱으로 켠다(그리고 변수를 지워
    그 앱의 자식에게는 넘기지 않음) — PyInstaller 문서 "Using sys.executable to spawn subprocesses that outlive the
    application process".

    PSModulePath (Windows): 앱을 PowerShell 7(pwsh)에서 켰으면(CI의 단계, pwsh 터미널) PS7의 모듈 폴더가 앞에 든 값을
    물려받는다. 도우미는 Windows PowerShell 5.1 — 빼서 5.1이 자기 기본 모듈 경로를 만들게 함(탐색기에서 켠 앱과 같은
    상태, 도우미 시험도 같게 함). 안전장치: CI의 같은 러너에서 5.1이 그 값을 가진 채 New-Object를 실행했음
    (path_map_setup.resolve_shortcuts) — 도우미가 출력 없이 끝나던 원인은 DETACHED_PROCESS(_WINDOWS_HELPER_CREATIONFLAGS).
    이 앱의 os.environ은 바꾸지 않음."""
    env = {**os.environ, PYINSTALLER_RESET_ENV: "1"}
    if paths.IS_WINDOWS:
        for key in [k for k in env if k.upper() == "PSMODULEPATH"]:  # Windows의 os.environ 키는 대문자
            del env[key]
    return env


def helper_console_path() -> str:
    """도우미의 stdout·stderr를 받는 파일 (state_dir()/update_helper_console.txt)."""
    return os.path.join(state_dir(), HELPER_CONSOLE_FILE_NAME)


def _decode_console(data: bytes) -> tuple[str, str | None]:
    """도우미 출력의 바이트 → (글, UTF-8이 아니어서 대신 쓴 인코딩 또는 None). bash는 UTF-8, Windows PowerShell 5.1은
    파일로 보낸 출력을 이 컴퓨터의 코드 페이지로 씀 — UTF-8로 읽히지 않으면 그 인코딩으로 (어떻게 읽었는지 함께 돌려줌)."""
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        return data.decode(encoding, errors="replace"), encoding


def helper_console_extra() -> str:
    """도우미 출력(helper_console_path) 중 업데이트 기록(log_path)에 없는 줄 — 도우미가 기록을 쓰기 전에 실패한 이유
    (PowerShell·bash가 스크립트를 시작하지 못함, 기록 파일을 쓰지 못함 등)가 여기에만 남는다. Mac 도우미는 기록의 줄을
    stdout에도 쓰므로 그 줄은 뺌 (Windows 도우미는 기록 파일이 있으면 stdout에 쓰지 않음). 파일이 없거나 남는 줄이 없으면 빈 글자. 읽기 오류는 그대로 올림."""
    try:
        with open(helper_console_path(), "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return ""
    text, encoding = _decode_console(data)
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as fh:
            logged = {line.rstrip("\r\n") for line in fh}
    except FileNotFoundError:
        logged = set()
    extra = [line.rstrip("\r") for line in text.split("\n") if line.strip() and line.rstrip("\r") not in logged]
    if not extra:
        return ""
    note = f"(UTF-8이 아니어서 {encoding}로 읽음)\n" if encoding else ""
    return note + "\n".join(extra) + "\n"


def _kernel32():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel32.SetDllDirectoryW.restype = ctypes.c_int
    return kernel32


def _last_windows_error() -> int:
    import ctypes

    return ctypes.get_last_error()


def _set_dll_directory(path: str | None) -> None:
    if not _kernel32().SetDllDirectoryW(path):
        raise OSError(f"SetDllDirectoryW({path!r})가 실패했습니다 (Windows 오류 {_last_windows_error()})")


@contextlib.contextmanager
def _default_dll_search_for_children():
    """(Windows 빌드 앱) 이 안에서 띄우는 프로세스가 앱의 DLL 찾는 곳을 물려받지 않게, 그동안만 기본으로 되돌림.

    PyInstaller 부트로더는 SetDllDirectoryW(<설치 폴더>\\_internal)로 앱의 DLL 찾는 곳을 바꾸고 자식 프로세스가 이것을
    물려받는다(PyInstaller 문서 "Launching External Programs from the Frozen Application"). 도우미(powershell.exe)가
    물려받으면 거기 들어온 DLL(백신 등이 넣은 DLL이 찾는 VC++ 런타임 등)을 설치 폴더의 _internal에서 불러와 잡고 있을 수
    있고, 그러면 도우미가 설치 폴더의 이름을 바꾸지 못한다. 띄운 뒤에는 _internal로 되돌림 (넘기지 못하면 앱은 계속 돎).
    소스 실행·Mac은 아무것도 하지 않음. 실패는 그대로 올림."""
    frozen_dir = getattr(sys, "_MEIPASS", None)
    if not (paths.IS_WINDOWS and frozen_dir):
        yield
        return
    _set_dll_directory(None)
    try:
        yield
    finally:
        _set_dll_directory(frozen_dir)


def launch_helper_mac(staged_app: str, app_path: str, target: str, token: str) -> subprocess.Popen:
    """앱이 끝나기를 기다렸다가 staged_app을 app_path 자리로 바꾸고 다시 켜는 도우미(update_helper_mac.sh)를 띄움.
    token: 업데이트 기록(Pending.token)의 토큰 — 도우미가 다시 켜는 앱에 `--update-result TOKEN`으로 넘김(그 앱만 결과를 판정).

    부른 쪽은 업데이트 기록(write_pending)을 남긴 뒤 이것을 부르고 앱을 끝낸다. 도우미는 바뀔 앱 번들 밖에서
    돌아야 하므로(번들째 백업 이름으로 옮기고, 되돌릴 때는 지움) 번들 안의 스크립트를 state_dir()로 복사해
    실행한다(_copy_helper_to_state_dir). 새 세션(start_new_session)으로 띄워 앱이 끝나도 같이 끝나지 않게 한다.
    환경은 _helper_env (다시 켜는 앱이 새로 시작한 앱이 되게). stdout·stderr는 helper_console_path(띄울 때마다 새로) —
    도우미가 기록을 쓰기 전에 실패해도 그 출력이 남음. 띄운 Popen을 돌려줌 — 앱은 도우미가 시작 기록(HELPER_START_TEXT)을
    남길 때까지 이것으로 도우미가 살아 있는지 보고, 그 뒤에 끝난다(player_update._hand_off). Popen 실패는 그대로 올린다.
    """
    dest = _copy_helper_to_state_dir(HELPER_MAC_FILE_NAME)
    args = [
        "/bin/bash", dest,
        "--pid", str(os.getpid()),
        "--app", app_path,
        "--staged", staged_app,
        "--target", target,
        "--ok", ok_marker_path(),
        "--log", log_path(),
        "--token", token,
    ]
    with open(helper_console_path(), "wb") as console:
        return subprocess.Popen(
            args,
            start_new_session=True,
            env=_helper_env(),
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
        )


def _windows_powershell() -> str:
    """Windows PowerShell 5.1 실행 파일 — path_map_setup._powershell과 같은 방식(System32 아래, 없으면 PATH의 powershell)."""
    exe = os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    return exe if os.path.isfile(exe) else "powershell"


def launch_helper_windows(installer: str, install_dir: str, target: str, token: str) -> subprocess.Popen:
    """앱이 끝나기를 기다렸다가 install_dir을 백업 이름으로 바꾸고 installer를 조용히 실행해 새 버전을 켜는 도우미
    (update_helper_windows.ps1)를 띄움. 새 버전이 잘 켜지지 않으면 도우미가 백업을 되돌리고 옛 앱을 켠다. token: 업데이트
    기록(Pending.token)의 토큰 — 도우미가 다시 켜는 앱에 `--update-result TOKEN`으로 넘김(그 앱만 결과를 판정).

    부른 쪽은 업데이트 기록(write_pending)을 남긴 뒤 이것을 부르고 앱을 끝낸다. 도우미가 설치 폴더의 이름을 바꾸므로
    설치 폴더 안의 스크립트를 state_dir()로 복사해 실행하고, 작업 폴더도 state_dir()로 둔다 — 앱의 작업 폴더(바로
    가기가 설치 폴더로 정함)를 물려받으면 그 폴더 핸들 때문에 설치 폴더의 이름을 바꿀 수 없음. 창 없는 자기 콘솔로,
    새 프로세스 그룹으로 띄움(_WINDOWS_HELPER_CREATIONFLAGS) — 앱이 끝나도 같이 끝나지 않음. 환경은
    _helper_env(다시 켜는 앱이 새로 시작한 앱이 되게, PS7의 PSModulePath 없이), DLL 찾는 곳은 기본
    (_default_dll_search_for_children). stdout·stderr는 helper_console_path(띄울 때마다 새로) — PowerShell이 스크립트를
    시작하지 못하거나 기록을 쓰기 전에 실패해도 그 출력이 남음. 띄운 Popen을 돌려줌 — 앱은 도우미가 시작 기록
    (HELPER_START_TEXT)을 남길 때까지 이것으로 도우미가 살아 있는지 보고, 그 뒤에 끝난다(player_update._hand_off). Popen
    실패는 그대로 올린다.
    """
    script = _copy_helper_to_state_dir(HELPER_WINDOWS_FILE_NAME)
    args = [
        _windows_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", script,
        "-AppPid", str(os.getpid()),
        "-InstallDir", install_dir,
        "-Installer", installer,
        "-Target", target,
        "-OkFile", ok_marker_path(),
        "-Log", log_path(),
        "-Token", token,
    ]
    with open(helper_console_path(), "wb") as console, _default_dll_search_for_children():
        return subprocess.Popen(
            args,
            creationflags=_WINDOWS_HELPER_CREATIONFLAGS,
            cwd=state_dir(),
            env=_helper_env(),
            stdin=subprocess.DEVNULL,
            stdout=console,
            stderr=subprocess.STDOUT,
        )


# ---- 업데이트 기록 (재시작한 앱이 성공/실패를 판정) ----


@dataclass(frozen=True)
class Pending:
    """업데이트를 건 뒤 남기는 기록: target(바꾸려는 버전)·previous(바꾸기 전 버전)·platform_key·started
    (건 시각, timestamp()). token: 도우미가 다시 켜는 앱에 넘기는 무작위 토큰(그 앱만 결과를 판정), helper_pid: 도우미의
    pid(살아 있는 동안 '업데이트 중'), app_pid: 업데이트를 건 창의 pid(실패 창에 그 창의 기록만) — pid는 글자. 1.1.x 앱이
    쓴 옛 기록에는 뒤의 셋이 없음 → 빈 글자."""

    target: str
    previous: str
    platform_key: str
    started: str
    token: str = ""
    helper_pid: str = ""
    app_pid: str = ""


def _pending_path():
    return os.path.join(state_dir(), PENDING_FILE_NAME)


def write_pending(p: Pending) -> None:
    user_files.write_json_atomic(_pending_path(), dataclasses.asdict(p), indent=None)


def read_pending() -> Pending | None:
    """기록이 없으면 None. 있지만 형식이 깨졌으면 UpdateError."""
    path = _pending_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise UpdateError(f"업데이트 기록을 읽지 못했습니다: {path}\n{exc}") from exc
    fields = dataclasses.fields(Pending)
    required = [f.name for f in fields if f.default is dataclasses.MISSING]
    optional = [f.name for f in fields if f.default is not dataclasses.MISSING]  # 옛 기록에는 없음 → 빈 글자
    if not (isinstance(data, dict) and all(isinstance(data.get(name), str) for name in required)
            and all(isinstance(data.get(name, ""), str) for name in optional)):
        raise UpdateError(f"업데이트 기록의 형식이 다릅니다: {path}\n{data!r}")
    p = Pending(**{name: data[name] for name in required}, **{name: data.get(name, "") for name in optional})
    if not all(_PID_TEXT_RE.fullmatch(pid) for pid in (p.helper_pid, p.app_pid) if pid):
        raise UpdateError(f"업데이트 기록의 형식이 다릅니다 (pid가 숫자가 아님): {path}\n{data!r}")
    return p


def clear_pending() -> None:
    try:
        os.remove(_pending_path())
    except FileNotFoundError:
        pass


def ok_marker_path() -> str:
    return os.path.join(state_dir(), OK_MARKER_FILE_NAME)


def write_ok_marker(version: str) -> None:
    user_files.write_json_atomic(ok_marker_path(), {"version": version}, indent=None)


def startup_result(current_version: str, update_token: str | None) -> tuple[str, Pending] | None:
    """앱이 시작할 때 부름: 업데이트 기록이 있으면 현재 버전과 비교해 판정하고 기록을 지운다.

    기록이 없으면 None. 기록에 토큰이 있고 그 도우미가 아직 앱을 다시 켤 수 있으면(_helper_may_relaunch) 도우미가 그 토큰과
    함께 켠 앱(update_token이 같음)만 판정 — 다르거나 없으면(업데이트 중에 사용자가 켠 앱) 기록을 그대로 두고 None: 진짜 새
    앱이 '잘 켜짐'을 쓰게. 도우미가 다시 켜지 않고 끝났으면(앱이 끝나지 않아 그만둠·로그아웃 뒤 되살림·충돌 등) 아무 앱이나
    판정 — 실패를 알리지 않은 채 기록이 남지 않게. 토큰 없는 옛 기록(1.1.x 앱이 씀 — 1.1.x 도우미는 토큰 없이 켬, 이
    버전으로 올리는 첫 업데이트)은 update_token과 상관없이 예전 규칙 그대로.
    current_version == target이면 ok 표시를 쓰고 기록을 지운 뒤 ("ok", 기록).
    current_version == previous(업데이트가 실패해 옛 버전이 그대로 켜짐)면 기록을 지운 뒤 ("failed", 기록).
    그 밖(업데이트를 거는 동안 다른 버전 — 예: 아직 바꾸는 중)이면 기록을 그대로 두고 None.
    """
    p = read_pending()
    if p is None:
        return None
    if p.token and update_token != p.token and _helper_may_relaunch(p):
        return None
    if current_version == p.target:
        write_ok_marker(p.target)
        clear_pending()
        return ("ok", p)
    if current_version == p.previous:
        clear_pending()
        return ("failed", p)
    return None


def _record_time(p: Pending) -> float:
    """기록을 쓴 시각(started — 시간대 없는 지역 시각, timestamp())을 epoch 초로."""
    return datetime.datetime.fromisoformat(p.started).timestamp()


def _helper_alive(p: Pending) -> bool:
    """기록의 도우미(helper_pid)가 아직 도는지 — 그 pid의 프로세스가 살아 있고 기록을 쓴 때부터 HELPER_START_WINDOW_S 안에
    시작했음 (pid를 물려받은 다른 프로세스가 아님). 시작 시각은 Mac ps가 초 단위(버림), started도 초 단위(버림) → 1초 여유.
    프로세스를 확인하다 난 오류는 그대로 올림."""
    from yesoncheck import instances  # instances가 이 모듈을 불러오므로 여기서

    helper_started = instances.process_start_time(int(p.helper_pid))
    if helper_started is None:
        return False  # 도우미가 끝남
    written = _record_time(p)
    return written - 1 <= helper_started <= written + HELPER_START_WINDOW_S


def _helper_may_relaunch(p: Pending) -> bool:
    """토큰 있는 기록의 도우미가 아직 앱을 (토큰과 함께) 다시 켤 수 있는지 — 업데이트 중. 기록이 HELPER_MAX_LIFETIME_S보다
    오래되었으면 아님. 도우미 pid가 있으면 그 도우미가 돎(_helper_alive), 없으면 기록이 HELPER_START_WINDOW_S 안에 쓰임
    (_hand_off가 도우미를 띄우고 그 pid를 다시 쓰기 전 — 이때 켠 앱이 '실패'로 판정해 기록을 지우면 도우미가 켤 새 앱이 '잘
    켜짐'을 쓰지 못해 되돌림). 토큰 없는 옛 기록은 아님 (1.1.x 도우미가 토큰 없이 켜는 새 앱이 판정해야 함)."""
    if not p.token:
        return False
    age = time.time() - _record_time(p)
    if age > HELPER_MAX_LIFETIME_S:
        return False
    if not p.helper_pid:
        return age <= HELPER_START_WINDOW_S
    return _helper_alive(p)


def update_in_progress() -> bool:
    """다른 창이 넘긴 업데이트가 진행 중인지 — 토큰 있는 업데이트 기록이 있고 그 도우미가 아직 앱을 다시 켤 수 있음
    (_helper_may_relaunch: 도우미가 돎, 또는 도우미 pid를 아직 쓰기 전). 토큰 없는 옛 기록(1.1.x 앱이 씀)은 False.
    기록이 깨졌으면 UpdateError, 프로세스를 확인하다 난 오류는 그대로 올림."""
    p = read_pending()
    return p is not None and _helper_may_relaunch(p)
