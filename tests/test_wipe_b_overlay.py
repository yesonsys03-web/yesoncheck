"""와이프 중 B 키 글자에 B도 (사용자 요청 2026-11-20 — "와이프 on시 단축키 B 하면 A만 뜨는데, B 파일명도 B 부분에"):
와이프가 켜져 있고 B가 열려 있을 때 B 키 글자를 켜면 영상 오른쪽 아래에 B의 'File: <B 이름>, Frame: <B 번호>/<B 전체>'가 B 쪽에만.
A 글자(왼쪽 아래)는 그대로. 굽는 그리기는 A·B 공용(overlay_text_layout.burn_overlay_label) — 오른쪽 정렬은 A 상자의 거울 자리.
"""

import numpy as np
import pytest

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.overlay_text_layout import burn_overlay_label, overlay_layout

TEXT = "File: EP101_SC050_LAYOUT_TK2.mov, Frame: 12/48"


def white_columns(frame):
    columns = np.where((frame == 255).all(axis=2).any(axis=0))[0]
    return int(columns.min()), int(columns.max())


def white_rows(frame):
    rows = np.where((frame == 255).all(axis=2).any(axis=1))[0]
    return int(rows.min()), int(rows.max())


# ---------------------------------------------------------------- 굽기 (A·B 공용)

@pytest.mark.parametrize("width, height", [(1920, 1080), (960, 540)])
def test_right_label_mirrors_the_left_one(width, height):
    layout = overlay_layout(TEXT, width, height)
    left = np.zeros((height, width, 3), np.uint8)
    right = np.zeros((height, width, 3), np.uint8)
    burn_overlay_label(left, TEXT)
    burn_overlay_label(right, TEXT, "right")
    assert white_columns(left) == (layout.margin_x - layout.pad, layout.margin_x + layout.text_width + layout.pad)
    assert white_columns(right) == (width - layout.margin_x - layout.text_width - layout.pad, width - layout.margin_x + layout.pad)
    assert white_rows(left) == white_rows(right)


def test_left_label_is_what_overlay_text_burned(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    """A 글자는 바뀌지 않음 — 플레이어의 overlay_text가 구운 그림과 바이트까지 같음."""
    player = new_player(make_config(str(tmp_path), {}))
    monkeypatch.setattr(player, "overlay_label", lambda: TEXT)
    by_player = np.full((1080, 1920, 3), 40, np.uint8)
    player.overlay_text(by_player)
    by_function = np.full((1080, 1920, 3), 40, np.uint8)
    burn_overlay_label(by_function, TEXT)
    assert np.array_equal(by_player, by_function)
    assert (by_player != 40).any()  # 무언가 그렸음


def test_unknown_align_is_rejected_before_drawing():
    frame = np.zeros((540, 960, 3), np.uint8)
    with pytest.raises(ValueError):
        burn_overlay_label(frame, TEXT, "middle")
    assert not frame.any()
