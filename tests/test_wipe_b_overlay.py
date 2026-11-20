"""와이프 중 B 키 글자에 B도 (사용자 요청 2026-11-20 — "와이프 on시 단축키 B 하면 A만 뜨는데, B 파일명도 B 부분에"):
와이프가 켜져 있고 B가 열려 있을 때 B 키 글자를 켜면 영상 오른쪽 아래에 B의 'File: <B 이름>, Frame: <B 번호>/<B 전체>'.
와이프 선에 잘리지 않고 영상 위에 늘 보임(사용자 결정 2026-11-20 'B 텍스트도 A처럼 잘리지 않게'). A 글자(왼쪽 아래)는 그대로. 굽는 그리기는 A·B 공용(overlay_text_layout.burn_overlay_label) — 오른쪽 정렬은 A 상자의 거울 자리.
"""

import numpy as np
import pytest
from PyQt5.QtCore import Qt

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


def test_b_label_uses_b_own_frame_number(wiped):
    """B 글자의 번호는 B 캡처의 번호 — B가 A와 다른 자리에 있으면 그 번호(A의 번호를 베끼지 않음)."""
    import cv2

    wiped.cap_b.set(cv2.CAP_PROP_POS_FRAMES, 4)
    wiped.cap_b.read()
    assert wiped.overlay_label().endswith("Frame: 1/24")
    assert wiped.overlay_label_b().endswith("Frame: 5/24")


def _arrow(player, qapp, key):
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QKeyEvent

    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    qapp.processEvents()


def test_arrows_move_b_with_a(wiped, qapp):
    """와이프 중 ←→·쉼표·마침표는 B도 A와 같은 프레임으로 (휠·슬라이더처럼 — 사용자 결정 2026-11-20; 예전엔 A만 움직여 B가 제자리)."""
    import cv2

    for key, number in ((Qt.Key_Right, 2), (Qt.Key_Period, 3), (Qt.Key_Left, 2), (Qt.Key_Comma, 1)):
        _arrow(wiped, qapp, key)
        assert wiped.overlay_label().endswith(f"Frame: {number}/24"), key
        assert wiped.overlay_label_b().endswith(f"Frame: {number}/24"), key
        assert int(wiped.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == int(wiped.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
    _arrow(wiped, qapp, Qt.Key_Right)
    shown = shown_image(wiped)
    assert abs(int(shown[5, -5].mean()) - int(wiped.frame_b[5, -5].mean())) <= 2  # 화면의 B 쪽 = 새로 읽은 B 그림


def test_arrows_without_wipe_leave_b_alone(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    """와이프가 꺼져 있으면(B를 연 채 와이프를 켜지 않음) ←→는 예전처럼 A만 — 보이지 않는 B를 읽지 않음."""
    import cv2

    from tests.conftest import write_test_video

    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "a.mov"), size=(640, 360)))
    assert player.open_file("B", write_test_video(str(tmp_path / "b.mov"), size=(640, 360)))
    before = int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES))
    _arrow(player, qapp, Qt.Key_Right)
    assert player.overlay_label().endswith("Frame: 2/24")
    assert int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == before


def test_rgb_wipe_shows_b_label_bottom_right(wiped):
    image = shown_image(wiped)
    height, width = image.shape[:2]
    left, top, right, bottom = b_box(wiped, width, height)
    edge = image[top + 1:bottom - 1, left + 1:left + 3]  # 상자 왼쪽 가장자리 안쪽 띠 — 글자가 닿지 않는 흰 자리
    assert (edge == 255).all()
    layout = overlay_layout(wiped.overlay_label(), width, height)
    assert (image[height - layout.margin_y, layout.margin_x - layout.pad] == 255).all()  # A 상자도 그대로 (왼쪽 아래)


