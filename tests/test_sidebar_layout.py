"""사이드바의 새 배치 (2026-11-16 UI 개편 PR 2) — 가운데 열에 있던 작품 고르기와 선택 재생 단추가 사이드바로.

위에서 아래로: 작품 묶음(작품·시즌·job) → 작은 단추 줄(폴더 열기 · 북마크 ▾ · 새로고침) → 목록 | 썸네일 →
탭과 목록 → 개수 줄 → 썸네일 진행 막대(만드는 동안만) → 고른 영상 이어 재생 단추 → 끝내기 단추(선택 재생 중에만).

작품 묶음은 사내 전용이라 이 PC에서 작품을 읽어 온 적이 있을 때만 보인다(prefs.json의 `work_picker_seen`).
"""

import json
import os

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QToolButton

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import hover_strip, mac_prefs, ui_text, work_picker


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def with_works(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {"MyShow": str(tmp_path / "MyShow")}))


def show(player):
    player.resize(1400, 860)
    player.show()
    QApplication.setActiveWindow(player)
    QTest.qWait(250)
    return player


def prefs():
    return mac_prefs.read_prefs(hover_strip.prefs_path())


def write_prefs(text):
    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def top_in(container, widget):
    return widget.mapTo(container, widget.rect().topLeft()).y()


def left_in(container, widget):
    return widget.mapTo(container, widget.rect().topLeft()).x()


# ---------------------------------------------------------------- 작품 묶음의 보임

def test_work_picker_is_hidden_on_a_pc_that_never_read_any_work(player):
    assert player.workPickerGroup.isHidden()
    assert work_picker.PREF_KEY == "work_picker_seen" and work_picker.PREF_KEY not in prefs()
    for combo in (player.workComboBox, player.seasonComboBox, player.jobComboBox):
        assert player.workPickerGroup.isAncestorOf(combo)  # 콤보는 숨은 채로도 있음 (코드가 쓰는 이름)


def test_work_picker_shows_and_is_remembered_once_works_are_read(with_works):
    assert not with_works.workPickerGroup.isHidden()
    assert prefs()[work_picker.PREF_KEY] is True
    assert with_works.workComboBox.findText("MyShow") > 0


def test_work_picker_stays_on_a_pc_that_has_seen_works_even_when_none_are_read(new_player, dialogs, tmp_path):  # noqa: F811
    """불러오는 중이거나 NAS가 끊겨 읽지 못한 때에도 자리가 그대로 — 켤 때마다 목록이 밀리지 않게."""
    mac_prefs.update_pref(work_picker.PREF_KEY, True, hover_strip.prefs_path())
    player = new_player(make_config(str(tmp_path), {}))
    assert not player.workPickerGroup.isHidden()
    assert player.workComboBox.count() == 1  # 안내 항목만


def test_work_picker_appears_when_works_arrive_later(player):
    assert player.workPickerGroup.isHidden()
    player.work_paths = {"MyShow": "/Volumes/Project/MyShow"}
    player.reload_work_combo()  # 공유 설정을 뒤에서 다 읽었을 때·작품을 더했을 때의 길
    assert not player.workPickerGroup.isHidden()
    assert prefs()[work_picker.PREF_KEY] is True


def test_seen_flag_is_written_only_once(with_works, monkeypatch):
    writes = []
    monkeypatch.setattr(work_picker, "remember_seen", lambda *args, **kwargs: writes.append(1))
    with_works.reload_work_combo()
    with_works.reload_work_combo()
    assert writes == []  # 이미 참 — 다시 쓰지 않음


def test_other_prefs_keys_are_kept_when_the_flag_is_written(new_player, dialogs, tmp_path):  # noqa: F811
    mac_prefs.update_pref("slider_thumbnails", False, hover_strip.prefs_path())
    new_player(make_config(str(tmp_path), {"MyShow": str(tmp_path / "MyShow")}))
    assert prefs() == {"slider_thumbnails": False, work_picker.PREF_KEY: True}


def test_broken_prefs_show_the_picker_and_leave_the_file_alone(new_player, dialogs, tmp_path, capsys):  # noqa: F811
    path = write_prefs("{ 깨진 JSON")
    player = new_player(make_config(str(tmp_path), {}))
    assert not player.workPickerGroup.isHidden()  # 읽지 못하면 숨기지 않음 (사내 PC에서 사라지지 않게)
    assert "[작품 고르기]" in capsys.readouterr().err
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "{ 깨진 JSON"
    assert dialogs.messages == []  # 창은 더 띄우지 않음 — 같은 파일을 읽는 다른 설정이 켤 때 이미 알림


