"""(Mac) 이 Mac에서 스튜디오 공유가 붙은 곳 — 자동 연결(autofs) 설정과 /etc/fstab (Qt 없음).

공유 설정(work_paths.json, OCR 결과·주석 파일의 영상 경로)의 Mac 경로는 "공유 설정의 앞부분"으로 시작한다. 앞부분은 모든
Mac에서 같다 (작품 경로에 따라 바뀌지 않음):
- 공유 설정 폴더의 앞부분 /USA_DB (shared_config.MAC_CONFIG_DIR),
- 공유 설정 폴더의 path_map.json "mac" 항목 (/usadata2, /usadata3, /Users/studio01/Desktop/usadata4, /Volumes/colordata —
  Windows가 Mac 공유의 앞부분으로 쓰는 것과 같음),
- 그 밖에 이 Mac에서 제자리가 아닌 곳에 붙은 공유는 /<이름> (기준 Mac의 fstab 모양: /bgfinal, /usadata1 …).

여는 쪽(forward): 앞부분이 이 Mac에 없으면 이름이 그 앞부분의 마지막 이름과 같은 공유 하나를 연다 (예: mac_b — auto_master의
간접 맵 auto_nfs로 붙인 /System/Volumes/Data/mnt/usadata2). 공유의 이름은 마운트 위치(맵 항목)의 마지막 이름과 서버 쪽
경로의 마지막 이름(nfs://203.0.113.3:/data/usadata2 → usadata2)이고, 대소문자를 구분한다 (USADATA2와 usadata2는 다른 이름).
맞는 공유가 여럿이면 고르지 않고 알린다 (그 앞부분 아래를 열면 PathMapError).

되돌리는 쪽(reverse, 이 Mac 경로 → 공유 설정에 적을 경로): 제자리가 아닌 공유(autofs 맵 폴더 아래, fstab net 항목의
/Network/Servers 아래, /System/Volumes/Data에만 있는 fstab 위치)와 없는 앞부분 대신 여는 공유만. 이름이 같은 path_map
항목이 하나면 그것(usadata4 → /Users/studio01/Desktop/usadata4), 아니면 /<이름>. 정하지 못하면(이름이 같은 공유가 여럿,
맵 폴더 아래의 모르는 이름, 공유 설정을 아직 읽지 않음) PathMapError — /mnt·/System/Volumes/Data/mnt 경로를 공유 설정에
적지 않는다. 제자리에 붙은 공유는 바꾸지 않는다 (기준 Mac은 예전과 같음).

시작할 때(read_mount_map, GUI 스레드)는 설정 파일과 /·/System/Volumes/Data의 목록만 본다 (/Users 아래 — ~/Desktop 등 —
는 보지 않음: macOS 개인정보 보호 확인 창이 시작을 막을 수 있음). 그때는 공유 설정 폴더의 앞부분만 정한다. 공유 설정을
읽은 뒤 뒤 스레드에서 with_canonical_roots(path_map의 "mac")로 나머지를 정한다. 공유(NAS) 자체는 열어 보지 않는다: 있는지는
위 폴더의 목록으로 본다. 설정 파일을 읽다 난 문제는 problems에 남긴다 (시작 로그·공유 설정 오류 창).
"""

import os
import posixpath
import re
from dataclasses import dataclass

from yesoncheck.paths import MAC_FIRMLINK_PREFIX, PathMapError, normalize_mac

AUTO_MASTER = "/etc/auto_master"
FSTAB = "/etc/fstab"
# 설정 파일·폴더를 찾는 기준 (시험은 conftest가 없는 폴더로 바꿈 — 이 Mac의 /etc를 읽지 않게)
DEFAULT_ROOT = "/"
# auto_master에서 보지 않는 맵: 이 Mac의 공유 위치와 상관없음 (서버 목록·빈 맵·홈 폴더). -static·-fstab은 fstab을 읽을 때 씀
_SKIPPED_MAPS = ("-hosts", "-null", "auto_home")
# fstab에서 보는 종류 (서버 쪽 위치가 smb://·https:// 같은 URL이면 종류와 상관없이 봄)
_NETWORK_TYPES = ("nfs", "smbfs", "afpfs", "url")
# fstab에서 말없이 넘기는 로컬 디스크 종류 (그 밖의 모르는 종류는 notes에 남김)
_LOCAL_TYPES = ("apfs", "hfs", "msdos", "exfat", "ntfs", "ufs", "cd9660", "udf", "devfs", "tmpfs", "lifs", "fdesc", "none")
# 서버 쪽 위치의 비밀번호 (//사용자:비밀번호@서버) — 로그·창에는 가림
_PASSWORD = re.compile(r"(//[^/\s:@]*):[^@\s]*@")
_UNSHARED = "이 아래 영상은 OCR 결과·주석을 저장하지 못하고 썸네일은 다른 PC와 나눠 쓰지 않음"


