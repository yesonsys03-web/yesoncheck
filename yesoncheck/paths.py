"""경로 변환: 공유 설정에 저장된 Mac 경로 ↔ 이 PC에서 여는 경로.

공유 설정(work_paths.json, OCR 결과·주석 파일의 영상 경로)에는 Mac 경로를 쓴다.
Windows에서는 공유 설정 폴더의 path_map.json("Mac 경로 앞부분 ↔ UNC" 표)으로 바꿔서 연다.
UNC(\\\\서버\\공유)는 PC마다 다른 드라이브 문자와 상관없이 같으므로, 드라이브 문자로 고른 경로도
먼저 UNC로 바꾼 뒤 표와 맞춘다. Mac에서는 변환하지 않는다(기존 동작 유지).
"""

import functools
import hashlib
import json
import ntpath
import os
import sys
import unicodedata

IS_WINDOWS = sys.platform == "win32"
PATH_MAP_FILENAME = "path_map.json"
PATH_MAP_VERSION = 1
MAC_FIRMLINK_PREFIX = "/System/Volumes/Data"

# WNetGetConnectionW 반환값
_NO_ERROR = 0
_ERROR_MORE_DATA = 234
_ERROR_CONNECTION_UNAVAIL = 1201  # 기억된 연결이지만 지금은 끊김 (원격 이름은 돌려줌)
_ERROR_NOT_CONNECTED = 2250  # 네트워크 드라이브가 아님 (로컬 디스크 등)


class PathMapError(Exception):
    """변환표가 없거나 틀렸거나, 경로를 변환표로 바꿀 수 없을 때."""


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def normalize_mac(path):
    """Mac 경로 정리: /System/Volumes/Data 접두 제거 (기존 normalize_path와 같은 규칙)."""
    if path and path.startswith(MAC_FIRMLINK_PREFIX + "/"):
        return path[len(MAC_FIRMLINK_PREFIX):]
    return path


def _mac_parts(path):
    if not path or not path.startswith("/"):
        raise PathMapError(f"Mac 절대 경로가 아닙니다: {path!r}")
    return [_nfc(part) for part in normalize_mac(path).split("/") if part]


def _unc_parts(path):
    # 슬래시를 백슬래시로 변환하고 UNC 여부를 먼저 확인.
    # ntpath.normpath는 \\(UNC 접두사)를 제거할 수 있으므로, 정규화 전에 검증한다.
    text = path.replace("/", "\\")
    if not text.startswith("\\\\"):
        raise PathMapError(f"UNC 경로(\\\\서버\\공유...)가 아닙니다: {path!r}")
    # . 또는 .. 세그먼트와 중복 구분자를 정규화
    text = ntpath.normpath(text)
    # 정규화 후 UNC 접두사가 제거되면 복원 (bare server의 경우 ntpath가 제거할 수 있음)
    if not text.startswith("\\\\") and text.startswith("\\"):
        text = "\\" + text
    # 정규화 후 UNC 접두사 확인
    if not text.startswith("\\\\"):
        raise PathMapError(f"UNC 경로(\\\\서버\\공유...)가 아닙니다: {path!r}")
    parts = [_nfc(part) for part in text[2:].split("\\") if part]
    if len(parts) < 2:
        raise PathMapError(f"UNC 경로에 서버와 공유 이름이 모두 있어야 합니다: {path!r}")
    return parts


def _fold(parts):
    return [part.casefold() for part in parts]


