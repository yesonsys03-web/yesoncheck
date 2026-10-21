"""주석 파일(.yesoncheck/<영상>_annotations.json)을 여러 창이 함께 고쳐도 서로의 항목을 지우지 않음.

저장할 때 디스크를 다시 읽어 항목 id로 합치고(frame_annotations.merge_annotations) 원자적으로 쓴다.
"""

import errno
import json
import os
import stat
import sys
import threading

import pytest

from tests.conftest import write_test_video
from yesoncheck import frame_annotations as fa
from yesoncheck import user_files
from yesoncheck.frame_annotations import FrameAnnotationStore


def text_item(text, x=0.1):
    return {"type": "text", "text": text, "norm_x1": x, "norm_y1": 0.2, "color": "#ff3333"}


def open_store(video):
    """영상을 연 창 하나: 주석 파일이 있으면 읽음."""
    store = FrameAnnotationStore()
    store.set_video(video, 24.0)
    store.load()
    return store


def disk_data(video):
    with open(fa.annotation_file_path(video), encoding="utf-8") as fh:
        return json.load(fh)


def disk_ids(video):
    return sorted(item["id"] for items in disk_data(video)["annotations"].values() for item in items)


def memory_ids(store):
    return sorted(item["id"] for items in store.annotations.values() for item in items)


def memory_texts(store):
    return sorted(item["text"] for items in store.annotations.values() for item in items)


@pytest.fixture
def video(tmp_path):
    return str(tmp_path / "scene.mov")


# ---------- merge_annotations (순수 함수) ----------

def entry(anchor, **fields):
    return anchor, {"id": fields.pop("id"), **fields}


def test_merge_keeps_disk_items_and_adds_local_changes():
    disk = {"a": entry(0, id="a", text="disk")}
    local = {"b": entry(3, id="b", text="new")}
    result, deleted = fa.merge_annotations(disk, set(), {}, local)
    assert result == {**disk, **local}
    assert deleted == set()


def test_merge_unchanged_local_item_does_not_override_disk():
    base = {"a": entry(0, id="a", text="old")}
    disk = {"a": entry(0, id="a", text="other window edit")}
    result, _ = fa.merge_annotations(disk, set(), base, dict(base))
    assert result == disk


def test_merge_changed_local_item_overrides_disk():
    base = {"a": entry(0, id="a", text="old")}
    disk = {"a": entry(0, id="a", text="other window edit")}
    local = {"a": entry(0, id="a", text="my edit")}
    result, _ = fa.merge_annotations(disk, set(), base, local)
    assert result == local


def test_merge_local_removal_becomes_tombstone():
    base = {"a": entry(0, id="a", text="x"), "b": entry(1, id="b", text="y")}
    disk = dict(base)
    local = {"b": base["b"]}
    result, deleted = fa.merge_annotations(disk, {"old"}, base, local)
    assert result == {"b": base["b"]}
    assert deleted == {"old", "a"}


def test_merge_deleted_wins_over_local_edit():
    base = {"a": entry(0, id="a", text="old")}
    local = {"a": entry(0, id="a", text="edited after other window deleted it")}
    result, deleted = fa.merge_annotations({}, {"a"}, base, local)
    assert result == {}
    assert deleted == {"a"}


def test_merge_anchor_frame_change_counts_as_change():
    base = {"a": entry(0, id="a", text="x")}
    local = {"a": (5, base["a"][1])}
    disk = dict(base)
    result, _ = fa.merge_annotations(disk, set(), base, local)
    assert result["a"][0] == 5


# ---------- 두 창이 같은 파일을 고침 ----------