def _redact(text):
    return _PASSWORD.sub(r"\1:***@", text)


@dataclass(frozen=True)
class Mount:
    """이 Mac에 공유가 붙는 곳 하나."""

    path: str  # 이 Mac에서 여는 경로 (예: /System/Volumes/Data/mnt/usadata2, /USA_DB)
    real: str  # 실제 경로 (autofs·net은 맵 폴더의 realpath 아래, fstab 위치는 path 그대로)
    names: tuple  # 이름 (서버 쪽 경로의 마지막 이름, 맵 항목·마운트 위치의 마지막 이름) — 대소문자 구분
    source: str  # 찾은 곳: 간접 맵 이름(auto_nfs) 또는 "fstab"
    remote: str  # 서버 쪽 위치 (로그용, 비밀번호는 가림)
    displaced: bool  # 제자리가 아닌 곳 (autofs 맵 폴더 아래, /Network/Servers 아래, Data 볼륨에만 있는 fstab 위치)

    def text(self):
        return f"{self.path} ({self.source}: {self.remote})"

    def forms(self):
        """이 공유 아래 경로가 이 Mac에서 보일 수 있는 앞부분 (/System/Volumes/Data 접두를 뺀 /mnt/… 포함)."""
        return list(dict.fromkeys((self.path, self.real, normalize_mac(self.path), normalize_mac(self.real))))


def first_root(path):
    """경로의 맨 앞 이름까지: /Volumes/<이름>/… → /Volumes/<이름>, 그 밖의 /<이름>/… → /<이름>. 아니면 None."""
    if not path or not path.startswith("/"):
        return None
    parts = path.split("/")
    if parts[1] == "Volumes":
        return f"/Volumes/{parts[2]}" if len(parts) > 2 and parts[2] else None
    return f"/{parts[1]}" if parts[1] else None


def _within(path, prefix):
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _local(root, path):
    """이 Mac의 절대 경로 path를 root 기준으로 (root가 /이면 그대로, 시험은 tmp 폴더)."""
    return os.path.join(root, path.lstrip("/"))


def _exists(path):
    """path가 있는지 — 위 폴더의 목록으로 (path 자체는 열어 보지 않음: 공유가 붙는 곳이면 서버가 응답하지 않을 때 멈출
    수 있음). 위 폴더를 읽지 못하면 OSError·ValueError."""
    parent, name = os.path.split(path.rstrip("/"))
    if not name:
        return True
    try:
        with os.scandir(parent) as entries:
            return any(entry.name == name for entry in entries)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _config_lines(path, problems, missing_ok=False, inline_comments=True):
    """자동 연결 설정·fstab 파일의 줄 → [토큰 목록]: 빈 줄·주석은 빼고 끝의 \\로 이어진 줄은 합침. 주석은 #부터
    (inline_comments가 아니면 줄 맨 앞의 #만 — fstab의 smb 비밀번호에 #이 들어갈 수 있음). 읽지 못하면 problems에 남기고
    None (missing_ok이고 파일이 없으면 빈 목록)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError as exc:
        if missing_ok:
            return []
        problems.append(f"읽지 못함: {path} ({type(exc).__name__}: {exc})")
        return None
    except (OSError, ValueError) as exc:
        problems.append(f"읽지 못함: {path} ({type(exc).__name__}: {exc})")
        return None
    lines = []
    pending = ""
    for raw in text.splitlines():
        if inline_comments:
            raw = raw.split("#", 1)[0]
        elif raw.lstrip().startswith("#"):
            raw = ""
        line = pending + raw
        pending = ""
        if line.rstrip().endswith("\\"):
            pending = line.rstrip()[:-1] + " "
            continue
        if line.split():
            lines.append(line.split())
    if pending.split():
        lines.append(pending.split())
    return lines


def _remote_parts(remote):
    """서버 쪽 위치 → (서버, 경로): 'server:/data/x', 'nfs://server:/data/x', 'nfs://server/data/x', '//user@server/share',
    'smb://user@server/share', 'afp://server/share'. 이런 모양이 아니면 None."""
    if "://" in remote:
        host, _, path = remote.split("://", 1)[1].partition("/")
    elif remote.startswith("//"):
        host, _, path = remote[2:].partition("/")
    elif ":/" in remote:
        host, _, path = remote.partition(":")
    else:
        return None
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    if not host:
        return None
    return host, "/" + path.strip("/")


def _remote_name(remote):
    parts = _remote_parts(remote) if remote else None
    return posixpath.basename(parts[1]) if parts else ""


def _names(*names):
    return tuple(dict.fromkeys(name for name in names if name))


def _unescape_fstab(token):
    """fstab의 8진수 이스케이프(\\040 = 공백)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), token)