class PathMap:
    """path_map.json 내용. shares: [(Mac 앞부분 조각 목록, [UNC 조각 목록, ...]), ...]"""

    def __init__(self, shares, source):
        self.shares = shares
        self.source = source

    @classmethod
    def from_dict(cls, data, source):
        def fail(message):
            raise PathMapError(f"변환표 형식 오류: {message}\n파일: {source}")

        if not isinstance(data, dict):
            fail("최상위가 객체({...})가 아닙니다")
        if data.get("version") != PATH_MAP_VERSION:
            fail(f'"version"이 {PATH_MAP_VERSION}이어야 합니다 (현재: {data.get("version")!r})')
        entries = data.get("shares")
        if not isinstance(entries, list) or not entries:
            fail('"shares" 목록이 비어 있거나 없습니다')
        shares = []
        seen = set()
        for index, entry in enumerate(entries, 1):
            where = f"shares의 {index}번째 항목"
            if not isinstance(entry, dict):
                fail(f"{where}이 객체가 아닙니다")
            mac = entry.get("mac")
            windows = entry.get("windows")
            if not isinstance(mac, str) or not mac.startswith("/") or mac.rstrip("/") != mac:
                fail(f'{where}: "mac"은 끝에 /가 없는 Mac 절대 경로여야 합니다 (현재: {mac!r})')
            if not isinstance(windows, list) or not windows or not all(isinstance(w, str) for w in windows):
                fail(f'{where}: "windows"는 UNC 경로 목록이어야 합니다 (현재: {windows!r})')
            try:
                mac_parts = _mac_parts(mac)
                unc_parts = [_unc_parts(w) for w in windows]
            except PathMapError as exc:
                fail(f"{where}: {exc}")
            key = tuple(mac_parts)
            if key in seen:
                fail(f'{where}: "mac" 값 {mac!r}이(가) 앞 항목과 겹칩니다')
            seen.add(key)
            shares.append((mac_parts, unc_parts))
        return cls(shares, source)

    @classmethod
    def load(cls, config_dir):
        path = os.path.join(config_dir, PATH_MAP_FILENAME)
        if not os.path.isfile(path):
            raise PathMapError(
                f"변환표 파일이 없습니다: {path}\n"
                "Windows에서 작품 경로를 열려면 공유 설정 폴더에 path_map.json이 있어야 합니다 "
                "(docs/windows-deploy.md 참고)."
            )
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise PathMapError(f"변환표를 읽지 못했습니다: {path}\n{exc}") from exc
        return cls.from_dict(data, path)

    def mac_to_windows(self, mac_path):
        parts = _mac_parts(mac_path)
        best = None
        for mac_prefix, uncs in self.shares:
            n = len(mac_prefix)
            if parts[:n] == mac_prefix and (best is None or n > len(best[0])):
                best = (mac_prefix, uncs)
        if best is None:
            raise PathMapError(f"변환표에 없는 경로입니다: {mac_path}\n변환표: {self.source}")
        mac_prefix, uncs = best
        return "\\\\" + "\\".join(uncs[0] + parts[len(mac_prefix):])

    def windows_to_mac(self, unc_path):
        parts = _unc_parts(unc_path)
        folded = _fold(parts)
        best = None
        for mac_prefix, uncs in self.shares:
            for alias in uncs:
                n = len(alias)
                if folded[:n] == _fold(alias) and (best is None or n > best[0]):
                    best = (n, mac_prefix)
        if best is None:
            raise PathMapError(f"변환표에 없는 공유 폴더입니다: {unc_path}\n변환표: {self.source}")
        n, mac_prefix = best
        return "/" + "/".join(mac_prefix + parts[n:])


def _remote_name_of_drive(drive):
    """WNetGetConnectionW: 'Z:' → '\\\\서버\\공유'. 네트워크 드라이브가 아니면 None (Windows 전용)."""
    import ctypes
    from ctypes import wintypes

    func = ctypes.WinDLL("mpr").WNetGetConnectionW
    func.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    func.restype = wintypes.DWORD
    size = wintypes.DWORD(512)
    while True:
        buffer = ctypes.create_unicode_buffer(size.value)
        result = func(drive, buffer, ctypes.byref(size))
        if result == _ERROR_MORE_DATA:
            continue  # size가 필요한 길이로 바뀌어 있음
        if result in (_NO_ERROR, _ERROR_CONNECTION_UNAVAIL):
            return buffer.value or None
        if result == _ERROR_NOT_CONNECTED:
            return None
        raise PathMapError(f"{drive} 드라이브의 연결 정보를 읽지 못했습니다 (WNetGetConnectionW 오류 {result})")


