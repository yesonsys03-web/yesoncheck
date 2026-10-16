"""사이드바 영상 목록을 디스크에서 읽는 규칙 (yesoncheck/video_list.py — Qt 없음).

처음 불러올 때(update_playlist·폴더 불러오기·끌어다 놓기)와 목록 다시 읽기가 같은 함수를 써서 규칙이 어긋나지 않게 함.
사용자 보고 (2026-10-16): FL_904 목록을 띄운 뒤 NAS에서 scene 폴더 22개를 지웠는데 목록에 그대로 남아 있었고,
누르면 아무 말 없이 영상이 멈췄음.
"""

import errno
import locale
import os
import sys

import pytest

from yesoncheck import paths, video_list
from yesoncheck.video_list import FOLDER_GONE, ListSource, ScanResult


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return str(path)


def names(result):
    return [name for name, _path in result.videos]


# ---- job 폴더 규칙 (update_playlist에서 옮김) ----

def test_default_rule_job_folder_and_scene_frames(tmp_path):
    """기본(Harmony scene 구조): job 폴더 바로 안 + 하위 폴더마다 frames 안. 숨김·._·다른 확장자는 빼고 확장자 대소문자 무시."""
    job = tmp_path / "job"
    touch(job / "top.mov")
    touch(job / "scene-001" / "frames" / "b.mov")
    touch(job / "scene-001" / "frames" / "A.MOV")
    touch(job / "scene-001" / "frames" / "._b.mov")
    touch(job / "scene-001" / "frames" / ".hidden.mp4")
    touch(job / "scene-001" / "frames" / "note.txt")
    touch(job / "scene-001" / "c.mov")  # frames 밖은 아님
    (job / "scene-002").mkdir()  # frames 없음
    touch(job / ".yesoncheck_thumb" / "x.jpg")
    touch(job / "scene-003" / "frames" / "d.mp4")
    touch(job / "scene-004" / "frames" / "sub" / "e.mov")  # frames 아래 하위 폴더는 아님

    result = video_list.scan_job("FL", str(job))
    assert sorted(names(result)) == ["A.MOV", "b.mov", "d.mp4", "top.mov"]
    assert result.unreadable == []
    by_name = dict(result.videos)
    assert by_name["b.mov"] == os.path.join(str(job), "scene-001", "frames", "b.mov")
    assert by_name["top.mov"] == os.path.join(str(job), "top.mov")


@pytest.mark.parametrize("work, sub", [("BB_Animatic", "Quicktime"), ("TGN_Animatic", "ANIMATIC")])
def test_animatic_rules_use_their_subfolder(tmp_path, work, sub):
    job = tmp_path / "job"
    touch(job / "s1" / sub / "a.mov")
    touch(job / "s1" / "frames" / "not_this.mov")
    result = video_list.scan_job(work, str(job))
    assert names(result) == ["a.mov"]


def test_bm_animatic_uses_animatic_folder_only(tmp_path):
    job = tmp_path / "job"
    touch(job / "top.mov")
    touch(job / "ANIMATIC" / "a.mov")
    touch(job / "s1" / "frames" / "not_this.mov")
    assert sorted(names(video_list.scan_job("BM_Animatic", str(job)))) == ["a.mov", "top.mov"]


def test_koth_animatic_uses_folders_named_animatic(tmp_path):
    """시즌 15까지 'POST-LOCK ANIMATIC', 시즌 16부터 '1601_ANIMATIC'·'1604_ANIMATICS' (대소문자 무시)."""
    job = tmp_path / "job"
    touch(job / "POST-LOCK ANIMATIC" / "a.mov")
    touch(job / "1604_animatics" / "b.mov")
    touch(job / "other" / "frames" / "not_this.mov")
    touch(job / "ANIMATIC.mov")  # 파일 (폴더가 아님)
    assert sorted(names(video_list.scan_job("KOTH_Animatic", str(job)))) == ["ANIMATIC.mov", "a.mov", "b.mov"]


def test_ms_animatic_uses_job_folder_only(tmp_path):
    job = tmp_path / "job"
    touch(job / "a.mov")
    touch(job / "s1" / "frames" / "not_this.mov")
    assert names(video_list.scan_job("MS_Animatic", str(job))) == ["a.mov"]


