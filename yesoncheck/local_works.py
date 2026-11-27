"""이 PC만의 작품 목록 — 사내 공유 설정(NAS)을 찾지 못한 PC(회사 밖)에서 작품 → 폴더를 그 PC에 등록해 작품 고르기를 씀 (Qt 없음).

왜 (사용자 2026-11-27): 작품 경로 관리는 NAS의 공유 파일(work_paths.json)을 고치는 사내 기능이라 회사 밖 PC에서는 "공유 설정에
문제가 있어 작품 경로를 관리할 수 없습니다" 창만 떴음 → "이 기능을 외부 컴에서도 사용할 수 있게" + "작품 폴더/시즌/job/영상 구조로만
구성되게 하면 안 돼. 이건 회사마다 상황이 다를 수 있어서".

- 저장: 이 PC의 prefs.json(`hover_strip.prefs_path` — Mac ~/Library/Application Support, Windows %LOCALAPPDATA%)의 `local_works`
  = [{"name", "folder", "levels"}] (등록한 차례). NAS·다른 PC와 무관. 더하기·고치기·빼기는 잠금 안에서 다시 읽고 고침
  (창마다 프로세스 — 다른 창이 그사이 더한 작품을 덮어 지우지 않음). 모양이 틀린 목록·깨진 파일은 빈 목록으로 치지 않고
  UserFileError (다음 저장이 덮어 지우지 않게).
- 폴더는 이 PC의 경로 그대로 적음 (사내 목록처럼 Mac 경로로 바꾸지 않음 — Windows의 로컬 디스크 폴더도 됨).
- 구조: 사내 작품은 작품 이름마다 폴더 규칙이 코드에 있지만(시즌 폴더의 이름 모양, job 안에서 영상을 찾는 자리), 여기서는 작품마다
  **단계 수 `levels`** 하나만 — 작품을 고른 뒤 폴더를 몇 번 더 고르는지: 0 = 작품을 고르면 바로, 1 = 작품 → 폴더, 2 = 작품 → 폴더 →
  폴더(사내와 같은 모양). 마지막으로 고른 폴더(`picked_folder`) 아래의 영상은 '폴더 열기'와 같은 규칙으로(하위 폴더까지 —
  video_list.scan_folder) 찾으므로 그 아래의 구조는 가리지 않음. 고를 폴더는 숨김이 아닌 하위 폴더 전부(`subfolders`).

쓰는 곳: `sidebar_local_works.SidebarLocalWorksMixin` (작품 고르기·이 PC의 작품 창).
"""

import ntpath
import os
from dataclasses import asdict, dataclass

from yesoncheck import hover_strip, mac_prefs, ui_text
from yesoncheck.file_names import natural_key
from yesoncheck.user_files import UserFileError

PREF_KEY = "local_works"
LEVELS = (0, 1, 2)
DEFAULT_LEVELS = 1  # 작품 추가 창에서 처음 골라져 있는 단계 (작품 → 폴더)
SKIPPED_FOLDERS = ("@eaDir",)  # 고를 폴더에서 빼는 이름: NAS(Synology)가 폴더마다 만드는 색인 폴더 ('.'으로 시작하는 것도 뺌)
# 작품 콤보의 안내 항목(0번)의 글 — 어느 언어의 것이든 작품 이름으로 받지 않음: 작품은 콤보의 글로 찾으므로, 같은 이름의 작품이 있으면
# 아무것도 고르지 않은 0번이 그 작품으로 보임 (언어를 바꾼 뒤에도 — 그래서 모든 언어의 글)
_PLACEHOLDER_KEYS = ("picker.work", "picker.loading")


@dataclass(frozen=True)
class LocalWork:
    """이 PC에 등록한 작품: 이름, 이 PC의 폴더, 폴더를 몇 번 더 고르는지."""

    name: str
    folder: str
    levels: int


def check(work):
    """등록할 수 있는 작품인지 — 아니면 ValueError (무엇이 왜인지)."""
    if not isinstance(work.name, str) or not work.name.strip():
        raise ValueError("작품 이름이 비어 있습니다.")
    if work.name in reserved_names():
        raise ValueError(f"쓸 수 없는 이름입니다 (작품 고르기의 안내 글과 같음): {work.name}")
    if not isinstance(work.folder, str) or not is_full_path(work.folder):
        raise ValueError(f"작품 폴더는 처음부터 적은 경로여야 합니다: {work.folder!r}")
    _check_levels(work.levels)


def reserved_names():
    """작품 이름으로 쓸 수 없는 글 — 작품 콤보의 안내 항목의 글(모든 언어)."""
    return {text for key in _PLACEHOLDER_KEYS for text in ui_text.TEXTS[key].values()}