@functools.lru_cache(maxsize=32)
def _cached_remote_name(drive):
    """비교·캐시 키 계산용 (자주 불림). 작품 경로 저장 등은 캐시 없는 drive_to_unc를 씀."""
    return _remote_name_of_drive(drive)


def drive_to_unc(path, resolver=None):
    """Windows 경로를 UNC로: 'Z:\\작품' → '\\\\서버\\공유\\작품'. 이미 UNC면 정리만 합니다.

    resolver(drive) -> 원격 이름 또는 None. 기본은 WNetGetConnectionW (시험에서 바꿔 끼움).
    """
    text = ntpath.normpath(path.replace("/", "\\"))
    if text.startswith("\\\\"):
        return text
    drive, rest = ntpath.splitdrive(text)
    if len(drive) != 2 or drive[1] != ":":
        raise PathMapError(f"드라이브 문자나 UNC로 시작하는 경로가 아닙니다: {path}")
    remote = (resolver or _remote_name_of_drive)(drive.upper())
    if not remote:
        raise PathMapError(
            f"{drive.upper()}는 네트워크 드라이브가 아닙니다 (로컬 디스크). NAS 공유 폴더를 고르세요: {path}"
        )
    return remote.rstrip("\\") + rest


_active_map = None


def activate(path_map):
    """이 PC에서 쓸 변환표를 정합니다 (None이면 해제)."""
    global _active_map
    _active_map = path_map


def active_map():
    if _active_map is None:
        raise PathMapError("변환표(path_map.json)가 로드되지 않았습니다. 시작할 때 표시된 공유 설정 오류를 확인하세요.")
    return _active_map


def to_native(mac_path):
    """공유 설정의 Mac 경로 → 이 PC에서 여는 경로 (Windows: UNC). Mac은 그대로."""
    if not IS_WINDOWS:
        return mac_path
    return active_map().mac_to_windows(mac_path)


def to_canonical(native_path):
    """이 PC의 경로 → 공유 설정에 저장할 Mac 경로. 못 바꾸면 PathMapError."""
    if not IS_WINDOWS:
        return normalize_mac(native_path)
    return active_map().windows_to_mac(drive_to_unc(native_path))


def to_storage(native_path):
    """OCR 결과·주석 파일에 적을 경로.

    Windows에서 NAS 경로면 Mac 경로로, 로컬 디스크처럼 변환표 밖이면 원래 경로를 그대로 적는다(스펙 2-4).
    """
    if not IS_WINDOWS or not native_path:
        return native_path
    try:
        return to_canonical(native_path)
    except PathMapError:
        return native_path


def from_storage(stored_path):
    """파일에서 읽은 영상 경로 → 이 PC 경로. Windows에서 Mac 경로면 변환 (실패 시 PathMapError)."""
    if not IS_WINDOWS or not stored_path or not stored_path.startswith("/"):
        return stored_path
    return to_native(stored_path)


def path_key(path):
    """경로 비교·캐시 키. Windows: 드라이브 문자를 UNC로 바꾸고 구분자·대소문자·한글 정규화 차이를 없앰. Mac: 그대로."""
    if not IS_WINDOWS or not path:
        return path
    text = ntpath.normpath(path.replace("/", "\\"))
    drive, rest = ntpath.splitdrive(text)
    if len(drive) == 2 and drive[1] == ":":
        remote = _cached_remote_name(drive.upper())
        if remote:
            text = remote.rstrip("\\") + rest
    return _nfc(text).casefold()


def same_path(a, b):
    if not a or not b:
        return a == b
    return path_key(a) == path_key(b)


def contains_path(paths_list, path):
    key = path_key(path)
    return any(path_key(p) == key for p in paths_list)


def thumbnail_key(path):
    """썸네일 파일 이름(md5). Mac은 기존과 같은 값, Windows는 드라이브 문자와 무관한 값."""
    return hashlib.md5(path_key(path).encode("utf-8")).hexdigest()


def normalize_native(path):
    """Windows: 'Z:/a\\b' 같이 섞인 구분자를 정리. Mac: 그대로."""
    if not IS_WINDOWS or not path:
        return path
    return ntpath.normpath(path)
