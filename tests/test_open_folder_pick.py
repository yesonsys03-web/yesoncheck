"""'폴더 열기' 단추 하나로 폴더도 파일도 (사용자 지시 2026-11-25): 폴더를 고르면 예전 그대로, 파일을 고르면 그 파일만 가져옴.
그리고 영상 영역·창 본문에 놓은 영상 파일도 Mov 목록에 보임 — 전에는 A로 열리기만 하고 목록에는 없었음(사이드바에 놓을 때만 보였음).

고르는 창은 플랫폼마다 다름: Mac의 기본 열기 창은 한 창에서 폴더와 파일을 모두 고르게 할 수 있고(`pick_folder_or_file`),
Windows의 기본 창은 그러지 못해 단추가 '폴더 고르기…'·'파일 고르기…' 두 항목을 띄움. 시험은 그 판단(`one_dialog_picks_both`)을
바꿔 끼워 두 모양을 어느 플랫폼에서나 봄 — 진짜 창은 띄우지 않음(conftest의 dialogs와 아래 대역).
예시 이름만 씀 (공개 저장소).
"""

import os

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog, QMenu

from tests.conftest import write_test_video
from tests.test_sequence_frame_open import deliver_drag, drop_files, frame, mov_names, seq_identities, shot_folder, virtual
from tests.test_sidebar_refresh import refresh
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import paths, player_sidebar, ui_text
from yesoncheck.sequence_source import ImageSequenceCapture

REAL_PICK = player_sidebar.pick_folder_or_file  # conftest의 dialogs가 이 이름을 대역으로 바꾸기 전의 진짜 함수


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def movie(tmp_path, name, folder="movs"):
    return write_test_video(str(tmp_path / folder / name))


def listed_paths(player):
    return [player.sidebar.item(i).toolTip() for i in range(player.sidebar.count())]


# ---------------------------------------------------------------- 영상 영역·창에 놓은 영상 파일도 목록에


@pytest.mark.parametrize("target", ["video", "window"])
def test_one_movie_dropped_on_the_viewer_opens_as_a_and_is_listed(player, dialogs, tmp_path, target):
    mov = movie(tmp_path, "a.mov")

    drop_files(player, target, [mov])

    assert player.filename_a == virtual(mov) and player.cap_a is not None and player.cap_a.isOpened()
    assert player.cap_b is None
    assert mov_names(player) == ["a.mov"]
    assert [paths.path_key(path) for path in listed_paths(player)] == [paths.path_key(mov)]  # 항목의 툴팁 = 파일 경로 (재생·썸네일이 읽음)
    assert dialogs.messages == []  # 하나를 놓을 때는 전처럼 안내 창 없음


@pytest.mark.parametrize("target", ["video", "window"])
def test_two_movies_dropped_on_the_viewer_open_as_a_and_b_and_both_are_listed(player, dialogs, tmp_path, target):
    first, second = movie(tmp_path, "a.mov"), movie(tmp_path, "b.mov")

    drop_files(player, target, [first, second])

    assert player.filename_a == virtual(first) and player.filename_b == virtual(second)
    assert mov_names(player) == ["a.mov", "b.mov"]
    assert dialogs.messages == []


@pytest.mark.parametrize("target", ["video", "window"])
def test_three_movies_dropped_on_the_viewer_open_the_first_and_list_all_three(player, dialogs, tmp_path, target):
    movies = [movie(tmp_path, f"{name}.mov") for name in ("a", "b", "c")]

    drop_files(player, target, movies)

    assert player.filename_a == virtual(movies[0]) and player.cap_b is None
    assert mov_names(player) == ["a.mov", "b.mov", "c.mov"]  # 첫째도 목록에 (전에는 나머지만)
    assert dialogs.messages == [
        ("information", "완료", "3개의 파일이 사이드바에 추가되었습니다."),
        ("information", "파일 로드 완료", "첫 번째 파일이 Video A에 로드되고, 3개의 파일이 사이드바에 추가되었습니다.")]


@pytest.mark.parametrize("target", ["video", "window"])
def test_a_movie_already_in_the_list_is_not_listed_twice(player, dialogs, tmp_path, target):
    mov = movie(tmp_path, "a.mov")
    drop_files(player, "sidebar", [mov])  # 사이드바에 놓음: 목록에만 (예전 그대로)
    assert mov_names(player) == ["a.mov"] and player.filename_a == ""
    dialogs.messages.clear()

    drop_files(player, target, [mov])

    assert player.filename_a == virtual(mov)
    assert mov_names(player) == ["a.mov"]
    assert dialogs.messages == []


