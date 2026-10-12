"""Frame annotation data model and persistence."""

import json
import math
import os
import uuid
from typing import Any, Dict, List, Optional

from yesoncheck import paths


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
    """Sidecar JSON path next to the video file."""
    base = os.path.splitext(os.path.basename(video_path))[0]
    folder = os.path.join(os.path.dirname(video_path), ".yesoncheck")
    return os.path.join(folder, f"{base}_annotations.json")


def annotation_export_suggested_name(video_path: str) -> str:
    base, ext = os.path.splitext(os.path.basename(video_path))
    return f"{base}_annotated{ext or '.mp4'}"


def annotation_export_default_path(video_path: str) -> str:
    """Default burned-in export path beside the source video."""
    base, ext = os.path.splitext(video_path)
    return f"{base}_annotated{ext or '.mp4'}"


def annotation_storage_dir(video_path: str) -> str:
    return os.path.join(os.path.dirname(video_path), ".yesoncheck")


def is_annotation_storage_writable(video_path: str) -> bool:
    folder = annotation_storage_dir(video_path)
    try:
        os.makedirs(folder, exist_ok=True)
        test_path = os.path.join(folder, ".write_test")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(test_path)
        return True
    except OSError:
        return False


class FrameAnnotationStore:
    """In-memory store keyed by 0-based frame index."""

    def __init__(self):
        self.video_path: Optional[str] = None
        self.fps: float = 0.0
        self.annotations: Dict[int, List[Dict[str, Any]]] = {}

    def clear(self):
        self.video_path = None
        self.fps = 0.0
        self.annotations = {}

    def set_video(self, video_path: str, fps: float = 0.0):
        self.video_path = video_path
        self.fps = fps
        self.annotations = {}

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

    def to_dict(self) -> Dict[str, Any]:
        serialized = {
            str(frame_idx): items for frame_idx, items in self.annotations.items()
        }
        return {
            "video_path": paths.to_storage(self.video_path),
            "fps": self.fps,
            "annotations": serialized,
        }

    def from_dict(self, data: Dict[str, Any]):
        self.video_path = data.get("video_path")
        self.fps = float(data.get("fps", 0.0) or 0.0)
        self.annotations = {}
        raw = data.get("annotations") or {}
        for key, items in raw.items():
            try:
                frame_idx = int(key)
            except (TypeError, ValueError):
                continue
            self.annotations[frame_idx] = [
                normalize_item_frame_range(item, frame_idx) for item in (items or [])
            ]

    def save(self, path: Optional[str] = None) -> str:
        if not self.video_path:
            raise ValueError("No video loaded")
        target = path or annotation_file_path(self.video_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
        return target

    def load(self, path: Optional[str] = None) -> bool:
        if not self.video_path:
            return False
        target = path or annotation_file_path(self.video_path)
        if not os.path.exists(target):
            return False
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        opened_video_path = self.video_path
        self.from_dict(data)
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
