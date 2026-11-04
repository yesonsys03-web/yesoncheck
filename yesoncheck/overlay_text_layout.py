"""B 키 오버레이(프레임 왼쪽 아래 "File: <이름>, Frame: n/N")의 크기·자리 규칙 — 두 그리기 길이 함께 쓴다:
굽는 길(`player_playback.overlay_text` — cv2로 프레임 픽셀에 흰 상자·검정 글자)과 네이티브 프레임의 아이템 길(`video_widget.set_overlay_text` —
읽기 전용 IOSurface 프레임에는 굽지 않고 Qt 아이템으로, 같은 자리·같은 크기). 한 곳에 두어 두 길이 어긋나지 않게. Qt 없음(cv2 글자 크기만)."""

import math
from typing import NamedTuple

import cv2

OVERLAY_TEXT_SCALE = 1.5  # B 키 오버레이 글자 크기 — 1080p 기준 예전(scale 0.7)의 배수, 프레임 높이에 비례 (overlay_metrics·overlay_text)
OVERLAY_FONT = cv2.FONT_HERSHEY_SIMPLEX  # 굽는 길의 글꼴 — 아이템 길은 Qt 글꼴이지만 높이를 이 글꼴의 글자 높이에 맞춤


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
    (예전엔 0.5로 한 번만 줄여 좁은 프레임에선 여전히 넘쳤음)."""
    scale, thickness, pad, margin_x, margin_y = overlay_metrics(width, height)
    (tw, th), base = cv2.getTextSize(text, OVERLAY_FONT, scale, thickness)
    room = max(1, width - 2 * margin_x)  # 아주 좁은 프레임에서도 음수가 되지 않게
    if tw > room:
        scale *= room / tw
        thickness = max(1, round(thickness * room / tw))
        (tw, th), base = cv2.getTextSize(text, OVERLAY_FONT, scale, thickness)
    return OverlayLayout(scale, thickness, pad, margin_x, margin_y, tw, th, base, room)