def read_mount_map(auto_master=None, fstab=None, root=None, config_dir=None):
    """(시작할 때) 이 Mac의 자동 연결 설정(auto_master와 그것이 가리키는 간접 맵 파일)과 fstab을 읽어 MountMap을 만듭니다.
    공유 설정 폴더의 앞부분(config_dir — 기본 shared_config.MAC_CONFIG_DIR — 의 /USA_DB)만 정합니다.

    root: 설정 파일(맵 이름)·폴더를 찾는 기준 (기본 DEFAULT_ROOT, 시험은 tmp 폴더). auto_master·fstab: 파일 경로
    (기본 root 아래 /etc/auto_master·/etc/fstab). auto_master의 +auto_master(디렉터리 서비스)·-hosts·-null·auto_home(/home)
    줄은 보지 않고, 직접 맵·모르는 줄은 notes에. fstab의 net 항목은 -fstab 맵 폴더(/Network/Servers) 아래 <서버><경로>에,
    그 밖의 항목은 /- -static으로 그 위치에 붙음 — 맨 위 위치(/USA_DB)가 /System/Volumes/Data 아래에만 있으면 그곳
    (synthetic 링크가 없는 Mac). 보는 폴더는 autofs 맵 폴더의 경로와 /·/System/Volumes/Data의 목록뿐.
    """
    if config_dir is None:
        from yesoncheck import shared_config

        config_dir = shared_config.MAC_CONFIG_DIR
    root = root or DEFAULT_ROOT
    auto_master = auto_master or _local(root, AUTO_MASTER)
    fstab = fstab or _local(root, FSTAB)
    problems = []
    notes = []
    mounts = []
    map_dirs = []
    static = False
    fstab_dir = None
    lines = _config_lines(auto_master, problems)
    for tokens in lines or ():
        mount_point = tokens[0]
        map_name = tokens[1] if len(tokens) > 1 else ""
        if mount_point.startswith("+") or map_name in _SKIPPED_MAPS or mount_point == "/home":
            continue
        if map_name == "-static":
            static = True  # fstab의 net이 아닌 항목을 그 위치에 붙임
            continue
        if map_name == "-fstab":
            fstab_dir = mount_point  # fstab의 net 항목을 이 폴더 아래 <서버><경로>에 붙임
            continue
        if mount_point == "/-" or not map_name or map_name.startswith("-") or not mount_point.startswith("/"):
            notes.append(f"{auto_master}: 보지 않은 줄 (간접 맵이 아님): {_redact(' '.join(tokens))}")
            continue
        try:
            _read_indirect_map(root, mount_point, map_name, mounts, map_dirs, problems, notes)
        except (OSError, ValueError) as exc:
            problems.append(f"{auto_master}: 맵을 읽지 못함: {mount_point} {map_name} ({type(exc).__name__}: {exc})")
    if lines is not None:
        _read_fstab(root, fstab, static, fstab_dir, mounts, map_dirs, problems, notes)
    config_root = first_root(config_dir)
    return MountMap(root, auto_master, fstab, mounts, map_dirs, problems, notes,
                    roots=[config_root] if config_root else [], loaded=False)


