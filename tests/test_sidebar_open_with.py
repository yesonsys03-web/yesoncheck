"""사이드바 우클릭 '다른 앱으로 열기' (sidebar_open_with): Mov·Seq·All 메뉴 맨 아래에 'QuickTime Player로 열기'(Mac)와
'다른 앱으로 열기 ▸'(등록한 앱·앱 등록…·앱 지우기 ▸).

진짜 앱은 띄우지 않음 — open_with.open_with_quicktime·open_with_app을 기록기로 바꿈. 메뉴는 QMenu.exec_를 가로채 글자 나무로 기록하고
pick에 적은 길(("다른 앱으로 열기", "DJV"))의 항목을 누름. 플랫폼은 메뉴를 만드는 동안만 sys.platform을 바꿈(메뉴가 그때 읽음).
설정 파일은 conftest가 시험마다 새로 만든 HOME 아래(Mac)·이 시험이 새로 정한 LOCALAPPDATA 아래(Windows).
"""

import os
import sys
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog, QMenu

from tests.conftest import write_test_video
from tests.test_sequence_capture import make_seq
from tests.test_sidebar_all_tab import all_item, show_all_tab
from tests.test_sidebar_seq_tab import seq_item, shot
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import open_with, sidebar_open_with

OTHER_APPS = "다른 앱으로 열기"
QUICKTIME = "QuickTime Player로 열기"


@pytest.fixture
def player(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def launches(monkeypatch):
    """띄운 것: [("quicktime", 파일들)] 또는 [(앱, 파일들)]. fail에 예외를 넣으면 띄우기가 그 예외를 냄."""
    rec = SimpleNamespace(calls=[], fail=None)

    def quicktime(files, **_kwargs):
        if rec.fail:
            raise rec.fail
        rec.calls.append(("quicktime", list(files)))

    def app(app_path, files, **_kwargs):
        if rec.fail:
            raise rec.fail
        rec.calls.append((app_path, list(files)))

    monkeypatch.setattr(open_with, "open_with_quicktime", quicktime)
    monkeypatch.setattr(open_with, "open_with_app", app)
    return rec


def menu_tree(menu):
    """[(글자, 켜짐, 툴팁, 하위 나무 또는 None)] — 구분선 빼고."""
    return [(a.text(), a.isEnabled(), a.toolTip(), menu_tree(a.menu()) if a.menu() else None)
            for a in menu.actions() if not a.isSeparator()]


def _matches(text, wanted):
    return text == wanted or text.startswith(wanted + " (")  # 개수 꼬리 '(3개)'


def find_action(menu, path):
    for part in path[:-1]:
        menu = next(a.menu() for a in menu.actions() if a.menu() and _matches(a.text(), part))
    return next(a for a in menu.actions() if _matches(a.text(), path[-1]))


@pytest.fixture
def menus(monkeypatch):
    rec = SimpleNamespace(shown=[], pick=None)

    def fake_exec(menu, *_args):
        rec.shown.append(menu_tree(menu))
        if rec.pick:
            find_action(menu, rec.pick).trigger()

    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    return rec


def entry(tree, wanted):
    return next(row for row in tree if _matches(row[0], wanted))


def right_click(player, widget, item, platform, monkeypatch):
    """item 위에서 우클릭 메뉴를 엶 (platform으로 만든 메뉴)."""
    show = {player.sidebar: player.show_sidebar_context_menu, player.seq_sidebar: player.show_seq_context_menu,
            player.all_sidebar: player.show_all_context_menu}[widget]
    with monkeypatch.context() as m:
        m.setattr(sys, "platform", platform)
        show(widget.visualItemRect(item).center())


def mov_item(player, name):
    return next(player.sidebar.item(i) for i in range(player.sidebar.count()) if player.sidebar.item(i).text() == name)


def first_frame(folder, base):
    return os.path.join(str(folder), f"{base}-0001.tga")


@pytest.fixture
def folder(tmp_path):
    """tk1.mov·tk3.mov + 시퀀스 tk1(1~6장)·tk2(1~6장, 4번 빠짐)."""
    folder = shot(tmp_path)
    write_test_video(str(folder / "tk3.mov"))
    return folder


def make_app(tmp_path, name):
    app = tmp_path / "Applications" / f"{name}.app"
    app.mkdir(parents=True)
    return str(app)


def make_exe(tmp_path, name):
    exe = tmp_path / "Program Files" / f"{name}.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    return str(exe)


# ---------------------------------------------------------------- 메뉴 모양


def test_mov_menu_ends_with_quicktime_and_other_apps_on_mac(player, folder, menus, monkeypatch):
    drop_folder(player, "video", folder)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    tree = menus.shown[-1]
    assert [row[0] for row in tree[-2:]] == [QUICKTIME, OTHER_APPS]
    quicktime, other = tree[-2:]
    assert quicktime[1] is True
    assert [(text, enabled) for text, enabled, _tip, _sub in other[3]] == [
        ("(등록한 앱 없음)", False), ("앱 등록…", True)]


def test_windows_menu_has_no_quicktime(player, folder, menus, monkeypatch):
    drop_folder(player, "video", folder)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "win32", monkeypatch)
    texts = [row[0] for row in menus.shown[-1]]
    assert texts[-1] == OTHER_APPS
    assert not any(text.startswith("QuickTime") for text in texts)