def test_tjs_animatic_job_folder_and_one_level_of_subfolders(tmp_path):
    job = tmp_path / "TJS_921"
    touch(job / "a.mov")
    os.makedirs(job / "folder.mov")  # 이름만 영상인 폴더는 아님
    touch(job / "ANIMATIC" / "b.MP4")
    touch(job / "ANIMATIC" / "deeper" / "not_this.mov")
    touch(job / ".hidden" / "not_this.mov")
    touch(job / "ANIMATIC" / ".c.mov")
    assert sorted(names(video_list.scan_job("TJS_Animatic", str(job)))) == ["a.mov", "b.MP4"]


def test_sort_non_hd_first_then_hd_each_in_locale_order(tmp_path):
    job = tmp_path / "job"
    files = ["FL_904_B001_TK1_HD.mov", "fl_904_a002_TK1.mov", "FL_904_A001_TK1.mov", "FL_904_A001_TK1_HD.mov",
             "FL_904_Z007_TK1.mov"]
    for name in files:
        touch(job / "scene" / "frames" / name)
    result = names(video_list.scan_job("FL", str(job)))
    non_hd = [n for n in files if "_HD" not in n]
    hd = [n for n in files if "_HD" in n]
    # scan_job이 정렬용 locale을 정한 뒤의 locale 순서
    assert result == sorted(non_hd, key=locale.strxfrm) + sorted(hd, key=locale.strxfrm)
    assert result[-2:] == ["FL_904_A001_TK1_HD.mov", "FL_904_B001_TK1_HD.mov"]


def test_job_folder_unreadable_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        video_list.scan_job("FL", str(tmp_path / "missing"))


def fail_listing(monkeypatch, failing, error):
    """failing 폴더를 읽으면(scandir) error가 나게."""
    real_scandir = os.scandir

    def scandir(path="."):
        if not isinstance(path, int) and os.path.normpath(os.fspath(path)) == os.path.normpath(str(failing)):
            raise error
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)


def test_unreadable_subfolder_is_reported_not_skipped(tmp_path, monkeypatch):
    """하위 폴더를 읽지 못하면 그 폴더를 결과에 남김 (그 안의 영상은 알 수 없음 — 다시 읽기는 그 영상들을 그대로 둠)."""
    job = tmp_path / "job"
    kept = touch(job / "scene-001" / "frames" / "a.mov")
    hidden = touch(job / "scene-002" / "frames" / "b.mov")
    error = PermissionError(errno.EACCES, "Permission denied", str(job / "scene-002" / "frames"))
    fail_listing(monkeypatch, job / "scene-002" / "frames", error)

    result = video_list.scan_job("FL", str(job))
    assert names(result) == ["a.mov"]
    assert [(os.path.normpath(folder), err) for folder, err in result.unreadable] == [
        (os.path.normpath(str(job / "scene-002" / "frames")), error)]
    assert result.keeps(kept) and result.keeps(hidden)
    assert not result.keeps(str(job / "scene-003" / "frames" / "c.mov"))


def test_share_lost_during_scan_raises(tmp_path, monkeypatch):
    """하위 폴더를 읽는 사이 공유가 끊겨(Windows는 FileNotFoundError) frames가 '없음'으로 보였으면 결과를 쓰지 않음."""
    job = tmp_path / "job"
    touch(job / "scene-001" / "frames" / "a.mov")
    real_stat = os.stat
    calls = []

    def stat(path, *args, **kwargs):
        if os.path.normpath(os.fspath(path)) == os.path.normpath(str(job)):
            calls.append(path)
            raise FileNotFoundError(errno.ENOENT, "The network path was not found", str(job))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(video_list.os, "stat", stat)
    with pytest.raises(FileNotFoundError):
        video_list.scan_job("FL", str(job))
    assert calls


# ---- 폴더 규칙 (폴더 불러오기·끌어다 놓기·북마크) ----