def _read_indirect_map(root, mount_point, map_name, mounts, map_dirs, problems, notes):
    """간접 맵 파일의 항목마다 <맵 폴더>/<항목 이름>에 붙는 공유. 맵 폴더는 내용과 상관없이 map_dirs에."""
    map_file = _local(root, map_name) if map_name.startswith("/") else _local(root, "/etc/" + map_name)
    map_dir = _local(root, mount_point.rstrip("/"))
    map_dir_real = os.path.realpath(map_dir)  # autofs 맵 폴더 자체는 이 Mac이 답함 (서버를 열지 않음)
    map_dirs += [map_dir, map_dir_real]
    if os.path.isfile(map_file) and os.access(map_file, os.X_OK):
        notes.append(f"{map_file}: 실행 맵이라 보지 않음 (항목을 알 수 없음 — {map_dir} 아래는 저장할 수 없음)")
        return
    for tokens in _config_lines(map_file, problems) or ():
        key = tokens[0]
        if key.startswith("+") or key == "*" or "/" in key:
            notes.append(f"{map_file}: 보지 않은 항목 (포함·와일드카드·여러 단계 — {map_dir} 아래 그 이름은 저장할 수 없음): "
                         f"{key}")
            continue
        remote = tokens[-1] if len(tokens) > 1 and not tokens[-1].startswith("-") else ""
        remote = remote.replace("&", key)  # 위치의 &는 항목 이름 (autofs 규칙)
        mounts.append(Mount(os.path.join(map_dir, key), os.path.join(map_dir_real, key),
                            _names(_remote_name(remote), key), map_name, _redact(remote), displaced=True))


def _read_fstab(root, fstab, static, fstab_dir, mounts, map_dirs, problems, notes):
    """fstab의 네트워크 공유 항목마다 붙는 곳 (파일이 없으면 없음 — 대부분의 Mac). 맨 위 위치(/<이름>)만 /와
    /System/Volumes/Data의 목록으로 어디에 있는지 봄 — 그 밖의 위치(/Volumes/…, /Users/…)는 열어 보지 않고 적힌 대로."""
    listings = {}

    def present(path):
        folder, name = os.path.split(path)
        if folder not in listings:
            try:
                with os.scandir(folder) as entries:
                    listings[folder] = {entry.name for entry in entries}
            except (FileNotFoundError, NotADirectoryError):
                listings[folder] = set()
        return name in listings[folder]

    for tokens in _config_lines(fstab, problems, missing_ok=True, inline_comments=False) or ():
        tokens = [_unescape_fstab(token) for token in tokens]
        line = _redact(" ".join(tokens))
        if len(tokens) < 3:
            notes.append(f"{fstab}: 보지 않은 줄 (항목이 모자람): {line}")
            continue
        if any("\x00" in token for token in tokens):
            problems.append(f"{fstab}: 경로에 쓸 수 없는 문자(NUL)가 있어 보지 않음: {line!r}")
            continue
        remote, mount_point, fs_type = tokens[:3]
        options = tokens[3].split(",") if len(tokens) > 3 else []
        if remote.startswith(("LABEL=", "UUID=")) or fs_type in _LOCAL_TYPES:
            continue  # 로컬 디스크
        if fs_type not in _NETWORK_TYPES and "://" not in remote:
            notes.append(f"{fstab}: 모르는 종류({fs_type})라 보지 않음: {line}")
            continue
        parts = _remote_parts(remote)
        if parts is None:
            notes.append(f"{fstab}: 서버 쪽 위치를 알 수 없어 보지 않음: {line}")
            continue
        server, export = parts
        try:
            if "net" in options:
                if fstab_dir is None:
                    notes.append(f"{fstab}: net 항목인데 auto_master에 -fstab 맵이 없어 붙지 않음 — 보지 않음: {line}")
                    continue
                base = _local(root, fstab_dir.rstrip("/"))
                base_real = os.path.realpath(base)
                tail = "/" + server + (export if export != "/" else "")
                # -fstab 맵 폴더와 그 아래 공유까지의 폴더(/Network/Servers/<서버>/…)는 자동 연결이 만드는 폴더 — 공유 안이 아님
                map_dirs += [base, base_real] + [base_real + tail[:i] for i in range(1, len(tail)) if tail[i] == "/"]
                mounts.append(Mount(base + tail, base_real + tail, _names(posixpath.basename(export)), "fstab",
                                    _redact(remote), displaced=True))
                continue
            if not static:
                notes.append(f"{fstab}: auto_master에 /- -static이 없어 붙지 않음 — 보지 않음: {line}")
                continue
            if not mount_point.startswith("/") or mount_point.rstrip("/") == "":
                notes.append(f"{fstab}: 마운트 위치가 절대 경로가 아님 — 보지 않음: {line}")
                continue
            mount_point = mount_point.rstrip("/")
            names = _names(posixpath.basename(export), posixpath.basename(mount_point))
            here = _local(root, mount_point)
            if mount_point.count("/") == 1:  # 맨 위 위치: 링크가 없으면 Data 볼륨에만 있음
                data = _local(root, MAC_FIRMLINK_PREFIX + mount_point)
                if present(here):
                    path, displaced = here, False
                elif present(data):
                    path, displaced = data, True
                else:
                    notes.append(f"{fstab}: 마운트 위치가 이 Mac에 없음 — 보지 않음: {mount_point} ({_redact(remote)})")
                    continue
            else:
                path, displaced = here, False
            mounts.append(Mount(path, path, names, "fstab", _redact(remote), displaced))
        except (OSError, ValueError) as exc:
            problems.append(f"{fstab}: 마운트 위치를 확인하지 못함: {line} ({type(exc).__name__}: {exc})")


