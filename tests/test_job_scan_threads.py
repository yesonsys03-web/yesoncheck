"""job 목록의 하위 폴더를 함께 읽기 (video_list.scan_job — 2026-11-13).

왜: 사용자 보고 "작품을 고르면 목록이 뜨는 데 시간이 걸린다". 씬 폴더가 2,000개 넘는 job은 `<씬>/frames`를 하나씩 차례로
읽느라 목록이 1.4~2.0초 뒤에 떴음(개발 Mac·NFS 실측) — 스레드 8개로 함께 읽으면 0.4~0.7초.

지키는 것: 함께 읽어도 결과(영상의 차례·시퀀스·읽지 못한 폴더의 차례)가 차례로 읽은 것과 같음, 스레드 수는 환경 변수
YESONCHECK_JOB_SCAN_THREADS로 바꿈(1 = 예전처럼 차례로), 나쁜 값은 켤 때 오류, job을 고르면 걸린 시간이 기록에 남음.
"""

import errno
import os
import re
import threading
import time

import pytest

from yesoncheck import video_list
from tests.test_sidebar_refresh import open_job
from tests.test_work_paths_ui import new_player  # noqa: F401 (fixture)

ENV = "YESONCHECK_JOB_SCAN_THREADS"
WORKS = ["FL", "BB_Animatic", "TGN_Animatic", "BM_Animatic", "KOTH_Animatic", "MS_Animatic", "TJS_Animatic"]


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return str(path)


def make_job(root, scenes=12):
    """작품 규칙마다 읽는 폴더가 다 들어 있는 job: 씬마다 frames·Quicktime·ANIMATIC, 같은 이름의 영상(읽은 차례가 결과에
    남음 — 정렬이 안정적), HD, 시퀀스, 씬 바로 안의 영상(TJS_Animatic 규칙)."""
    job = root / "job"
    touch(job / "top.mov")
    for i in range(scenes):
        scene = job / f"scene-{i:03d}"
        for sub in ("frames", "Quicktime", "ANIMATIC"):
            touch(scene / sub / f"{sub}_{i:03d}.mov")
            touch(scene / sub / "dup.mov")
            if i % 3 == 0:
                touch(scene / sub / f"{sub}_{i:03d}_HD.mov")
            if i % 4 == 0:
                for frame in (1, 2, 3):
                    touch(scene / sub / f"{sub}{i:03d}-{frame:04d}.png")
        touch(scene / f"direct_{i:03d}.mov")
        touch(scene / "dup.mov")
    (job / "empty-scene").mkdir()
    touch(job / "Quicktime" / "job_quicktime.mov")
    touch(job / "ANIMATIC" / "job_animatic.mov")
    touch(job / "1601_ANIMATIC" / "koth.mov")
    return str(job)


def scan(monkeypatch, work, job, threads=None):
    """threads: None이면 기본(환경 변수 없음), 아니면 그 값으로."""
    if threads is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, str(threads))
    return video_list.scan_job(work, job)


def wrap_reads(monkeypatch, before):
    """하위 폴더를 읽을 때마다(_read_folder) 먼저 before(폴더)를 부름."""
    real = video_list._read_folder

    def read(folder, unreadable, files_only=False):
        before(folder)
        return real(folder, unreadable, files_only)

    monkeypatch.setattr(video_list, "_read_folder", read)


# ---- 함께 읽음 ----

def test_sub_folders_are_read_together(tmp_path, monkeypatch):
    """기본: 하위 폴더 읽기가 서로 겹침 — 읽기마다 다른 읽기 하나가 함께 들어올 때까지 기다리게 해서 봄(차례로 읽으면 혼자 남음)."""
    job = tmp_path / "job"
    for i in range(8):
        touch(job / f"scene-{i:03d}" / "frames" / f"a{i}.mov")
    pair = threading.Barrier(2)
    alone = []

    def wait_for_another(folder):
        try:
            pair.wait(timeout=3)
        except threading.BrokenBarrierError:
            alone.append(folder)

    wrap_reads(monkeypatch, wait_for_another)
    result = scan(monkeypatch, "FL", str(job))
    assert alone == [], "하위 폴더를 차례로(하나씩) 읽었음"
    assert sorted(name for name, _path in result.videos) == [f"a{i}.mov" for i in range(8)]


def test_one_thread_reads_in_the_calling_thread(tmp_path, monkeypatch):
    """YESONCHECK_JOB_SCAN_THREADS=1: 예전처럼 부른 스레드에서 차례로."""
    job = make_job(tmp_path)
    readers = set()
    wrap_reads(monkeypatch, lambda folder: readers.add(threading.get_ident()))
    scan(monkeypatch, "FL", job, threads=1)
    assert readers == {threading.get_ident()}


def test_no_more_readers_than_the_setting(tmp_path, monkeypatch):
    """함께 읽는 수는 정한 스레드 수를 넘지 않음."""
    job = make_job(tmp_path, scenes=24)
    lock = threading.Lock()
    state = {"now": 0, "most": 0}
    real = video_list._read_folder

    def read(folder, unreadable, files_only=False):
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
        try:
            time.sleep(0.01)
            return real(folder, unreadable, files_only)
        finally:
            with lock:
                state["now"] -= 1

    monkeypatch.setattr(video_list, "_read_folder", read)
    scan(monkeypatch, "FL", job, threads=3)
    assert 2 <= state["most"] <= 3


