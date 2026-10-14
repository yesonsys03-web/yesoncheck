"""Windows 자동 연결: 이 PC에 이미 연결된 네트워크 드라이브에서 공유 설정 폴더를 찾고,
변환표(path_map.json)의 "Mac 경로 앞부분 ↔ UNC" 짝을 찾아 기존 변환표에 합친다.

연결은 만들지 않는다(드라이브는 각 PC에서 이미 연결돼 있어야 함). 짝은 작품 폴더가 실제로 열리는지로
검증한다(공유 이름이 같은지만으로 짝짓지 않음). 확인 창은 path_map_setup_dialog.py.
"""

import copy
import datetime
import json
import ntpath
import os
import shutil
import stat
import string
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from yesoncheck import external_tools, paths, shared_config, timing_log

# 공유 하나를 열어 볼 때 기다리는 최대 시간. 서버가 꺼진(주소가 바뀐) 기억된 드라이브는 SMB(445)·NetBIOS(139)·
# WebDAV를 차례로 시도하느라 수십 초~무한히 걸릴 수 있음 → 이 시간이 지나면 '응답 없음'으로 건너뛰고 알림
SHARE_PROBE_TIMEOUT_S = 10
SHORTCUT_TIMEOUT_S = 10  # 바로 가기(.lnk) 대상 읽기 (PowerShell 한 번)
_WAIT_STEP_S = 0.1  # 기다리는 동안 on_wait를 부르는 간격


class SetupCancelled(Exception):
    """진행 표시에서 사용자가 취소함."""


class ShortcutError(Exception):
    """바로 가기(.lnk)의 대상을 읽지 못함 (PowerShell 없음·시간 초과·오류)."""


def _timeout(timeout):
    """기다릴 시간 (None이면 SHARE_PROBE_TIMEOUT_S — 부를 때 읽어 시험에서 바꿀 수 있게)."""
    return SHARE_PROBE_TIMEOUT_S if timeout is None else timeout


def call_with_timeout(func, arg, timeout=None, on_wait=None):
    """func(arg)를 daemon 스레드에서 실행하고 timeout초까지만 기다림 → (끝났는지, 결과).

    on_wait: 기다리는 동안 약 0.1초마다 부름 (GUI 스레드에서 이벤트 처리·진행 창 등). False를 돌려주면 기다리기를
    멈추고 SetupCancelled. func의 예외는 시간 안에 오면 그대로 올림. 호출한 쪽이 실제로 포기했을 때만(시간 초과·취소·
    on_wait 예외) '버려짐'으로 표시 — 버려진 스레드는 나중에 끝나도 이 호출 안의 상자에만 쓰고(호출한 쪽의 상태는
    건드리지 않음), 그 뒤에 난 예외는 로그에만 남김. 판단은 잠금 안에서 하므로 예외는 올리거나 로그에 남기거나
    둘 중 하나만, 반드시 한 번.
    """
    timeout = _timeout(timeout)
    lock = threading.Lock()
    done = threading.Event()
    box = {}  # value / error, 그리고 abandoned (잠금 안에서만 읽고 씀)

    def run():
        try:
            outcome = ("value", func(arg))
        except BaseException as exc:
            outcome = ("error", exc)
        with lock:
            box[outcome[0]] = outcome[1]
            late = box.get("abandoned", False)
            done.set()
        if late and outcome[0] == "error":
            timing_log.log("확인", f"{arg} — 응답 없음으로 건너뛴 뒤 늦게 난 오류: {outcome[1]!r}")

    def give_up():
        """(잠금 안) 아직 안 끝났으면 버려짐으로 표시. 이미 끝났는데 호출한 쪽이 자기 예외로 나가면 그 오류는 로그로."""
        if done.is_set():
            return True
        box["abandoned"] = True
        return False

    threading.Thread(target=run, name=f"probe {arg}", daemon=True).start()
    deadline = time.monotonic() + timeout
    settled = False
    try:
        while not done.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if done.wait(min(_WAIT_STEP_S, remaining)):
                break
            if on_wait is not None and on_wait() is False:
                raise SetupCancelled()
        with lock:
            finished = give_up()
            settled = True
            outcome = dict(box)
    finally:
        if not settled:  # 취소·on_wait 예외로 나가는 중
            with lock:
                finished = give_up()
                outcome = dict(box)
            if finished and "error" in outcome:
                timing_log.log("확인", f"{arg} — 기다리기를 멈춘 사이에 난 오류: {outcome['error']!r}")
    if not finished:
        return False, None
    if "error" in outcome:
        raise outcome["error"]
    return True, outcome["value"]


def probe(func, path, timeout=None, on_wait=None):
    """func(path)(열리는지·있는지 확인)를 timeout초까지만 기다림 → True | False | None(시간 안에 응답 없음)."""
    finished, value = call_with_timeout(func, path, timeout, on_wait)
    return bool(value) if finished else None


def _default_is_dir(path):
    return os.path.isdir(path)


def _default_is_file(path):
    return os.path.isfile(path)


def _default_realpath(path):
    return os.path.realpath(path)


def _default_scandir(path):
    return os.scandir(path)


def _default_lstat(path):
    return os.lstat(path)


def _powershell():
    """Windows PowerShell 실행 파일 (없으면 PATH의 powershell)."""
    exe = os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    return exe if os.path.isfile(exe) else "powershell"