def test_two_stores_add_different_items_both_kept(video):
    a = open_store(video)
    b = open_store(video)
    item_a = a.add(0, text_item("from A"))
    a.save()
    item_b = b.add(10, text_item("from B"), start_frame=10, end_frame=12)
    b.save()

    assert disk_ids(video) == sorted([item_a["id"], item_b["id"]])
    assert memory_ids(b) == sorted([item_a["id"], item_b["id"]])  # 저장하면 다른 창의 항목도 메모리에 옴
    a.save()  # A도 다시 저장하면 B의 항목을 받음 (지우지 않음)
    assert memory_ids(a) == sorted([item_a["id"], item_b["id"]])
    assert disk_ids(video) == sorted([item_a["id"], item_b["id"]])
    reopened = open_store(video)
    assert memory_texts(reopened) == ["from A", "from B"]


def test_stale_store_save_does_not_revert_other_edit(video):
    first = open_store(video)
    item = first.add(0, text_item("original"))
    first.save()

    a = open_store(video)
    b = open_store(video)  # A가 고치기 전에 읽은 낡은 창
    a.update_by_id(item["id"], {"text": "edited in A"})
    a.save()
    added = b.add(5, text_item("added in B"))
    b.save()

    reopened = open_store(video)
    texts = {i["id"]: i["text"] for items in reopened.annotations.values() for i in items}
    assert texts == {item["id"]: "edited in A", added["id"]: "added in B"}
    assert memory_texts(b) == ["added in B", "edited in A"]


def test_deleted_item_not_resurrected_by_stale_store(video):
    first = open_store(video)
    item = first.add(0, text_item("to delete"))
    first.save()

    a = open_store(video)
    b = open_store(video)  # 지우기 전에 읽은 낡은 창
    assert a.remove_by_id(item["id"])
    a.save()
    added = b.add(5, text_item("added in B"))
    b.save()

    assert disk_ids(video) == [added["id"]]
    assert disk_data(video)["deleted_ids"] == [item["id"]]
    assert memory_ids(b) == [added["id"]]  # 낡은 창의 메모리에서도 사라짐


def test_edit_after_delete_stays_deleted(video):
    first = open_store(video)
    item = first.add(0, text_item("to delete"))
    first.save()

    a = open_store(video)
    b = open_store(video)
    a.remove_by_id(item["id"])
    a.save()
    b.update_by_id(item["id"], {"text": "edited after the delete"})
    b.save()

    assert disk_ids(video) == []
    assert memory_ids(b) == []
    assert disk_data(video)["deleted_ids"] == [item["id"]]


def test_old_file_without_deleted_ids_merges(video):
    """deleted_ids가 없던 예전 파일: 빈 것으로 읽고 합침 — 저장하면 deleted_ids가 생김."""
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    old_item = {"id": "old000000001", "type": "text", "text": "old", "norm_x1": 0.1, "norm_y1": 0.1,
                "start_frame": 2, "end_frame": 4}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"video_path": video, "fps": 24.0, "annotations": {"2": [old_item]}}, fh)

    a = open_store(video)
    b = open_store(video)
    item_a = a.add(0, text_item("from A"))
    a.save()
    item_b = b.add(1, text_item("from B"))
    b.save()

    data = disk_data(video)
    assert data["deleted_ids"] == []
    assert disk_ids(video) == sorted(["old000000001", item_a["id"], item_b["id"]])
    assert [i["start_frame"] for i in data["annotations"]["2"]] == [2]


def test_removing_item_from_old_file_records_tombstone(video):
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"video_path": video, "fps": 24.0,
                   "annotations": {"0": [{"id": "old000000001", "type": "text", "text": "old"}]}}, fh)
    store = open_store(video)
    store.remove_by_id("old000000001")
    store.save()
    assert disk_data(video)["deleted_ids"] == ["old000000001"]
    assert disk_ids(video) == []


def test_loaded_item_without_id_gets_one(video):
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"video_path": video, "fps": 24.0, "annotations": {"3": [{"type": "text", "text": "no id"}]}}, fh)
    store = open_store(video)
    (item,) = store.annotations[3]
    assert item["id"]
    store.save()
    assert disk_ids(video) == [item["id"]]