def is_full_path(folder, pathmod=None):
    """folder가 어디서 켜든 같은 곳을 가리키는 경로인지: 처음부터 적은 경로이고, Windows는 드라이브(또는 \\\\서버\\공유)부터
    (ntpath.isabs는 드라이브 없이 뿌리부터 적은 '\\foo'도 받음 — 지금 드라이브에 따라 달라지는 경로). pathmod: 시험용(기본 os.path)."""
    pathmod = pathmod or os.path
    if not pathmod.isabs(folder):
        return False
    return pathmod is not ntpath or bool(ntpath.splitdrive(folder)[0])


def _check_levels(levels):
    if isinstance(levels, bool) or levels not in LEVELS:
        raise ValueError(f"단계 수는 {LEVELS} 중 하나여야 합니다: {levels!r}")


def level_text(levels):
    """단계 수를 화면의 글로 (지금 화면 언어 — ui_text의 local_works.level.N)."""
    _check_levels(levels)
    return ui_text.text(f"local_works.level.{levels}")


def _works_of(prefs, path):
    """prefs(dict)의 작품 목록. 모양이 틀리면 UserFileError (빈 목록으로 치지 않음)."""
    stored = prefs.get(PREF_KEY, [])
    try:
        if not isinstance(stored, list):
            raise ValueError(f"목록이 아님 ({type(stored).__name__})")
        works = []
        for entry in stored:
            if not isinstance(entry, dict) or set(entry) != {"name", "folder", "levels"}:
                raise ValueError(f"항목이 {{name, folder, levels}}가 아님: {entry!r}")
            work = LocalWork(entry["name"], entry["folder"], entry["levels"])
            check(work)
            if any(known.name == work.name for known in works):  # (손으로 고친 파일) 이름으로 찾아 고치므로 둘이면 한쪽만 고쳐짐
                raise ValueError(f"같은 이름의 작품이 둘: {work.name}")
            works.append(work)
    except ValueError as exc:
        raise UserFileError(f"설정 파일의 {PREF_KEY}(이 PC의 작품 목록)를 읽을 수 없습니다: {path}\n{exc}") from exc
    return works


def _store(prefs, works):
    prefs[PREF_KEY] = [asdict(work) for work in works]


def read(path=None):
    """이 PC에 등록한 작품들 (등록한 차례, 없으면 []). 깨진 파일·모양이 틀린 목록은 UserFileError."""
    path = path or hover_strip.prefs_path()
    return _works_of(mac_prefs.read_prefs(path), path)


def add(work, path=None):
    """work를 목록 끝에 더함 → 새 목록. 등록할 수 없는 작품·이미 있는 이름은 ValueError (파일은 그대로)."""
    check(work)
    path = path or hover_strip.prefs_path()

    def edit(prefs):
        works = _works_of(prefs, path)
        if any(known.name == work.name for known in works):
            raise ValueError(f"이미 있는 작품 이름입니다: {work.name}")
        _store(prefs, [*works, work])

    return _works_of(mac_prefs.edit_prefs(edit, path), path)


def change(name, path=None, *, folder=None, levels=None):
    """name 작품의 폴더·단계 수를 바꿈(준 것만, 자리는 그대로) → 새 목록. 없는 이름은 LookupError, 틀린 값은 ValueError."""
    path = path or hover_strip.prefs_path()

    def edit(prefs):
        works = _works_of(prefs, path)
        for index, known in enumerate(works):
            if known.name == name:
                changed = LocalWork(name, known.folder if folder is None else folder, known.levels if levels is None else levels)
                check(changed)
                works[index] = changed
                _store(prefs, works)
                return
        raise LookupError(f"이 PC의 작품 목록에 없는 작품입니다: {name}")

    return _works_of(mac_prefs.edit_prefs(edit, path), path)


def remove(name, path=None):
    """name 작품을 목록에서 뺌 → 새 목록 (없으면 그대로). 폴더·영상은 건드리지 않음."""
    path = path or hover_strip.prefs_path()

    def edit(prefs):
        _store(prefs, [known for known in _works_of(prefs, path) if known.name != name])

    return _works_of(mac_prefs.edit_prefs(edit, path), path)


def subfolders(folder):
    """folder 바로 아래에서 고를 폴더 이름들 — 숨김('.'으로 시작)·SKIPPED_FOLDERS가 아닌 폴더, 번호 순서. 읽지 못하면 OSError."""
    with os.scandir(folder) as entries:
        names = [entry.name for entry in entries
                 if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIPPED_FOLDERS]
    return sorted(names, key=lambda name: (natural_key(name), name))


def picked_folder(work, picked):
    """work에서 폴더를 picked(이름들, 고른 차례)로 고른 끝의 폴더 — 그 아래의 영상을 목록에 넣음. 고른 수가 단계 수와 다르면 ValueError."""
    if len(picked) != work.levels:
        raise ValueError(f"'{work.name}'은(는) 폴더를 {work.levels}번 골라야 합니다 (고른 것: {list(picked)})")
    return os.path.join(work.folder, *picked)
