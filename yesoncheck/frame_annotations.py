"""Frame annotation data model and persistence.

주석 파일은 NAS의 모든 창(Mac·Windows PC)이 함께 쓴다. 창마다 자기 메모리 전체를 덮어쓰면 다른 창이 넣은 항목이 지워지므로,
저장할 때 디스크를 다시 읽어 항목 id로 합친다 (merge_annotations). 지운 항목은 파일의 deleted_ids에 id를 남겨(묘비)
낡은 창이 되살리지 못하게 한다. NAS에서는 파일 잠금을 믿을 수 없어 쓰는 쪽은 원자적 쓰기(user_files)만 쓴다 —
반쪽짜리 파일은 생기지 않지만, 한 창이 읽고 쓰는 그 짧은 사이에 다른 창이 쓰면 그 변경은 덮일 수 있다 (잠금 없이 감수).
"""

import copy
import hashlib
import json
import math
import os
import stat
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from yesoncheck import paths, user_files
from yesoncheck.sequence_scan import is_sequence_path


ANNOTATION_TYPES = ("text", "rect", "ellipse", "line", "arrow")
DEFAULT_COLOR = "#ff3333"
DEFAULT_FONT_SIZE = 28
DEFAULT_STROKE_WIDTH = 3
MIN_FONT_SIZE = 12
MAX_FONT_SIZE = 120
MIN_STROKE_WIDTH = 1
MAX_STROKE_WIDTH = 30


def new_annotation_id() -> str:
    return uuid.uuid4().hex[:12]


def get_item_frame_range(item: Dict[str, Any], anchor_frame: int):
    """Return inclusive 0-based (start, end) for an annotation item."""
    start = item.get("start_frame")
    end = item.get("end_frame")
    if start is None:
        start = anchor_frame
    if end is None:
        end = start
    start = int(start)
    end = int(end)
    if start > end:
        start, end = end, start
    return start, end


def item_visible_on_frame(item: Dict[str, Any], frame_idx: int, anchor_frame: int) -> bool:
    start, end = get_item_frame_range(item, anchor_frame)
    return start <= frame_idx <= end


def normalize_item_frame_range(item: Dict[str, Any], anchor_frame: int) -> Dict[str, Any]:
    """Ensure start_frame/end_frame exist on an item (for load/migration)."""
    updated = dict(item)
    start, end = get_item_frame_range(updated, anchor_frame)
    updated["start_frame"] = start
    updated["end_frame"] = end
    return updated


def annotation_file_path(video_path: str) -> str:
    """Sidecar JSON path next to the video file.

    이미지 시퀀스는 가상 경로(`<폴더>/<base>.seq`)가 영상 경로 자리에 오고 `<base>_seq_annotations.json`에 저장된다 — 이름이
    시작 번호·실제 확장자와 무관해 재렌더(0001→0101, tga→png)에도 같은 파일을 읽고, 같은 이름의 mov 주석 파일과도 겹치지 않는다.
    """
    base = os.path.splitext(os.path.basename(video_path))[0]
    folder = os.path.join(os.path.dirname(video_path), ".yesoncheck")
    suffix = "_seq_annotations.json" if is_sequence_path(video_path) else "_annotations.json"
    return os.path.join(folder, f"{base}{suffix}")


# 시퀀스를 굽기 내보내기하면 나오는 영상 (시퀀스에는 영상 확장자가 없어 정함)
SEQUENCE_EXPORT_EXT = ".mov"


def annotation_export_suggested_name(video_path: str) -> str:
    base, ext = os.path.splitext(os.path.basename(video_path))
    if is_sequence_path(video_path):
        ext = SEQUENCE_EXPORT_EXT  # 가상 경로의 '.seq'가 아니라 영상 파일로
    return f"{base}_annotated{ext or '.mp4'}"


def annotation_export_default_path(video_path: str) -> str:
    """Default burned-in export path beside the source video."""
    base, ext = os.path.splitext(video_path)
    if is_sequence_path(video_path):
        ext = SEQUENCE_EXPORT_EXT
    return f"{base}_annotated{ext or '.mp4'}"


def annotation_storage_dir(video_path: str) -> str:
    return os.path.join(os.path.dirname(video_path), ".yesoncheck")


# 항목 id → (앵커 프레임, 항목)
Entries = Dict[str, Tuple[int, Dict[str, Any]]]

