"""북마크(bookmarks.py)와 작은 설정 파일(오버레이 위치·주석 내보내기 폴더)을 여러 창이 함께 써도 잃지 않는지 시험.

북마크는 쓸 때마다 파일을 다시 읽어 고치고(update_json) 원자적으로 쓴다. 읽지 못한 파일은 덮어 지우지 않는다.
오버레이·내보내기 폴더 설정은 마지막에 쓴 창이 이기되 원자적으로 쓰고, 읽기 오류는 기록 + 창 한 번 뒤 기본값.
"""

import json
import multiprocessing
import os

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidget, QListWidgetItem

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import bookmarks, user_files
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


@pytest.mark.parametrize("change", [bookmarks.add, bookmarks.remove])
def test_add_remove_on_corrupt_file_raise_and_do_not_overwrite(tmp_path, change):
    path = str(tmp_path / "b.json")
    write_text(path, "{깨진")
    with pytest.raises(UserFileError):
        change(path, "/works/a")
    assert read_text(path) == "{깨진"


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