def test_folder_rule_recursive_video_extensions_natural_order(tmp_path):
    folder = tmp_path / "clips"
    touch(folder / "clip10.mov")
    touch(folder / "clip2.MKV")
    touch(folder / "sub" / "clip1.mp4")
    touch(folder / ".hidden.mov")
    touch(folder / "notes.txt")
    touch(folder / ".yesoncheck_thumb" / "x.jpg")
    result = video_list.scan_folder(str(folder))
    assert names(result) == ["clip1.mp4", "clip2.MKV", "clip10.mov"]
    assert dict(result.videos)["clip1.mp4"] == os.path.join(str(folder), "sub", "clip1.mp4")


def test_folder_rule_unreadable_folder(tmp_path, monkeypatch):
    folder = tmp_path / "clips"
    touch(folder / "a.mov")
    touch(folder / "sub" / "b.mov")
    with pytest.raises(FileNotFoundError):
        video_list.scan_folder(str(tmp_path / "missing"))
    error = PermissionError(errno.EACCES, "Permission denied", str(folder / "sub"))
    fail_listing(monkeypatch, folder / "sub", error)
    result = video_list.scan_folder(str(folder))
    assert names(result) == ["a.mov"]
    assert [err for _folder, err in result.unreadable] == [error]
    assert result.keeps(str(folder / "sub" / "b.mov"))


def test_scan_source_dispatches(tmp_path):
    touch(tmp_path / "job" / "s" / "frames" / "a.mov")
    touch(tmp_path / "job" / "s" / "b.mov")
    assert names(video_list.scan_source(ListSource("job", str(tmp_path / "job"), "FL"))) == ["a.mov"]
    assert names(video_list.scan_source(ListSource("folder", str(tmp_path / "job")))) == ["a.mov", "b.mov"]


# ---- 없어진 폴더 / 읽지 못하는 폴더 ----

def test_is_gone_walks_up_to_first_existing_folder(tmp_path):
    """없어짐: FileNotFoundError이고 위로 올라가 처음 확인되는 폴더가 공유 안 (바로 위 폴더만 보지 않음).
    리뷰 M1: 따로 넣은 …/scene-Z007/frames/X.mov의 scene-Z007이 통째로 지워지면 '확인하지 못함'으로 영원히 남았음."""
    (tmp_path / "season" / "job" / "scene-Z008").mkdir(parents=True)  # 남은 scene
    video = str(tmp_path / "season" / "job" / "scene-Z007" / "frames" / "X.mov")  # scene-Z007이 지워짐
    missing = FileNotFoundError(errno.ENOENT, "No such file or directory", video)
    assert video_list.is_gone(video, missing) is True
    gone_job = str(tmp_path / "season" / "gone_job")  # job 폴더 (목록 출처)
    assert video_list.is_gone(gone_job, missing) is True
    assert video_list.is_gone(gone_job + os.sep, missing) is True  # 끝에 / (job을 고르지 않은 목록)
    assert video_list.is_gone(str(tmp_path / "gone_season" / "job"), missing) is True  # 위 폴더까지 지워짐
    assert video_list.is_gone(gone_job, PermissionError(errno.EACCES, "Permission denied", gone_job)) is False
    assert video_list.is_gone(gone_job, TimeoutError(errno.ETIMEDOUT, "Operation timed out", gone_job)) is False


def test_is_gone_false_when_first_existing_folder_unreadable(tmp_path, monkeypatch):
    """위 폴더를 확인하다 다른 오류(권한·시간 초과)가 나면 없어진 것으로 보지 않음."""
    real_stat = os.stat
    season = str(tmp_path / "season")

    def stat(path, *args, **kwargs):
        if os.path.normpath(os.fspath(path)) == os.path.normpath(season):
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", season)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(video_list.os, "stat", stat)
    gone_job = os.path.join(season, "job")
    assert video_list.is_gone(gone_job, FileNotFoundError(errno.ENOENT, "No such file", gone_job)) is False


