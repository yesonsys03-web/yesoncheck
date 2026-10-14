"""Windows 버그 회귀 시험: 메인 창을 약 1142×845(논리 px)보다 작게 줄일 수 없던 문제.

원인 (컨트롤러가 macOS offscreen에서 측정): VideoPlayer.minimumSizeHint()가 1142×845 — resize(500, 400)을 해도
1142×845. Windows 150% 배율에서는 약 1713×1268 실제 픽셀로 1080p 화면보다 커서 창이 화면을 넘었다.
- 높이: 가운데 열(영상 열기·OCR·볼륨·FPS·작품 선택 …)을 세로로 쌓은 최소 높이(약 707~734)가 창 높이를 묶음
- 너비: 슬라이더 아래 정보 줄의 고정 너비(Current 200, Total 200, 재생 FPS 150) + 시간 + 파일 이름(긴 이름일수록 창이 넓어짐)

고치는 방법: 가운데 열을 세로 스크롤 영역(QScrollArea)에 넣고, 정보 줄 라벨은 작은 최소 너비 + 고정된 원하는 너비
(숫자가 바뀌어도 흔들리지 않게)로, 좁아지면 글자를 …로 줄여 그림 (파일 이름은 가운데를 줄임).
처음 창 크기는 예전처럼 1080×720 이상·레이아웃이 원하는 크기까지(화면 작업 영역 안으로) — 줄일 수만 있게 됨.

offscreen 화면은 800×600이라 '화면이 충분히 클 때'의 처음 크기는 가짜 화면(1920×1040)으로 확인한다.
"""

import os

import pytest
from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtWidgets import QApplication, QScrollArea, QSplitter

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

TARGET = QSize(900, 600)
LONG_NAME = "HH99_sc012_layout_retake_v003_final_check_for_director_review.mov"