@pytest.mark.parametrize("target", ["video", "window"])
def test_a_dropped_movie_is_added_to_the_list_that_is_already_there(player, dialogs, tmp_path, target):
    """지금 목록(불러온 폴더)은 그대로 두고 끝에 더함 — 놓은 파일 때문에 보던 목록이 비워지지 않음."""
    movie(tmp_path, "s1.mov", folder="job")
    movie(tmp_path, "s2.mov", folder="job")
    player.load_videos_from_folder(str(tmp_path / "job"))
    dialogs.messages.clear()
    extra = movie(tmp_path, "extra.mov", folder="elsewhere")

    drop_files(player, target, [extra])

    assert mov_names(player) == ["s1.mov", "s2.mov", "extra.mov"]
    assert player.filename_a == virtual(extra)
    assert dialogs.messages == []


def test_a_dropped_movie_stays_listed_after_a_refresh_while_the_file_exists(player, dialogs, tmp_path):
    mov = movie(tmp_path, "a.mov")
    drop_files(player, "video", [mov])

    refresh(player)
    assert mov_names(player) == ["a.mov"]

    os.remove(mov)
    refresh(player)
    assert mov_names(player) == []


def test_three_movies_all_listed_already_open_the_first_without_a_notice(player, dialogs, tmp_path):
    movies = [movie(tmp_path, f"{name}.mov") for name in ("a", "b", "c")]
    drop_files(player, "sidebar", movies)
    dialogs.messages.clear()

    drop_files(player, "video", movies)

    assert player.filename_a == virtual(movies[0])
    assert mov_names(player) == ["a.mov", "b.mov", "c.mov"]
    assert dialogs.messages == []  # 더한 것이 없으면 '추가되었습니다'라고 하지 않음


@pytest.mark.parametrize("where, opens", [
    ("videoWidget", True),  # 영상 영역 (자기 핸들러)
    ("sidebar", False),  # Mov 목록 (자기 핸들러 — 예전 그대로 목록에만)
    ("seq_sidebar", True),  # 아래 셋은 드롭을 받지 않는 위젯 — Qt가 창 본문 핸들러에 건넴
    ("all_sidebar", True),
    ("openFolderButton", True),
])
def test_a_movie_dragged_anywhere_in_the_window_shows_in_the_list(player, dialogs, tmp_path, where, opens):
    """파일을 창 어디에 놓든 Mov 목록에 보임 (사용자 지시 2026-11-25 '어디에 하든지 사이드바 리스트에도 표시') — 놓는 자리는 Qt가
    고르게 함 (DragEnter → DragMove → Drop을 그 위젯에 보냄), 한 번만 들어감."""
    mov = movie(tmp_path, "a.mov")

    enter, drop = deliver_drag(getattr(player, where), [mov])

    assert enter.isAccepted()
    assert mov_names(player) == ["a.mov"]
    assert (player.filename_a == virtual(mov)) is opens


# ---------------------------------------------------------------- '폴더 열기': 한 창에서 폴더나 파일 (Mac)


@pytest.fixture
def one_dialog(monkeypatch):
    """Mac의 모양: 기본 열기 창 하나에서 폴더나 파일을 고름. answers에 넣은 차례대로 창이 답하고(없으면 취소), asked에 창을 띄운 기록."""
    state = type("OneDialog", (), {})()
    state.answers, state.asked = [], []

    def pick(parent, title):
        state.asked.append(title)
        return state.answers.pop(0) if state.answers else ""

    monkeypatch.setattr(player_sidebar, "one_dialog_picks_both", lambda: True)
    monkeypatch.setattr(player_sidebar, "pick_folder_or_file", pick)
    return state


def test_picking_a_folder_loads_it_as_before(player, dialogs, one_dialog, tmp_path):
    movie(tmp_path, "old.mov", folder="before")
    player.load_videos_from_folder(str(tmp_path / "before"))
    dialogs.messages.clear()
    movie(tmp_path, "b.mov", folder="job")
    movie(tmp_path, "a.mov", folder="job")
    one_dialog.answers.append(str(tmp_path / "job"))

    player.select_folder()

    assert one_dialog.asked == [ui_text.text("sidebar.open_folder.pick")]
    assert mov_names(player) == ["a.mov", "b.mov"]  # 예전 그대로: 목록을 그 폴더의 영상으로 바꿈
    assert player.filename_a == virtual(str(tmp_path / "job" / "a.mov"))
    assert [title for _kind, title, _text in dialogs.messages] == ["폴더 로드 완료"]


