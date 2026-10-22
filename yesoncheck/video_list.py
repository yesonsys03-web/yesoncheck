"""사이드바 영상 목록을 디스크에서 읽는 규칙 (Qt 없음).

처음 불러올 때(job 고르기·폴더 불러오기·끌어다 놓기)와 목록 다시 읽기(새로고침·F5·창이 다시 활성 등)가 같은 함수를
써서 규칙이 어긋나지 않게 한다. 목록에 넣은 곳(ListSource)마다 다시 읽어, 디스크에 없는 영상은 빼고 새 영상은
정렬 순서 자리에 넣는 계획(plan_refresh)도 여기서 세운다 — 사이드바에 적용하는 일은 sidebar_refresh(SidebarRefreshMixin).

오류(OSError)는 삼키지 않는다: 목록을 넣은 폴더 자체를 읽지 못하면 예외를 올리고, 그 안의 하위 폴더를 읽지 못하면
결과의 unreadable에 남긴다 (그 아래 영상은 알 수 없음 → 다시 읽기는 그 영상들을 그대로 둠). 부른 쪽이 창·로그로 알린다.
"""

import locale
import os
import re
import traceback
import unicodedata
from dataclasses import dataclass, field

from yesoncheck import file_names, paths

# 폴더 불러오기·끌어다 놓기로 목록에 넣는 영상 (job 목록은 file_names.is_listed_video: .mov·.mp4만)
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.mts', '.m2ts'}

FOLDER_GONE = "folder_gone"  # plan_refresh 결과 값: 목록을 넣은 폴더가 없어짐 (지워졌거나 이름이 바뀜) → 그 영상을 뺌
# Mac: 공유·디스크를 붙이는 폴더. 떼면 /Volumes/x가 없어지거나 빈 폴더로 남으므로 이 폴더와 그 바로 아래(붙어 있지
# 않은 것)는 공유 안이 아님 (is_gone)
MAC_MOUNT_PARENT = "/Volumes"
# Mac: 공유를 붙이는 곳의 위(/, autofs 마운트들이 있는 Data 볼륨) — 여기까지 올라가면 공유가 떨어졌을 수 있음 (is_gone).
# 이 Mac의 자동 연결 맵 폴더(paths.mac_mount_map_dirs)도 같음
MAC_LOCAL_ROOTS = ("/", "/System/Volumes/Data")
_sort_locale_set = False  # set_sort_locale을 이 프로세스에서 이미 불렀는지


@dataclass(frozen=True)
class ListSource:
    """사이드바 영상이 들어온 곳. kind: "job"(작품 job 폴더 — work의 규칙) 또는 "folder"(폴더 불러오기·끌어다 놓기·북마크
    — 하위 폴더까지). 따로 끌어다 놓은 파일은 출처 없음(None): 파일이 있는 동안만 목록에 둠."""

    kind: str
    folder: str
    work: str = None


@dataclass
class ScanResult:
    videos: list  # [(표시 이름, 경로)] 목록 순서
    unreadable: list = field(default_factory=list)  # [(폴더, OSError)] 읽지 못한 하위 폴더 — 그 아래 영상은 알 수 없음

    def keeps(self, path):
        """다시 읽은 목록에 path를 남길지: 읽은 영상이거나 읽지 못한 폴더 아래에 있음 (Windows는 대소문자·구분자 무시)."""
        key = paths.path_key(path)
        if not hasattr(self, "_keys"):
            self._keys = {paths.path_key(p) for _name, p in self.videos}
        return key in self._keys or any(_is_under(key, paths.path_key(folder)) for folder, _error in self.unreadable)


def _is_under(key, folder_key):
    """key(path_key)가 folder_key 폴더이거나 그 아래인지."""
    folder_key = folder_key.rstrip("/\\")
    return key == folder_key or (key.startswith(folder_key) and key[len(folder_key):len(folder_key) + 1] in ("/", "\\"))


def is_under(path, folder):
    """path가 folder이거나 그 아래인지 (Windows는 대소문자·구분자·드라이브 문자/UNC 차이 무시)."""
    return _is_under(paths.path_key(path), paths.path_key(folder))


def scan_source(source):
    """목록을 넣은 곳을 처음 불러올 때와 같은 규칙으로 읽음 → ScanResult. 그 폴더를 읽지 못하면 OSError."""
    if source.kind == "job":
        return scan_job(source.work, source.folder)
    if source.kind == "folder":
        return scan_folder(source.folder)
    raise ValueError(f"모르는 목록 출처: {source!r}")


