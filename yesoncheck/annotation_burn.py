"""Burn frame annotations onto video frames (OpenCV + Qt text).

주석을 그리는 규칙(좌표·기본 굵기·글자 크기·글꼴·화살표 촉)은 여기 한 곳에 둔다 — 굽는 길(burn_annotations_on_frame: 표시 경로의 RGB
프레임·주석 포함 영상보내기)과 네이티브(IOSurface — 읽기 전용이라 굽지 못함) 프레임의 아이템 층(annotation_overlay)이 같은 함수
(annotation_spec 등)를 불러 두 길의 기하가 어긋나지 않게. tests/test_annotation_overlay.py가 굽는 결과를 나누기 전 함수와 바이트까지 견줌.
"""

import math
from typing import NamedTuple, Optional, Tuple

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from yesoncheck.frame_annotations import MAX_FONT_SIZE, MIN_FONT_SIZE

TEXT_PATCH_INSET = 4  # 글자 패치의 안쪽 여백(px) — 글자 원점(기준선 왼쪽)은 패치 왼쪽 위 + (4, 4 + 글꼴 ascent), 패치 왼쪽 위는 주석 (x1, y1)


def hex_to_rgb(color_hex):
    color_hex = (color_hex or "#ff3333").lstrip("#")
    if len(color_hex) != 6:
        return (255, 51, 51)
    return tuple(int(color_hex[i : i + 2], 16) for i in (0, 2, 4))


def auto_stroke_width(width, height):
    """주석에 굵기가 없을 때의 획 굵기 — 프레임 짧은 변 400px마다 1, 최소 2."""
    return max(2, int(min(height, width) / 400))


def default_font_size(width, height):
    """글자 주석에 크기가 없을 때의 글자 크기(점) — 짧은 변 45px마다 1, 최소 14 (그다음 clamp_font_size)."""
    return max(14, int(min(height, width) / 45))


def clamp_font_size(font_size):
    """글자 크기를 MIN_FONT_SIZE~MAX_FONT_SIZE로 자름."""
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size))


def arrow_tip_length(stroke_width):
    """화살표 촉 길이 — 선 길이에 대한 비율(cv2.arrowedLine의 tipLength), 굵을수록 길게 0.12~0.35."""
    return min(0.35, max(0.12, 0.08 + stroke_width * 0.02))


def arrow_tip_points(x1, y1, x2, y2, tip_length):
    """cv2.arrowedLine이 촉으로 긋는 두 선의 바깥 끝 — 촉 선은 이 점에서 (x2, y2)까지. cv2(drawing.cpp)와 같은 식: 촉 길이 = 선 길이 ×
    tip_length, 끝점에서 (x1, y1) 쪽을 본 각 ± 45°, 정수로 반올림(cvRound — 반은 짝수 쪽, 파이썬 round와 같음). 굽는 길은 cv2를 그대로 부르고
    이 함수는 아이템 층이 같은 촉을 그리려고 씀(tests/test_annotation_overlay.py가 cv2 그림과 바이트로 견줌)."""
    tip_size = math.hypot(x1 - x2, y1 - y2) * tip_length
    angle = math.atan2(y1 - y2, x1 - x2)
    return [(round(x2 + tip_size * math.cos(angle + side * math.pi / 4)), round(y2 + tip_size * math.sin(angle + side * math.pi / 4)))
            for side in (1, -1)]


def burned_stroke_extent(stroke_width):
    """cv2가 굵기 stroke_width로 그린 선(line·rectangle·ellipse·arrowedLine이 함께 쓰는 ThickLine)이 실제로 덮는 픽셀 폭 — 1은 1px 선,
    2 이상은 반폭 ceil(굵기/2)의 다각형(+ 둥근 끝·이음)을 끝 픽셀까지 칠해 2·ceil(굵기/2) + 1 (굵기 3 → 5px, 4 → 5px). 굽는 길은 쓰지 않고
    (cv2에 굵기를 그대로 넘김) 아이템 층이 구운 획과 같은 굵기로 보이려고 펜 폭으로 씀. 이 cv2(4.6)를 그려서 잰 값은
    tests/test_annotation_overlay.py가 지킴."""
    if stroke_width <= 1:
        return 1
    return 2 * math.ceil(stroke_width / 2) + 1


def rect_corners(x1, y1, x2, y2):
    """사각형 주석의 (왼쪽, 위, 오른쪽, 아래) — 그린 방향과 상관없이."""
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def ellipse_center_axes(x1, y1, x2, y2):
    """타원 주석의 (가운데 x, 가운데 y, 가로 반지름, 세로 반지름) — 정수 나눗셈, 반지름은 최소 1."""
    return (x1 + x2) // 2, (y1 + y2) // 2, max(1, abs(x2 - x1) // 2), max(1, abs(y2 - y1) // 2)


def annotation_font(font_size):
    """글자 주석의 글꼴 — Apple SD Gothic Neo → Malgun Gothic → Arial 중 정확히 있는 첫 글꼴(없으면 Arial), 크기는 점."""
    font = QFont("Apple SD Gothic Neo", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Malgun Gothic", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Arial", font_size)
    return font


class AnnotationSpec(NamedTuple):
    """주석 하나를 width×height 프레임에 그릴 값 (annotation_spec). kind는 rect|ellipse|line|arrow|text(그 밖의 값은 그리지 않음),
    color는 주석의 색 글자 그대로(글자 — QColor), rgb는 그 RGB(도형), 좌표는 프레임 픽셀(정수 — cv2 좌표). text·font_size는 글자 주석이고
    글자가 있을 때만(그 밖에는 None)."""

    kind: str
    color: Optional[str]
    rgb: Tuple[int, int, int]
    stroke_width: int
    x1: int
    y1: int
    x2: int
    y2: int
    text: Optional[str]
    font_size: Optional[int]