_chmod = os.chmod  # 테스트가 바꿔 끼울 수 있게 모듈 값으로 둠
_MISSING = object()  # 파일이 없음 (JSON null과 구분)

# 이번 실행에서 내가 만든 주석 폴더 → 권한을 바꾸지 못한 이유
_share_problems: Dict[str, str] = {}


class AnnotationFileError(Exception):
    """주석 파일을 읽지 못함 (없는 것은 오류가 아님) — 경로(path)와 원인(cause)."""

    def __init__(self, path: str, cause: str):
        self.path = path
        self.cause = cause
        super().__init__(f"주석 파일을 읽지 못했습니다: {path}\n{cause}")


def merge_annotations(
    disk: Entries,
    disk_deleted: Set[str],
    base: Entries,
    local: Entries,
) -> Tuple[Entries, Set[str]]:
    """디스크의 주석과 이 창의 주석을 항목 id로 합침 (순수 함수). 돌려주는 값: (합친 항목, 지운 id 전체).

    disk: 저장하려고 지금 다시 읽은 파일의 항목, disk_deleted: 그 파일의 deleted_ids,
    base: 이 창이 마지막으로 디스크와 맞춘(읽거나 저장한) 모습, local: 이 창의 지금 모습.
    이 창이 바꾼 것(base와 다른 항목)과 지운 것(base에 있었는데 없는 항목)만 디스크에 반영하고 나머지는 디스크 그대로 —
    그래서 낡은 창이 저장해도 다른 창의 고침을 되돌리지 않는다. 지운 것이 이긴다: 다른 창이 지운 항목을 이 창이 고쳤어도 지운 채로.
    """
    changed = {id_: v for id_, v in local.items() if base.get(id_) != v}
    removed = set(base) - set(local)
    deleted = disk_deleted | removed
    result = {id_: v for id_, v in disk.items() if id_ not in deleted}
    result.update({id_: v for id_, v in changed.items() if id_ not in deleted})  # 지운 것이 이김
    return result, deleted


def annotation_share_problem(folder: str) -> Optional[str]:
    """이번 실행에서 내가 만든 주석 폴더 folder의 권한을 바꾸지 못했으면 그 이유, 아니면 None."""
    return _share_problems.get(folder)


def _make_annotation_folder(folder: str) -> None:
    """주석 폴더를 (없으면) 만든다. 내가 만들었으면 (Mac) 0o777을 더함: 다른 NAS 계정을 쓰는 Windows PC도 쓸 수 있게
    (원자적 교체는 폴더 쓰기 권한이 필요). 이미 있던 폴더는 건드리지 않는다 — thumbnails.share_folder와 같은 규칙.

    폴더를 만들지 못하면 OSError. 권한을 바꾸지 못한 것은 이 PC가 폴더를 쓰는 데 지장이 없으므로 예외 없이 로그에 남기고
    annotation_share_problem으로 알린다.
    """
    parent = os.path.dirname(folder)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.mkdir(folder)
    except OSError:
        if not os.path.isdir(folder):
            raise
        return  # 이미 있던 폴더 (이미 있으면 상위 폴더에 만들 권한이 없어도 쓸 수 있음 — 예전 makedirs(exist_ok=True)와 같음)
    if paths.IS_WINDOWS:
        return
    try:
        _chmod(folder, stat.S_IMODE(os.stat(folder).st_mode) | 0o777)
    except OSError as exc:
        problem = f"{type(exc).__name__}: {exc}"
        print(f"주석 폴더의 권한을 바꾸지 못했습니다 (폴더는 그대로 씀): {folder}\n{problem}")
        _share_problems[folder] = problem


def is_annotation_storage_writable(video_path: str) -> bool:
    folder = annotation_storage_dir(video_path)
    try:
        _make_annotation_folder(folder)
        # 창마다·확인마다 다른 이름: 여러 창이 동시에 확인해도 서로의 시험 파일을 지우지 않음
        test_path = os.path.join(folder, f".write_test_{uuid.uuid4().hex}")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(test_path)
        return True
    except OSError:
        return False


def _read_annotation_file(path: str):
    """path의 주석 파일 내용(JSON 값). 없으면 _MISSING, 읽지 못했거나 JSON이 깨졌으면 AnnotationFileError."""
    try:
        return user_files.read_json(path, _MISSING)
    except user_files.UserFileError as exc:
        cause = exc.__cause__
        raise AnnotationFileError(path, f"{type(cause).__name__}: {cause}") from exc