def _is_dir(entry, unreadable):
    try:
        return entry.is_dir()
    except OSError as e:  # 종류를 확인하지 못함 (그 아래 영상은 알 수 없음)
        unreadable.append((entry.path, e))
        return False


def _is_file(entry, unreadable):
    try:
        return entry.is_file()
    except OSError as e:
        unreadable.append((entry.path, e))
        return False


def _videos_in(folder, unreadable, files_only=False):
    """folder 바로 안의 job 목록 영상 [(이름, 경로)]. 그 폴더가 없으면(예: frames가 없는 scene 폴더) 빈 목록,
    읽지 못하면 unreadable에 남기고 빈 목록. files_only: 영상 이름인 폴더는 뺌 (TJS_Animatic의 예전 규칙).

    없다고 나오면 방금 목록에 있던 위 폴더(scene 폴더)를 확인: 그것도 확인되지 않으면 'frames 없음'이 아니라 그 위 폴더를
    읽지 못한 것 (Windows는 SMB가 잠깐 끊겨도 FileNotFoundError — 그 아래 영상을 빼지 않게).
    """
    try:
        with os.scandir(folder) as entries:
            return [(entry.name, entry.path) for entry in entries
                    if file_names.is_listed_video(entry.name) and (not files_only or _is_file(entry, unreadable))]
    except (FileNotFoundError, NotADirectoryError):
        parent = os.path.dirname(folder)
        try:
            os.stat(parent)
        except OSError as e:
            unreadable.append((parent, e))
        return []
    except OSError as e:
        unreadable.append((folder, e))
        return []


def scan_job(work, base_path):
    """작품 job 폴더의 영상 → ScanResult (목록 순서: sort_job_videos). update_playlist에서 옮긴 작품별 규칙:

    - MS_Animatic: job 폴더 바로 안
    - TJS_Animatic: job 폴더 바로 안 + 숨김이 아닌 하위 폴더 한 단계 (파일만)
    - 나머지: job 폴더 바로 안 + 하위 폴더마다 정한 폴더 안 — 기본은 Harmony scene 구조(scene-*/frames, 작품 경로
      관리에서 새로 등록한 작품도), BB_Animatic */Quicktime, TGN_Animatic */ANIMATIC. 그리고 BM_Animatic은 ANIMATIC
      폴더, KOTH_Animatic은 이름에 ANIMATIC이 든 폴더 (시즌 15까지 'POST-LOCK ANIMATIC', 시즌 16부터
      '1601_ANIMATIC'·'1604_ANIMATICS').

    job 폴더를 읽지 못하면 OSError. 하위 폴더를 읽지 못하면 결과의 unreadable에.
    """
    unreadable = []
    with os.scandir(base_path) as it:
        entries = list(it)
    if work == "MS_Animatic":
        videos = [(e.name, e.path) for e in entries if file_names.is_listed_video(e.name)]
    elif work == "TJS_Animatic":
        videos = [(e.name, e.path) for e in entries if file_names.is_listed_video(e.name) and _is_file(e, unreadable)]
        for entry in entries:
            if not entry.name.startswith('.') and _is_dir(entry, unreadable):
                videos += _videos_in(entry.path, unreadable, files_only=True)
    else:
        videos = [(e.name, e.path) for e in entries if file_names.is_listed_video(e.name)]
        for entry in entries:
            if work == "BB_Animatic":
                sub = "Quicktime"
            elif work == "TGN_Animatic":
                sub = "ANIMATIC"
            elif work in ("BM_Animatic", "KOTH_Animatic"):
                sub = None  # 아래 정한 폴더만
            else:
                sub = "frames"
            if sub and _is_dir(entry, unreadable):
                videos += _videos_in(os.path.join(entry.path, sub), unreadable)
        if work == "BM_Animatic":
            videos += _videos_in(os.path.join(base_path, "ANIMATIC"), unreadable)
        if work == "KOTH_Animatic":
            for entry in entries:
                if 'ANIMATIC' in entry.name.upper() and _is_dir(entry, unreadable):
                    videos += _videos_in(entry.path, unreadable)
    # 하위 폴더를 읽는 사이 공유가 끊겼으면(Windows는 끊긴 SMB도 FileNotFoundError) 하위 폴더가 '없음'으로 보였을 수
    # 있음 → job 폴더를 한 번 더 확인 (확인하지 못하면 OSError: 이 결과는 쓰지 않음)
    os.stat(base_path)
    return ScanResult(sort_job_videos(videos), unreadable)


