"""공유 설정 읽기 — 공유 설정 폴더를 정하고 작품 경로(Windows는 변환표도)·(Mac) 공유가 붙은 곳을 읽는 코드. 파일·NAS 작업만 하고
창·위젯은 건드리지 않아 GUI 밖 스레드에서 돌릴 수 있음(SharedConfigLoad가 QThread로 돌림). 읽은 결과는 SharedConfigState로 돌려주고
창에 넣는 일(`_apply_shared_config`)은 player_sidebar의 믹스인이 함.

기존 경로 `yesoncheck.player_sidebar`에서도 같은 객체로 불러올 수 있음(player_sidebar가 다시 내보냄).
"""

import functools
import os
import sys
import time
import traceback
from dataclasses import dataclass, field

from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck import path_map_setup, paths, shared_config, timing_log


@dataclass
class SharedConfigState:
    """공유 설정을 읽은 결과 (gather_shared_config가 만들고 창의 _apply_shared_config가 넣음). Qt 객체 없음.

    기본값은 빈 상태 (창을 만들 때 '불러오는 중' 상태, 그리고 setup_shared_config가 읽기 전에 먼저 넣는 상태).
    """

    config_dir: str = None
    work_paths: dict = field(default_factory=dict)
    shared_config_problem: str = None
    path_map_problem: str = None
    config_dir_candidates: list = field(default_factory=list)
    config_dir_search_failed: bool = False
    config_dir_search_problems: list = field(default_factory=list)  # (Windows) 자동 찾기 중 확인하지 못한 곳
    activate_path_map: bool = False  # (Windows) 넣을 때 paths.activate(path_map) — 아니면 활성 변환표를 그대로 둠
    path_map: object = None  # paths.PathMap (이 PC에 연결된 주소를 앞으로 옮김) 또는 None(변환표 해제)
    works_not_opening: list = None  # (Windows) 시작할 때 미리 계산한 '열리지 않는 작품' — None이면 계산하지 않음
    mount_map: object = None  # (Mac) path_map.json까지 보고 정한 mac_mounts.MountMap — None이면 활성 맵을 그대로 둠
    elapsed: float = None  # 백그라운드 읽기에 걸린 초


def list_works_not_opening(work_paths, to_native, timeout=None):
    """(Windows) 이 PC에서 열리지 않는 작품 목록 ['작품: 이유']. to_native: 저장된 Mac 경로 → 이 PC 경로.

    작품 경로의 공유 루트(\\\\서버\\공유)를 공유마다 한 번만, timeout초까지만 기다리며 열어 보고, 열리지 않거나
    응답이 없으면(서버가 꺼짐·주소가 바뀜 등) 그 공유의 작품 폴더는 열어 보지 않습니다 — 작품마다 SMB 시간 초과를
    기다리지 않도록. 응답한 루트 아래의 작품 폴더는 바로 엽니다.
    """
    is_dir = path_map_setup._default_is_dir
    timeout = path_map_setup.SHARE_PROBE_TIMEOUT_S if timeout is None else timeout
    root_opens = {}  # 접은 (서버, 공유) → 열리는지
    broken = []
    timing_log.log("작품 확인", f"작품 {len(work_paths)}개가 이 PC에서 열리는지 확인 중…")
    started = time.perf_counter()
    for work_name, stored in sorted(work_paths.items()):
        try:
            native = to_native(stored)
        except paths.PathMapError:
            broken.append(f"{work_name}: 변환표에 없음 ({stored})")
            continue
        root_parts = paths._unc_parts(native)[:2]
        key = tuple(paths._fold(root_parts))
        root = "\\\\" + "\\".join(root_parts)
        if key not in root_opens:
            timing_log.log("작품 확인", f"{root} 여는 중…")
            root_started = time.perf_counter()
            root_opens[key] = path_map_setup.probe(is_dir, root, timeout)
            result = {True: "열림", False: "열리지 않음", None: f"응답 없음 ({timeout:g}초) — 건너뜀"}[root_opens[key]]
            timing_log.log("작품 확인", f"{root} {timing_log.since(root_started)} — {result}")
        if root_opens[key] is None:
            broken.append(
                f"{work_name}: 열 수 없음 ({native}) — 공유 폴더 {root}가 {timeout:g}초 안에 응답 없음 (서버가 꺼졌거나 느림)"
            )
        elif not root_opens[key]:
            broken.append(f"{work_name}: 열 수 없음 ({native}) — 공유 폴더 {root}가 열리지 않음 (서버가 꺼졌거나 연결이 끊김)")
        elif not is_dir(native):
            broken.append(f"{work_name}: 열 수 없음 ({native})")
    timing_log.log("작품 확인", f"확인 끝 ({timing_log.since(started)}): 열리지 않는 작품 {len(broken)}개")
    return broken


