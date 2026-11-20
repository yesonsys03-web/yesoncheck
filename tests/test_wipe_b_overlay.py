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


# ---------------------------------------------------------------- CPU 길 (RGB 합성 — offscreen raster)

def shown_image(player):
    """화면 아이템에 걸린 그림 (raster 길의 픽스맵) → (높이, 너비, 3) RGB."""
    from PyQt5.QtGui import QImage

    image = player.videoWidget.video_item.pixmap().toImage().convertToFormat(QImage.Format_RGB888)
    width, height = image.width(), image.height()
    bits = image.bits()
    bits.setsize(image.byteCount())
    return np.frombuffer(bits, np.uint8).reshape(height, image.bytesPerLine())[:, :width * 3].reshape(height, width, 3).copy()


def b_box(player, width, height):
    """오른쪽 아래 B 상자의 (왼쪽, 위, 오른쪽, 아래) — burn_overlay_label의 오른쪽 정렬 규칙."""
    layout = overlay_layout(player.overlay_label_b(), width, height)
    y = height - layout.margin_y
    return (width - layout.margin_x - layout.text_width - layout.pad, y - layout.text_height - layout.pad,
            width - layout.margin_x + layout.pad, y + max(layout.pad, layout.baseline))


@pytest.fixture
def wiped(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    """A·B(640×360, 첫 장은 검정)를 열고 와이프·X·B 키 글자를 켠 플레이어 (raster)."""
    from tests.conftest import write_test_video

    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "a_tk1.mov"), size=(640, 360)))
    assert player.open_file("B", write_test_video(str(tmp_path / "b_tk2.mov"), size=(640, 360)))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(1)  # 와이프를 켠 뒤 B를 읽음
    player.toggle_overlay_text()
    qapp.processEvents()
    assert player.show_overlay and player.frame_b is not None
    return player


def test_provider_only_with_wipe_b_and_overlay(wiped):
    assert wiped._overlay_b_text() == wiped.overlay_label_b()
    assert wiped.overlay_label_b() == "File: b_tk2.mov, Frame: 1/24"
    wiped.toggle_overlay_text()  # B 키 끔
    assert wiped._overlay_b_text() is None
    wiped.toggle_overlay_text()
    wiped.wipeXButton.setChecked(False)  # 와이프는 켠 채 축이 없음 — B가 보이지 않음
    assert wiped._overlay_b_text() is None
    wiped.wipeXButton.setChecked(True)
    wiped.wipeCheckBox.setChecked(False)  # 와이프 끔 → B도 닫힘
    assert wiped._overlay_b_text() is None


def test_b_label_uses_b_own_frame_number(wiped, qapp):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent

    wiped.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))  # →는 A만 한 장
    qapp.processEvents()
    assert wiped.overlay_label().endswith("Frame: 2/24")
    assert wiped.overlay_label_b().endswith("Frame: 1/24")


def test_rgb_wipe_shows_b_label_bottom_right(wiped):
    image = shown_image(wiped)
    height, width = image.shape[:2]
    left, top, right, bottom = b_box(wiped, width, height)
    edge = image[top + 1:bottom - 1, left + 1:left + 3]  # 상자 왼쪽 가장자리 안쪽 띠 — 글자가 닿지 않는 흰 자리
    assert (edge == 255).all()
    layout = overlay_layout(wiped.overlay_label(), width, height)
    assert (image[height - layout.margin_y, layout.margin_x - layout.pad] == 255).all()  # A 상자도 그대로 (왼쪽 아래)


def test_b_label_is_cut_by_the_wipe_line(wiped):
    wiped.videoWidget.wipe_position_x = 0.99
    wiped.update_frame()
    image = shown_image(wiped)
    height, width = image.shape[:2]
    left, top, right, bottom = b_box(wiped, width, height)
    wipe_x = int(width * 0.99)
    assert not (image[top:bottom + 1, left:wipe_x] == 255).all(axis=2).any()  # 선 왼쪽(A 쪽)에는 B 상자가 없음


def test_rgb_path_does_not_touch_frame_b(wiped):
    """B 글자는 사본에 — 플레이어의 frame_b(B의 첫 장 = 검정)에는 흰 상자가 없음 (준비에서 이미 몇 번 그렸음)."""
    wiped.update_frame()
    assert not (wiped.frame_b == 255).all(axis=2).any()


def test_b_label_on_black_b_of_other_size(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    """A와 크기가 다른 B는 검정으로 그려짐 — B 글자는 그 위에 그대로(어느 B인지 보임)."""
    from tests.conftest import write_test_video

    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "a.mov"), size=(640, 360)))
    assert player.open_file("B", write_test_video(str(tmp_path / "b_small.mov"), size=(320, 240)))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(1)
    player.toggle_overlay_text()
    image = shown_image(player)
    height, width = image.shape[:2]
    left, top, right, bottom = b_box(player, width, height)
    assert (image[top + 1:bottom - 1, left + 1:left + 3] == 255).all()


def test_no_b_label_without_wipe(wiped):
    wiped.wipeCheckBox.setChecked(False)
    image = shown_image(wiped)
    height, width = image.shape[:2]
    layout = overlay_layout("File: b_tk2.mov, Frame: 1/24", width, height)
    right_half = image[height - layout.margin_y - layout.text_height - layout.pad:, width // 2:]
    assert not (right_half == 255).all(axis=2).any()