def set_sort_locale():
    """job 목록 정렬에 쓰는 locale(이름 순서: LC_COLLATE)을 en_US.UTF-8로 — 앱을 시작할 때 GUI 스레드에서 한 번 (창을 만들 때).
    setlocale은 프로세스 전체를 바꾸므로 목록 다시 읽기 스레드의 정렬(sort_job_videos)에서는 부르지 않음.
    쓸 수 없으면 시스템 locale로, 그것도 안 되면 지금 locale로 (이유는 로그에)."""
    global _sort_locale_set
    if _sort_locale_set:
        return
    _sort_locale_set = True
    try:
        locale.setlocale(locale.LC_COLLATE, 'en_US.UTF-8')
    except locale.Error as e:
        print(f"정렬 locale en_US.UTF-8을 쓰지 못해 시스템 locale로: {e}")
        try:
            locale.setlocale(locale.LC_COLLATE, '')
        except locale.Error as e2:
            print(f"시스템 locale도 쓰지 못해 지금 locale로 정렬: {e2}")


def sort_job_videos(videos):
    """job 목록 순서: HD가 아닌 영상 먼저, 그다음 HD('_HD'가 든 이름) — 각각 이름의 locale 순서 (set_sort_locale)."""
    hd_files = [v for v in videos if '_HD' in v[0]]
    non_hd_files = [v for v in videos if '_HD' not in v[0]]
    try:
        hd_files.sort(key=lambda v: locale.strxfrm(v[0]))
        non_hd_files.sort(key=lambda v: locale.strxfrm(v[0]))
    except Exception as e:  # 예전처럼 정렬은 계속 (이름의 소문자 순서) — 이유는 스택 트레이스째 로그에
        print(f"locale 정렬 실패 → 소문자 이름 순서: {type(e).__name__}: {e}")
        traceback.print_exc()
        hd_files.sort(key=lambda v: v[0].lower())
        non_hd_files.sort(key=lambda v: v[0].lower())
    return non_hd_files + hd_files


def natural_key(file_path):
    """번호 순서 정렬 키: 파일 이름의 숫자는 숫자로 (clip2 < clip10), 나머지는 소문자로."""
    filename = os.path.basename(file_path)
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', filename)]


def scan_folder(folder):
    """폴더 불러오기·끌어다 놓기·북마크 규칙: 하위 폴더까지 VIDEO_EXTENSIONS 영상 ('.'으로 시작하는 파일 제외), 번호 순서
    (이름이 같으면 경로 순) → ScanResult. 폴더를 읽지 못하면 OSError, 하위 폴더를 읽지 못하거나 항목이 폴더인지
    확인하지 못하면 결과의 unreadable에 (그 아래 영상은 알 수 없음 — 예전 os.walk는 '폴더 아님'으로 넘겼음).
    읽을 수 있는 폴더에서는 예전 os.walk와 같은 영상: 폴더 링크는 따라 들어가지 않고, 깨진 링크도 이름으로 판단.
    """
    unreadable = []
    videos = []
    pending = [folder]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as e:
            if current == folder:
                raise
            unreadable.append((current, e))
            continue
        for entry in entries:
            if _is_dir(entry, unreadable):
                if not os.path.islink(entry.path):
                    pending.append(entry.path)
            elif not entry.name.startswith('.') and os.path.splitext(entry.name.lower())[1] in VIDEO_EXTENSIONS:
                videos.append((entry.name, entry.path))
    # 하위 폴더를 읽는 사이 공유가 끊겼으면 결과를 쓰지 않음 (scan_job과 같음)
    os.stat(folder)
    videos.sort(key=lambda v: (natural_key(v[1]), v[1]))
    return ScanResult(videos, unreadable)


def is_gone(path, error):
    """path를 읽다 난 error가 '없어짐'(지워졌거나 이름이 바뀜)인지 (check_gone의 판단만)."""
    return check_gone(path, error)[0]


