"""이 PC만의 작품 목록 (`local_works`) — 사내 공유 설정(NAS)을 찾지 못한 PC(회사 밖)에서 작품 → 폴더를 그 PC에 등록.

왜 (사용자 2026-11-27): "작품 경로 관리는 사내에서 작품 경로를 설정할 수 있는 기능이잖아. 이 기능을 외부 컴에서도 사용할 수 있게 하는
방법은 없어?" → 그 PC만의 목록, 단 "작품 폴더/시즌/job/영상 구조로만 구성되게 하면 안 돼. 이건 회사마다 상황이 다를 수 있어서" →
작품마다 '폴더를 몇 번 더 고를지'(0·1·2)를 정하고, 영상은 마지막으로 고른 폴더 아래를 폴더 열기와 같은 규칙으로(하위 폴더까지) 찾음.
여기는 저장과 규칙(Qt 없음) — 창은 test_local_works_ui. 예시 이름만 씀 (공개 저장소).
"""

import json
import os

import pytest

from yesoncheck import local_works, mac_prefs
from yesoncheck.local_works import LocalWork
from yesoncheck.user_files import UserFileError


@pytest.fixture
def prefs(tmp_path):
    return str(tmp_path / "settings" / "prefs.json")


def work(tmp_path, name="MyShow", levels=1):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return LocalWork(name, str(folder), levels)


def test_no_file_means_no_works(prefs):
    assert local_works.read(prefs) == []
    assert not os.path.exists(prefs)  # 읽기만으로 파일을 만들지 않음


def test_added_works_are_read_back_in_order(prefs, tmp_path):
    first, second = work(tmp_path, "MyShow", 2), work(tmp_path, "Shorts", 0)

    assert local_works.add(first, prefs) == [first]
    assert local_works.add(second, prefs) == [first, second]

    assert local_works.read(prefs) == [first, second]
    with open(prefs, encoding="utf-8") as fh:
        assert json.load(fh) == {"local_works": [
            {"name": "MyShow", "folder": first.folder, "levels": 2}, {"name": "Shorts", "folder": second.folder, "levels": 0}]}


def test_other_settings_in_the_file_are_kept(prefs, tmp_path):
    mac_prefs.update_pref("slider_thumbnails", False, prefs)

    local_works.add(work(tmp_path), prefs)
    local_works.remove("MyShow", prefs)

    assert mac_prefs.read_prefs(prefs) == {"slider_thumbnails": False, "local_works": []}


def test_a_name_is_registered_once(prefs, tmp_path):
    local_works.add(work(tmp_path, "MyShow", 1), prefs)

    with pytest.raises(ValueError, match="이미 있는 작품"):
        local_works.add(work(tmp_path, "MyShow", 2), prefs)

    assert [w.levels for w in local_works.read(prefs)] == [1]


@pytest.mark.parametrize("bad, word", [
    (LocalWork("", "/projects/a", 1), "이름"),
    (LocalWork("  ", "/projects/a", 1), "이름"),
    (LocalWork("MyShow", "relative/folder", 1), "처음부터 적은 경로"),
    (LocalWork("MyShow", "", 1), "처음부터 적은 경로"),
    (LocalWork("MyShow", "/projects/a", 3), "단계"),
    (LocalWork("MyShow", "/projects/a", True), "단계"),
    (LocalWork("MyShow", "/projects/a", "1"), "단계"),
], ids=["no_name", "blank_name", "relative", "no_folder", "too_deep", "bool_levels", "text_levels"])
def test_a_work_that_makes_no_sense_is_refused_before_writing(prefs, bad, word):
    if bad.folder.startswith("/") and os.name == "nt":
        bad = LocalWork(bad.name, "C:" + bad.folder.replace("/", "\\"), bad.levels)
    with pytest.raises(ValueError, match=word):
        local_works.add(bad, prefs)
    assert not os.path.exists(prefs)


def test_changing_the_folder_or_the_levels_keeps_the_place_in_the_list(prefs, tmp_path):
    first, second = work(tmp_path, "MyShow", 2), work(tmp_path, "Shorts", 0)
    local_works.add(first, prefs)
    local_works.add(second, prefs)
    moved = tmp_path / "moved"
    moved.mkdir()

    local_works.change("MyShow", prefs, folder=str(moved))
    after = local_works.change("MyShow", prefs, levels=0)

    assert after == [LocalWork("MyShow", str(moved), 0), second] == local_works.read(prefs)


def test_changing_a_work_that_is_not_there_says_so(prefs, tmp_path):
    local_works.add(work(tmp_path), prefs)
    with pytest.raises(LookupError, match="Nope"):
        local_works.change("Nope", prefs, levels=0)
    with pytest.raises(ValueError, match="단계"):
        local_works.change("MyShow", prefs, levels=5)
    assert local_works.read(prefs) == [work(tmp_path)]


