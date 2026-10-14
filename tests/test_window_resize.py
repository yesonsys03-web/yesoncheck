"""Windows 버그 회귀 시험: 메인 창을 약 1142×845(논리 px)보다 작게 줄일 수 없던 문제.

원인 (컨트롤러가 macOS offscreen에서 측정): VideoPlayer.minimumSizeHint()가 1142×845 — resize(500, 400)을 해도
1142×845. Windows 150% 배율에서는 약 1713×1268 실제 픽셀로 1080p 화면보다 커서 창이 화면을 넘었다.
- 높이: 가운데 열(영상 열기·OCR·볼륨·FPS·작품 선택 …)을 세로로 쌓은 최소 높이(약 707~734)가 창 높이를 묶음
- 너비: 슬라이더 아래 정보 줄의 고정 너비(Current 200, Total 200, 재생 FPS 150) + 시간 + 파일 이름(긴 이름일수록 창이 넓어짐)

고치는 방법: 가운데 열을 세로 스크롤 영역(QScrollArea)에 넣고, 정보 줄 라벨은 글꼴로 정한 최소 너비 + 고정된 원하는
너비(숫자가 바뀌어도 흔들리지 않게)로, 좁아지면 정해진 순서로 줄이고 넘치는 글자는 …로 줄여 그림.
처음 창 크기는 예전처럼 1080×720 이상·레이아웃이 원하는 크기까지(화면 작업 영역 안으로) — 줄일 수만 있게 됨.

글꼴은 플랫폼·테마마다 다르다 (Windows CI의 글자는 Mac보다 훨씬 넓고, 밝은 테마(T 키)에서는 정보 줄 라벨이 16pt).
그래서 픽셀 숫자가 아니라 목표(900×600)와 '글자가 다 보임'으로 확인하고, 실패하면 _layout_report로 원인을 남긴다.
offscreen 화면은 800×600이라 '화면이 충분히 클 때'의 처음 크기는 가짜 화면(1920×1040)으로 확인한다.
"""

import os

import pytest
from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QHelpEvent
from PyQt5.QtWidgets import QApplication, QLabel, QScrollArea, QSplitter, QToolTip, QWidget

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

TARGET = QSize(900, 600)
LONG_NAME = "HH99_sc012_layout_retake_v003_final_check_for_director_review.mov"
DESIGNED_WIDTHS = {"labelFrameCount": 200, "labelTotalFrames": 200, "labelPlaybackFPS": 150}  # 예전 고정 너비
INFO_LABELS = ["filenameLabel", "labelFrameCount", "labelTotalFrames", "labelPlaybackFPS", "timeLabel"]


def _settle():
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def player(new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    _settle()
    return player


@pytest.fixture
def large_screen(monkeypatch):
    """화면 작업 영역이 1920×1040인 것처럼 (offscreen 화면은 800×600)."""
    real_screen = QApplication.primaryScreen()

    class LargeScreen:
        def availableGeometry(self):
            return QRect(0, 0, 1920, 1040)

        def __getattr__(self, name):
            return getattr(real_screen, name)

    monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: LargeScreen()))


def _open_video(player, folder, name):
    video = write_test_video(os.path.join(str(folder), "videos", name), frames=48)
    player.open_file("A", video)
    _settle()
    return video


def _big_numbers(player):
    """긴 영상의 숫자 (5자리 프레임) — 최소 너비에서도 다 보여야 하는 글자."""
    player.labelFrameCount.setText("Current: 12345")
    player.labelTotalFrames.setText("Total: 12345 (771F 09f)")
    _settle()


def _middle_scroll_area(player):
    """가운데 열(영상 열기·OCR 버튼이 있는 열)을 감싼 QScrollArea — 없으면 None."""
    widget = player.ocrAnalyzeButton.parentWidget()
    while widget is not None and not isinstance(widget, QScrollArea):
        widget = widget.parentWidget()
    return widget


def _main_splitter(player):
    return [s for s in player.centralWidget().findChildren(QSplitter) if s.orientation() == Qt.Horizontal][0]