def test_picking_a_movie_file_brings_in_only_that_file(player, dialogs, one_dialog, tmp_path):
    """파일을 고르면 그 파일만 — 그 파일이 든 폴더의 다른 영상은 가져오지 않음. 영상 영역에 놓을 때와 같은 규칙(A로 열고 목록에 더함)."""
    wanted = movie(tmp_path, "wanted.mov", folder="job")
    movie(tmp_path, "other.mov", folder="job")
    one_dialog.answers.append(wanted)

    player.select_folder()

    assert player.filename_a == virtual(wanted)
    assert mov_names(player) == ["wanted.mov"]
    assert dialogs.messages == []


def test_picking_a_movie_file_keeps_the_list_that_is_already_there(player, dialogs, one_dialog, tmp_path):
    movie(tmp_path, "s1.mov", folder="job")
    player.load_videos_from_folder(str(tmp_path / "job"))
    dialogs.messages.clear()
    extra = movie(tmp_path, "extra.mov", folder="elsewhere")
    one_dialog.answers.append(extra)

    player.select_folder()

    assert mov_names(player) == ["s1.mov", "extra.mov"]
    assert player.filename_a == virtual(extra)


def test_picking_a_sequence_frame_opens_that_sequence(player, dialogs, one_dialog, tmp_path):
    folder = shot_folder(tmp_path)
    one_dialog.answers.append(frame(folder, "tk1", 3))

    player.select_folder()

    assert isinstance(player.cap_a, ImageSequenceCapture)
    assert os.path.basename(player.filename_a) == "tk1.seq"
    assert "tk1.seq" in seq_identities(player) and player.sidebar_tabs.currentIndex() == 1
    assert player.sidebar.count() == 0
    assert dialogs.messages == []


def test_picking_a_file_that_is_not_a_video_or_a_frame_says_so(player, dialogs, one_dialog, tmp_path):
    note = tmp_path / "notes" / "readme.txt"
    note.parent.mkdir()
    note.write_text("x")
    one_dialog.answers.append(str(note))

    player.select_folder()

    assert player.cap_a is None and player.sidebar.count() == 0 and player.seq_sidebar.count() == 0
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "경고")]
    assert "readme.txt" in dialogs.messages[0][2]  # 무엇을 가져오지 못했는지 (조용히 아무 일도 없지 않음)


def test_cancelling_the_dialog_does_nothing(player, dialogs, one_dialog, tmp_path):
    movie(tmp_path, "s1.mov", folder="job")
    player.load_videos_from_folder(str(tmp_path / "job"))
    dialogs.messages.clear()

    player.select_folder()  # 답이 없음 = 취소

    assert one_dialog.asked == [ui_text.text("sidebar.open_folder.pick")]
    assert mov_names(player) == ["s1.mov"] and dialogs.messages == []


def test_a_picked_path_that_is_gone_is_reported_and_the_list_stays(player, dialogs, one_dialog, tmp_path):
    """고른 것이 폴더로도 파일로도 확인되지 않으면(그새 지워짐·공유가 끊김) 무엇을 찾지 못했는지 알리고 보던 목록은 그대로 —
    폴더 읽기에 넘기면 읽기 전에 목록부터 비우고 '읽지 못한 폴더'로 기억해 버림 (리뷰에서 잡음)."""
    movie(tmp_path, "s1.mov", folder="job")
    player.load_videos_from_folder(str(tmp_path / "job"))
    opened = player.filename_a
    dialogs.messages.clear()
    gone = str(tmp_path / "gone.mov")
    one_dialog.answers.append(gone)

    player.select_folder()

    assert mov_names(player) == ["s1.mov"] and player.filename_a == opened
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "경고")]
    assert paths.normalize_native(gone) in dialogs.messages[0][2]  # 어느 경로인지 통째로
    refresh(player)
    assert mov_names(player) == ["s1.mov"] and dialogs.errors() == [dialogs.messages[0]]  # 읽지 못한 폴더로 남지 않음