@pytest.mark.parametrize("widget_name", ["seq_sidebar", "all_sidebar"])
def test_seq_and_all_menus_have_the_group_too(player, folder, menus, monkeypatch, qapp, widget_name):
    drop_folder(player, "video", folder)
    widget = getattr(player, widget_name)
    if widget is player.all_sidebar:
        show_all_tab(player, qapp)
        item = all_item(player, "mov", "tk1.mov")
    else:
        item = seq_item(player, "tk1")
    right_click(player, widget, item, "darwin", monkeypatch)
    assert [row[0] for row in menus.shown[-1][-2:]] == [QUICKTIME, OTHER_APPS]


# ---------------------------------------------------------------- 넘기는 파일


def test_quicktime_opens_the_selected_movies_in_list_order(player, folder, menus, launches, monkeypatch):
    drop_folder(player, "video", folder)
    mov_item(player, "tk3.mov").setSelected(True)
    mov_item(player, "tk1.mov").setSelected(True)
    menus.pick = (QUICKTIME,)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    assert entry(menus.shown[-1], QUICKTIME)[0] == "QuickTime Player로 열기 (2개)"
    assert launches.calls == [("quicktime", [str(folder / "tk1.mov"), str(folder / "tk3.mov")])]


def test_mov_menu_opened_outside_the_selection_uses_that_item(player, folder, menus, launches, monkeypatch):
    drop_folder(player, "video", folder)
    player.sidebar.clearSelection()
    mov_item(player, "tk3.mov").setSelected(True)
    menus.pick = (QUICKTIME,)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    assert launches.calls == [("quicktime", [str(folder / "tk1.mov")])]


def test_sequences_turn_quicktime_off_and_give_apps_the_first_frame(player, folder, menus, launches, monkeypatch,
                                                                     tmp_path):
    app = make_app(tmp_path, "DJV")
    open_with.add_app(app, "darwin")
    drop_folder(player, "video", folder)
    seq_item(player, "tk1").setSelected(True)
    seq_item(player, "tk2").setSelected(True)
    menus.pick = (OTHER_APPS, "DJV")
    right_click(player, player.seq_sidebar, seq_item(player, "tk1"), "darwin", monkeypatch)
    quicktime = entry(menus.shown[-1], QUICKTIME)
    assert quicktime[1] is False
    assert launches.calls == [(app, [first_frame(folder, "tk1"), first_frame(folder, "tk2")])]


def test_all_tab_mixed_selection(player, folder, menus, launches, monkeypatch, qapp, tmp_path):
    """QuickTime은 영상만, 등록한 앱은 영상 + 시퀀스 첫 프레임 — 목록 순서(자연 정렬: tk1 시퀀스·tk1.mov·tk2·tk3.mov)."""
    app = make_app(tmp_path, "DJV")
    open_with.add_app(app, "darwin")
    drop_folder(player, "video", folder)
    show_all_tab(player, qapp)
    player.all_sidebar.selectAll()
    clicked = all_item(player, "mov", "tk1.mov")

    menus.pick = (QUICKTIME,)
    right_click(player, player.all_sidebar, clicked, "darwin", monkeypatch)
    quicktime = entry(menus.shown[-1], QUICKTIME)
    assert quicktime[0] == "QuickTime Player로 열기 (2개)" and "시퀀스" in quicktime[2]
    menus.pick = (OTHER_APPS, "DJV")
    right_click(player, player.all_sidebar, clicked, "darwin", monkeypatch)

    movies = [str(folder / "tk1.mov"), str(folder / "tk3.mov")]
    assert launches.calls[0] == ("quicktime", movies)
    assert launches.calls[1] == (app, [first_frame(folder, "tk1"), str(folder / "tk1.mov"), first_frame(folder, "tk2"),
                                       str(folder / "tk3.mov")])
    assert entry(menus.shown[-1], OTHER_APPS)[0] == "다른 앱으로 열기 (4개)"