def resolve_shortcuts(lnk_paths):
    """(Windows) 바로 가기(.lnk)들의 대상 경로를 PowerShell 한 번으로 읽음 → {lnk: 대상 경로 또는 ShortcutError}.

    WScript.Shell의 CreateShortcut(...).TargetPath (콘솔 창 없이, 표준 입력 없이, 출력은 UTF-8). 대상 공유는 열지
    않음. 경로는 명령 문자열에 넣지 않고 환경 변수 YC_LNKS(줄바꿈으로 구분)로 넘김 — 경로 안의 따옴표(’ 등)가 명령을
    깨지 않게. PowerShell을 실행하지 못함(없음·정책으로 막힘 등 모든 OSError)·시간 초과·오류 종료는 ShortcutError로
    올림. 바로 가기 하나를 읽지 못하면 그 값만 ShortcutError.
    """
    lnk_paths = list(lnk_paths)
    if not lnk_paths:
        return {}
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "$shell=New-Object -ComObject WScript.Shell; "
        "foreach($p in $env:YC_LNKS.Split([char]10)){ "
        "try { [Console]::Out.WriteLine('OK' + [char]9 + $shell.CreateShortcut($p).TargetPath) } "
        "catch { [Console]::Out.WriteLine('ERR' + [char]9 + ($_.Exception.Message -replace '[\\r\\n]+', ' ')) } }"
    )
    command = [_powershell(), "-NoProfile", "-NonInteractive", "-Command", script]
    env = dict(os.environ, YC_LNKS="\n".join(lnk_paths))
    try:
        completed = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, env=env,
                                   timeout=SHORTCUT_TIMEOUT_S, **external_tools.subprocess_kwargs())
    except subprocess.TimeoutExpired as exc:
        raise ShortcutError(f"바로 가기 대상 확인이 {SHORTCUT_TIMEOUT_S:g}초 안에 끝나지 않았습니다") from exc
    except OSError as exc:  # 없음(FileNotFoundError)·AppLocker/SRP/WDAC로 막힘(PermissionError, WinError 1260) 등
        raise ShortcutError(f"PowerShell을 실행하지 못했습니다: {exc}") from exc
    out = external_tools.decode_output(completed.stdout).lstrip("\ufeff")
    if completed.returncode != 0:
        raise ShortcutError(
            f"PowerShell 오류 (종료 코드 {completed.returncode}): {external_tools.decode_output(completed.stderr).strip()}"
        )
    lines = [line.rstrip("\r") for line in out.split("\n")]  # "\n"으로만 나눔 (오류 문구 안의 U+2028 등으로는 안 나눔)
    if lines and lines[-1] == "":
        lines.pop()  # 마지막 줄바꿈
    if len(lines) != len(lnk_paths):
        raise ShortcutError(
            f"PowerShell 출력 줄 수가 바로 가기 수와 다릅니다 ({len(lines)}줄 / {len(lnk_paths)}개): {out!r}"
            f" {external_tools.decode_output(completed.stderr).strip()}"
        )
    result = {}
    for path, line in zip(lnk_paths, lines):
        status, _tab, value = line.partition("\t")
        result[path] = value if status == "OK" else ShortcutError(value or line)
    return result


def _default_mtime(path):
    return os.stat(path).st_mtime_ns


_shortcut_cache = {}  # (경로 키, 수정 시각) → 대상 경로. 읽지 못한 것은 넣지 않음 (다음에 다시 읽어 봄)
_shortcut_cache_lock = threading.Lock()


def clear_shortcut_cache():
    with _shortcut_cache_lock:
        _shortcut_cache.clear()


def shortcut_targets(lnk_paths, resolver=None):
    """바로 가기 대상 → {lnk: 대상 경로 또는 ShortcutError}. 프로세스 안에서 (경로, 수정 시각)별로 한 번만 읽음:
    백그라운드 불러오기가 읽은 것을 GUI 스레드의 자동 설정·다시 읽기와 Harmony 경로 확인이 그대로 씀.
    수정 시각을 읽지 못하면 캐시 없이 읽음. 오류(호출 전체 실패는 ShortcutError로 올림)는 캐시하지 않음."""
    resolver = resolver or resolve_shortcuts
    result, missing = {}, []
    for path in lnk_paths:
        try:
            key = (os.path.normcase(path), _default_mtime(path))
        except OSError:
            key = None
        with _shortcut_cache_lock:
            cached = _shortcut_cache.get(key) if key is not None else None
        if cached is not None:
            result[path] = cached
        else:
            missing.append((path, key))
    if missing:
        resolved = resolver([path for path, _key in missing])
        for path, key in missing:
            if path not in resolved:
                continue
            target = resolved[path]
            result[path] = target
            if key is not None and not isinstance(target, ShortcutError):
                with _shortcut_cache_lock:
                    _shortcut_cache[key] = target
    return result


def _shortcut_unc(target):
    """바로 가기 대상 → UNC (연결된 네트워크 드라이브 위면 drive_to_unc로 바꿈). 로컬·빈 대상, \\\\?\\·\\\\.\\로
    시작하는 경로(장치·긴 경로 접두사)는 None. 드라이브 연결 정보를 읽지 못한 오류 등은 PathMapError로 올림
    (호출하는 쪽이 문제 줄로)."""
    if not target or target.startswith(("\\\\?\\", "\\\\.\\")):
        return None
    unc = _real_unc(target)
    if unc is not None:
        return unc
    try:
        converted = paths.drive_to_unc(target)
    except paths.NotNetworkDriveError:
        return None
    return converted if converted.startswith("\\\\") else None


def _join_unc(unc, rest_parts):
    return unc.rstrip("\\") + "\\" + "\\".join(rest_parts)


@dataclass
class Share:
    """이 PC에 연결된 네트워크 공유 하나 (같은 UNC에 연결된 드라이브 문자는 모두 drives에)."""

    unc: str
    drives: list = field(default_factory=list)