def _widest(root, owner, count=4):
    rows = []
    for widget in root.findChildren(QWidget):
        if widget.isVisibleTo(owner) and widget.layout() is None:
            width = max(widget.minimumSizeHint().width(), widget.minimumWidth())
            text = widget.text() if isinstance(widget, (QLabel,)) or hasattr(widget, "setText") else ""
            rows.append((width, type(widget).__name__, str(text)[:24]))
    return sorted(rows, reverse=True)[:count]


def _layout_report(player):
    """실패 메시지용: 창·열·정보 줄 라벨의 크기와 글꼴 (Windows CI에서 무엇이 넓은지 알 수 있게)."""
    screen = QApplication.primaryScreen()
    lines = [
        f"window size={player.size()} min={player.minimumSizeHint()} hint={player.sizeHint()}",
        f"app font={QApplication.font().family()} pt={QApplication.font().pointSizeF()} "
        f"logicalDpi={screen.logicalDotsPerInch()} style={QApplication.style().objectName()}",
    ]
    splitter = _main_splitter(player)
    lines.append(f"main splitter sizes={splitter.sizes()} handle={splitter.handleWidth()}")
    for i in range(splitter.count()):
        pane = splitter.widget(i)
        lines.append(f"  pane {i} {type(pane).__name__} min={max(pane.minimumSizeHint().width(), pane.minimumWidth())} "
                     f"width={pane.width()} widest={_widest(pane, player)}")
    for name in INFO_LABELS:
        label = getattr(player, name)
        font = label.font()
        shown = label.displayed_text() if hasattr(label, "displayed_text") else label.text()
        lines.append(f"  {name}: width={label.width()} min={label.minimumSizeHint().width()} "
                     f"hint={label.sizeHint().width()} font={font.family()} px={font.pixelSize()} "
                     f"pt={font.pointSizeF()} fm.h={label.fontMetrics().height()} text={label.text()!r} shown={shown!r}")
    return "\n".join(lines)


def _assert_fits(size, player):
    assert size.width() <= TARGET.width() and size.height() <= TARGET.height(), _layout_report(player)


def test_minimum_size_fits_target(player):
    _assert_fits(player.minimumSizeHint(), player)


def test_minimum_size_fits_target_with_file_and_big_numbers(player, tmp_path):
    """파일 이름이 길고 숫자가 5자리여도 (Windows의 넓은 글꼴로도) 최소 크기 ≤ 900×600."""
    _open_video(player, tmp_path, LONG_NAME)
    _big_numbers(player)
    _assert_fits(player.minimumSizeHint(), player)


def test_resize_to_target_is_honored(player, tmp_path):
    _open_video(player, tmp_path, LONG_NAME)
    _big_numbers(player)
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET, _layout_report(player)


def test_frame_numbers_never_elide_at_minimum_width(player, tmp_path):
    """창이 최소 너비여도 Current는 숫자까지 다, Total은 적어도 'Total: 12345'까지 보임 (뒤의 '(…F …f)'는 줄 수 있음)."""
    _open_video(player, tmp_path, LONG_NAME)
    _big_numbers(player)
    player.resize(player.minimumSizeHint())
    _settle()
    report = _layout_report(player)
    assert player.labelFrameCount.displayed_text() == "Current: 12345", report
    assert player.labelTotalFrames.displayed_text().startswith("Total: 12345"), report
    for name in INFO_LABELS:
        assert getattr(player, name).isVisible(), name  # 줄어들어도 사라지지 않음


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


def _tooltip_shown_for(label):
    """라벨에 툴팁 이벤트(마우스를 올려 둠)를 보내고 뜬 툴팁 글자 (안 뜨면 "")."""
    QToolTip.hideText()
    _settle()
    center = label.rect().center()
    event = QHelpEvent(QEvent.ToolTip, center, label.mapToGlobal(center))
    QApplication.sendEvent(label, event)
    _settle()
    shown = QToolTip.text() if QToolTip.isVisible() else ""
    QToolTip.hideText()
    return shown


def test_info_labels_readable_at_target(player, tmp_path):
    _open_video(player, tmp_path, LONG_NAME)
    player.resize(TARGET)
    _settle()
    report = _layout_report(player)
    assert player.size() == TARGET, report
    assert player.labelFrameCount.displayed_text() == player.labelFrameCount.text(), report
    assert player.labelTotalFrames.displayed_text().startswith("Total: 48"), report
    for name in INFO_LABELS:
        label = getattr(player, name)
        assert label.isVisible() and label.width() > 0, report
        if label.displayed_text() != label.text():  # 줄여 그려지면 전체 글자는 툴팁으로 (파일 이름은 언제나 툴팁)
            assert _tooltip_shown_for(label) == label.text(), (name, report)