@pytest.mark.skipif(sys.platform == "win32", reason="Mac: /Volumes 아래 공유 (Windows는 \\\\서버\\공유 위로 올라가지 않음)")
def test_is_gone_false_for_unmounted_mac_share(tmp_path, monkeypatch):
    """Mac에서 공유를 떼면 /Volumes/x가 없어지거나 빈 폴더로 남음 → 그 아래 영상은 '없어짐'이 아니라 '확인하지 못함'."""
    volumes = tmp_path / "Volumes"
    (volumes / "stale").mkdir(parents=True)  # 떼고 남은 빈 폴더
    monkeypatch.setattr(video_list, "MAC_MOUNT_PARENT", os.path.realpath(str(volumes)))
    for video in (volumes / "colordata" / "FLORIDA" / "a.mov",  # /Volumes/colordata가 없어짐 → /Volumes까지 올라감
                  volumes / "stale" / "FLORIDA" / "a.mov"):
        error = FileNotFoundError(errno.ENOENT, "No such file or directory", str(video))
        assert video_list.is_gone(str(video), error) is False, video


@pytest.mark.skipif(sys.platform == "win32", reason="Mac: 붙인 공유(autofs 포함)의 맨 위 폴더")
def test_is_gone_at_mount_root_needs_entries(tmp_path, monkeypatch):
    """처음 확인되는 폴더가 붙인 공유의 맨 위 폴더면 그 안에 무엇이 있어야 없어진 것 (리뷰 L10: 공유 바로 아래 출처).
    autofs 트리거·떼고 남은 빈 마운트 폴더는 비어 있음 → '확인하지 못함'."""
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(video_list, "_is_mount_root",
                        lambda folder: os.path.realpath(folder) == os.path.realpath(str(share)))
    job = str(share / "FL_904")
    error = FileNotFoundError(errno.ENOENT, "No such file or directory", job)
    assert video_list.is_gone(job, error) is False  # 빈 마운트 폴더 (autofs 트리거 등)
    (share / "FL_902").mkdir()
    assert video_list.is_gone(job, error) is True  # 공유가 붙어 있고 FL_904만 없어짐


def test_read_sources_classifies_each_source_and_file(tmp_path, monkeypatch):
    """목록 다시 읽기의 디스크 읽기 (GUI 밖 스레드에서): 출처마다 결과, 따로 넣은 파일마다 있는지."""
    touch(tmp_path / "ok" / "a.mov")
    (tmp_path / "locked").mkdir()
    ok, gone, locked = (ListSource("folder", str(tmp_path / name)) for name in ("ok", "gone", "locked"))
    denied = PermissionError(errno.EACCES, "Permission denied", str(tmp_path / "locked"))
    fail_listing(monkeypatch, tmp_path / "locked", denied)
    kept = touch(tmp_path / "files" / "keep.mov")
    removed = str(tmp_path / "deleted_scene" / "frames" / "gone.mov")

    read = video_list.read_sources([ok, gone, locked], [kept, removed])

    assert names(read.results[ok]) == ["a.mov"]
    assert read.results[gone] is FOLDER_GONE and isinstance(read.errors[gone], FileNotFoundError)
    assert read.results[locked] is None and read.errors[locked] is denied
    assert ok not in read.errors
    assert read.gone_files == {paths.path_key(removed)}
    assert read.unverified == []


def test_sort_fallback_logs_traceback(tmp_path, monkeypatch, capsys):
    """locale 정렬이 실패하면 소문자 이름 순서로 — 이유는 스택 트레이스째 로그에 (리뷰 L12)."""
    def broken(text):
        raise ValueError("strxfrm 실패")

    monkeypatch.setattr(video_list.locale, "strxfrm", broken)
    assert names(video_list.ScanResult(video_list.sort_job_videos([("b.mov", "b"), ("A.mov", "a")]))) == ["A.mov", "b.mov"]
    log = capsys.readouterr()
    assert "locale 정렬 실패" in log.out and "Traceback" in log.err and "strxfrm 실패" in log.err


# ---- 다시 읽기 계획 (지금 목록 + 읽은 결과 → 뺄 줄·새 목록) ----

JOB = ListSource("job", "/w/S1/job", "FL")
DROP = ListSource("folder", "/d/other")


def result_of(*file_paths, unreadable=()):
    return ScanResult([(os.path.basename(p), p) for p in file_paths], list(unreadable))