def _reverse_root(mount, path_map_roots):
    """제자리가 아닌 공유를 되돌릴 앞부분: 이름이 같은(대소문자 구분) path_map 항목이 하나면 그것, 아니면 /<이름>
    (이름은 서버 쪽 경로의 마지막 이름이 먼저)."""
    matches = [root for root in path_map_roots if posixpath.basename(root) in mount.names]
    if len(matches) == 1:
        return matches[0]
    return "/" + mount.names[0]


class MountMap:
    """이 Mac에서 공유가 붙은 곳 (read_mount_map이 만들고 with_canonical_roots가 마저 정함). paths.activate_mount_map으로
    정하면 Mac의 경로 변환이 씀.

    roots: 공유 설정의 앞부분 (정한 순서). loaded: path_map.json까지 보고 정했는지 (아니면 되돌리는 경로가 없음).
    forward: 이 Mac에 없는 앞부분 → 대신 여는 공유(Mount). ambiguous: 맞는 공유가 여럿이라 바꾸지 않는 앞부분 → [Mount].
    reverse: [(이 Mac의 앞부분, 공유 설정의 앞부분)] 긴 것부터. unmapped: [(이 Mac의 앞부분, 까닭)] 공유 설정에 적을 경로를
    정하지 못하는 곳 (긴 것부터). map_dirs: autofs 맵 폴더(실제 경로 포함) — 공유 안이 아님 (video_list.check_gone).
    """

    def __init__(self, root, auto_master, fstab, mounts, map_dirs, problems, notes, roots, loaded,
                 path_map_roots=()):
        self.root = root
        self.auto_master = auto_master
        self.fstab = fstab
        self.mounts = list(mounts)
        self.map_dirs = frozenset(map_dirs)
        self.problems = list(problems)
        self.notes = list(notes)
        self.loaded = loaded
        self.path_map_roots = list(path_map_roots)
        self.roots = list(dict.fromkeys(roots))
        self.forward = {}
        self.ambiguous = {}
        self.reverse = []
        self.reverse_roots = []  # (Mount, 공유 설정의 앞부분) — 로그용
        self.unmapped = []
        self._unshared_logged = set()  # 썸네일을 나눠 쓰지 못한다고 로그에 남긴 곳
        self._resolve_forward()
        self._resolve_reverse()

    def has_displaced(self):
        return any(mount.displaced for mount in self.mounts)

    def _resolve_forward(self):
        for root in self.roots:
            name = posixpath.basename(root)
            here = _local(self.root, root)
            candidates = []
            for mount in self.mounts:
                if name in mount.names and mount.path != here and all(m.real != mount.real for m in candidates):
                    candidates.append(mount)
            if not candidates:
                continue  # 대신 열 공유가 없음 → 이 Mac에 있는지 볼 필요도 없음
            try:
                if _exists(here):
                    continue  # 이 Mac에 있음 → 그대로 엶
            except (OSError, ValueError) as exc:
                self.problems.append(f"이 Mac에 있는지 확인하지 못해 바꾸지 않음: {root} ({type(exc).__name__}: {exc})")
                continue
            if len(candidates) == 1:
                self.forward[root] = candidates[0]
            else:
                self.ambiguous[root] = candidates

    def _resolve_reverse(self):
        reverse = []
        unmapped = []
        reason = "자동 연결 맵 폴더 아래의 맵에 없는 이름 (와일드카드·실행 맵이면 모든 이름)"
        for map_dir in sorted(self.map_dirs):
            unmapped += [(form, reason) for form in dict.fromkeys((map_dir, normalize_mac(map_dir)))]
        targets = {}
        for root, mount in self.forward.items():
            targets.setdefault(mount, root)
        for mount in self.mounts:
            if not mount.displaced and mount not in targets:
                continue  # 제자리에 붙은 공유: 바꾸지 않음
            if not self.loaded:
                reason = "공유 설정(path_map.json)을 아직 읽지 않아 공유 설정에 적을 경로를 정하지 않음"
                unmapped += [(form, reason) for form in mount.forms()]
                continue
            root = targets.get(mount) or _reverse_root(mount, self.path_map_roots)
            if root in self.ambiguous:
                reason = f"{root}에 맞는 공유가 여럿 — " + ", ".join(m.text() for m in self.ambiguous[root])
                unmapped += [(form, reason) for form in mount.forms()]
                continue
            self.reverse_roots.append((mount, root))
            reverse += [(form, root) for form in mount.forms() if form != root]
        self.reverse = sorted(reverse, key=lambda item: len(item[0]), reverse=True)
        self.unmapped = sorted(unmapped, key=lambda item: len(item[0]), reverse=True)

    def with_canonical_roots(self, path_map_roots):
        """(공유 설정을 읽은 뒤, 뒤 스레드) path_map.json의 "mac"(공유 설정의 앞부분)까지 보고 정한 새 MountMap (이 맵은
        그대로). 앞부분: 공유 설정 폴더의 앞부분, path_map 항목, 제자리가 아닌 공유의 되돌릴 앞부분(/<이름>) 순서."""
        path_map_roots = list(dict.fromkeys(root.rstrip("/") for root in path_map_roots if root.startswith("/")))
        displaced_roots = [_reverse_root(mount, path_map_roots) for mount in self.mounts if mount.displaced]
        return MountMap(self.root, self.auto_master, self.fstab, self.mounts, self.map_dirs, self.problems, self.notes,
                        roots=self.roots + path_map_roots + displaced_roots, loaded=True, path_map_roots=path_map_roots)

    def _root_of(self, canonical):
        """canonical이 속한 앞부분 (아는 앞부분 중 가장 긴 것, 없으면 맨 앞 이름까지)."""
        known = [root for root in self.roots if _within(canonical, root)]
        return max(known, key=len) if known else first_root(canonical)

    def to_native(self, canonical):
        """공유 설정의 Mac 경로 → 이 Mac에서 여는 경로 (바꿀 것이 없으면 그대로). 맞는 공유가 여럿이면 PathMapError."""
        root = self._root_of(canonical)
        mount = self.forward.get(root)
        if mount is not None:
            return mount.path + canonical[len(root):]
        if root in self.ambiguous:
            raise PathMapError(f"이 Mac에서 열 곳을 정하지 못했습니다: {canonical}\n{self.describe(canonical)}")
        return canonical

    def to_canonical(self, native):
        """이 Mac의 경로 → 공유 설정에 적을 Mac 경로. 바꿀 것이 없으면(제자리에 붙은 공유·로컬 디스크) None.
        제자리가 아닌 공유·자동 연결 맵 폴더 아래인데 정하지 못하면 PathMapError."""
        for form, root in self.reverse:
            if _within(native, form):
                return root + native[len(form):]
        for form, reason in self.unmapped:
            if _within(native, form):
                raise PathMapError(f"공유 설정에 적을 Mac 경로를 정하지 못했습니다: {native}\n{reason}")
        return None

    def log_unshared_thumbnail(self, native, error):
        """(paths.thumbnail_key) 공유 설정에 적을 경로를 정하지 못한 곳의 썸네일은 이 Mac 경로로 이름을 지음 — 그곳마다 한 번
        로그에 (다른 PC와 나눠 쓰지 않음)."""
        area = next((form for form, _reason in self.unmapped if _within(native, form)), native)
        if area in self._unshared_logged:
            return
        self._unshared_logged.add(area)
        print(f"[공유] {area} 아래 영상의 썸네일은 이 Mac 경로로 이름을 지어 다른 PC와 나눠 쓰지 않음: {error}", flush=True)

    def describe(self, canonical):
        """canonical(공유 설정의 Mac 경로)을 이 Mac에서 어디로 여는지 찾아본 내용 — 열지 못했을 때 오류에 덧붙임."""
        lines = [f"이 Mac에서 공유가 붙은 곳 찾기 (자동 연결 설정 {self.auto_master}, {self.fstab}):"]
        root = self._root_of(canonical)
        if root is None:
            lines.append(f"  {canonical}: /로 시작하지 않아 바꾸지 않음")
        elif root in self.forward:
            lines.append(f"  {root} → {self.forward[root].text()}")
        elif root in self.ambiguous:
            lines.append(f"  {root}: 맞는 공유가 여럿이라 바꾸지 않음 — " + ", ".join(m.text() for m in self.ambiguous[root]))
        else:
            name = posixpath.basename(root)
            named = [m.text() for m in self.mounts if name in m.names]
            try:
                here = _exists(_local(self.root, root))
            except (OSError, ValueError) as exc:
                lines.append(f"  {root}: 이 Mac에 있는지 확인하지 못함 ({type(exc).__name__}: {exc})")
            else:
                if here:
                    lines.append(f"  {root}: 이 Mac에 있어 바꾸지 않음")
                elif root not in self.roots:
                    lines.append(f"  {root}: 이 Mac에 없음. 공유 설정의 앞부분(공유 설정 폴더·path_map.json의 \"mac\"·제자리가 "
                                 f"아닌 공유의 /<이름>)이 아니라 바꾸지 않음 (이름이 {name}인 공유: {', '.join(named) or '없음'})")
                else:
                    found = ", ".join(m.text() for m in self.mounts) or "없음"
                    lines.append(f"  {root}: 이 Mac에 없고, 이름이 {name}인 공유도 자동 연결 설정·fstab에 없음 "
                                 f"(이름은 대소문자 구분, 찾은 공유: {found})")
        if not self.loaded:
            lines.append("  공유 설정(path_map.json)을 아직 읽지 않아 공유 설정 폴더의 앞부분만 정함")
        lines += [f"  설정 파일 문제: {problem}" for problem in self.problems]
        return "\n".join(lines)

    def report_lines(self):
        """시작 로그 줄: 찾은 공유 수, 바꾸는 앞부분마다 한 줄, 고르지 않은 앞부분, 설정 파일 문제, 보지 않은 줄."""
        displaced = sum(mount.displaced for mount in self.mounts)
        lines = [f"이 Mac에서 공유가 붙은 곳: 자동 연결 설정 {self.auto_master}, {self.fstab} — 공유 {len(self.mounts)}개"
                 f"(제자리가 아닌 것 {displaced}개), 바꾸는 앞부분 {len(self.forward)}개"]
        lines += self.mapping_lines()
        if not self.loaded and displaced:
            lines.append(f"제자리가 아닌 공유 {displaced}개: 공유 설정(path_map.json)을 읽은 뒤 공유 설정에 적을 경로를 정함 — "
                         "그 전에는 그 아래 경로를 저장하지 않음")
        lines += [f"설정 파일 문제: {problem}" for problem in self.problems]
        lines += self.notes
        return lines

    def mapping_lines(self):
        """바꾸는 앞부분(여는 쪽), 고르지 않은 앞부분, 공유 설정에 적을 때의 앞부분, 정하지 못하는 곳."""
        lines = [f"{root} → {mount.path} ({mount.source})" for root, mount in self.forward.items()]
        lines += [f"{root}: 맞는 공유가 여럿이라 바꾸지 않음 — " + ", ".join(m.text() for m in matches)
                  for root, matches in self.ambiguous.items()]
        if self.loaded:
            lines += [f"공유 설정에 적을 때: {mount.path} → {root}" for mount, root in self.reverse_roots]
            forms = {}  # 까닭 → 그 까닭의 앞부분들 (한 줄씩)
            for form, reason in self.unmapped:
                forms.setdefault(reason, []).append(form)
            lines += [f"{', '.join(sorted(found))}: {reason} — {_UNSHARED}" for reason, found in forms.items()]
        return lines