@pytest.mark.parametrize("axes", ["x", "y", "xy"])
def test_b_label_is_not_cut_by_the_wipe_line(wiped, axes):
    """선을 오른쪽(아래) 끝 가까이 옮겨 B 상자가 A 쪽에 놓여도 B 글자는 그대로 보임 — 합성한 그림 위에 구움(A 글자처럼, 사용자 결정)."""
    wiped.wipeXButton.setChecked("x" in axes)
    wiped.wipeYButton.setChecked("y" in axes)
    wiped.videoWidget.wipe_position_x = 0.99
    wiped.videoWidget.wipe_position_y = 0.99
    wiped.update_frame()
    image = shown_image(wiped)
    height, width = image.shape[:2]
    left, top, right, bottom = b_box(wiped, width, height)
    assert (image[top + 1:bottom - 1, left + 1:left + 3] == 255).all()  # 상자 왼쪽 가장자리 안쪽 띠 — 선 왼쪽(A 쪽)인데도 흰색


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


# ---------------------------------------------------------------- Mac 네이티브 길 (IOSurface — 굽지 않고 아이템)

from tests.native_fakes import FAKE_HEIGHT, FAKE_WIDTH, fake_native_player  # noqa: E402,F401 (fake_native_player: fixture)


@pytest.fixture
def native_wiped(fake_native_player, qapp):  # noqa: F811
    """A·B 가짜 네이티브(GL 스트림 아이템) + 와이프·X·B 키 글자."""
    rig = fake_native_player(ab=True)
    rig.player.wipeXButton.setChecked(True)
    rig.player.toggle_overlay_text()
    qapp.processEvents()
    return rig


def test_native_b_label_item_right_aligned(native_wiped):
    player = native_wiped.player
    widget = player.videoWidget
    box, text = widget.overlay_b_box_item, widget.overlay_b_text_item
    assert box.isVisible() and text.text() == player.overlay_label_b()
    layout = overlay_layout(text.text(), FAKE_WIDTH, FAKE_HEIGHT)
    assert abs(box.rect().right() - (FAKE_WIDTH - layout.margin_x + layout.pad + 1)) <= 1  # A 상자(margin_x − pad에서 시작)의 거울
    assert box.rect().bottom() == widget.overlay_box_item.rect().bottom()  # 아래 끝은 A 상자와 같음
    assert widget.overlay_box_item.isVisible()  # A 글자도 그대로
    assert native_wiped.reads == []  # 네이티브 프레임의 픽셀을 파이썬에서 읽지 않음


@pytest.mark.parametrize("axes", ["x", "y", "xy"])
def test_native_b_label_is_not_clipped(native_wiped, axes):
    """B 글자 아이템은 와이프 선에 잘리지 않음(A 글자 아이템처럼 영상 위에 — 사용자 결정): 자르는 조상이 없고, 선을 끝 가까이 옮겨도 같은 자리에 보임."""
    from PyQt5.QtWidgets import QGraphicsItem

    player = native_wiped.player
    widget = player.videoWidget
    player.wipeXButton.setChecked("x" in axes)
    player.wipeYButton.setChecked("y" in axes)
    before = widget.overlay_b_box_item.rect()
    widget.wipe_position_x = 0.99
    widget.wipe_position_y = 0.99
    player.update_frame()
    box = widget.overlay_b_box_item
    assert box.isVisible() and box.rect() == before
    parent = box.parentItem()
    while parent is not None:
        assert not parent.flags() & QGraphicsItem.ItemClipsChildrenToShape
        parent = parent.parentItem()


def test_native_b_label_hidden_when_b_is_not_drawn(fake_native_player, qapp):  # noqa: F811
    rig = fake_native_player(ab=True, video_item="pixmap")  # 킬 스위치(픽스맵 길) — A만 그림
    rig.player.wipeXButton.setChecked(True)
    rig.player.toggle_overlay_text()
    assert not rig.player.videoWidget.overlay_b_box_item.isVisible()


def test_native_b_label_hidden_without_wipe_overlay_or_frame(native_wiped):
    player = native_wiped.player
    widget = player.videoWidget
    assert widget.overlay_b_box_item.isVisible()
    player.toggle_overlay_text()  # B 키 끔
    assert not widget.overlay_b_box_item.isVisible()
    player.toggle_overlay_text()
    player.wipeXButton.setChecked(False)  # 축이 없음 — B가 보이지 않음
    assert not widget.overlay_b_box_item.isVisible()
    player.wipeXButton.setChecked(True)
    assert widget.overlay_b_box_item.isVisible()
    widget.updateFrame(None, None)  # 빈 화면
    assert not widget.overlay_b_box_item.isVisible()