def _config_dir_usable(config_dir):
    """공유 설정 폴더로 쓸 수 있는지 → True | False | None(시간 안에 응답 없음). NAS를 열어 보므로 앞뒤로 기록하고
    SHARE_PROBE_TIMEOUT_S초까지만 기다림 (서버가 꺼졌거나 주소가 바뀌면 끝없이 걸릴 수 있음)."""
    if config_dir is None:
        return False
    timing_log.log("공유 설정", f"설정 폴더 확인 중: {config_dir}")
    started = time.perf_counter()
    usable = path_map_setup.probe(shared_config.is_valid_config_dir, config_dir)
    result = {True: "쓸 수 있음", False: "쓸 수 없음", None: "응답 없음"}[usable]
    timing_log.log("공유 설정", f"설정 폴더 확인 ({timing_log.since(started)}) — {result}")
    return usable


def _auto_find_config_dir(state, shares, share_problems):
    """(Windows) 이 PC에서 쓸 수 있는 공유(shares: 연결된 네트워크 드라이브·시스템 드라이브의 UNC 링크)와 Harmony식
    C:\\USA_DB\\test_jn\\.yesoncheck에서 공유 설정 폴더를 찾습니다 (같은 폴더는 하나로).

    Harmony 경로(%SystemDrive%\\USA_DB\\test_jn\\.yesoncheck — 링크·바로 가기로 NAS를 가리킬 때만)에서 찾으면 그것이
    Mac 경로 /USA_DB/test_jn/.yesoncheck와 똑같은 폴더이므로 바로 씀 (네트워크 공유는 확인하지 않음 — 서버가 꺼진
    기억된 드라이브의 시간 제한을 기다리지 않게). 아니면 공유에서 찾음:
    딱 하나면 PC별 설정에 저장하고 그 폴더를 돌려줍니다. 여러 개면 state.config_dir_candidates에 남기고
    (창 표시 후 고르게 함) None. 하나도 못 찾으면 state.config_dir_search_failed를 True로 남기고 None.
    PC별 설정 저장 실패는 state.shared_config_problem에 남기고 None. 확인하지 못한 곳(드라이브 연결 정보, 링크의 실제
    위치, 응답 없는 공유)은 state.config_dir_search_problems에 남김 (폴더를 고르게 할 때 보임).
    """
    timing_log.log("공유 설정", "PC별 설정의 공유 설정 폴더가 없거나 열리지 않음 → 이 PC의 공유에서 찾는 중…")
    started = time.perf_counter()
    local, local_problem = path_map_setup.find_local_config_dir()
    search_problems = list(share_problems) + ([local_problem] if local_problem else [])
    state.config_dir_search_problems = search_problems
    if local:
        timing_log.log("공유 설정", f"Harmony 경로({path_map_setup.system_drive()}\\"
                                   f"{paths._mac_parts(shared_config.MAC_CONFIG_DIR)[0]})에서 찾음: {local} — "
                                   "다른 공유는 확인하지 않음")
        found = [local]
    else:
        found = []
        seen = set()
        for folder in path_map_setup.find_config_dirs(shares, problems=search_problems):  # 응답 없는 공유는 problems로
            key = path_map_setup.config_dir_key(folder)
            if key not in seen:
                seen.add(key)
                found.append(folder)
    timing_log.log("공유 설정", f"찾기 끝 ({timing_log.since(started)}): {', '.join(found) or '못 찾음'}")
    if len(found) != 1:
        state.config_dir_candidates = found
        if not found:
            state.config_dir_search_failed = True
        return None
    try:
        shared_config.save_local_settings({"config_dir": found[0]})
    except (shared_config.SharedConfigError, OSError) as exc:
        state.shared_config_problem = (
            f"공유 설정 폴더를 찾았지만 PC별 설정에 저장하지 못했습니다: {found[0]}\n{exc}\n\n{traceback.format_exc()}"
        )
        return None
    print(f"[공유 설정] 이 PC의 공유에서 공유 설정 폴더를 찾았습니다: {found[0]}")
    return found[0]