@dataclass
class Candidate:
    """Mac 앞부분 하나에 대한 Windows 주소 후보와, 그 짝으로 폴더가 열리는 것이 확인된 작품들."""

    mac_prefix: str
    unc: str
    drives: list
    works: list = field(default_factory=list)


@dataclass
class PairChoice:
    """Mac 앞부분 하나와 후보들 (기본 선택이 첫 번째)."""

    mac_prefix: str
    candidates: list

    @property
    def ambiguous(self):
        return len(self.candidates) > 1


@dataclass
class Proposal:
    pairs: list
    unmatched: dict
    shares: list
    share_problems: list = field(default_factory=list)

    def default_choices(self):
        return [(pair.mac_prefix, pair.candidates[0].unc) for pair in self.pairs]

    def ordered_default_choices(self):
        """기본 선택을 합칠 순서로: 확인된 작품이 많은 짝 먼저, 같으면 Mac 앞부분 순서 (split_mergeable에 넘김)."""
        pairs = sorted(
            self.pairs,
            key=lambda pair: (-len(pair.candidates[0].works), tuple(paths._mac_parts(pair.mac_prefix))),
        )
        return [(pair.mac_prefix, pair.candidates[0].unc) for pair in pairs]


def connected_shares(remote_of_drive=None):
    """드라이브 문자 A~Z 중 네트워크 드라이브를 UNC별로 묶어 돌려줍니다 → (shares, problems).

    연결 정보를 읽지 못한 드라이브는 problems에 "Z: — <이유>"로 남기고 나머지 드라이브는 계속 씁니다.
    """
    resolve = remote_of_drive or paths._remote_name_of_drive
    shares = []
    by_key = {}
    problems = []
    for letter in string.ascii_uppercase:
        drive = letter + ":"
        try:
            remote = resolve(drive)
            if not remote:
                continue
            key = paths.unc_key(remote)
        except paths.PathMapError as exc:
            problems.append(f"{drive} — {exc}")
            continue
        share = by_key.get(key)
        if share is None:
            share = Share(unc=paths.drive_to_unc(remote))
            by_key[key] = share
            shares.append(share)
        share.drives.append(drive)
    return shares, problems


def merge_shares(shares, more):
    """두 공유 목록을 UNC별로 합친 새 목록. 같은 공유의 드라이브 문자·링크 이름은 한 Share에 모으고 순서는 유지."""
    merged = [Share(share.unc, list(share.drives)) for share in shares]
    by_key = {paths.unc_key(share.unc): share for share in merged}
    for share in more:
        key = paths.unc_key(share.unc)
        found = by_key.get(key)
        if found is None:
            found = Share(share.unc, list(share.drives))
            by_key[key] = found
            merged.append(found)
        else:
            found.drives.extend(drive for drive in share.drives if drive not in found.drives)
    return merged


def system_drive():
    """%SystemDrive% (보통 'C:')."""
    return os.environ.get("SystemDrive") or "C:"


def _real_unc(real):
    """realpath 결과가 UNC면 '\\\\서버\\공유\\…' 모양으로 (긴 경로 접두사 \\\\?\\UNC\\ 제거), 아니면 None."""
    if real.startswith("\\\\?\\UNC\\"):
        real = "\\\\" + real[len("\\\\?\\UNC\\"):]
    if real.startswith("\\\\") and not real.startswith("\\\\?\\") and not real.startswith("\\\\.\\"):
        return real
    return None


# Windows 재분석 태그·파일 속성 (winnt.h; Python stat 모듈은 Windows에서만 정의)
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # 정션
IO_REPARSE_TAG_SYMLINK = 0xA000000C
FILE_ATTRIBUTE_DIRECTORY = 0x10