def check_gone(path, error):
    """path를 읽다 난 error가 '없어짐'(지워졌거나 이름이 바뀜)인지 → (없어짐, 아니면 그 까닭 — 로그·창에 덧붙임).

    없어짐으로 보는 것은 확인되는 증거가 있을 때만 (끊긴 공유의 영상을 목록에서 빼지 않게):
    FileNotFoundError이고, 위로 올라가며 처음 확인되는(os.stat) 폴더가 공유 안이고(_inside_share), 그 폴더를 읽을 수 있고
    비어 있지 않으며(공유를 떼고 남은 빈 마운트 폴더가 아님), 그 폴더 목록에 path로 가는 다음 이름이 없고(목록에 보이는데
    열리지 않으면 자동 연결(autofs) 폴더의 서버가 꺼졌거나 공유가 떨어진 것), path를 다시 확인해도 없음(Windows SMB가
    그사이 다시 연결됨). Windows는 끊긴 SMB 공유도 FileNotFoundError로 올리고, 위로 올라가도 \\\\서버\\공유·드라이브
    맨 위가 확인되지 않으면 '확인하지 못함'.
    """
    if not isinstance(error, FileNotFoundError):
        return False, ""
    folder, child, problem = _nearest_existing_folder(path)
    if folder is None:
        return False, problem
    inside, problem = _inside_share(folder)
    if not inside:
        return False, problem
    try:
        names = os.listdir(folder)
    except OSError as e:
        return False, f"처음 확인되는 위 폴더를 읽지 못함: {folder} ({type(e).__name__}: {e})"
    if not names:
        return False, f"처음 확인되는 위 폴더가 비어 있음 (공유를 떼고 남은 폴더일 수 있음): {folder}"
    if _name_key(child) in {_name_key(name) for name in names}:
        return False, (f"위 폴더 {folder}의 목록에는 {child}가 있는데 열리지 않음 "
                       "(공유가 떨어졌거나 자동 연결 폴더의 서버가 응답하지 않을 수 있음)")
    try:
        os.stat(path)
    except FileNotFoundError:
        return True, ""
    except OSError as e:
        return False, f"다시 확인하지 못함: {path} ({type(e).__name__}: {e})"
    return False, f"다시 확인하니 있음 (공유가 다시 연결됨): {path}"


def _name_key(name):
    """폴더 목록의 이름 비교: 대소문자·한글 정규화(Mac SMB는 NFD) 차이는 같은 이름으로 (판단을 '확인하지 못함' 쪽으로)."""
    return unicodedata.normalize("NFC", name).casefold()


def _nearest_existing_folder(path):
    """path 위로 올라가며 처음 확인되는(os.stat이 되는) 폴더 → (폴더, 그 폴더에서 path로 가는 다음 이름, 까닭).
    맨 위(/, \\\\서버\\공유, 드라이브)까지 없거나 확인하다 다른 오류가 나면 (None, None, 그 까닭)."""
    current = os.path.normpath(path)
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            return None, None, f"맨 위({current})까지 확인되는 폴더가 없음 (공유가 끊겼을 수 있음)"
        child = os.path.basename(current)
        current = parent
        try:
            os.stat(current)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as e:
            return None, None, f"위 폴더를 확인하지 못함: {current} ({type(e).__name__}: {e})"
        return current, child, ""


def _is_mount_root(folder):
    """folder가 붙인 공유·디스크(autofs 트리거 포함)의 맨 위 폴더인지: 위 폴더와 장치가 다름 (/usadata2 같은 링크는 따라감).
    확인하지 못하면 OSError."""
    real = os.path.realpath(folder)
    parent = os.path.dirname(real)
    return real != parent and os.stat(real).st_dev != os.stat(parent).st_dev


def _inside_share(folder):
    """확인된 폴더 folder가 공유(마운트) 안인지 → (안인지, 아니면 그 까닭). Windows는 위로 올라가도 \\\\서버\\공유·드라이브
    맨 위에서 멈추므로 확인되면 공유 안. Mac은 / · Data 볼륨(autofs 마운트들의 위) · /Volumes · 이 Mac의 자동 연결(autofs)
    맵 폴더(예: mac_b의 /System/Volumes/Data/mnt — paths.mac_mount_map_dirs)와, /Volumes 바로 아래의 붙어 있지 않은
    폴더(떼고 남은 것)가 아니어야 함 — 장치 번호를 보기 전에 (예전 macOS는 /Volumes의 장치가 /와 달라 붙인 공유의 맨 위처럼
    보임)."""
    if paths.IS_WINDOWS:
        return True, ""
    real = os.path.realpath(folder)
    if real in MAC_LOCAL_ROOTS or real == MAC_MOUNT_PARENT:
        return False, f"공유를 붙이는 곳까지 올라감 (공유가 떨어졌을 수 있음): {real}"
    if real in paths.mac_mount_map_dirs():
        # 맵 폴더의 목록은 붙은 공유만 보일 수 있음(-nobrowse) → 공유 이름이 목록에 없어도 지워진 것이 아님
        return False, f"자동 연결(autofs) 맵 폴더까지 올라감 (공유가 붙지 않았거나 서버가 응답하지 않을 수 있음): {real}"
    if os.path.dirname(real) == MAC_MOUNT_PARENT:
        try:
            mounted = _is_mount_root(real)
        except OSError as e:
            return False, f"공유가 붙어 있는지 확인하지 못함: {real} ({type(e).__name__}: {e})"
        if not mounted:
            return False, f"{MAC_MOUNT_PARENT} 아래의 붙어 있지 않은 폴더 (공유를 떼고 남은 것): {real}"
    return True, ""