def _load_mac_mount_map(state, config_dir, mount_map):
    """(Mac, 뒤 스레드) 공유 설정 폴더의 path_map.json "mac" 항목(공유 설정의 앞부분 — Windows와 같음)으로 이 Mac에서 공유가
    붙은 곳을 마저 정한 MountMap (mac_mounts.MountMap.with_canonical_roots). 바꾸는 것은 로그에 [공유] 줄로.

    path_map.json을 읽지 못하면 제자리가 아닌 곳에 붙은 공유의 앞부분은 /<이름>으로만 정함: 그런 공유가 이 Mac에 있으면
    변환표 문제(state.path_map_problem — 창으로 알림), 없으면 바뀌는 것이 없어 로그만. 자동 연결 설정·fstab에 공유가 하나도
    없으면 읽지 않음.
    """
    roots = []
    if mount_map.mounts:
        try:
            roots = ["/" + "/".join(mac_parts) for mac_parts, _uncs in paths.PathMap.load(config_dir).shares]
        except paths.PathMapError as exc:
            if mount_map.has_displaced():
                state.path_map_problem = (
                    f"{exc}\n\n이 Mac은 공유를 제자리가 아닌 곳(자동 연결 폴더 등)에 붙여 path_map.json의 \"mac\" 항목으로 공유 설정의 "
                    "앞부분을 정합니다. 읽지 못해 /<이름>으로만 정했습니다 — 이름이 다른 앞부분(예: "
                    "/Users/studio01/Desktop/usadata4)의 영상은 다른 PC와 경로·썸네일이 맞지 않을 수 있습니다."
                    f"\n\n{traceback.format_exc()}"
                )
            print(f"[공유] path_map.json을 읽지 못함 — 제자리가 아닌 공유의 앞부분은 /<이름>으로만 정함: {exc}", flush=True)
    loaded = mount_map.with_canonical_roots(roots)
    for line in loaded.mapping_lines():
        print(f"[공유] (공유 설정을 읽은 뒤) {line}", flush=True)
    for problem in loaded.problems[len(mount_map.problems):]:
        print(f"[공유] (공유 설정을 읽은 뒤) 문제: {problem}", flush=True)
    return loaded


def gather_shared_config(find_works_not_opening=False):
    """공유 설정 폴더를 정하고 작품 경로(Windows는 변환표도)를 읽습니다 → SharedConfigState.

    파일·NAS 작업만 하고 창·위젯·활성 변환표(paths.activate)는 건드리지 않음 → GUI 밖 스레드에서 실행할 수 있음.
    (설정 폴더를 자동으로 찾았을 때 PC별 설정(로컬 파일) 저장은 여기서 함.) 예상한 문제는 결과의 *_problem에
    스택 트레이스째 남기고, 그 밖의 예외는 그대로 올립니다. 공유 파일을 기본값으로 덮어쓰지 않습니다.
    find_works_not_opening: (Windows) 시작할 때 알릴 '열리지 않는 작품'도 읽은 변환표로 미리 계산.
    """
    state = SharedConfigState()
    shares_once = []  # (Windows) 이 PC의 공유는 한 번만 조사 (링크의 실제 위치 확인은 NAS를 열어 볼 수 있음)

    def available_shares():
        """→ (shares, problems). 드라이브·링크 문제는 available_shares가 로그에도 남김."""
        if not shares_once:
            shares_once.append(path_map_setup.available_shares())
        return shares_once[0]

    try:
        config_dir = shared_config.configured_config_dir()
    except shared_config.SharedConfigError as exc:
        state.shared_config_problem = f"{exc}\n\n{traceback.format_exc()}"
        return state
    usable = True
    if paths.IS_WINDOWS and not os.environ.get(shared_config.CONFIG_DIR_ENV):
        usable = _config_dir_usable(config_dir)
    if usable is None:
        # 설정 폴더 자체가 응답하지 않음 — config_dir은 비워 둠 (GUI 스레드의 resolve가 그 폴더를 다시 열어 보지 않고
        # 다른 폴더를 고르게 함)
        state.shared_config_problem = (
            f"공유 설정 폴더가 {path_map_setup.SHARE_PROBE_TIMEOUT_S:g}초 안에 응답하지 않습니다: {config_dir} "
            "(서버가 꺼졌거나 느림)"
        )
        return state
    if not usable:
        found = _auto_find_config_dir(state, *available_shares())
        if state.shared_config_problem:
            return state
        config_dir = found or config_dir
    if config_dir is None:
        state.shared_config_problem = "공유 설정 폴더가 아직 정해지지 않았습니다."
        return state
    state.config_dir = config_dir
    work_paths_file = os.path.join(config_dir, shared_config.WORK_PATHS_FILENAME)
    problems = []
    timing_log.log("공유 설정", f"작품 경로 읽는 중: {work_paths_file}")
    started = time.perf_counter()
    try:
        state.work_paths = shared_config.read_work_paths(work_paths_file)
        timing_log.log("공유 설정", f"작품 경로 읽음 ({timing_log.since(started)}): 작품 {len(state.work_paths)}개")
    except shared_config.SharedConfigError as exc:
        lookup = ""
        if not paths.IS_WINDOWS and not os.environ.get(shared_config.CONFIG_DIR_ENV):
            lookup = f"\n\n{shared_config.mac_config_dir_lookup()}"  # (Mac) 공유 설정 폴더를 어디서 찾아봤는지
        problems.append(f"{exc}{lookup}\n\n{traceback.format_exc()}")
        timing_log.log("공유 설정", f"작품 경로를 읽지 못함 ({timing_log.since(started)})")
    if not paths.IS_WINDOWS and paths.active_mount_map() is not None:
        # (Mac) path_map.json의 "mac"(공유 설정의 앞부분)까지 보고 이 Mac에서 공유가 붙은 곳을 마저 정함. 창에는
        # _apply_shared_config가 넣음
        state.mount_map = _load_mac_mount_map(state, config_dir, paths.active_mount_map())
    if paths.IS_WINDOWS:
        state.activate_path_map = True
        timing_log.log("변환표", f"읽는 중: {os.path.join(config_dir, paths.PATH_MAP_FILENAME)}")
        started = time.perf_counter()
        try:
            path_map = paths.PathMap.load(config_dir)
        except paths.PathMapError as exc:
            state.path_map_problem = f"{exc}\n\n{traceback.format_exc()}"
            timing_log.log("변환표", f"읽지 못함 ({timing_log.since(started)})")
        else:
            timing_log.log("변환표", f"읽음 ({timing_log.since(started)})")
            # 같은 공유를 PC마다 다른 주소로 연결했을 수 있음 → 이 PC에 연결된(드라이브·링크) 주소를 먼저 씀 (파일은 그대로)
            shares, _problems = available_shares()
            state.path_map = path_map.with_preferred_aliases([share.unc for share in shares])
    if problems:
        state.shared_config_problem = "\n\n".join(problems)
    if find_works_not_opening and state.path_map is not None and not state.shared_config_problem:
        state.works_not_opening = list_works_not_opening(state.work_paths, state.path_map.mac_to_windows)
    return state


