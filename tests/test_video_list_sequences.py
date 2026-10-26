"""사이드바 목록 읽기(video_list)가 영상과 이미지 시퀀스를 같은 폴더 목록에서 한 번에 모으는 규칙.

영상 쪽은 예전과 똑같아야 한다 (Mov 탭 동작 무변경): 같은 항목, 같은 순서. 시퀀스는 sequence_scan.group_sequences로 묶고,
시퀀스에서 뽑은 임시 프레임 폴더(temp_frames)는 시퀀스로 묶지 않는다 (그 폴더 안의 영상은 예전처럼 모음).
예시 이름만 씀 (공개 저장소).
"""

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yesoncheck import file_names, sequence_scan, video_list
from yesoncheck.video_list import ListSource
from yesoncheck.sequence_scan import SeqInfo

REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return str(path)


def names(result):
    return [name for name, _path in result.videos]


def build_tree(job):
    """scene-01/frames: 시퀀스 EX01_tk1 (2장) + EX01_tk1.mov + 임시 프레임 폴더 / scene-02/frames: EX02.mov (시퀀스 없음)."""
    frames = job / "scene-01" / "frames"
    touch(frames / "EX01_tk1-0001.tga")
    touch(frames / "EX01_tk1-0002.tga")
    touch(frames / "EX01_tk1.mov")
    touch(frames / "temp_frames" / "EX01_tk1-0001.tga")
    touch(frames / "temp_frames" / "EX01_tk1-0002.tga")
    touch(job / "scene-02" / "frames" / "EX02.mov")
    return frames


def seq_ids(result):
    return [s.identity for s in result.sequences]


# ---- 영상과 시퀀스를 함께 ----

def test_scan_job_returns_videos_and_sequences(tmp_path):
    job = tmp_path / "job"
    frames = build_tree(job)
    result = video_list.scan_job("FL", str(job))
    assert sorted(names(result)) == ["EX01_tk1.mov", "EX02.mov"]
    assert result.sequences == [SeqInfo(str(frames), "EX01_tk1", "tga", 4, 1, 2, 2)]
    assert result.sequences[0].identity == os.path.join(str(frames), "EX01_tk1.seq")
    assert result.unreadable == []


def test_scan_folder_recursive_sequences(tmp_path):
    root = tmp_path / "root"
    frames = build_tree(root)
    touch(root / "top" / "deep" / "S03_tk2-001.png")
    touch(root / "top" / "deep" / "S03_tk2-002.png")
    touch(root / "top" / "deep" / "S03_tk2-004.png")
    result = video_list.scan_folder(str(root))
    assert sorted(names(result)) == ["EX01_tk1.mov", "EX02.mov"]
    assert result.sequences == [
        SeqInfo(str(frames), "EX01_tk1", "tga", 4, 1, 2, 2),
        SeqInfo(str(root / "top" / "deep"), "S03_tk2", "png", 3, 1, 4, 3),
    ]


def test_sequences_in_job_folder_itself_and_ms_animatic(tmp_path):
    """영상을 모으는 폴더마다 시퀀스도 모음: job 폴더 바로 안도 (MS_Animatic은 그 폴더만 읽음)."""
    job = tmp_path / "job"
    touch(job / "top.mov")
    touch(job / "A_tk1-01.exr")
    touch(job / "A_tk1-02.exr")
    touch(job / "scene-01" / "frames" / "B_tk1-01.exr")
    touch(job / "scene-01" / "frames" / "B_tk1-02.exr")
    touch(job / "scene-01" / "not_frames" / "C_tk1-01.exr")
    touch(job / "scene-01" / "not_frames" / "C_tk1-02.exr")
    fl = video_list.scan_job("FL", str(job))
    assert [(s.dir, s.base) for s in fl.sequences] == [
        (str(job), "A_tk1"), (os.path.join(str(job), "scene-01", "frames"), "B_tk1")]
    ms = video_list.scan_job("MS_Animatic", str(job))
    assert names(ms) == ["top.mov"]
    assert [(s.dir, s.base) for s in ms.sequences] == [(str(job), "A_tk1")]