def annotation_spec(annotation, width, height):
    """주석 dict → AnnotationSpec — 굽는 길과 아이템 층이 함께 쓰는 한 규칙. 값을 읽는 차례·식은 예전 굽기 반복문 그대로(잘못된 값의 예외도 같은
    자리에서): 종류(없으면 rect)·색(없으면 #ff3333)·굵기(없으면 auto_stroke_width, 1 아래는 1)·좌표 int(정규 좌표 × 너비/높이)(x2·y2가 없으면
    x1·y1), 글자 주석이면 글자와 — 글자가 있을 때만 — 크기(없으면 default_font_size, clamp_font_size)."""
    kind = annotation.get("type", "rect")
    color = annotation.get("color", "#ff3333")
    rgb = hex_to_rgb(color)
    stroke_width = int(annotation.get("stroke_width", auto_stroke_width(width, height)))
    stroke_width = max(1, stroke_width)

    x1 = int(annotation.get("norm_x1", 0.0) * width)
    y1 = int(annotation.get("norm_y1", 0.0) * height)
    x2 = int(annotation.get("norm_x2", annotation.get("norm_x1", 0.0)) * width)
    y2 = int(annotation.get("norm_y2", annotation.get("norm_y1", 0.0)) * height)

    text = font_size = None
    if kind == "text":
        text = annotation.get("text", "")
        if text:
            font_size = clamp_font_size(int(annotation.get("font_size", default_font_size(width, height))))
    return AnnotationSpec(kind, color, rgb, stroke_width, x1, y1, x2, y2, text, font_size)


def _paste_rgba_patch(frame, patch_rgb, mask, x, y):
    patch_h, patch_w = patch_rgb.shape[:2]
    frame_h, frame_w = frame.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(frame_w, x + patch_w)
    y2 = min(frame_h, y + patch_h)
    if x2 <= x1 or y2 <= y1:
        return

    sx1 = x1 - x
    sy1 = y1 - y
    sw = x2 - x1
    sh = y2 - y1
    region = frame[y1:y2, x1:x2]
    patch = patch_rgb[sy1 : sy1 + sh, sx1 : sx1 + sw]
    alpha = mask[sy1 : sy1 + sh, sx1 : sx1 + sw].astype(np.float32) / 255.0
    alpha = alpha[..., np.newaxis]
    frame[y1:y2, x1:x2] = (patch * alpha + region * (1.0 - alpha)).astype(np.uint8)


def render_text_patch(text, color_hex, font_size=22):
    font = annotation_font(font_size)

    metrics = QFontMetrics(font)
    text_width = metrics.horizontalAdvance(text) + 2 * TEXT_PATCH_INSET
    text_height = metrics.height() + 2 * TEXT_PATCH_INSET
    image = QImage(text_width, text_height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor(color_hex))
    painter.drawText(TEXT_PATCH_INSET, metrics.ascent() + TEXT_PATCH_INSET, text)
    painter.end()

    buffer = image.bits()
    buffer.setsize(image.byteCount())
    array = np.frombuffer(buffer, dtype=np.uint8).reshape(text_height, text_width, 4)
    rgb = array[:, :, [2, 1, 0]].copy()
    alpha = array[:, :, 3].copy()
    return rgb, alpha


def burn_annotations_on_frame(frame, annotations):
    """Draw annotations permanently onto an RGB frame copy.

    프레임은 RGB 3채널(표시 경로의 `frame_a`, 내보내기 워커는 BGR → RGB로 바꿔 넘김)이라 도형 색도 RGB 순서로 그린다 —
    2026-11-03까지는 BGR 순서로 그려 빨강(#ff3333)이 파랑으로 굽혔음(글자 패치는 RGB라 정상이었음). tests/test_annotation_burn_color.py
    좌표·굵기·글자 크기는 annotation_spec(네이티브 프레임의 아이템 층과 같은 규칙).
    """
    if frame is None or not annotations:
        return frame

    output = frame.copy()
    height, width = output.shape[:2]

    for annotation in annotations:
        spec = annotation_spec(annotation, width, height)
        x1, y1, x2, y2 = spec.x1, spec.y1, spec.x2, spec.y2

        if spec.kind == "text":
            if not spec.text:
                continue
            patch_rgb, alpha = render_text_patch(spec.text, spec.color, font_size=spec.font_size)
            _paste_rgba_patch(output, patch_rgb, alpha, x1, y1)
        elif spec.kind == "rect":
            left, top, right, bottom = rect_corners(x1, y1, x2, y2)
            cv2.rectangle(output, (left, top), (right, bottom), spec.rgb, spec.stroke_width)
        elif spec.kind == "ellipse":
            center_x, center_y, axis_x, axis_y = ellipse_center_axes(x1, y1, x2, y2)
            cv2.ellipse(output, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, spec.rgb, spec.stroke_width)
        elif spec.kind == "line":
            cv2.line(output, (x1, y1), (x2, y2), spec.rgb, spec.stroke_width)
        elif spec.kind == "arrow":
            cv2.arrowedLine(
                output, (x1, y1), (x2, y2), spec.rgb, spec.stroke_width, tipLength=arrow_tip_length(spec.stroke_width)
            )

    return output