def test_no_reader_threads_left_after_the_scan(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    before = set(threading.enumerate())
    scan(monkeypatch, "FL", job)
    assert [t for t in threading.enumerate() if t not in before] == []


def test_a_single_sub_folder_is_read_without_extra_threads(tmp_path, monkeypatch):
    job = tmp_path / "job"
    touch(job / "scene-001" / "frames" / "a.mov")
    readers = set()
    wrap_reads(monkeypatch, lambda folder: readers.add(threading.get_ident()))
    scan(monkeypatch, "FL", str(job))
    assert readers == {threading.get_ident()}


# ---- 결과는 차례로 읽은 것과 같음 ----

@pytest.mark.parametrize("work", WORKS)
def test_result_is_the_same_as_reading_one_by_one(tmp_path, monkeypatch, work):
    job = make_job(tmp_path)
    one_by_one = scan(monkeypatch, work, job, threads=1)
    together = scan(monkeypatch, work, job)
    assert one_by_one.videos, "이 작품 규칙으로 읽힌 영상이 없음 (시험 폴더가 틀림)"
    assert together.videos == one_by_one.videos
    assert together.sequences == one_by_one.sequences
    assert together.unreadable == one_by_one.unreadable == []


@pytest.mark.parametrize("work", ["FL", "TJS_Animatic", "KOTH_Animatic"])
def test_order_is_kept_when_later_folders_finish_first(tmp_path, monkeypatch, work):
    """같은 이름의 영상은 읽은 차례대로 남음(안정 정렬) — 뒤 폴더의 읽기가 먼저 끝나도 폴더 차례대로 합침."""
    job = make_job(tmp_path)
    one_by_one = scan(monkeypatch, work, job, threads=1)
    seen = []
    wrap_reads(monkeypatch, seen.append)
    scan(monkeypatch, work, job, threads=1)
    slow = {folder: 0.02 * (len(seen) - index) for index, folder in enumerate(seen)}  # 앞 폴더일수록 늦게 끝남
    wrap_reads(monkeypatch, lambda folder: time.sleep(slow[folder]))
    together = scan(monkeypatch, work, job)
    assert together.videos == one_by_one.videos
    assert together.sequences == one_by_one.sequences


def test_unreadable_folders_come_in_the_same_order(tmp_path, monkeypatch):
    """읽지 못한 하위 폴더는 삼키지 않고, 차례로 읽을 때와 같은 차례로 남김."""
    job = make_job(tmp_path)
    failing = {os.path.normpath(os.path.join(job, f"scene-{i:03d}", "frames")): PermissionError(
        errno.EACCES, "Permission denied", f"scene-{i:03d}") for i in (2, 5, 7, 11)}
    real_scandir = os.scandir

    def scandir(path="."):
        key = None if isinstance(path, int) else os.path.normpath(os.fspath(path))
        if key in failing:
            time.sleep(0.02 if key.endswith(os.path.join("scene-002", "frames")) else 0)  # 앞의 실패가 늦게 끝남
            raise failing[key]
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    one_by_one = scan(monkeypatch, "FL", job, threads=1)
    together = scan(monkeypatch, "FL", job)
    assert len(one_by_one.unreadable) == 4
    assert together.unreadable == one_by_one.unreadable
    assert together.videos == one_by_one.videos


def test_unexpected_error_in_a_sub_folder_is_not_swallowed(tmp_path, monkeypatch):
    job = make_job(tmp_path)

    def boom(folder):
        if os.path.join("scene-004", "frames") in folder:
            raise RuntimeError("시험: 예상 못 한 오류")

    wrap_reads(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="예상 못 한 오류"):
        scan(monkeypatch, "FL", job)


# ---- 스레드 수 설정 ----

def test_default_thread_count(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert video_list.JOB_SCAN_THREADS_ENV == ENV
    assert video_list.job_scan_threads() == video_list.JOB_SCAN_THREADS == 8


@pytest.mark.parametrize("text, expected", [("", 8), ("   ", 8), ("1", 1), ("16", 16), (" 4 ", 4), ("32", 32)])
def test_thread_count_from_environment(monkeypatch, text, expected):
    monkeypatch.setenv(ENV, text)
    assert video_list.job_scan_threads() == expected


@pytest.mark.parametrize("text", ["0", "-1", "33", "abc", "1.5", "+4", "８", "4 threads"])
def test_bad_thread_count_is_an_error(monkeypatch, text):
    """모르는 값은 기본값으로 넘기지 않음."""
    monkeypatch.setenv(ENV, text)
    with pytest.raises(ValueError, match=ENV):
        video_list.job_scan_threads()


def test_launch_rejects_a_bad_thread_count_before_the_window(qapp, monkeypatch):
    """test_frame_cache_budget::test_launch_rejects_bad_frame_cache_mode와 같은 모양 — 목록을 읽을 때가 아니라 켤 때 알림."""
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 값인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(ENV, "many")
    with pytest.raises(ValueError, match=re.escape(repr("many"))):
        app_module.launch(["yesoncheck"])


def test_conftest_clears_the_setting():
    """시험은 개발자의 환경 변수와 무관하게 기본값으로 돎."""
    assert ENV not in os.environ


# ---- 기록 ----

def test_picking_a_job_logs_how_long_the_read_took(new_player, work_area, monkeypatch, capsys):  # noqa: F811
    monkeypatch.delenv(ENV, raising=False)
    open_job(new_player, work_area, monkeypatch)
    out = capsys.readouterr().out
    assert re.search(r"^\[측정\] job 목록 읽기 \d+\.\d\d초 \(영상 3개, 스레드 8\) — job_01$", out, re.M), out


def test_the_log_line_shows_the_thread_setting(new_player, work_area, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setenv(ENV, "1")
    open_job(new_player, work_area, monkeypatch)
    out = capsys.readouterr().out
    assert re.search(r"^\[측정\] job 목록 읽기 \d+\.\d\d초 \(영상 3개, 스레드 1\) — job_01$", out, re.M), out
