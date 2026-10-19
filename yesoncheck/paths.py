"""경로 변환: 공유 설정에 저장된 Mac 경로 ↔ 이 PC에서 여는 경로.

공유 설정(work_paths.json, OCR 결과·주석 파일의 영상 경로)에는 Mac 경로를 쓴다.
Windows에서는 공유 설정 폴더의 path_map.json("Mac 경로 앞부분 ↔ UNC" 표)으로 바꿔서 연다.
UNC(\\\\서버\\공유)는 PC마다 다른 드라이브 문자와 상관없이 같으므로, 드라이브 문자로 고른 경로도
먼저 UNC로 바꾼 뒤 표와 맞춘다. Mac에서는 공유를 제자리가 아닌 곳에 붙인 Mac에서만 바꾼다: 이 Mac의 자동 연결 설정·
fstab으로 공유가 붙은 곳을 찾아(mac_mounts.MountMap, activate_mount_map) 공유 설정의 앞부분(공유 설정 폴더·path_map.json의
"mac")이 이 Mac에 없을 때 그곳을 열고, 그 아래 경로는 공유 설정의 앞부분으로 되돌려 적는다. 공유를 모두 제자리에 붙인
Mac(기준 Mac)은 예전과 같다.
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

# GetDriveTypeW 반환값
_DRIVE_NO_ROOT_DIR = 1  # 지금 없는 드라이브 문자 (끊긴 기억된 네트워크 연결, 뽑힌 USB 등)
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4


class PathMapError(Exception):
    """변환표가 없거나 틀렸거나, 경로를 변환표로 바꿀 수 없을 때."""


class NotNetworkDriveError(PathMapError):
    """drive_to_unc: 드라이브 문자가 네트워크 드라이브가 아님 (로컬 디스크이거나 없는 드라이브)."""


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


def unc_key(unc_path):
    """UNC 비교 키: 대소문자·구분자·한글 정규화(NFC/NFD) 차이를 없앤 조각 튜플. UNC가 아니면 PathMapError."""
    return tuple(_fold(_unc_parts(unc_path)))


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
        alias_owner = {}  # 접은 UNC 별칭 → 처음 나온 항목 번호 (같은 공유가 두 Mac 경로에 걸리면 Windows → Mac이 모호함)
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
            for alias, parts in zip(windows, unc_parts):
                folded = tuple(_fold(parts))
                owner = alias_owner.setdefault(folded, index)
                if owner != index:
                    fail(
                        f'{where}: "windows" 주소 {alias!r}이(가) {owner}번째 항목에도 있습니다 '
                        "(대소문자·/·한글 정규화 차이는 같은 주소로 봄). 한 공유 주소는 한 Mac 경로에만 적으세요"
                    )
            shares.append((mac_parts, unc_parts))
        return cls(shares, source)

    @classmethod
    def load(cls, config_dir):
        path = os.path.join(config_dir, PATH_MAP_FILENAME)
        if not os.path.isfile(path):
            raise PathMapError(
                f"변환표 파일이 없습니다: {path}\n"
                "Windows에서 작품 경로를 열려면 공유 설정 폴더에 path_map.json이 있어야 합니다 "
                "(내부 문서 저장소(yesoncheck-internal)의 docs/windows-deploy.md 참고)."
            )
        try:
            with open(path, encoding="utf-8-sig") as fh:  # 메모장이 붙이는 BOM 허용
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

    def with_preferred_aliases(self, share_uncs):
        """이 PC에 연결된 공유(share_uncs)와 서버·공유 이름이 같은 별칭을 각 항목의 앞으로 옮긴 새 PathMap.

        mac_to_windows는 첫 별칭을 쓰므로, 같은 공유를 PC마다 다른 주소(IP·서버 이름)로 연결해도 각 PC는 자기
        드라이브가 연결된 주소를 엽니다(맞는 것이 없으면 원래 첫 주소). 나머지 순서는 유지하고(안정 정렬),
        windows_to_mac은 모든 별칭을 그대로 씁니다. path_map.json은 바꾸지 않습니다.
        """
        connected = {tuple(_fold(_unc_parts(unc)[:2])) for unc in share_uncs}
        shares = []
        for mac_prefix, uncs in self.shares:
            ordered = sorted(uncs, key=lambda alias: tuple(_fold(alias[:2])) not in connected)
            shares.append((mac_prefix, ordered))
        return PathMap(shares, self.source)

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


def _drive_type(drive):
    """GetDriveTypeW: 'Z:' → 드라이브 종류(_DRIVE_* 값) (Windows 전용)."""
    import ctypes
    from ctypes import wintypes

    func = ctypes.WinDLL("kernel32").GetDriveTypeW
    func.argtypes = [wintypes.LPCWSTR]
    func.restype = wintypes.UINT
    return func(drive + "\\")


def _wnet_get_connection(drive):
    """WNetGetConnectionW: 'Z:' → (반환값, 원격 이름 '\\\\서버\\공유') (Windows 전용)."""
    import ctypes
    from ctypes import wintypes

    func = ctypes.WinDLL("mpr").WNetGetConnectionW
    func.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    func.restype = wintypes.DWORD
    size = wintypes.DWORD(512)
    while True:
        buffer = ctypes.create_unicode_buffer(size.value)
        result = func(drive, buffer, ctypes.byref(size))
        if result != _ERROR_MORE_DATA:
            return result, buffer.value
        # ERROR_MORE_DATA: size가 필요한 길이로 바뀌어 있음 → 다시


def _remote_name_of_drive(drive):
    """'Z:' → '\\\\서버\\공유'. 네트워크 드라이브가 아니면 None (Windows 전용).

    드라이브 종류를 먼저 보고 로컬 디스크(고정·이동식·CD 등)는 WNetGetConnectionW를 부르지 않는다:
    네트워크 공급자가 여럿인 PC에서는 로컬 디스크에도 1203(ERROR_NO_NET_OR_BAD_PATH)·1222(ERROR_NO_NETWORK)
    같은 값을 돌려주는데, path_key는 모든 경로 비교·썸네일 키에 쓰이므로 여기서 오류가 나면 안 된다.
    """
    drive_type = _drive_type(drive)
    if drive_type not in (_DRIVE_REMOTE, _DRIVE_NO_ROOT_DIR):
        return None
    result, remote = _wnet_get_connection(drive)
    if result in (_NO_ERROR, _ERROR_CONNECTION_UNAVAIL):
        return remote or None
    if result == _ERROR_NOT_CONNECTED:
        return None
    if drive_type == _DRIVE_NO_ROOT_DIR:
        # 지금 없는 드라이브 문자이고 기억된 네트워크 연결도 아님 → 네트워크 드라이브가 아님
        print(f"{drive} 드라이브가 없고 기억된 네트워크 연결도 아닙니다 (WNetGetConnectionW {result})")
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
        raise NotNetworkDriveError(
            f"{drive.upper()}는 네트워크 드라이브가 아닙니다 (로컬 디스크이거나 없는 드라이브). NAS 공유 폴더를 고르세요: {path}"
        )
    return remote.rstrip("\\") + rest


_active_map = None


def activate(path_map):
    """이 PC에서 쓸 변환표를 정합니다 (None이면 해제)."""
    global _active_map
    _active_map = path_map


def active_map():
    if _active_map is None:
        raise PathMapError(
            "변환표(path_map.json)가 로드되지 않았습니다. 시작할 때 표시된 변환표 오류(또는 공유 설정 오류)를 확인하세요."
        )
    return _active_map


_mount_map = None  # (Mac) 이 Mac에서 공유가 붙은 곳 (mac_mounts.MountMap) — None이면 Mac 경로를 바꾸지 않음


def activate_mount_map(mount_map):
    """(Mac) 이 Mac에서 공유가 붙은 곳(mac_mounts.MountMap)을 정합니다 (None이면 해제). 시작할 때 app.load_mount_map이
    (공유 설정 폴더의 앞부분만), 공유 설정을 읽은 뒤 path_map.json까지 보고 정한 맵으로 _apply_shared_config가 부름."""
    global _mount_map
    _mount_map = mount_map


def active_mount_map():
    return _mount_map


def describe_mac_path(mac_path):
    """(Mac) 공유 설정의 Mac 경로를 이 Mac에서 어디로 여는지 찾아본 내용 (공유 설정·작품 폴더를 열지 못했을 때 오류에 덧붙임)."""
    if _mount_map is None:
        return "이 Mac에서 공유가 붙은 곳(자동 연결 설정·fstab)을 읽지 않았습니다 — 공유 설정의 경로를 그대로 엶."
    return _mount_map.describe(mac_path)


def mac_mount_map_dirs():
    """(Mac) 자동 연결(autofs) 맵 폴더들(실제 경로): 공유가 붙는 곳의 위 — 공유 안이 아님 (video_list.check_gone)."""
    return _mount_map.map_dirs if _mount_map is not None else frozenset()


def _mac_canonical(native_path):
    """(Mac) 제자리가 아닌 곳에 붙은 공유 아래 경로 → 공유 설정의 Mac 경로. 바꿀 것이 없으면 None. 그런 공유·자동 연결
    맵 폴더 아래인데 공유 설정에 적을 경로를 정하지 못하면 PathMapError (mac_mounts)."""
    if _mount_map is None or not native_path:
        return None
    return _mount_map.to_canonical(native_path)


def to_native(mac_path):
    """공유 설정의 Mac 경로 → 이 PC에서 여는 경로 (Windows: UNC).

    Mac: 공유 설정의 앞부분이 이 Mac에 없고 이름이 같은 공유가 다른 곳에 붙어 있으면 그곳 (mac_mounts), 아니면 그대로.
    맞는 공유가 여럿이면 PathMapError.
    """
    if not IS_WINDOWS:
        if _mount_map is None or not mac_path:
            return mac_path
        return _mount_map.to_native(mac_path)
    return active_map().mac_to_windows(mac_path)


def to_canonical(native_path):
    """이 PC의 경로 → 공유 설정에 저장할 Mac 경로. 못 바꾸면 PathMapError.

    Mac: 제자리가 아닌 곳에 붙은 공유 아래면 공유 설정의 앞부분으로 (/System/Volumes/Data/mnt/usadata2/… → /usadata2/…),
    그런 곳인데 정하지 못하면 PathMapError. 그 밖은 예전처럼 /System/Volumes/Data 접두만 뺌.
    """
    if not IS_WINDOWS:
        canonical = _mac_canonical(native_path)
        return canonical if canonical is not None else normalize_mac(native_path)
    return active_map().windows_to_mac(drive_to_unc(native_path))


def to_storage(native_path):
    """OCR 결과·주석 파일에 적을 경로.

    Windows에서 NAS 경로면 Mac 경로로, 로컬 디스크처럼 변환표 밖이면 원래 경로를 그대로 적는다(스펙 2-4).
    Mac: 제자리가 아닌 곳에 붙은 공유 아래면 공유 설정의 Mac 경로로, 그 밖은 원래 경로 그대로 (예전과 같음). 그런 곳인데
    정하지 못하면 PathMapError (/mnt·/System/Volumes/Data/mnt 경로를 적지 않음 — 부른 쪽이 창으로 알림).
    """
    if not native_path:
        return native_path
    if not IS_WINDOWS:
        canonical = _mac_canonical(native_path)
        return canonical if canonical is not None else native_path
    try:
        return to_canonical(native_path)
    except PathMapError:
        return native_path


def from_storage(stored_path):
    """파일에서 읽은 영상 경로 → 이 PC 경로. Mac 경로면 to_native로 (Windows는 변환표, Mac은 다른 곳에 붙인 공유만;
    실패 시 PathMapError)."""
    if not stored_path or not stored_path.startswith("/"):
        return stored_path
    return to_native(stored_path)


def _drive_as_unc(path):
    """(Windows) 구분자를 정리하고 네트워크 드라이브 문자를 UNC로 바꾼 경로 (캐시된 원격 이름 사용). 대소문자는 그대로."""
    text = ntpath.normpath(path.replace("/", "\\"))
    drive, rest = ntpath.splitdrive(text)
    if len(drive) == 2 and drive[1] == ":":
        remote = _cached_remote_name(drive.upper())
        if remote:
            text = remote.rstrip("\\") + rest
    return text


def path_key(path):
    """경로 비교·캐시 키. Windows: 드라이브 문자를 UNC로 바꾸고 구분자·대소문자·한글 정규화 차이를 없앰. Mac: 그대로."""
    if not IS_WINDOWS or not path:
        return path
    return _nfc(_drive_as_unc(path)).casefold()


def same_path(a, b):
    if not a or not b:
        return a == b
    return path_key(a) == path_key(b)


def contains_path(paths_list, path):
    key = path_key(path)
    return any(path_key(p) == key for p in paths_list)


def thumbnail_key(path):
    """썸네일 파일 이름(md5). NAS의 썸네일 폴더는 모든 Mac·Windows PC가 함께 쓰므로 같은 영상은 같은 이름이어야 한다.

    Mac: 경로 그대로의 md5 (기존 값 — NAS에 이미 있는 Mac 썸네일을 계속 씀). 제자리가 아닌 곳에 붙은 공유(mac_mounts)
    아래면 공유 설정의 Mac 경로(to_storage와 같은 것)의 md5 → 다른 Mac·Windows가 만든 썸네일을 그대로 씀. 그런 곳인데
    공유 설정에 적을 경로를 정하지 못하면 예전처럼 경로 그대로의 md5 (그곳마다 한 번 로그).
    Windows: 드라이브 문자를 UNC로 바꾼 뒤(대소문자는 그대로) 변환표로 Mac 경로를 얻어 그 md5 → Mac이 만든
    썸네일을 그대로 찾고, Windows가 만든 썸네일도 Mac이 찾는다. 로컬 디스크, 변환표에 없는 공유, 변환표가
    로드되지 않았을 때는 예전처럼 path_key의 md5 (드라이브 문자와 무관).
    Mac과 나눠 쓰려면 Mac이 여는 영상 경로가 windows_to_mac 결과와 글자까지 같아야 한다: 공유 설정(work_paths.json)의
    작품 경로가 정규 형태(NFC, /System/Volumes/Data 접두 없음, // 없음)여야 함 — 지금의 work_paths.json은 그러함.
    알려진 한계: 경로 어디든 Mac이 NFD로 목록을 받는 한글 이름이 있으면(예: Mac이 SMB로 마운트한 colordata)
    windows_to_mac의 NFC 경로와 달라 나눠 쓰지 못한다 (각자 만든 것은 각자 계속 씀). /usadata2·/usadata3은 SMB가
    아니라 NFS 마운트다.
    """
    if not IS_WINDOWS:
        try:
            canonical = _mac_canonical(path)
        except PathMapError as exc:
            # 공유 설정에 적을 경로를 정하지 못한 곳: 이 Mac 경로로 이름을 지음 (나눠 쓰지 않음 — 그곳마다 한 번 로그,
            # 시작 로그의 [공유] 줄에도 있음). 썸네일 흐름은 그대로 (보기·만들기는 됨)
            _mount_map.log_unshared_thumbnail(path, exc)
            canonical = None
        if canonical is not None:
            return hashlib.md5(canonical.encode("utf-8")).hexdigest()
    if IS_WINDOWS and path and _active_map is not None:
        native = _drive_as_unc(path)
        if native.startswith("\\\\"):
            try:
                mac_path = _active_map.windows_to_mac(native)
            except PathMapError:
                mac_path = None  # 변환표에 없는 공유 → NAS 공유 썸네일이 아님 (아래 예전 이름)
            if mac_path is not None:
                return hashlib.md5(mac_path.encode("utf-8")).hexdigest()
    return hashlib.md5(path_key(path).encode("utf-8")).hexdigest()


def normalize_native(path):
    """Windows: 'Z:/a\\b' 같이 섞인 구분자를 정리. Mac: 그대로."""
    if not IS_WINDOWS or not path:
        return path
    return ntpath.normpath(path)