def test_removing_keeps_the_others(prefs, tmp_path):
    first, second = work(tmp_path, "MyShow"), work(tmp_path, "Shorts")
    local_works.add(first, prefs)
    local_works.add(second, prefs)

    assert local_works.remove("MyShow", prefs) == [second]
    assert local_works.remove("MyShow", prefs) == [second]  # 없는 이름은 그대로


def test_a_work_added_by_another_window_is_not_lost(prefs, tmp_path):
    """창마다 프로세스 — 잠금 안에서 다시 읽고 고침: 이 창이 읽은 뒤 다른 창이 더한 작품을 덮어 지우지 않음."""
    mine, theirs = work(tmp_path, "MyShow"), work(tmp_path, "Shorts")
    local_works.add(mine, prefs)
    stale = local_works.read(prefs)  # 이 창이 읽어 둔 목록
    local_works.add(theirs, prefs)  # (다른 창)

    local_works.change("MyShow", prefs, levels=0)

    assert stale == [mine]
    assert local_works.read(prefs) == [LocalWork("MyShow", mine.folder, 0), theirs]


@pytest.mark.parametrize("stored", [
    {"local_works": "MyShow"},
    {"local_works": [["MyShow", "/projects/a", 1]]},
    {"local_works": [{"name": "MyShow", "folder": "/projects/a"}]},
    {"local_works": [{"name": "MyShow", "folder": "/projects/a", "levels": 7}]},
    {"local_works": [{"name": 3, "folder": "/projects/a", "levels": 1}]},
], ids=["not_a_list", "not_objects", "missing_key", "bad_levels", "bad_name"])
def test_a_list_of_the_wrong_shape_is_an_error_and_is_not_overwritten(prefs, tmp_path, stored):
    """모양이 틀린 목록을 빈 목록으로 치지 않음 — 다음 저장이 덮어 지우지 않게 읽기도 쓰기도 UserFileError."""
    os.makedirs(os.path.dirname(prefs))
    with open(prefs, "w", encoding="utf-8") as fh:
        json.dump(stored, fh)

    with pytest.raises(UserFileError, match="local_works"):
        local_works.read(prefs)
    with pytest.raises(UserFileError, match="local_works"):
        local_works.add(work(tmp_path), prefs)

    with open(prefs, encoding="utf-8") as fh:
        assert json.load(fh) == stored


def test_a_broken_file_is_an_error(prefs):
    os.makedirs(os.path.dirname(prefs))
    with open(prefs, "w", encoding="utf-8") as fh:
        fh.write("{ 깨짐")
    with pytest.raises(UserFileError):
        local_works.read(prefs)


def test_the_default_place_is_this_pcs_settings_file(monkeypatch, tmp_path):
    from yesoncheck import hover_strip

    place = str(tmp_path / "prefs.json")
    monkeypatch.setattr(hover_strip, "prefs_path", lambda: place)

    local_works.add(work(tmp_path))

    assert local_works.read() == [work(tmp_path)] and os.path.isfile(place)


# ---------------------------------------------------------------- 고르기 규칙

def test_level_texts_say_how_many_folders_are_picked():
    assert [local_works.level_text(levels) for levels in local_works.LEVELS] == [
        "작품을 고르면 바로 영상 목록", "작품 → 폴더 하나를 더 고름", "작품 → 폴더 → 폴더 (두 번 더 고름)"]
    with pytest.raises(ValueError):
        local_works.level_text(3)


def test_subfolders_are_the_visible_folders_in_number_order(tmp_path):
    for name in ("ep10", "ep2", "EP1", ".yesoncheck", ".hidden", "@eaDir"):
        (tmp_path / name).mkdir()
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "clip.mov").write_text("x")

    assert local_works.subfolders(str(tmp_path)) == ["EP1", "ep2", "ep10"]


def test_subfolders_of_a_folder_that_cannot_be_read_raise(tmp_path):
    with pytest.raises(OSError):
        local_works.subfolders(str(tmp_path / "gone"))


def test_the_folder_to_list_is_the_work_folder_plus_what_was_picked(tmp_path):
    deep = LocalWork("MyShow", str(tmp_path), 2)

    assert local_works.picked_folder(LocalWork("MyShow", str(tmp_path), 0), []) == str(tmp_path)
    assert local_works.picked_folder(LocalWork("MyShow", str(tmp_path), 1), ["ep01"]) == os.path.join(str(tmp_path), "ep01")
    assert local_works.picked_folder(deep, ["s1", "ep01"]) == os.path.join(str(tmp_path), "s1", "ep01")
    with pytest.raises(ValueError, match="2번"):
        local_works.picked_folder(deep, ["s1"])  # 아직 다 고르지 않음


def test_module_has_no_qt():
    import subprocess
    import sys

    code = "import sys; import yesoncheck.local_works; print(any(name.startswith('PyQt5') for name in sys.modules))"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip() == "False"