def _is_dir_link(entry):
    """디렉터리 심볼릭 링크 또는 정션인지 (파일 링크는 아님). 대상은 열지 않음 — Windows는 목록을 읽을 때 받은
    링크 자체의 속성(디렉터리 링크·정션은 FILE_ATTRIBUTE_DIRECTORY)과 재분석 태그를 봄."""
    info = entry.stat(follow_symlinks=False)
    if not (entry.is_symlink() or getattr(info, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT):
        return False
    attributes = getattr(info, "st_file_attributes", None)
    if attributes is None:  # Windows가 아님 (실제로는 Windows에서만 씀): 대상을 따라가 봄
        return entry.is_dir()
    return bool(attributes & FILE_ATTRIBUTE_DIRECTORY)


FILE_LINK_KIND = "파일 링크(/D 없는 심볼릭 링크)"


def _kind(info, name, is_symlink=None):
    """항목 종류 (따라가지 않은 정보로): 디렉터리 링크·파일 링크·정션·폴더(링크 아님)·바로 가기(.lnk)·파일."""
    mode = getattr(info, "st_mode", 0)
    tag = getattr(info, "st_reparse_tag", 0)
    attributes = getattr(info, "st_file_attributes", None)
    if is_symlink is None:
        is_symlink = stat.S_ISLNK(mode) or tag == IO_REPARSE_TAG_SYMLINK
    if is_symlink:
        if attributes is not None and not attributes & FILE_ATTRIBUTE_DIRECTORY:
            return FILE_LINK_KIND
        return "디렉터리 링크"
    if tag == IO_REPARSE_TAG_MOUNT_POINT:
        return "정션"
    if stat.S_ISDIR(mode):
        return "폴더(링크 아님)"
    if name.casefold().endswith(".lnk"):
        return "바로 가기(.lnk)"
    return "파일"


def _path_kind(path):
    """경로의 항목 종류 (lstat — 따라가지 않음). 없으면 '없음'."""
    try:
        info = _default_lstat(path)
    except FileNotFoundError:
        return "없음"
    except OSError as exc:
        return f"종류를 알 수 없음 ({exc})"
    return _kind(info, ntpath.basename(path))


def _is_harmony_name(name):
    base = (name[:-4] if name.casefold().endswith(".lnk") else name).casefold()
    return base == "usa_db" or base.startswith("usadata")


def local_link_shares(root=None, scandir=None, realpath=None, resolve_shortcuts=None, timeout=None):
    """(Windows) 시스템 드라이브 바로 아래의 디렉터리 링크·바로 가기(.lnk) 중 대상이 UNC인 것 → (shares, problems).

    Toon Boom Harmony용으로 C:\\USA_DB → \\\\Mainnas\\USA_DB 같은 링크나 바로 가기(C:\\USA_DB.lnk — 탐색기에는
    확장자 없이 'USA_DB'로 보임)를 만들어 둔 PC는 그 공유를 드라이브 문자 없이 씀 → 연결된 공유처럼 다룸:
    Share(unc=<대상 UNC>, drives=["C:\\USA_DB"] 또는 ["C:\\USA_DB.lnk"]). 링크가 아닌 폴더는 실제 위치를 묻지 않음.
    링크의 실제 위치는 timeout초까지만 기다림. 바로 가기는 모두 PowerShell 한 번으로 읽음. 알 수 없는 링크·바로 가기,
    목록을 읽지 못한 경우는 problems에 남기고 나머지는 씀.
    """
    root = root or system_drive() + "\\"
    scandir = scandir or _default_scandir
    realpath = realpath or _default_realpath
    resolve_shortcuts = resolve_shortcuts or globals()["resolve_shortcuts"]
    timeout = _timeout(timeout)
    timing_log.log("링크", f"{root} 아래 디렉터리 링크·바로 가기 확인 중…")
    started = time.perf_counter()
    try:
        with scandir(root) as entries:
            entries = list(entries)
            links = [entry for entry in entries if _is_dir_link(entry)]
            shortcuts = [entry for entry in entries  # 보통 파일만 (이름만 .lnk인 폴더·링크는 아님)
                         if entry.name.casefold().endswith(".lnk") and entry.is_file(follow_symlinks=False)]
            harmony = [f"{entry.name}={_kind(entry.stat(follow_symlinks=False), entry.name, entry.is_symlink())}"
                       for entry in entries if _is_harmony_name(entry.name)]
    except OSError as exc:
        timing_log.log("링크", f"{root} 목록을 읽지 못함 ({timing_log.since(started)}): {exc}")
        return [], [f"{root} — 목록을 읽지 못함: {exc}"]
    # 바로 가기 짐작이 틀렸을 때도 다음 로그로 알 수 있게: Harmony 이름(USA_DB·usadata*)의 항목 종류
    timing_log.log("링크", f"{root} Harmony 항목 종류: {', '.join(harmony) or '(USA_DB·usadata* 없음)'}")
    shares, problems = [], []

    def add(label, target, unc, elapsed_from):
        timing_log.log("링크", f"{label} → {target} ({timing_log.since(elapsed_from)})" + ("" if unc else " — 공유가 아님"))
        if unc is not None:
            shares[:] = merge_shares(shares, [Share(unc, [label])])

    for entry in links:
        link_started = time.perf_counter()
        try:
            finished, real = call_with_timeout(realpath, entry.path, timeout)
            if not finished:
                problems.append(f"{entry.path} — 실제 위치가 {timeout:g}초 안에 응답 없음 (대상 서버가 꺼졌거나 느림)")
                timing_log.log("링크", f"{entry.path} → 응답 없음 ({timeout:g}초) — 건너뜀")
                continue
            unc = _real_unc(real)
            if unc is not None:
                paths.unc_key(unc)  # 서버·공유 이름까지 있는 UNC인지 확인 (아니면 PathMapError)
        except (OSError, paths.PathMapError) as exc:
            problems.append(f"{entry.path} — 실제 위치를 알 수 없음: {exc}")
            timing_log.log("링크", f"{entry.path} → 알 수 없음 ({timing_log.since(link_started)}): {exc}")
            continue
        add(entry.path, real, unc, link_started)

    if shortcuts:
        lnk_started = time.perf_counter()
        lnk_paths = [entry.path for entry in shortcuts]
        try:
            targets = shortcut_targets(lnk_paths, resolve_shortcuts)  # 프로세스 안에서 (경로, 수정 시각)별로 한 번
        except ShortcutError as exc:
            problems.append(f"{', '.join(lnk_paths)} — 바로 가기 대상을 알 수 없음: {exc}")
            timing_log.log("링크", f"바로 가기 {len(lnk_paths)}개의 대상을 알 수 없음 ({timing_log.since(lnk_started)}): {exc}")
            targets = {}
        for path in lnk_paths:
            if path not in targets:
                continue
            target = targets[path]
            try:
                if isinstance(target, ShortcutError):
                    raise target
                unc = _shortcut_unc(target)
                if unc is not None:
                    paths.unc_key(unc)
            except (ShortcutError, paths.PathMapError) as exc:
                problems.append(f"{path} — 바로 가기 대상을 알 수 없음: {exc}")
                timing_log.log("링크", f"{path} → 알 수 없음: {exc}")
                continue
            add(path, target, unc, lnk_started)
    timing_log.log("링크", f"{root} 링크·바로 가기 확인 끝 ({timing_log.since(started)}): UNC {len(shares)}개")
    return shares, problems


def available_shares():
    """(Windows) 이 PC에서 쓸 수 있는 공유: 연결된 네트워크 드라이브 + 시스템 드라이브의 UNC 링크 → (shares, problems).

    공유 설정 폴더 찾기, 변환표 자동 설정, 변환표 주소 고르기(with_preferred_aliases)에 씀.
    """
    timing_log.log("공유", "연결된 네트워크 드라이브 확인 중…")
    started = time.perf_counter()
    shares, problems = connected_shares()
    for problem in problems:
        timing_log.log("공유", f"드라이브 연결 정보를 읽지 못함: {problem}")
    links, link_problems = local_link_shares()
    merged = merge_shares(shares, links)
    listed = ", ".join(f"{share.unc} ({', '.join(share.drives)})" for share in merged) or "없음"
    timing_log.log("공유", f"쓸 수 있는 공유 ({timing_log.since(started)}): {listed}")
    return merged, problems + link_problems


def find_local_config_dir(drive=None, mac_config_dir=None, is_file=None, realpath=None, is_dir=None,
                          resolve_shortcuts=None, timeout=None):
    """(Windows) 시스템 드라이브 아래의 Harmony식 공유 설정 폴더 → (폴더 또는 None, 문제 줄 또는 None).

    Mac 경로를 그대로 옮긴 C:\\USA_DB\\test_jn\\.yesoncheck에 work_paths.json이 있고 실제 위치(realpath)가 UNC(NAS를
    가리키는 링크)일 때만 그 UNC를 씀. C:\\USA_DB가 폴더가 아니고 바로 가기 C:\\USA_DB.lnk(탐색기에는 'USA_DB')가
    있으면 그 대상(UNC, 또는 연결된 네트워크 드라이브 위의 경로)을 PowerShell로 읽어 <대상>\\test_jn\\.yesoncheck를 봄.
    링크·바로 가기가 아닌 진짜 로컬 폴더·로컬 대상은 쓰지 않음(로그). 공유는 timeout초까지만 기다림. 알 수 없거나
    응답이 없으면 문제 줄로 돌려주고 None — 호출하는 쪽은 드라이브 후보로 계속 찾음.
    """
    is_file = is_file or _default_is_file
    realpath = realpath or _default_realpath
    is_dir = is_dir or _default_is_dir
    resolve_shortcuts = resolve_shortcuts or globals()["resolve_shortcuts"]
    timeout = _timeout(timeout)
    parts = paths._mac_parts(mac_config_dir or shared_config.MAC_CONFIG_DIR)
    base = (drive or system_drive()).rstrip("\\/") + "\\"
    folder = base + "\\".join(parts)
    timing_log.log("공유 설정", f"{folder} 확인 중…")
    started = time.perf_counter()
    answer = probe(is_file, folder + "\\" + shared_config.WORK_PATHS_FILENAME, timeout)  # C:\USA_DB가 링크면 NAS를 엶
    if answer is None:
        problem = f"{folder} — {timeout:g}초 안에 응답 없음 (링크 대상 서버가 꺼졌거나 느림)"
        timing_log.log("공유 설정", f"{folder} 응답 없음 ({timeout:g}초) — 건너뜀")
        return None, problem
    if answer:
        try:
            real = realpath(folder)
        except OSError as exc:
            problem = f"{folder} — 실제 위치(링크 대상)를 알 수 없음: {exc}"
            timing_log.log("공유 설정", f"{problem} ({timing_log.since(started)})")
            return None, problem
        unc = _real_unc(real)
        if unc is None:
            timing_log.log("공유 설정", f"{folder} 는 링크가 아니라 로컬 폴더 — 쓰지 않음 ({timing_log.since(started)})")
            return None, None
        timing_log.log("공유 설정", f"{folder} 확인 {timing_log.since(started)} — 찾음: {unc}")
        return unc, None
    timing_log.log("공유 설정", f"{folder} 확인 {timing_log.since(started)} — 없음")

    # 바로 가기: C:\USA_DB 폴더(링크 포함)가 없고 C:\USA_DB.lnk가 있을 때. 짐작이 틀렸을 때도 다음 로그로 알 수
    # 있게 C:\USA_DB가 무엇인지 남김
    top = base + parts[0]
    lnk = top + ".lnk"
    top_kind = _path_kind(top)
    if is_dir(top):
        below = "\\".join(parts[1:] + [shared_config.WORK_PATHS_FILENAME])
        timing_log.log("공유 설정", f"{top} 는 {top_kind} — 그 아래에 {below} 없음")
        return None, None
    if top_kind == FILE_LINK_KIND:
        timing_log.log("공유 설정", f"{top} 는 {FILE_LINK_KIND} — 따라가지 않음")
    elif top_kind == "없음":
        timing_log.log("공유 설정", f"{top} 없음")
    else:
        timing_log.log("공유 설정", f"{top} 는 {top_kind}")
    if not is_file(lnk):
        timing_log.log("공유 설정", f"{lnk} 없음")
        return None, None
    try:
        target = shortcut_targets([lnk], resolve_shortcuts)[lnk]  # local_link_shares가 읽었으면 다시 읽지 않음
        if isinstance(target, ShortcutError):
            raise target
        unc = _shortcut_unc(target)
    except (ShortcutError, paths.PathMapError) as exc:
        problem = f"{lnk} — 바로 가기 대상을 알 수 없음: {exc}"
        timing_log.log("공유 설정", f"{problem} ({timing_log.since(started)})")
        return None, problem
    if unc is None:
        timing_log.log("공유 설정", f"{lnk} → {target or '(대상 없음)'} — NAS(UNC)가 아니라 쓰지 않음")
        return None, None
    timing_log.log("공유 설정", f"{lnk} → {unc}")
    candidate = unc.rstrip("\\") + "\\" + "\\".join(parts[1:])
    answer = probe(is_file, candidate + "\\" + shared_config.WORK_PATHS_FILENAME, timeout)
    if answer is None:
        problem = f"{lnk} → {candidate} — {timeout:g}초 안에 응답 없음 (서버가 꺼졌거나 느림)"
        timing_log.log("공유 설정", f"{candidate} 응답 없음 ({timeout:g}초) — 건너뜀")
        return None, problem
    if not answer:
        timing_log.log("공유 설정", f"{candidate} 확인 {timing_log.since(started)} — 없음")
        return None, None
    timing_log.log("공유 설정", f"{candidate} 확인 {timing_log.since(started)} — 찾음 (바로 가기 {lnk})")
    return candidate, None


def config_dir_key(folder):
    """공유 설정 폴더 후보 비교 키: UNC는 unc_key, 로컬 경로는 대소문자·구분자 무시."""
    if folder.startswith("\\\\"):
        return ("unc",) + paths.unc_key(folder)
    return ("local", ntpath.normpath(folder.replace("/", "\\")).casefold())


def find_config_dirs(shares, mac_config_dir=None, is_file=None, problems=None, timeout=None):
    """연결된 공유에서 공유 설정 폴더(work_paths.json이 있는 폴더)를 찾습니다 → UNC 목록.

    Mac 공유 설정 경로(/USA_DB/test_jn/.yesoncheck)의 뒷부분 조각을 길게부터 공유 아래에 붙여 봅니다
    (USA_DB\\test_jn\\.yesoncheck → test_jn\\.yesoncheck, 뒷부분은 두 조각 이상).

    공유마다 동시에 확인하고 전체로 timeout초까지만 기다립니다: 그때까지 답이 없는 공유(서버가 꺼졌거나 주소가 바뀐
    기억된 드라이브 — 수십 초~무한히 걸릴 수 있음)는 '못 찾음'으로 치고 problems(목록)에 남깁니다.
    결과 순서는 공유 순서, 한 공유 안에서는 긴 뒷부분 먼저(차례로 확인할 때와 같음). 확인 중 오류는 그대로 올립니다.
    """
    is_file = is_file or _default_is_file
    timeout = _timeout(timeout)
    parts = paths._mac_parts(mac_config_dir or shared_config.MAC_CONFIG_DIR)
    # 호출한 쪽이 실제로 포기했을 때만 gave_up — 판단(어느 공유가 시간 안에 답했는지)과 각 공유의 '끝남' 표시는 같은
    # 잠금 안에서 하므로, 결과는 시간 안이면 쓰이고 아니면 로그에 '늦게 응답'으로만 남음 (둘 다 되는 일은 없음)
    lock = threading.Lock()
    gave_up = [False]
    done = [False] * len(shares)
    results = [None] * len(shares)
    errors = [None] * len(shares)

    def search(share):
        """이 공유에서 처음 찾은 폴더 (없으면 None)."""
        for k in range(0, len(parts) - 1):
            folder = _join_unc(share.unc, parts[k:])
            if is_file(folder + "\\" + shared_config.WORK_PATHS_FILENAME):
                return folder
        return None

    def run(index, share):
        timing_log.log("공유 설정", f"{share.unc} ({', '.join(share.drives)}) 확인 중…")
        started = time.perf_counter()
        try:
            folder, error = search(share), None
        except BaseException as exc:  # 시간 안이면 호출한 쪽에서 그대로 다시 올림 (삼키지 않음)
            folder, error = None, exc
        with lock:
            results[index], errors[index], done[index] = folder, error, True
            late = gave_up[0]
        suffix = " (늦게 응답 — 이미 건너뜀)" if late else ""
        if error is not None:
            if late:
                timing_log.log("공유 설정", f"{share.unc} — 응답 없음으로 건너뛴 뒤 늦게 난 오류: {error!r}")
        elif folder is not None:
            timing_log.log("공유 설정", f"{share.unc} 확인 {timing_log.since(started)} — 찾음: {folder}{suffix}")
        else:
            timing_log.log("공유 설정", f"{share.unc} 확인 {timing_log.since(started)} — 없음{suffix}")

    # daemon 스레드: 서버가 꺼진 공유를 확인하는 중에 앱을 닫아도 프로세스가 그 확인을 기다리지 않음
    # (ThreadPoolExecutor의 작업 스레드는 인터프리터가 끝날 때 기다림)
    threads = [
        threading.Thread(target=run, args=(index, share), name=f"find_config_dirs-{share.unc}", daemon=True)
        for index, share in enumerate(shares)
    ]
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    with lock:
        answered = list(done)  # 이 판단 뒤에 끝난 공유는 '응답 없음' (결과는 읽지 않음)
        if not all(answered):
            gave_up[0] = True
    for index, error in enumerate(errors):
        if answered[index] and error is not None:
            raise error  # 스택 트레이스는 확인 스레드 안의 것 그대로
    found = []
    seen = set()
    for index, share in enumerate(shares):
        if not answered[index]:
            timing_log.log("공유 설정", f"{share.unc} 응답 없음 ({timeout:g}초) — 건너뜀")
            line = f"{', '.join(share.drives)} ({share.unc}) — {timeout:g}초 안에 응답 없음 (서버가 꺼졌거나 느림)"
            if problems is not None:
                problems.append(line)
            continue
        folder = results[index]
        if folder is None:
            continue
        key = paths.unc_key(folder)
        if key not in seen:
            seen.add(key)
            found.append(folder)
    return found


def propose_mapping(work_paths, shares, is_dir=None, progress=None, timeout=None, on_wait=None):
    """작품 경로({작품: Mac 경로})와 연결된 공유로 변환표 짝을 찾습니다 → Proposal.

    작품마다, 공유마다 Mac 경로의 앞부분 k조각을 떼고 나머지를 공유 아래에 붙인 폴더가 열리는지 봅니다
    (앞부분·나머지 모두 한 조각 이상). 나머지가 가장 길게 맞는 후보를 고르고, 같은 깊이로 여러 공유가
    맞으면 후보 여러 개가 됩니다. progress(done, total)가 False를 돌려주면 SetupCancelled.

    먼저 공유마다 루트(share.unc)를 한 번 열어 보고, 열리지 않는 공유(서버가 꺼진 기억된 드라이브 등)는
    건너뛰고 share_problems에 남깁니다 — 작품마다 SMB 시간 초과를 기다리지 않도록. 루트는 timeout초까지만 기다리고
    (on_wait: 기다리는 동안 약 0.1초마다 — GUI 스레드에서 진행 창 처리·취소, False면 SetupCancelled), 응답이 없는
    공유도 건너뛰고 알립니다. 응답한 루트 아래의 작품 폴더는 is_dir로 바로 엽니다.
    """
    is_dir = is_dir or _default_is_dir
    timeout = _timeout(timeout)
    cache = {}

    def opens(share, rest):
        key = (paths.unc_key(share.unc), tuple(part.casefold() for part in rest))
        if key not in cache:
            cache[key] = is_dir(_join_unc(share.unc, rest) if rest else share.unc)
        return cache[key]

    total = max(1, len(shares) + len(work_paths) * len(shares))
    done = 0

    def step():
        nonlocal done
        done += 1
        if progress is not None and progress(done, total) is False:
            raise SetupCancelled()

    reachable = []
    share_problems = []
    for share in shares:
        timing_log.log("변환표 자동 설정", f"{share.unc} ({', '.join(share.drives)}) 여는 중…")
        started = time.perf_counter()
        root_opens = probe(is_dir, share.unc, timeout, on_wait)
        cache[(paths.unc_key(share.unc), ())] = bool(root_opens)
        result = {True: "열림", False: "열리지 않음", None: f"응답 없음 ({timeout:g}초) — 건너뜀"}[root_opens]
        timing_log.log("변환표 자동 설정", f"{share.unc} {timing_log.since(started)} — {result}")
        if root_opens:
            reachable.append(share)
        elif root_opens is None:
            share_problems.append(
                f"{', '.join(share.drives)} ({share.unc}) — 공유 폴더가 {timeout:g}초 안에 응답 없음 (서버가 꺼졌거나 느림)"
            )
        else:
            share_problems.append(
                f"{', '.join(share.drives)} ({share.unc}) — 공유 폴더가 열리지 않음 (서버가 꺼졌거나 연결이 끊김)"
            )
        step()
    total = max(1, len(shares) + len(work_paths) * len(reachable))  # 줄기만 함 → 진행 표시는 앞으로만 감

    matches = {}  # 작품 → [(앞부분 조각 튜플, Share)] (가장 깊게 맞은 것들)
    unmatched = {}
    for work, mac_path in sorted(work_paths.items()):
        try:
            parts = paths._mac_parts(mac_path)
        except paths.PathMapError:
            unmatched[work] = mac_path
            for _share in reachable:
                step()
            continue
        best_depth, best = 0, []
        for share in reachable:
            for k in range(1, len(parts)):
                rest = parts[k:]
                if len(rest) < best_depth:
                    break  # k가 커질수록 나머지가 짧아짐 → 더 깊게 맞을 수 없음
                if opens(share, rest):
                    if len(rest) > best_depth:
                        best_depth, best = len(rest), [(tuple(parts[:k]), share)]
                    else:
                        best.append((tuple(parts[:k]), share))
                    break  # 이 공유에서는 가장 깊은 것을 찾음
            step()
        if best:
            matches[work] = best
        else:
            unmatched[work] = mac_path

    groups = {}  # 앞부분 조각 튜플 → {UNC 키: Candidate}
    for work, found in sorted(matches.items()):
        for prefix, share in found:
            group = groups.setdefault(prefix, {})
            key = paths.unc_key(share.unc)
            candidate = group.get(key)
            if candidate is None:
                candidate = Candidate("/" + "/".join(prefix), share.unc, list(share.drives))
                group[key] = candidate
            candidate.works.append(work)

    pairs = []
    for prefix in sorted(groups):
        candidates = list(groups[prefix].values())
        last = prefix[-1].casefold()
        candidates.sort(key=lambda c: (paths.unc_key(c.unc)[-1] != last, -len(c.works)))  # 안정 정렬
        pairs.append(PairChoice("/" + "/".join(prefix), candidates))
    return Proposal(pairs=pairs, unmatched=unmatched, shares=list(shares), share_problems=share_problems)


def _owner_of_unc(data, mac_prefix, unc):
    """data(변환표 dict)에서 unc를 이미 별칭으로 쓰는 다른 Mac 앞부분 (없으면 None)."""
    key = paths.unc_key(unc)
    mac_key = tuple(paths._mac_parts(mac_prefix))
    for entry in (data or {}).get("shares", []):
        if tuple(paths._mac_parts(entry["mac"])) == mac_key:
            continue
        if any(paths.unc_key(alias) == key for alias in entry["windows"]):
            return entry["mac"]
    return None


def split_mergeable(existing, choices):
    """고른 짝을 하나씩 합쳐 보고 → (합칠 수 있는 짝 [(Mac 앞부분, UNC)], 합칠 수 없는 짝 [(Mac 앞부분, UNC, 이유)]).

    짝마다 existing + 앞에서 합칠 수 있었던 짝에 더해 봅니다(주어진 순서 유지). 합치면 PathMapError가 나는 짝
    (예: Mac이 같은 공유를 /Volumes/x와 /Volumes/x-1로 연결해 한 UNC가 두 Mac 앞부분에 맞음)은 이유와 함께
    rejected로 보냅니다.
    """
    ok, rejected = [], []
    merged = existing  # existing + 지금까지 합칠 수 있었던 짝
    for mac_prefix, unc in choices:
        try:
            merged_next = merge_path_map(merged, [(mac_prefix, unc)])
        except paths.PathMapError as exc:
            owner = _owner_of_unc(merged, mac_prefix, unc)
            if owner is not None:
                reason = (
                    f"같은 Windows 주소({unc})가 이미 다른 Mac 경로({owner})에 쓰여 있어 넣을 수 없음 — "
                    "작품 경로를 Mac에서 같은 경로로 맞추세요"
                )
            else:
                reason = f"넣으면 변환표 형식 오류가 남: {exc}"
            rejected.append((mac_prefix, unc, reason))
        else:
            ok.append((mac_prefix, unc))
            merged = merged_next
    return ok, rejected


def has_additions(existing, proposal):
    """기본 선택 중 합칠 수 있는 짝으로 기존 변환표가 달라지는지 (아니면 시작할 때 창을 띄우지 않음).

    합칠 수 없는 짝(split_mergeable의 rejected)은 세지 않습니다 — 그 짝 때문에 시작할 때마다 창이 뜨지 않도록.
    """
    ok, _rejected = split_mergeable(existing, proposal.ordered_default_choices())
    if not ok:
        return False
    return merge_path_map(existing, ok) != existing


def read_existing(config_dir):
    """기존 path_map.json → (내용 dict 또는 None, 읽을 수 없는 이유 또는 None).

    파일이 없으면(FileNotFoundError) (None, None). JSON·글자 인코딩(UTF-8이 아님)·형식 오류(기본 파일의
    '여기에_붙여넣기' 포함)는 (None, 이유) — 저장할 때 백업 후 새로 만듭니다. 그 밖의 OSError(NAS가 잠깐 끊김,
    권한 등)는 그대로 올립니다: '파일 없음'으로 보고 백업 없이 덮어쓰지 않도록.
    """
    path = os.path.join(config_dir, paths.PATH_MAP_FILENAME)
    try:
        with open(path, encoding="utf-8-sig") as fh:  # 메모장이 붙이는 BOM 허용
            data = json.load(fh)
        paths.PathMap.from_dict(data, path)
    except FileNotFoundError:
        return None, None
    except ValueError as exc:  # JSON 오류, UnicodeDecodeError(CP949·UTF-16 등)
        return None, f"변환표를 읽지 못했습니다: {path}\n{exc}"
    except paths.PathMapError as exc:
        return None, str(exc)
    return data, None


def merge_path_map(existing, chosen):
    """기존 변환표(dict 또는 None)에 고른 짝 [(Mac 앞부분, UNC)]을 합친 새 dict. 기존 항목은 지우지 않습니다.

    같은 Mac 앞부분이 이미 있으면 이 PC의 UNC가 그 항목의 별칭에 없을 때만 뒤에 덧붙입니다(첫 주소 유지).
    결과는 PathMap.from_dict로 검증합니다(틀리면 PathMapError).
    """
    data = copy.deepcopy(existing) if existing else {"version": paths.PATH_MAP_VERSION, "shares": []}
    shares = data.setdefault("shares", [])
    for mac_prefix, unc in chosen:
        mac_key = tuple(paths._mac_parts(mac_prefix))
        entry = next((e for e in shares if tuple(paths._mac_parts(e["mac"])) == mac_key), None)
        if entry is None:
            shares.append({"mac": mac_prefix, "windows": [unc]})
        elif all(paths.unc_key(alias) != paths.unc_key(unc) for alias in entry["windows"]):
            entry["windows"].append(unc)
    paths.PathMap.from_dict(data, "자동 설정 결과")
    return data


def save_path_map(config_dir, data, backup_existing):
    """path_map.json을 씁니다 → 백업 경로 또는 None. 실패는 OSError로 올립니다.

    backup_existing이면 쓰기 전에 기존 파일을 path_map.json.bak-<YYYYMMDD-HHMMSS>로 복사합니다.
    쓰기는 원자적입니다: 같은 폴더의 임시 파일에 다 쓴 뒤 os.replace로 바꿔치기하므로,
    쓰다가 실패해도(NAS 연결 끊김, 디스크 가득 참, 권한 해제 등) 원래 파일은 그대로 남습니다.
    """
    path = os.path.join(config_dir, paths.PATH_MAP_FILENAME)
    backup = None
    if backup_existing and os.path.exists(path):
        backup = f"{path}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
    temp = None
    try:
        fd, temp = tempfile.mkstemp(dir=config_dir, prefix=f"{paths.PATH_MAP_FILENAME}.tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temp, path)
    except OSError as exc:
        notes = []
        if temp is not None:
            try:
                os.remove(temp)
            except OSError:
                notes.append(f"지우지 못한 임시 파일이 남았습니다: {temp}")
        if backup:
            notes.append(f"쓰기 전에 만든 백업: {backup}")
        if notes:
            raise OSError(str(exc) + "".join(f"\n({note})" for note in notes)) from exc
        raise
    return backup
