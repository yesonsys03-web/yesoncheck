"""Windows 자동 연결: 이 PC에 이미 연결된 네트워크 드라이브에서 공유 설정 폴더를 찾고,
변환표(path_map.json)의 "Mac 경로 앞부분 ↔ UNC" 짝을 찾아 기존 변환표에 합친다.

연결은 만들지 않는다(드라이브는 각 PC에서 이미 연결돼 있어야 함). 짝은 작품 폴더가 실제로 열리는지로
검증한다(공유 이름이 같은지만으로 짝짓지 않음). 확인 창은 path_map_setup_dialog.py.
"""

import copy
import datetime
import json
import os
import shutil
import string
from dataclasses import dataclass, field

from yesoncheck import paths, shared_config


class SetupCancelled(Exception):
    """진행 표시에서 사용자가 취소함."""


def _default_is_dir(path):
    return os.path.isdir(path)


def _default_is_file(path):
    return os.path.isfile(path)


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


def find_config_dirs(shares, mac_config_dir=None, is_file=None):
    """연결된 공유에서 공유 설정 폴더(work_paths.json이 있는 폴더)를 찾습니다 → UNC 목록.

    Mac 공유 설정 경로(/USA_DB/test_jn/.yesoncheck)의 뒷부분 조각을 길게부터 공유 아래에 붙여 봅니다
    (USA_DB\\test_jn\\.yesoncheck → test_jn\\.yesoncheck, 뒷부분은 두 조각 이상).
    """
    is_file = is_file or _default_is_file
    parts = paths._mac_parts(mac_config_dir or shared_config.MAC_CONFIG_DIR)
    found = []
    seen = set()
    for share in shares:
        for k in range(0, len(parts) - 1):
            folder = _join_unc(share.unc, parts[k:])
            if is_file(folder + "\\" + shared_config.WORK_PATHS_FILENAME):
                key = paths.unc_key(folder)
                if key not in seen:
                    seen.add(key)
                    found.append(folder)
                break
    return found


def propose_mapping(work_paths, shares, is_dir=None, progress=None):
    """작품 경로({작품: Mac 경로})와 연결된 공유로 변환표 짝을 찾습니다 → Proposal.

    작품마다, 공유마다 Mac 경로의 앞부분 k조각을 떼고 나머지를 공유 아래에 붙인 폴더가 열리는지 봅니다
    (앞부분·나머지 모두 한 조각 이상). 나머지가 가장 길게 맞는 후보를 고르고, 같은 깊이로 여러 공유가
    맞으면 후보 여러 개가 됩니다. progress(done, total)가 False를 돌려주면 SetupCancelled.
    """
    is_dir = is_dir or _default_is_dir
    cache = {}

    def opens(share, rest):
        key = (paths.unc_key(share.unc), tuple(part.casefold() for part in rest))
        if key not in cache:
            cache[key] = is_dir(_join_unc(share.unc, rest))
        return cache[key]

    total = max(1, len(work_paths) * len(shares))
    done = 0
    matches = {}  # 작품 → [(앞부분 조각 튜플, Share)] (가장 깊게 맞은 것들)
    unmatched = {}
    for work, mac_path in sorted(work_paths.items()):
        try:
            parts = paths._mac_parts(mac_path)
        except paths.PathMapError:
            unmatched[work] = mac_path
            continue
        best_depth, best = 0, []
        for share in shares:
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
            done += 1
            if progress is not None and progress(done, total) is False:
                raise SetupCancelled()
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
    return Proposal(pairs=pairs, unmatched=unmatched, shares=list(shares))


def has_additions(existing, proposal):
    """기본 선택으로 합쳤을 때 기존 변환표에서 달라지는 것이 있는지 (없으면 시작할 때 창을 띄우지 않음)."""
    choices = proposal.default_choices()
    if not choices:
        return False
    try:
        merged = merge_path_map(existing, choices)
    except paths.PathMapError:
        return True  # 합치면 형식 오류가 남 → 창에서 보여 주고 저장할 때 오류로 알림
    return merged != existing


def read_existing(config_dir):
    """기존 path_map.json → (내용 dict 또는 None, 읽을 수 없는 이유 또는 None).

    파일이 없으면 (None, None). JSON·형식 오류(기본 파일의 '여기에_붙여넣기' 포함)는 (None, 이유) —
    저장할 때 백업 후 새로 만듭니다. 파일을 읽는 OSError는 그대로 올립니다(덮어쓰지 않도록).
    """
    path = os.path.join(config_dir, paths.PATH_MAP_FILENAME)
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    try:
        data = json.loads(text)
        paths.PathMap.from_dict(data, path)
    except (ValueError, paths.PathMapError) as exc:
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
    """
    path = os.path.join(config_dir, paths.PATH_MAP_FILENAME)
    backup = None
    if backup_existing and os.path.exists(path):
        backup = f"{path}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        if backup:
            raise OSError(f"{exc}\n(쓰기 전에 만든 백업: {backup})") from exc
        raise
    return backup