def apply(rows, plan):
    """계획대로 바꾼 목록 [(경로, 출처)]."""
    removed, final = plan
    assert removed == sorted(removed)
    kept = {r for r in range(len(rows))} - set(removed)
    out = []
    for entry in final:
        if isinstance(entry, int):
            assert entry in kept
            out.append(rows[entry])
        else:
            source, _name, path = entry
            out.append((path, source))
    return out


def test_plan_removes_missing_and_inserts_new_in_sorted_place():
    rows = [("/j/a.mov", JOB), ("/j/b.mov", JOB), ("/j/d.mov", JOB)]
    result = result_of("/j/a.mov", "/j/c.mov", "/j/d.mov", "/j/e.mov")
    plan = video_list.plan_refresh(rows, {JOB: result}, set())
    assert plan[0] == [1]
    assert apply(rows, plan) == [(p, JOB) for p in ("/j/a.mov", "/j/c.mov", "/j/d.mov", "/j/e.mov")]
    assert video_list.plan_changes(plan)


def test_plan_unchanged_list_is_no_op():
    rows = [("/j/a.mov", JOB), ("/j/b.mov", JOB)]
    plan = video_list.plan_refresh(rows, {JOB: result_of("/j/a.mov", "/j/b.mov")}, set())
    assert plan == ([], [0, 1])
    assert not video_list.plan_changes(plan)


def test_plan_new_item_before_first_kept_item():
    rows = [("/j/b.mov", JOB)]
    plan = video_list.plan_refresh(rows, {JOB: result_of("/j/a.mov", "/j/b.mov")}, set())
    assert apply(rows, plan) == [("/j/a.mov", JOB), ("/j/b.mov", JOB)]


def test_plan_keeps_items_of_unreadable_source_and_folders():
    rows = [("/j/s1/frames/a.mov", JOB), ("/j/s2/frames/b.mov", JOB), ("/d/other/c.mov", DROP)]
    # job은 읽었지만 s2/frames를 읽지 못함, 끌어다 놓은 폴더는 아예 읽지 못함(None)
    result = result_of("/j/s1/frames/a.mov", unreadable=[("/j/s2/frames", PermissionError("denied"))])
    plan = video_list.plan_refresh(rows, {JOB: result, DROP: None}, set())
    assert plan == ([], [0, 1, 2])


def test_plan_removes_items_of_gone_source():
    rows = [("/j/a.mov", JOB), ("/d/other/c.mov", DROP)]
    plan = video_list.plan_refresh(rows, {JOB: FOLDER_GONE, DROP: result_of("/d/other/c.mov")}, set())
    assert apply(rows, plan) == [("/d/other/c.mov", DROP)]


def test_plan_individual_files_kept_while_they_exist():
    rows = [("/f/a.mov", None), ("/f/b.mov", None)]
    plan = video_list.plan_refresh(rows, {}, {paths.path_key("/f/b.mov")})
    assert apply(rows, plan) == [("/f/a.mov", None)]


def test_plan_each_source_keeps_its_place():
    """덧붙인 목록(job + 끌어다 놓은 폴더): 새 영상은 자기 출처의 영상들 사이·뒤에. 남은 영상이 없는 출처는 맨 뒤에."""
    gone_src = ListSource("folder", "/d/empty")
    rows = [("/j/a.mov", JOB), ("/j/c.mov", JOB), ("/d/other/x.mov", DROP), ("/d/empty/old.mov", gone_src)]
    results = {
        JOB: result_of("/j/a.mov", "/j/c.mov", "/j/d.mov"),
        DROP: result_of("/d/other/w.mov", "/d/other/x.mov"),
        gone_src: result_of("/d/empty/new.mov"),
    }
    plan = video_list.plan_refresh(rows, results, set())
    assert apply(rows, plan) == [
        ("/j/a.mov", JOB), ("/j/c.mov", JOB), ("/j/d.mov", JOB),
        ("/d/other/w.mov", DROP), ("/d/other/x.mov", DROP),
        ("/d/empty/new.mov", gone_src),
    ]


