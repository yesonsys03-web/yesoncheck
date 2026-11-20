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

from tests.native_fakes import fake_native_player  # noqa: E402,F401 (fake_native_player: fixture)

NATIVE_WIDTH, NATIVE_HEIGHT = 3840, 2160  # 가짜 기본 크기(16×8)에서는 짧은 이름도 두 글자가 겹쳐 B가 한 줄 위로 올라감 — 4K(행을 함께 쓰는 가짜 프레임)로


@pytest.fixture
def native_wiped(fake_native_player, qapp):  # noqa: F811
    """A·B 가짜 네이티브(GL 스트림 아이템) + 와이프·X·B 키 글자."""
    rig = fake_native_player(ab=True, size=(NATIVE_WIDTH, NATIVE_HEIGHT))
    rig.player.wipeXButton.setChecked(True)
    rig.player.toggle_overlay_text()
    qapp.processEvents()
    return rig


def test_native_b_label_item_right_aligned(native_wiped):
    player = native_wiped.player
    widget = player.videoWidget
    box, text = widget.overlay_b_box_item, widget.overlay_b_text_item
    assert box.isVisible() and text.text() == player.overlay_label_b()
    layout = overlay_layout(text.text(), NATIVE_WIDTH, NATIVE_HEIGHT)
    assert abs(box.rect().right() - (NATIVE_WIDTH - layout.margin_x + layout.pad + 1)) <= 1  # A 상자(margin_x − pad에서 시작)의 거울
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


def test_native_b_label_hidden_when_b_is_not_given(native_wiped):
    """B를 넘기지 않는 길(OCR 검토 창이 열린 드래그 — _minimal_preview_seek)에서는 네이티브 길도 B 글자를 숨김: B 자리가 검정인데 B 캡처의
    옛 번호를 보이지 않게(RGB 길의 test_no_labels_drawn_by_the_widget_when_b_is_not_given과 같은 규칙). A 글자 아이템은 그대로."""
    player = native_wiped.player
    widget = player.videoWidget
    assert widget.overlay_b_box_item.isVisible()
    widget.updateFrame(player.frame_a, None)
    assert not widget.overlay_b_box_item.isVisible()
    assert widget.overlay_box_item.isVisible()
    player.update_frame()
    assert widget.overlay_b_box_item.isVisible()


@pytest.mark.parametrize("axes", ["x", "y", "xy"])
def test_a_label_is_not_cut_by_the_wipe_line(wiped, axes):
    """A 글자도 와이프 선에 잘리지 않음 — CPU 길은 A 그림에 구운 글자를 B가 덮었음(사용자 보고 2026-11-20: 선을 A 글자 위로 옮기면 A 글자가
    잘림). 합성한 그림 위에 다시 구움(Mac 네이티브 길의 A 글자 아이템은 원래 잘리지 않음)."""
    wiped.wipeXButton.setChecked("x" in axes)
    wiped.wipeYButton.setChecked("y" in axes)
    wiped.videoWidget.wipe_position_x = 0.05  # 선이 A 글자의 왼쪽 — A 글자 대부분이 B 쪽
    wiped.videoWidget.wipe_position_y = 0.05
    wiped.update_frame()
    image = shown_image(wiped)
    height, width = image.shape[:2]
    layout = overlay_layout(wiped.overlay_label(), width, height)
    y = height - layout.margin_y
    right = layout.margin_x + layout.text_width + layout.pad
    band = image[y - layout.text_height - layout.pad + 1:y + max(layout.pad, layout.baseline) - 1, right - 2:right]
    assert (band == 255).all()  # A 상자의 오른쪽 가장자리 안쪽 띠 — B 쪽인데도 흰색


def test_a_label_pixels_on_the_a_side_are_unchanged_by_the_redraw(wiped):
    """다시 굽기는 같은 자리·같은 글·같은 방식이라 A 쪽의 A 글자 픽셀은 바뀌지 않음 — 와이프 없이 보이던 그림과 같음."""
    wiped.videoWidget.wipe_position_x = 0.95  # A 글자 전부가 A 쪽
    wiped.update_frame()
    with_wipe = shown_image(wiped)
    height, width = with_wipe.shape[:2]
    layout = overlay_layout(wiped.overlay_label(), width, height)
    expected = wiped.prepare_frame_for_display(wiped.frame_a)  # A 그림에 구운 A 글자 (예전 그대로)
    top = height - layout.margin_y - layout.text_height - layout.pad
    right = layout.margin_x + layout.text_width + layout.pad + 1
    assert np.array_equal(with_wipe[top:, :right], expected[top:, :right])


# ---------------------------------------------------------------- 리뷰에서 찾은 것 (2026-11-20)

LONG_A = "File: EP101_SC050_LAYOUT_BACKGROUND_PAINT_TK1.mov, Frame: 12/480"
LONG_B = "File: EP101_SC050_LAYOUT_BACKGROUND_PAINT_TK2.mov, Frame: 12/480"


