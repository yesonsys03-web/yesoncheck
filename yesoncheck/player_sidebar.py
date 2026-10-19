"""Media library and sidebar helpers for VideoPlayer."""

import contextlib
import functools
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
from PyQt5.QtCore import QDateTime, QDir, Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWIDGETSIZE_MAX,
)

from yesoncheck.workers import ThumbnailLoaderWorker, ThumbnailWorker
import traceback

from yesoncheck import path_map_setup, paths, shared_config, thumbnails, timing_log, video_list
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog

LOADING_TITLE = "Yeson Checker — 공유 설정 불러오는 중…"
LOADING_NOTICE = "공유 설정을 불러오는 중입니다. 잠시 뒤 다시 시도하세요."
LOADING_WORK_ITEM = "공유 설정 불러오는 중…"  # 불러오는 동안 작품 목록의 첫 항목 ("작품선택" 대신)
WORK_PLACEHOLDER = "작품선택"
NO_SEASON_WORKS = ("The_Johnsons", "TJS_Animatic")  # 시즌이 없는 작품: 작품 폴더 바로 아래가 job (작품 → job)
THUMBNAIL_SAVE_FAILED = "썸네일 저장 실패"  # 썸네일 파일을 쓰지 못함 (창 제목)
THUMBNAIL_FOLDER_PROBLEM = "썸네일 폴더 문제"  # 썸네일 폴더를 만들지 못함 등 (창 제목)
THUMBNAIL_VIDEO_PROBLEM = "영상 확인 실패"  # 썸네일을 만들 영상을 확인하지 못함 (창 제목)
THUMBNAIL_MAKE_FAILED = "썸네일 만들기 실패"  # 영상은 있지만 썸네일을 만들지 못함 — OpenCV가 열지 못함 등 (창 제목)
THUMBNAIL_CONTEXT_ROLE = Qt.UserRole + 1  # 사이드바 항목 데이터: 그 영상의 썸네일 자리 (ThumbnailContext)
SIDEBAR_SOURCE_ROLE = Qt.UserRole + 2  # 사이드바 항목 데이터: 그 영상이 들어온 곳 (video_list.ListSource, 따로 넣은 파일은 None)
LIST_READ_FAILED = "목록 폴더를 읽지 못함"  # 영상 목록을 만들거나 다시 읽을 폴더를 읽지 못함 (창 제목)
LIST_FOLDER_GONE = "목록 폴더 없음"  # 목록에 영상을 넣은 폴더가 지워짐 (창 제목)
ACTIVATION_REFRESH_GAP_S = 2.0  # 앱이 다시 활성될 때 이 시간 안에 이미 목록을 읽었으면 또 읽지 않음
ACTIVATION_REFRESH_GAP_FACTOR = 10  # … 마지막 읽기가 오래 걸렸으면(Windows SMB의 큰 job) 그 시간의 이만큼 배 동안


@dataclass(frozen=True)
class ThumbnailContext:
    """사이드바 영상의 썸네일을 어디에 둘지. 항목을 넣을 때의 상태로 정하고, 나중에 다른 폴더를 끌어다 놓아 덧붙이거나
    job·북마크를 바꿔도 그 항목은 바뀌지 않음 (재검토 L1).
    """

    folder: str = None  # 썸네일 폴더: 여기서 읽고 여기에 저장
    problem: tuple = None  # (폴더, 창 제목, 내용): 썸네일 폴더를 만들지 못함 → 화면에만, 창은 썸네일을 쓸 때
    pending_base: str = None  # 아직 정하지 않음: 처음 쓸 때 이 폴더 아래에 썸네일 폴더를 만듦 (예: 처음 끌어다 놓은 파일)


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


class SidebarScan(QThread):
    """사이드바 목록 다시 읽기의 디스크 읽기(video_list.read_sources — Qt 없음)를 GUI 밖에서. 목록은 건드리지 않고 결과만
    scanned 신호로 GUI 스레드에 (창의 _on_sidebar_scanned가 목록을 맞춤).

    부모 없이 만들고 창이 붙잡음 (_sidebar_scan, 결과를 받을 때까지). 창을 닫을 때 실행 중이면 release_worker로 넘김:
    끝날 때까지 붙잡아 두고(실행 중인 QThread가 파괴되면 앱이 죽음) 앱이 끝나기 전에 wait_for_released_workers가 정해진
    시간까지 기다림 (응답 없는 NAS를 읽는 중일 수 있음).
    """

    scanned = pyqtSignal(object)  # 이 SidebarScan (read·elapsed·unexpected를 채움)

    def __init__(self, sources, files, generation, check_thumbnails=False):
        super().__init__()
        self.sources = sources  # 읽을 곳 (video_list.ListSource)
        self.files = files  # 있는지 확인할 따로 넣은 파일
        self.generation = generation  # 읽기 시작할 때의 사이드바 세대 번호 (결과를 넣을 때 목록이 그대로인지)
        # 이 읽기를 시작할 때까지 누른 새로고침 버튼·F5의 썸네일 확인 요청 (결과를 넣을 때 씀 — _on_sidebar_scanned)
        self.check_thumbnails = check_thumbnails
        self.read = None  # video_list.SourcesRead
        self.elapsed = None
        self.unexpected = None  # 예상 못 한 오류의 스택 트레이스 (GUI 스레드가 창으로)

    def run(self):
        started = time.perf_counter()
        try:
            self.read = video_list.read_sources(self.sources, self.files)
        except Exception:
            # 예상 못 한 오류도 삼키지 않음: 로그에 스택 트레이스째 남기고 GUI 스레드가 창으로 알림
            self.unexpected = traceback.format_exc()
            print(f"[목록] 다시 읽다 예상치 못한 오류:\n{self.unexpected}", file=sys.stderr, flush=True)
        self.elapsed = time.perf_counter() - started
        self.scanned.emit(self)