def test_plan_same_video_from_two_sources():
    """같은 영상이 두 출처로 목록에 있으면(job + 그 job 폴더를 끌어다 놓음) 출처마다 따로 맞춤."""
    rows = [("/j/a.mov", JOB), ("/j/a.mov", DROP)]
    results = {JOB: result_of("/j/a.mov", "/j/b.mov"), DROP: result_of("/j/a.mov")}
    plan = video_list.plan_refresh(rows, results, set())
    assert apply(rows, plan) == [("/j/a.mov", JOB), ("/j/b.mov", JOB), ("/j/a.mov", DROP)]


def test_plan_compares_windows_paths_by_key(monkeypatch):
    """Windows: 목록의 UNC 경로와 다시 읽은 경로는 대소문자·구분자가 달라도 같은 영상 (paths.path_key)."""
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)
    paths._cached_remote_name.cache_clear()
    try:
        source = ListSource("job", "\\\\Mainnas\\usadata2\\FL\\S1\\FL_904", "FL")
        listed = "\\\\Mainnas\\usadata2\\FL\\S1\\FL_904\\scene-A001\\frames\\FL_904_A001_TK1.mov"
        rescanned = "//MAINNAS/USADATA2/FL/S1/FL_904/scene-A001/frames/fl_904_a001_tk1.MOV"
        unreadable = [("\\\\MAINNAS\\usadata2\\fl\\s1\\fl_904\\scene-Z007\\frames", PermissionError("denied"))]
        rows = [(listed, source), ("\\\\Mainnas\\usadata2\\FL\\S1\\FL_904\\scene-Z007\\frames\\Z007.mov", source)]
        plan = video_list.plan_refresh(rows, {source: result_of(rescanned, unreadable=unreadable)}, set())
        assert plan == ([], [0, 1])
    finally:
        paths._cached_remote_name.cache_clear()


# ---- 2차 검토: 끊긴 공유의 영상을 '없어짐'으로 보지 않음 ----

def fail_stat_under(monkeypatch, root, error_for):
    """root 아래(root 포함) 경로의 os.stat이 error_for(경로)를 올림 — 응답 없는 마운트·자동 연결(autofs) 폴더 흉내."""
    real_stat = os.stat
    root = os.path.normpath(str(root))

    def stat(path, *args, **kwargs):
        p = os.path.normpath(os.fspath(path))
        if p == root or p.startswith(root + os.sep):
            raise error_for(p)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(video_list.os, "stat", stat)


def enoent(path):
    return FileNotFoundError(errno.ENOENT, "No such file or directory", path)


@pytest.mark.skipif(sys.platform == "win32", reason="Mac 폴더 구조 (/, /Volumes, /System/Volumes/Data)")
def test_is_gone_false_when_nearest_is_mac_local_root(tmp_path, monkeypatch):
    """처음 확인되는 폴더가 /System/Volumes/Data(autofs 마운트들의 위)·/Volumes면 — 그 장치가 /와 다르게 보여도(마운트의
    맨 위처럼 보여도) — 없어진 것으로 보지 않음 (2차 검토 OQ1·OQ2)."""
    data = tmp_path / "Data"
    (data / "other").mkdir(parents=True)
    volumes = tmp_path / "Volumes"
    (volumes / "Macintosh HD").mkdir(parents=True)
    monkeypatch.setattr(video_list, "MAC_LOCAL_ROOTS", ("/", os.path.realpath(str(data))))
    monkeypatch.setattr(video_list, "MAC_MOUNT_PARENT", os.path.realpath(str(volumes)))
    real_is_mount_root = video_list._is_mount_root
    monkeypatch.setattr(video_list, "_is_mount_root",  # 예전 macOS: /Volumes·Data 볼륨의 장치가 /와 다름
                        lambda folder: os.path.realpath(folder) in (os.path.realpath(str(data)),
                                                                    os.path.realpath(str(volumes)))
                        or real_is_mount_root(folder))
    for video in (data / "usadata2" / "FLORIDA" / "S1" / "FL_904" / "a.mov",
                  volumes / "colordata" / "FLORIDA" / "a.mov"):
        assert video_list.is_gone(str(video), enoent(str(video))) is False, video