@pytest.mark.parametrize("work, sub", [("BB_Animatic", "Quicktime"), ("TGN_Animatic", "ANIMATIC")])
def test_sequences_follow_the_work_rule_folders(tmp_path, work, sub):
    job = tmp_path / "job"
    touch(job / "s1" / sub / "a.mov")
    touch(job / "s1" / sub / "A_tk1-001.tif")
    touch(job / "s1" / sub / "A_tk1-002.tif")
    touch(job / "s1" / "frames" / "B_tk1-001.tif")  # 이 작품 규칙의 폴더가 아님
    touch(job / "s1" / "frames" / "B_tk1-002.tif")
    result = video_list.scan_job(work, str(job))
    assert names(result) == ["a.mov"]
    assert [s.base for s in result.sequences] == ["A_tk1"]


def test_sequenceless_folder_empty_seq_list(tmp_path):
    root = tmp_path / "root"
    touch(root / "scene-01" / "frames" / "A.mov")
    touch(root / "scene-01" / "frames" / "lonely-0001.tga")  # 한 장은 시퀀스가 아님
    touch(root / "notes.txt")
    folder_result = video_list.scan_folder(str(root))
    job_result = video_list.scan_job("FL", str(root))
    assert folder_result.sequences == [] and job_result.sequences == []
    assert names(folder_result) == names(job_result) == ["A.mov"]


def test_scan_source_and_read_sources_carry_sequences(tmp_path):
    job = tmp_path / "job"
    frames = build_tree(job)
    job_source = ListSource("job", str(job), "FL")
    folder_source = ListSource("folder", str(job))
    for source in (job_source, folder_source):
        assert seq_ids(video_list.scan_source(source)) == [os.path.join(str(frames), "EX01_tk1.seq")]
    read = video_list.read_sources([job_source, folder_source], [])
    assert seq_ids(read.results[job_source]) == [os.path.join(str(frames), "EX01_tk1.seq")]
    assert seq_ids(read.results[folder_source]) == [os.path.join(str(frames), "EX01_tk1.seq")]


def test_videos_identical_with_and_without_sequence_files(tmp_path):
    """시퀀스 프레임 파일이 있어도 영상 목록은 예전과 같음 (같은 항목, 같은 순서)."""
    plain, mixed = tmp_path / "plain", tmp_path / "mixed"
    movs = ["scene-01/frames/b2.mov", "scene-01/frames/b10.MOV", "scene-02/frames/a1.mp4", "top.mov",
            "scene-03/frames/B_HD.mov", "x/y/clip.mkv"]
    for root in (plain, mixed):
        for rel in movs:
            touch(root / rel)
    for n in (1, 2, 3):
        touch(mixed / "scene-01" / "frames" / f"b2-000{n}.tga")
        touch(mixed / "x" / "y" / f"clip-000{n}.png")
        touch(mixed / "scene-02" / "frames" / "temp_frames" / f"z-000{n}.tga")

    def rel_videos(result, root):
        return [(name, os.path.relpath(path, root)) for name, path in result.videos]

    for scan in (lambda root: video_list.scan_job("FL", str(root)), lambda root: video_list.scan_folder(str(root))):
        assert rel_videos(scan(mixed), mixed) == rel_videos(scan(plain), plain)


def test_sequences_sorted_naturally_across_folders(tmp_path):
    root = tmp_path / "root"
    for folder, base in (("b", "clip10"), ("a", "clip2"), ("a", "Clip3")):
        touch(root / folder / f"{base}-0001.tga")
        touch(root / folder / f"{base}-0002.tga")
    result = video_list.scan_folder(str(root))
    assert [(os.path.basename(s.dir), s.base) for s in result.sequences] == [("a", "clip2"), ("a", "Clip3"), ("b", "clip10")]


def test_same_base_in_two_folders_ordered_by_path(tmp_path):
    root = tmp_path / "root"
    for folder in ("z", "m"):
        touch(root / folder / "S_tk1-0001.tga")
        touch(root / folder / "S_tk1-0002.tga")
    result = video_list.scan_folder(str(root))
    assert [os.path.basename(s.dir) for s in result.sequences] == ["m", "z"]