def test_ids_given_to_old_items_are_the_same_in_every_window(video):
    """id가 없거나 겹치는 옛 항목은 창마다·읽을 때마다 같은 id를 받음 (무작위면 저장할 때 항목이 불어남)."""
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    same = {"type": "text", "text": "same"}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"annotations": {"3": [dict(same), dict(same), {"id": "dup", "type": "text", "text": "a"},
                                         {"id": "dup", "type": "text", "text": "b"}]}}, fh)
    a = open_store(video)
    b = open_store(video)
    ids_a = [i["id"] for i in a.annotations[3]]
    assert ids_a == [i["id"] for i in b.annotations[3]]
    assert len(set(ids_a)) == 4 and ids_a[2] == "dup"
    a.update_by_id(ids_a[1], {"text": "edited"})
    a.save()
    b.save()  # 낡은 b가 저장해도 같은 항목이 두 개가 되지 않음
    assert len(disk_ids(video)) == 4
    assert sorted(memory_texts(open_store(video))) == ["a", "b", "edited", "same"]


def test_non_integer_frame_key_raises_instead_of_being_dropped(video):
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"annotations": {"abc": [{"id": "x", "type": "text"}]}}, fh)
    store = FrameAnnotationStore()
    store.set_video(video, 24.0)
    with pytest.raises(fa.AnnotationFileError, match="abc"):
        store.load()


def test_save_returns_path_and_writes_deleted_ids_key(video):
    store = open_store(video)
    store.add(0, text_item("x"))
    path = store.save()
    assert path == fa.annotation_file_path(video)
    assert disk_data(video)["deleted_ids"] == []


# ---------- 오류 ----------

def test_save_keeps_old_file_when_write_fails(video, monkeypatch):
    store = open_store(video)
    store.add(0, text_item("kept"))
    store.save()
    path = fa.annotation_file_path(video)
    with open(path, "rb") as fh:
        before = fh.read()

    extra = store.add(1, text_item("never reaches the disk"))

    def failing_replace(src, dst):
        raise OSError(errno.EIO, "Input/output error", dst)

    monkeypatch.setattr(user_files, "_replace", failing_replace)
    with pytest.raises(OSError):
        store.save()
    monkeypatch.undo()

    with open(path, "rb") as fh:
        assert fh.read() == before
    leftovers = [name for name in os.listdir(os.path.dirname(path)) if name != os.path.basename(path)]
    assert leftovers == []  # 임시 파일을 남기지 않음
    # 실패한 저장이 메모리를 바꾸지 않음 → 다시 저장하면 그 항목도 써짐
    assert extra["id"] in memory_ids(store)
    store.save()
    assert extra["id"] in disk_ids(video)