def test_label_lift_only_when_the_labels_would_overlap():
    """이름이 길면 오른쪽 아래의 B 글자가 왼쪽 아래 A 글자의 끝(Frame: n/N)을 덮었음 — 겹칠 때만 B를 한 줄 위로 (사용자 결정)."""
    from yesoncheck.overlay_text_layout import label_lift, overlay_label_box

    short_a, short_b = "File: a_tk1.mov, Frame: 1/24", "File: b_tk2.mov, Frame: 1/24"
    assert label_lift(short_a, short_b, 1920, 1080) == 0
    assert label_lift(None, short_b, 1920, 1080) == 0
    lift = label_lift(LONG_A, LONG_B, 1920, 1080)
    assert lift > 0
    _layout, a = overlay_label_box(LONG_A, 1920, 1080, "left")
    _layout, b = overlay_label_box(LONG_B, 1920, 1080, "right", lift=lift)
    assert b.bottom < a.top  # 올린 B 상자는 A 상자보다 위 — 겹치지 않음
    assert label_lift(short_a, short_b, 1080, 1920) > 0  # 세로 영상은 짧은 이름도 겹침


def test_long_names_lift_b_above_a(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    from tests.conftest import write_test_video
    from yesoncheck.overlay_text_layout import label_lift, overlay_label_box

    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "EP101_SC050_LAYOUT_BACKGROUND_PAINT_TK1.mov"), size=(640, 360)))
    assert player.open_file("B", write_test_video(str(tmp_path / "EP101_SC050_LAYOUT_BACKGROUND_PAINT_TK2.mov"), size=(640, 360)))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(1)
    player.toggle_overlay_text()
    image = shown_image(player)
    height, width = image.shape[:2]
    text_a, text_b = player.overlay_label(), player.overlay_label_b()
    lift = label_lift(text_a, text_b, width, height)
    assert lift > 0
    _layout, a = overlay_label_box(text_a, width, height, "left")
    _layout, b = overlay_label_box(text_b, width, height, "right", lift=lift)
    assert (image[a.top + 1:a.bottom, a.right - 2:a.right] == 255).all()  # A 상자의 오른쪽 끝(Frame: n/N 쪽)이 그대로
    assert (image[b.top + 1:b.bottom, b.left + 1:b.left + 3] == 255).all()  # B 상자는 한 줄 위에


def test_native_long_names_lift_b_above_a(native_wiped, monkeypatch):
    player = native_wiped.player
    monkeypatch.setattr(player, "overlay_label", lambda: LONG_A)
    monkeypatch.setattr(player, "overlay_label_b", lambda: LONG_B)
    player.update_frame()
    widget = player.videoWidget
    a, b = widget.overlay_box_item.rect(), widget.overlay_b_box_item.rect()
    assert widget.overlay_box_item.isVisible() and widget.overlay_b_box_item.isVisible()
    assert b.bottom() < a.top()  # 겹치면 B를 A 줄 위로
    monkeypatch.setattr(player, "overlay_label", lambda: "File: a.mov, Frame: 1/24")
    monkeypatch.setattr(player, "overlay_label_b", lambda: "File: b.mov, Frame: 1/24")
    player.update_frame()
    assert widget.overlay_b_box_item.rect().bottom() == widget.overlay_box_item.rect().bottom()  # 짧으면 같은 줄


class _CountingCapture:
    """B 캡처를 감싸 set·read 횟수를 셈 (cv2.VideoCapture에는 속성을 달 수 없음)."""

    def __init__(self, cap):
        self._cap = cap
        self.sets = 0
        self.reads = 0

    def set(self, prop, value):
        self.sets += 1
        return self._cap.set(prop, value)

    def read(self):
        self.reads += 1
        return self._cap.read()

    def __getattr__(self, name):
        return getattr(self._cap, name)


def test_arrow_reads_b_in_order_without_seeking(wiped, qapp):
    """와이프 중 →: B가 바로 앞 장에 있으면 탐색(set) 없이 다음 장을 읽음 — cv2의 set은 같은 자리여도 키프레임부터 다시 디코드해
    느렸음(리뷰 실측 키 한 번 93ms 대 18ms). ←(뒤로)는 탐색이 필요함. 화면의 B 쪽은 새로 읽은 그 장의 그림(시험 영상의 i번째 장 = 회색 10·i)."""
    counting = wiped.cap_b = _CountingCapture(wiped.cap_b)
    _arrow(wiped, qapp, Qt.Key_Right)
    assert (counting.sets, counting.reads) == (0, 1)
    assert abs(int(shown_image(wiped)[5, -5].mean()) - 10) <= 4  # B의 1번 장(회색 10)
    _arrow(wiped, qapp, Qt.Key_Right)
    assert (counting.sets, counting.reads) == (0, 2)
    assert abs(int(shown_image(wiped)[5, -5].mean()) - 20) <= 4
    _arrow(wiped, qapp, Qt.Key_Left)
    assert counting.sets == 1 and counting.reads == 3
    assert abs(int(shown_image(wiped)[5, -5].mean()) - 10) <= 4