def test_the_button_opens_the_one_dialog_directly(player, dialogs, one_dialog, monkeypatch, tmp_path):
    monkeypatch.setattr(QMenu, "exec_", lambda *a, **k: pytest.fail("Mac에서는 메뉴를 띄우지 않음"))
    wanted = movie(tmp_path, "wanted.mov")
    one_dialog.answers.append(wanted)

    player.openFolderButton.click()

    assert one_dialog.asked == [ui_text.text("sidebar.open_folder.pick")]
    assert player.filename_a == virtual(wanted)


# ---------------------------------------------------------------- 고르는 창 자체 (Mac의 기본 창이 둘 다 고르게 하는 설정)


class FakeExec:
    """QFileDialog.exec_ 대역: 창의 설정을 적고 정해 둔 답을 돌려줌."""

    def __init__(self, monkeypatch, result, chosen):
        self.seen = []
        monkeypatch.setattr(QFileDialog, "exec_", lambda dialog: (self.seen.append(dialog), result)[1])
        monkeypatch.setattr(QFileDialog, "selectedFiles", lambda dialog: list(chosen))


def test_the_one_dialog_is_the_native_open_dialog_in_any_file_mode(player, monkeypatch, tmp_path):
    """Mac의 기본 열기 창은 '어떤 파일이든(AnyFile)' + 열기 모드일 때 파일과 폴더를 모두 고르게 함 (2026-11-25 이 Mac에서 창을 띄워
    NSOpenPanel의 값으로 확인: 파일 True·폴더 True·여러 개 False). 파일 모드를 바꾸면 한쪽만 고르게 되므로 고정."""
    fake = FakeExec(monkeypatch, QFileDialog.Accepted, [str(tmp_path / "job")])

    chosen = REAL_PICK(player, "제목")

    assert chosen == str(tmp_path / "job")
    dialog = fake.seen[0]
    assert dialog.fileMode() == QFileDialog.AnyFile and dialog.acceptMode() == QFileDialog.AcceptOpen
    assert not dialog.testOption(QFileDialog.DontUseNativeDialog)  # Qt가 그린 창이 아니라 기본 창
    assert dialog.windowTitle() == "제목" and dialog.parent() is player


def test_the_one_dialog_returns_nothing_when_cancelled(player, monkeypatch, tmp_path):
    FakeExec(monkeypatch, QFileDialog.Rejected, [str(tmp_path / "job")])

    assert REAL_PICK(player, "제목") == ""


def test_only_the_mac_picks_both_in_one_dialog(monkeypatch):
    for platform, expected in (("darwin", True), ("win32", False), ("linux", False)):
        monkeypatch.setattr(player_sidebar.sys, "platform", platform)
        assert player_sidebar.one_dialog_picks_both() is expected


# ---------------------------------------------------------------- '폴더 열기': 두 항목 (Windows)


@pytest.fixture
def two_dialogs(monkeypatch):
    """Windows의 모양: 기본 창이 폴더와 파일을 함께 고르지 못함 — 폴더 창과 파일 창이 따로. files에 넣은 것을 파일 창이 답함."""
    state = type("TwoDialogs", (), {})()
    state.files, state.asked_files = [], []

    def pick_files(parent, title, *args, **kwargs):
        state.asked_files.append(title)
        return (state.files.pop(0) if state.files else []), ""

    monkeypatch.setattr(player_sidebar, "one_dialog_picks_both", lambda: False)
    monkeypatch.setattr(player_sidebar, "pick_folder_or_file", lambda *a: pytest.fail("Windows에서는 한 창으로 고르지 않음"))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", pick_files)
    return state


def test_the_button_shows_two_choices_where_one_dialog_cannot_pick_both(player, dialogs, two_dialogs, monkeypatch):
    shown = []
    monkeypatch.setattr(QMenu, "exec_", lambda menu, *args: shown.append(([a.text() for a in menu.actions()], args)))

    player.openFolderButton.click()

    assert [texts for texts, _args in shown] == [[ui_text.text("sidebar.open_folder.folder"), ui_text.text("sidebar.open_folder.files")]]
    below = player.openFolderButton.mapToGlobal(player.openFolderButton.rect().bottomLeft())
    assert shown[0][1] == (below,)  # 단추 바로 아래에
    assert dialogs.messages == [] and two_dialogs.asked_files == []