def test_bad_flag_value_shows_the_picker_and_logs(new_player, dialogs, tmp_path, capsys):  # noqa: F811
    write_prefs(json.dumps({work_picker.PREF_KEY: "yes"}))
    player = new_player(make_config(str(tmp_path), {}))
    assert not player.workPickerGroup.isHidden()
    assert "[작품 고르기]" in capsys.readouterr().err


def test_failing_to_remember_is_logged_and_the_picker_still_shows(new_player, dialogs, tmp_path, monkeypatch, capsys):  # noqa: F811
    def refuse(*args, **kwargs):
        raise OSError("디스크가 가득 참")

    monkeypatch.setattr(work_picker, "remember_seen", refuse)
    player = new_player(make_config(str(tmp_path), {"MyShow": str(tmp_path / "MyShow")}))
    assert not player.workPickerGroup.isHidden()
    err = capsys.readouterr().err
    assert "[작품 고르기]" in err and "디스크가 가득 참" in err


def test_work_picker_module_reads_and_writes_the_flag(tmp_path):
    path = str(tmp_path / "prefs.json")
    assert work_picker.read_seen(path) is False
    work_picker.remember_seen(path)
    assert work_picker.read_seen(path) is True
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({work_picker.PREF_KEY: 1}, fh)
    with pytest.raises(ValueError):
        work_picker.read_seen(path)


# ---------------------------------------------------------------- 배치

def test_sidebar_runs_top_to_bottom_in_the_new_order(with_works, qapp):
    player = show(with_works)
    side = player.mainSplitter.widget(0)
    rows = [player.workPickerGroup, player.openFolderButton, player.listModeButton, player.sidebar_tabs,
            player.sidebar_count_label, player.playSelectedPauseButton.button]
    tops = [top_in(side, widget) for widget in rows]
    assert tops == sorted(tops) and len(set(tops)) == len(tops)
    # 작은 단추 셋은 한 줄에 왼쪽부터, 목록|썸네일도 한 줄
    tools = [player.openFolderButton, player.bookmarkMenuButton, player.refreshListButton]
    assert len({(top_in(side, w), w.height()) for w in tools}) == 1  # 같은 줄·같은 높이 (북마크는 QToolButton이어도)
    lefts = [left_in(side, w) for w in tools]
    assert lefts == sorted(lefts) and len(set(lefts)) == 3
    assert top_in(side, player.listModeButton) == top_in(side, player.thumbnailModeButton)
    assert left_in(side, player.listModeButton) < left_in(side, player.thumbnailModeButton)
    # 작품 묶음 안: 라벨 → 작품 → 시즌 → job
    inside = [player.workLabel, player.workComboBox, player.seasonComboBox, player.jobComboBox]
    tops = [top_in(side, widget) for widget in inside]
    assert tops == sorted(tops) and len(set(tops)) == 4
    assert player.workLabel.text() == "작품 선택"  # 사용자 지시 2026-11-16 (예전 가운데 열의 글자는 'Yeson 작품')


def test_list_keeps_its_place_when_the_work_picker_is_hidden_or_shown(player, qapp):
    """작품 묶음이 숨은 PC에서는 그 자리가 비지 않고 단추 줄이 맨 위."""
    show(player)
    side = player.mainSplitter.widget(0)
    margin = side.layout().contentsMargins().top()
    assert top_in(side, player.openFolderButton) == margin


def test_small_buttons_read_the_text_table_and_take_no_focus(player):
    assert player.openFolderButton.text() == "폴더 열기"
    assert player.bookmarkMenuButton.text() == "북마크"
    assert player.refreshListButton.text() == "새로고침" and player.refreshListButton.toolTip() == "목록 다시 읽기 (F5)"
    assert player.listModeButton.text() == "목록" and player.thumbnailModeButton.text() == "썸네일"
    assert player.listModeButton.isCheckable() and player.listModeButton.isChecked()
    assert player.thumbnailModeButton.isCheckable() and not player.thumbnailModeButton.isChecked()
    for button in (player.openFolderButton, player.bookmarkMenuButton, player.refreshListButton, player.listModeButton,
                   player.thumbnailModeButton, player.playSelectedPauseButton.button):
        assert button.focusPolicy() == Qt.NoFocus
    for button in (player.openFolderButton, player.bookmarkMenuButton, player.refreshListButton, player.listModeButton,
                   player.thumbnailModeButton):
        assert button.objectName() == "sidebarTool"
        assert button.styleSheet() == ""  # 색은 테마 시트가 정함 — 채도 높은 색 단추 없음