def test_directories_with_frame_like_names_are_not_frames(tmp_path):
    """폴더 항목은 시퀀스 프레임이 아님 (group_sequences는 파일 이름만 받음)."""
    root = tmp_path / "root"
    (root / "shot-0001.tga").mkdir(parents=True)
    (root / "shot-0002.tga").mkdir()
    touch(root / "shot-0003.tga")
    assert video_list.scan_folder(str(root)).sequences == []
    assert video_list.scan_job("MS_Animatic", str(root)).sequences == []
    touch(root / "shot-0004.tga")
    assert [(s.base, s.count) for s in video_list.scan_folder(str(root)).sequences] == [("shot", 2)]
    assert [(s.base, s.count) for s in video_list.scan_job("MS_Animatic", str(root)).sequences] == [("shot", 2)]


# ---- temp_frames 제외 ----

def test_temp_frames_excluded_from_sequences(tmp_path):
    """재귀 스캔: temp_frames 폴더(대소문자 무시)의 프레임은 시퀀스로 묶지 않음 — 그 안의 영상은 예전처럼 모음."""
    root = tmp_path / "root"
    frames = build_tree(root)
    touch(root / "other" / "Temp_Frames" / "Q_tk1-0001.png")
    touch(root / "other" / "Temp_Frames" / "Q_tk1-0002.png")
    touch(root / "other" / "Temp_Frames" / "kept.mov")
    touch(frames / "temp_frames" / "inside.mov")
    result = video_list.scan_folder(str(root))
    assert [s.dir for s in result.sequences] == [str(frames)]
    assert "kept.mov" in names(result) and "inside.mov" in names(result)


def test_temp_frames_excluded_in_scan_job(tmp_path):
    """job 규칙으로 읽는 폴더가 temp_frames이면 (TJS는 job 아래 한 단계 폴더를 읽음) 거기서도 시퀀스로 묶지 않음."""
    job = tmp_path / "job"
    touch(job / "temp_frames" / "T_tk1-0001.tga")
    touch(job / "temp_frames" / "T_tk1-0002.tga")
    touch(job / "temp_frames" / "t.mov")
    touch(job / "TEMP_FRAMES" / "U_tk1-0001.tga")
    touch(job / "TEMP_FRAMES" / "U_tk1-0002.tga")
    touch(job / "shots" / "S_tk1-0001.tga")
    touch(job / "shots" / "S_tk1-0002.tga")
    result = video_list.scan_job("TJS_Animatic", str(job))
    assert [s.base for s in result.sequences] == ["S_tk1"]
    assert names(result) == ["t.mov"]


def test_temp_frames_guard_on_root_folder_and_trailing_separator(tmp_path):
    """읽는 폴더 자신의 이름이 temp_frames여도 같음 (끝의 구분자가 있어도)."""
    folder = tmp_path / "temp_frames"
    touch(folder / "V_tk1-0001.tga")
    touch(folder / "V_tk1-0002.tga")
    assert video_list.scan_folder(str(folder)).sequences == []
    assert video_list.scan_folder(str(folder) + os.sep).sequences == []


# ---- 읽기 횟수 / 오류 ----

def test_scan_counts_single_listdir(tmp_path, monkeypatch):
    """영상과 시퀀스를 같은 폴더 목록에서 모음: 폴더 읽기(os.scandir) 횟수는 시퀀스를 찾기 전과 같고 listdir은 없음."""
    job = tmp_path / "job"
    build_tree(job)
    real_scandir, scanned, listed = os.scandir, [], []

    def scandir(path="."):
        scanned.append(os.path.relpath(os.fspath(path), str(tmp_path)).replace(os.sep, "/"))  # Windows의 역슬래시도 "/"로
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    monkeypatch.setattr(video_list.os, "listdir", lambda *args: listed.append(args) or [])

    result = video_list.scan_job("FL", str(job))
    assert len(result.sequences) == 1
    assert sorted(scanned) == sorted(["job", "job/scene-01/frames", "job/scene-02/frames"])  # 예전과 같음

    scanned.clear()
    result = video_list.scan_folder(str(job))
    assert len(result.sequences) == 1
    assert sorted(scanned) == sorted(["job", "job/scene-01", "job/scene-01/frames", "job/scene-01/frames/temp_frames",
                                      "job/scene-02", "job/scene-02/frames"])  # 폴더마다 한 번 (예전과 같음)
    assert listed == []


