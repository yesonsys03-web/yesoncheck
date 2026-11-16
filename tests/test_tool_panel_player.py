"""도구 패널을 단 창 — 진짜 VideoPlayer(화면 없이): 가운데 열이 없어지고 주석·OCR이 뷰어 오른쪽 패널로.

2026-11-16 UI 개편 PR 2. 메인 스플리터는 [사이드바 | 영상 | 도구 패널], 패널은 열었을 때만 보인다(한 번에 한 쪽).
여는 길: 재생 줄의 주석·OCR 토글, N 키(마지막에 쓰던 쪽 — 처음이면 주석), 패널의 닫기 단추.
지키는 것: 패널을 여닫아도 사이드바 폭과 재생 줄은 그대로(폭은 영상 칸에서 가져오고 돌려줌), 닫아도 주석 모드·OCR
입력값은 그대로, V 키·영상만 전체 화면에서 되돌아오면 열려 있던 쪽은 그대로·닫혀 있던 패널은 나타나지 않음.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QToolButton

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import tool_panel
from yesoncheck.tool_panel import ToolPanel


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def shown(player, qapp):
    player.resize(1400, 860)
    player.show()
    QApplication.setActiveWindow(player)
    QTest.qWait(250)  # show()가 걸어 둔 일(100ms 뒤 force_focus, 200ms 뒤 사이드바 폭)이 지난 뒤부터
    return player


def press(player, key, text=""):
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))


def sizes(player):
    return player.mainSplitter.sizes()


def click(button, qapp):
    QTest.mouseClick(button, Qt.LeftButton)
    qapp.processEvents()


def panel_state(player):
    bar = player.transportBar
    return (player.tool_panel_key(), not player.toolPanel.isHidden(), bar.annotationButton.isChecked(),
            bar.ocrButton.isChecked())


# ---------------------------------------------------------------- 창 구조

def test_splitter_is_sidebar_video_and_a_hidden_tool_panel(player):
    splitter = player.mainSplitter
    assert splitter.count() == 3
    assert splitter.widget(0) is player.control_widgets[0]
    assert splitter.widget(1).isAncestorOf(player.videoWidget)
    assert splitter.widget(2) is player.toolPanel and isinstance(player.toolPanel, ToolPanel)
    assert player.toolPanel.isHidden() and player.tool_panel_key() is None
    assert player.toolPanel.keys() == ("annotation", "ocr")
    assert not splitter.isCollapsible(2)  # 손잡이를 끌어 0폭으로 접을 수 없음 — 닫기는 단추·N 키로


def test_middle_column_and_its_boxes_are_gone(player):
    for gone in ("middleScrollArea", "middle_panel_visible", "toggle_middle_panel", "apply_middle_panel_state",
                 "playSelectedButton"):
        assert not hasattr(player, gone), gone
    assert not [b for b in player.findChildren(QPushButton) if b.objectName() == "collapsibleToggle"]
    texts = {button.text() for button in player.findChildren(QPushButton)}
    for old in ("Open Video A", "Open Video B", "X-Axis Wipe", "Y-Axis Wipe", "Play Selected", "Select Folder",
                "Add Bookmark", "Bookmarks", "작품 경로 관리"):
        assert old not in texts, old


def test_video_has_the_room_until_a_panel_opens(shown):
    side, video, panel = sizes(shown)
    assert panel == 0 and video > side > 0
    splitter = shown.mainSplitter
    assert side + video + splitter.handleWidth() == splitter.width()


def test_control_widgets_are_the_sidebar_the_bar_and_the_slider(player):
    """V 키·전체 화면이 숨기고 되돌리는 것 — 도구 패널은 넣지 않음(재생 줄을 따라 숨고 나타남: 닫혀 있던 패널이
    되돌릴 때 잠깐이라도 보이면 안 됨)."""
    assert player.control_widgets == [player.mainSplitter.widget(0), player.transportBar, player.positionScroll]


# ---------------------------------------------------------------- 여닫기

def test_toggle_buttons_open_switch_and_close(shown, qapp):
    bar = shown.transportBar
    assert panel_state(shown) == (None, False, False, False)
    click(bar.annotationButton, qapp)
    assert panel_state(shown) == ("annotation", True, True, False)
    assert shown.toolPanel.current() == "annotation"
    click(bar.ocrButton, qapp)  # 다른 쪽을 켜면 바뀜 — 한 번에 하나
    assert panel_state(shown) == ("ocr", True, False, True)
    assert shown.toolPanel.current() == "ocr"
    click(bar.ocrButton, qapp)  # 열린 쪽의 토글을 다시 누르면 닫힘
    assert panel_state(shown) == (None, False, False, False)


def test_close_button_closes_the_panel(shown, qapp):
    shown.show_tool_panel("ocr")
    click(shown.toolPanel.findChild(QToolButton, "toolPanelClose"), qapp)
    assert panel_state(shown) == (None, False, False, False)


def test_n_key_opens_the_annotation_panel_first_and_then_the_last_one(shown):
    press(shown, Qt.Key_N)
    assert panel_state(shown) == ("annotation", True, True, False)
    press(shown, Qt.Key_N)
    assert panel_state(shown) == (None, False, False, False)
    shown.show_tool_panel("ocr")
    press(shown, Qt.Key_N)
    assert shown.tool_panel_key() is None
    press(shown, Qt.Key_N)  # 마지막에 쓰던 쪽
    assert panel_state(shown) == ("ocr", True, False, True)


def test_korean_u_key_toggles_the_panel_too(shown):
    press(shown, 0, "ㅜ")
    assert shown.tool_panel_key() == "annotation"
    press(shown, 0, "ㅜ")
    assert shown.tool_panel_key() is None


def test_n_key_works_while_a_list_has_focus(shown, qapp):
    shown.sidebar.setFocus()
    qapp.processEvents()
    QTest.keyClick(shown.sidebar, Qt.Key_N)
    assert shown.tool_panel_key() == "annotation" and not shown.toolPanel.isHidden()
    QTest.keyClick(shown.sidebar, Qt.Key_N)
    assert shown.tool_panel_key() is None and shown.toolPanel.isHidden()


def test_n_key_is_taken_by_the_event_filter_from_every_list(player):
    """목록(Mov·Seq·All)이 포커스를 가진 채 누른 N도 창의 필터가 받음 (예전 '가운데 열 숨기기' 키와 같은 길)."""
    for source, expected in ((player.sidebar, "annotation"), (player.seq_sidebar, None), (player.all_sidebar, "annotation")):
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_N, Qt.NoModifier, "n")
        assert player.eventFilter(source, event) is True
        assert player.tool_panel_key() == expected


def test_n_key_leaves_the_sidebar_and_the_video_alone(shown):
    press(shown, Qt.Key_N)
    assert not shown.sidebar_tabs.isHidden() and not shown.videoWidget.isHidden()
    assert not shown.transportBar.isHidden() and shown.controls_visible


@pytest.mark.parametrize("switch", ["switch_to_thumbnail_mode", "switch_to_list_mode"])
def test_panel_opens_at_its_width_after_the_sidebar_was_resized_while_it_was_closed(shown, qapp, switch):
    """닫은 동안 목록/썸네일 전환이 스플리터 폭을 다시 정해도(setSizes가 숨은 칸의 폭도 고쳐 적음) 패널은 제 폭으로 열림 —
    예전 가운데 열은 이때 0폭(접힌 채)으로 나타나 N을 다시 눌러도 돌아오지 않았음."""
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    width = sizes(shown)[2]
    assert width > 0
    shown.close_tool_panel()
    shown.initialize_sidebar_width()
    getattr(shown, switch)()
    qapp.processEvents()
    press(shown, Qt.Key_N)
    qapp.processEvents()
    assert not shown.toolPanel.isHidden() and sizes(shown)[2] == width
    assert shown.toolPanel.width() == width


def test_unknown_panel_key_is_refused_and_nothing_changes(shown):
    shown.show_tool_panel("ocr")
    with pytest.raises(KeyError):
        shown.show_tool_panel("settings")
    assert panel_state(shown) == ("ocr", True, False, True)


# ---------------------------------------------------------------- 폭

def test_opening_takes_the_width_from_the_video_and_closing_gives_it_back(shown, qapp):
    side, video, _panel = sizes(shown)
    handle = shown.mainSplitter.handleWidth()
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    wanted = max(tool_panel.PANEL_WIDTH, shown.toolPanel.minimumSizeHint().width())
    assert sizes(shown) == [side, video - wanted - handle, wanted]  # 사이드바 폭은 그대로
    assert shown.toolPanel.width() == wanted
    shown.show_tool_panel("ocr")  # 쪽을 바꿔도 폭은 그대로
    qapp.processEvents()
    assert sizes(shown) == [side, video - wanted - handle, wanted]
    shown.close_tool_panel()
    qapp.processEvents()
    assert sizes(shown) == [side, video, 0]


def test_panel_remembers_the_width_the_user_gave_it(shown, qapp):
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    side, video, panel = sizes(shown)
    shown.mainSplitter.setSizes([side, video - 80, panel + 80])  # 손잡이를 끌어 넓힘
    qapp.processEvents()
    assert sizes(shown)[2] == panel + 80
    shown.close_tool_panel()
    shown.show_tool_panel("ocr")
    qapp.processEvents()
    assert sizes(shown) == [side, video - 80, panel + 80]


def settle(qapp):
    for _ in range(6):  # 레이아웃 요청이 칸 → 가운데 위젯 → 창으로 한 단계씩 올라감
        qapp.processEvents()


def test_opening_in_a_window_too_narrow_widens_the_window_and_keeps_the_video(shown, qapp):
    """패널까지 담기에는 좁은 창: 창이 새 최소 너비(사이드바 + 영상 + 패널)까지 넓어지고, 영상 칸은 0폭으로 접히지 않음
    (접히면 스플리터가 늘어나는 폭을 사이드바에 줘 — 닫은 뒤에도 영상이 0폭으로 남음)."""
    splitter = shown.mainSplitter
    video_minimum = splitter.widget(1).minimumSizeHint().width()
    shown.resize(shown.minimumSizeHint().width() + 60, 700)
    settle(qapp)
    narrow = shown.width()
    shown.show_tool_panel("ocr")
    settle(qapp)
    side, video, panel = sizes(shown)
    assert shown.width() > narrow
    assert panel >= shown.toolPanel.minimumSizeHint().width() and video >= video_minimum > 0
    assert side + video + panel + 2 * splitter.handleWidth() == splitter.width()
    shown.close_tool_panel()
    settle(qapp)
    after_side, after_video, after_panel = sizes(shown)
    assert after_panel == 0 and after_side + after_video + splitter.handleWidth() == splitter.width()
    # 닫으면 패널의 폭은 영상 칸으로 — 좁아서 최소 너비까지 눌렸던 사이드바가 제 폭을 되찾는 몫만 빼고
    assert side <= after_side <= side + 20
    assert after_video == video + panel + splitter.handleWidth() - (after_side - side)
    shown.resize(1400, 700)  # 넓히면 늘어난 폭도 영상 칸으로 (사이드바가 아니라)
    settle(qapp)
    assert sizes(shown)[0] == after_side and sizes(shown)[1] > after_video + 500


def test_video_and_panel_columns_cannot_be_collapsed_by_the_handle(player):
    splitter = player.mainSplitter
    assert not splitter.isCollapsible(1) and not splitter.isCollapsible(2)
    assert splitter.isCollapsible(0)  # 사이드바는 예전처럼 끌어서 접을 수 있음


@pytest.mark.parametrize("opened", ["annotation", "ocr", None])
def test_long_file_names_do_not_widen_the_panel_or_the_window(shown, qapp, tmp_path, opened):
    """주석 쪽의 저장 위치·보내기 폴더 라벨에는 영상 이름·폴더 경로가 들어감 — 끊을 데가 없는 긴 이름이 패널(과 창)의
    최소 너비를 늘리지 않음. (늘리면 긴 이름의 영상을 여는 순간 패널이 넓어지고 좁은 창은 저절로 커짐 —
    넓은 글꼴 흉내에서 재생 줄 시험이 잡음)"""
    if opened:
        shown.show_tool_panel(opened)
    settle(qapp)
    before = (shown.toolPanel.minimumSizeHint().width(), shown.minimumSizeHint().width(), shown.width(), sizes(shown))
    long_name = "EP101_SC001_" + "아주_긴_이름_" * 14 + "TK2.mp4"
    shown.open_file("A", write_test_video(str(tmp_path / long_name), frames=6))
    shown.annotation_export_dir = "/Volumes/Project/" + "끊을_데가_없는_긴_폴더_이름_" * 8
    shown._update_annotation_export_dir_label()
    settle(qapp)
    assert long_name[:-4] in shown.annotationStorageLabel.text()  # 라벨에는 그 이름이 들어 있음
    assert (shown.toolPanel.minimumSizeHint().width(), shown.minimumSizeHint().width(), shown.width(),
            sizes(shown)) == before


def test_transport_bar_does_not_move_when_the_panel_opens(shown, qapp):
    bar, central = shown.transportBar, shown.centralWidget()
    before = bar.geometry(), bar.mapTo(central, bar.rect().topLeft())
    spots = [b.mapTo(central, b.rect().topLeft()) for b in (bar.firstButton, bar.playButton, bar.loopButton,
                                                              bar.frameField)]
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    shown.show_tool_panel("ocr")
    qapp.processEvents()
    assert (bar.geometry(), bar.mapTo(central, bar.rect().topLeft())) == before
    assert [b.mapTo(central, b.rect().topLeft()) for b in (bar.firstButton, bar.playButton, bar.loopButton,
                                                           bar.frameField)] == spots


def test_thumbnail_mode_resizes_the_sidebar_against_the_video_not_the_panel(shown, qapp):
    """목록/썸네일 전환의 사이드바 폭 조절은 영상 칸에서 주고받음 — 열린 패널의 폭은 그대로."""
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    side, video, panel = sizes(shown)
    shown._resize_sidebar_column(shown.sidebar_tabs.currentWidget().width() + 50)
    qapp.processEvents()
    assert sizes(shown) == [side + 50, video - 50, panel]
    shown._resize_sidebar_column(shown.sidebar_tabs.currentWidget().width() - 50)
    qapp.processEvents()
    assert sizes(shown) == [side, video, panel]


# ---------------------------------------------------------------- 패널 안의 위젯과 상태

ANNOTATION_WIDGETS = ("annotationModeButton", "annotationToolCombo", "annotationColorCombo", "annotationFontSizeSpin",
                      "annotationStrokeWidthSpin", "annotationRangeStartSpin", "annotationRangeEndSpin",
                      "annotationListWidget", "annotationDeleteButton", "annotationClearFrameButton",
                      "annotationExportDirButton", "annotationExportDirLabel", "annotationExportButton",
                      "annotationStorageLabel", "annotationStatusLabel")
OCR_WIDGETS = ("ocrSelectRoiButton", "ocrClearRoiButton", "ocrTrackingCheckBox", "ocrModeComboBox", "ocrPatternLabel",
               "ocrPatternLineEdit", "ocrAnalyzeButton", "ocrAnalyzeRangeButton", "ocrReopenResultButton",
               "ocrSaveResultButton", "ocrLoadResultButton")


def test_annotation_and_ocr_widgets_live_in_the_panel(shown, qapp):
    panel = shown.toolPanel
    for name in ANNOTATION_WIDGETS + OCR_WIDGETS:
        assert panel.isAncestorOf(getattr(shown, name)), name
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    assert shown.annotationModeButton.isVisible() and shown.annotationListWidget.isVisible()
    assert not shown.ocrAnalyzeButton.isVisible()
    shown.show_tool_panel("ocr")
    qapp.processEvents()
    assert shown.ocrSelectRoiButton.isVisible() and shown.ocrAnalyzeButton.isVisible() and shown.ocrLoadResultButton.isVisible()
    assert not shown.annotationModeButton.isVisible()
    assert not shown.ocrPatternLineEdit.isVisible()  # All 방식일 때만 보임 (지금 규칙 그대로)


def test_ocr_page_has_the_three_sections_in_order(shown, qapp):
    from PyQt5.QtWidgets import QLabel

    shown.show_tool_panel("ocr")
    qapp.processEvents()
    panel = shown.toolPanel
    sections = [label for label in panel.findChildren(QLabel, "toolPanelSection") if label.isVisible()]
    assert [label.text() for label in sections] == ["ROI 설정", "OCR 분석", "결과 관리"]

    def top(widget):
        return widget.mapTo(panel, widget.rect().topLeft()).y()

    order = [sections[0], shown.ocrSelectRoiButton, shown.ocrClearRoiButton, shown.ocrTrackingCheckBox,
             sections[1], shown.ocrModeComboBox, shown.ocrAnalyzeButton, shown.ocrAnalyzeRangeButton,
             sections[2], shown.ocrReopenResultButton, shown.ocrSaveResultButton, shown.ocrLoadResultButton]
    tops = [top(widget) for widget in order]
    assert tops == sorted(tops) and len(set(tops)) == len(tops)


def test_annotation_list_uses_the_height_of_the_panel(shown, qapp):
    """가운데 열용 높이 제한(상자 300px·목록 120px)을 풂 — 패널이 높으면 목록이 그만큼 길어짐."""
    shown.show_tool_panel("annotation")
    qapp.processEvents()
    low = shown.annotationListWidget.height()
    shown.resize(1400, 1100)
    qapp.processEvents()
    assert shown.annotationListWidget.height() >= low + 200
    assert shown.annotationListWidget.maximumHeight() > 10000


def test_ocr_mode_handler_still_shows_the_pattern_field(shown, qapp):
    shown.show_tool_panel("ocr")
    combo = shown.ocrModeComboBox
    combo.setCurrentIndex(combo.findData("all"))
    qapp.processEvents()
    assert shown.ocrPatternLineEdit.isVisible() and shown.ocrPatternLabel.isVisible()
    combo.setCurrentIndex(combo.findData("king"))
    qapp.processEvents()
    assert not shown.ocrPatternLineEdit.isVisible()


def test_state_survives_closing_and_switching_the_panel(shown, qapp, tmp_path):
    shown.open_file("A", write_test_video(str(tmp_path / "a.mp4"), frames=12))
    shown.show_tool_panel("annotation")
    shown.annotationModeButton.setChecked(True)
    shown.annotationToolCombo.setCurrentIndex(shown.annotationToolCombo.findData("arrow"))
    qapp.processEvents()
    assert shown.videoWidget.annotation_mode_enabled
    shown.show_tool_panel("ocr")
    combo = shown.ocrModeComboBox
    combo.setCurrentIndex(combo.findData("all"))
    shown.ocrPatternLineEdit.setText("## WW")
    shown.close_tool_panel()
    qapp.processEvents()
    # 닫은 채: 주석 모드는 그대로(배지가 알림), 입력값도 그대로
    assert shown.annotationModeButton.isChecked() and shown.videoWidget.annotation_mode_enabled
    assert shown.annotationToolCombo.currentData() == "arrow"
    assert combo.currentData() == "all" and shown.ocrPatternLineEdit.text() == "## WW"
    press(shown, Qt.Key_N)  # 마지막 쪽(OCR)으로 다시 엶
    qapp.processEvents()
    assert shown.tool_panel_key() == "ocr" and shown.ocrPatternLineEdit.isVisible()
    assert shown.ocrPatternLineEdit.text() == "## WW"
    shown.annotationModeButton.setChecked(False)


# ---------------------------------------------------------------- V 키 · 영상만 전체 화면

def test_v_key_hides_the_open_panel_and_brings_the_same_page_back(shown, qapp):
    shown.show_tool_panel("ocr")
    qapp.processEvents()
    before = sizes(shown)
    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert shown.toolPanel.isHidden() and shown.transportBar.isHidden() and shown.control_widgets[0].isHidden()
    assert shown.tool_panel_key() == "ocr"  # 숨은 동안에도 열린 상태는 기억
    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert panel_state(shown) == ("ocr", True, False, True)
    assert shown.toolPanel.current() == "ocr" and sizes(shown) == before


def test_v_key_does_not_reveal_a_closed_panel(shown, qapp):
    press(shown, Qt.Key_V)
    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert panel_state(shown) == (None, False, False, False)
    assert not shown.transportBar.isHidden()


def test_n_key_while_controls_are_hidden_takes_effect_when_they_come_back(shown, qapp):
    press(shown, Qt.Key_V)
    press(shown, Qt.Key_N)
    assert shown.tool_panel_key() == "annotation" and shown.toolPanel.isHidden()  # 컨트롤이 숨은 동안은 패널도 숨은 채
    press(shown, Qt.Key_V)
    qapp.processEvents()
    assert panel_state(shown) == ("annotation", True, True, False)


@pytest.mark.parametrize("opened", ["annotation", None])
def test_video_only_fullscreen_restores_the_panel_as_it_was(shown, qapp, opened):
    if opened:
        shown.show_tool_panel(opened)
    qapp.processEvents()
    before = panel_state(shown)
    shown.hide_all_ui_elements()
    qapp.processEvents()
    assert shown.toolPanel.isHidden() and shown.transportBar.isHidden()
    shown.restore_ui_elements()
    qapp.processEvents()
    assert panel_state(shown) == before
    assert not shown.transportBar.isHidden() and not shown.control_widgets[0].isHidden()
    assert shown.endPlaylistButton.isHidden() and shown.thumbnailProgressBar.isHidden()  # 엉뚱한 것이 나타나지 않음


# ---------------------------------------------------------------- 와이프 토글

def test_wipe_toggle_is_the_old_wipe_switch(shown, qapp, tmp_path):
    bar = shown.transportBar
    assert shown.wipeCheckBox is bar.wipeButton
    assert shown.wipeXButton is bar.wipeXButton and shown.wipeYButton is bar.wipeYButton
    assert not shown.wipeXButton.isEnabled() and not shown.wipeYButton.isEnabled()
    click(bar.wipeButton, qapp)
    assert shown.wipeCheckBox.isChecked() and shown.videoWidget.wipeEnabled
    assert shown.wipeXButton.isEnabled() and shown.wipeYButton.isEnabled()
    click(bar.wipeXButton, qapp)
    assert shown.videoWidget.wipe_enabled_x and not shown.videoWidget.wipe_enabled_y
    click(bar.wipeYButton, qapp)
    assert shown.videoWidget.wipe_enabled_y
    shown.wipeCheckBox.setChecked(False)  # 코드가 끄는 길 (B를 닫을 때 등)
    qapp.processEvents()
    assert not shown.videoWidget.wipeEnabled
    assert not shown.wipeXButton.isChecked() and not shown.wipeYButton.isChecked()
    assert not shown.wipeXButton.isEnabled() and not shown.wipeYButton.isEnabled()
    assert not shown.videoWidget.wipe_enabled_x and not shown.videoWidget.wipe_enabled_y


# ---------------------------------------------------------------- 창의 최소 크기

def test_window_minimum_width_is_set_by_the_bar_or_the_columns_not_more(player):
    """가운데 열이 없어져 창의 최소 너비는 재생 줄(또는 사이드바 + 영상 칸)이 정함 — 패널·콤보가 늘리지 않음."""
    splitter = player.mainSplitter
    columns = (splitter.widget(0).minimumSizeHint().width() + splitter.widget(1).minimumSizeHint().width()
               + splitter.handleWidth())
    floor = max(player.transportBar.minimumSizeHint().width(), columns)
    assert floor <= player.minimumSizeHint().width() <= floor + 40


def test_toggle_controls_does_not_swallow_errors(player):
    """컨트롤을 숨기다 난 오류는 드러남 — 조용히 건너뛰지 않음 (예전 코드를 옮기며 남았던 except를 뺌: 리뷰)."""

    class Broken:
        def setVisible(self, visible):
            raise RuntimeError("probe")

    player.control_widgets.append(Broken())
    try:
        with pytest.raises(RuntimeError, match="probe"):
            player.toggle_controls()
    finally:
        player.control_widgets.pop()
        if not player.controls_visible:
            player.toggle_controls()