def test_small_buttons_call_the_same_handlers_as_before(player, qapp, monkeypatch):
    calls = []
    for name in ("select_folder", "add_bookmark", "show_bookmarks", "_refresh_sidebar_by_user"):
        monkeypatch.setattr(player, name, lambda *args, name=name: calls.append(name))
    player.openFolderButton.click()
    player.refreshListButton.click()
    assert calls == ["select_folder", "_refresh_sidebar_by_user"]
    assert isinstance(player.bookmarkMenuButton, QToolButton)
    assert player.bookmarkMenuButton.popupMode() == QToolButton.InstantPopup
    actions = player.bookmarkMenuButton.menu().actions()
    assert [action.text() for action in actions] == ["북마크 추가", "북마크 관리… (P)"]
    actions[0].trigger()
    actions[1].trigger()
    assert calls[2:] == ["add_bookmark", "show_bookmarks"]


def test_long_names_in_the_combos_do_not_widen_the_sidebar(with_works, qapp):
    side = with_works.mainSplitter.widget(0)
    before = side.minimumSizeHint().width(), with_works.minimumSizeHint().width()
    long_name = "아주_긴_작품_이름_" * 12
    with_works.workComboBox.addItem(long_name)
    with_works.seasonComboBox.addItem(long_name)
    with_works.jobComboBox.addItem(long_name)
    with_works.jobComboBox.setCurrentIndex(with_works.jobComboBox.count() - 1)
    qapp.processEvents()
    assert (side.minimumSizeHint().width(), with_works.minimumSizeHint().width()) == before


def test_combos_take_no_focus_and_show_the_whole_name_as_a_tooltip(with_works, qapp):
    combo = with_works.jobComboBox
    assert combo.focusPolicy() == Qt.NoFocus
    combo.addItem("EP101_아주_긴_job_이름_끝까지_보이지_않는_것")
    combo.blockSignals(True)  # 목록을 읽지 않게 — 툴팁만 봄
    combo.setCurrentIndex(combo.count() - 1)
    combo.blockSignals(False)
    with_works._show_combo_tooltips()
    assert combo.toolTip() == "EP101_아주_긴_job_이름_끝까지_보이지_않는_것"


def test_popup_list_is_as_wide_as_its_longest_name(qapp):
    """콤보는 사이드바 폭이라 좁지만, 펼친 목록은 가장 긴 이름이 다 보이는 폭 (WidePopupComboBox)."""
    from yesoncheck.sidebar_controls import WidePopupComboBox

    combo = WidePopupComboBox()
    combo.addItem("job선택")
    combo.addItem("EP101_아주_긴_job_이름_" * 4)
    combo.setFixedWidth(150)
    combo.show()
    qapp.processEvents()
    wanted = combo.view().sizeHintForColumn(0)
    assert wanted > 150
    combo.showPopup()
    qapp.processEvents()
    try:
        assert combo.view().minimumWidth() >= wanted and combo.view().width() >= wanted
    finally:
        combo.hidePopup()
        combo.close()
        combo.deleteLater()
    wide = WidePopupComboBox()
    wide.addItem("A")
    wide.setFixedWidth(600)
    wide.show()
    wide.showPopup()
    qapp.processEvents()
    try:
        assert wide.view().minimumWidth() == 600  # 이름이 짧으면 콤보의 폭 그대로 (콤보보다 좁아지지 않음)
    finally:
        wide.hidePopup()
        wide.close()
        wide.deleteLater()


# ---------------------------------------------------------------- 썸네일 진행 막대

def test_thumbnail_progress_bar_is_hidden_until_thumbnails_are_made(player, qapp, monkeypatch):
    bar = player.thumbnailProgressBar
    assert bar.isHidden()
    assert bar not in player.control_widgets  # V 키 복원이 드러내면 안 됨
    seen = []
    monkeypatch.setattr(player, "generate_thumbnail", lambda *args, **kwargs: seen.append(not bar.isHidden()) or True)
    monkeypatch.setattr("yesoncheck.sidebar_thumbnails.time.sleep", lambda _s: None)
    player._thumbnail_bar_timer.setInterval(0)
    started, stopped = player._make_thumbnails([("a.mov", None), ("b.mov", None)], player._thumbnail_pass_state())
    assert (started, stopped) == (2, None) and seen == [True, True]  # 만드는 동안 보임
    assert not bar.isHidden()  # 끝난 글자를 잠깐 보임
    QTest.qWait(30)
    assert bar.isHidden()