def test_a_label_redraw_keeps_a_annotations(wiped):
    """A 글자를 합성 위에 다시 구울 때 A 쪽은 건드리지 않음 — 글자 상자 안의 A 주석이 덮이지 않음(리뷰: 통째로 다시 구우면 주석이 가려짐)."""
    layout = overlay_layout(wiped.overlay_label(), 640, 360)
    box_y = 1 - (layout.margin_y + layout.text_height / 2) / 360  # 글자 상자 가운데 높이
    wiped.annotation_store.add(0, {"type": "rect", "norm_x1": 0.0, "norm_y1": box_y - 0.02, "norm_x2": 0.3, "norm_y2": box_y + 0.02,
                                   "color": "#ff3333", "stroke_width": 2})
    wiped.videoWidget.wipe_position_x = 0.95  # A 글자 전부가 A 쪽
    wiped.update_frame()
    image = shown_image(wiped)
    expected = wiped.prepare_frame_for_display(wiped.frame_a)  # A 그림 = 글자 + 그 위에 주석 (예전 그대로)
    b_left = b_box(wiped, 640, 360)[0]  # 오른쪽 아래 B 글자 상자(A 쪽 위에 그려짐)의 왼쪽 — 그 앞까지가 A 그림 그대로여야 함
    assert b_left < int(640 * 0.95)
    assert np.array_equal(image[:, :b_left], expected[:, :b_left])
    red = (expected[..., 0] > 200) & (expected[..., 1] < 100) & (expected[..., 2] < 100)
    assert red[:, :b_left].sum() > 100  # 시험이 주석을 실제로 그렸음 (글자 상자 안의 빨간 사각형)


def test_no_labels_drawn_by_the_widget_when_b_is_not_given(wiped):
    """B를 넘기지 않는 길(슬라이더 드래그 미리보기·OCR 검토 창이 열린 드래그 — frame_b None)에서는 위젯이 글자를 그리지 않음:
    B 쪽은 검정인데 B 캡처가 움직이지 않은 옛 번호를 보였음(리뷰)."""
    frame = np.zeros((360, 640, 3), np.uint8)  # 글자를 굽지 않은 A (그 길처럼)
    wiped.videoWidget.updateFrame(frame, None)
    image = shown_image(wiped)
    assert not (image == 255).all(axis=2).any()


# ---------------------------------------------------------------- 와이프 중 슬라이더 드래그의 B (사용자 결정 2026-11-20)

def _drag(player, frame_idx, total=24, overlay=False):
    player.is_dragging = True
    if overlay:
        player._overlay_slider_preview_seek(frame_idx, total)
    else:
        player._quick_preview_seek(frame_idx, total)


def _b_side_gray(player):
    return int(shown_image(player)[5, -5].mean())


@pytest.mark.parametrize("overlay", [False, True], ids=["main-slider", "overlay-slider"])
def test_drag_reads_small_b_along(wiped, overlay):
    """1920×1080 이하의 B는 끄는 동안에도 A와 같은 장으로 읽어 보여 줌 — 예전에는 B 자리가 검게 깜빡였음(시험 영상의 i번째 장 = 회색 10·i)."""
    import cv2

    _drag(wiped, 10, overlay=overlay)
    assert int(wiped.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == 11 and wiped.frame_b is not None
    assert abs(_b_side_gray(wiped) - 100) <= 4
    _drag(wiped, 15, overlay=overlay)
    assert abs(_b_side_gray(wiped) - 150) <= 4


def test_drag_cache_hit_still_reads_small_b(wiped):
    """A가 캐시에 있는 자리로 돌아와도(캐시 적중 — A를 읽지 않음) B는 그 장으로."""
    _drag(wiped, 15)
    _drag(wiped, 5)
    _drag(wiped, 15)  # A는 캐시에서
    assert abs(_b_side_gray(wiped) - 150) <= 4


def test_drag_keeps_large_b_picture_until_release(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    """1920×1080보다 큰 B(4K 등)는 끄는 동안 끄기 전 그림 그대로(검게 깜빡이지 않음 — 읽으면 드래그가 느려짐), 놓으면 A와 같은 장으로."""
    import cv2

    from tests.conftest import write_test_video

    player = new_player(make_config(str(tmp_path), {}))
    size = (2048, 1152)  # 1920×1080보다 큼
    assert player.open_file("A", write_test_video(str(tmp_path / "a_big.mov"), size=size))
    assert player.open_file("B", write_test_video(str(tmp_path / "b_big.mov"), size=size))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(6)  # A·B 5번 장(회색 50)
    before = player.frame_b
    _drag(player, 15)
    assert player.frame_b is before and int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == 6  # B는 읽지 않음
    assert abs(_b_side_gray(player) - 50) <= 4  # 검정이 아니라 끄기 전 B 그림
    maximum = player.positionScroll.maximum()
    player.positionScroll.blockSignals(True)
    player.positionScroll.setValue(round(15 / 23 * maximum))
    player.positionScroll.blockSignals(False)
    player.sync_audio_on_release()  # 놓음
    player.is_dragging = False
    assert int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
    assert abs(_b_side_gray(player) - 150) <= 4