def test_is_gone_false_when_missing_child_is_still_listed(tmp_path, monkeypatch):
    """위 폴더 목록에는 보이는데 열리지 않는 폴더(자동 연결 폴더의 서버가 꺼짐 — 예: ~/Desktop/usadata4) 아래는 확인하지 못함."""
    desktop = tmp_path / "Desktop"
    (desktop / "usadata4").mkdir(parents=True)
    (desktop / "notes").mkdir()
    fail_stat_under(monkeypatch, desktop / "usadata4", enoent)
    video = str(desktop / "usadata4" / "x" / "y.mov")
    gone, detail = video_list.check_gone(video, enoent(video))
    assert gone is False
    assert "usadata4" in detail and str(desktop) in detail


def test_is_gone_false_when_nearest_folder_is_empty(tmp_path):
    """처음 확인되는 폴더가 비어 있으면(공유를 떼고 남은 마운트 폴더일 수 있음) 없어진 것으로 보지 않음."""
    (tmp_path / "mnt" / "share").mkdir(parents=True)
    video = str(tmp_path / "mnt" / "share" / "FLORIDA" / "a.mov")
    gone, detail = video_list.check_gone(video, enoent(video))
    assert gone is False and "비어" in detail


def test_is_gone_false_when_path_is_back(tmp_path, monkeypatch):
    """L3: 위 폴더를 확인한 뒤 영상을 다시 확인 — 그사이 다시 보이면(Windows SMB 다시 연결) 없어진 것이 아님."""
    job = tmp_path / "job"
    (job / "other").mkdir(parents=True)
    video = str(job / "scene" / "frames" / "a.mov")
    real_listdir = os.listdir

    def listdir(path="."):
        names = real_listdir(path)
        if os.path.normpath(os.fspath(path)) == os.path.normpath(str(job)):
            touch(video)  # 위 폴더 목록을 읽은 바로 뒤 공유가 다시 연결됨
        return names

    monkeypatch.setattr(video_list.os, "listdir", listdir)
    gone, detail = video_list.check_gone(video, enoent(video))
    assert gone is False and "다시 확인" in detail and video in detail


def test_check_gone_detail_names_unreadable_ancestor(tmp_path, monkeypatch):
    """L4: 위 폴더를 확인하다 난 오류(경로·오류)는 삼키지 않고 알림 문구로."""
    season = tmp_path / "season"
    season.mkdir()
    fail_stat_under(monkeypatch, season, lambda p: TimeoutError(errno.ETIMEDOUT, "Operation timed out", p))
    job = str(season / "job")
    gone, detail = video_list.check_gone(job, enoent(job))
    assert gone is False
    assert str(season) in detail and "TimeoutError" in detail and "Operation timed out" in detail


