"""도형 주석(사각형·타원·선·화살표)을 프레임에 구운 색은 고른 색 그대로여야 함.

`burn_annotations_on_frame`은 RGB 프레임을 받는데(표시 경로의 `frame_a`, 내보내기 워커는 BGR → RGB로 바꿔 넘김) 도형 색을 BGR 순서로
그려 빨강(#ff3333)이 파랑 (51, 51, 255)으로, 노랑이 청록으로 굽혔음 — 표시·내보내기 둘 다(2026-11-03 builder check가 실행으로 찾음).
글자 주석(`render_text_patch` — RGB 패치)과 편집 미리보기는 정상이었으므로 도형만 글자와 같은 순서로 맞춘다.
"""

import sys

import numpy as np
import pytest

from yesoncheck.annotation_burn import burn_annotations_on_frame

RED = (255, 51, 51)  # "#ff3333"을 RGB로


def black_rgb_frame(height=120, width=160):
    return np.zeros((height, width, 3), np.uint8)


def burned_colors(output):
    """검정이 아닌(구워진) 픽셀들의 색 집합 — RGB 튜플."""
    mask = output.any(axis=2)
    return {tuple(int(c) for c in px) for px in output[mask]}


def shape(ann_type, color="#ff3333"):
    return {"type": ann_type, "color": color, "norm_x1": 0.2, "norm_y1": 0.2, "norm_x2": 0.8, "norm_y2": 0.8, "stroke_width": 3}


@pytest.mark.parametrize("ann_type", ["rect", "ellipse", "line", "arrow"])
def test_shape_is_burned_in_the_chosen_color(ann_type):
    output = burn_annotations_on_frame(black_rgb_frame(), [shape(ann_type)])
    assert burned_colors(output) == {RED}  # 전에는 {(51, 51, 255)} — 파랑


def test_yellow_line_is_yellow_not_cyan():
    output = burn_annotations_on_frame(black_rgb_frame(), [shape("line", "#ffff00")])
    assert burned_colors(output) == {(255, 255, 0)}


def test_text_and_shape_agree_on_channel_order(qapp):
    """글자(이미 RGB — QFont·QPainter라 qapp 필요)와 도형이 같은 순서 — 빨강이면 모든 구워진 픽셀에서 R ≥ B (안티앨리어싱 가장자리 포함)."""
    text = {"type": "text", "text": "A", "color": "#ff3333", "norm_x1": 0.05, "norm_y1": 0.05, "font_size": 30}
    output = burn_annotations_on_frame(black_rgb_frame(), [text, shape("rect")])
    mask = output.any(axis=2)
    pixels = output[mask].astype(int)
    assert pixels.size  # 사각형은 늘 그려짐
    assert np.all(pixels[:, 0] >= pixels[:, 2]), "R < B인 픽셀이 있음 — 도형이나 글자가 BGR 순서로 굽힘"
    if sys.platform != "win32":  # Windows offscreen은 글리프를 못 그림(기존 — CLAUDE.md '다음 후보')
        rect_only = burn_annotations_on_frame(black_rgb_frame(), [shape("rect")])
        assert output.any(axis=2).sum() > rect_only.any(axis=2).sum(), "글자가 하나도 안 그려짐"


def test_frame_itself_is_not_modified():
    frame = black_rgb_frame()
    burn_annotations_on_frame(frame, [shape("rect")])
    assert not frame.any()