def test_corrupt_file_load_raises_annotation_file_error(video):
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"annotations": {"0": [')  # 쓰다 만 파일
    store = FrameAnnotationStore()
    store.set_video(video, 24.0)
    with pytest.raises(fa.AnnotationFileError) as excinfo:
        store.load()
    assert excinfo.value.path == path
    assert path in str(excinfo.value)
    assert "JSONDecodeError" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, user_files.UserFileError)
    assert store.annotations == {}


def test_save_over_corrupt_file_raises_and_leaves_it(video):
    store = open_store(video)
    store.add(0, text_item("mine"))
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("not json at all")
    with pytest.raises(fa.AnnotationFileError):
        store.save()
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "not json at all"


@pytest.mark.parametrize("content", ['["a list"]', '{"annotations": [1]}', '{"annotations": {"0": ["x"]}}',
                                     '{"annotations": {}, "deleted_ids": "abc"}'])
def test_wrong_shape_file_raises_annotation_file_error(video, content):
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    store = FrameAnnotationStore()
    store.set_video(video, 24.0)
    with pytest.raises(fa.AnnotationFileError) as excinfo:
        store.load()
    assert path in str(excinfo.value)


# ---------- 쓰기 확인·폴더 권한 ----------

def test_writable_check_concurrent_threads_both_true(video):
    """두 창(스레드)이 동시에 확인해도 서로의 시험 파일을 지우지 않아 둘 다 True."""
    os.makedirs(os.path.dirname(video), exist_ok=True)
    rounds = 60
    barrier = threading.Barrier(2)
    results = [[], []]
    errors = []

    def run(slot):
        try:
            for _ in range(rounds):
                barrier.wait(10)
                results[slot].append(fa.is_annotation_storage_writable(video))
        except Exception as exc:  # 스레드 안의 오류를 시험이 보게
            errors.append(exc)
            barrier.abort()

    threads = [threading.Thread(target=run, args=(slot,)) for slot in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    assert results[0] == [True] * rounds and results[1] == [True] * rounds
    assert os.listdir(fa.annotation_storage_dir(video)) == []  # 시험 파일을 남기지 않음


def test_writable_check_false_when_folder_cannot_be_made(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    assert fa.is_annotation_storage_writable(str(blocker / "scene.mov")) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 비트")
@pytest.mark.parametrize("how", ["writable_check", "save"])
def test_created_annotation_folder_is_shared(video, how):
    """내가 만든 .yesoncheck 폴더는 0o777로: 다른 NAS 계정(Windows)도 쓸 수 있게 (원자적 교체는 폴더 쓰기 권한이 필요)."""
    old_umask = os.umask(0o022)
    try:
        if how == "writable_check":
            assert fa.is_annotation_storage_writable(video)
        else:
            store = open_store(video)
            store.add(0, text_item("x"))
            store.save()
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(os.stat(fa.annotation_storage_dir(video)).st_mode) == 0o777


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 비트")
def test_existing_annotation_folder_keeps_its_mode(video):
    folder = fa.annotation_storage_dir(video)
    os.makedirs(folder)
    os.chmod(folder, 0o755)
    assert fa.is_annotation_storage_writable(video)
    store = open_store(video)
    store.add(0, text_item("x"))
    store.save()
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o755


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (Mac에서만 chmod)")
def test_annotation_folder_chmod_failure_is_not_fatal(video, monkeypatch, capsys):
    """권한을 바꾸지 못해도 폴더는 쓸 수 있음 → 저장은 되고, 이유는 로그와 share_problem으로."""
    def cannot_chmod(path, mode):
        raise PermissionError(errno.EPERM, "Operation not permitted", path)

    monkeypatch.setattr(fa, "_chmod", cannot_chmod)
    store = open_store(video)
    store.add(0, text_item("x"))
    store.save()
    folder = fa.annotation_storage_dir(video)
    assert disk_ids(video) == memory_ids(store)
    assert "Operation not permitted" in fa.annotation_share_problem(folder)
    assert "Operation not permitted" in capsys.readouterr().out
    assert fa.annotation_share_problem(folder + "_other") is None


# ---------- 플레이어 ----------

@pytest.fixture
def new_player(qapp, dialogs, monkeypatch, tmp_path):
    config = tmp_path / ".yesoncheck_config"
    config.mkdir()
    (config / "work_paths.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(config))
    from yesoncheck.main_window import VideoPlayer

    created = []

    def make():
        player = VideoPlayer()
        created.append(player)
        return player

    yield make
    for player in created:
        player.close()


@pytest.fixture
def real_video(tmp_path):
    return write_test_video(str(tmp_path / "videos" / "scene.mp4"))


def test_unreadable_annotation_file_shows_dialog_and_blocks_save(new_player, dialogs, real_video):
    video = real_video
    path = fa.annotation_file_path(video)
    os.makedirs(os.path.dirname(path))
    corrupt = '{"annotations": {"0": [{"id": "keep", "type": "text"'  # 쓰다 만 파일
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(corrupt)

    player = new_player()
    assert player.open_file("A", video)
    errors = dialogs.criticals
    assert len(errors) == 1, dialogs.messages
    assert path in errors[0] and "JSONDecodeError" in errors[0]
    assert player.annotation_store.total_count() == 0

    # 이 영상에서는 주석을 그려도 저장하지 않음 (읽지 못한 파일을 덮어 지우지 않게)
    player.annotation_store.add(0, text_item("drawn after the error"))
    assert player.auto_save_annotations() is False
    assert len(dialogs.criticals) == 1  # 저장마다 창이 뜨지 않음
    assert "주석 저장 안 함" in player.annotationStorageLabel.text()
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == corrupt
    assert os.listdir(os.path.dirname(path)) == [os.path.basename(path)]

    # 파일을 치운 뒤 영상을 다시 열면 다시 저장됨
    os.remove(path)
    assert player.open_file("A", video)
    player.annotation_store.add(0, text_item("saved again"))
    assert player.auto_save_annotations() is True
    assert disk_ids(video) == memory_ids(player.annotation_store)
    assert len(dialogs.criticals) == 1


def test_player_save_merges_items_from_another_window(new_player, dialogs, real_video):
    video = real_video
    player = new_player()
    assert player.open_file("A", video)
    other = open_store(video)  # 다른 창
    other_item = other.add(4, text_item("from the other window"))
    other.save()
    mine = player.annotation_store.add(0, text_item("mine"))
    assert player.auto_save_annotations() is True
    assert disk_ids(video) == sorted([mine["id"], other_item["id"]])
    assert other_item["id"] in memory_ids(player.annotation_store)
    assert player.annotationListWidget.count() == 2  # 다른 창의 항목이 목록에도 보임
    assert dialogs.errors() == []


def test_player_write_failure_shows_dialog_once_and_keeps_file(new_player, dialogs, real_video, monkeypatch):
    video = real_video
    player = new_player()
    assert player.open_file("A", video)
    player.annotation_store.add(0, text_item("kept"))
    assert player.auto_save_annotations() is True
    path = fa.annotation_file_path(video)
    with open(path, "rb") as fh:
        before = fh.read()

    def failing_replace(src, dst):
        raise OSError(errno.EIO, "Input/output error", dst)

    monkeypatch.setattr(user_files, "_replace", failing_replace)
    player.annotation_store.add(1, text_item("lost for now"))
    assert player.auto_save_annotations() is False
    assert player.auto_save_annotations() is False  # 자동 저장은 자주 불림 → 창은 한 번
    assert [(kind, title) for kind, title, _t in dialogs.errors()] == [("critical", "주석 저장 실패")]
    assert "Input/output error" in dialogs.errors()[0][2]
    assert "주석 저장 실패" in player.annotationStorageLabel.text()
    monkeypatch.undo()
    with open(path, "rb") as fh:
        assert fh.read() == before


def test_player_write_failure_logs_traceback(new_player, dialogs, real_video, monkeypatch, capsys):
    player = new_player()
    assert player.open_file("A", real_video)
    player.annotation_store.add(0, text_item("x"))

    def failing_replace(src, dst):
        raise OSError(errno.EIO, "Input/output error", dst)

    monkeypatch.setattr(user_files, "_replace", failing_replace)
    capsys.readouterr()
    assert player.auto_save_annotations() is False
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and "Input/output error" in captured.err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (Mac에서만 chmod)")
def test_player_tells_when_annotation_folder_cannot_be_shared(new_player, dialogs, real_video, monkeypatch):
    def cannot_chmod(path, mode):
        raise PermissionError(errno.EPERM, "Operation not permitted", path)

    monkeypatch.setattr(fa, "_chmod", cannot_chmod)
    player = new_player()
    assert player.open_file("A", real_video)
    player.annotation_store.add(0, text_item("x"))
    assert player.auto_save_annotations() is True  # 저장은 됨
    player.annotation_store.add(1, text_item("y"))
    assert player.auto_save_annotations() is True
    assert [(kind, title) for kind, title, _t in dialogs.errors()] == [("critical", "주석 폴더 권한")]
    assert "Operation not permitted" in dialogs.errors()[0][2]