def test_tooltips_only_when_elided(player, tmp_path):
    """Total·재생 FPS·시간: 줄여 그려질 때만 전체 글자를 툴팁으로. 다 보이면 툴팁 없음."""
    _open_video(player, tmp_path, "sc012.mov")
    player.resize(player.sizeHint().expandedTo(QSize(1400, 800)))
    _settle()
    for name in ["labelTotalFrames", "labelPlaybackFPS", "timeLabel"]:
        label = getattr(player, name)
        assert label.displayed_text() == label.text(), _layout_report(player)
        assert _tooltip_shown_for(label) == "", name
    player.labelTotalFrames.setText("Total A: 12345 (771F 09f), B: 12345 (771F 09f)")  # 와이프 모드의 긴 글자
    player.resize(player.minimumSizeHint())
    _settle()
    for name in ["labelTotalFrames", "labelPlaybackFPS", "timeLabel"]:
        label = getattr(player, name)
        assert label.displayed_text() != label.text(), (name, _layout_report(player))
        assert _tooltip_shown_for(label) == label.text(), name


def test_long_file_name_is_elided_instead_of_widening(player, tmp_path):
    """예전에는 파일 이름이 길수록 창의 최소 너비가 늘었음 (긴 이름 → 창이 화면보다 넓어짐)."""
    _open_video(player, tmp_path, "sc012.mov")
    short_name_minimum = player.minimumSizeHint()
    _open_video(player, tmp_path, LONG_NAME)
    assert player.minimumSizeHint() == short_name_minimum
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET, _layout_report(player)
    label = player.filenameLabel
    assert label.text() == f"A: {LONG_NAME}"  # 전체 이름은 그대로 (복사·툴팁용)
    shown = label.displayed_text()
    assert shown != label.text() and shown.startswith("A") and shown.endswith("v"), shown  # 가운데를 줄임
    assert _tooltip_shown_for(label) == label.text()


def test_info_labels_get_designed_widths_when_there_is_room(player, tmp_path):
    """자리가 있으면 예전처럼: 숫자 라벨은 원하는 너비(예전 200·200·150 이상 — 글자가 그보다 넓은 글꼴이면 글자 너비)로,
    숫자가 바뀌어도 너비가 그대로이고 모든 글자가 다 보임."""
    _open_video(player, tmp_path, "sc012.mov")
    player.resize(player.sizeHint().expandedTo(QSize(1400, 800)))
    _settle()
    report = _layout_report(player)
    for name, designed in DESIGNED_WIDTHS.items():
        label = getattr(player, name)
        assert label.width() == label.sizeHint().width() >= designed, (name, report)
    for name in INFO_LABELS:
        label = getattr(player, name)
        assert label.displayed_text() == label.text(), (name, report)
    width = player.labelFrameCount.width()
    player.labelFrameCount.setText("Current: 99999")
    _settle()
    assert player.labelFrameCount.width() == width