# ---------------------------------------------------------------- 등록·지우기


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_register_from_the_menu_saves_and_lists_the_app(player, folder, menus, monkeypatch, tmp_path, platform):
    app = make_app(tmp_path, "DJV") if platform == "darwin" else make_exe(tmp_path, "djv")
    asked = []

    def pick_app(parent, title, start, filters, *args, **kwargs):
        asked.append(filters)
        return app, filters

    monkeypatch.setattr(QFileDialog, "getOpenFileName", pick_app)
    drop_folder(player, "video", folder)
    menus.pick = (OTHER_APPS, "앱 등록…")
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), platform, monkeypatch)
    assert asked == ["앱 (*.app)" if platform == "darwin" else "프로그램 (*.exe)"]
    assert open_with.registered_apps(platform) == [app]

    menus.pick = None
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), platform, monkeypatch)
    other = entry(menus.shown[-1], OTHER_APPS)[3]
    label = "DJV" if platform == "darwin" else "djv"
    assert (other[0][0], other[0][1], other[0][2]) == (label, True, app)
    remove = entry(other, "앱 지우기")[3]
    assert [row[0] for row in remove] == [label]


def test_cancelled_register_changes_nothing(player, folder, menus, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    drop_folder(player, "video", folder)
    menus.pick = (OTHER_APPS, "앱 등록…")
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    assert open_with.registered_apps("darwin") == []
    assert not os.path.exists(open_with.prefs_path("darwin"))


def test_missing_app_is_shown_off_but_can_be_removed(player, folder, menus, launches, monkeypatch, tmp_path):
    app = make_app(tmp_path, "DJV")
    open_with.add_app(app, "darwin")
    os.rmdir(app)  # 지웠거나 옮김
    drop_folder(player, "video", folder)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    first = entry(menus.shown[-1], OTHER_APPS)[3][0]
    assert first[:2] == ("DJV (찾을 수 없음)", False)

    menus.pick = (OTHER_APPS, "앱 지우기", "DJV")
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    assert open_with.registered_apps("darwin") == []
    assert launches.calls == []


# ---------------------------------------------------------------- 실패는 조용히 넘기지 않음


def test_launch_failure_shows_an_error_window_with_the_reason(player, folder, menus, launches, monkeypatch, dialogs):
    launches.fail = RuntimeError("다른 앱으로 열지 못했습니다 — open이 종료 코드 1로 끝났습니다.")
    drop_folder(player, "video", folder)
    menus.pick = (QUICKTIME,)
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    assert len(dialogs.criticals) == 1
    text = dialogs.criticals[0]
    assert "QuickTime Player" in text and "종료 코드 1" in text and "Traceback" in text


def test_missing_file_is_reported_and_nothing_is_launched(player, menus, launches, monkeypatch, dialogs, tmp_path):
    gone = tmp_path / "gone" / "gone.mov"
    write_test_video(str(gone))
    player.add_files_to_sidebar([str(gone)])  # 열지 않고 목록에만 (Windows는 열린 파일을 지우지 못함)
    os.remove(gone)
    menus.pick = (QUICKTIME,)
    right_click(player, player.sidebar, mov_item(player, "gone.mov"), "darwin", monkeypatch)
    assert launches.calls == []
    assert len(dialogs.criticals) == 1 and "gone.mov" in dialogs.criticals[0]


def test_many_files_ask_first(player, menus, launches, monkeypatch, dialogs, tmp_path):
    from PyQt5.QtWidgets import QMessageBox

    folder = tmp_path / "many"
    for i in range(sidebar_open_with.OPEN_CONFIRM_COUNT + 1):
        write_test_video(str(folder / f"c{i:02d}.mov"), frames=2, size=(32, 24))
    drop_folder(player, "video", folder)
    player.sidebar.selectAll()
    dialogs.answer_question(QMessageBox.No)
    menus.pick = (QUICKTIME,)
    right_click(player, player.sidebar, player.sidebar.item(0), "darwin", monkeypatch)
    assert launches.calls == []
    assert len(dialogs.questions) == 1 and f"{sidebar_open_with.OPEN_CONFIRM_COUNT + 1}개" in dialogs.questions[0]

    dialogs.answer_question(QMessageBox.Yes)
    right_click(player, player.sidebar, player.sidebar.item(0), "darwin", monkeypatch)
    assert len(launches.calls) == 1 and len(launches.calls[0][1]) == sidebar_open_with.OPEN_CONFIRM_COUNT + 1


def test_broken_settings_file_shows_why_and_register_reports_it(player, folder, menus, monkeypatch, dialogs, tmp_path):
    path = open_with.prefs_path("darwin")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"open_with_apps": "DJV"}')
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (make_app(tmp_path, "DJV"), "앱 (*.app)"))
    drop_folder(player, "video", folder)
    menus.pick = (OTHER_APPS, "앱 등록…")
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "darwin", monkeypatch)
    first = entry(menus.shown[-1], OTHER_APPS)[3][0]
    assert first[0] == "설정 파일을 읽지 못했습니다" and first[1] is False and "open_with_apps" in first[2]
    assert len(dialogs.criticals) == 1 and "open_with_apps" in dialogs.criticals[0]
    with open(path, encoding="utf-8") as f:
        assert f.read() == '{"open_with_apps": "DJV"}'  # 덮어 지우지 않음