def test_scene_folder_lost_during_scan_is_unreadable_not_empty(tmp_path, monkeypatch):
    """L3: frames를 읽을 때 FileNotFoundError이고 방금 목록에 있던 scene 폴더도 확인되지 않으면(SMB가 잠깐 끊김)
    'frames 없음'이 아니라 읽지 못한 폴더 — 그 아래 영상은 그대로 둠."""
    job = tmp_path / "job"
    kept = touch(job / "scene-001" / "frames" / "a.mov")
    lost = touch(job / "scene-002" / "frames" / "b.mov")
    scene2 = os.path.normpath(str(job / "scene-002"))
    real_scandir = os.scandir
    real_stat = os.stat

    def scandir(path="."):
        if not isinstance(path, int) and os.path.normpath(os.fspath(path)).startswith(scene2):
            raise enoent(os.fspath(path))
        return real_scandir(path)

    def stat(path, *args, **kwargs):
        if os.path.normpath(os.fspath(path)).startswith(scene2):
            raise enoent(os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    monkeypatch.setattr(video_list.os, "stat", stat)
    result = video_list.scan_job("FL", str(job))
    assert names(result) == ["a.mov"]
    assert [os.path.normpath(folder) for folder, _e in result.unreadable] == [scene2]
    assert result.keeps(lost) and result.keeps(kept)


def walk_reference(folder):
    """예전 get_video_files_from_folder (os.walk) — 읽을 수 있는 폴더에서 scan_folder와 같아야 함."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if not name.startswith('.') and os.path.splitext(name.lower())[1] in video_list.VIDEO_EXTENSIONS:
                found.append(os.path.join(root, name))
    return sorted(found, key=lambda p: (video_list.natural_key(p), p))


def test_scan_folder_same_as_os_walk(tmp_path):
    """L5: os.scandir로 바꿔도 읽을 수 있는 폴더에서는 예전(os.walk)과 같은 영상·같은 순서."""
    root = tmp_path / "tree"
    for rel in ("a1.mov", "A10.MP4", "a2.mkv", "x/b1.mov", "x/y/c.webm", "x/y/.hidden.mov", "z/n.txt",
                ".dot/d.mov", "same/a1.mov", "same/deeper/a1.mov", "k/clip.mov/inner.mov"):
        touch(root / rel)
    if sys.platform != "win32":
        os.symlink(str(root / "x"), str(root / "link_to_x"))  # 폴더 링크: 목록엔 폴더로, 따라 들어가지는 않음
        os.symlink(str(root / "a1.mov"), str(root / "link.mov"))  # 파일 링크: 영상
        os.symlink(str(root / "missing.mov"), str(root / "broken.mov"))  # 깨진 링크: 예전처럼 파일로
    result = video_list.scan_folder(str(root))
    assert [path for _name, path in result.videos] == walk_reference(str(root))
    assert result.unreadable == []


@pytest.mark.skipif(sys.platform == "win32", reason="DirEntry.is_dir이 오류를 올리는 경우 (POSIX에서 흉내)")
def test_scan_folder_is_dir_failure_is_unreadable(tmp_path, monkeypatch):
    """L5: 하위 항목이 폴더인지 확인하지 못하면(예전 os.walk는 '폴더 아님'으로 넘김) 읽지 못한 것으로 — 그 아래 영상은 그대로."""
    root = tmp_path / "clips"
    touch(root / "a.mov")
    kept = touch(root / "sub" / "b.mov")
    real_scandir = os.scandir
    sub = os.path.normpath(str(root / "sub"))

    class Entry:
        def __init__(self, entry):
            self._entry = entry
            self.name, self.path = entry.name, entry.path

        def is_dir(self, *args, **kwargs):
            if os.path.normpath(self.path) == sub:
                raise PermissionError(errno.EACCES, "Permission denied", self.path)
            return self._entry.is_dir(*args, **kwargs)

        def is_file(self, *args, **kwargs):
            return self._entry.is_file(*args, **kwargs)

        def is_symlink(self):
            return self._entry.is_symlink()

    class Listing:
        def __init__(self, path):
            self._it = real_scandir(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._it.close()

        def __iter__(self):
            return (Entry(entry) for entry in self._it)

    monkeypatch.setattr(video_list.os, "scandir", lambda path=".": Listing(path))
    result = video_list.scan_folder(str(root))
    assert names(result) == ["a.mov"]
    assert [os.path.normpath(folder) for folder, _e in result.unreadable] == [sub]
    assert result.keeps(kept)


def test_sort_does_not_set_locale(monkeypatch):
    """L7: 정렬(다시 읽기 스레드에서도 돎)은 locale을 바꾸지 않음 — 시작할 때 GUI 스레드에서 한 번 (set_sort_locale)."""
    def no_setlocale(*args):
        raise AssertionError(f"정렬 중 setlocale: {args}")

    monkeypatch.setattr(video_list.locale, "setlocale", no_setlocale)
    monkeypatch.setattr(video_list.locale, "getlocale", lambda *args: ("ko_KR", "UTF-8"))  # 예: 한국어 Windows
    assert names(video_list.ScanResult(video_list.sort_job_videos([("b.mov", "b"), ("a.mov", "a")]))) == ["a.mov", "b.mov"]


def test_set_sort_locale_once(monkeypatch):
    calls = []
    monkeypatch.setattr(video_list, "_sort_locale_set", False)
    monkeypatch.setattr(video_list.locale, "setlocale", lambda category, value=None: calls.append((category, value)))
    video_list.set_sort_locale()
    video_list.set_sort_locale()
    assert calls == [(locale.LC_COLLATE, "en_US.UTF-8")]