def test_shrink_order_of_info_row():
    """줄이는 순서 (실제 라벨 대신 크기가 정해진 위젯으로 — 글꼴과 상관없이):
    1) 숫자 라벨의 빈 공간(원하는 너비 → 글자가 다 들어가는 너비) 2) 재생 FPS·시간 3) 파일 이름 4) Total의 '(…F …f)'.
    Current는 'Current: 00000'(= 최소 너비) 밑으로 줄지 않음."""
    from yesoncheck.window_layout import InfoRowLayout

    class Box(QWidget):
        def __init__(self, hint, comfortable, minimum, order):
            super().__init__()
            self._hint, self._comfortable, self._minimum, self.shrink_order = hint, comfortable, minimum, order

        def sizeHint(self):
            return QSize(self._hint, 30)

        def minimumSizeHint(self):
            return QSize(self._minimum, 30)

        def comfortable_width(self):
            return self._comfortable

    row = QWidget()
    layout = InfoRowLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    #          hint comfortable min order
    name = Box(300, 300, 30, 2)
    current = Box(200, 120, 120, 4)
    total = Box(200, 180, 100, 3)
    fps = Box(150, 110, 30, 1)
    time = Box(200, 200, 30, 1)
    for box in (name, current, total, fps, time):
        layout.addWidget(box)
    layout.setAlignment(time, Qt.AlignRight)

    assert layout.widths_for(1050) == [300, 200, 200, 150, 200]  # 자리가 있음
    assert layout.widths_for(1050 - 60) == [300, 180, 180, 130, 200]  # 1) 빈 공간 (똑같이 20씩, 각자 글자 너비까지)
    assert layout.widths_for(910 - 100) == [300, 120, 180, 60, 150]  # 2) FPS·시간 (똑같이 50씩)
    assert layout.widths_for(910 - 340) == [210, 120, 180, 30, 30]  # 3) 파일 이름
    assert layout.widths_for(910 - 340 - 180 - 50) == [30, 120, 130, 30, 30]  # 4) Total
    assert layout.widths_for(100) == [30, 120, 100, 30, 30]  # 최소보다 좁아도 최소 너비 밑으로는 안 감
    row.resize(1100, 30)
    row.show()
    _settle()
    assert time.geometry().right() == row.width() - 1  # 시간은 오른쪽 끝 (예전 addStretch 뒤)
    assert [w.x() for w in (name, current, total, fps)] == [0, 300, 500, 700]


def test_collapse_stage_comes_last():
    """재생 FPS·시간·파일 이름 칸은 맨 마지막 단계(Total까지 다 줄인 뒤)에만 너비 0까지 접힘 — 그래서 창의 최소 너비가
    작아지지만, 그 전까지는 칸이 남아 있음."""
    from yesoncheck.window_layout import InfoRowLayout

    class Box(QWidget):
        def __init__(self, hint, stages, minimum):
            super().__init__()
            self._hint, self._stages, self._minimum = hint, stages, minimum

        def sizeHint(self):
            return QSize(self._hint, 30)

        def minimumSizeHint(self):
            return QSize(self._minimum, 30)

        def shrink_stages(self):
            return self._stages

    row = QWidget()
    layout = InfoRowLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    time = Box(100, [(1, 20), (5, 0)], 0)  # 글자 → … (20) 다음, 마지막에 접힘
    total = Box(200, [(3, 120)], 120)
    for box in (time, total):
        layout.addWidget(box)
    assert layout.minimumSize().width() == 120
    assert layout.widths_for(300 - 80) == [20, 200]  # 시간 칸 먼저 (…만 남음)
    assert layout.widths_for(300 - 80 - 50) == [20, 150]  # 그다음 Total
    assert layout.widths_for(300 - 80 - 80 - 10) == [10, 120]  # Total이 최소가 된 뒤에야 접힘
    assert layout.widths_for(120) == [0, 120]


def test_light_theme_does_not_elide_at_normal_size(player, tmp_path):
    """밝은 테마(T 키)에서는 정보 줄 라벨이 더 큰 글꼴(16pt)이 됨 → 그 글꼴의 원하는 너비로 다시 재고, 창이 원하는
    크기면 글자를 줄이지 않음 (예전에 1px 넘친다고 '…'로 바꾸던 문제 포함)."""
    _open_video(player, tmp_path, "sc012.mov")
    player.toggle_theme()
    _settle()
    player.resize(player.sizeHint().expandedTo(QSize(1400, 800)))
    _settle()
    report = _layout_report(player)
    for name in INFO_LABELS:
        label = getattr(player, name)
        assert label.displayed_text() == label.text(), (name, report)
    player.toggle_theme()  # 어두운 테마로 돌아와도 그대로
    _settle()
    for name in INFO_LABELS:
        label = getattr(player, name)
        assert label.displayed_text() == label.text(), (name, _layout_report(player))