def _derived_id(frame_idx: int, item: Dict[str, Any], seen: Set[str]) -> str:
    """id가 없거나 겹치는 항목의 id: 내용에서 정함. 창마다·읽을 때마다 같은 항목이 같은 id를 받아야 하므로 무작위(new_annotation_id)로
    주지 않는다 (무작위면 저장할 때 디스크를 다시 읽으며 다른 id가 붙어 같은 항목이 두 개로 불어날 수 있음). 내용이 같은 항목은
    나타나는 차례로 구분."""
    text = json.dumps([frame_idx, item], sort_keys=True, ensure_ascii=False, default=str)
    serial = 0
    while True:
        candidate = hashlib.sha1(f"{serial}:{text}".encode("utf-8")).hexdigest()[:12]
        if candidate not in seen:
            return candidate
        serial += 1


def _parse_annotation_data(data: Any, path: str) -> Tuple[Dict[int, List[Dict[str, Any]]], Set[str]]:
    """파일 내용 → ({앵커 프레임: [항목]}, 지운 id 집합). 모양이 맞지 않으면 AnnotationFileError(path, 이유).

    deleted_ids가 없는 옛 파일은 빈 것으로 읽는다. 항목은 프레임 범위를 채우고, id가 없거나 겹치면 새 id를 준다
    (합치기는 id로 하므로 모든 항목에 있어야 함 — 앱은 처음부터 id를 넣어 왔으므로 손으로 만든 파일에서만 생김. _derived_id).
    """
    if not isinstance(data, dict):
        raise AnnotationFileError(path, f"최상위가 객체가 아닙니다 ({type(data).__name__})")
    raw = data.get("annotations") or {}
    if not isinstance(raw, dict):
        raise AnnotationFileError(path, f"annotations가 객체가 아닙니다 ({type(raw).__name__})")
    deleted = data.get("deleted_ids") or []
    if not isinstance(deleted, list) or not all(isinstance(id_, str) for id_ in deleted):
        raise AnnotationFileError(path, "deleted_ids가 문자열 목록이 아닙니다")
    annotations: Dict[int, List[Dict[str, Any]]] = {}
    seen: Set[str] = set()
    for key, items in raw.items():
        try:
            frame_idx = int(key)
        except (TypeError, ValueError) as exc:
            raise AnnotationFileError(path, f"annotations의 프레임 번호가 정수가 아닙니다: {key!r}") from exc
        items = items or []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise AnnotationFileError(path, f"annotations[{key!r}]가 항목(객체)의 목록이 아닙니다")
        parsed = []
        for item in items:
            item = normalize_item_frame_range(item, frame_idx)
            if not item.get("id") or item["id"] in seen:
                item["id"] = _derived_id(frame_idx, item, seen)
            seen.add(item["id"])
            parsed.append(item)
        annotations[frame_idx] = parsed
    return annotations, set(deleted)


def _flatten(annotations: Dict[int, List[Dict[str, Any]]]) -> Entries:
    """{앵커 프레임: [항목]} → {id: (앵커 프레임, 항목)} (항목 객체는 그대로)."""
    flat: Entries = {}
    for anchor_frame, items in annotations.items():
        for item in items:
            flat[item["id"]] = (anchor_frame, item)
    return flat


def _unflatten(entries: Entries) -> Dict[int, List[Dict[str, Any]]]:
    annotations: Dict[int, List[Dict[str, Any]]] = {}
    for anchor_frame, item in entries.values():
        annotations.setdefault(anchor_frame, []).append(item)
    return annotations