def _settle():
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def player(new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    _settle()
    return player


def _open_video(player, folder, name):
    video = write_test_video(os.path.join(str(folder), "videos", name), frames=48)
    player.open_file("A", video)
    _settle()
    return video


def _middle_scroll_area(player):
    """가운데 열(영상 열기·OCR 버튼이 있는 열)을 감싼 QScrollArea — 없으면 None."""
    widget = player.ocrAnalyzeButton.parentWidget()
    while widget is not None and not isinstance(widget, QScrollArea):
        widget = widget.parentWidget()
    return widget


def test_minimum_size_fits_target(player):
    hint = player.minimumSizeHint()
    assert hint.width() <= TARGET.width() and hint.height() <= TARGET.height(), hint


def test_resize_to_target_is_honored(player):
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET


def test_middle_column_is_in_vertical_scroll_area(player):
    area = _middle_scroll_area(player)
    assert area is not None, "가운데 열이 QScrollArea 안에 없음"
    assert isinstance(area.parentWidget(), QSplitter)  # 메인 스플리터의 한 칸
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert area in player.control_widgets  # V 키·동영상 전용 전체화면에서 열 전체가 숨겨지도록

    player.resize(TARGET)
    _settle()
    # 창이 낮아도 기능은 그대로: 맨 아래 작품 선택 콤보까지 스크롤로 닿을 수 있음 (가려지지만 사라지지 않음)
    assert area.verticalScrollBar().maximum() > 0
    assert player.jobComboBox.isVisibleTo(player)
    area.ensureWidgetVisible(player.jobComboBox)
    _settle()
    top_left = player.jobComboBox.mapTo(area.viewport(), player.jobComboBox.rect().topLeft())
    assert area.viewport().rect().contains(top_left)
    # 세로 스크롤바가 생겨도 내용이 오른쪽에서 잘리지 않음 (가로 스크롤 없음)
    assert area.widget().width() <= area.viewport().width()
    assert area.widget().width() >= area.widget().minimumSizeHint().width()


def test_info_labels_readable_at_target(player, tmp_path):
    _open_video(player, tmp_path, "sc012.mov")
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET
    for label, prefix in [(player.labelFrameCount, "Current:"), (player.labelTotalFrames, "Total:"),
                          (player.timeLabel, "00:00:00"), (player.filenameLabel, "A: ")]:
        assert label.isVisible() and label.width() > 0, label.text()
        assert label.text().startswith(prefix)
        assert label.displayed_text().startswith(prefix), (label.text(), label.displayed_text(), label.width())
    assert player.labelPlaybackFPS.isVisible() and player.labelPlaybackFPS.width() > 0


def test_long_file_name_is_elided_instead_of_widening(player, tmp_path):
    """예전에는 파일 이름이 길수록 창의 최소 너비가 늘었음 (긴 이름 → 창이 화면보다 넓어짐)."""
    _open_video(player, tmp_path, "sc012.mov")
    short_name_minimum = player.minimumSizeHint()
    _open_video(player, tmp_path, LONG_NAME)
    assert player.minimumSizeHint() == short_name_minimum
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET
    label = player.filenameLabel
    assert label.text() == f"A: {LONG_NAME}"  # 전체 이름은 그대로 (복사·툴팁용)
    shown = label.displayed_text()
    assert "…" in shown and shown.startswith("A: ") and shown.endswith("mov"), shown  # 가운데를 줄임
    assert label.toolTip() == label.text()


def test_info_labels_keep_todays_widths_when_there_is_room(player, tmp_path):
    """예전처럼 보이게: 자리가 있으면 Current·Total 200, 재생 FPS 150 — 숫자가 바뀌어도 너비가 그대로."""
    _open_video(player, tmp_path, "sc012.mov")
    player.resize(1600, 900)
    _settle()
    widths = [player.labelFrameCount.width(), player.labelTotalFrames.width(), player.labelPlaybackFPS.width()]
    assert widths == [200, 200, 150]
    player.labelFrameCount.setText("Current: 123456789")
    _settle()
    assert player.labelFrameCount.width() == 200
    # 파일 이름이 다 보이고 (줄이지 않음) 시간은 오른쪽 끝
    assert player.filenameLabel.displayed_text() == player.filenameLabel.text()
    assert player.timeLabel.displayed_text() == player.timeLabel.text()


def test_numbers_give_up_empty_space_before_file_name_and_time(player, tmp_path):
    """줄이 조금 모자라면 숫자 라벨의 빈 공간부터 줄어듦 — 파일 이름·시간은 글자가 다 보임.
    (QHBoxLayout은 모든 라벨에서 똑같이 빼서 글자가 꽉 찬 시간·파일 이름이 먼저 잘림)"""
    _open_video(player, tmp_path, "HH99_102_sc012_v003.mov")
    player.resize(1273, 872)  # 큰 화면에서의 처음 크기 정도
    _settle()
    labels = [player.labelFrameCount, player.labelTotalFrames, player.labelPlaybackFPS]
    assert any(label.width() < label.sizeHint().width() for label in labels)  # 실제로 모자란 상황
    for label in labels + [player.filenameLabel, player.timeLabel]:
        assert label.displayed_text() == label.text(), (label.text(), label.displayed_text(), label.width())


def test_startup_geometry_on_large_screen():
    from yesoncheck.window_layout import startup_geometry

    screen = QRect(0, 0, 1920, 1040)
    # 레이아웃이 원하는 크기가 더 크면 그 크기, 아니면 예전 기본값 1080×720 — 위치도 예전처럼 (100, 100)
    assert startup_geometry(QSize(1262, 872), QSize(800, 450), screen) == QRect(100, 100, 1262, 872)
    assert startup_geometry(QSize(900, 600), QSize(800, 450), screen) == QRect(100, 100, 1080, 720)


def test_startup_geometry_fits_small_screen():
    from yesoncheck.window_layout import STARTUP_FRAME_MARGINS, startup_geometry

    screen = QRect(0, 0, 1280, 693)  # 1080p 화면 150% 배율의 작업 영역 (논리 px)
    usable = screen.marginsRemoved(STARTUP_FRAME_MARGINS)
    rect = startup_geometry(QSize(1262, 872), QSize(800, 450), screen)
    assert usable.contains(rect), (rect, usable)
    assert rect.width() == 1262 and rect.height() == usable.height()
    # 최소 크기보다 작은 화면이면 최소 크기 (그 이상은 줄일 수 없음), 작업 영역의 왼쪽 위에
    tiny = QRect(0, 0, 640, 400)
    rect = startup_geometry(QSize(1262, 872), QSize(800, 450), tiny)
    assert rect.size() == QSize(800, 450)
    assert rect.topLeft() == tiny.marginsRemoved(STARTUP_FRAME_MARGINS).topLeft()


def test_startup_size_on_large_screen_shows_whole_middle_column(new_player, dialogs, tmp_path, monkeypatch):
    """화면이 충분하면 처음 창은 1080×720 이상이고 가운데 열이 스크롤 없이 다 보임 (예전 모습)."""
    real_screen = QApplication.primaryScreen()

    class LargeScreen:
        def availableGeometry(self):
            return QRect(0, 0, 1920, 1040)

        def __getattr__(self, name):
            return getattr(real_screen, name)

    monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: LargeScreen()))
    player = new_player(make_config(str(tmp_path), {}))
    startup = player.size()
    assert startup.width() >= 1080 and startup.height() >= 720, startup
    assert player.initial_geometry == player.geometry()  # 동영상 전용 전체화면을 끝내면 이 크기로 돌아옴
    player.show()
    _settle()
    assert player.size() == startup
    assert _middle_scroll_area(player).verticalScrollBar().maximum() == 0


def test_startup_size_on_offscreen_screen(new_player, dialogs, tmp_path):
    """offscreen 화면(800×600)처럼 작으면 작업 영역 안으로 줄이되 최소 크기보다 작게는 안 함."""
    from yesoncheck.window_layout import STARTUP_FRAME_MARGINS

    player = new_player(make_config(str(tmp_path), {}))
    usable = QApplication.primaryScreen().availableGeometry().marginsRemoved(STARTUP_FRAME_MARGINS)
    minimum = player.minimumSizeHint()
    size = player.size()
    assert size.width() <= max(usable.width(), minimum.width()), (size, usable, minimum)
    assert size.height() <= max(usable.height(), minimum.height()), (size, usable, minimum)