def test_elide_only_when_ink_overflows(qapp):
    """QLabel 글자 영역에 잉크가 들어가면 QLabel 그대로 (끝의 글자 간격 때문에 1px 넘친다고 줄이지 않음),
    안 들어가도 테두리 안이면 글자를 왼쪽으로 옮겨 다 그림, 그래도 넘칠 때만 '…'."""
    from yesoncheck.window_layout import TIGHT_INSET, ElidedLabel

    label = ElidedLabel(Qt.ElideRight)
    label.setStyleSheet("QLabel { padding: 10px; border: 1px solid black; }")
    label.setText("Total: 48 (3F 00f)")
    label.ensurePolished()
    left, right = label.text_insets()
    ink = label.fontMetrics().tightBoundingRect(label.text())
    ink_right = ink.x() + ink.width()
    label.resize(left + right + ink_right, 40)  # 잉크는 QLabel 영역에 다 들어감 (글자 간격은 넘칠 수 있음)
    assert label.displayed_text() == label.text()
    assert label._placement()[2]  # QLabel 그대로 그림
    label.resize(2 * TIGHT_INSET + ink_right + 2, 40)  # 안쪽 여백까지 쓰면 들어감
    assert label.displayed_text() == label.text()
    assert not label._placement()[2] and label._placement()[1] < left  # 왼쪽으로 옮겨 그림
    label.resize(2 * TIGHT_INSET + ink_right - 3, 40)
    assert label.displayed_text().endswith("…")


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


def test_startup_size_on_large_screen_is_the_polished_layout_size(new_player, dialogs, tmp_path, large_screen):
    """화면이 충분하면 처음 창 = max(1080×720, 스타일·글꼴이 적용된 레이아웃의 원하는 크기): 가운데 열이 스크롤 없이
    다 보이고 정보 줄 라벨이 원하는 너비 (Windows에서는 스타일 적용 전 크기로 재서 9px 낮았음)."""
    player = new_player(make_config(str(tmp_path), {}))
    startup = player.size()
    assert startup.width() >= 1080 and startup.height() >= 720, startup
    player.show()
    _settle()
    report = _layout_report(player)
    assert player.size() == startup, report
    assert player.size() == player.sizeHint().expandedTo(QSize(1080, 720)), report
    assert player.initial_geometry == player.geometry()  # 동영상 전용 전체화면을 끝내면 이 크기로 돌아옴
    assert _middle_scroll_area(player).verticalScrollBar().maximum() == 0, report
    for name, designed in DESIGNED_WIDTHS.items():
        label = getattr(player, name)
        assert label.width() == label.sizeHint().width() >= designed, (name, report)
    splitter = _main_splitter(player)
    assert splitter.sizes()[0] >= 200 and splitter.sizes()[1] >= 220, report  # 예전 처음 열 너비 (setSizes 200·220)


def test_startup_size_on_offscreen_screen(new_player, dialogs, tmp_path):
    """offscreen 화면(800×600)처럼 작으면 작업 영역 안으로 줄이되 최소 크기보다 작게는 안 함."""
    from yesoncheck.window_layout import STARTUP_FRAME_MARGINS

    player = new_player(make_config(str(tmp_path), {}))
    usable = QApplication.primaryScreen().availableGeometry().marginsRemoved(STARTUP_FRAME_MARGINS)
    minimum = player.minimumSizeHint()
    size = player.size()
    assert size.width() <= max(usable.width(), minimum.width()), (size, usable, minimum)
    assert size.height() <= max(usable.height(), minimum.height()), (size, usable, minimum)


def test_thumbnail_mode_keeps_look_but_does_not_block_shrinking(player, tmp_path):
    """썸네일 모드: 예전처럼 사이드바가 2배 너비로 시작하지만 고정 너비가 아님 → 창을 900×600으로 줄일 수 있음."""
    player.resize(1400, 850)
    _settle()
    player.initialize_sidebar_width()
    default = player.default_sidebar_width
    player.switch_to_thumbnail_mode()
    _settle()
    report = _layout_report(player)
    assert abs(player.sidebar.width() - 2 * default) <= 2, (player.sidebar.width(), default, report)
    assert player.sidebar.maximumWidth() > 10000, report  # 고정 너비가 아님
    player.resize(TARGET)
    _settle()
    assert player.size() == TARGET, _layout_report(player)
    assert player.sidebar.width() >= player.sidebar.minimumWidth() > 0
    player.resize(1400, 850)
    _settle()
    player.switch_to_list_mode()
    _settle()
    assert abs(player.sidebar.width() - default) <= 2, (player.sidebar.width(), default, _layout_report(player))
    assert player.sidebar.maximumWidth() > 10000 and player.sidebar.minimumWidth() == 0
