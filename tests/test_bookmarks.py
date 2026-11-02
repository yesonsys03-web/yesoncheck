"""북마크(bookmarks.py)와 작은 설정 파일(오버레이 위치·주석 내보내기 폴더)을 여러 창이 함께 써도 잃지 않는지 시험.

북마크는 쓸 때마다 파일을 다시 읽어 고치고(update_json) 원자적으로 쓴다. 읽지 못한 파일은 덮어 지우지 않는다.
오버레이·내보내기 폴더 설정은 마지막에 쓴 창이 이기되 원자적으로 쓰고, 읽기 오류는 기록 + 창 한 번 뒤 기본값.
"""

import json
import multiprocessing
import os

import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import bookmarks, sidebar_bookmarks, user_files
from yesoncheck.user_files import UserFileError


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------- bookmarks.py (Qt 없음) ----------


def test_load_missing_is_empty(tmp_path):
    assert bookmarks.load(str(tmp_path / "none.json")) == []


def test_add_creates_file_and_returns_new_list(tmp_path):
    path = str(tmp_path / "b.json")
    assert bookmarks.add(path, "/works/a") == ["/works/a"]
    assert bookmarks.add(path, "/works/b") == ["/works/a", "/works/b"]
    assert json.loads(read_text(path)) == ["/works/a", "/works/b"]
    assert bookmarks.load(path) == ["/works/a", "/works/b"]


