"""B 키 오버레이(프레임 왼쪽 아래 "File: <이름>, Frame: n/N")의 크기·자리 규칙 — 두 그리기 길이 함께 쓴다:
굽는 길(`player_playback.overlay_text` — cv2로 프레임 픽셀에 흰 상자·검정 글자)과 네이티브 프레임의 아이템 길(`video_widget.set_overlay_text` —
읽기 전용 IOSurface 프레임에는 굽지 않고 Qt 아이템으로, 같은 자리·같은 크기). 한 곳에 두어 두 길이 어긋나지 않게. Qt 없음(cv2 글자 크기만).

좁은 프레임에서 들어갈 만큼 줄이는 글자 배율은 지금 글자가 아니라 '자리 잡을 글'(overlay_reserve_text — 'Frame: n/N'의 n을 N의 자릿수만큼 가장 넓은
숫자로)로 정함 — 프레임 번호에 따라 글자 크기가 바뀌지 않게(2026-11-09). 흰 상자는 글자에 딱 맞춤(사용자 결정 — 오른쪽 빈자리 없이; 숫자 폭이 같은
글꼴이라 같은 자릿수 안에서는 떨리지 않음, 자릿수가 바뀔 때만 한 칸씩)."""

import math
import re
from typing import NamedTuple

import cv2

OVERLAY_TEXT_SCALE = 1.5  # B 키 오버레이 글자 크기 — 1080p 기준 예전(scale 0.7)의 배수, 프레임 높이에 비례 (overlay_metrics·overlay_text)
OVERLAY_FONT = cv2.FONT_HERSHEY_SIMPLEX  # 굽는 길의 글꼴 — 아이템 길은 Qt 글꼴이지만 높이를 이 글꼴의 글자 높이에 맞춤


_FRAME_NUMBER = re.compile(r"(?<=Frame: )(\d+)(?=/(\d+)$)")  # overlay_label 끝의 'Frame: <지금>/<전체>'의 <지금>


def overlay_reserve_text(text, digit):
    """흰 상자의 너비·글자 크기를 정할 글 — text 끝의 'Frame: n/N'에서 n을 digit으로 N의 자릿수(n이 더 길면 그것)만큼 바꾼 것. 파일 이름·전체 장
    수는 그대로. 프레임 번호가 없으면 text 그대로(잡을 자리가 없음). digit은 그리는 글꼴에서 가장 넓은 숫자(widest_digit) — 번호가 1이든 119든 같은 글."""
    match = _FRAME_NUMBER.search(text)
    if match is None:
        return text
    digits = max(len(match.group(1)), len(match.group(2)))
    return text[:match.start(1)] + digit * digits + text[match.end(1):]


def widest_digit(width_of):
    """0~9 중 width_of(숫자 한 글자 → 너비)가 가장 큰 숫자 (같으면 앞의 것)."""
    return max("0123456789", key=width_of)


class OverlayMetrics(NamedTuple):
    scale: float  # cv2 글꼴 배율
    thickness: int  # 획 굵기(px)
    pad: int  # 흰 상자 안쪽 여백
    margin_x: int  # 왼쪽 여백
    margin_y: int  # 아래 여백


def overlay_metrics(width, height):
    """B 키 오버레이의 글자 배율·굵기·여백 — 프레임 크기에 비례: k = OVERLAY_TEXT_SCALE × max(너비/1920, 높이/1080)
    (1080p는 예전 scale 0.7·굵기 2·여백 10/20/5의 1.5배, 4K는 그 2배 픽셀; 16:9 창에 맞춰 볼 때 어느 비율의 클립이든 같은 크기 — 가로가 긴 스코프 클립은 너비로 맞춰짐).

    굵기만은 더 줌(× √(k/1.5) — 프레임이 큰 만큼): 4K 프레임은 창에 맞춰 반으로 줄여 보이는데 그때 획 가장자리가 섞여 같은 비율의 굵기도 가늘고 연하게 보임
    (사용자 보고 — 1080p는 굵게, 4K는 보통 굵기로 보였음) → 4K는 2배(6px)가 아니라 8px."""
    k = OVERLAY_TEXT_SCALE * max(width / 1920, height / 1080)
    thickness = max(1, round(2 * k * math.sqrt(k / OVERLAY_TEXT_SCALE)))
    return OverlayMetrics(0.7 * k, thickness, max(1, round(5 * k)), max(1, round(10 * k)), max(1, round(20 * k)))


class OverlayLayout(NamedTuple):
    """한 글자줄의 배치 — 기준선은 (margin_x, 프레임 높이 − margin_y), 흰 상자는 글자 상자를 pad만큼 넓힌 것(아래는 pad와 글자 꼬리 중 큰 것)."""

    scale: float  # cv2 글꼴 배율 (너비를 넘치면 줄인 값)
    thickness: int  # cv2 획 굵기(px) (줄였으면 같은 비율로)
    pad: int
    margin_x: int
    margin_y: int
    text_width: int  # cv2 글자 너비(px)
    text_height: int  # cv2 글자 높이(px) — 기준선 위
    baseline: int  # cv2 기준선 아래(g·p·_ 꼬리, px)
    room: int  # 글자가 들어갈 너비 = 너비 − 2·margin_x (아주 좁은 프레임에서도 1 이상)


