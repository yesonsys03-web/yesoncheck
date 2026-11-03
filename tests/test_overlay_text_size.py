"""B 키 오버레이(`overlay_text` — 프레임에 굽는 "File: …, Frame: n/N"): 글자·여백·굵기를 프레임 높이에 비례시켜 해상도와 상관없이 화면에서
같은 크기로 보이게. 기준은 1080p에서 예전(scale 0.7·굵기 2·여백 10/20/5)의 1.5배 — 4K는 그 2배 픽셀이라 창에 맞춰 줄이면 1080p와 같은 크기.
예전에는 프레임 픽셀 고정 크기라 4K에서 반 크기로 보였음(사용자 보고)."""

import os
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

TEXT = "File: FL_106_A001_TK1_HD.mov, Frame: 1/334"


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    p = new_player(make_config(str(tmp_path), {}))
    p.filename_a = "/x/FL_106_A001_TK1_HD.mov"
    p.cap_a = SimpleNamespace(get=lambda prop: 1.0 if prop == cv2.CAP_PROP_POS_FRAMES else 334.0)
    return p


def white_box(frame):
    """오버레이의 흰 바탕 상자 (rows, cols) 크기 — 흰 픽셀이 있는 행·열의 수."""
    white = np.all(frame == 255, axis=2)
    return int(white.any(axis=1).sum()), int(white.any(axis=0).sum())


def box_height(scale, thickness, pad):
    """상자 높이: 글자 높이 + 위 여백 + 아래 여백(여백과 글자 꼬리 중 큰 것) + 1(양 끝 포함)."""
    (_, th), base = cv2.getTextSize(TEXT, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    return th + pad + max(pad, base) + 1


def test_1080p_overlay_is_one_and_a_half_times_the_old_size(player):
    """1080p: 예전(scale 0.7·굵기 2·여백 5)의 1.5배(scale 1.05·굵기 3·여백 8)."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    player.overlay_text(frame)
    rows, _cols = white_box(frame)
    assert rows == box_height(1.05, 3, 8)
    assert rows == pytest.approx(box_height(0.7, 2, 5) * 1.5, abs=4)


def test_4k_overlay_scales_with_frame_height(player):
    """4K(2배 높이)는 1080p의 2배 픽셀 → 창에 맞춰 반으로 줄여 보면 같은 크기."""
    hd, uhd = np.zeros((1080, 1920, 3), np.uint8), np.zeros((2160, 3840, 3), np.uint8)
    player.overlay_text(hd)
    player.overlay_text(uhd)
    rows_hd, cols_hd = white_box(hd)
    rows_uhd, cols_uhd = white_box(uhd)
    assert rows_uhd == pytest.approx(rows_hd * 2, rel=0.08)
    assert cols_uhd == pytest.approx(cols_hd * 2, rel=0.08)


def test_overlay_sits_in_the_bottom_left_with_proportional_margins(player):
    frame = np.zeros((2160, 3840, 3), np.uint8)
    player.overlay_text(frame)
    white = np.all(frame == 255, axis=2)
    ys, xs = np.where(white)
    assert xs.min() == pytest.approx(5 * 3, abs=2)  # x 여백 10·상자 5 → 1080p의 1.5배 × 2
    (_, _), base = cv2.getTextSize(TEXT, cv2.FONT_HERSHEY_SIMPLEX, 2.1, 8)
    assert frame.shape[0] - 1 - ys.max() == 60 - max(15, base) - 1  # 아래 여백 20×3 − 상자 아래(여백 15 또는 글자 꼬리)


@pytest.mark.parametrize("height, scale, thickness", [
    (1080, 1.05, 3),  # 예전 0.7·2의 1.5배
    (2160, 2.1, 8),   # 4K: 크기는 2배 픽셀, 굵기는 2배(6)보다 더 — 창에 맞춰 반으로 줄여 보면 획 가장자리가 섞여 가늘어 보임(사용자 보고) → ×√2
    (720, 0.7, 2),
])
def test_overlay_metrics_scale_with_height_and_thicken_more_for_bigger_frames(height, scale, thickness):
    from yesoncheck.player_playback import overlay_metrics

    m = overlay_metrics(height * 16 // 9, height)
    assert m.scale == pytest.approx(scale) and m.thickness == thickness
    assert (m.pad, m.margin_x, m.margin_y) == (round(5 * height / 720), round(10 * height / 720), round(20 * height / 720))


def test_overlay_metrics_follow_the_larger_of_width_and_height():
    """16:9 창에 맞춰 볼 때 어느 비율이든 같은 크기: 가로가 긴 스코프(1920×804)는 너비로 1080p와 같고, 4:3(1440×1080)은 높이로 같음."""
    from yesoncheck.player_playback import overlay_metrics

    assert overlay_metrics(1920, 804) == overlay_metrics(1920, 1080) == overlay_metrics(1440, 1080)
    assert overlay_metrics(1080, 1920).scale > overlay_metrics(1920, 1080).scale  # 세로로 긴 클립은 높이(1920)로 — 창 높이에 맞춰지므로 그만큼 큼


def test_small_frame_still_fits_and_is_not_tiny(player):
    """작은 프레임(720p)은 예전과 같은 픽셀 크기(scale 0.7·굵기 2·여백 5)."""
    frame = np.zeros((720, 1280, 3), np.uint8)
    player.overlay_text(frame)
    rows, cols = white_box(frame)
    assert 0 < cols < 1280 and rows == box_height(0.7, 2, 5)


@pytest.mark.parametrize("width", [600, 300])
def test_text_wider_than_frame_shrinks_to_fit(player, width):
    """좁은 프레임: 글자를 들어갈 만큼 줄여 상자가 오른쪽 끝 앞에서 끝나고 글자(검정)가 상자 밖으로 나가지 않음 (예전엔 300px에서 넘쳤음)."""
    frame = np.full((1080, width, 3), 128, np.uint8)
    player.overlay_text(frame)
    white = np.all(frame == 255, axis=2)
    ys, xs = np.where(white)
    assert width - 1 - xs.max() >= 5
    black = np.all(frame == 0, axis=2)
    assert not black[:, xs.max() + 1:].any() and not black[:ys.min(), :].any()


def test_letter_tails_stay_inside_the_box(player):
    """g·p·_의 꼬리가 상자 아래로 삐져나오지 않음 (상자 아래는 여백과 글자 꼬리 중 큰 것)."""
    frame = np.full((2160, 3840, 3), 128, np.uint8)
    player.overlay_text(frame)
    white = np.all(frame == 255, axis=2)
    black = np.all(frame == 0, axis=2)
    assert not black[white.any(axis=1).nonzero()[0].max() + 1:, :].any()