def test_add_does_not_duplicate(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    assert bookmarks.add(path, "/works/a") == ["/works/a"]


def test_add_merges_with_what_other_windows_added(tmp_path):
    """이 창이 아는 목록(낡음)이 아니라 디스크의 목록에 더함: 다른 창이 넣은 것이 사라지지 않음."""
    path = str(tmp_path / "b.json")
    stale = bookmarks.add(path, "/works/a")  # 이 창이 아는 목록
    bookmarks.add(path, "/works/other-window")  # 다른 창
    assert stale == ["/works/a"]
    assert bookmarks.add(path, "/works/mine") == ["/works/a", "/works/other-window", "/works/mine"]
    assert bookmarks.load(path) == ["/works/a", "/works/other-window", "/works/mine"]


def test_remove_keeps_other_windows_additions(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    bookmarks.add(path, "/works/b")
    bookmarks.add(path, "/works/added-by-other-window")  # 이 창이 모르는 사이에 다른 창이 더함
    assert bookmarks.remove(path, "/works/a") == ["/works/b", "/works/added-by-other-window"]
    assert bookmarks.load(path) == ["/works/b", "/works/added-by-other-window"]


def test_remove_missing_folder_changes_nothing(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    assert bookmarks.remove(path, "/works/none") == ["/works/a"]
    assert bookmarks.remove(str(tmp_path / "none.json"), "/works/a") == []


@pytest.mark.parametrize("text", ["{깨진", '{"a": 1}', '["/works/a", 3]', "null"])
def test_load_corrupt_raises(tmp_path, text):
    """깨진 JSON도, 폴더 경로 목록이 아닌 JSON도 빈 목록으로 치지 않고 경로가 든 UserFileError."""
    path = str(tmp_path / "b.json")
    write_text(path, text)
    with pytest.raises(UserFileError) as info:
        bookmarks.load(path)
    assert path in str(info.value)


@pytest.mark.parametrize("change", [bookmarks.add, bookmarks.remove,
                                    lambda path, folder: bookmarks.replace(path, folder, "/works/b")])
def test_add_remove_on_corrupt_file_raise_and_do_not_overwrite(tmp_path, change):
    path = str(tmp_path / "b.json")
    write_text(path, "{깨진")
    with pytest.raises(UserFileError):
        change(path, "/works/a")
    assert read_text(path) == "{깨진"


# ---------- bookmarks.replace (Qt 없음) — 관리 창에서 경로를 고침 ----------


def test_replace_changes_the_path_in_place(tmp_path):
    """고친 경로는 같은 자리에 (목록 순서 유지)."""
    path = str(tmp_path / "b.json")
    for folder in ("/works/a", "/works/GASA01/scene-01A_S03/frames", "/works/c"):
        bookmarks.add(path, folder)
    new = bookmarks.replace(path, "/works/GASA01/scene-01A_S03/frames", "/works/GASA01/scene-01A_S04/frames")
    assert new == ["/works/a", "/works/GASA01/scene-01A_S04/frames", "/works/c"]
    assert bookmarks.load(path) == new


def test_replace_keeps_what_other_windows_added(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    bookmarks.add(path, "/works/other-window")  # 이 창은 모르는 사이 다른 창이 더함
    assert bookmarks.replace(path, "/works/a", "/works/a2") == ["/works/a2", "/works/other-window"]


def test_replace_appends_when_other_window_removed_old_meanwhile(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    assert bookmarks.replace(path, "/works/gone", "/works/new") == ["/works/a", "/works/new"]


def test_replace_to_a_path_already_present_leaves_one_entry(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    bookmarks.add(path, "/works/b")
    assert bookmarks.replace(path, "/works/b", "/works/a") == ["/works/a"]
    assert bookmarks.replace(path, "/works/gone", "/works/a") == ["/works/a"]


def test_replace_same_path_changes_nothing(tmp_path):
    path = str(tmp_path / "b.json")
    bookmarks.add(path, "/works/a")
    bookmarks.add(path, "/works/b")
    assert bookmarks.replace(path, "/works/a", "/works/a") == ["/works/a", "/works/b"]


def _add_many(path, worker, count):
    """자식 프로세스: 북마크를 count개 더함 (시험 모듈에 있어야 spawn으로 부를 수 있음)."""
    for n in range(count):
        bookmarks.add(path, f"/works/w{worker}/folder-{n}")


def test_add_from_two_processes_keeps_both(tmp_path):
    path = str(tmp_path / "b.json")
    context = multiprocessing.get_context("spawn")  # Mac·Windows 기본과 같게
    processes = [context.Process(target=_add_many, args=(path, worker, 20)) for worker in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
    assert [process.exitcode for process in processes] == [0, 0]

    saved = bookmarks.load(path)
    assert len(saved) == 40 and len(set(saved)) == 40  # 두 프로세스가 더한 것이 모두 남음
    assert {f"/works/w{w}/folder-{n}" for w in range(2) for n in range(20)} == set(saved)


# ---------- 창 (오프스크린) ----------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """창이 만들 때 읽는 홈 폴더의 설정 파일(오버레이·내보내기 폴더)을 시험용 폴더로 (사용자의 진짜 파일을 건드리지 않게)."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return str(folder)


def make_player(new_player, tmp_path):
    return new_player(make_config(str(tmp_path), {}))


def drop_folder(player, target, folder):
    """폴더를 실제 QDropEvent로 끌어다 놓음. target: "video"(영상 영역) 또는 "sidebar"(사이드바)."""
    from PyQt5.QtCore import QMimeData, QPointF, QUrl
    from PyQt5.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    if target == "video":
        player.videoWidget.dropEvent(event)
    else:
        assert player.eventFilter(player.sidebar, event) is True


def bookmark_list_widget(*texts, current=0):
    widget = QListWidget()
    for text in texts:
        widget.addItem(QListWidgetItem(text))
    widget.setCurrentRow(current)
    return widget


def test_sidebar_unreadable_bookmarks_not_overwritten(new_player, dialogs, home, tmp_path, capsys):
    """북마크 파일을 읽지 못하면 경고(경로·오류) — 이 창은 북마크를 더하거나 지우지 않아 파일을 덮지 않음."""
    from yesoncheck import bookmarks as bookmarks_module

    path = bookmarks_module.default_path()
    write_text(path, "{깨진")
    player = make_player(new_player, tmp_path)
    assert player.bookmarks_file == path and player.bookmarks == []
    assert "Traceback" in capsys.readouterr().err  # 기록에 스택 트레이스

    player.show_user_file_problems()  # app.launch가 창을 보인 뒤 부름 (시작 때 모아 둔 경고)
    assert len(dialogs.warnings) == 1
    assert path in dialogs.warnings[0] and "JSONDecodeError" in dialogs.warnings[0]

    folder = tmp_path / "clips"
    write_test_video(str(folder / "c.mov"))
    dialogs.folders.append(str(folder))
    player.add_bookmark()  # 북마크 추가 시도
    drop_folder(player, "sidebar", folder)  # 끌어다 놓아 자동 추가 시도
    drop_folder(player, "video", folder)
    player.show_bookmarks()  # 목록 열기 시도
    player.delete_bookmark(bookmark_list_widget("/works/a"))  # 삭제 시도

    assert read_text(path) == "{깨진"  # 그대로
    assert [name for name in os.listdir(os.path.dirname(path)) if name.startswith(".tmp-")] == []
    assert player.bookmarks == []
    assert len(dialogs.warnings) == 1 + 5  # 시도마다 왜 안 되는지 창
    assert all(path in text for text in dialogs.warnings)
    assert len(dialogs.questions) == 1 and dialogs.criticals == []  # 삭제는 사용자가 확인한 뒤에야 막힘 (확인 창 하나)


def test_sidebar_bookmarks_work_again_after_file_is_fixed(new_player, dialogs, home, tmp_path):
    from yesoncheck import bookmarks as bookmarks_module

    path = bookmarks_module.default_path()
    write_text(path, "{깨진")
    player = make_player(new_player, tmp_path)
    write_text(path, json.dumps(["/works/a"]))  # 사용자가 파일을 고침 — 창을 다시 켜지 않아도 됨

    folder = tmp_path / "clips"
    folder.mkdir()
    dialogs.folders.append(str(folder))
    player.add_bookmark()
    assert bookmarks_module.load(path) == ["/works/a", str(folder)]
    assert player.bookmarks == ["/works/a", str(folder)]


def test_sidebar_add_and_delete_merge_with_other_windows(new_player, dialogs, home, tmp_path):
    """두 창이 같은 북마크 파일에 더하고 지워도 서로의 것을 잃지 않음."""
    window_a = make_player(new_player, tmp_path)
    window_b = make_player(new_player, tmp_path)
    folder_a, folder_b, folder_c = (tmp_path / name for name in ("a", "b", "c"))
    for folder in (folder_a, folder_b, folder_c):
        folder.mkdir()

    dialogs.folders.append(str(folder_a))
    window_a.add_bookmark()
    dialogs.folders.append(str(folder_b))
    window_b.add_bookmark()  # window_a는 모르는 사이
    assert window_a.bookmarks == [str(folder_a)]  # 낡은 기억

    dialogs.folders.append(str(folder_c))
    window_a.add_bookmark()  # 디스크에 더함 → b의 것도 보임
    saved = bookmarks.load(window_a.bookmarks_file)
    assert saved == [str(folder_a), str(folder_b), str(folder_c)]
    assert window_a.bookmarks == saved

    window_b.delete_bookmark(bookmark_list_widget(str(folder_a), current=0))  # b가 a를 지움 (c는 b가 모름)
    assert bookmarks.load(window_a.bookmarks_file) == [str(folder_b), str(folder_c)]
    assert window_b.bookmarks == [str(folder_b), str(folder_c)]
    assert dialogs.errors() == []


def test_sidebar_show_bookmarks_reads_what_other_windows_added(new_player, dialogs, home, tmp_path, monkeypatch):
    window_a = make_player(new_player, tmp_path)
    window_b = make_player(new_player, tmp_path)
    bookmarks.add(window_b.bookmarks_file, "/works/added-later")
    shown = []

    def fake_exec(dialog):
        listing = dialog.findChildren(QListWidget)[0]
        shown.append([listing.item(row).text() for row in range(listing.count())])
        return 0

    monkeypatch.setattr("yesoncheck.sidebar_bookmarks.QDialog.exec_", fake_exec)
    window_a.show_bookmarks()
    assert shown == [["/works/added-later"]]
    assert dialogs.messages == []


@pytest.mark.parametrize("target", ["sidebar", "video"])
def test_dropped_folders_are_bookmarked_through_the_file(new_player, dialogs, home, tmp_path, target):
    window_a = make_player(new_player, tmp_path)
    window_b = make_player(new_player, tmp_path)
    bookmarks.add(window_b.bookmarks_file, "/works/other-window")
    first, second = tmp_path / "first", tmp_path / "second"
    write_test_video(str(first / "c.mov"))
    write_test_video(str(second / "d.mov"))

    drop_folder(window_a, target, first)
    assert bookmarks.load(window_a.bookmarks_file) == ["/works/other-window", str(first)]
    drop_folder(window_a, target, first)  # 같은 폴더를 또 놓아도 겹치지 않음
    drop_folder(window_a, target, second)
    assert bookmarks.load(window_a.bookmarks_file) == ["/works/other-window", str(first), str(second)]
    assert window_a.bookmarks == bookmarks.load(window_a.bookmarks_file)
    assert dialogs.errors() == []


def test_sidebar_lock_timeout_is_reported_not_swallowed(new_player, dialogs, home, tmp_path, monkeypatch, capsys):
    """다른 창이 잠금을 오래 쥐고 있어 시간 초과(TimeoutError)여도 숨기지 않음: 기록에 스택 트레이스 + 창, 목록은 그대로."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    player.load_bookmarks()

    def locked(path, folder):
        raise TimeoutError(f"다른 YesonCheck 창이 잠그고 있어 10초 안에 잠그지 못했습니다: {path}.lock")

    monkeypatch.setattr(bookmarks, "add", locked)
    capsys.readouterr()
    folder = tmp_path / "clips"
    write_test_video(str(folder / "c.mov"))
    drop_folder(player, "sidebar", folder)
    assert len(dialogs.warnings) == 1 and "잠그고 있어" in dialogs.warnings[0] and player.bookmarks_file in dialogs.warnings[0]
    assert "TimeoutError" in capsys.readouterr().err
    assert player.bookmarks == ["/works/a"]
    assert bookmarks.load(player.bookmarks_file) == ["/works/a"]


def test_old_save_bookmarks_is_gone():
    """창의 메모리 목록을 통째로 파일에 쓰던 save_bookmarks가 남아 있으면 다른 창의 것을 덮어 씀."""
    from yesoncheck.main_window import VideoPlayer

    assert not hasattr(VideoPlayer, "save_bookmarks")


# ---------- 북마크 관리 창: 경로를 그 자리에서 고치기 · 우클릭 메뉴 · P 키 ----------


def show_bookmark_dialog(player, monkeypatch, body):
    """show_bookmarks의 모달 exec_ 대신 body(dialog, list_widget)를 돌림 (창의 연결·단추·메뉴는 실제 것).

    body가 dialog.show()로 띄운 창은 끝에 숨김 — 보이는 모달 창이 남으면 뒤의 시험(test_default_app의 진짜 QMessageBox: '보이는 모달 창'을
    찾아 reject하는 close_for_update 모양)이 그 창을 대신 닫아 영원히 기다림 (창은 player의 자식 창이라 player.close()가 숨기지 않음).
    """

    def fake_exec(dialog):
        try:
            body(dialog, dialog.findChildren(QListWidget)[0])
        finally:
            if dialog.isVisible():
                dialog.hide()
        return 0

    monkeypatch.setattr("yesoncheck.sidebar_bookmarks.QDialog.exec_", fake_exec)
    player.show_bookmarks()


def dialog_button(dialog, text):
    return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)


def open_editor(listing, row, text=None):
    """목록의 편집기(QLineEdit)를 실제로 열고(commit 없이) 글을 바꿈 — 사용자가 경로를 클릭해 고치는 중."""
    listing.setCurrentRow(row)
    listing.editItem(listing.item(row))
    editor = listing.indexWidget(listing.model().index(row, 0))
    assert isinstance(editor, QLineEdit) and editor.text() == listing.item(row).text()
    if text is not None:
        editor.setText(text)
    return editor


def edit_in_place(listing, row, text):
    """편집기를 열어 글을 바꾸고 commit — 사용자가 경로를 클릭해 고치고 Enter를 누른 것."""
    editor = open_editor(listing, row, text)
    listing.commitData(editor)
    listing.closeEditor(editor, QAbstractItemDelegate.NoHint)


def listed(listing):
    return [listing.item(row).text() for row in range(listing.count())]


def test_bookmark_paths_are_editable_by_clicking(new_player, dialogs, home, tmp_path, monkeypatch):
    """항목은 그 자리에서 고칠 수 있음 — 고른 항목을 다시 클릭(SelectedClicked)하거나 우클릭 → 경로 수정.
    편집 트리거는 그것뿐: 더블클릭은 그대로 폴더 열기, Enter도 그대로 폴더 열기(EditKeyPressed를 켜면 Mac에서 Enter가 편집기를
    열어 예전 습관이 깨짐). 우클릭 메뉴는 customContextMenuRequested로."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    seen = {}

    def body(dialog, listing):
        seen["flags"] = listing.item(0).flags()
        seen["triggers"] = listing.editTriggers()
        seen["menu"] = listing.contextMenuPolicy()

    show_bookmark_dialog(player, monkeypatch, body)
    assert seen["flags"] & Qt.ItemIsEditable
    assert int(seen["triggers"]) == int(QAbstractItemView.SelectedClicked)
    assert seen["menu"] == Qt.CustomContextMenu


def test_edited_path_is_saved_and_opens_right_away(new_player, dialogs, home, tmp_path, monkeypatch):
    """고친 경로는 바로 파일에(다른 창의 것은 남기고, 자리 유지) → '폴더 열기'가 고친 경로를 엶."""
    player = make_player(new_player, tmp_path)
    old = tmp_path / "GASA01" / "scene-01A_S03" / "frames"
    new = tmp_path / "GASA01" / "scene-01A_S04" / "frames"
    old.mkdir(parents=True)
    write_test_video(str(new / "a.mov"))
    bookmarks.add(player.bookmarks_file, "/works/first")
    bookmarks.add(player.bookmarks_file, str(old))
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)

    def body(dialog, listing):
        bookmarks.add(player.bookmarks_file, "/works/other-window")  # 창을 연 뒤 다른 창이 더함
        edit_in_place(listing, 1, str(new))
        assert listed(listing) == ["/works/first", str(new)]
        player.open_bookmark_folder(listing, dialog)

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == ["/works/first", str(new), "/works/other-window"]
    assert player.bookmarks == bookmarks.load(player.bookmarks_file)
    assert opened == [str(new)]
    assert dialogs.messages == []


def test_open_button_commits_an_unfinished_edit(new_player, dialogs, home, tmp_path, monkeypatch):
    """편집기가 열린 채 '폴더 열기'를 누르면(Mac은 단추가 포커스를 가져가지 않아 편집기가 닫히지 않음)
    고치던 글을 먼저 반영하고 그 경로를 엶."""
    player = make_player(new_player, tmp_path)
    new = tmp_path / "clips"
    write_test_video(str(new / "a.mov"))
    bookmarks.add(player.bookmarks_file, "/works/a")
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)

    def body(dialog, listing):
        listing.setCurrentRow(0)
        listing.editItem(listing.item(0))
        listing.findChild(QLineEdit).setText(str(new))  # commit 없이 단추를 누름
        dialog_button(dialog, "폴더 열기").click()

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == [str(new)]
    assert bookmarks.load(player.bookmarks_file) == [str(new)]
    assert dialogs.messages == []


def test_editing_to_a_path_already_bookmarked_is_refused(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    bookmarks.add(player.bookmarks_file, "/works/b")
    texts = []

    def body(dialog, listing):
        edit_in_place(listing, 1, "/works/a")
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert texts == [["/works/a", "/works/b"]]  # 되돌림
    assert bookmarks.load(player.bookmarks_file) == ["/works/a", "/works/b"]
    assert [m[:2] for m in dialogs.messages] == [("information", "이미 북마크됨")]


def test_editing_to_a_folder_that_is_not_there_saves_and_warns(new_player, dialogs, home, tmp_path, monkeypatch):
    """없는 폴더(오타·떨어진 NAS)도 저장은 하되 경고로 알림 — 조용히 받지도, 막지도 않음."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    missing = str(tmp_path / "nope")

    def body(dialog, listing):
        edit_in_place(listing, 0, missing)

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [missing]
    assert player.bookmarks == [missing]
    assert len(dialogs.warnings) == 1 and missing in dialogs.warnings[0]


def test_empty_edit_is_reverted_without_saving(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    texts = []

    def body(dialog, listing):
        edit_in_place(listing, 0, "   ")
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert texts == [["/works/a"]]
    assert bookmarks.load(player.bookmarks_file) == ["/works/a"]
    assert dialogs.messages == []


def test_edit_on_unreadable_file_is_reverted_and_reported(new_player, dialogs, home, tmp_path, monkeypatch, capsys):
    """창을 연 뒤 파일이 깨졌으면 고친 것을 저장하지 않고(파일을 덮지 않음) 항목을 되돌리며 기록 + 창."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    texts = []

    def body(dialog, listing):
        write_text(player.bookmarks_file, "{깨진")
        capsys.readouterr()
        edit_in_place(listing, 0, "/works/a2")
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert texts == [["/works/a"]]
    assert read_text(player.bookmarks_file) == "{깨진"
    assert len(dialogs.warnings) == 1 and player.bookmarks_file in dialogs.warnings[0]
    assert "UserFileError" in capsys.readouterr().err


def test_right_click_menu_copies_the_path(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    bookmarks.add(player.bookmarks_file, "/works/b")
    QApplication.clipboard().setText("")

    def body(dialog, listing):
        listing.setCurrentRow(1)
        menu = player.bookmark_context_menu(listing, dialog)
        next(action for action in menu.actions() if action.text() == "경로 복사").trigger()

    show_bookmark_dialog(player, monkeypatch, body)
    assert QApplication.clipboard().text() == "/works/b"


def test_right_click_menu_starts_editing(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    states = []

    def body(dialog, listing):
        listing.setCurrentRow(0)
        menu = player.bookmark_context_menu(listing, dialog)
        next(action for action in menu.actions() if action.text() == "경로 수정").trigger()
        states.append((listing.state(), listing.findChild(QLineEdit) is not None))

    show_bookmark_dialog(player, monkeypatch, body)
    assert states == [(QAbstractItemView.EditingState, True)]


def test_switching_to_another_app_keeps_the_editor_open(new_player, dialogs, home, tmp_path, monkeypatch):
    """고치는 중에 다른 앱으로 갔다 와도(Cmd+Tab으로 Finder에서 경로를 복사해 오는 동안) 반쯤 친 글이 저장되지 않고 편집기가 그대로.
    창 안의 다른 곳을 클릭하면(포커스가 창 안에서 옮겨짐) Finder의 이름 바꾸기처럼 저장."""
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))
    seen = {}

    def body(dialog, listing):
        editor = open_editor(listing, 0, str(tmp_path / "half-typ"))
        QApplication.sendEvent(editor, QFocusEvent(QEvent.FocusOut, Qt.ActiveWindowFocusReason))  # 다른 앱으로
        seen["still_editing"] = listing.indexWidget(listing.model().index(0, 0)) is editor
        seen["file_meanwhile"] = bookmarks.load(player.bookmarks_file)
        editor.setText(str(a2))  # 돌아와서 붙여 넣음
        QApplication.sendEvent(editor, QFocusEvent(QEvent.FocusOut, Qt.MouseFocusReason))  # 창 안의 다른 곳 클릭
        seen["editing_after_click"] = listing.indexWidget(listing.model().index(0, 0)) is not None

    show_bookmark_dialog(player, monkeypatch, body)
    assert seen["still_editing"] and seen["file_meanwhile"] == [str(a)]
    assert not seen["editing_after_click"]
    assert bookmarks.load(player.bookmarks_file) == [str(a2)]
    assert dialogs.messages == []


@pytest.mark.parametrize("close", ["button", "reject", "x"])
def test_closing_the_dialog_commits_the_edit(new_player, dialogs, home, tmp_path, monkeypatch, close):
    """닫기 단추·X(보이는 창의 close → closeEvent → reject)·Esc(reject) — 모두 done()을 지나 고치던 경로를 먼저 반영.
    편집기 안의 Esc만 편집 취소."""
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))

    def body(dialog, listing):
        open_editor(listing, 0, str(a2))
        if close == "button":
            dialog_button(dialog, "닫기").click()
        elif close == "x":
            dialog.show()
            dialog.close()
        else:
            dialog.reject()

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [str(a2)]
    assert dialogs.messages == []


def test_enter_in_the_list_opens_the_selected_folder_as_before(new_player, dialogs, home, tmp_path, monkeypatch):
    """목록에서 Enter는 예전처럼 창의 기본 단추 '폴더 열기' (편집기를 열지 않음)."""
    player = make_player(new_player, tmp_path)
    folder = tmp_path / "clips"
    write_test_video(str(folder / "a.mov"))
    bookmarks.add(player.bookmarks_file, str(folder))
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)
    seen = {}

    def body(dialog, listing):
        dialog.show()
        listing.setCurrentRow(0)
        QTest.keyClick(listing, Qt.Key_Return)
        seen["editor"] = listing.indexWidget(listing.model().index(0, 0))

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == [str(folder)]
    assert seen["editor"] is None
    assert dialogs.messages == []


def test_enter_in_the_editor_saves_without_opening_the_folder(new_player, dialogs, home, tmp_path, monkeypatch):
    """편집기 안의 Enter는 저장(Qt가 commit을 큐에 넣음)이고 창의 기본 단추 '폴더 열기'로 새지 않음."""
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)
    seen = {}

    def body(dialog, listing):
        dialog.show()
        editor = open_editor(listing, 0, str(a2))
        QTest.keyClick(editor, Qt.Key_Return)
        QApplication.processEvents()
        seen["editing"] = listing.state() == QAbstractItemView.EditingState

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [str(a2)]
    assert opened == [] and not seen["editing"]
    assert dialogs.messages == []


def test_open_button_after_a_refused_edit_does_not_open_the_old_folder(new_player, dialogs, home, tmp_path, monkeypatch):
    """고치던 경로가 거부되면(이미 있는 경로) '폴더 열기'는 옛 경로를 열지 않고 멈춤 — 알림만."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    bookmarks.add(player.bookmarks_file, "/works/b")
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)
    texts = []

    def body(dialog, listing):
        open_editor(listing, 1, "/works/a")
        dialog_button(dialog, "폴더 열기").click()
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == []
    assert texts == [["/works/a", "/works/b"]]
    assert [m[:2] for m in dialogs.messages] == [("information", "이미 북마크됨")]


def test_delete_button_commits_an_unfinished_edit(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))
    counts = []

    def body(dialog, listing):
        open_editor(listing, 0, str(a2))
        dialog_button(dialog, "삭제").click()
        counts.append(listing.count())

    show_bookmark_dialog(player, monkeypatch, body)
    assert len(dialogs.questions) == 1 and str(a2) in dialogs.questions[0]
    assert bookmarks.load(player.bookmarks_file) == [] and counts == [0]


def test_edit_that_cannot_be_written_is_reverted_and_reported(new_player, dialogs, home, tmp_path, monkeypatch, capsys):
    """잠금 시간 초과(TimeoutError)·쓰기 실패(OSError)는 기록(스택 트레이스) + 창 + 되돌림."""
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))

    def locked(path, old, new):
        raise TimeoutError(f"다른 YesonCheck 창이 잠그고 있어 10초 안에 잠그지 못했습니다: {path}.lock")

    monkeypatch.setattr(bookmarks, "replace", locked)
    texts = []

    def body(dialog, listing):
        capsys.readouterr()
        edit_in_place(listing, 0, str(a2))
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert texts == [[str(a)]]
    assert bookmarks.load(player.bookmarks_file) == [str(a)]
    assert len(dialogs.warnings) == 1 and "잠그고 있어" in dialogs.warnings[0]
    assert "TimeoutError" in capsys.readouterr().err


def test_typed_path_is_tidied_before_saving(new_player, dialogs, home, tmp_path, monkeypatch):
    """손으로 친 경로는 앞뒤 공백·`~`·끝의 구분자를 정리해 저장 (`~/clips/` → 홈 아래 clips)."""
    player = make_player(new_player, tmp_path)
    clips = os.path.join(home, "clips")
    os.mkdir(clips)
    bookmarks.add(player.bookmarks_file, "/works/a")
    texts = []

    def body(dialog, listing):
        edit_in_place(listing, 0, "  ~/clips/  ")
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [clips] and texts == [[clips]]
    assert dialogs.messages == []


def test_editing_to_an_existing_path_with_a_trailing_slash_is_refused(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a/")  # 끌어다 놓은 폴더는 끝에 구분자가 붙어 있기도 함
    bookmarks.add(player.bookmarks_file, "/works/b")

    def body(dialog, listing):
        edit_in_place(listing, 1, "/works/a")

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == ["/works/a/", "/works/b"]
    assert [m[:2] for m in dialogs.messages] == [("information", "이미 북마크됨")]


def test_double_click_opens_the_folder_without_starting_an_edit(new_player, dialogs, home, tmp_path, monkeypatch):
    """실제 마우스: 고른 항목을 더블클릭하면 폴더 열기이고 편집기는 한 번도 만들어지지 않음.

    더블클릭 = 누름·뗌(이 뗌에서 Qt가 SelectedClicked 편집을 더블클릭 간격만큼 미뤄 둠)·더블클릭·뗌. Qt는 더블클릭의 doubleClicked
    신호를 보낸 **뒤에** 미룬 편집을 취소하므로, 열기를 신호 안에서 바로 하면(0.5초 대기 + processEvents) 그사이 편집 타이머가 터져
    닫히는 창에 편집기가 생김 — 열기를 Qt 루프로 미루면 생기지 않음. (QTest.mouseDClick은 더블클릭 이벤트 하나만 보내므로
    누름·뗌을 따로 보냄.) 편집기 생성은 델리게이트의 createEditor를 감시."""
    player = make_player(new_player, tmp_path)
    folder = tmp_path / "clips"
    write_test_video(str(folder / "a.mov"))
    bookmarks.add(player.bookmarks_file, str(folder))
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)
    created = []
    original = sidebar_bookmarks._BookmarkPathDelegate.createEditor

    def spy(self, parent, option, index):
        created.append(index.row())
        return original(self, parent, option, index)

    monkeypatch.setattr(sidebar_bookmarks._BookmarkPathDelegate, "createEditor", spy)
    seen = {}

    def body(dialog, listing):
        dialog.show()
        QTest.qWaitForWindowExposed(dialog)
        viewport = listing.viewport()
        pos = listing.visualItemRect(listing.item(0)).center()
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, pos)  # 고름
        QTest.qWait(QApplication.doubleClickInterval() + 100)
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, pos)  # 고른 항목을 더블클릭: 누름·뗌
        QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, pos)  # 더블클릭
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, pos)  # 뗌
        QTest.qWait(QApplication.doubleClickInterval() + 800)  # 미룬 열기(0.5초 대기 포함)와 미룬 편집 타이머가 돌 시간
        seen["dialog_open"] = dialog.isVisible()

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == [str(folder)]
    assert created == [] and not seen["dialog_open"]
    assert dialogs.messages == []


def test_open_with_an_untouched_editor_on_a_trailing_slash_path(new_player, dialogs, home, tmp_path, monkeypatch):
    """끌어다 놓은 폴더처럼 끝에 구분자가 붙어 저장된 경로: 편집기만 열렸다(느린 더블클릭) 아무것도 고치지 않고 '폴더 열기'를
    누르면 첫 클릭에 열림 — 정리한 글(구분자 없음)과 저장된 글이 달라도 '고치지 않음'은 거부가 아님."""
    player = make_player(new_player, tmp_path)
    folder = tmp_path / "clips"
    write_test_video(str(folder / "a.mov"))
    stored = str(folder) + os.sep
    bookmarks.add(player.bookmarks_file, stored)
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)

    def body(dialog, listing):
        open_editor(listing, 0)
        dialog_button(dialog, "폴더 열기").click()

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == [stored]
    assert bookmarks.load(player.bookmarks_file) == [stored]
    assert dialogs.messages == []


def test_close_for_update_reverts_an_unfinished_edit_without_a_dialog(new_player, dialogs, home, tmp_path, monkeypatch):
    """다른 창의 업데이트가 이 창을 닫을 때(close_for_update → 모달 reject): 고치던 반쪽 글을 저장하지도, 창을 띄우지도 않음 —
    창이 모달에 막혀 닫히지 않으면 업데이트가 90초 뒤 멈춤."""
    player = make_player(new_player, tmp_path)
    a = tmp_path / "a"
    a.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))
    seen = {}

    def body(dialog, listing):
        open_editor(listing, 0, str(tmp_path / "GASA01" / "sce"))
        player._closing_for_update = True
        try:
            dialog.reject()
            seen["editing"] = listing.state() == QAbstractItemView.EditingState
        finally:
            player._closing_for_update = False

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [str(a)]
    assert not seen["editing"]
    assert dialogs.messages == []


def test_typed_path_strips_surrounding_quotes(new_player, dialogs, home, tmp_path, monkeypatch):
    """Windows 탐색기의 '경로로 복사'(Ctrl+Shift+C)처럼 따옴표로 싸인 경로는 따옴표를 벗겨 저장."""
    player = make_player(new_player, tmp_path)
    clips = tmp_path / "clips"
    clips.mkdir()
    bookmarks.add(player.bookmarks_file, "/works/a")

    def body(dialog, listing):
        edit_in_place(listing, 0, f'"{clips}"')

    show_bookmark_dialog(player, monkeypatch, body)
    assert bookmarks.load(player.bookmarks_file) == [str(clips)]
    assert dialogs.messages == []


def test_relative_path_is_refused(new_player, dialogs, home, tmp_path, monkeypatch):
    """처음부터 적지 않은 경로(clips)는 저장하지 않고 되돌림 + 알림 — 어느 폴더 기준인지 알 수 없는 북마크를 남기지 않음."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    texts = []

    def body(dialog, listing):
        edit_in_place(listing, 0, "clips")
        texts.append(listed(listing))

    show_bookmark_dialog(player, monkeypatch, body)
    assert texts == [["/works/a"]]
    assert bookmarks.load(player.bookmarks_file) == ["/works/a"]
    assert [m[:2] for m in dialogs.messages] == [("information", "경로 형식")]


def test_right_click_shows_the_menu_for_the_item_under_the_cursor(new_player, dialogs, home, tmp_path, monkeypatch):
    """우클릭: 커서 아래 항목을 고르고 메뉴를 띄움(exec_), 항목이 없는 곳은 메뉴 없음. 고치던 경로는 먼저 반영."""
    player = make_player(new_player, tmp_path)
    a, a2 = tmp_path / "a", tmp_path / "a2"
    a.mkdir()
    a2.mkdir()
    bookmarks.add(player.bookmarks_file, "/works/first")
    bookmarks.add(player.bookmarks_file, str(a))
    shown = []
    monkeypatch.setattr(sidebar_bookmarks.QMenu, "exec_", lambda menu, *args: shown.append([act.text() for act in menu.actions()]))
    seen = {}

    def body(dialog, listing):
        dialog.show()
        open_editor(listing, 1, str(a2))  # 고치는 중에 우클릭
        player._show_bookmark_context_menu(listing, dialog, listing.visualItemRect(listing.item(1)).center())
        seen["current"] = listing.currentRow()
        player._show_bookmark_context_menu(listing, dialog, QPoint(5, listing.viewport().height() - 1))  # 항목 없는 곳

    show_bookmark_dialog(player, monkeypatch, body)
    assert shown == [["경로 복사", "경로 수정", "", "폴더 열기", "삭제"]]
    assert seen["current"] == 1
    assert bookmarks.load(player.bookmarks_file) == ["/works/first", str(a2)]
    assert dialogs.messages == []


def test_right_click_with_a_refused_edit_shows_no_menu(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    bookmarks.add(player.bookmarks_file, "/works/b")
    shown = []
    monkeypatch.setattr(sidebar_bookmarks.QMenu, "exec_", lambda menu, *args: shown.append(True))

    def body(dialog, listing):
        dialog.show()
        open_editor(listing, 1, "/works/a")
        player._show_bookmark_context_menu(listing, dialog, listing.visualItemRect(listing.item(1)).center())

    show_bookmark_dialog(player, monkeypatch, body)
    assert shown == []
    assert [m[:2] for m in dialogs.messages] == [("information", "이미 북마크됨")]


def test_real_app_switch_keeps_the_editor_and_focus_comes_back(new_player, dialogs, home, tmp_path, monkeypatch):
    """실제 창 활성 전환(setActiveWindow): 다른 앱으로 가도 편집기·글이 그대로, 돌아오면 편집기가 다시 포커스."""
    player = make_player(new_player, tmp_path)
    a = tmp_path / "a"
    a.mkdir()
    bookmarks.add(player.bookmarks_file, str(a))
    half = str(tmp_path / "GASA01" / "sce")
    seen = {}

    def body(dialog, listing):
        dialog.show()
        QApplication.setActiveWindow(dialog)
        editor = open_editor(listing, 0, half)
        editor.setFocus()
        QApplication.setActiveWindow(None)  # 다른 앱으로
        seen["editing"] = listing.indexWidget(listing.model().index(0, 0)) is editor
        seen["text"] = editor.text()
        seen["file_meanwhile"] = bookmarks.load(player.bookmarks_file)
        QApplication.setActiveWindow(dialog)  # 돌아옴
        seen["focus_back"] = QApplication.focusWidget() is editor
        listing.closeEditor(editor, QAbstractItemDelegate.RevertModelCache)

    show_bookmark_dialog(player, monkeypatch, body)
    assert seen["editing"] and seen["text"] == half and seen["file_meanwhile"] == [str(a)]
    assert seen["focus_back"]
    assert bookmarks.load(player.bookmarks_file) == [str(a)]
    assert dialogs.messages == []


def test_mouse_click_on_open_button_with_a_refused_edit_does_not_open(new_player, dialogs, home, tmp_path, monkeypatch):
    """실제 마우스 클릭(포커스를 가져가는 스타일 — Windows·Fusion): 단추가 포커스를 가져가며 편집기를 먼저 닫아 버리면 거부된
    편집을 모르고 옛 경로를 열게 됨 → 단추는 클릭으로 포커스를 가져가지 않게(TabFocus — Mac 기본과 같게)."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")
    bookmarks.add(player.bookmarks_file, "/works/b")
    opened = []
    monkeypatch.setattr(player, "load_videos_from_folder", opened.append)

    def body(dialog, listing):
        dialog.show()
        QApplication.setActiveWindow(dialog)
        editor = open_editor(listing, 1, "/works/a")
        editor.setFocus()
        QTest.mouseClick(dialog_button(dialog, "폴더 열기"), Qt.LeftButton)

    show_bookmark_dialog(player, monkeypatch, body)
    assert opened == []
    assert [m[:2] for m in dialogs.messages] == [("information", "이미 북마크됨")]


def test_error_while_committing_on_close_is_reported_and_the_dialog_still_closes(new_player, dialogs, home, tmp_path,
                                                                                  monkeypatch, capsys):
    """done()(가상 함수) 안에서 난 예외는 밖으로 내보내지 않고(qFatal) 바로 기록 + Qt 루프에서 오류 창, 창은 닫힘."""
    player = make_player(new_player, tmp_path)
    bookmarks.add(player.bookmarks_file, "/works/a")

    def broken(list_widget):
        raise RuntimeError("commit 폭발")

    monkeypatch.setattr(sidebar_bookmarks, "commit_bookmark_edit", broken)
    windows = []
    monkeypatch.setattr(sidebar_bookmarks.error_window, "show_window", windows.append)
    seen = {}

    def body(dialog, listing):
        capsys.readouterr()
        dialog.reject()
        seen["result"] = dialog.result()
        seen["logged"] = capsys.readouterr().err
        seen["windows_before_loop"] = list(windows)
        QApplication.processEvents()

    show_bookmark_dialog(player, monkeypatch, body)
    assert seen["result"] == QDialog.Rejected
    assert "[북마크]" in seen["logged"] and "RuntimeError: commit 폭발" in seen["logged"]
    assert seen["windows_before_loop"] == []  # 창은 done() 안에서 열지 않음
    assert len(windows) == 1 and windows[0].startswith("북마크 관리 창을 닫으며") and "commit 폭발" in windows[0]


def test_p_key_opens_the_bookmark_dialog(new_player, dialogs, home, tmp_path, monkeypatch):
    """P(한글 자판 ㅔ)는 창(keyPressEvent)과 사이드바 목록이 포커스를 가질 때(eventFilter) 모두 북마크 관리 창을 엶."""
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QKeyEvent

    player = make_player(new_player, tmp_path)
    calls = []
    monkeypatch.setattr(player, "show_bookmarks", lambda: calls.append("open"))
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier, "p"))
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_unknown, Qt.NoModifier, "ㅔ"))
    assert player.eventFilter(player.sidebar, QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier, "p")) is True
    assert player.eventFilter(player.seq_sidebar, QKeyEvent(QEvent.KeyPress, Qt.Key_unknown, Qt.NoModifier, "ㅔ")) is True
    assert calls == ["open"] * 4


# ---------- 오버레이 설정 ----------


def test_overlay_settings_round_trip(new_player, dialogs, home, tmp_path):
    player = make_player(new_player, tmp_path)
    player.overlayFrame.move(33, 44)
    player.save_overlay_settings()
    saved = json.loads(read_text(player.overlay_settings_file))
    assert saved["position"] == [33, 44] and set(saved) == {"position", "size", "parent_size", "is_bottom_center"}

    other = make_player(new_player, tmp_path)  # 다음에 켠 창은 읽어 옴
    assert other.overlay_saved_pos == [33, 44]
    assert dialogs.messages == []


def test_overlay_settings_write_is_atomic(new_player, dialogs, home, tmp_path, monkeypatch):
    """임시 파일에 다 쓴 뒤 os.replace로 바꿈: 바꾸기 직전까지 읽는 쪽은 옛 파일 전체를 봄."""
    player = make_player(new_player, tmp_path)
    player.save_overlay_settings()
    old = read_text(player.overlay_settings_file)

    seen = []
    real_replace = user_files._replace

    def spy(src, dst):
        assert os.path.dirname(src) == os.path.dirname(dst)  # 같은 폴더의 임시 파일
        seen.append(read_text(dst))  # 바꾸기 직전의 대상 파일
        return real_replace(src, dst)

    monkeypatch.setattr(user_files, "_replace", spy)
    player.overlayFrame.move(33, 44)
    player.save_overlay_settings()
    assert seen == [old]
    assert json.loads(read_text(player.overlay_settings_file))["position"] == [33, 44]
    assert [name for name in os.listdir(home) if name.startswith(".tmp-")] == []


def test_overlay_settings_write_failure_keeps_old_file_and_warns_once(new_player, dialogs, home, tmp_path,
                                                                      monkeypatch, capsys):
    player = make_player(new_player, tmp_path)
    player.show_user_file_problems()
    player.save_overlay_settings()
    old = read_text(player.overlay_settings_file)

    def disk_full(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(user_files, "_replace", disk_full)
    capsys.readouterr()
    player.overlayFrame.move(33, 44)
    player.save_overlay_settings()
    player.overlayFrame.move(55, 66)
    player.save_overlay_settings()  # 또 실패해도 창은 한 번

    assert read_text(player.overlay_settings_file) == old  # 반쯤 쓴 파일이 아님
    assert [name for name in os.listdir(home) if name.startswith(".tmp-")] == []
    assert len(dialogs.warnings) == 1
    assert player.overlay_settings_file in dialogs.warnings[0] and "No space left" in dialogs.warnings[0]
    err = capsys.readouterr().err
    assert err.count("Traceback") == 2 and "No space left on device" in err  # 실패마다 기록에 스택 트레이스


def test_overlay_settings_unreadable_gives_defaults_and_one_window(new_player, dialogs, home, tmp_path, capsys):
    path = os.path.join(home, ".yeson_overlay_settings.json")
    write_text(path, "{깨진")
    player = make_player(new_player, tmp_path)
    assert (player.overlay_saved_pos, player.overlay_saved_size, player.overlay_saved_parent_size) == (None, None, None)
    assert player.overlay_is_bottom_center is False
    assert "Traceback" in capsys.readouterr().err
    assert dialogs.warnings == []  # 창이 뜨기 전에는 모아 둠 (스플래시에 가려지지 않게)

    player.show_user_file_problems()
    player.show_user_file_problems()
    player.load_overlay_settings()  # 다시 읽어도 창은 세션에 한 번
    player.show_user_file_problems()
    assert len(dialogs.warnings) == 1
    assert path in dialogs.warnings[0] and "JSONDecodeError" in dialogs.warnings[0]
    assert read_text(path) == "{깨진"  # 읽기만 함


@pytest.mark.parametrize("text", ['["not", "a", "dict"]', '{"position": "x"}', '{"parent_size": [1, "2"]}'])
def test_overlay_settings_wrong_shape_is_reported_not_swallowed(new_player, dialogs, home, tmp_path, text):
    path = os.path.join(home, ".yeson_overlay_settings.json")
    write_text(path, text)
    player = make_player(new_player, tmp_path)
    player.show_user_file_problems()
    assert player.overlay_saved_pos is None and player.overlay_saved_parent_size is None
    assert len(dialogs.warnings) == 1 and path in dialogs.warnings[0]


# ---------- 주석 내보내기 폴더 설정 ----------


def test_annotation_export_dir_round_trip_and_atomic(new_player, dialogs, home, tmp_path, monkeypatch):
    player = make_player(new_player, tmp_path)
    export = tmp_path / "exported"
    export.mkdir()
    seen = []
    real_replace = user_files._replace

    def spy(src, dst):
        seen.append(os.path.dirname(src) == os.path.dirname(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(user_files, "_replace", spy)
    player.annotation_export_dir = str(export)
    player._save_annotation_export_settings()
    assert seen == [True]
    assert json.loads(read_text(player.annotation_export_settings_file)) == {"export_dir": str(export)}

    other = make_player(new_player, tmp_path)
    assert other.annotation_export_dir == str(export)
    assert dialogs.messages == []


def test_annotation_export_settings_unreadable_gives_default_and_one_window(new_player, dialogs, home, tmp_path,
                                                                            capsys):
    path = os.path.join(home, ".yeson_annotation_export.json")
    write_text(path, "{깨진")
    player = make_player(new_player, tmp_path)
    assert player.annotation_export_dir == ""
    assert "Traceback" in capsys.readouterr().err

    player.show_user_file_problems()
    player._load_annotation_export_settings()  # 다시 읽어도 창은 한 번
    player.show_user_file_problems()
    assert len(dialogs.warnings) == 1
    assert path in dialogs.warnings[0] and "JSONDecodeError" in dialogs.warnings[0]
    assert read_text(path) == "{깨진"


def test_annotation_export_settings_write_failure_warns_once(new_player, dialogs, home, tmp_path, monkeypatch, capsys):
    player = make_player(new_player, tmp_path)
    player.show_user_file_problems()
    player.annotation_export_dir = str(tmp_path)
    player._save_annotation_export_settings()
    old = read_text(player.annotation_export_settings_file)

    def denied(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(user_files, "_replace", denied)
    capsys.readouterr()
    player.annotation_export_dir = str(tmp_path / "x")
    player._save_annotation_export_settings()
    player._save_annotation_export_settings()
    assert read_text(player.annotation_export_settings_file) == old
    assert len(dialogs.warnings) == 1
    assert player.annotation_export_settings_file in dialogs.warnings[0] and "Permission denied" in dialogs.warnings[0]
    assert capsys.readouterr().err.count("Traceback") == 2