@dataclass
class SourcesRead:
    """목록 다시 읽기의 디스크 읽기 결과 (read_sources). GUI 스레드가 plan_refresh로 목록을 맞추고 문제를 알림."""

    results: dict  # 출처 → ScanResult | FOLDER_GONE(없어짐) | None(읽지 못함)
    errors: dict  # 출처 → 읽지 못했거나 없어진 출처의 OSError
    notes: dict  # 출처 → 없어진 것으로 보지 않은 까닭 (check_gone — 창에 덧붙임, 없으면 "")
    gone_files: set  # 없어진 따로 넣은 파일의 path_key
    unverified: list  # [(경로, OSError, 까닭)] 있는지 확인하지 못한 따로 넣은 파일


def read_sources(sources, files):
    """목록에 영상을 넣은 곳(sources)을 처음과 같은 규칙으로 다시 읽고 따로 넣은 파일(files)이 있는지 확인 → SourcesRead.
    파일·NAS만 읽음 (Qt 없음) → GUI 밖 스레드에서 실행 (Windows SMB·느린 NAS에서 창이 멈추지 않게)."""
    results = {}
    errors = {}
    notes = {}
    for source in sources:
        try:
            results[source] = scan_source(source)
        except OSError as e:
            gone, note = check_gone(source.folder, e)
            errors[source] = e
            notes[source] = note
            results[source] = FOLDER_GONE if gone else None
    gone_files = set()
    unverified = []
    for path in files:
        try:
            os.stat(path)
        except OSError as e:
            gone, note = check_gone(path, e)
            if gone:
                gone_files.add(paths.path_key(path))
            else:
                unverified.append((path, e, note))
    return SourcesRead(results, errors, notes, gone_files, unverified)


def plan_refresh(rows, results, gone_files):
    """다시 읽은 결과로 목록을 맞추는 계획 → (뺄 줄 번호 목록, 새 목록).

    rows: 지금 목록 [(경로, 출처)] (출처 None: 따로 끌어다 놓은 파일). results: {출처: ScanResult | None(읽지 못함 →
    그 출처의 영상은 그대로) | FOLDER_GONE(그 출처의 영상을 뺌)} — 없는 출처의 영상도 그대로.
    gone_files: 없어진 따로 넣은 파일의 path_key.
    새 목록: 남는 줄 번호(int) 또는 새 항목 (출처, 이름, 경로). 새 항목은 그 출처를 다시 읽은 순서에서 바로 뒤에 오는
    남는 영상 앞에, 없으면 그 출처의 마지막 남는 영상 뒤에, 그 출처에 남는 영상이 없으면 맨 뒤에 — 출처가 하나인
    목록(job·폴더)이면 처음 불러온 목록과 같은 순서.
    """
    removed = []
    for row, (path, source) in enumerate(rows):
        if source is None:
            if paths.path_key(path) in gone_files:
                removed.append(row)
            continue
        result = results.get(source)
        if result is FOLDER_GONE or (isinstance(result, ScanResult) and not result.keeps(path)):
            removed.append(row)
    removed_rows = set(removed)
    kept = [row for row in range(len(rows)) if row not in removed_rows]
    before = {}  # 남는 줄 → 그 앞에 넣을 새 항목
    after = {}  # 출처의 마지막 남는 줄 → 그 뒤에 넣을 새 항목
    tail = []  # 남는 영상이 없는 출처의 새 항목
    for source, result in results.items():
        if not isinstance(result, ScanResult):
            continue
        first_row = {}  # path_key → 이 출처에서 그 영상의 첫 남는 줄
        last_row = None
        for row in kept:
            path, row_source = rows[row]
            if row_source == source:
                first_row.setdefault(paths.path_key(path), row)
                last_row = row
        waiting = []
        for name, path in result.videos:
            row = first_row.get(paths.path_key(path))
            if row is None:
                waiting.append((source, name, path))
            elif waiting:
                before.setdefault(row, []).extend(waiting)
                waiting = []
        if waiting:
            if last_row is None:
                tail.extend(waiting)
            else:
                after.setdefault(last_row, []).extend(waiting)
    final = []
    for row in kept:
        final.extend(before.get(row, ()))
        final.append(row)
        final.extend(after.get(row, ()))
    final.extend(tail)
    return removed, final


def plan_changes(plan):
    """계획이 목록을 바꾸는지 (뺄 줄이나 새 항목이 있음)."""
    removed, final = plan
    return bool(removed) or any(not isinstance(entry, int) for entry in final)