def config_dir_from_chosen_folder(folder):
    """(Windows) 고른 폴더 → 저장할 공유 설정 폴더 주소.

    네트워크 드라이브·UNC는 drive_to_unc로. 네트워크 드라이브가 아닌 드라이브(로컬 디스크)의 링크(Harmony용
    C:\\USA_DB → \\\\서버\\USA_DB)는 실제 위치(realpath)가 UNC면 그 UNC로 (원래 오류와 함께 로그에 남김).
    그 밖의 드라이브 오류(연결 정보를 읽지 못함 등)와 링크가 아닌 로컬 폴더는 drive_to_unc의 오류를 그대로 올림.
    """
    try:
        return paths.drive_to_unc(folder)
    except paths.NotNetworkDriveError as exc:
        try:
            real = path_map_setup._real_unc(path_map_setup._default_realpath(folder))
        except OSError as real_exc:
            raise paths.PathMapError(f"{exc}\n실제 위치(링크 대상)도 알 수 없습니다: {real_exc}") from real_exc
        if real is None:
            raise
        print(f"[공유 설정] 고른 폴더 {folder}: {exc} → 링크의 실제 위치 {real} 사용")
        return real


class SharedConfigLoad(QThread):
    """gather_shared_config를 GUI 밖에서 실행하는 스레드 (위젯은 건드리지 않음). 결과는 loaded 신호로 GUI 스레드에.

    부모 없이 만들고(창이 지워질 때 함께 파괴되지 않게) 실행 중에는 _running에 붙잡아 둠: 실행 중인 QThread가
    파괴되면 "QThread: Destroyed while thread is still running"으로 프로세스가 중단됨(7133188 참고).
    끝나면(finished — GUI 스레드에서 처리) 놓음.
    """

    loaded = pyqtSignal(object)  # SharedConfigState
    _running = set()

    def __init__(self, gather=None):
        super().__init__()
        self._gather = gather or functools.partial(gather_shared_config, find_works_not_opening=True)
        self.finished.connect(self._forget)

    def start(self, *args):
        SharedConfigLoad._running.add(self)
        super().start(*args)

    def run(self):
        started = time.perf_counter()
        try:
            state = self._gather()
        except Exception:
            # 예상 못 한 오류도 삼키지 않음: 로그에 스택 트레이스째 남기고 공유 설정 문제로 알림 (resolve가 창으로)
            text = traceback.format_exc()
            print(f"[공유 설정] 불러오다 예상치 못한 오류:\n{text}", file=sys.stderr, flush=True)
            state = SharedConfigState(shared_config_problem=f"공유 설정을 불러오다 예상치 못한 오류가 났습니다.\n\n{text}")
        state.elapsed = time.perf_counter() - started
        self.loaded.emit(state)

    def _forget(self):
        self.wait()  # finished는 스레드가 끝나기 직전에 옴 → 완전히 끝날 때까지 (곧 끝남)
        SharedConfigLoad._running.discard(self)
