"""업데이트 설치 준비: 받기(다운로드+sha256 검사)·Mac dmg 준비(hdiutil+ditto)·업데이트 기록 (Qt 없음).

이 모듈은 파일·프로세스 작업만 한다 — 창을 띄우는 일, 로그 메시지를 어떻게 보여 줄지, 백그라운드 스레드로
옮기는 일은 부른 쪽(player_base 등)이 한다. NAS 경로는 그냥 복사(1 MB 단위), URL은 requests로 스트리밍
받는다. 받은 뒤 크기·sha256을 확인하고, 틀리거나 취소되면 받던 파일(.part)을 지운다. 예상 못 한 예외는
삼키지 않고 그대로 올린다.

Mac에서는 dmg를 hdiutil로 열고 안의 .app 하나를 ditto로(심볼릭 링크가 많아 shutil 대신) 앱 옆의 숨김 이름으로
복사한 뒤 항상 떼어내고, 복사한 앱의 버전을 build_info로 확인한다. 업데이트를 건 뒤 기록
(state_dir()/pending_update.json)을 남겨 두면, 재시작한 앱이 현재 버전과 비교해 성공(ok)·실패(failed)를
판정해 지운다(startup_result). 이 기록·로그(update.log)는 재시작 뒤 앱과, 종료를 기다리다 새 앱을 켜는
도우미(다른 프로세스)가 함께 쓴다 — log()는 매번 열고 닫는다(핸들을 오래 들고 있으면 Windows에서 도우미가
로그 파일에 쓰지 못함).
"""

import dataclasses
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

import requests

from yesoncheck import build_info, paths
from yesoncheck.updates import FileEntry

PENDING_FILE_NAME = "pending_update.json"
OK_MARKER_FILE_NAME = "update_ok.json"
LOG_FILE_NAME = "update.log"
APP_EXECUTABLE_NAME = "YesonCheck_Autocut"

NEEDED_BYTES = {"windows": 1_500_000_000, "mac-x86_64": 3_000_000_000, "mac-arm64": 3_000_000_000}

_CHUNK_BYTES = 1024 * 1024  # NAS 복사·sha256 계산·requests 스트리밍 모두 1 MB 단위
_DOWNLOAD_TIMEOUT_S = 10  # 연결·읽기 각각
_LOG_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")  # log()가 줄 앞에 붙이는 시각


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
    """시각(timestamp())을 붙여 log_path()에 한 줄 덧붙이고 stdout에도 보임.

    매번 열고 닫는다(긴 시간 핸들을 들고 있지 않음) — 업데이트 뒤 다시 켜는 도우미(별도 프로세스)가
    Windows에서 같은 파일에 덧붙여 쓸 수 있어야 하기 때문.
    """
    stamped = f"{timestamp()} {line}"
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write(stamped + "\n")
    print(stamped)


def log_tail_since(started: str, max_lines: int = 80) -> str:
    """로그에서 시각이 started 이상인 줄만, 최근 max_lines줄까지. 로그 파일이 없으면 빈 글자.

    log()가 쓴 줄은 "<ISO 시각> …"로 시작하지만, 트레이스백처럼 그 뒤에 시각 없이 여러 줄이 이어지는
    경우가 있다(실패 로그를 통째로 보여 줘야 함 — "업데이트 실패" 창의 자료). 시각으로 시작하는 줄만
    포함 여부를 다시 정하고, 시각이 없는 줄(들여쓴 트레이스백 줄 등)은 바로 앞의 시각 있는 줄과 같은
    여부를 따른다. started는 초 단위까지만 비교한다(앞 19자리 "YYYY-MM-DDTHH:MM:SS") — 더 긴(마이크로초·
    시간대) 값이 들어와도 같은 초의 줄을 빼먹지 않게.
    """
    try:
        with open(log_path(), encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return ""
    cutoff = started[:19]
    matched = []
    include = False
    for line in lines:
        if _LOG_TIMESTAMP_RE.match(line):
            include = line[:19] >= cutoff
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
    삼키지 않음 — rmdir 실패도 그대로 올림). 복사한 앱의 build_info.json 버전이 target_version과
    다르면(또는 실행 파일이 없으면) 준비한 폴더를 지우고 UpdateError.
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
    _hdiutil_detach(mount_point)  # 복사 성공·실패 모두 항상 떼어냄; 실패하면 그대로 올림(마운트 안 지움)
    os.rmdir(mount_point)  # 떼어내기가 성공한 뒤에만 — 비어 있어야 하고, 실패해도 그대로 올림(삼키지 않음)
    if copy_error is not None:
        raise copy_error
    _verify_staged_app(dest_path, target_version)
    return dest_path


# ---- 업데이트 기록 (재시작한 앱이 성공/실패를 판정) ----


@dataclass(frozen=True)
class Pending:
    """업데이트를 건 뒤 남기는 기록: target(바꾸려는 버전)·previous(바꾸기 전 버전)·platform_key·started
    (건 시각, ISO 8601)."""

    target: str
    previous: str
    platform_key: str
    started: str


def _pending_path():
    return os.path.join(state_dir(), PENDING_FILE_NAME)


def _write_json_atomic(path, data):
    """임시 파일 + os.replace로 씀 (쓰는 중에 읽는 쪽이 반쪽짜리 파일을 보지 않게)."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_pending(p: Pending) -> None:
    _write_json_atomic(_pending_path(), dataclasses.asdict(p))


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
    names = [f.name for f in dataclasses.fields(Pending)]
    if not isinstance(data, dict) or not all(isinstance(data.get(name), str) for name in names):
        raise UpdateError(f"업데이트 기록의 형식이 다릅니다: {path}\n{data!r}")
    return Pending(**{name: data[name] for name in names})


def clear_pending() -> None:
    try:
        os.remove(_pending_path())
    except FileNotFoundError:
        pass


def ok_marker_path() -> str:
    return os.path.join(state_dir(), OK_MARKER_FILE_NAME)


def write_ok_marker(version: str) -> None:
    _write_json_atomic(ok_marker_path(), {"version": version})


def startup_result(current_version: str) -> tuple[str, Pending] | None:
    """앱이 시작할 때 부름: 업데이트 기록이 있으면 현재 버전과 비교해 판정하고 기록을 지운다.

    기록이 없으면 None. current_version == target이면 ok 표시를 쓰고 기록을 지운 뒤 ("ok", 기록).
    current_version == previous(업데이트가 실패해 옛 버전이 그대로 켜짐)면 기록을 지운 뒤 ("failed", 기록).
    그 밖(업데이트를 거는 동안 다른 버전 — 예: 아직 바꾸는 중)이면 기록을 그대로 두고 None.
    """
    p = read_pending()
    if p is None:
        return None
    if current_version == p.target:
        write_ok_marker(p.target)
        clear_pending()
        return ("ok", p)
    if current_version == p.previous:
        clear_pending()
        return ("failed", p)
    return None