def test_upper_case_frame_extension_passes_the_real_file(player, menus, launches, monkeypatch, tmp_path):
    """SeqInfo의 확장자는 늘 소문자 — .TGA 프레임을 대소문자를 가리는 NFS에서 소문자 이름으로 넘기면 없는 파일. 누를 때
    sequence_source.first_frame_path로 실제 이름을 찾음 (이 Mac의 tmp는 대소문자를 안 가려 os.stat을 가리게 바꿈)."""
    caps = tmp_path / "caps"
    make_seq(str(caps), "tk1", [1, 2, 3])
    for n in (1, 2, 3):
        os.rename(caps / f"tk1-{n:04d}.tga", caps / f"tk1-{n:04d}.TGA")
    app = make_app(tmp_path, "DJV")
    open_with.add_app(app, "darwin")
    player.load_videos_from_folder(str(caps))
    lowercase = str(caps / "tk1-0001.tga")
    real_stat = os.stat

    def case_sensitive_stat(path, *args, **kwargs):
        if os.fspath(path) == lowercase:
            raise FileNotFoundError(2, "No such file or directory", lowercase)
        return real_stat(path, *args, **kwargs)

    menus.pick = (OTHER_APPS, "DJV")
    with monkeypatch.context() as m:
        m.setattr(os, "stat", case_sensitive_stat)
        right_click(player, player.seq_sidebar, seq_item(player, "tk1"), "darwin", monkeypatch)
    assert launches.calls == [(app, [str(caps / "tk1-0001.TGA")])]


def test_sequence_whose_first_frame_is_gone_is_reported(player, folder, menus, launches, monkeypatch, dialogs,
                                                         tmp_path):
    app = make_app(tmp_path, "DJV")
    open_with.add_app(app, "darwin")
    drop_folder(player, "video", folder)
    os.remove(first_frame(folder, "tk2"))
    menus.pick = (OTHER_APPS, "DJV")
    right_click(player, player.seq_sidebar, seq_item(player, "tk2"), "darwin", monkeypatch)
    assert launches.calls == []
    assert len(dialogs.criticals) == 1 and "tk2-0001.tga" in dialogs.criticals[0]


def test_dll_restore_failure_says_the_app_opened(player, folder, menus, launches, monkeypatch, dialogs, tmp_path):
    exe = make_exe(tmp_path, "djv")
    open_with.add_app(exe, "win32")
    launches.fail = open_with.DllDirectoryRestoreError("앱은 띄웠지만 DLL 검색 경로를 되돌리지 못했습니다")
    drop_folder(player, "video", folder)
    menus.pick = (OTHER_APPS, "djv")
    right_click(player, player.sidebar, mov_item(player, "tk1.mov"), "win32", monkeypatch)
    assert len(dialogs.criticals) == 1
    assert "열었지만" in dialogs.criticals[0] and "다시 켜" in dialogs.criticals[0]
