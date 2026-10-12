"""Burn frame annotations onto video frames (OpenCV + Qt text)."""

import math

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from yesoncheck.frame_annotations import MAX_FONT_SIZE, MIN_FONT_SIZE


def hex_to_rgb(color_hex):
    color_hex = (color_hex or "#ff3333").lstrip("#")
    if len(color_hex) != 6:
        return (255, 51, 51)
    return tuple(int(color_hex[i : i + 2], 16) for i in (0, 2, 4))


def hex_to_bgr(color_hex):
    red, green, blue = hex_to_rgb(color_hex)
    return (blue, green, red)


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
    font = QFont("Apple SD Gothic Neo", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Malgun Gothic", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Arial", font_size)

    metrics = QFontMetrics(font)
    text_width = metrics.horizontalAdvance(text) + 8
    text_height = metrics.height() + 8
    image = QImage(text_width, text_height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor(color_hex))
    painter.drawText(4, metrics.ascent() + 4, text)
    painter.end()

    buffer = image.bits()
    buffer.setsize(image.byteCount())
    array = np.frombuffer(buffer, dtype=np.uint8).reshape(text_height, text_width, 4)
    rgb = array[:, :, [2, 1, 0]].copy()
    alpha = array[:, :, 3].copy()
    return rgb, alpha


def burn_annotations_on_frame(frame, annotations):
    """Draw annotations permanently onto an RGB frame copy."""
    if frame is None or not annotations:
        return frame

    output = frame.copy()
    height, width = output.shape[:2]
    auto_stroke = max(2, int(min(height, width) / 400))

    for annotation in annotations:
        ann_type = annotation.get("type", "rect")
        color = annotation.get("color", "#ff3333")
        bgr = hex_to_bgr(color)
        stroke_width = int(annotation.get("stroke_width", auto_stroke))
        stroke_width = max(1, stroke_width)

        x1 = int(annotation.get("norm_x1", 0.0) * width)
        y1 = int(annotation.get("norm_y1", 0.0) * height)
        x2 = int(annotation.get("norm_x2", annotation.get("norm_x1", 0.0)) * width)
        y2 = int(annotation.get("norm_y2", annotation.get("norm_y1", 0.0)) * height)

        if ann_type == "text":
            text = annotation.get("text", "")
            if not text:
                continue
            font_size = int(annotation.get("font_size", max(14, int(min(height, width) / 45))))
            font_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size))
            patch_rgb, alpha = render_text_patch(text, color, font_size=font_size)
            _paste_rgba_patch(output, patch_rgb, alpha, x1, y1)
        elif ann_type == "rect":
            cv2.rectangle(
                output,
                (min(x1, x2), min(y1, y2)),
                (max(x1, x2), max(y1, y2)),
                bgr,
                stroke_width,
            )
        elif ann_type == "ellipse":
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            axis_x = max(1, abs(x2 - x1) // 2)
            axis_y = max(1, abs(y2 - y1) // 2)
            cv2.ellipse(output, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, bgr, stroke_width)
        elif ann_type == "line":
            cv2.line(output, (x1, y1), (x2, y2), bgr, stroke_width)
        elif ann_type == "arrow":
            tip_length = min(0.35, max(0.12, 0.08 + stroke_width * 0.02))
            cv2.arrowedLine(
                output, (x1, y1), (x2, y2), bgr, stroke_width, tipLength=tip_length
            )

    return output
