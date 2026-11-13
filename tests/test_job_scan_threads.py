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

from yesoncheck import file_names, video_list
from yesoncheck.video_list import ScanResult
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


@pytest.mark.parametrize("work", ["FL", "BB_Animatic", "TGN_Animatic", "KOTH_Animatic", "TJS_Animatic"])
def test_every_rule_with_several_sub_folders_reads_them_together(tmp_path, monkeypatch, work):
    """하위 폴더를 여럿 읽는 작품 규칙은 모두 함께 읽음 — 첫 읽기가 둘째 읽기가 들어올 때까지 기다림(차례로 읽으면 끝내 안 옴)."""
    job = make_job(tmp_path)
    lock = threading.Lock()
    entered = []
    overlapped = threading.Event()

    def wait_for_a_second_reader(folder):
        with lock:
            entered.append(folder)
            first = len(entered) == 1
        if first:
            overlapped.wait(timeout=3)
        else:
            overlapped.set()

    wrap_reads(monkeypatch, wait_for_a_second_reader)
    scan(monkeypatch, work, job)
    assert len(entered) >= 2, "이 작품 규칙이 하위 폴더를 둘 이상 읽지 않음 (시험 폴더가 틀림)"
    assert overlapped.is_set(), "하위 폴더를 차례로(하나씩) 읽었음"


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
    assert 1 <= state["most"] <= 3  # 함께 읽는지는 위 시험들이 봄 — 여기서는 상한


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


def reference_scan_job(work, base_path):
    """2026-11-13 전의 scan_job 본문 그대로(하위 폴더를 하나씩 차례로) — 새 구현을 견주는 기준.
    (스레드 1과 기본을 견주는 시험은 둘 다 새 코드라, 읽을 폴더를 모으는 규칙이 틀리면 똑같이 틀림)"""
    unreadable = []
    sequences = []

    def read_sub(folder, files_only=False):
        found_videos, found_sequences = video_list._read_folder(folder, unreadable, files_only)
        sequences.extend(found_sequences)
        return found_videos

    with os.scandir(base_path) as it:
        entries = list(it)
    sequences.extend(video_list._sequences_in(base_path, video_list._frame_names(entries, unreadable)))
    if work == "MS_Animatic":
        videos = [(e.name, e.path) for e in entries if file_names.is_listed_video(e.name)]
    elif work == "TJS_Animatic":
        videos = [(e.name, e.path) for e in entries
                  if file_names.is_listed_video(e.name) and video_list._is_file(e, unreadable)]
        for entry in entries:
            if not entry.name.startswith('.') and video_list._is_dir(entry, unreadable):
                videos += read_sub(entry.path, files_only=True)
    else:
        videos = [(e.name, e.path) for e in entries if file_names.is_listed_video(e.name)]
        for entry in entries:
            if work == "BB_Animatic":
                sub = "Quicktime"
            elif work == "TGN_Animatic":
                sub = "ANIMATIC"
            elif work in ("BM_Animatic", "KOTH_Animatic"):
                sub = None
            else:
                sub = "frames"
            if sub and video_list._is_dir(entry, unreadable):
                videos += read_sub(os.path.join(entry.path, sub))
        if work == "BB_Animatic":
            videos += read_sub(os.path.join(base_path, "Quicktime"))
        if work == "BM_Animatic":
            videos += read_sub(os.path.join(base_path, "ANIMATIC"))
        if work == "KOTH_Animatic":
            for entry in entries:
                if 'ANIMATIC' in entry.name.upper() and video_list._is_dir(entry, unreadable):
                    videos += read_sub(entry.path)
    os.stat(base_path)
    return ScanResult(video_list.sort_job_videos(videos), unreadable, video_list.sort_sequences(sequences))


class TroubledEntry:
    """os.DirEntry 대역: 정한 경로의 is_dir·is_file이 OSError를 냄 (나머지는 진짜 항목에 맡김)."""

    def __init__(self, real, errors):
        self._real = real
        self._errors = errors
        self.name = real.name
        self.path = real.path

    def _check(self, what):
        error = self._errors.get((what, os.path.normpath(self.path)))
        if error is not None:
            raise error

    def is_dir(self, **kwargs):
        self._check("is_dir")
        return self._real.is_dir(**kwargs)

    def is_file(self, **kwargs):
        self._check("is_file")
        return self._real.is_file(**kwargs)


class Listing:
    """os.scandir가 돌려주는 것의 대역 (with … as it: list(it))."""

    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc):
        return False