def test_unreadable_folder_still_reported_with_sequences(tmp_path, monkeypatch):
    """폴더를 읽지 못하면 예전처럼 unreadable에 남고, 읽은 폴더의 시퀀스는 그대로."""
    root = tmp_path / "root"
    frames = build_tree(root)
    locked = root / "locked"
    touch(locked / "L_tk1-0001.tga")
    error = PermissionError(errno.EACCES, "Permission denied", str(locked))
    real_scandir = os.scandir

    def scandir(path="."):
        if os.path.normpath(os.fspath(path)) == os.path.normpath(str(locked)):
            raise error
        return real_scandir(path)

    monkeypatch.setattr(video_list.os, "scandir", scandir)
    result = video_list.scan_folder(str(root))
    assert [s.dir for s in result.sequences] == [str(frames)]
    assert [(os.path.normpath(folder), err) for folder, err in result.unreadable] == [(os.path.normpath(str(locked)), error)]


def test_file_check_failure_on_frame_entry_is_unreadable_not_silent(tmp_path, monkeypatch):
    """scan_job: 프레임 이름 항목이 파일인지 확인하지 못하면 삼키지 않고 unreadable에 남김."""
    job = tmp_path / "job"
    touch(job / "ok.mov")
    bad = touch(job / "W_tk1-0001.tga")
    touch(job / "W_tk1-0002.tga")
    real_scandir = os.scandir

    class Entry:
        def __init__(self, entry):
            self._entry = entry
            self.name, self.path = entry.name, entry.path

        def is_dir(self, *args, **kwargs):
            return self._entry.is_dir(*args, **kwargs)

        def is_file(self, *args, **kwargs):
            if self.path == bad:
                raise PermissionError(errno.EACCES, "Permission denied", self.path)
            return self._entry.is_file(*args, **kwargs)

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
    result = video_list.scan_job("MS_Animatic", str(job))
    assert names(result) == ["ok.mov"]
    assert [path for path, _e in result.unreadable] == [bad]
    assert result.sequences == []  # 확인된 프레임이 한 장뿐이라 시퀀스가 아님


# ---- natural_key 이동 (순환 import 해소) ----

def test_natural_key_lives_in_file_names_and_is_reexported():
    assert video_list.natural_key is file_names.natural_key
    assert file_names.natural_key("/x/clip2.mov") < file_names.natural_key("/x/clip10.mov")
    assert file_names.natural_key("/x/Clip3.mov") == ["clip", 3, ".mov"]


def test_natural_key_accepts_digit_like_characters(tmp_path):
    """'²'·'①'처럼 isdigit이지만 int()가 못 받는 글자가 이름에 있어도 죽지 않음 (이제 job 목록 읽기도 이미지 이름에 씀)."""
    assert file_names.natural_key("1²2.mov") == ["", 1, "²", 2, ".mov"]
    assert file_names.natural_key("①.mov") == ["①.mov"]
    job = tmp_path / "job"
    touch(job / "1²2_tk1-0001.tga")
    touch(job / "1²2_tk1-0002.tga")
    assert [s.base for s in video_list.scan_job("MS_Animatic", str(job)).sequences] == ["1²2_tk1"]


def test_sequence_scan_uses_the_neutral_natural_key():
    assert sequence_scan.natural_key is file_names.natural_key


@pytest.mark.parametrize("first, second", [("yesoncheck.sequence_scan", "yesoncheck.video_list"),
                                           ("yesoncheck.video_list", "yesoncheck.sequence_scan")])
def test_no_import_cycle_in_either_order(first, second):
    """어느 모듈을 먼저 불러도 순환 import가 없음 (새 인터프리터에서)."""
    code = f"import {first}, {second}; from yesoncheck import video_list as v; assert v.natural_key"
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