class PlayerSidebarMixin:

    def dragEnterEvent(self, event):
        """메인 윈도우에 파일 드래그앤드롭 이벤트"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        # 부모 위젯을 찾아서 VideoPlayer 인스턴스를 찾기
        parent = self.parent()
        while parent and not hasattr(parent, 'open_file'):
            parent = parent.parent()
        
        if parent and hasattr(parent, 'open_file'):
            video_files = []
            has_folder = False
            read_failed = False  # 읽지 못한 폴더가 있음 (창으로 알림 — '지원되는 비디오 파일이 없습니다'는 띄우지 않음)
            folder_paths = []  # 폴더 경로들을 저장할 리스트
            
            # URL들을 파일/폴더로 분류
            for url in urls:
                local_path = paths.normalize_native(url.toLocalFile())
                if os.path.isfile(local_path):
                    # 파일인 경우
                    if parent.is_video_file(local_path):
                        video_files.append(local_path)
                elif os.path.isdir(local_path):
                    # 폴더인 경우 - 재귀적으로 비디오 파일 찾기
                    has_folder = True
                    folder_paths.append(local_path)  # 폴더 경로 저장
                    folder_files = parent.get_video_files_from_folder(local_path)
                    if folder_files is None:
                        read_failed = True
                        parent._register_unread_folder(local_path)  # 연결이 돌아오면 새로고침(F5)으로 들어옴
                        continue
                    folder_files.sort()  # 이름 순서대로 정렬
                    video_files.extend(folder_files)
            
            # 폴더가 포함된 경우 북마크에 자동 추가
            if folder_paths:
                for folder_path in folder_paths:
                    if not paths.contains_path(parent.bookmarks, folder_path):
                        parent.bookmarks.append(folder_path)
                        print(f"폴더가 북마크에 자동 추가됨: {folder_path}")
                
                # 북마크 저장
                parent.save_bookmarks()
                
                # 사용자에게 알림 (폴더가 여러 개인 경우에만)
                if len(folder_paths) > 1:
                    QMessageBox.information(parent, "북마크 추가", f"{len(folder_paths)}개의 폴더가 북마크에 자동으로 추가되었습니다.")
            
            # 비디오 파일 처리
            if has_folder:
                # 폴더가 포함된 경우: 기존 사이드바 초기화 후 모든 파일을 사이드바에 추가하고 첫 번째 파일을 Video A에 로드
                if video_files:
                    # 첫 폴더의 썸네일 폴더를 씀 (전에 고른 job·폴더가 아니라)
                    parent._use_dropped_folder_for_thumbnails(folder_paths[0])
                    
                    # 기존 사이드바 리스트 초기화
                    parent.sidebar.clear()
                    parent.add_files_to_sidebar(video_files, folder_paths)
                    # 첫 번째 파일을 Video A에 로드
                    parent.open_file('A', video_files[0])
                    # 백그라운드 로딩 스케줄링
                    parent.schedule_background_thumbnail_loading()
                    QMessageBox.information(parent, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
                elif not read_failed:
                    QMessageBox.warning(parent, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")
            else:
                # 개별 파일들만 있는 경우
                if len(video_files) == 1:
                    parent.open_file('A', video_files[0])
                elif len(video_files) == 2:
                    # 두 개 파일: Video A와 B에 각각 로드
                    parent.open_file('A', video_files[0])
                    parent.open_file('B', video_files[1])
                elif len(video_files) > 2:
                    # 여러 파일: 첫 번째는 Video A에, 나머지는 사이드바에 추가
                    parent.open_file('A', video_files[0])
                    remaining_files = video_files[1:]
                    parent.add_files_to_sidebar(remaining_files)
                    if remaining_files:
                        QMessageBox.information(parent, "파일 로드 완료", f"첫 번째 파일이 Video A에 로드되고, {len(remaining_files)}개의 파일이 사이드바에 추가되었습니다.")
        
        event.acceptProposedAction()

    def is_video_file(self, file_path):
        """파일이 지원되는 비디오 형식인지 확인"""
        return os.path.splitext(file_path.lower())[1] in video_list.VIDEO_EXTENSIONS

    def add_files_to_sidebar(self, file_paths, folders=()):
        """사이드바에 파일들을 추가 (항상 번호순 정렬).

        folders: 끌어다 놓은 폴더 — 그 아래 파일은 그 폴더에서 들어온 것으로 기억 (목록 다시 읽기가 그 폴더를 같은 규칙으로
        다시 읽음). 나머지는 따로 넣은 파일 (다시 읽을 때 파일이 있는 동안만 목록에).
        폴더 A와 그 안의 A/sub를 함께 끌어다 놓으면 A/sub의 영상은 폴더마다 한 번씩 두 번 들어오므로 하나는 A, 하나는 A/sub에서
        들어온 것으로 (같은 영상의 n번째는 그 영상을 담은 n번째 폴더) — 다시 읽어도 출처마다 한 번씩이라 늘지 않음.
        """
        file_paths = sorted(file_paths, key=video_list.natural_key)
        sources = [self._register_sidebar_source(video_list.ListSource("folder", folder)) for folder in folders]
        unclaimed = {}  # path_key → 그 영상을 담은 폴더 중 아직 항목을 정하지 않은 것

        def source_of(file_path):
            key = paths.path_key(file_path)
            if key not in unclaimed:
                unclaimed[key] = [source for source in sources if video_list.is_under(file_path, source.folder)]
            return unclaimed[key].pop(0) if unclaimed[key] else None

        # 항목마다 지금의 썸네일 자리를 기억 (이미 목록에 있는 영상이면 그 항목의 자리)
        items = self._add_sidebar_videos(
            [(os.path.basename(file_path), file_path, source_of(file_path))
             for file_path in file_paths if os.path.exists(file_path)])
        # 썸네일 모드인 경우 썸네일 생성. 영상·자리를 미리 꺼내 둠: 만드는 동안 이벤트를 처리하므로 목록이 바뀌면
        # (job·폴더를 바꿈) 항목이 지워짐 → 그때는 멈춤. 그동안 목록 다시 읽기는 끝난 뒤로 미룸
        if self.is_thumbnail_mode:
            with self._hold_sidebar_refresh():
                state = self._thumbnail_pass_state()  # 목록 모드로 바꾸거나 창을 닫아도 멈춤
                jobs = {}  # 같은 영상을 한 번에 여러 번 넣었으면 한 번만 (아이콘은 경로가 같은 모든 항목에)
                for item in items:
                    jobs.setdefault(paths.path_key(item.data(Qt.UserRole)),
                                    (item.data(Qt.UserRole), item.data(THUMBNAIL_CONTEXT_ROLE)))
                for file_path, context in jobs.values():
                    stopped = self._thumbnail_pass_stopped(state)
                    if stopped:
                        print(f"넣은 영상의 썸네일 만들기를 멈춤 ({stopped})")
                        break
                    self.generate_thumbnail(file_path, context=context)
        self._sidebar_read_done(None)  # 끌어다 놓은 폴더·파일을 방금 읽음 (앱이 다시 활성돼도 곧바로 또 읽지 않게)
        
        if file_paths:
            QMessageBox.information(self, "완료", f"{len(file_paths)}개의 파일이 사이드바에 추가되었습니다.")

    def get_video_files_from_folder(self, folder_path):
        """폴더에서 재귀적으로 비디오 파일들을 찾아서 반환 (.으로 시작하는 파일 제외, 번호 순서).

        규칙은 video_list.scan_folder (목록 다시 읽기도 같은 규칙). 폴더를 읽지 못하면 창으로 알리고 None — 부른 쪽은
        '지원되는 비디오 파일이 없습니다'를 띄우지 않음 (예전에는 로그에만 남기고 빈 목록이 되어 그 창이 떴음). 그 안의 폴더를
        읽지 못하면 읽은 영상을 돌려주고 창으로 알림. 창은 다시 읽기와 같은 문구·기록 ((제목, 폴더, 오류)마다 한 번).
        """
        started = time.perf_counter()
        try:
            result = video_list.scan_folder(folder_path)
        except OSError as e:
            self._report_list_source_problem(folder_path, e)
            return None
        self._sidebar_scan_seconds = time.perf_counter() - started
        self._report_list_read(folder_path, result)
        return [file_path for _name, file_path in result.videos]

    def show_sidebar_context_menu(self, pos):
        index = self.sidebar.indexAt(pos)
        if index.isValid():
            menu = QMenu(self.sidebar)
            open_video_a_action = menu.addAction("비디오 A 열기")
            open_video_a_action.triggered.connect(lambda: self.open_video_a(index))
            open_video_b_action = menu.addAction("비디오 B 열기")
            open_video_b_action.triggered.connect(lambda: self.open_video_b(index))

            # 구분선 추가
            menu.addSeparator()

            merge_videos_action = menu.addAction("애니매틱 하나로 합치기")
            merge_videos_action.triggered.connect(self.merge_videos)

            # 구분선 추가
            menu.addSeparator()

            copy_file_action = menu.addAction("파일 복사")
            copy_file_action.triggered.connect(self.copy_selected_files)  # copy_selected_files 메서드 호출

            # 구분선 추가
            menu.addSeparator()

            # 썸네일 재생성 메뉴 추가
            regenerate_thumbnail_action = menu.addAction("썸네일 재생성")
            regenerate_thumbnail_action.triggered.connect(lambda: self.regenerate_selected_thumbnails())

            # 구분선 추가
            menu.addSeparator()

            video_info_action = menu.addAction("미디어 정보")
            video_info_action.triggered.connect(lambda: self.show_video_info(index))

            # 메뉴가 떠 있는 동안·고른 일을 하는 동안 목록 다시 읽기는 미룸 (index는 줄 번호 — 목록이 바뀌면 다른 영상을 가리킴)
            with self._hold_sidebar_refresh():
                menu.exec_(self.sidebar.viewport().mapToGlobal(pos))

    def copy_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if not selected_items:
            return

        file_paths = [item.toolTip() for item in selected_items]
        target_path = QFileDialog.getExistingDirectory(self, "Select Folder to Copy")
        target_path = paths.normalize_native(target_path)
        if target_path:
            self.copy_files_to_target(file_paths, target_path)

    def copy_files_to_target(self, file_paths, target_path):
        """선택한 파일을 폴더로 복사합니다 (메타데이터 유지). 실패한 파일은 모아서 보여 줍니다."""
        failures = []
        for file_path in file_paths:
            try:
                shutil.copy2(file_path, target_path)
                print(f"File copied to {target_path}")
            except OSError as exc:
                failures.append(f"{file_path}\n  → {exc}")
        if failures:
            QMessageBox.critical(self, "복사 실패", f"{len(failures)}개 파일을 복사하지 못했습니다:\n\n" + "\n".join(failures))

    def regenerate_selected_thumbnails(self):
        """선택된 파일들의 썸네일을 재생성합니다."""
        try:
            selected_items = self.sidebar.selectedItems()
            if not selected_items:
                QMessageBox.information(self, "알림", "선택된 파일이 없습니다.")
                return

            # 진행 상황을 보여주는 다이얼로그 생성
            progress_dialog = QProgressDialog("썸네일 재생성 중...", "취소", 0, len(selected_items), self)
            progress_dialog.setWindowTitle("썸네일 재생성")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)
            progress_dialog.setAutoReset(True)
            progress_dialog.show()

            print(f"선택된 {len(selected_items)}개 파일의 썸네일 재생성을 시작합니다.")

            # 이벤트를 처리하는 동안 목록이 바뀌면(job·폴더를 바꿈) 항목이 지워지므로 경로를 미리 꺼내 두고, 항목은 목록이
            # 그대로인지 확인한 뒤에만 씀. 그동안 목록 다시 읽기는 끝난 뒤로 미룸 (항목을 쥐고 있음)
            with self._hold_sidebar_refresh():
                generation = self._sidebar_generation
                stopped = False
                for i, (file_path, item) in enumerate([(item.toolTip(), item) for item in selected_items]):
                    if progress_dialog.wasCanceled():
                        print("썸네일 재생성이 취소되었습니다.")
                        break

                    if file_path and os.path.isfile(file_path):
                        # 진행 상황 업데이트 (모달 진행 창의 setValue는 이벤트를 처리함)
                        progress_dialog.setLabelText(f"재생성 중: {os.path.basename(file_path)}")
                        progress_dialog.setValue(i)
                        if self._sidebar_generation != generation:
                            print("사이드바 목록이 바뀌어(job·폴더를 바꿈) 썸네일 재생성을 멈춤")
                            stopped = True
                            break
                    
                        # 기존 썸네일 삭제 (이 항목의 썸네일 폴더에서)
                        self.delete_thumbnail_file(file_path, item)
                        # 썸네일 재생성
                        self.generate_thumbnail(file_path, item)
                        print(f"썸네일 재생성 완료: {os.path.basename(file_path)}")

                    # UI 업데이트
                    QApplication.processEvents()

            progress_dialog.setValue(len(selected_items))
            if stopped:
                return
            QMessageBox.information(self, "완료", f"{len(selected_items)}개 파일의 썸네일 재생성이 완료되었습니다.")

        except Exception as e:
            print(f"썸네일 재생성 중 오류: {e}")
            QMessageBox.critical(self, "오류", f"썸네일 재생성 중 오류가 발생했습니다:\n{str(e)}")

    def delete_thumbnail_file(self, file_path, item=None):
        """특정 파일의 썸네일을 그 항목의 썸네일 폴더에서 삭제합니다 (item: 사이드바 항목, 없으면 경로로 찾음)."""
        try:
            if item is None:
                item = self._sidebar_item_for(file_path)
            context = self._item_thumbnail_context(item, file_path)
            if context.pending_base is not None:
                context = self._resolve_pending_thumbnail_context(context)
            if not context.folder:
                return  # 저장한 썸네일 없음 (화면에만)

            thumbnail_path = thumbnails.thumbnail_path(context.folder, file_path)

            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                print(f"썸네일 파일 삭제: {thumbnail_path}")

            # UI에서도 썸네일 제거
            if item is not None:
                item.setIcon(QIcon())
                # 파일명만 표시
                item.setText(os.path.basename(file_path))

        except Exception as e:
            print(f"썸네일 파일 삭제 중 오류: {e}")

    def update_season_list(self):
        selected_work = self.workComboBox.currentText()
        self._work_path_problems_shown = set()
        self.seasonComboBox.clear()
        self.seasonComboBox.addItem("시즌선택")

        try:
            # JSON에서 작품 경로 가져오기
            path = self.get_work_path(selected_work)
            
            if not path:
                # 경로가 없는 경우 시즌 목록 없음
                season_list = []
            elif selected_work == "The_Johnsons":
                # The_Johnsons는 시즌이 없으므로 바로 job 목록을 가져옴
                season_list = []  # 시즌 목록 없음
                # 시즌 선택 없이 바로 job 목록 가져오기
                self.jobComboBox.clear()
                self.jobComboBox.addItem("job선택")
                try:
                    if os.path.isdir(path):
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file.startswith("TJS_")
                            and len(file) > 4
                            and file[4:].isdigit()
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                except FileNotFoundError:
                    print(f"Directory not found: {path}")
            elif selected_work == "TJS_Animatic":
                # TJS_Animatic는 시즌이 없으므로 바로 job 목록을 가져옴
                season_list = []  # 시즌 목록 없음
                # 시즌 선택 없이 바로 job 목록 가져오기
                self.jobComboBox.clear()
                self.jobComboBox.addItem("job선택")
                try:
                    if os.path.isdir(path):
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file.startswith("TJS")
                            and (file[3:].isdigit() or (len(file) > 4 and file[3] == '_' and file[4:].isdigit()))
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                except FileNotFoundError:
                    print(f"Directory not found: {path}")
            else:
                # 시즌 목록 가져오기 (작품별 패턴 매칭)
                season_list = []
                if os.path.isdir(path):
                    if selected_work == "BB":
                        season_list = [file for file in os.listdir(path) if "BB_Season" in file]
                    elif selected_work == "KOTH":
                        season_list = [file for file in os.listdir(path) if "KOTH_Season" in file]
                    elif selected_work == "Big_Mouth":
                        season_list = [file for file in os.listdir(path) if "BM_Season" in file]
                    elif selected_work == "TGN":
                        season_list = [file for file in os.listdir(path) if "GN_Season" in file]
                    elif selected_work == "MatingSeason":
                        season_list = [file for file in os.listdir(path) if "MS_Season" in file]
                    elif selected_work == "BB_Animatic":
                        season_list = [file for file in os.listdir(path) if "season" in file]
                    elif selected_work == "KOTH_Animatic":
                        season_list = [file for file in os.listdir(path) if "KOTH_SEASON" in file]
                    elif selected_work == "BM_Animatic":
                        season_list = [file for file in os.listdir(path) if "BM_SEASON" in file]
                    elif selected_work == "TGN_Animatic":
                        season_list = [file for file in os.listdir(path) if "TGN_Season" in file]
                    elif selected_work == "MS_Animatic":
                        season_list = [file for file in os.listdir(path) if "MS" in file and os.path.isdir(os.path.join(path, file))]
                    else:
                        # 일반적인 경우: 모든 디렉토리를 시즌으로 간주
                        season_list = [file for file in os.listdir(path) 
                                      if os.path.isdir(os.path.join(path, file)) 
                                      and not file.startswith('.')]

            season_list.sort()  # Sort the list
            for season in season_list:
                self.seasonComboBox.addItem(season)

        except FileNotFoundError:
            # Handle the case where the directory does not exist
            print(f"Directory not found: {path}")
            # Optionally, you can display a message to the user or log the error
        except Exception as e:
            print(f"Error updating season list: {e}")

    def update_job_list(self):
        selected_season = self.seasonComboBox.currentText()
        selected_work = self.workComboBox.currentText()
        
        # JSON에서 작품 기본 경로 가져오기
        base_path = self.get_work_path(selected_work)
        
        # The_Johnsons, TJS_Animatic는 시즌이 없으므로 시즌 선택 없이도 job 목록 가져오기
        if selected_work == "The_Johnsons":
            self.jobComboBox.clear()
            self.jobComboBox.addItem("job선택")
            path = base_path
            try:
                if os.path.isdir(path):
                    job_list = [
                        file for file in os.listdir(path)
                        if os.path.isdir(os.path.join(path, file))
                        and not file.startswith('.')
                        and file.startswith("TJS_")
                        and len(file) > 4
                        and file[4:].isdigit()
                        and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                    ]
                    job_list.sort()
                    for job in job_list:
                        self.jobComboBox.addItem(job)
            except FileNotFoundError:
                print(f"Directory not found: {path}")
            return
        
        if selected_work == "TJS_Animatic":
            self.jobComboBox.clear()
            self.jobComboBox.addItem("job선택")
            path = base_path
            try:
                if os.path.isdir(path):
                    job_list = [
                        file for file in os.listdir(path)
                        if os.path.isdir(os.path.join(path, file))
                        and not file.startswith('.')
                        and file.startswith("TJS")
                        and (file[3:].isdigit() or (len(file) > 4 and file[3] == '_' and file[4:].isdigit()))
                        and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                    ]
                    job_list.sort()
                    for job in job_list:
                        self.jobComboBox.addItem(job)
            except FileNotFoundError:
                print(f"Directory not found: {path}")
            return

        # 시즌이 있는 작품: job 목록은 늘 비우고 시즌을 골랐을 때만 그 시즌의 job (작품 → 시즌 → job). 작품을 바꾸거나
        # '시즌선택'으로 돌리면 'job선택'만. 예전에는 '시즌선택'이 아닌 글자를 시즌으로 여겨, 시즌 목록을 비울 때(clear가 빈
        # 글자로 보냄) 작품 폴더의 하위 폴더를 job으로 넣고 이어서 온 '시즌선택'에서는 그 목록을 그대로 두었음
        self.jobComboBox.clear()
        self.jobComboBox.addItem("job선택")
        if self._picked(self.seasonComboBox):
            try:
                # JSON에서 가져온 기본 경로와 시즌을 결합
                if base_path:
                    path = os.path.join(base_path, selected_season)
                else:
                    path = None

                if path and os.path.isdir(path):
                    if selected_work == "MS_Animatic":
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and 'ANIMATIC' in file.upper()
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                        return
                    elif selected_work == "TJS_Animatic":
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and 'ANIMATIC' in file.upper()
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)
                        return
                    else:
                        # 일반적인 경우
                        job_list = [
                            file for file in os.listdir(path)
                            if os.path.isdir(os.path.join(path, file))
                            and not file.startswith('.')
                            and file not in ["@eaDir", "EXPORT", "Yeson_BB_Model", "Yeson_GN_Model", "KOTH_library", "TEST_IB_4A", "KOTH_Main_Models", "Yeson_BM_Model", "Yeson_KOTH_Model", "A_Season13_IB_Model"]
                        ]
                        job_list.sort()
                        for job in job_list:
                            self.jobComboBox.addItem(job)

            except FileNotFoundError:
                # Handle the case where the directory does not exist
                print(f"Directory not found: {path}")
                # Optionally, you can display a message to the user or log the error
            except Exception as e:
                print(f"Error updating job list: {e}")

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            self.load_videos_from_folder(folder_path)

    def load_videos_from_folder(self, folder_path):
        self.playlist.clear()
        self.sidebar.clear()
        
        # 선택된 폴더 경로 저장 (썸네일 폴더 생성용)
        self.selected_folder_path = folder_path
        
        # 재귀적으로 폴더 내의 모든 비디오 파일 찾기 (드래그앤드롭과 동일한 방식, 번호 순서)
        video_files = self.get_video_files_from_folder(folder_path)
        read_failed = video_files is None  # 폴더를 읽지 못함 (창으로 알림) — 연결이 돌아오면 다시 읽기(F5)로 목록이 생김
        video_files = video_files or []
        
        if video_files:
            # 폴더 드래그앤드롭 시에는 기존 썸네일 폴더를 초기화하고 새로 설정 — 항목을 넣기 전에 (항목마다 이 자리를 기억)
            self.current_thumbnail_folder = None  # 기존 썸네일 폴더 초기화
            self._thumbnail_folder_problem = None  # 전에 연 job의 썸네일 폴더 문제는 이제 상관없음
            self.setup_thumbnail_folder()
            source = self._register_sidebar_source(video_list.ListSource("folder", folder_path))
        else:
            source = self._register_unread_folder(folder_path)  # 빈 폴더·읽지 못한 폴더
        
        # 사이드바에 파일들 추가
        self.playlist.extend(video_files)
        self._add_sidebar_videos([(os.path.basename(file_path), file_path, source) for file_path in video_files])
        self._sidebar_read_done(None)  # 방금 읽음 (앱이 다시 활성돼도 곧바로 또 읽지 않게)
        
        if self.playlist:
            self.current_playlist_index = 0
            self.open_file('A', self.playlist[0])
            self.sidebar.selectAll()
            self.schedule_background_thumbnail_loading()
            QMessageBox.information(self, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
        elif not read_failed:
            QMessageBox.warning(self, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")

    def play_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            selected_items.sort(key=lambda x: self.sidebar.row(x))
            self.playlist = [item.toolTip() for item in selected_items]
            self.current_playlist_index = 0
            self.is_playlist_playing = True
            self._playlist_played_any = False
            print(f"Play Selected: {len(selected_items)} files selected, starting playback")
            self.play_current_playlist_item()
        else:
            print("No files selected")
            # 사용자에게 선택된 파일이 없다는 것을 알림
            QMessageBox.information(self, "Play Selected", "Please select one or more files from the sidebar first.")

    def play_current_playlist_item(self):
        """선택 재생: 지금 차례의 영상을 열어 재생. 열 수 없는 영상은 건너뛰고 다음 영상으로 (되부르지 않고 반복).

        디스크에 없는 영상을 처음 만나면 남은 차례의 영상을 한 번에 확인해 없는 것을 모두 빼고 창 한 번·목록 다시 읽기 한 번
        (예전에는 없는 영상마다 창과 NAS 다시 읽기). 영상을 확인하지 못하면(NAS 연결 끊김·권한) 창으로 알리고 선택 재생을
        멈춤 (다음 영상도 그럴 것이므로 영상마다 창이 뜨지 않게). OpenCV가 열지 못한 영상은 open_file이 알리고 다음 영상으로.
        다음 영상을 정하는 동안(창이 떠 이벤트를 처리함) 보던 영상이 끝나도 선택 재생을 거기서 또 진행하지 않음
        (_playlist_resolving — 예전에는 같은 영상을 두 번 열고 하나를 건너뜀).
        """
        self._playlist_resolving = True
        try:
            self._play_playlist_from_current()
        finally:
            self._playlist_resolving = False

    def _play_playlist_from_current(self):
        while 0 <= self.current_playlist_index < len(self.playlist):
            current_file = self.playlist[self.current_playlist_index]
            try:
                os.stat(current_file)
            except OSError as e:
                gone, note = video_list.check_gone(current_file, e)
                if gone:
                    self._skip_missing_playlist_videos()
                    continue
                reason = f"{type(e).__name__}: {e}" + (f"\n{note}" if note else "")
                print(f"선택 재생할 영상을 확인하지 못함: {current_file} ({reason})")
                QMessageBox.critical(self, "영상을 열 수 없음",
                                     "선택 재생할 영상을 확인하지 못해 선택 재생을 멈춥니다 (NAS 연결 끊김·권한 등).\n"
                                     f"영상: {current_file}\n이유: {reason}")
                self._end_playlist_mode()
                return
            print(f"Playing playlist item {self.current_playlist_index + 1}/{len(self.playlist)}: {os.path.basename(current_file)}")
            print(f"is_playlist_playing before: {self.is_playlist_playing}")
            
            # 플레이리스트 재생 상태 확실히 설정
            self.is_playlist_playing = True
            
            # 사이드바에서 현재 파일 강조
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                is_current = paths.same_path(item.toolTip(), current_file)
                font = item.font()
                font.setBold(is_current)
                item.setFont(font)
                if is_current:
                    item.setForeground(QColor("red"))  # 현재 재생 중인 항목은 빨간색
                else:
                    # 현재 테마에 맞는 색상으로 설정
                    if self.current_theme == 'dark':
                        item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
                    else:
                        item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상
            
            # 파일 열기 및 재생
            try:
                if self.open_file('A', current_file):
                    self._playlist_played_any = True
                    # 첫 번째 프레임으로 이동
                    self.seek_to_frame(1)
                    self.play_video()
                    self.playSelectedPauseButton.setText('Selected Pause')
                    self.playSelectedPauseButton.setStyleSheet("background-color: yellow;")
                    print(f"Successfully started playing: {os.path.basename(current_file)}")
                    print(f"is_playlist_playing after: {self.is_playlist_playing}")
                    return
                # 열지 못함 (open_file이 창으로 알림) — 예전에는 보던 영상을 처음부터 다시 재생했음
            except Exception as e:
                print(f"Error playing file {current_file}: {e}")
                traceback.print_exc()
                QMessageBox.warning(self, "Play Error", f"Failed to play file: {os.path.basename(current_file)}\nError: {str(e)}")
            # 오류 발생 시 다음 파일로 이동
            self.current_playlist_index += 1
        print(f"Playlist index {self.current_playlist_index} is past the end ({len(self.playlist)} items)")
        self._finish_playlist()

    def _skip_missing_playlist_videos(self):
        """선택 재생 중 디스크에 없는 영상을 만남 (지금 차례): 남은 차례의 영상도 한 번에 확인해 없어진 것을 모두 선택 재생에서
        빼고 창 한 번, 목록 다시 읽기 한 번. 확인하지 못한 영상(공유가 끊김 등)은 남겨 그 차례에 알림."""
        current = self.playlist[self.current_playlist_index]
        gone = [current]
        kept = []
        for path in self.playlist[self.current_playlist_index + 1:]:
            try:
                os.stat(path)
            except OSError as e:
                if video_list.is_gone(path, e):
                    gone.append(path)
                    continue
            kept.append(path)
        self.playlist = self.playlist[:self.current_playlist_index] + kept
        print(f"선택 재생: 디스크에 없는 영상 {len(gone)}개를 건너뜀:\n" + "\n".join(gone))
        lines = gone[:10] + ([f"… 외 {len(gone) - 10}개"] if len(gone) > 10 else [])
        QMessageBox.warning(self, "영상 없음",
                            f"디스크에 없는 영상 {len(gone)}개를 건너뜁니다:\n" + "\n".join(lines) + "\n목록을 다시 읽습니다.")
        self.refresh_sidebar()

    def _end_playlist_mode(self):
        """선택 재생 상태만 끝냄 (보던 영상은 그대로)."""
        self.is_playlist_playing = False
        self.reset_sidebar_colors()
        self.playSelectedPauseButton.setText('Selected Play'); self.playSelectedPauseButton.setStyleSheet("")
        if not self.timer.isActive():
            # 창이 떠 있는 동안 보던 영상이 끝나 재생이 이미 멈춤 → 재생 버튼이 'Pause'로 남지 않게
            self.playPauseButton.setText('Play'); self.playPauseButton.setStyleSheet("")
            if hasattr(self, 'overlayPlayPause'):
                self.overlayPlayPause.setText('▶')

    def _finish_playlist(self):
        """선택 재생 끝. 재생한 영상이 있으면 예전처럼 멈추고 알림. 하나도 재생하지 못했으면(모두 없거나 열 수 없음 — 그때마다
        창으로 알림) 보던 영상은 멈추지 않고 선택 재생만 끝냄."""
        if not self._playlist_played_any:
            print("선택 재생: 재생할 수 있는 영상이 없어 선택 재생을 끝냄 (보던 영상은 그대로)")
            self._end_playlist_mode()
            return
        print("Reached end of playlist, stopping playback")
        self.is_playlist_playing = False
        self.stop_video()
        self.reset_sidebar_colors()
        QMessageBox.information(self, "Playlist Complete", "All selected files have been played.")

    def reset_sidebar_colors(self):
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            font = item.font(); font.setBold(False)
            item.setFont(font)
            # 현재 테마에 맞는 색상으로 설정
            if self.current_theme == 'dark':
                item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
            else:
                item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상

    def play_next_in_playlist(self):
        if self._playlist_resolving:
            # 선택 재생이 다음 영상을 정하는 중(창이 떠 있음)에 영상이 끝남: 그 반복이 이어서 엶 — 여기서 또 진행하면 두 번 엶
            print("선택 재생: 다음 영상을 정하는 중에 영상이 끝남 — 진행은 그 반복이 함")
            return
        if self.current_playlist_index < len(self.playlist) - 1:
            self.current_playlist_index += 1
            print(f"Moving to next item in playlist: {self.current_playlist_index + 1}/{len(self.playlist)}")
            self.play_current_playlist_item()
        else:
            self._finish_playlist()

    def initialize_sidebar_width(self):
        """기본 사이드바 폭을 초기화합니다."""
        # default_sidebar_width가 없으면 초기화
        if not hasattr(self, 'default_sidebar_width') or self.default_sidebar_width is None:
            if hasattr(self, 'sidebar') and self.sidebar is not None:
                self.default_sidebar_width = self.sidebar.width()
                print(f"기본 사이드바 폭 초기화: {self.default_sidebar_width}")
            else:
                # sidebar가 아직 없으면 기본값 설정
                self.default_sidebar_width = 200

    def load_selected_item_to_video_a(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            self.open_file('A', selected_items[0].toolTip())

    def load_bookmarks(self):
        try:
            if os.path.exists(self.bookmarks_file):
                with open(self.bookmarks_file, 'r', encoding='utf-8') as f:
                    self.bookmarks = json.load(f)
            else:
                self.bookmarks = []
        except Exception as e:
            print(f"Bookmark load error: {e}")
            self.bookmarks = []

    def save_bookmarks(self):
        try:
            with open(self.bookmarks_file, 'w', encoding='utf-8') as f:
                json.dump(self.bookmarks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Bookmark save error: {e}")

    def add_bookmark(self):
        # 현재 폴더를 북마크에 추가
        folder_path = QFileDialog.getExistingDirectory(self, "북마크할 폴더 선택")
        folder_path = paths.normalize_native(folder_path)
        if folder_path:
            if not paths.contains_path(self.bookmarks, folder_path):
                self.bookmarks.append(folder_path)
                self.save_bookmarks()
                QMessageBox.information(self, "북마크 추가", f"{folder_path}\n폴더가 북마크에 추가되었습니다.")
            else:
                QMessageBox.information(self, "이미 북마크됨", f"{folder_path}\n폴더는 이미 북마크에 있습니다.")

    def show_bookmarks(self):
        if not self.bookmarks:
            QMessageBox.information(self, "북마크 없음", "저장된 북마크가 없습니다.")
            return
        
        # 북마크 선택 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("북마크 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("북마크된 폴더 목록:")
        layout.addWidget(label)
        
        # 북마크 리스트
        list_widget = QListWidget()
        for bookmark in self.bookmarks:
            item = QListWidgetItem(bookmark)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 폴더 열기 버튼
        open_button = QPushButton("폴더 열기")
        open_button.clicked.connect(lambda: self.open_bookmark_folder(list_widget, dialog))
        button_layout.addWidget(open_button)
        
        # 삭제 버튼
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(lambda: self.delete_bookmark(list_widget))
        button_layout.addWidget(delete_button)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        # 더블클릭으로도 폴더 열기 가능
        list_widget.itemDoubleClicked.connect(lambda item: self.open_bookmark_folder(list_widget, dialog))
        
        dialog.exec_()

    def open_bookmark_folder(self, list_widget, dialog):
        """선택된 북마크 폴더를 엽니다"""
        current_item = list_widget.currentItem()
        if current_item:
            folder_path = current_item.text()
            
            # 기존 백그라운드 스레드들을 안전하게 정리
            self.cleanup_background_threads()
            
            # 스레드 정리 후 추가 대기 시간
            import time
            time.sleep(0.5)
            
            # UI 업데이트 처리
            QApplication.processEvents()
            
            self.load_videos_from_folder(folder_path)
            # 북마크 폴더는 해당 폴더에 썸네일 생성
            self.setup_thumbnail_folder_for_bookmark(folder_path)
            self.schedule_background_thumbnail_loading()
            dialog.close()

    def setup_thumbnail_folder_for_bookmark(self, folder_path):
        """북마크 폴더용 썸네일 폴더를 설정합니다."""
        self._thumbnail_folder_problem = None  # 전에 연 job의 썸네일 폴더 문제는 이제 상관없음
        try:
            thumbnail_folder = thumbnails.ensure_folder(folder_path)
            self.current_thumbnail_folder = thumbnail_folder
            print(f"북마크 썸네일 폴더 설정: {thumbnail_folder}")
            return True
        except Exception as e:
            print(f"북마크 썸네일 폴더 설정 중 오류: {e}")
            self.current_thumbnail_folder = None
            return False

    def delete_bookmark(self, list_widget):
        """선택된 북마크를 삭제합니다"""
        current_item = list_widget.currentItem()
        if current_item:
            folder_path = current_item.text()
            reply = QMessageBox.question(
                self, 
                "북마크 삭제", 
                f"다음 폴더를 북마크에서 삭제하시겠습니까?\n\n{folder_path}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 북마크에서 제거
                if folder_path in self.bookmarks:
                    self.bookmarks.remove(folder_path)
                    self.save_bookmarks()
                
                # 리스트에서 제거
                list_widget.takeItem(list_widget.row(current_item))
                
                QMessageBox.information(self, "삭제 완료", "북마크가 삭제되었습니다.")
        else:
            QMessageBox.warning(self, "선택 필요", "삭제할 북마크를 선택해주세요.")

    def setup_shared_config(self):
        """공유 설정 폴더를 정하고 작품 경로(Windows는 변환표도)를 읽어 창에 넣습니다 (동기: 이 스레드에서 바로 읽음).

        = gather_shared_config(파일·NAS) + _apply_shared_config(창·활성 변환표). 창은 띄우지 않고 문제를
        self.shared_config_problem에 남깁니다 (창 표시 후 resolve_shared_config_problem이 알림).
        읽기에 실패해도 공유 파일을 기본값으로 덮어쓰지 않습니다. 시작할 때는 start_shared_config_load(백그라운드).
        """
        self._apply_shared_config(SharedConfigState())  # 먼저 빈 상태로 (예상 못 한 예외가 나도 이전 값이 남지 않게)
        self._apply_shared_config(gather_shared_config())

    def _first_work_item(self):
        """작품 목록의 첫 항목: 불러오는 동안은 "공유 설정 불러오는 중…", 그 뒤는 "작품선택" (골라도 아무 일 없음)."""
        return LOADING_WORK_ITEM if getattr(self, "shared_config_loading", False) else WORK_PLACEHOLDER

    def set_shared_config_loading_state(self):
        """공유 설정을 아직 읽지 않은 빈 '불러오는 중' 상태 (파일·NAS 접근 없음). start_shared_config_load가 채움."""
        self._apply_shared_config(SharedConfigState())
        self.shared_config_loading = True

    def _apply_shared_config(self, state):
        """(GUI 스레드) gather_shared_config 결과를 창에 넣고 (Windows) 이 PC의 변환표를 활성화합니다."""
        self.work_paths = state.work_paths
        self.shared_config_problem = state.shared_config_problem
        self.path_map_problem = state.path_map_problem
        self.config_dir_candidates = state.config_dir_candidates
        self.config_dir_search_failed = state.config_dir_search_failed
        self.config_dir_search_problems = state.config_dir_search_problems
        self.work_paths_config_dir = state.config_dir
        if state.config_dir is None:
            self.work_paths_file = None
            self.work_paths_password_file = None
        else:
            self.work_paths_file = os.path.join(state.config_dir, shared_config.WORK_PATHS_FILENAME)
            self.work_paths_password_file = os.path.join(state.config_dir, shared_config.PASSWORD_FILENAME)
        if state.activate_path_map:
            paths.activate(state.path_map)
        if state.mount_map is not None:
            paths.activate_mount_map(state.mount_map)

    def start_shared_config_load(self):
        """(창 표시 후) 공유 설정을 백그라운드 스레드에서 읽고, 끝나면 GUI 스레드에서 넣은 뒤 문제를 알립니다.

        읽는 동안(NAS가 느리거나 서버가 꺼진 드라이브가 있으면 수십 초) 창은 그대로 쓸 수 있고, 작품 경로 관리·
        공유 설정 폴더 변경은 안내만 합니다.
        """
        if self._shared_config_closed:
            timing_log.startup("창이 이미 닫혀 공유 설정을 불러오지 않음")
            return
        if self._shared_config_load is not None:
            raise RuntimeError("공유 설정을 이미 불러오는 중입니다 (start_shared_config_load를 두 번 부름)")
        self.shared_config_loading = True
        self.setWindowTitle(LOADING_TITLE)
        timing_log.startup("공유 설정 불러오기 시작 (백그라운드)")
        load = SharedConfigLoad()
        load.loaded.connect(self._on_shared_config_loaded)  # 창은 GUI 스레드 → 대기열을 거쳐 GUI 스레드에서 실행
        self._shared_config_load = load
        load.start()

    def _on_shared_config_loaded(self, state):
        """(GUI 스레드) 백그라운드에서 읽은 공유 설정을 넣고 작품 목록을 채운 뒤 문제를 알립니다.

        창이 닫힌 뒤에 온 결과는 버립니다 (활성 변환표도 바꾸지 않음).
        """
        self._shared_config_load = None  # 스레드 객체는 끝날 때까지 SharedConfigLoad._running이 붙잡음
        if self._shared_config_closed:
            timing_log.startup(f"공유 설정 불러오기 끝 ({state.elapsed:.2f}초) — 창이 이미 닫혀 결과를 버림")
            return
        if QThread.currentThread() is not QApplication.instance().thread():
            raise RuntimeError("공유 설정 결과를 GUI 스레드가 아닌 곳에서 넣으려 했습니다")
        self._apply_shared_config(state)
        self.shared_config_loading = False
        self.shared_config_load_seconds = state.elapsed
        self.reload_work_combo()
        problem = "있음" if (state.shared_config_problem or state.path_map_problem) else "없음"
        timing_log.startup(
            f"공유 설정 불러오기 끝 ({state.elapsed:.2f}초): 설정 폴더 {state.config_dir or '없음'}, "
            f"작품 {len(state.work_paths)}개, 문제 {problem}"
        )
        self.resolve_shared_config_problem(works_not_opening=state.works_not_opening)

    def wait_for_shared_config_load(self, timeout_ms):
        """(창을 닫을 때) 실행 중인 공유 설정 불러오기를 timeout_ms까지만 기다립니다 → 끝났으면 True.

        끝나지 않으면(NAS 응답 대기 등) 로그만 남기고 False — 스레드는 SharedConfigLoad._running이 끝날 때까지
        붙잡고 있어 파괴되지 않고, 늦게 온 결과는 _on_shared_config_loaded가 버립니다.
        """
        load = self._shared_config_load
        if load is None or not load.isRunning():
            return True
        timing_log.log("닫기", "공유 설정 불러오기가 끝나기를 기다리는 중…")
        if load.wait(timeout_ms):
            timing_log.log("닫기", "공유 설정 불러오기 끝남")
            return True
        timing_log.log("닫기", f"공유 설정 불러오기가 {timeout_ms / 1000:g}초 안에 끝나지 않았습니다 — "
                             "결과는 버리고 계속 닫습니다 (NAS 응답을 기다리는 중일 수 있음)")
        return False

    def _shared_config_busy(self):
        """공유 설정을 불러오는 중이면 안내하고 True (반쯤 읽은 상태로는 아무것도 하지 않음)."""
        if getattr(self, "shared_config_loading", False):
            QMessageBox.information(self, "공유 설정", LOADING_NOTICE)
            return True
        return False

    def _update_shared_config_title(self):
        if getattr(self, "shared_config_loading", False):
            self.setWindowTitle(LOADING_TITLE)
            return
        title = "Yeson Checker"
        if self.shared_config_problem:
            title += " — 공유 설정 오류 (작품 목록 없음)"
        if getattr(self, "path_map_problem", None):
            title += " — 변환표 오류 (작품 경로 관리에서 자동 설정)" if paths.IS_WINDOWS else " — 변환표 오류"
        self.setWindowTitle(title)

    def resolve_shared_config_problem(self, works_not_opening=None):
        """창 표시 후 공유 설정 문제를 알립니다.

        Windows: 설정 폴더를 못 찾았으면 고르게 하고(찾은 후보가 여럿이면 그 목록에서), 변환표가 없거나
        열리지 않는 작품이 있으면 연결된 드라이브로 변환표 자동 설정을 제안합니다.
        works_not_opening: 시작할 때 백그라운드에서 미리 계산한 '열리지 않는 작품' (None이면 여기서 확인).
        """
        if self.shared_config_problem and paths.IS_WINDOWS and not shared_config.is_valid_config_dir(self.work_paths_config_dir):
            if self.config_dir_candidates:
                picked = self._pick_config_dir_candidate()
            else:
                reason = self.shared_config_problem
                if self.config_dir_search_failed:
                    reason = "연결된 네트워크 드라이브에서 공유 설정 폴더를 찾지 못했습니다.\n\n" + reason
                reason += self._config_dir_search_problems_text()
                picked = self.choose_shared_config_dir(reason)
            if picked:
                return  # _use_config_dir가 문제 알림·변환표 자동 설정까지 처리함
        if self.shared_config_problem:
            QMessageBox.critical(
                self,
                "공유 설정 오류",
                f"{self._shared_config_problem_text()}\n\n작품 목록 없이 계속합니다. 파일 직접 열기와 드래그는 쓸 수 있습니다.",
            )
            return
        if not paths.IS_WINDOWS and self.path_map_problem:
            # (Mac) path_map.json을 읽지 못해 공유 설정의 앞부분을 /<이름>으로만 정함 (_load_mac_mount_map)
            QMessageBox.warning(self, "변환표 오류", self.path_map_problem)
            return
        self._offer_path_map_setup(works_not_opening)

    def _config_dir_search_problems_text(self):
        """공유 설정 폴더 자동 찾기 중 확인하지 못한 곳 (폴더를 고르게 할 때 덧붙임)."""
        problems = getattr(self, "config_dir_search_problems", None)
        if not problems:
            return ""
        return "\n\n확인하지 못한 곳:\n" + "\n".join(problems)

    def _shared_config_problem_text(self):
        """공유 설정 오류 창에 보일 내용: 공유 설정 문제 + (함께 있으면) 변환표 문제."""
        message = self.shared_config_problem
        if self.path_map_problem:
            message += f"\n\n{self.path_map_problem}"
        return message

    def choose_shared_config_dir(self, reason=None):
        """(Windows) 공유 설정 폴더를 고르게 하고 PC별 설정에 저장합니다. 골랐으면 True.

        네트워크 드라이브·UNC 폴더, 또는 실제 위치가 UNC인 로컬 링크(Harmony용 C:\\USA_DB 아래)를 고를 수 있음.
        """
        if self._shared_config_busy():
            return False
        if reason:
            QMessageBox.information(
                self,
                "공유 설정 폴더 선택",
                f"{reason}\n\n작품 경로 설정(work_paths.json)이 들어 있는 공유 설정 폴더(.yesoncheck)를 골라 주세요.",
            )
        while True:
            folder = QFileDialog.getExistingDirectory(self, "공유 설정 폴더(.yesoncheck) 선택")
            if not folder:
                return False
            try:
                config_dir = config_dir_from_chosen_folder(folder)
                shared_config.validate_config_dir(config_dir)
            except (paths.PathMapError, shared_config.SharedConfigError) as exc:
                QMessageBox.warning(self, "다른 폴더를 고르세요", str(exc))
                continue
            return self._use_config_dir(config_dir)

    def _use_config_dir(self, config_dir):
        """(Windows) 고른 공유 설정 폴더를 PC별 설정에 저장하고 다시 읽습니다. 저장했으면 True."""
        try:
            shared_config.save_local_settings({"config_dir": config_dir})
        except (shared_config.SharedConfigError, OSError) as exc:
            QMessageBox.critical(self, "PC별 설정 저장 실패", f"{exc}\n\n{traceback.format_exc()}")
            return False
        self.setup_shared_config()
        self.reload_work_combo()
        if self.shared_config_problem:
            QMessageBox.critical(self, "공유 설정 오류", self._shared_config_problem_text())
        else:
            self._offer_path_map_setup()
        return True

    def _pick_config_dir_candidate(self):
        """(Windows) 연결된 드라이브에서 찾은 공유 설정 폴더가 여럿일 때 고르게 합니다. 골랐으면 True."""
        manual = "직접 고르기..."
        item, ok = QInputDialog.getItem(
            self,
            "공유 설정 폴더 선택",
            "연결된 네트워크 드라이브에서 공유 설정 폴더를 여러 개 찾았습니다. 쓸 폴더를 고르세요:"
            + self._config_dir_search_problems_text(),
            list(self.config_dir_candidates) + [manual],
            0,
            False,
        )
        if not ok:
            return False
        if item == manual:
            return self.choose_shared_config_dir()
        return self._use_config_dir(item)

    def _works_not_opening(self):
        """(Windows) 이 PC에서 열리지 않는 작품 목록 ['작품: 이유'] (활성 변환표로, 이 스레드에서 바로 확인).

        GUI 스레드에서 공유 루트마다 최대 SHARE_PROBE_TIMEOUT_S초를 기다릴 수 있어 그동안 대기 커서."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return list_works_not_opening(self.work_paths, paths.to_native)
        finally:
            QApplication.restoreOverrideCursor()

    def _offer_path_map_setup(self, works_not_opening=None):
        """(Windows) 변환표가 없거나 열리지 않는 작품이 있으면 변환표 자동 설정을 제안합니다.

        works_not_opening: 시작할 때 백그라운드에서 미리 계산한 목록 (None이면 여기서 확인).
        """
        if not paths.IS_WINDOWS:
            return
        if self.path_map_problem:
            needed = True
        elif works_not_opening is not None:
            needed = bool(works_not_opening)
        else:
            needed = bool(self._works_not_opening())
        if needed:
            self.auto_setup_path_map(ask_password=True, startup=True)

    def _report_path_map_problem(self, parent, note=None):
        """(Windows, startup) 저장 없이 끝날 때 변환표 문제를 한 번만 알립니다 (호출하는 쪽에서 self.path_map_problem을 확인)."""
        message = self.path_map_problem
        if note:
            message = f"{message}\n\n{note}"
        QMessageBox.critical(parent, "변환표 오류", message)

    def auto_setup_path_map(self, ask_password, startup=False, parent=None):
        """(Windows) 연결된 네트워크 드라이브로 변환표 짝을 찾아 확인 창을 띄우고, 승인되면 path_map.json에 합쳐 저장합니다.

        startup이면 기존 변환표에 더할 것이 없을 때 창을 띄우지 않고 변환표 문제만 알립니다(저장 없이 끝나는 모든
        경로에서 한 번만). 저장했으면 True(다시 읽기에 실패해도 저장은 된 것이므로 True이며, 공유 설정 오류를 따로 알립니다).

        확인 창·비밀번호는 몇 분이 걸릴 수 있으므로, 저장 직전에 path_map.json을 다시 읽어 그 내용에 합칩니다
        (그 사이 다른 PC가 쓴 항목을 지우지 않도록, 백업 여부도 다시 읽은 내용으로 정함).
        """
        parent = parent or self
        config_dir = self.work_paths_config_dir
        map_file = os.path.join(config_dir, paths.PATH_MAP_FILENAME)

        def read_map_file():
            """→ (existing, existing_error) 또는 읽지 못하면 오류 창을 띄우고 None."""
            try:
                return path_map_setup.read_existing(config_dir)
            except OSError as exc:
                QMessageBox.critical(parent, "변환표를 읽지 못함", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")
                return None

        def report_save_failure(exc):
            QMessageBox.critical(parent, "변환표 저장 실패", f"{map_file}\n\n{exc}\n\n{traceback.format_exc()}")

        read = read_map_file()
        if read is None:
            return False
        existing, existing_error = read
        shares, share_problems = path_map_setup.available_shares()  # 네트워크 드라이브 + 시스템 드라이브의 UNC 링크
        progress = QProgressDialog("연결된 네트워크 드라이브에서 작품 폴더를 찾는 중…", "취소", 0, 100, parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)
        progress.setValue(0)  # 0.5초 뒤 저절로 보이게 — 응답 없는 공유 루트를 기다리는 동안에도 '취소'를 누를 수 있게

        def on_progress(done, total):
            progress.setValue(int(done * 100 / total))
            QApplication.processEvents()
            return not progress.wasCanceled()

        def on_wait():
            # 공유 루트가 응답하기를 기다리는 동안(최대 SHARE_PROBE_TIMEOUT_S초): 진행 창을 그리고 취소를 받음
            QApplication.processEvents()
            return not progress.wasCanceled()

        timing_log.log("변환표 자동 설정", f"작품 {len(self.work_paths)}개의 폴더를 공유 {len(shares)}개에서 찾는 중…")
        started = time.perf_counter()
        try:
            proposal = path_map_setup.propose_mapping(self.work_paths, shares, progress=on_progress, on_wait=on_wait)
            timing_log.log("변환표 자동 설정", f"찾기 끝 ({timing_log.since(started)}): 짝 {len(proposal.pairs)}개")
        except path_map_setup.SetupCancelled:
            timing_log.log("변환표 자동 설정", f"찾기 취소됨 ({timing_log.since(started)})")
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        finally:
            progress.close()
            progress.deleteLater()
        proposal.share_problems = share_problems + proposal.share_problems

        if startup and not path_map_setup.has_additions(existing, proposal):
            if self.path_map_problem:
                self._report_path_map_problem(
                    parent, note="연결된 네트워크 드라이브에서 새로 찾은 짝이 없습니다. NAS 드라이브 연결을 확인하세요.",
                )
            return False
        _ok, rejected = path_map_setup.split_mergeable(existing, proposal.ordered_default_choices())
        blocked = {mac_prefix: reason for mac_prefix, _unc, reason in rejected}
        dialog = PathMapSetupDialog(proposal, existing_error, parent, blocked=blocked)
        if dialog.exec_() != QDialog.Accepted:
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        chosen = dialog.chosen()
        try:
            path_map_setup.merge_path_map(existing, chosen)  # 비밀번호를 묻기 전에: 합칠 수 없는 짝을 골랐으면 여기서 알림
        except paths.PathMapError as exc:
            report_save_failure(exc)
            return False
        if ask_password and not self._confirm_work_paths_password(parent):
            if startup and self.path_map_problem:
                self._report_path_map_problem(parent)
            return False
        read = read_map_file()  # 확인 창·비밀번호 사이에 다른 PC가 바꿨을 수 있음 → 저장 직전 내용에 합침
        if read is None:
            return False
        fresh, fresh_error = read
        try:
            data = path_map_setup.merge_path_map(fresh, chosen)
            backup = path_map_setup.save_path_map(config_dir, data, backup_existing=fresh_error is not None)
        except (paths.PathMapError, OSError) as exc:
            report_save_failure(exc)
            return False

        self.setup_shared_config()
        self.reload_work_combo()
        message = f"변환표를 저장했습니다: {map_file}"
        if backup:
            message += f"\n원래 파일은 {backup}으로 보관했습니다."
        if self.shared_config_problem:
            # 변환표는 저장됐지만 공유 설정을 다시 읽다가 문제가 생김 (예: NAS 연결 끊김) — 저장은 됐다고 알림
            QMessageBox.critical(
                parent, "공유 설정 오류",
                f"{message}\n\n하지만 공유 설정을 다시 읽지 못했습니다:\n{self.shared_config_problem}",
            )
            return True
        broken = self._works_not_opening()
        if broken:
            QMessageBox.warning(parent, "변환표 저장됨 — 열리지 않는 작품", message + "\n\n아직 열리지 않는 작품:\n" + "\n".join(broken))
        else:
            QMessageBox.information(parent, "변환표 저장됨", message)
        return True

    def reload_work_combo(self):
        """작품 콤보박스를 self.work_paths로 다시 채웁니다."""
        self.workComboBox.blockSignals(True)
        self.workComboBox.clear()
        self.workComboBox.addItem(self._first_work_item())
        for work_name in sorted(self.work_paths.keys()):
            self.workComboBox.addItem(work_name)
        self.workComboBox.blockSignals(False)
        self._update_shared_config_title()
        self.update_season_list()

    def save_work_paths(self, parent=None):
        """작품 경로를 공유 파일에 저장합니다. 실패하면 오류 창을 띄우고 False."""
        try:
            shared_config.write_work_paths(self.work_paths_file, self.work_paths)
            return True
        except OSError:
            QMessageBox.critical(parent or self, "작품 경로 저장 실패", f"{self.work_paths_file}\n\n{traceback.format_exc()}")
            return False

    def hash_password(self, password):
        """비밀번호를 해시화합니다."""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def load_password_hash(self):
        """저장된 비밀번호 해시. 파일이 없으면 None(최초 설정). 읽기 실패는 예외로 올립니다."""
        if not os.path.exists(self.work_paths_password_file):
            return None
        with open(self.work_paths_password_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('password_hash', None)

    def save_password_hash(self, password_hash):
        """비밀번호 해시를 저장합니다 (공유 설정 폴더는 이미 있어야 함). 실패는 예외로 올립니다."""
        with open(self.work_paths_password_file, 'w', encoding='utf-8') as f:
            json.dump({'password_hash': password_hash}, f, ensure_ascii=False, indent=2)

    def verify_password(self, password):
        """비밀번호를 확인합니다."""
        stored_hash = self.load_password_hash()
        if stored_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            return True
        return self.hash_password(password) == stored_hash

    def set_password(self, password):
        """비밀번호를 설정합니다."""
        password_hash = self.hash_password(password)
        self.save_password_hash(password_hash)

    def get_work_path(self, work_name):
        """작품 경로를 이 PC에서 여는 경로로 돌려줍니다 (Windows: 변환표로 UNC 변환, Mac: 공유를 제자리가 아닌 곳에 붙인
        Mac은 그곳 — mac_mounts).

        변환하지 못하거나 폴더가 없으면 오류 창을 한 번 띄우고 ""를 돌려줍니다.
        """
        stored = self.work_paths.get(work_name, "")
        if not stored:
            return ""
        try:
            native = paths.to_native(stored)
        except paths.PathMapError as exc:
            self._report_work_path_problem(f"작품 '{work_name}'의 경로를 이 PC 경로로 바꿀 수 없습니다.\n\n{exc}")
            return ""
        if paths.IS_WINDOWS and not os.path.isdir(native):
            self._report_work_path_problem(
                f"작품 '{work_name}' 폴더를 열 수 없습니다.\n\n이 PC 경로: {native}\n공유 설정 경로: {stored}\n\n"
                "NAS 연결과 path_map.json을 확인하세요."
            )
            return ""
        if not paths.IS_WINDOWS and not os.path.isdir(native):
            # (Mac) 빈 시즌 목록만 보이지 않게: 어디를 찾아봤는지(이 Mac에서 공유가 붙은 곳)와 함께 알림
            self._report_work_path_problem(
                f"작품 '{work_name}' 폴더를 열 수 없습니다.\n\n이 Mac 경로: {native}\n공유 설정 경로: {stored}\n\n"
                f"{paths.describe_mac_path(stored)}\n\nNAS 연결을 확인하세요."
            )
            return ""
        return native

    def _report_work_path_problem(self, message):
        """작품 하나를 고를 때 시즌·job·목록이 각각 같은 경로를 물으므로 같은 오류는 한 번만 보여 줍니다."""
        shown = self.__dict__.setdefault("_work_path_problems_shown", set())
        if message in shown:
            return
        shown.add(message)
        QMessageBox.critical(self, "작품 경로 오류", message)

    def _stored_work_path_or_warn(self, folder_path, parent):
        """고른 폴더를 공유 설정에 저장할 Mac 경로로 바꿉니다. 못 바꾸면 오류 창을 띄우고 None."""
        try:
            return paths.to_canonical(folder_path)
        except paths.PathMapError as exc:
            QMessageBox.critical(parent, "경로를 저장할 수 없음", f"고른 폴더를 공유 설정에 저장할 경로로 바꾸지 못했습니다.\n\n{exc}")
            return None

    def _refresh_work_path_table(self, table):
        table.clear()
        for work_name, path in sorted(self.work_paths.items()):
            text = f"{work_name}: {path}"
            if paths.IS_WINDOWS:
                try:
                    text += f"\n    → {paths.to_native(path)}"
                except paths.PathMapError:
                    text += "\n    → 변환표에 없음 (path_map.json 확인)"
            else:
                # (Mac) 공유를 다른 곳에 붙인 Mac에서만 이 Mac에서 여는 경로를 덧붙임 (같으면 예전처럼 한 줄)
                try:
                    native = paths.to_native(path)
                except paths.PathMapError:
                    text += "\n    → 이 Mac에서 열 곳을 정하지 못함 (맞는 공유가 여럿 — 시작 로그의 [공유] 줄 확인)"
                else:
                    if native != path:
                        text += f"\n    → {native}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, work_name)
            table.addItem(item)

    def _confirm_work_paths_password(self, parent=None):
        """작품 경로 관리 비밀번호를 확인합니다 (파일이 없으면 최초 설정). 확인되면 True. 문제는 창으로 알립니다."""
        parent = parent or self
        try:
            password_hash = self.load_password_hash()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(parent, "비밀번호 파일 오류", f"비밀번호 파일을 읽지 못했습니다:\n{self.work_paths_password_file}\n\n{exc}")
            return False

        if password_hash is None:
            # 비밀번호가 설정되지 않은 경우, 초기 비밀번호 설정
            password, ok = QInputDialog.getText(
                parent,
                "비밀번호 설정",
                "작품 경로 관리를 위한 비밀번호를 설정하세요:\n(처음 한 번만 설정하면 됩니다)",
                echo=QLineEdit.Password
            )
            if not ok or not password:
                return False

            password_confirm, ok = QInputDialog.getText(
                parent,
                "비밀번호 확인",
                "비밀번호를 다시 입력하세요:",
                echo=QLineEdit.Password
            )
            if not ok:
                return False

            if password != password_confirm:
                QMessageBox.warning(parent, "오류", "비밀번호가 일치하지 않습니다.")
                return False

            try:
                self.set_password(password)
            except OSError as exc:
                QMessageBox.critical(parent, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
                return False
            QMessageBox.information(parent, "설정 완료", "비밀번호가 설정되었습니다.")
            return True

        # 비밀번호 입력 요청
        password, ok = QInputDialog.getText(
            parent,
            "비밀번호 입력",
            "작품 경로 관리를 위해 비밀번호를 입력하세요:",
            echo=QLineEdit.Password
        )
        if not ok:
            return False
        if not self.verify_password(password):
            QMessageBox.warning(parent, "오류", "비밀번호가 올바르지 않습니다.")
            return False
        return True

    def manage_work_paths(self):
        """작품 경로 관리 다이얼로그를 표시합니다."""
        if self._shared_config_busy():
            return
        # 공유 설정에 문제가 있으면 관리 금지 (깨진 파일을 빈 목록으로 덮어쓰거나 새 비밀번호를 받지 않도록)
        if self.shared_config_problem or self.work_paths_config_dir is None:
            QMessageBox.warning(
                self, "작품 경로 관리",
                f"공유 설정에 문제가 있어 작품 경로를 관리할 수 없습니다.\n\n{self.shared_config_problem or '공유 설정 폴더 없음'}",
            )
            return
        if not self._confirm_work_paths_password():
            return

        # 비밀번호 확인 후 다이얼로그 표시
        dialog = QDialog(self)
        dialog.setWindowTitle("작품 경로 관리")
        dialog.setModal(True)
        dialog.setMinimumSize(700, 500)
        
        # 다크 테마 스타일 적용
        dialog.setStyleSheet("""
QDialog {
    background: #232323;
    color: #e0e0e0;
}
QLabel {
    color: #e0e0e0;
    background: transparent;
}
QPushButton {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    color: #fafafa;
    font-weight: 500;
    padding: 8px 16px;
}
QPushButton:hover {
    background: #353535;
    border: 1px solid #ff9900;
    color: #ff9900;
}
QPushButton:pressed {
    background: #1a1a1a;
    border: 1px solid #ff9900;
}
QListWidget {
    background: #232323;
    border: 1px solid #444;
    color: #fafafa;
    selection-background-color: #444;
    selection-color: #ff9900;
    alternate-background-color: #2a2a2a;
}
QListWidget::item:selected {
    background: #444;
    color: #ff9900;
}
QListWidget::item:hover {
    background: #353535;
}
QScrollBar:vertical {
    background: #232323;
    border: 1px solid #444;
    border-radius: 6px;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #ff9900;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
""")
        
        layout = QVBoxLayout()
        
        # 설명 라벨
        label = QLabel("작품별 경로를 관리할 수 있습니다. 경로를 수정하거나 작품을 추가/삭제할 수 있습니다.")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # 작품 경로 리스트
        table = QListWidget()
        table.setAlternatingRowColors(True)
        
        self._refresh_work_path_table(table)

        layout.addWidget(table)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 추가 버튼
        add_button = QPushButton("작품 추가")
        add_button.clicked.connect(lambda: self.add_work_path(table, dialog))
        button_layout.addWidget(add_button)
        
        # 수정 버튼
        edit_button = QPushButton("경로 수정")
        edit_button.clicked.connect(lambda: self.edit_work_path(table, dialog))
        button_layout.addWidget(edit_button)
        
        # 삭제 버튼
        delete_button = QPushButton("작품 삭제")
        delete_button.clicked.connect(lambda: self.delete_work_path(table, dialog))
        button_layout.addWidget(delete_button)
        
        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # 비밀번호 변경 버튼 레이아웃
        password_layout = QHBoxLayout()
        password_button = QPushButton("비밀번호 변경")
        password_button.clicked.connect(lambda: self.change_password(dialog))
        password_layout.addWidget(password_button)
        if paths.IS_WINDOWS:
            auto_button = QPushButton("변환표 자동 설정")
            auto_button.setToolTip(
                "이 PC에 연결된 네트워크 드라이브에서 작품 폴더가 열리는 곳을 찾아 path_map.json을 만들거나 보충합니다."
            )

            def on_auto_setup():
                self.auto_setup_path_map(ask_password=False, parent=dialog)
                if self.shared_config_problem:
                    # 다시 읽기에 실패해 work_paths가 빈 목록일 수 있음 — 관리 창을 닫아 그대로 덮어쓰지 않게 함
                    dialog.reject()
                else:
                    self._refresh_work_path_table(table)

            auto_button.clicked.connect(on_auto_setup)
            password_layout.addWidget(auto_button)
        password_layout.addStretch()
        layout.addLayout(password_layout)
        
        dialog.setLayout(layout)
        
        dialog.exec_()

    def add_work_path(self, table, dialog):
        """새로운 작품 경로를 추가합니다."""
        work_name, ok = QInputDialog.getText(
            dialog, 
            "작품 추가", 
            "작품 이름을 입력하세요:",
            text=""
        )
        if not ok or not work_name:
            return
        
        if work_name in self.work_paths:
            QMessageBox.warning(dialog, "오류", f"'{work_name}' 작품은 이미 존재합니다.")
            return
        
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택")
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            del self.work_paths[work_name]
            return

        # 콤보박스에도 추가
        if work_name not in [self.workComboBox.itemText(i) for i in range(self.workComboBox.count())]:
            self.workComboBox.addItem(work_name)
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "추가 완료", f"'{work_name}' 작품이 추가되었습니다.")

    def edit_work_path(self, table, dialog):
        """선택된 작품의 경로를 수정합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "수정할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        try:
            start_dir = paths.to_native(self.work_paths.get(work_name, ""))
        except paths.PathMapError:
            start_dir = ""  # 선택 창의 시작 위치만 정하는 값 (고른 경로는 저장 전에 다시 검사함)
        folder_path = QFileDialog.getExistingDirectory(dialog, f"{work_name} 작품 경로 선택", start_dir)
        if not folder_path:
            return
        stored_path = self._stored_work_path_or_warn(folder_path, dialog)
        if stored_path is None:
            return
        previous = self.work_paths.get(work_name)
        self.work_paths[work_name] = stored_path
        if not self.save_work_paths(dialog):
            self.work_paths[work_name] = previous
            return
        self._refresh_work_path_table(table)
        QMessageBox.information(dialog, "수정 완료", f"'{work_name}' 작품의 경로가 수정되었습니다.")

    def delete_work_path(self, table, dialog):
        """선택된 작품을 삭제합니다."""
        current_item = table.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "선택 필요", "삭제할 작품을 선택해주세요.")
            return
        
        work_name = current_item.data(Qt.UserRole)
        if not work_name:
            return
        
        reply = QMessageBox.question(
            dialog,
            "작품 삭제",
            f"'{work_name}' 작품을 삭제하시겠습니까?\n\n경로: {self.work_paths.get(work_name, '')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            previous = self.work_paths.pop(work_name, None)
            if not self.save_work_paths(dialog):
                if previous is not None:
                    self.work_paths[work_name] = previous
                return
            index = self.workComboBox.findText(work_name)
            if index >= 0:
                self.workComboBox.removeItem(index)
            self._refresh_work_path_table(table)
            QMessageBox.information(dialog, "삭제 완료", f"'{work_name}' 작품이 삭제되었습니다.")

    def change_password(self, dialog):
        """비밀번호를 변경합니다."""
        # 현재 비밀번호 확인
        current_password, ok = QInputDialog.getText(
            dialog,
            "현재 비밀번호 확인",
            "현재 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if not self.verify_password(current_password):
            QMessageBox.warning(dialog, "오류", "현재 비밀번호가 올바르지 않습니다.")
            return
        
        # 새 비밀번호 입력
        new_password, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 설정",
            "새 비밀번호를 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok or not new_password:
            return
        
        # 새 비밀번호 확인
        new_password_confirm, ok = QInputDialog.getText(
            dialog,
            "새 비밀번호 확인",
            "새 비밀번호를 다시 입력하세요:",
            echo=QInputDialog.Password
        )
        if not ok:
            return
        
        if new_password != new_password_confirm:
            QMessageBox.warning(dialog, "오류", "새 비밀번호가 일치하지 않습니다.")
            return
        
        # 비밀번호 변경
        try:
            self.set_password(new_password)
        except OSError as exc:
            QMessageBox.critical(dialog, "비밀번호 저장 실패", f"{self.work_paths_password_file}\n\n{exc}")
            return
        QMessageBox.information(dialog, "변경 완료", "비밀번호가 변경되었습니다.")

    def _resize_sidebar_column(self, list_width):
        """사이드바 목록이 list_width가 되도록 메인 스플리터의 왼쪽 칸 너비를 바꿈 — 늘어난 만큼 영상 쪽에서 가져오고
        줄어든 만큼 영상 쪽에 줌. 창이 좁아 다 못 가져오면 스플리터가 최소 너비 안에서 맞춤."""
        sizes = self.mainSplitter.sizes()
        column = sizes[0] + list_width - self.sidebar.width()
        sizes[2] = max(0, sizes[2] - (column - sizes[0]))
        sizes[0] = column
        self.mainSplitter.setSizes(sizes)

    def switch_to_list_mode(self):
        self.listModeButton.setChecked(True)
        self.thumbnailModeButton.setChecked(False)
        self.sidebar.setViewMode(QListWidget.ListMode)
        self.sidebar.setSpacing(0)  # 리스트 아이템 사이 공란 제거
        self.is_thumbnail_mode = False
        
        # 사이드바 폭을 원래대로 되돌리기 (고정 너비가 아니라 스플리터 칸 너비 — 창을 줄이면 같이 줄어듦)
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(QWIDGETSIZE_MAX)
        if self.default_sidebar_width is not None:
            self._resize_sidebar_column(self.default_sidebar_width)
            print(f"사이드바 폭을 원래대로 복원: {self.default_sidebar_width}")
        
        self.update_sidebar_display()

    def switch_to_thumbnail_mode(self):
        print("썸네일 모드로 전환 시작")
        
        # 완료된 워커들만 정리 (실행 중인 워커는 유지)
        self.cleanup_thumbnail_workers()
        
        # 메모리 정리 (지연 시간 단축)
        QApplication.processEvents()
        import gc
        gc.collect()
        
        self.listModeButton.setChecked(False)
        self.thumbnailModeButton.setChecked(True)
        self.sidebar.setViewMode(QListWidget.ListMode)  # ListMode로 변경
        self.sidebar.setIconSize(QSize(self.thumbnail_size, self.thumbnail_size))
        self.sidebar.setSpacing(10)
        self.is_thumbnail_mode = True
        print(f"썸네일 모드 설정 완료: iconSize={self.sidebar.iconSize()}, viewMode={self.sidebar.viewMode()}")
        
        # 사이드바 폭을 2배로 조정
        if self.default_sidebar_width is None:
            # 기본 폭이 설정되지 않은 경우 현재 폭을 기본값으로 저장
            self.default_sidebar_width = self.sidebar.width()
            print(f"기본 사이드바 폭 저장: {self.default_sidebar_width}")
        
        # 사이드바 폭을 2배로 설정: 예전처럼 2배 너비로 시작하지만 고정 너비(setFixedWidth)가 아니라 스플리터 칸 너비 —
        # 고정 너비는 창의 최소 너비를 그만큼 늘려 창을 줄일 수 없게 했음. 최소 너비는 썸네일 한 개가 보일 만큼.
        new_width = self.default_sidebar_width * 2
        self.sidebar.setMaximumWidth(QWIDGETSIZE_MAX)
        self.sidebar.setMinimumWidth(self.thumbnail_size + 2 * self.sidebar.spacing() + 2 * self.sidebar.frameWidth()
                                     + self.sidebar.verticalScrollBar().sizeHint().width())
        self._resize_sidebar_column(new_width)
        print(f"사이드바 폭을 2배로 조정: {self.default_sidebar_width} -> {new_width}")
        
        # 즉시 사이드바 업데이트 (지연 없이): generate_thumbnails_for_all_items가 캐시된 썸네일을 바로 적용하고
        # (캐시 사용·새 생성 개수 로그) 나머지를 만듦 — 여기서 같은 확인을 먼저 하지 않음 (영상마다 NAS를 한 번만).
        # 항목 자리의 미뤄 둔 썸네일 폴더 문제도 거기서 창으로 ((폴더, 제목)마다 한 번)
        self.update_sidebar_display()

    def cleanup_all_thumbnail_workers(self):
        """모든 썸네일 워커를 강제로 정리합니다."""
        try:
            print("모든 썸네일 워커 정리 시작")
            for worker in self.thumbnail_workers:
                try:
                    worker.stop()
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 정리 중 오류: {e}")
            
            self.thumbnail_workers.clear()
            print("모든 썸네일 워커 정리 완료")
        except Exception as e:
            print(f"워커 전체 정리 중 오류: {e}")

    def update_sidebar_display(self):
        """사이드바 아이템들을 현재 모드에 맞게 업데이트합니다."""
        print(f"사이드바 디스플레이 업데이트: thumbnail_mode={self.is_thumbnail_mode}, item_count={self.sidebar.count()}")
        
        if self.is_thumbnail_mode:
            with self._hold_sidebar_refresh():  # 그동안 목록 다시 읽기는 끝난 뒤로 미룸 (반복이 멈추지 않게)
                self.generate_thumbnails_for_all_items()
        else:
            self.clear_thumbnails()

    def generate_thumbnails_for_all_items(self):
        """모든 사이드바 아이템에 대해 썸네일을 생성합니다."""
        print(f"모든 아이템 썸네일 생성 시작: {self.sidebar.count()}개 아이템")
        self.cleanup_thumbnail_workers()
        # 이벤트를 처리하며 만드는 동안 목록이 바뀌거나(job·폴더를 바꿈) 목록 모드로 바꾸거나 창을 닫으면 나머지는 만들지
        # 않고 멈춤
        state = self._thumbnail_pass_state()
        # 첫 번째 단계에서 새로 만들 영상(과 그 자리)을 정해 두고 두 번째 단계는 그 목록만 (NAS에서 다시 확인하지 않고,
        # 지워졌을 수 있는 항목도 쓰지 않음)
        to_generate, _checked = self._apply_disk_thumbnails()
        new_generation_count = len(to_generate)
        print(f"썸네일 처리 완료: 캐시 사용 {self.sidebar.count() - new_generation_count}개, 새 생성 {new_generation_count}개")
        _started, stopped = self._make_thumbnails(to_generate, state)
        if stopped:
            return
        # 새로운 썸네일이 생성된 경우에만 팝업창 띄우기
        if new_generation_count > 0:
            total_files = self.sidebar.count()
            cached_count = total_files - new_generation_count
            QMessageBox.information(self, "썸네일 생성 완료", 
                                  f"썸네일 처리가 완료되었습니다.\n\n"
                                  f"• 전체 파일 수: {total_files}개\n"
                                  f"• 기존 캐시 사용: {cached_count}개\n"
                                  f"• 새로 생성: {new_generation_count}개")
            
        else:
            print("모든 썸네일이 캐시에 있어서 새로 생성할 필요가 없습니다.")

    def _thumbnail_pass_state(self):
        """썸네일 반복을 시작할 때의 상태 (세대 번호, 썸네일 모드) — _thumbnail_pass_stopped가 지금과 비교."""
        return (self._sidebar_generation, self.is_thumbnail_mode)

    def _thumbnail_pass_stopped(self, state):
        """썸네일을 확인·만드는 반복(이벤트를 처리함)을 멈출 까닭 → 짧은 문구 (계속하면 None).

        창을 닫음, 목록이 바뀜 (job·폴더를 바꿈 — 지워진 항목·예전 목록의 영상을 쓰지 않게), 썸네일 모드에서 시작했는데
        목록 모드로 바꿈 (목록 모드에 아이콘을 붙이거나 워커를 띄우지 않게 — 목록 모드에서 시작한 썸네일 재생성은 그대로).
        """
        generation, thumbnail_mode = state
        if self._sidebar_scan_closed:
            return "창을 닫음"
        if self._sidebar_generation != generation:
            return "목록이 바뀜"
        if thumbnail_mode and not self.is_thumbnail_mode:
            return "목록 모드로 바꿈"
        return None

    def _make_thumbnails(self, to_generate, state):
        """정해 둔 영상들의 썸네일을 3개씩 만들며 진행바(thumbnailProgressBar)에 보임 → (워커를 띄운 수, 멈춘 까닭 — 끝까지
        했으면 None). 썸네일 버튼과 새로고침 버튼·F5가 같은 반복.

        to_generate: [(영상, 그 항목의 자리)] (_apply_disk_thumbnails가 정함 — NAS에서 다시 확인하지 않고, 지워졌을 수 있는
        항목도 쓰지 않음). state: 반복을 시작할 때의 상태 (_thumbnail_pass_state) — 만드는 동안(이벤트를 처리함) 목록이
        바뀌거나 목록 모드로 바꾸거나 창을 닫으면 나머지는 만들지 않고 멈춤 (그 전 확인에서 멈췄어도).
        """
        import gc
        total = len(to_generate)
        bar = self.thumbnailProgressBar
        if total > 0:
            bar.setMaximum(total)
            bar.setValue(0)
            bar.setFormat('썸네일 생성 중: %v/%m')
        else:
            bar.setMaximum(100)
            bar.setValue(100)
            bar.setFormat('썸네일 모두 디스크에 저장됨')
        bar.setVisible(True)
        batch_size = 3
        started = 0
        done = 0
        stopped = self._thumbnail_pass_stopped(state)
        for batch_start in range(0, total, batch_size):
            if stopped:
                break
            batch = to_generate[batch_start:batch_start + batch_size]
            print(f"배치 처리: {batch_start+1}-{batch_start + len(batch)}/{total}")
            for file_path, context in batch:
                stopped = self._thumbnail_pass_stopped(state)
                if stopped:
                    break
                if self.generate_thumbnail(file_path, context=context):
                    started += 1
                done += 1
                bar.setValue(done)
                QApplication.processEvents()
            stopped = stopped or self._thumbnail_pass_stopped(state)
            if stopped:
                break
            QApplication.processEvents()
            time.sleep(0.2)
            self.cleanup_thumbnail_workers()
            gc.collect()
        if stopped:
            print(f"썸네일 만들기를 멈춤 ({stopped}, {done}/{total}개에서)")
            bar.setFormat(f'썸네일 생성 멈춤 ({stopped})')
            return started, stopped
        if total > 0:
            bar.setValue(total)
            bar.setFormat('썸네일 생성 완료')
        return started, None

    def cleanup_thumbnail_workers(self):
        """완료된 워커들을 정리합니다: 목록에서 빼는 것은 그 워커의 finished를 GUI 스레드가 받을 때(generate_thumbnail의
        safe_remove_worker — 멈춘 워커는 멈춘 쪽이 목록을 비움). 끝났다고(isRunning) 여기서 먼저 놓으면 GUI 스레드가 아직 받지
        않은 신호 중 partial·람다로 이은 것(failed → 실패 창, finished → safe_remove_worker)이 QThread와 함께 사라져 실패 창이
        뜨지 않았음 (3개마다 0.2초 쉬는 동안 끝난 빠른 실패. 메서드로 이은 thumbnail_ready·save_failed는 전달됐음)."""
        print(f"워커 정리 완료: 현재 워커 수 {len(self.thumbnail_workers)}")

    def cleanup_background_threads(self):
        """모든 백그라운드 스레드를 안전하게 정리합니다."""
        try:
            print("백그라운드 스레드 정리 시작...")
            
            # 백그라운드 썸네일 로딩 타이머 중지
            if hasattr(self, 'thumbnail_loading_timer'):
                self.thumbnail_loading_timer.stop()
                print("썸네일 로딩 타이머 중지됨")
            
            # 백그라운드 썸네일 로더 워커 중지 및 대기
            if hasattr(self, 'thumbnail_loader_worker') and self.thumbnail_loader_worker:
                if self.thumbnail_loader_worker.isRunning():
                    print("백그라운드 썸네일 로더 워커 중지 중...")
                    self.thumbnail_loader_worker.stop()
                    self.thumbnail_loader_worker.wait(5000)  # 5초 대기
                    if self.thumbnail_loader_worker.isRunning():
                        print("워커 강제 종료")
                        self.thumbnail_loader_worker.terminate()
                        self.thumbnail_loader_worker.wait(3000)
                    # deleteLater() 호출하여 안전하게 삭제
                    self.thumbnail_loader_worker.deleteLater()
                    self.thumbnail_loader_worker = None
                    print("백그라운드 썸네일 로더 워커 정리 완료")
            
            # 모든 썸네일 워커를 안전하게 중지
            print(f"썸네일 워커 {len(self.thumbnail_workers)}개 중지 중...")
            for worker in self.thumbnail_workers:
                try:
                    if worker.isRunning():
                        worker.stop()
                        worker.wait(3000)  # 3초 대기
                        if worker.isRunning():
                            worker.terminate()
                            worker.wait(2000)
                    # deleteLater() 호출하여 안전하게 삭제
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 중지 중 오류: {e}")
            
            # 워커 리스트 클리어
            self.thumbnail_workers.clear()
            
            # 추가 대기 시간
            import time
            time.sleep(0.5)
            
            # UI 업데이트 처리
            QApplication.processEvents()
            
            print("모든 백그라운드 스레드 정리 완료")
            
        except Exception as e:
            print(f"백그라운드 스레드 정리 중 오류: {e}")

    def _bump_sidebar_generation(self):
        """사이드바 목록을 비움(clear → 모델 초기화): 썸네일을 만드는 반복이 지워진 항목을 쓰지 않고 멈추게 세대를 올림."""
        self._sidebar_generation += 1

    def _new_item_thumbnail_context(self, file_path):
        """지금 사이드바에 넣는 영상의 썸네일 자리: 지금의 썸네일 폴더·폴더 문제.

        아무것도 정하지 않았으면(예: 처음 끌어다 놓은 파일) 예전처럼 불러온 폴더 또는 영상 폴더 아래에 — 처음 쓸 때 만듦.
        """
        if self.current_thumbnail_folder:
            return ThumbnailContext(folder=self.current_thumbnail_folder)
        if self._thumbnail_folder_problem is not None:
            return ThumbnailContext(problem=self._thumbnail_folder_problem)
        return ThumbnailContext(pending_base=getattr(self, "selected_folder_path", None) or os.path.dirname(file_path))

    def _add_sidebar_videos(self, entries):
        """영상들을 사이드바 끝에 넣음 — entries: [(표시 이름, 경로, 들어온 곳(ListSource 또는 None))] → 넣은 항목 목록.

        항목마다 썸네일 자리(ThumbnailContext)를 지금 상태로 기억 (같은 영상이 이미 있으면 _new_sidebar_item의 규칙).
        """
        known = self._known_sidebar_videos()
        added = []
        for label, file_path, source in entries:
            item = self._new_sidebar_item(label, file_path, self._new_item_thumbnail_context(file_path), source, known)
            self.sidebar.addItem(item)
            added.append(item)
        return added

    def _known_sidebar_videos(self):
        """지금 목록의 영상 → {path_key: [썸네일 자리, 그 영상의 항목들]} (_new_sidebar_item이 씀)."""
        known = {}
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and item.data(Qt.UserRole):
                entry = known.setdefault(paths.path_key(item.data(Qt.UserRole)), [item.data(THUMBNAIL_CONTEXT_ROLE), []])
                entry[1].append(item)
        return known

    def _new_sidebar_item(self, label, file_path, context, source, known):
        """사이드바 항목을 만듦 (목록에는 부르는 쪽이 넣음). context: 이 영상이 들어온 곳의 썸네일 자리.

        이미 목록에 있는 영상(known)이면 그 항목의 자리를 그대로 씀. 다만 그 자리에 썸네일 폴더가 없고(폴더 문제·
        아직 정하지 않음) context에는 폴더가 있으면(예: 그 영상의 폴더를 끌어다 놓음) context를 쓰고 원래 항목도 그 자리로
        올림. 폴더가 정해진 자리는 다른 폴더로 바꾸지 않음. known은 이 항목까지 넣어 갱신.
        """
        key = paths.path_key(file_path)
        entry = known.get(key)
        if entry is None:
            entry = known[key] = [context, []]
        elif entry[0] is not None and (entry[0].folder or not context.folder):
            context = entry[0]  # 이미 있는 영상: 그 항목의 자리
        else:
            print(f"이미 목록에 있는 영상의 썸네일을 이제 이 폴더에: {context.folder} ({file_path})")
            for existing in entry[1]:
                existing.setData(THUMBNAIL_CONTEXT_ROLE, context)
            entry[0] = context
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, file_path)  # 파일 경로를 UserRole에 저장
        item.setData(THUMBNAIL_CONTEXT_ROLE, context)
        item.setData(SIDEBAR_SOURCE_ROLE, source)
        item.setToolTip(file_path)  # toolTip도 설정하여 기존 코드와 호환
        entry[1].append(item)
        return item

    def _register_sidebar_source(self, source, context=None):
        """목록에 영상을 넣는 곳(job 폴더·폴더)을 기억 → source. 목록 다시 읽기가 이곳을 처음과 같은 규칙으로 다시 읽음.

        context: 이곳에서 새로 생긴 영상의 썸네일 자리 (없으면 지금 넣는 영상과 같은 지금 상태의 자리 — 처음 불러올 때와
        같음). 같은 곳을 또 넣으면 처음 기억한 자리를 그대로. 목록을 비우면(clear) 함께 잊음.
        """
        if context is None:
            context = self._new_item_thumbnail_context(source.folder)
        self._sidebar_sources.setdefault(source, context)
        return source

    def _register_unread_folder(self, folder_path):
        """읽지 못한(또는 빈) 폴더도 목록에 영상을 넣는 곳으로 기억 → 연결이 돌아오면(영상이 생기면) 다시 읽기(F5·앱이 다시
        활성)로 목록에 들어옴. 그 영상의 썸네일은 처음 쓸 때 이 폴더 아래에 (영상이 있을 때 불러온 것과 같게)."""
        return self._register_sidebar_source(video_list.ListSource("folder", folder_path),
                                             ThumbnailContext(pending_base=folder_path))

    def _forget_sidebar_sources(self):
        """사이드바 목록을 비움(clear → 모델 초기화): 목록에 영상을 넣은 곳도 잊음 (새 목록을 넣는 쪽이 다시 기억).
        방금 job 목록을 읽었다는 표시도 지움 (목록이 바뀌었으므로 그 job을 다시 고르면 다시 불러옴). 예전 목록에서 누른
        새로고침의 썸네일 확인 요청도 버림 (새 목록은 처음 불러올 때의 흐름대로)."""
        self._sidebar_sources.clear()
        self._job_list_loaded_for = None
        self._sidebar_thumbnail_check_requested = False

    @contextlib.contextmanager
    def _hold_sidebar_refresh(self):
        """사이드바 항목·줄 번호를 쓰는 동안(썸네일 반복·job 목록 만들기·오른쪽 클릭 메뉴 — 이벤트를 처리함): 목록 다시 읽기는
        끝난 뒤로 미룸. 그동안 온 다시 읽기 결과도 버리고 끝난 뒤 다시 읽음.

        다시 읽기가 목록을 바꾸면 세대 번호가 올라 썸네일 반복이 '썸네일 생성 멈춤'으로 끝나고, 메뉴의 줄 번호(QModelIndex)가
        다른 영상을 가리킬 수 있으므로 — 그 대신 하던 일을 끝까지 하고 바로 뒤에 다시 읽음.
        """
        self._sidebar_refresh_holds += 1
        try:
            yield
        finally:
            self._sidebar_refresh_holds -= 1
            if not self._sidebar_refresh_holds and self._sidebar_refresh_deferred:
                QTimer.singleShot(0, self._run_deferred_sidebar_refresh)

    def _run_deferred_sidebar_refresh(self):
        if self._sidebar_refresh_deferred:
            self.refresh_sidebar()

    def _job_selection(self):
        return (self.workComboBox.currentText(), self.seasonComboBox.currentText(), self.jobComboBox.currentText())

    @staticmethod
    def _picked(combo):
        """시즌·job 콤보에서 항목을 골랐는지: 0번은 안내 항목('시즌선택'·'job선택'), -1은 비었거나 비우는 중 (clear가 빈
        글자로 currentIndexChanged를 보냄 — 안내 글자와만 비교하면 빈 글자를 고른 것으로 여김)."""
        return combo.currentIndex() > 0

    def _job_picked(self):
        """작품 → 시즌 → job 순서로 job까지 골랐는지 (시즌이 없는 작품은 작품 → job)."""
        return self._picked(self.jobComboBox) and (
            self.workComboBox.currentText() in NO_SEASON_WORKS or self._picked(self.seasonComboBox))

    def _on_job_activated(self, _index):
        """job 목록에서 고름 (같은 job을 다시 골라도 옴 — currentIndexChanged는 job이 바뀔 때만 와서 예전에는 아무 일도
        없었음). 다른 job이면 Qt가 바로 앞에 보낸 currentIndexChanged(update_playlist)가 이미 그 job을 읽었으므로 그대로
        (update_playlist가 읽은 (작품, 시즌, job)을 기억 — 그 안에서 창이 떠 이벤트를 처리해도 지워지지 않음),
        같은 job이면 목록을 다시 읽음. 목록이 폴더 불러오기·끌어다 놓기로 바뀌어 job 목록이 아니면 그 job을 새로 불러옴.
        'job선택'을 고르면 아무것도 읽지 않음."""
        loaded, self._job_list_loaded_for = self._job_list_loaded_for, None
        if loaded == self._job_selection() or not self._job_picked():
            return
        job_sources = {source for source in self._sidebar_sources if source.kind == "job"}
        if any(self.sidebar.item(i).data(SIDEBAR_SOURCE_ROLE) in job_sources for i in range(self.sidebar.count())):
            self.refresh_sidebar()
        else:
            # job 목록이 아니거나(폴더를 불러옴·끌어다 놓음) 고를 때 읽지 못해 영상이 없음 → 처음 고를 때처럼 불러옴
            # (job 경로·썸네일 폴더·첫 영상까지 — 다시 읽기는 영상만 넣음)
            self.update_playlist()

    def _clear_job_list_loaded_for(self):
        """update_playlist가 끝난 뒤의 첫 이벤트 처리: 코드로 job을 바꿔(activated가 오지 않음) 남은 표시를 지움. 사용자가
        고른 것이면 Qt가 update_playlist 바로 다음(이벤트를 처리하기 전) activated를 보내 이미 썼음."""
        self._job_list_loaded_for = None

    def _on_application_state_changed(self, state):
        """앱이 다시 활성됨(다른 앱에서 돌아옴 — QGuiApplication.applicationStateChanged): 다른 앱·PC에서 NAS의 영상을
        지우거나 넣고 돌아왔을 수 있으므로 조금 뒤 목록 다시 읽기. 이 앱의 창 사이를 오가거나 이 앱의 창(메시지 창 등)을
        닫을 때는 앱이 활성인 채라 오지 않음 (예전에는 창마다 활성이 바뀔 때 읽었음)."""
        if state == Qt.ApplicationActive:
            self._sidebar_refresh_timer.start()

    def _refresh_sidebar_on_activation(self):
        """(앱이 다시 활성된 뒤 조금 뒤) 목록 다시 읽기. 그사이 앱이 다시 비활성이 됐거나 창이 보이지 않거나 모달 대화상자·팝업이
        떠 있으면 하지 않음. 방금 읽었으면(ACTIVATION_REFRESH_GAP_S초, 마지막 읽기가 오래 걸렸으면 그 시간의
        ACTIVATION_REFRESH_GAP_FACTOR배 안 — job을 고르거나 폴더를 불러온 것도 읽은 것) 하지 않음."""
        if (QApplication.applicationState() != Qt.ApplicationActive or not self.isVisible()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return
        gap = max(ACTIVATION_REFRESH_GAP_S, ACTIVATION_REFRESH_GAP_FACTOR * self._sidebar_scan_seconds)
        if self._sidebar_refreshed_at is not None and time.monotonic() - self._sidebar_refreshed_at < gap:
            print(f"앱이 다시 활성됨: {gap:.1f}초 안에 목록을 읽어서 건너뜀")
            return
        self.refresh_sidebar()

    def _refresh_sidebar_by_user(self):
        """새로고침 버튼·F5: 목록 다시 읽기. 썸네일 모드면 다시 읽은 결과를 넣은 뒤 모든 영상의 썸네일도 썸네일 버튼처럼
        확인 — 저장된 썸네일(영상보다 새것)은 그대로 쓰고, 같은 이름으로 다시 렌더링해 썸네일보다 새 영상·썸네일이 없거나
        읽을 수 없는 영상만 다시 만듦 (목록이 바뀌지 않아도). 저절로 다시 읽을 때(앱이 다시 활성·같은 job을 다시 고름·없는
        영상을 엶·선택 재생)는 예전처럼 새 영상만 — 앱을 오갈 때마다 모든 영상을 NAS에서 확인하지 않게. 앱이 다시 활성될
        때의 간격(ACTIVATION_REFRESH_GAP_S)은 보지 않고 바로 읽음.

        요청(_sidebar_thumbnail_check_requested)은 다음에 시작하는 읽기에 실려(SidebarScan.check_thumbnails) 그 결과를 넣을 때
        (_apply_sidebar_read) 한 번 씀. 읽는 중에 누르면 그 읽기에는 싣지 않고 남겨 뒤이은 읽기에서, 목록을 쓰는 중이라 미루면
        미룬 읽기에서. 결과를 버리고 다시 읽으면(목록을 쓰는 중·폴더를 덧붙임) 요청으로 되돌려 다시 읽을 때. 목록을 비우면
        (job을 바꿈·폴더를 불러옴 — _forget_sidebar_sources, 읽는 중이면 그 결과도 버림) 버림. 읽기가 예상 못 한 오류로 끝나면
        (오류 창) 버림. 목록 모드에서 누르면 요청하지 않음 (예전처럼 목록만).
        """
        if self.is_thumbnail_mode:
            self._sidebar_thumbnail_check_requested = True
        self.refresh_sidebar()

    def _sidebar_read_done(self, seconds):
        """목록을 디스크에서 읽음 (처음 불러오기·다시 읽기): 앱이 다시 활성될 때 곧바로 또 읽지 않게 때·걸린 시간을 남김."""
        self._sidebar_refreshed_at = time.monotonic()
        if seconds is not None:
            self._sidebar_scan_seconds = seconds

    def refresh_sidebar(self):
        """사이드바 목록 다시 읽기 (새로고침 버튼·F5·창이 다시 활성·같은 job을 다시 고름·디스크에 없는 영상을 엶).

        목록에 영상을 넣은 곳(job 폴더·폴더)마다 처음 불러올 때와 같은 규칙(video_list)으로 다시 읽어 디스크에 없는 영상은
        빼고 새 영상은 정렬 자리에 넣음 (그곳에서 처음 불러올 때와 같은 썸네일 자리). 따로 끌어다 놓은 파일은 있는 동안만.
        디스크 읽기는 GUI 밖 스레드(SidebarScan)에서 — Windows SMB의 큰 job이나 응답 없는 NAS에서도 창이 멈추지 않음.
        결과는 GUI 스레드에서 넣음 (_on_sidebar_scanned). 한 번에 하나만 읽고, 읽는 동안 온 요청은 끝난 뒤 한 번 더.
        목록을 쓰는 중(_hold_sidebar_refresh)이면 끝난 뒤로 미룸. 선택 재생(Play Selected)은 목록 줄이 아니라 경로 목록
        (self.playlist)으로 재생하므로 미루지 않음.
        """
        if self._sidebar_scan_closed:
            return  # 창이 닫힘 (미뤄 둔 다시 읽기의 타이머가 늦게 옴) — 닫힌 창이 붙잡는 읽기 스레드를 만들지 않음
        if self._sidebar_refresh_holds:
            if not self._sidebar_refresh_deferred:
                print("목록을 쓰는 중이라(썸네일 만들기·job 목록 만들기·메뉴) 목록 다시 읽기를 끝난 뒤로 미룸")
            self._sidebar_refresh_deferred = True
            return
        self._sidebar_refresh_deferred = False
        if self._sidebar_scan is not None:
            self._sidebar_rescan_queued = True
            return
        if not self._sidebar_sources and not self.sidebar.count():
            self._sidebar_thumbnail_check_requested = False  # 읽을 것도, 썸네일을 확인할 영상도 없음
            return
        files = []
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(SIDEBAR_SOURCE_ROLE) is None and item.data(Qt.UserRole):
                files.append(item.data(Qt.UserRole))
        self._sidebar_refreshed_at = time.monotonic()
        # 지금까지의 썸네일 확인 요청은 이 읽기에 실음 (읽는 동안 누른 새로고침은 다시 요청해 뒤이은 읽기에서)
        scan = SidebarScan(tuple(self._sidebar_sources), files, self._sidebar_generation,
                           self._sidebar_thumbnail_check_requested)
        self._sidebar_thumbnail_check_requested = False
        scan.scanned.connect(self._on_sidebar_scanned)  # 창은 GUI 스레드 → 대기열을 거쳐 GUI 스레드에서 실행
        self._sidebar_scan = scan
        scan.start()

    def _on_sidebar_scanned(self, scan):
        """(GUI 스레드) 목록 다시 읽기의 디스크 읽기가 끝남 → 목록을 맞추고 문제를 알림.

        읽는 동안 목록이 바뀌었으면(세대 번호·목록에 영상을 넣은 곳이 다름 — job을 바꿈·폴더를 불러옴·끌어다 놓음) 결과를
        버리고 다시 읽음. 목록을 쓰는 중이면 버리고 끝난 뒤 다시 읽음. 창이 닫힌 뒤에 온 결과는 버림.
        이 읽기에 실린 새로고침의 썸네일 확인(scan.check_thumbnails)은 결과를 넣을 때 씀. 버리고 다시 읽으면(폴더를 덧붙임·
        목록을 쓰는 중) 요청으로 되돌려 다시 읽을 때, 목록을 새로 불러왔거나(새 목록은 처음 불러올 때의 흐름대로) 예상 못 한
        오류(창으로 알림 — 몇 시간 뒤 저절로 다시 읽을 때 모든 영상을 확인하지 않게)면 버림.
        """
        if scan is not self._sidebar_scan or self._sidebar_scan_closed:
            return  # 창을 닫으며 놓은 읽기 (release_worker가 신호를 막지만 이미 대기열에 들어간 결과)
        self._sidebar_scan = None
        scan.wait()  # 결과를 보낸 뒤 곧 끝남
        try:
            if scan.unexpected is not None:
                # 이 읽기에 실린 썸네일 확인도 버림 (오류 창을 봄 — 나중에 저절로 다시 읽을 때 모든 영상을 확인하지 않게)
                QMessageBox.critical(self, "목록 다시 읽기 오류",
                                     f"사이드바 목록을 다시 읽다 예상치 못한 오류가 났습니다.\n\n{scan.unexpected}")
                return
            if scan.generation != self._sidebar_generation:
                # 읽는 동안 목록을 비우고 새로 불러옴(job을 바꿈·폴더를 불러옴): 새 목록은 방금 디스크에서 읽었으므로 버리기만 —
                # 읽는 동안 다시 읽어 달라는 요청이 왔으면(_sidebar_rescan_queued) 아래에서 한 번 더. 이 읽기에 실린 썸네일
                # 확인도 버림 (새 목록은 처음 불러올 때의 흐름대로)
                print("목록 다시 읽기: 읽는 동안 목록을 새로 불러와 결과를 버림")
                return
            if set(scan.sources) != set(self._sidebar_sources):
                print("목록 다시 읽기: 읽는 동안 목록에 폴더를 덧붙여 결과를 버리고 다시 읽음")
                self._sidebar_rescan_queued = True
                self._sidebar_thumbnail_check_requested |= scan.check_thumbnails  # 다시 읽을 때 씀
                return
            if self._sidebar_refresh_holds:
                print("목록 다시 읽기: 목록을 쓰는 중이라 결과를 버리고 끝난 뒤 다시 읽음")
                self._sidebar_refresh_deferred = True
                self._sidebar_thumbnail_check_requested |= scan.check_thumbnails  # 다시 읽을 때 씀
                return
            self._apply_sidebar_read(scan.read, scan.elapsed, scan.check_thumbnails)
        finally:
            # 예외가 나도 남김: 오류 창 → 앱이 다시 활성 → 다시 읽기 → 오류 창이 되풀이되지 않게
            self._sidebar_read_done(scan.elapsed)
            if self._sidebar_rescan_queued:
                self._sidebar_rescan_queued = False
                self.refresh_sidebar()

    def _apply_sidebar_read(self, read, elapsed, check_thumbnails=False):
        """(GUI 스레드) 다시 읽은 결과(video_list.SourcesRead)로 목록을 맞춤. 바뀐 것이 없으면 목록을 건드리지 않음
        (깜빡임 없음, 세대 번호 그대로). 남는 항목은 그대로 둠: 썸네일 자리·아이콘·선택·현재 항목·재생 중 표시(빨간 글자),
        맨 위에 보이던 영상도 그 자리에. 읽지 못한 폴더(NAS 연결 끊김·권한)의 영상은 빼지 않고 실제 오류를 창으로
        ((제목, 폴더, 오류)마다 한 번 — 그 폴더를 다시 읽으면 기록을 지워 다음에 또 끊기면 다시 알림). 폴더가 지워졌으면
        그 영상을 빼고 알림. 썸네일 모드면 새 영상의 썸네일만 붙이거나 만듦 — check_thumbnails(이 읽기에 실린 새로고침
        버튼·F5의 요청 — _refresh_sidebar_by_user)면 모든 영상의 썸네일 (다시 렌더링한 영상도, _check_thumbnails_after_refresh).
        그사이 목록 모드로 바꿨으면 요청은 버리기만.
        """
        rows = [(self.sidebar.item(i).data(Qt.UserRole), self.sidebar.item(i).data(SIDEBAR_SOURCE_ROLE))
                for i in range(self.sidebar.count())]
        plan = video_list.plan_refresh(rows, read.results, read.gone_files)
        added = []
        if video_list.plan_changes(plan):
            added = self._apply_sidebar_plan(plan)
            print(f"목록 다시 읽기: 뺌 {len(plan[0])}개, 넣음 {len(added)}개 → {self.sidebar.count()}개 "
                  f"(읽은 곳 {len(read.results)}곳, {elapsed:.2f}초)")
        else:
            print(f"목록 다시 읽기: 바뀐 것 없음 ({len(rows)}개, 읽은 곳 {len(read.results)}곳, {elapsed:.2f}초)")
        for source, result in read.results.items():
            if isinstance(result, video_list.ScanResult):
                self._report_list_read(source.folder, result)
            else:
                self._report_list_source_problem(source.folder, read.errors[source],
                                                 gone=result is video_list.FOLDER_GONE, note=read.notes[source])
        self._report_unverified_files(read.unverified)
        if self.is_thumbnail_mode and (added or check_thumbnails):
            with self._hold_sidebar_refresh():
                if check_thumbnails:
                    self._check_thumbnails_after_refresh(read)  # 새 영상도 여기서 한 번
                else:
                    # 저절로 다시 읽음: 새 영상만 — 저장된 썸네일을 바로 붙이고 없는 것만 만듦 (남은 영상의 썸네일은 다시
                    # 보지 않음 — 앱을 오갈 때마다 모든 영상을 NAS에서 확인하지 않게)
                    state = self._thumbnail_pass_state()
                    to_generate, _checked = self._apply_disk_thumbnails(added)
                    for file_path, context in to_generate:
                        stopped = self._thumbnail_pass_stopped(state)
                        if stopped:
                            print(f"새 영상의 썸네일 만들기를 멈춤 ({stopped})")
                            break
                        self.generate_thumbnail(file_path, context=context)

    def _check_thumbnails_after_refresh(self, read):
        """새로고침 버튼·F5로 다시 읽은 결과(read)를 넣은 뒤 (썸네일 모드, 목록 다시 읽기는 미룬 채 — _apply_sidebar_read):
        모든 영상의 썸네일을 썸네일 버튼처럼 확인 — 저장된 썸네일(영상보다 새것)은 바로 붙이고, 같은 이름으로 다시 렌더링해
        썸네일보다 새 영상·썸네일이 없거나 읽을 수 없는 영상만 진행바와 함께 다시 만듦 (_make_thumbnails).

        건너뜀 (로그에 몇 개·왜): 이번 읽기에서 확인하지 못한 영상 — 읽지 못한 목록 폴더·하위 폴더 아래, 있는지 확인하지 못한
        따로 넣은 파일 (그 문제는 목록 창으로 이미 알림. NAS가 끊겼으면 영상마다 GUI 스레드에서 기다리고 "영상 확인 실패"
        창이 또 뜸). 썸네일 폴더를 만들지 못해 화면에만 보이는 영상 중 아이콘이 이미 있는 것 (저장된 썸네일이 없어
        새로고침마다 다시 만들게 됨 — 아이콘이 없는 것만 만듦).
        """
        confirmed = {source: {paths.path_key(path) for _name, path in result.videos}
                     for source, result in read.results.items() if isinstance(result, video_list.ScanResult)}
        unverified = {paths.path_key(path) for path, _error, _note in read.unverified}
        items = []
        unread = 0
        shown = 0
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            file_path = item.data(Qt.UserRole)
            if not file_path:
                continue
            key = paths.path_key(file_path)
            source = item.data(SIDEBAR_SOURCE_ROLE)
            if source is None:
                unconfirmed = key in unverified  # 따로 넣은 파일: 있는 것은 읽기에서 확인함
            else:
                unconfirmed = key not in confirmed.get(source, ())  # 그 출처를 다시 읽어 나온 영상만 확인함
            context = item.data(THUMBNAIL_CONTEXT_ROLE)
            if unconfirmed:
                unread += 1
            elif context is not None and context.problem is not None and not item.icon().isNull():
                shown += 1
            else:
                items.append(item)
        if unread:
            print(f"새로고침: 이번에 읽지 못한 곳의 영상 {unread}개는 썸네일을 확인하지 않음 "
                  f"(목록 폴더·그 안의 폴더를 읽지 못했거나 따로 넣은 파일을 확인하지 못함 — 창으로 알림)")
        if shown:
            print(f"새로고침: 썸네일 폴더가 없어 화면에만 보이는 영상 {shown}개는 아이콘이 있어 다시 만들지 않음")
        state = self._thumbnail_pass_state()
        to_generate, checked = self._apply_disk_thumbnails(items)
        started, _stopped = self._make_thumbnails(to_generate, state)
        print(f"새로고침: 썸네일 확인 {checked}개, 다시 만듦 {started}개")

    def _apply_sidebar_plan(self, plan):
        """video_list.plan_refresh의 계획대로 사이드바를 바꿈 → 새로 넣은 항목 목록. 남는 항목은 건드리지 않음.

        먼저 세대 번호를 올림: 썸네일 반복·백그라운드 처리가 예전 줄 번호나 뺀 항목을 쓰지 않게 (반복은 미뤄 두므로 보통은
        돌고 있지 않음). 맨 위에 보이던 영상이 남으면 다시 맨 위로, 빠졌으면 스크롤 위치를 그대로.
        """
        removed, final = plan
        self._bump_sidebar_generation()
        anchor = next((self.sidebar.item(i) for i in range(self.sidebar.count())
                       if self.sidebar.visualItemRect(self.sidebar.item(i)).bottom() >= 0), None)
        scroll = self.sidebar.verticalScrollBar().value()
        added = []
        self.sidebar.setUpdatesEnabled(False)
        try:
            for row in reversed(removed):
                print(f"목록에서 뺌 (디스크에 없음): {self.sidebar.takeItem(row).data(Qt.UserRole)}")
            known = self._known_sidebar_videos()
            for index, entry in enumerate(final):
                if isinstance(entry, int):
                    continue
                source, label, file_path = entry
                item = self._new_sidebar_item(label, file_path, self._sidebar_sources[source], source, known)
                self.sidebar.insertItem(index, item)
                added.append(item)
                print(f"목록에 넣음 (새 영상): {file_path}")
        finally:
            self.sidebar.setUpdatesEnabled(True)
        if anchor is not None and self.sidebar.row(anchor) >= 0:
            self.sidebar.scrollToItem(anchor, QAbstractItemView.PositionAtTop)
        else:
            self.sidebar.verticalScrollBar().setValue(scroll)
        return added

    def _report_list_source_problem(self, folder, error, gone=None, note=""):
        """목록에 영상을 넣는(넣은) 폴더를 읽지 못함 → 창 ((제목, 폴더, 오류)마다 한 번). 처음 불러올 때와 다시 읽을 때 같은
        문구·같은 기록 — 같은 문제가 두 번 뜨지 않음. gone: 지워졌는지 (None이면 여기서 video_list.check_gone으로 확인),
        note: 없어진 것으로 보지 않은 까닭 (확인한 위 폴더와 그 상태 — 창·로그에 덧붙임)."""
        if gone is None:
            gone, note = video_list.check_gone(folder, error)
        reason = f"{type(error).__name__}: {error}" + (f"\n{note}" if note else "")
        if gone:
            title = LIST_FOLDER_GONE
            text = ("영상 목록 폴더가 디스크에 없습니다 (지워졌거나 이름이 바뀜). 이 폴더의 영상은 목록에서 뺍니다.\n"
                    f"폴더: {folder}\n이유: {reason}")
        else:
            title = LIST_READ_FAILED
            text = ("영상 목록 폴더를 읽지 못했습니다 (NAS 연결 끊김·권한 등). 목록은 그대로 두고, 연결을 확인한 뒤 "
                    f"새로고침(F5)을 누르면 다시 읽습니다.\n폴더: {folder}\n이유: {reason}")
        self._report_list_problem(title, folder, (type(error).__name__, str(error)), text)

    def _report_list_read(self, folder, result):
        """목록 폴더를 읽음: 전에 알린 이 폴더의 문제 기록은 지우고(다시 생기면 또 알림), 읽지 못한 하위 폴더가 있으면 알림
        (처음 불러올 때와 다시 읽을 때 같은 문구 — 폴더가 많으면(공유가 끊김 등) 10개까지만)."""
        detail = tuple((paths.path_key(sub), type(e).__name__, str(e)) for sub, e in result.unreadable)
        key = (LIST_READ_FAILED, paths.path_key(folder), detail)
        self._list_problems_shown = {shown for shown in self._list_problems_shown
                                     if shown[1] != key[1] or (result.unreadable and shown == key)}
        if not result.unreadable:
            return
        lines = [f"{sub}\n  → {type(e).__name__}: {e}" for sub, e in result.unreadable]
        if len(lines) > 10:
            lines = lines[:10] + [f"… 외 {len(lines) - 10}개"]
        self._report_list_problem(
            LIST_READ_FAILED, folder, detail,
            "목록 폴더 안에서 읽지 못한 폴더가 있어 그 안의 영상은 확인하지 못했습니다 — 목록에 새로 넣지도 빼지도 "
            f"않습니다 (권한·NAS 연결 끊김 등).\n목록 폴더: {folder}\n\n" + "\n".join(lines))

    def _report_unverified_files(self, unverified):
        """따로 넣은 영상 중 있는지 확인하지 못한 것(공유가 끊김·권한) → 목록에 그대로 두고 창으로 (같은 문제는 한 번).
        unverified: [(경로, OSError, 없어진 것으로 보지 않은 까닭)]."""
        detail = tuple((paths.path_key(path), type(e).__name__, str(e)) for path, e, _note in unverified)
        self._list_problems_shown = {shown for shown in self._list_problems_shown
                                     if shown[1] is not None or (unverified and shown[2] == detail)}
        if unverified:
            self._report_list_problem(
                LIST_READ_FAILED, None, detail,
                "따로 넣은 영상을 확인하지 못해 목록에 그대로 둡니다 (NAS 연결 끊김·권한 등).\n\n"
                + "\n".join(f"{path}\n  → {type(e).__name__}: {e}" + (f"\n  → {note}" if note else "")
                            for path, e, note in unverified))

    def _report_list_problem(self, title, folder, detail, text):
        """영상 목록을 만들거나 다시 읽다 생긴 문제를 알림: 로그에는 매번, 창은 (제목, 폴더, 오류 종류·내용)마다 한 번 —
        창이 다시 활성될 때마다 다시 읽어도 창이 계속 뜨지 않게. 그 폴더를 다시 읽을 수 있게 되면 기록을 지움
        (_report_list_read)."""
        print(f"{title}\n{text}")
        key = (title, paths.path_key(folder) if folder else None, detail)
        if key in self._list_problems_shown:
            return
        # 창을 띄우기 전에 넣음: 창이 떠 있는 동안 같은 문제가 다시 와도 창을 또 띄우지 않게
        self._list_problems_shown.add(key)
        QMessageBox.warning(self, title, text)

    def _sidebar_item_for(self, file_path):
        """사이드바에서 그 영상의 (첫) 항목. 없으면 None."""
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and paths.same_path(item.data(Qt.UserRole), file_path):
                return item
        return None

    def _item_thumbnail_context(self, item, file_path):
        """항목의 썸네일 자리. 사이드바에 없는 영상(item=None)이면 지금 상태의 자리."""
        context = item.data(THUMBNAIL_CONTEXT_ROLE) if item is not None else None
        if context is None:
            context = self._new_item_thumbnail_context(file_path)
            if item is not None:
                print(f"썸네일 자리가 없는 사이드바 항목 — 지금 상태로 정함: {file_path}")
                item.setData(THUMBNAIL_CONTEXT_ROLE, context)
        return context

    def _resolve_pending_thumbnail_context(self, context):
        """아직 정하지 않은 썸네일 자리를 정함: pending_base 아래 썸네일 폴더를 만들고, 같은 자리를 기다리던 항목 모두에 기억.

        만들지 못하면 폴더 문제(화면에만, 창은 썸네일을 쓸 때). 예전처럼, 아무 상태도 정하지 않은 때면 새로 넣을 항목의
        자리로도 씀 (예: 처음 끌어다 놓은 파일들의 썸네일 폴더를 그다음에 끌어다 놓은 파일도 씀).
        """
        base = context.pending_base
        try:
            folder = thumbnails.ensure_folder(base)
        except OSError as e:
            resolved = ThumbnailContext(
                problem=self._thumbnail_folder_problem_for(os.path.join(base, thumbnails.FOLDER_NAME), e))
        else:
            resolved = ThumbnailContext(folder=folder)
            print(f"generate_thumbnail에서 썸네일 폴더 설정: {folder}")
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item is not None and item.data(THUMBNAIL_CONTEXT_ROLE) == context:
                item.setData(THUMBNAIL_CONTEXT_ROLE, resolved)
        for source, source_context in self._sidebar_sources.items():  # 그곳에서 새로 생길 영상도 같은 자리
            if source_context == context:
                self._sidebar_sources[source] = resolved
        if not self.current_thumbnail_folder and self._thumbnail_folder_problem is None:
            self.current_thumbnail_folder = resolved.folder
            self._thumbnail_folder_problem = resolved.problem
        return resolved

    def _apply_disk_thumbnails(self, items=None):
        """사이드바 영상마다 그 항목의 썸네일 폴더에 있는 썸네일(영상보다 새것)을 바로 적용하고, (새로 만들어야 할
        [(영상, 그 항목의 자리)], 확인한 영상 수)를 돌려줌. 항목 자리의 미뤄 둔 썸네일 폴더 문제는 여기서 창으로
        ((폴더, 제목)마다 한 번). items: 그 항목만 (목록 다시 읽기로 새로 넣은 항목 — 남은 항목의 썸네일은 다시 보지 않음,
        새로고침이 고른 항목). 없으면 모든 항목.

        새로 만들 것: 썸네일이 없거나, 영상보다 오래됐거나, 영상보다 새것이지만 읽을 수 없는(깨진) 썸네일, 화면에만인 항목.
        캐시 적용이 이벤트를 처리하는 동안 목록이 바뀌거나(job·폴더를 바꿈) 목록 모드로 바꾸거나 창을 닫으면 거기서 멈춤
        (_thumbnail_pass_stopped). 같은 영상이 여러 번 있으면 한 번만 (아이콘은 경로가 같은 모든 항목에 붙음).
        """
        state = self._thumbnail_pass_state()
        to_generate = []
        seen = set()
        if items is None:
            items = (self.sidebar.item(i) for i in range(self.sidebar.count()))
        for item in items:
            stopped = self._thumbnail_pass_stopped(state)
            if stopped:
                print(f"썸네일 확인을 멈춤 ({stopped})")
                break
            if item is None:
                continue  # None인 경우 건너뛰기
            file_path = item.data(Qt.UserRole)
            if not file_path:
                continue
            key = paths.path_key(file_path)
            if key in seen:
                continue  # 같은 영상의 다른 항목 (같은 자리 — 이미 처리함)
            seen.add(key)  # 확인한 영상 (그 수를 돌려줌)
            context = self._item_thumbnail_context(item, file_path)
            if not self._video_is_available(file_path, context):
                continue
            if context.pending_base is not None:
                context = self._resolve_pending_thumbnail_context(context)
            self._report_context_problem(context)
            fresh = self._has_disk_thumbnail(file_path, context)
            if fresh is None:
                continue  # 영상을 확인하지 못함 (없어졌거나 읽을 수 없음)
            if fresh:
                pixmap = QPixmap(thumbnails.thumbnail_path(context.folder, file_path))
                if not pixmap.isNull():
                    print(f"캐시된 썸네일 즉시 적용: {file_path}")
                    self.update_sidebar_item_thumbnail(file_path, pixmap)
                    continue
                print(f"디스크 썸네일을 읽을 수 없어 새로 만듦: {file_path}")
            else:
                print(f"새 썸네일 생성 예정: {file_path}")
            to_generate.append((file_path, context))
        return to_generate, len(seen)

    def _video_is_available(self, file_path, context):
        """썸네일을 만들 영상 파일이 있는지 os.stat으로 확인 (os.path.isfile은 오류를 숨기고 False를 돌려줌).

        확인하지 못하면 False: 없어졌으면 로그만, 다른 오류는 창으로 알림 (_report_video_problem).
        """
        try:
            info = os.stat(file_path)
        except OSError as e:
            self._report_video_problem(file_path, e, context)
            return False
        return stat.S_ISREG(info.st_mode)

    def _report_video_problem(self, file_path, error, context):
        """영상을 확인하지 못함 → 그 영상의 썸네일은 건너뜀. 없어진 것만 로그로 끝내고, 다른 오류(권한·시간 초과·
        끊긴 공유 등)는 "영상 확인 실패" 창으로 — 조용히 건너뛰지 않음.

        없어진 것: FileNotFoundError이고 영상의 폴더는 확인됨. Windows는 끊긴 SMB 공유(ERROR_BAD_NETPATH·BAD_NET_NAME)도
        FileNotFoundError로 올리고 Mac autofs도 그럴 수 있어, 폴더까지 확인하지 못하면 두 오류를 함께 알림.
        창은 목록 단위로 한 번: 그 항목 자리의 썸네일 폴더(또는 만들지 못한 폴더·정할 폴더) — 영상 폴더마다 창이 뜨지 않게.
        """
        reason = f"이유: {type(error).__name__}: {error}"
        if isinstance(error, FileNotFoundError):
            folder = os.path.dirname(file_path)
            try:
                os.stat(folder)
            except OSError as folder_error:
                reason += f"\n영상 폴더도 확인하지 못함: {type(folder_error).__name__}: {folder_error}"
            else:
                print(f"영상이 없어져 썸네일을 건너뜀: {file_path} ({type(error).__name__}: {error})")
                return
        self._report_thumbnail_problem(
            context.folder
            or (context.problem[0] if context.problem else None)
            or context.pending_base,
            THUMBNAIL_VIDEO_PROBLEM,
            "썸네일을 만들 영상을 확인하지 못해 이 영상의 썸네일은 건너뜁니다 (권한·연결 끊김 등).\n"
            f"영상: {file_path}\n{reason}",
        )

    def _has_disk_thumbnail(self, file_path, context):
        """그 항목의 썸네일 폴더에 영상보다 새 썸네일이 있는지 확인합니다 (영상이 바뀌었으면 False → 새로 만듦).

        썸네일 폴더가 없는 자리(폴더 문제)면 False. 영상을 확인하지 못하면 None (건너뜀): 없어졌으면 로그만,
        다른 오류는 창으로 (_report_video_problem). 썸네일 파일을 확인하지 못하면(권한 등) 창으로 알리고
        ((폴더, 제목)마다 한 번) False → 새로 만듦.
        """
        if not context.folder:
            return False
        thumbnail_path = thumbnails.thumbnail_path(context.folder, file_path)
        try:
            return thumbnails.is_fresh(thumbnail_path, file_path)
        except OSError as e:
            if e.filename == file_path:  # 영상 쪽 오류 (썸네일이 없는 것은 is_fresh가 False로 돌려줌)
                self._report_video_problem(file_path, e, context)
                return None
            self._report_thumbnail_problem(
                context.folder,
                THUMBNAIL_FOLDER_PROBLEM,
                "썸네일 파일을 확인하지 못해 새로 만듭니다.\n"
                f"썸네일 파일: {thumbnail_path}\n이유: {type(e).__name__}: {e}",
            )
            return False

    def generate_thumbnail(self, file_path, item=None, context=None):
        """영상 하나의 썸네일: 그 항목의 썸네일 자리(ThumbnailContext)에서 읽거나 만들어 저장 (폴더가 없는 자리면 화면에만).

        context: 미리 꺼내 둔 그 항목의 자리 (반복에서 — 이벤트를 처리하는 동안 항목이 지워질 수 있음). 없으면 item의 자리,
        item도 없으면 경로로 찾고, 사이드바에 없는 영상이면 지금 상태의 자리. 아이콘은 경로로 찾아 붙임.
        다른 썸네일을 기다리는 동안 목록이 바뀌거나(job·폴더를 바꿈) 썸네일 모드에서 목록 모드로 바꾸거나 창을 닫으면 만들지
        않음 (_thumbnail_pass_stopped). → 워커를 띄웠으면 True, 아니면 False (저장된 썸네일을 붙임·영상을 확인하지 못함·멈춤).
        워커가 썸네일을 만들지 못하면(failed) 창으로 ((폴더, 제목)마다 한 번 — _on_thumbnail_failed).
        """
        import time
        print(f"썸네일 생성 시작: {file_path}")
        state = self._thumbnail_pass_state()
        
        if context is None:
            if item is None:
                item = self._sidebar_item_for(file_path)
            context = self._item_thumbnail_context(item, file_path)
        if context.pending_base is not None:
            # 썸네일 폴더를 아직 정하지 않음 (예: 처음 끌어다 놓은 파일 — 예전의 드래그한 폴더·영상 폴더): 영상이 있을 때만 만듦
            if not self._video_is_available(file_path, context):
                return False
            context = self._resolve_pending_thumbnail_context(context)
        # 이 항목 자리의 미뤄 둔 썸네일 폴더 문제(폴더를 만들지 못함·권한을 바꾸지 못함)를 창으로 ((폴더, 제목)마다 한 번)
        self._report_context_problem(context)
        # 폴더가 없으면(썸네일 폴더 문제) 다른 폴더로 대신하지 않고 화면에만
        thumbnail_folder = context.folder
        
        # 동시 실행 제한 (1개로 더 줄임)
        # 디스크에 저장된 썸네일 확인 (영상보다 오래된 썸네일은 워커가 새로 만들어 바꿈)
        if thumbnail_folder:
            thumbnail_path = thumbnails.thumbnail_path(thumbnail_folder, file_path)
            fresh = self._has_disk_thumbnail(file_path, context)
            if fresh is None:
                return False  # 영상을 확인하지 못함 (없어졌거나 읽을 수 없음)
            
            if fresh:
                print(f"디스크에서 썸네일 로드: {thumbnail_path}")
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    # UI 업데이트
                    self.update_sidebar_item_thumbnail(file_path, pixmap)
                    return False
                else:
                    print(f"디스크 썸네일이 손상됨, 재생성: {thumbnail_path}")
                    try:
                        os.remove(thumbnail_path)
                    except FileNotFoundError:
                        pass  # 그사이 다른 PC가 지움 — 새로 만들면 됨
                    except OSError as e:
                        # 지우지 못해도 워커가 새 썸네일로 바꿔 저장함 (임시 파일 + os.replace — 그것도 못 하면 저장 실패 창)
                        self._report_thumbnail_problem(
                            thumbnail_folder,
                            THUMBNAIL_FOLDER_PROBLEM,
                            "읽을 수 없는(깨진) 썸네일 파일을 지우지 못했습니다. 새로 만든 썸네일로 바꿔 저장해 봅니다.\n"
                            f"썸네일 파일: {thumbnail_path}\n이유: {type(e).__name__}: {e}",
                        )
        max_workers = 1
        while len(self.thumbnail_workers) >= max_workers:
            QApplication.processEvents()
            time.sleep(0.2)  # 대기 시간을 늘려서 메모리 부하 감소
            # 완료된 워커들 정리
            self.cleanup_thumbnail_workers()
        stopped = self._thumbnail_pass_stopped(state)
        if stopped:
            print(f"이 영상의 썸네일은 만들지 않음 ({stopped}): {file_path}")
            return False

        # 워커 생성 (썸네일 폴더가 없으면 저장하지 않고 화면에만)
        worker = ThumbnailWorker(file_path, self.thumbnail_size, thumbnail_folder)
        worker.thumbnail_ready.connect(self.on_thumbnail_ready)
        worker.save_failed.connect(self._on_thumbnail_save_failed)
        # 만들지 못함 → 그 항목 자리의 폴더(화면에만인 자리는 만들지 못한 폴더)마다 한 번 창으로
        worker.failed.connect(functools.partial(
            self._on_thumbnail_failed,
            context.folder or (context.problem[0] if context.problem else None) or context.pending_base))
        
        # 안전한 워커 제거 함수
        def safe_remove_worker():
            try:
                if hasattr(self, 'thumbnail_workers') and worker in self.thumbnail_workers:
                    self.thumbnail_workers.remove(worker)
                    print(f"워커 제거 완료: {file_path}")
            except Exception as e:
                print(f"워커 제거 중 에러: {e}")
            finally:
                try:
                    if worker.isRunning():
                        worker.stop()  # 안전한 중지
                        worker.wait(2000)
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 정리 중 오류: {e}")
        
        worker.finished.connect(safe_remove_worker)
        self.thumbnail_workers.append(worker)
        worker.start()
        print(f"썸네일 워커 시작: {file_path}, 현재 워커 수: {len(self.thumbnail_workers)}")
        return True

    def _use_dropped_folder_for_thumbnails(self, folder_path):
        """끌어다 놓은 폴더(여러 개면 첫 폴더)의 썸네일은 그 폴더의 썸네일 폴더에 (전에 고른 job·폴더가 아니라).

        영상 영역·사이드바·창 어디에 끌어다 놓아도 같음. 전에 연 job의 썸네일 폴더 문제는 이제 상관없음.
        썸네일 폴더를 만들지 못하면 job 폴더처럼 기억만 하고(화면에만, 창은 썸네일을 쓸 때) 예외는 올리지 않음.
        """
        # 폴더 경로를 selected_folder_path로 설정 (썸네일 폴더 생성용)
        self.selected_folder_path = folder_path
        print(f"드래그앤드롭으로 썸네일 폴더 설정: {folder_path}")
        self._thumbnail_folder_problem = None
        try:
            self.current_thumbnail_folder = thumbnails.ensure_folder(folder_path)
        except OSError as e:
            self.current_thumbnail_folder = None
            self._remember_thumbnail_folder_problem(os.path.join(folder_path, thumbnails.FOLDER_NAME), e)
            return
        print(f"드래그앤드롭으로 썸네일 폴더 설정: {self.current_thumbnail_folder}")

    def _thumbnail_folder_problem_for(self, folder, error):
        """썸네일 폴더를 만들지 못한 문제 (폴더, 창 제목, 내용) → 그 자리의 썸네일은 저장하지 않고 화면에만. 로그는 바로."""
        text = ("썸네일 폴더를 만들지 못해 이 작업의 썸네일은 저장하지 않습니다.\n"
                "이번에는 화면에만 보이고, 다음에 썸네일 모드를 켜면 다시 만듭니다.\n"
                f"이유: {type(error).__name__}: {error}")
        print(f"{THUMBNAIL_FOLDER_PROBLEM}: {folder}\n{text}")
        return (folder, THUMBNAIL_FOLDER_PROBLEM, text)

    def _remember_thumbnail_folder_problem(self, folder, error):
        """썸네일 폴더를 만들지 못함 → 새로 넣는 항목의 썸네일은 저장하지 않고 화면에만 (다른 폴더로 대신하지 않음).

        로그에는 바로 남기고, 창은 썸네일을 쓸 때(썸네일 모드·썸네일 생성) _report_context_problem이 띄움.
        """
        self._thumbnail_folder_problem = self._thumbnail_folder_problem_for(folder, error)

    def _report_context_problem(self, context):
        """썸네일을 쓸 때(썸네일 모드·썸네일 생성) 그 항목 자리의 미뤄 둔 썸네일 폴더 문제를 창으로 ((폴더, 제목)마다 한 번).

        폴더를 만들지 못함(context.problem) 또는 폴더는 쓰지만 권한을 바꾸지 못함(thumbnails.share_problem).
        이미 알린 (폴더, 제목)이면 아무것도 하지 않음 (영상마다 불리므로 로그도 다시 남기지 않음).
        """
        if context.problem is not None:
            problem = context.problem
        elif context.folder and thumbnails.share_problem(context.folder):
            problem = (
                context.folder,
                THUMBNAIL_FOLDER_PROBLEM,
                "썸네일 폴더의 권한을 바꾸지 못했습니다. 이 PC에서는 썸네일을 저장하지만, 다른 NAS 계정을 쓰는 PC"
                "(Windows 등)는 이 폴더에 저장하지 못해 매번 다시 만들 수 있습니다.\n"
                f"이유: {thumbnails.share_problem(context.folder)}",
            )
        else:
            return
        if (problem[0], problem[1]) not in self._thumbnail_problems_shown:
            self._report_thumbnail_problem(*problem)

    def _on_thumbnail_save_failed(self, folder, detail):
        """ThumbnailWorker.save_failed: 저장하지 못한 썸네일도 이번 실행에서는 아이콘으로 보임."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_SAVE_FAILED,
            "썸네일 파일을 저장하지 못했습니다.\n"
            f"이번에는 화면에만 보이고, 다음에 썸네일 모드를 켜면 다시 만듭니다.\n{detail}",
        )

    def _on_thumbnail_failed(self, folder, detail):
        """ThumbnailWorker.failed: 영상의 썸네일을 만들지 못함 (OpenCV가 열지 못함·첫 프레임을 읽지 못함·예상 못 한 오류) →
        창 ((폴더, 제목)마다 한 번 — 영상마다 뜨지 않게, 로그에는 매번). folder: 그 항목 자리의 썸네일 폴더."""
        self._report_thumbnail_problem(
            folder,
            THUMBNAIL_MAKE_FAILED,
            "영상의 썸네일을 만들지 못해 이 영상은 아이콘 없이 둡니다 (영상이 손상되었거나 지원하지 않는 형식이거나 "
            f"읽을 수 없음).\n{detail}",
        )

    def _report_thumbnail_problem(self, folder, title, text):
        """썸네일 문제를 알림: 로그에는 매번, 창은 이번 실행에서 (폴더, 제목)마다 한 번
        ("썸네일 폴더 문제"를 알린 폴더라도 나중의 "썸네일 저장 실패"는 따로 알림).

        title: THUMBNAIL_SAVE_FAILED·THUMBNAIL_FOLDER_PROBLEM·THUMBNAIL_VIDEO_PROBLEM·THUMBNAIL_MAKE_FAILED.
        text: 무슨 일이 있었고 썸네일이 어떻게 되는지와 이유.
        창에는 NAS 권한 확인 안내와 폴더 경로를 덧붙임.
        """
        print(f"{title}: {folder}\n{text}")
        if (folder, title) in self._thumbnail_problems_shown:
            return
        # 창을 띄우기 전에 넣음: 창이 떠 있는 동안 다음 저장 실패 시그널이 들어와도 창을 또 띄우지 않게
        self._thumbnail_problems_shown.add((folder, title))
        QMessageBox.warning(
            self,
            title,
            f"{text}\n\n"
            "NAS에서 이 폴더의 권한(이 PC가 쓰는 NAS 계정의 읽기·쓰기 권한)을 확인하세요.\n\n"
            f"폴더: {folder}",
        )

    def on_thumbnail_ready(self, file_path, pixmap):
        """썸네일 생성이 완료되었을 때 호출됩니다. 예외는 잡지 않음 (앱의 sys.excepthook이 스택 트레이스째 로그와 창으로)."""
        try:
            print(f"썸네일 생성 완료: {file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap: {file_path}")
                return
            
            # 사이드바 아이템 업데이트
            self.update_sidebar_item_thumbnail(file_path, pixmap)
        finally:
            # 메모리 정리
            import gc
            gc.collect()

    def update_sidebar_item_thumbnail(self, file_path, pixmap):
        """사이드바 아이템의 썸네일을 업데이트합니다. 예외는 잡지 않음 (앱의 sys.excepthook이 스택 트레이스째 로그와 창으로 —
        예전에는 로그에만 남기고 아이콘 없이 지나감)."""
        try:
            print(f"썸네일 아이템 업데이트 시작: {file_path}")
            
            # pixmap 유효성 검사
            if pixmap.isNull():
                print(f"유효하지 않은 pixmap으로 업데이트 시도: {file_path}")
                return
            
            # 사이드바에서 해당 파일을 찾아 썸네일 설정 (같은 영상이 여러 번 있으면 모든 항목에)
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item and paths.same_path(item.data(Qt.UserRole), file_path):
                    # 아이콘 설정
                    item.setIcon(QIcon(pixmap))
                    print(f"썸네일 아이템 업데이트 완료: {file_path}")
        finally:
            # 메모리 정리
            QApplication.processEvents()

    def clear_thumbnails(self):
        """리스트 모드에서 썸네일을 제거합니다."""
        try:
            # 실행 중인 워커들만 중지
            for worker in self.thumbnail_workers:
                try:
                    worker.stop()
                except:
                    pass
            self.thumbnail_workers.clear()
            
            # UI에서만 썸네일 제거 (디스크 썸네일은 유지)
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item:
                    item.setIcon(QIcon())
                    # 파일명만 표시
                    file_path = item.data(Qt.UserRole)
                    if file_path:
                        filename = os.path.basename(file_path)
                        item.setText(filename)
            print("썸네일 UI 제거 완료 (디스크 썸네일 유지)")
        except Exception as e:
            print(f"썸네일 제거 중 오류: {e}")

    def get_current_job_path(self):
        """현재 선택된 job의 경로를 반환합니다."""
        try:
            # 1. 선택된 폴더 경로가 있으면 우선 사용 (북마크, 드래그앤드롭 등)
            if hasattr(self, 'selected_folder_path') and self.selected_folder_path:
                if os.path.exists(self.selected_folder_path):
                    print(f"선택된 폴더 경로 사용: {self.selected_folder_path}")
                    return self.selected_folder_path
                else:
                    print(f"선택된 폴더 경로가 존재하지 않음: {self.selected_folder_path}")
            
            # 2. UI에서 job 선택으로 설정된 경로가 있으면 사용
            if hasattr(self, 'current_job_path') and self.current_job_path:
                if os.path.exists(self.current_job_path):
                    print(f"UI job 선택 경로 사용: {self.current_job_path}")
                    return self.current_job_path
                else:
                    print(f"UI job 선택 경로가 존재하지 않음: {self.current_job_path}")
            
            # 3. 경로를 찾을 수 없는 경우
            print("Job 경로를 찾을 수 없음")
            return None
                
        except Exception as e:
            print(f"Job 경로 조회 중 오류: {e}")
            return None

    def setup_thumbnail_folder(self):
        """현재 job에 대한 썸네일 폴더를 설정합니다."""
        try:
            # 이미 썸네일 폴더가 설정되어 있으면 그대로 사용
            if hasattr(self, 'current_thumbnail_folder') and self.current_thumbnail_folder:
                print(f"이미 설정된 썸네일 폴더 사용: {self.current_thumbnail_folder}")
                return True
            
            # job 경로를 찾아서 썸네일 폴더 설정
            job_path = self.get_current_job_path()
            if job_path:
                # 폴더가 없으면 생성
                thumbnail_folder = thumbnails.ensure_folder(job_path)
                
                self.current_thumbnail_folder = thumbnail_folder
                print(f"썸네일 폴더 설정: {thumbnail_folder}")
                return True
            else:
                self.current_thumbnail_folder = None
                print("Job 경로를 찾을 수 없어 썸네일 폴더를 설정하지 않음")
                return False
        except Exception as e:
            print(f"썸네일 폴더 설정 중 오류: {e}")
            self.current_thumbnail_folder = None
            return False

    def start_background_thumbnail_loading(self):
        """백그라운드에서 썸네일 로딩을 시작합니다."""
        try:
            # 현재 사이드바의 영상마다 그 항목의 썸네일 폴더에 있는 썸네일 (썸네일 폴더가 정해진 항목만 —
            # 폴더 문제·아직 정하지 않은 항목은 읽을 썸네일이 없음)
            thumbnail_files = []
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                if item:
                    file_path = item.data(Qt.UserRole)
                    if file_path and os.path.isfile(file_path):
                        folder = self._item_thumbnail_context(item, file_path).folder
                        if folder:
                            thumbnail_files.append((file_path, thumbnails.thumbnail_path(folder, file_path)))
            
            if not thumbnail_files:
                print("로딩할 썸네일이 없음 (썸네일 폴더가 정해진 영상 없음)")
                return
            
            print(f"백그라운드 썸네일 로딩 시작: {len(thumbnail_files)}개 파일")
            
            # 기존 로더 워커가 있다면 중지
            if self.thumbnail_loader_worker and self.thumbnail_loader_worker.isRunning():
                self.thumbnail_loader_worker.stop()
                self.thumbnail_loader_worker.wait(3000)
                if self.thumbnail_loader_worker.isRunning():
                    self.thumbnail_loader_worker.terminate()
                    self.thumbnail_loader_worker.wait(2000)
                self.thumbnail_loader_worker.deleteLater()
                self.thumbnail_loader_worker = None
            
            # 새로운 로더 워커 생성
            self.thumbnail_loader_worker = ThumbnailLoaderWorker(thumbnail_files)
            self.thumbnail_loader_worker.thumbnail_loaded.connect(self.on_background_thumbnail_loaded)
            self.thumbnail_loader_worker.loading_finished.connect(self.on_background_loading_finished)
            self.thumbnail_loader_worker.start()
            
        except Exception as e:
            print(f"백그라운드 썸네일 로딩 시작 중 오류: {e}")

    def on_background_thumbnail_loaded(self, file_path, pixmap):
        """백그라운드에서 썸네일이 로드되었을 때 호출됩니다."""
        try:
            # 캐시에 저장
            
            
            # UI 업데이트
            self.update_sidebar_item_thumbnail(file_path, pixmap)
            
        except Exception as e:
            print(f"백그라운드 썸네일 로드 처리 중 오류: {file_path}, 오류: {e}")

    def on_background_loading_finished(self):
        """백그라운드 로딩이 완료되었을 때 호출됩니다."""
        try:
            print("백그라운드 썸네일 로딩 완료")
            
            # 로더 워커 정리
            if self.thumbnail_loader_worker:
                # 워커가 실행 중이면 중지
                if self.thumbnail_loader_worker.isRunning():
                    self.thumbnail_loader_worker.stop()
                    self.thumbnail_loader_worker.wait(2000)
                # 안전하게 삭제
                self.thumbnail_loader_worker.deleteLater()
                self.thumbnail_loader_worker = None
            
        except Exception as e:
            print(f"백그라운드 로딩 완료 처리 중 오류: {e}")

    def schedule_background_thumbnail_loading(self):
        """백그라운드 썸네일 로딩을 스케줄링합니다."""
        try:
            # 0.5초 후에 백그라운드 로딩 시작 (3초에서 0.5초로 단축)
            self.thumbnail_loading_timer.start(500)
            print("백그라운드 썸네일 로딩 스케줄링 (0.5초 후)")
        except Exception as e:
            print(f"백그라운드 로딩 스케줄링 중 오류: {e}")

        def cleanup_thumbnail_folder(self):
            """현재 job의 썸네일 폴더를 정리합니다."""
            try:
                if self.current_thumbnail_folder and os.path.exists(self.current_thumbnail_folder):
                    # 원본 파일이 존재하지 않는 썸네일들 삭제
                    import hashlib
                    for filename in os.listdir(self.current_thumbnail_folder):
                        if filename.endswith('.jpg'):
                            thumbnail_path = os.path.join(self.current_thumbnail_folder, filename)
                            try:
                                pixmap = QPixmap(thumbnail_path)
                                if pixmap.isNull():
                                    os.remove(thumbnail_path)
                                    print(f"손상된 썸네일 삭제: {thumbnail_path}")
                            except Exception:
                                try:
                                    os.remove(thumbnail_path)
                                    print(f"손상된 썸네일 삭제: {thumbnail_path}")
                                except Exception:
                                    pass
                    print(f"썸네일 폴더 정리 완료: {self.current_thumbnail_folder}")
            except Exception as e:
                print(f"썸네일 폴더 정리 중 오류: {e}")

    def get_thumbnail_disk_usage(self):
        """현재 썸네일 폴더의 디스크 사용량을 반환합니다."""
        try:
            if not self.current_thumbnail_folder or not os.path.exists(self.current_thumbnail_folder):
                return {'total_size': 0, 'file_count': 0, 'folder_path': self.current_thumbnail_folder}
            
            total_size = 0
            file_count = 0
            
            for filename in os.listdir(self.current_thumbnail_folder):
                if filename.endswith('.jpg'):
                    file_path = os.path.join(self.current_thumbnail_folder, filename)
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
                        file_count += 1
            
            return {
                'total_size': total_size,
                'file_count': file_count,
                'folder_path': self.current_thumbnail_folder
            }
            
        except Exception as e:
            print(f"썸네일 디스크 사용량 계산 중 오류: {e}")
            return {'total_size': 0, 'file_count': 0, 'folder_path': self.current_thumbnail_folder}