def make_troubled_job(root, monkeypatch):
    """읽기 실패를 여러 가지로 심은 job → (job 경로, 심은 오류 수). 작품 규칙마다 다른 실패에 닿음:
    씬 폴더가 폴더인지 확인 실패 · 하위 폴더 목록 읽기 실패 · 없는 하위 폴더 + 그 위 폴더 확인 실패 · job 폴더 바로 안과
    하위 폴더 안의 프레임·영상이 파일인지 확인 실패."""
    job = make_job(root)
    for frame in (1, 2):
        touch(os.path.join(job, f"jobseq-{frame:04d}.png"))  # job 폴더 바로 안의 시퀀스 프레임

    def denied(what):
        return PermissionError(errno.EACCES, "Permission denied", what)

    def at(*parts):
        return os.path.normpath(os.path.join(job, *parts))

    entry_errors = {
        ("is_dir", at("scene-003")): denied("is_dir scene-003"),
        ("is_dir", at("1601_ANIMATIC")): denied("is_dir 1601_ANIMATIC"),
        ("is_file", at("jobseq-0002.png")): denied("is_file jobseq-0002.png"),
        ("is_file", at("top.mov")): denied("is_file top.mov"),
        ("is_file", at("scene-000", "frames", "frames000-0002.png")): denied("is_file frames000-0002.png"),
        ("is_file", at("scene-000", "Quicktime", "Quicktime000-0002.png")): denied("is_file Quicktime000-0002.png"),
        ("is_file", at("scene-001", "direct_001.mov")): denied("is_file direct_001.mov"),
    }
    listing_errors = {at("scene-005", sub): denied(f"scandir scene-005/{sub}") for sub in ("frames", "Quicktime", "ANIMATIC")}
    listing_errors[at("scene-007")] = denied("scandir scene-007")
    stat_errors = {at("empty-scene"): denied("stat empty-scene")}  # frames가 없는 폴더 → 그 위 폴더를 확인하다 실패
    real_scandir, real_stat = os.scandir, os.stat

    def scandir(path="."):
        key = os.path.normpath(os.fspath(path))
        if key in listing_errors:
            raise listing_errors[key]
        with real_scandir(path) as it:
            return Listing([TroubledEntry(entry, entry_errors) for entry in it])

    def stat(path, *args, **kwargs):
        if not isinstance(path, int) and os.path.normpath(os.fspath(path)) in stat_errors:
            raise stat_errors[os.path.normpath(os.fspath(path))]
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    monkeypatch.setattr(video_list.os, "stat", stat)
    return job, len(entry_errors) + len(listing_errors) + len(stat_errors)


def problems(result):
    return [(os.path.normpath(folder), error) for folder, error in result.unreadable]


@pytest.mark.parametrize("threads", [1, 8])
@pytest.mark.parametrize("work", WORKS)
def test_same_as_the_old_one_by_one_code_with_failures_mixed_in(tmp_path, monkeypatch, work, threads):
    """예전 코드(하나씩 차례로)를 기준으로: 읽기 실패가 섞인 job에서 영상의 차례·시퀀스·읽지 못한 것의 차례와 오류가 모두 같음."""
    job, _planted = make_troubled_job(tmp_path, monkeypatch)
    expected = reference_scan_job(work, job)
    result = scan(monkeypatch, work, job, threads=threads)
    assert result.videos == expected.videos
    assert result.sequences == expected.sequences
    assert problems(result) == problems(expected)
    assert expected.unreadable, "이 작품 규칙이 심은 실패에 하나도 닿지 않음 (시험 폴더가 틀림)"


def test_the_troubled_job_reaches_every_kind_of_failure(tmp_path, monkeypatch):
    """심은 실패가 어느 작품 규칙에서든 한 번은 읽지 못한 것으로 나옴 (시험이 실패 없는 길만 견주지 않게)."""
    job, planted = make_troubled_job(tmp_path, monkeypatch)
    reached = set()
    for work in WORKS:
        reached.update(id(error) for _folder, error in reference_scan_job(work, job).unreadable)
    assert len(reached) == planted


def test_reads_not_started_yet_are_dropped_after_an_unexpected_error(tmp_path, monkeypatch):
    """한 폴더에서 예상 못 한 오류가 나면 아직 시작하지 않은 폴더는 읽지 않고 올림 (읽는 중이던 것만 끝남) — 창이 남은
    수백 폴더를 다 읽을 때까지 멈춰 있지 않게."""
    job = tmp_path / "job"
    for i in range(60):
        touch(job / f"scene-{i:03d}" / "frames" / f"a{i}.mov")
    order = []
    wrap_reads(monkeypatch, order.append)
    scan(monkeypatch, "FL", str(job), threads=1)
    first = order[0]
    started = []

    def boom_on_the_first(folder):
        started.append(folder)
        if folder == first:
            raise RuntimeError("시험: 예상 못 한 오류")
        time.sleep(0.2)

    wrap_reads(monkeypatch, boom_on_the_first)
    with pytest.raises(RuntimeError, match="예상 못 한 오류"):
        scan(monkeypatch, "FL", str(job), threads=2)
    assert len(started) <= 10, f"오류 뒤에도 {len(started)}개 폴더를 읽기 시작함"


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
    assert re.search(r"^\[측정\] job 목록 읽기 \d+\.\d\d초 \(영상 3개, 스레드 설정 8\) — job_01$", out, re.M), out


def test_the_log_line_shows_the_thread_setting(new_player, work_area, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setenv(ENV, "1")
    open_job(new_player, work_area, monkeypatch)
    out = capsys.readouterr().out
    assert re.search(r"^\[측정\] job 목록 읽기 \d+\.\d\d초 \(영상 3개, 스레드 설정 1\) — job_01$", out, re.M), out