class FrameAnnotationStore:
    """In-memory store keyed by 0-based frame index."""

    def __init__(self):
        self.video_path: Optional[str] = None
        self.fps: float = 0.0
        self.annotations: Dict[int, List[Dict[str, Any]]] = {}
        # 마지막으로 디스크와 맞춘(읽거나 저장한) 모습과 그 파일의 deleted_ids — save가 '이 창이 바꾼 것'을 가려내는 기준
        self._base: Entries = {}
        self._deleted_ids: Set[str] = set()

    def clear(self):
        self.video_path = None
        self.fps = 0.0
        self._adopt({}, set())

    def set_video(self, video_path: str, fps: float = 0.0):
        self.video_path = video_path
        self.fps = fps
        self._adopt({}, set())

    def _adopt(self, annotations: Dict[int, List[Dict[str, Any]]], deleted_ids: Set[str]):
        """annotations가 디스크와 같아진 상태 → 메모리로 삼고 base(깊은 복사: 항목은 제자리에서 고쳐짐)를 새로 잡음."""
        self.annotations = annotations
        self._deleted_ids = set(deleted_ids)
        self._base = copy.deepcopy(_flatten(annotations))

    def get_frame(self, frame_idx: int) -> List[Dict[str, Any]]:
        result = []
        for anchor_frame, items in self.annotations.items():
            for item in items:
                if item_visible_on_frame(item, frame_idx, anchor_frame):
                    result.append(item)
        return result

    def find_item_by_id(self, annotation_id: str):
        for anchor_frame, items in self.annotations.items():
            for item in items:
                if item.get("id") == annotation_id:
                    return anchor_frame, item
        return None, None

    def add(
        self,
        frame_idx: int,
        item: Dict[str, Any],
        start_frame: Optional[int] = None,
        end_frame: Optional[int] = None,
    ) -> Dict[str, Any]:
        item = dict(item)
        if "id" not in item:
            item["id"] = new_annotation_id()
        start = frame_idx if start_frame is None else int(start_frame)
        end = frame_idx if end_frame is None else int(end_frame)
        if start > end:
            start, end = end, start
        item["start_frame"] = start
        item["end_frame"] = end
        self.annotations.setdefault(frame_idx, []).append(item)
        return item

    def remove(self, frame_idx: int, annotation_id: str) -> bool:
        return self.remove_by_id(annotation_id)

    def remove_by_id(self, annotation_id: str) -> bool:
        for storage_frame, items in list(self.annotations.items()):
            for idx, item in enumerate(items):
                if item.get("id") == annotation_id:
                    items.pop(idx)
                    if not items:
                        del self.annotations[storage_frame]
                    return True
        return False

    def clear_frame(self, frame_idx: int):
        self.clear_visible_on_frame(frame_idx)

    def clear_visible_on_frame(self, frame_idx: int):
        to_remove = []
        for anchor_frame, items in self.annotations.items():
            for item in items:
                if item_visible_on_frame(item, frame_idx, anchor_frame):
                    to_remove.append(item.get("id"))
        for ann_id in to_remove:
            if ann_id:
                self.remove_by_id(ann_id)

    def update_item(self, frame_idx: int, annotation_id: str, updates: Dict[str, Any]) -> bool:
        return self.update_by_id(annotation_id, updates)

    def update_by_id(self, annotation_id: str, updates: Dict[str, Any]) -> bool:
        for anchor_frame, items in self.annotations.items():
            for item in items:
                if item.get("id") == annotation_id:
                    item.update(updates)
                    start, end = get_item_frame_range(item, anchor_frame)
                    item["start_frame"] = start
                    item["end_frame"] = end
                    return True
        return False

    def find_at_point(self, frame_idx: int, norm_x: float, norm_y: float, threshold: float = 0.04):
        items = self.get_frame(frame_idx)
        for item in reversed(items):
            if item.get("type") == "text":
                continue
            if self._point_hits_item(item, norm_x, norm_y, threshold):
                return item
        for item in reversed(items):
            if item.get("type") == "text" and self._point_hits_item(item, norm_x, norm_y, threshold):
                return item
        return None

    def find_edit_candidate(self, frame_idx: int, norm_x: float, norm_y: float, threshold: float = 0.03):
        items = self.get_frame(frame_idx)
        for item in reversed(items):
            target = self.find_edit_target(item, norm_x, norm_y, threshold)
            if target:
                return item, target
        return None, None

    @staticmethod
    def _point_hits_item(item: Dict[str, Any], norm_x: float, norm_y: float, threshold: float) -> bool:
        ann_type = item.get("type", "rect")
        x1 = item.get("norm_x1", 0.0)
        y1 = item.get("norm_y1", 0.0)
        x2 = item.get("norm_x2", x1)
        y2 = item.get("norm_y2", y1)

        if ann_type == "text":
            return abs(norm_x - x1) <= threshold and abs(norm_y - y1) <= threshold

        left = min(x1, x2) - threshold
        right = max(x1, x2) + threshold
        top = min(y1, y2) - threshold
        bottom = max(y1, y2) + threshold

        if ann_type in ("rect", "ellipse"):
            return left <= norm_x <= right and top <= norm_y <= bottom

        if ann_type in ("line", "arrow"):
            if left <= norm_x <= right and top <= norm_y <= bottom:
                return True
            dist = _point_segment_distance(norm_x, norm_y, x1, y1, x2, y2)
            return dist <= threshold

        return False

    @staticmethod
    def get_bounds(item: Dict[str, Any]):
        x1 = item.get("norm_x1", 0.0)
        y1 = item.get("norm_y1", 0.0)
        x2 = item.get("norm_x2", x1)
        y2 = item.get("norm_y2", y1)
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    @staticmethod
    def set_bounds(item: Dict[str, Any], left, top, right, bottom) -> Dict[str, Any]:
        updated = dict(item)
        updated["norm_x1"] = max(0.0, min(1.0, left))
        updated["norm_y1"] = max(0.0, min(1.0, top))
        updated["norm_x2"] = max(0.0, min(1.0, right))
        updated["norm_y2"] = max(0.0, min(1.0, bottom))
        return updated

    @staticmethod
    def _clamp_norm(value: float) -> float:
        return max(0.0, min(1.0, value))

    @classmethod
    def find_edit_target(cls, item: Dict[str, Any], norm_x: float, norm_y: float, threshold: float = 0.03):
        """Return handle id or 'move' if the point hits the annotation body."""
        ann_type = item.get("type", "rect")
        x1 = item.get("norm_x1", 0.0)
        y1 = item.get("norm_y1", 0.0)
        x2 = item.get("norm_x2", x1)
        y2 = item.get("norm_y2", y1)

        def near(px, py):
            return math.hypot(norm_x - px, norm_y - py) <= threshold

        if ann_type in ("line", "arrow"):
            if near(x1, y1):
                return "p1"
            if near(x2, y2):
                return "p2"
            if cls._point_hits_item(item, norm_x, norm_y, threshold):
                return "move"
            return None

        if ann_type in ("rect", "ellipse"):
            left, top, right, bottom = cls.get_bounds(item)
            corners = {
                "tl": (left, top),
                "tr": (right, top),
                "bl": (left, bottom),
                "br": (right, bottom),
            }
            for handle, (cx, cy) in corners.items():
                if near(cx, cy):
                    return handle
            if left <= norm_x <= right and top <= norm_y <= bottom:
                return "move"
            return None

        if ann_type == "text":
            if near(x1, y1):
                return "move"
            if cls._point_hits_item(item, norm_x, norm_y, threshold):
                return "move"
            return None

        return None

    @classmethod
    def resize_item_by_handle(
        cls,
        snapshot: Dict[str, Any],
        handle: str,
        norm_x: float,
        norm_y: float,
        min_size: float = 0.01,
    ) -> Dict[str, Any]:
        norm_x = cls._clamp_norm(norm_x)
        norm_y = cls._clamp_norm(norm_y)
        ann_type = snapshot.get("type", "rect")

        if handle in ("p1", "p2"):
            updated = dict(snapshot)
            if handle == "p1":
                updated["norm_x1"] = norm_x
                updated["norm_y1"] = norm_y
            else:
                updated["norm_x2"] = norm_x
                updated["norm_y2"] = norm_y
            return updated

        if ann_type in ("rect", "ellipse") and handle in ("tl", "tr", "bl", "br"):
            left, top, right, bottom = cls.get_bounds(snapshot)
            if handle == "tl":
                left, top = norm_x, norm_y
            elif handle == "tr":
                right, top = norm_x, norm_y
            elif handle == "bl":
                left, bottom = norm_x, norm_y
            elif handle == "br":
                right, bottom = norm_x, norm_y

            if right - left < min_size:
                if handle in ("tl", "bl"):
                    left = right - min_size
                else:
                    right = left + min_size
            if bottom - top < min_size:
                if handle in ("tl", "tr"):
                    top = bottom - min_size
                else:
                    bottom = top + min_size

            return cls.set_bounds(snapshot, left, top, right, bottom)

        return dict(snapshot)

    @staticmethod
    def move_item(item: Dict[str, Any], delta_x: float, delta_y: float) -> Dict[str, Any]:
        moved = dict(item)
        for key in ("norm_x1", "norm_x2"):
            if key in moved:
                moved[key] = max(0.0, min(1.0, moved[key] + delta_x))
        for key in ("norm_y1", "norm_y2"):
            if key in moved:
                moved[key] = max(0.0, min(1.0, moved[key] + delta_y))
        return moved

    def frames_with_annotations(self) -> List[int]:
        frames = set()
        for anchor_frame, items in self.annotations.items():
            for item in items:
                start, end = get_item_frame_range(item, anchor_frame)
                for frame_idx in range(start, end + 1):
                    frames.add(frame_idx)
        return sorted(frames)

    def total_count(self) -> int:
        return sum(len(items) for items in self.annotations.values())

    def all_items_sorted(self):
        """Return (start_frame, end_frame, anchor_frame, item) sorted by range start."""
        entries = []
        for anchor_frame, items in self.annotations.items():
            for item in items:
                start, end = get_item_frame_range(item, anchor_frame)
                entries.append((start, end, anchor_frame, item))
        entries.sort(key=lambda entry: (entry[0], entry[2], entry[3].get("id", "")))
        return entries

    def as_frame_dict(self, total_frames: Optional[int] = None) -> Dict[int, List[Dict[str, Any]]]:
        expanded: Dict[int, List[Dict[str, Any]]] = {}
        for anchor_frame, items in self.annotations.items():
            for item in items:
                start, end = get_item_frame_range(item, anchor_frame)
                if total_frames is not None:
                    end = min(end, max(0, total_frames - 1))
                for frame_idx in range(start, end + 1):
                    expanded.setdefault(frame_idx, []).append(item)
        return expanded

    def _file_data(self, stored_video_path, annotations, deleted_ids) -> Dict[str, Any]:
        return {
            "video_path": stored_video_path,
            "fps": self.fps,
            "annotations": {str(frame_idx): items for frame_idx, items in annotations.items()},
            "deleted_ids": sorted(deleted_ids),
        }

    def to_dict(self) -> Dict[str, Any]:
        return self._file_data(paths.to_storage(self.video_path), self.annotations, self._deleted_ids)

    def from_dict(self, data: Dict[str, Any], path: str = ""):
        """파일 내용으로 메모리를 바꾸고 base를 잡음. 모양이 맞지 않으면 AnnotationFileError (메모리는 그대로)."""
        annotations, deleted_ids = _parse_annotation_data(data, path)
        self.video_path = data.get("video_path")
        self.fps = float(data.get("fps", 0.0) or 0.0)
        self._adopt(annotations, deleted_ids)

    def save(self, path: Optional[str] = None) -> str:
        """디스크를 다시 읽어 이 창이 바꾼 것만 합친 뒤 원자적으로 쓰고, 메모리를 합친 결과로 바꿈 (다른 창의 항목이 옴).

        읽지 못하거나 깨진 파일이면 AnnotationFileError (그 파일은 덮지 않음). 쓰기가 실패하면 OSError 등을 그대로
        올리고 원래 파일·메모리는 그대로 (다시 저장하면 됨).
        """
        if not self.video_path:
            raise ValueError("No video loaded")
        target = path or annotation_file_path(self.video_path)
        # 폴더·파일을 만들기 전에: 적을 영상 경로를 정하지 못하면(paths.PathMapError) 빈 폴더·파일을 남기지 않게
        stored_video_path = paths.to_storage(self.video_path)
        _make_annotation_folder(os.path.dirname(os.path.abspath(target)))
        disk_data = _read_annotation_file(target)
        if disk_data is _MISSING:
            disk, disk_deleted = {}, set()
        else:
            disk_annotations, disk_deleted = _parse_annotation_data(disk_data, target)
            disk = _flatten(disk_annotations)
        merged, deleted = merge_annotations(disk, disk_deleted, self._base, _flatten(self.annotations))
        merged_annotations = _unflatten(merged)
        user_files.write_json_atomic(target, self._file_data(stored_video_path, merged_annotations, deleted))
        self._adopt(merged_annotations, deleted)
        return target

    def load(self, path: Optional[str] = None) -> bool:
        """주석 파일을 읽음 → 있었으면 True, 없으면 False. 읽지 못했거나 깨졌으면 AnnotationFileError (메모리는 그대로)."""
        if not self.video_path:
            return False
        target = path or annotation_file_path(self.video_path)
        data = _read_annotation_file(target)
        if data is _MISSING:
            return False
        opened_video_path = self.video_path
        self.from_dict(data, target)
        # 파일에 적힌 경로(다른 PC·OS에서 저장했을 수 있음)로 바꾸지 않고 지금 연 영상 경로를 유지
        self.video_path = opened_video_path
        return True


def _point_segment_distance(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)