def overlay_layout(text, width, height):
    """width×height 프레임에 text를 놓는 배치 — overlay_metrics의 크기·여백, 너비를 넘치면 들어갈 만큼 배율·굵기를 줄임
    (예전엔 0.5로 한 번만 줄여 좁은 프레임에선 여전히 넘쳤음). 넘치는지는 자리 잡을 글(overlay_reserve_text)로 봄 — 프레임 번호가 바뀌어도
    배율이 그대로 (2026-11-09)."""
    scale, thickness, pad, margin_x, margin_y = overlay_metrics(width, height)
    reserve = overlay_reserve_text(text, widest_digit(lambda d: cv2.getTextSize(d, OVERLAY_FONT, scale, thickness)[0][0]))
    (rw, _rh), _rbase = cv2.getTextSize(reserve, OVERLAY_FONT, scale, thickness)
    room = max(1, width - 2 * margin_x)  # 아주 좁은 프레임에서도 음수가 되지 않게
    if rw > room:
        scale *= room / rw
        thickness = max(1, round(thickness * room / rw))
    (tw, th), base = cv2.getTextSize(text, OVERLAY_FONT, scale, thickness)
    return OverlayLayout(scale, thickness, pad, margin_x, margin_y, tw, th, base, room)


class LabelBox(NamedTuple):
    """한 글자줄의 흰 상자(끝 픽셀 포함 — cv2.rectangle과 같은 규칙)와 글자 기준선 왼쪽 끝."""

    left: int
    top: int
    right: int
    bottom: int
    x: int  # 기준선 왼쪽 끝
    y: int  # 기준선


def overlay_label_box(text, width, height, align="left", lift=0):
    """(OverlayLayout, LabelBox) — align "left"는 기준선 왼쪽 끝이 margin_x(A 글자 — 왼쪽 아래), "right"는 상자 오른쪽 끝이 너비 − margin_x + pad
    (A 상자 왼쪽 끝 margin_x − pad의 거울 — 와이프 중 B 글자, 오른쪽 아래). lift만큼 위로(겹칠 때 B를 한 줄 위로 — label_lift).
    그 밖의 정렬은 ValueError."""
    if align not in ("left", "right"):
        raise ValueError(f"B 키 글자 정렬은 left 또는 right여야 합니다: {align!r}")
    layout = overlay_layout(text, width, height)
    x = layout.margin_x if align == "left" else width - layout.margin_x - layout.text_width
    y = height - layout.margin_y - lift
    pad = layout.pad
    box = LabelBox(x - pad, y - layout.text_height - pad, x + layout.text_width + pad, y + max(pad, layout.baseline), x, y)
    return layout, box


def draw_overlay_label(frame, text, layout, box, dx=0, dy=0):
    """흰 상자 + 검정 글자를 그림 — (dx, dy)만큼 옮긴 자리에(프레임의 일부를 잘라 낸 배열에 그릴 때)."""
    cv2.rectangle(frame, (box.left + dx, box.top + dy), (box.right + dx, box.bottom + dy), (255, 255, 255), -1)  # g·p·_ 꼬리까지 상자 안에
    cv2.putText(frame, text, (box.x + dx, box.y + dy), OVERLAY_FONT, layout.scale, (0, 0, 0), layout.thickness)


def burn_overlay_label(frame, text, align="left", lift=0):
    """B 키 글자를 프레임 픽셀에 구움 — 흰 상자 위 검정 글자(굽는 길: A는 플레이어 overlay_text, 와이프 중 B는 video_widget). 자리는
    overlay_label_box(정렬·lift), 그 밖의 정렬은 그리기 전에 ValueError."""
    height, width = frame.shape[:2]
    layout, box = overlay_label_box(text, width, height, align, lift)
    draw_overlay_label(frame, text, layout, box)


def label_lift(text_a, text_b, width, height):
    """와이프 중 B 글자를 위로 올릴 거리(px) — 오른쪽 아래의 B 상자가 왼쪽 아래 A 상자와 겹치거나 틈이 pad보다 좁으면(파일 이름이 길거나 세로 영상)
    A 상자 높이 + pad, 아니면 0 (A의 Frame: n/N을 덮지 않게 — 사용자 결정 2026-11-20 '겹칠 때만 B를 한 줄 위로'). text_a가 None(A 글자 없음)이면 0."""
    if not text_a or not text_b:
        return 0
    _layout_a, a = overlay_label_box(text_a, width, height, "left")
    layout_b, b = overlay_label_box(text_b, width, height, "right")
    if a.right + layout_b.pad < b.left:
        return 0
    return (a.bottom - a.top + 1) + layout_b.pad