def test_a_new_pass_keeps_the_bar_from_being_hidden_by_the_old_timer(player, qapp, monkeypatch):
    bar = player.thumbnailProgressBar
    monkeypatch.setattr("yesoncheck.sidebar_thumbnails.time.sleep", lambda _s: None)
    player._thumbnail_bar_timer.setInterval(10_000)
    player._make_thumbnails([], player._thumbnail_pass_state())
    assert not bar.isHidden() and player._thumbnail_bar_timer.isActive()
    checks = []

    def generate(*args, **kwargs):
        checks.append((not bar.isHidden(), player._thumbnail_bar_timer.isActive()))
        return True

    monkeypatch.setattr(player, "generate_thumbnail", generate)
    player._make_thumbnails([("a.mov", None)], player._thumbnail_pass_state())
    assert checks == [(True, False)]  # 새로 만드는 동안에는 숨기는 타이머가 멈춰 있음


# ---------------------------------------------------------------- 고른 영상 이어 재생 단추

def start_playlist(player, tmp_path, frames=(48, 6)):
    clips = [write_test_video(str(tmp_path / f"c{i}.mp4"), frames=count) for i, count in enumerate(frames)]
    player.add_files_to_sidebar(clips)
    player.sidebar.selectAll()
    return clips


def test_one_playlist_button_starts_pauses_and_resumes(player, qapp, tmp_path):
    slot = player.playSelectedPauseButton
    button = slot.button
    assert isinstance(button, QPushButton) and button.objectName() == "playlistButton"
    assert button.text() == "고른 영상 이어 재생" and button.toolTip() == "목록에서 고른 영상을 차례로 재생합니다 (Enter)"
    assert slot.text() == "Selected Play" and button.property("playing") is False
    start_playlist(player, tmp_path)
    button.click()  # 선택 재생이 아니면 시작
    assert player.is_playlist_playing and player.timer.isActive()
    assert button.text() == "이어 재생 일시정지" and button.property("playing") is True
    assert slot.text() == "Selected Pause"
    button.click()  # 선택 재생 중이면 일시정지
    assert player.is_playlist_playing and not player.timer.isActive()
    assert button.text() == "고른 영상 이어 재생" and button.property("playing") is False
    button.click()  # 다시 누르면 이어 재생
    assert player.timer.isActive() and button.text() == "이어 재생 일시정지"
    player.end_playlist()
    assert not player.is_playlist_playing and button.text() == "고른 영상 이어 재생"
    assert slot.text() == "Selected Play" and button.property("playing") is False


def test_end_button_sits_under_the_playlist_button_only_during_a_playlist(player, qapp, tmp_path):
    show(player)
    side = player.mainSplitter.widget(0)
    button, end = player.playSelectedPauseButton.button, player.endPlaylistButton
    assert end.isHidden() and button.isVisible()
    start_playlist(player, tmp_path)
    button.click()
    qapp.processEvents()
    assert end.isVisible()
    assert top_in(side, end) >= top_in(side, button) + button.height()
    assert top_in(side, button) > top_in(side, player.sidebar_count_label)
    end.click()
    qapp.processEvents()
    assert end.isHidden() and not player.is_playlist_playing


def test_playlist_slot_refuses_unknown_texts(player):
    slot = player.playSelectedPauseButton
    with pytest.raises(ValueError):
        slot.setText("Stop")
    assert slot.text() == "Selected Play" and slot.button.text() == "고른 영상 이어 재생"
    slot.setStyleSheet("background-color: yellow;")  # 옛 코드의 호출 — 받기만 함
    assert slot.button.styleSheet() == ""


def test_playlist_button_follows_the_language(player):
    ui_text.set_language("en")
    try:
        player.retranslate_sidebar_controls()
        assert player.playSelectedPauseButton.button.text() == "Play selected in a row"
        assert player.openFolderButton.text() == "Open folder" and player.listModeButton.text() == "List"
        assert player.workLabel.text() == "Select show"
        assert [a.text() for a in player.bookmarkMenuButton.menu().actions()] == ["Add bookmark", "Manage bookmarks… (P)"]
    finally:
        ui_text.set_language("ko")
        player.retranslate_sidebar_controls()
    assert player.playSelectedPauseButton.button.text() == "고른 영상 이어 재생"