def test_choosing_the_folder_item_loads_a_folder_as_before(player, dialogs, two_dialogs, tmp_path):
    movie(tmp_path, "b.mov", folder="job")
    movie(tmp_path, "a.mov", folder="job")
    dialogs.folders.append(str(tmp_path / "job"))

    player.open_folder_menu().actions()[0].trigger()

    assert mov_names(player) == ["a.mov", "b.mov"]
    assert player.filename_a == virtual(str(tmp_path / "job" / "a.mov"))
    assert [title for _kind, title, _text in dialogs.messages] == ["폴더 로드 완료"]


def test_choosing_the_files_item_brings_in_the_picked_files_only(player, dialogs, two_dialogs, tmp_path):
    first, second = movie(tmp_path, "a.mov", folder="job"), movie(tmp_path, "b.mov", folder="job")
    movie(tmp_path, "c.mov", folder="job")
    two_dialogs.files.append([first, second])

    player.open_folder_menu().actions()[1].trigger()

    assert two_dialogs.asked_files == [ui_text.text("sidebar.open_folder.files.title")]
    assert player.filename_a == virtual(first) and player.filename_b == virtual(second)  # 영상 영역에 둘을 놓을 때처럼
    assert mov_names(player) == ["a.mov", "b.mov"]
    assert dialogs.messages == []


def test_picked_files_that_can_be_brought_in_are_and_the_rest_are_named(player, dialogs, two_dialogs, tmp_path):
    """여러 개를 골랐는데 일부만 가져올 수 있으면: 되는 것은 가져오고, 안 되는 것은 이름을 알림 (고른 것을 조용히 빼지 않음)."""
    good = movie(tmp_path, "a.mov", folder="job")
    note = tmp_path / "job" / "readme.txt"
    note.write_text("x")
    gone = str(tmp_path / "job" / "gone.mov")
    two_dialogs.files.append([good, str(note), gone])

    player.open_folder_menu().actions()[1].trigger()

    assert player.filename_a == virtual(good) and mov_names(player) == ["a.mov"]
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "경고")]
    said = dialogs.messages[0][2]
    assert "readme.txt" in said and paths.normalize_native(gone) in said and "a.mov" not in said


def test_a_lone_frame_picked_with_a_sequence_frame_is_named(player, dialogs, two_dialogs, tmp_path):
    """한 장뿐인 프레임은 시퀀스가 아니라 가져오지 않음 — 함께 고른 시퀀스는 열고, 가져오지 않은 한 장은 이름을 알림."""
    folder = shot_folder(tmp_path)
    two_dialogs.files.append([frame(folder, "tk1", 2), frame(folder, "lone", 1)])

    player.open_folder_menu().actions()[1].trigger()

    assert os.path.basename(player.filename_a) == "tk1.seq"
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "경고")]
    assert "lone-0001.tga" in dialogs.messages[0][2] and "tk1-0002.tga" not in dialogs.messages[0][2]


def test_cancelling_the_files_dialog_does_nothing(player, dialogs, two_dialogs):
    player.open_folder_menu().actions()[1].trigger()

    assert two_dialogs.asked_files == [ui_text.text("sidebar.open_folder.files.title")]
    assert player.cap_a is None and player.sidebar.count() == 0 and dialogs.messages == []


def test_the_file_menu_and_the_i_key_still_open_the_folder_dialog_there(player, dialogs, two_dialogs, tmp_path):
    """Windows의 File → 폴더 열기…·I 키는 예전 그대로 폴더 창 (파일은 단추의 '파일 고르기…'나 File → 영상 A 열기…)."""
    movie(tmp_path, "a.mov", folder="job")
    dialogs.folders.append(str(tmp_path / "job"))

    player.select_folder()

    assert mov_names(player) == ["a.mov"] and two_dialogs.asked_files == []


def test_the_two_choices_follow_the_ui_language(player, two_dialogs):
    ui_text.set_language("en")
    try:
        assert [action.text() for action in player.open_folder_menu().actions()] == ["Choose a folder…", "Choose files…"]
    finally:
        ui_text.set_language("ko")
    assert [action.text() for action in player.open_folder_menu().actions()] == ["폴더 고르기…", "파일 고르기…"]


def test_item_data_of_a_picked_file_is_its_path(player, dialogs, one_dialog, tmp_path):
    wanted = movie(tmp_path, "wanted.mov")
    one_dialog.answers.append(wanted)

    player.select_folder()

    item = player.sidebar.item(0)
    assert paths.path_key(item.data(Qt.UserRole)) == paths.path_key(wanted) == paths.path_key(item.toolTip())
