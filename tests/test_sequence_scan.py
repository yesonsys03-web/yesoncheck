"""이미지 시퀀스 그룹핑(sequence_scan): 폴더의 파일 이름 -> SeqInfo 목록, 가상 경로(.seq) identity."""

import dataclasses
import os

import pytest

from yesoncheck.sequence_scan import SEQ_EXTENSIONS, TEMP_FRAMES_DIR, SeqInfo, group_sequences, is_sequence_path


def _frames(base, numbers, ext="tga", pad=4):
    return [f"{base}-{n:0{pad}d}.{ext}" for n in numbers]


def test_group_basic_and_label_fields():
    seqs = group_sequences("/j/frames", [f"EX01_tk1-{i:04d}.tga" for i in (1, 2, 3)] + ["EX01_tk1.mov"])
    assert len(seqs) == 1
    s = seqs[0]
    assert (s.base, s.ext, s.pad, s.first, s.last, s.count) == ("EX01_tk1", "tga", 4, 1, 3, 3)
    assert s.dir == "/j/frames"
    assert s.identity == os.path.join("/j/frames", "EX01_tk1.seq") and s.missing == 0  # identity는 OS의 구분자 (실제 경로로 씀)


def test_identity_uses_os_path_join():
    s = group_sequences("/j/frames", _frames("a_tk1", (1, 2)))[0]
    assert s.identity == os.path.join("/j/frames", "a_tk1.seq")


def test_frame_name_pads_with_zeros():
    s = group_sequences("/j", _frames("a_tk1", (7, 8), pad=5, ext="png"))[0]
    assert s.frame_name(7) == "a_tk1-00007.png"
    assert s.frame_name(123) == "a_tk1-00123.png"


def test_frame_name_roundtrips_every_input_name():
    names = _frames("clip_tk2", range(5, 12), ext="exr", pad=3)
    s = group_sequences("/j", names)[0]
    assert [s.frame_name(n) for n in range(s.first, s.last + 1)] == sorted(names)


def test_group_multi_take_separate_items():
    names = _frames("EX01_tk1", (1, 2, 3)) + _frames("EX01_tk2", (1, 2))
    seqs = group_sequences("/j", names)
    assert [(s.base, s.count) for s in seqs] == [("EX01_tk1", 3), ("EX01_tk2", 2)]
    assert len({s.identity for s in seqs}) == 2


def test_group_gap_counted():
    s = group_sequences("/j", ["a_tk1-0001.tga", "a_tk1-0003.tga"])[0]
    assert (s.first, s.last, s.count, s.missing) == (1, 3, 2, 1)


def test_single_frame_not_sequence():
    assert group_sequences("/j", ["a_tk1-0001.tga"]) == []


def test_empty_names():
    assert group_sequences("/j", []) == []


def test_different_padding_separate_groups():
    names = ["a_tk1-001.tga", "a_tk1-002.tga", "a_tk1-0001.tga", "a_tk1-0002.tga"]
    seqs = group_sequences("/j", names)
    assert sorted((s.pad, s.count) for s in seqs) == [(3, 2), (4, 2)]


def test_different_extension_separate_groups():
    names = _frames("a_tk1", (1, 2), ext="tga") + _frames("a_tk1", (1, 2), ext="png")
    seqs = group_sequences("/j", names)
    assert sorted(s.ext for s in seqs) == ["png", "tga"]
    assert all(s.count == 2 for s in seqs)


def test_dotfiles_and_other_ext_ignored():
    names = ["._x-0001.tga", "._x-0002.tga", ".x-0001.tga", ".x-0002.tga", "a-0001.dpx", "a-0002.dpx"]
    assert group_sequences("/j", names) == []


def test_dotfile_does_not_join_real_sequence():
    names = ["._a-0001.tga", "a-0001.tga", "a-0002.tga"]
    seqs = group_sequences("/j", names)
    assert [(s.base, s.count) for s in seqs] == [("a", 2)]


def test_single_digit_frame_number_is_not_a_frame():
    assert group_sequences("/j", ["a-1.tga", "a-2.tga", "a-3.tga"]) == []


def test_base_with_dashes_uses_last_dash():
    names = _frames("scene-09B_tk1", (1, 2, 3))
    s = group_sequences("/j", names)[0]
    assert (s.base, s.first, s.last, s.count) == ("scene-09B_tk1", 1, 3, 3)


def test_base_ending_in_digits_after_dash():
    s = group_sequences("/j", ["a-0001-0002.tga", "a-0001-0003.tga"])[0]
    assert (s.base, s.first, s.last) == ("a-0001", 2, 3)


def test_name_without_base_ignored():
    assert group_sequences("/j", ["-0001.tga", "-0002.tga"]) == []


def test_extension_compared_case_insensitively_and_stored_lowercase():
    s = group_sequences("/j", ["a-0001.TGA", "a-0002.Tga", "a-0003.tga"])[0]
    assert (s.ext, s.count) == ("tga", 3)


@pytest.mark.parametrize("ext", sorted(SEQ_EXTENSIONS))
def test_every_supported_extension_groups(ext):
    s = group_sequences("/j", _frames("a", (1, 2), ext=ext))[0]
    assert s.ext == ext


def test_supported_extensions_are_the_image_formats():
    assert SEQ_EXTENSIONS == {"tga", "png", "jpg", "jpeg", "tif", "tiff", "exr"}


def test_duplicate_names_counted_once():
    s = group_sequences("/j", ["a-0001.tga", "a-0001.tga", "a-0002.tga"])[0]
    assert (s.count, s.missing) == (2, 0)


def test_names_with_trailing_newline_or_non_ascii_digits_ignored():
    assert group_sequences("/j", ["a-0001.tga\n", "a-0002.tga\n", "a-١٢.tga", "a-٣٤.tga"]) == []


def test_sorted_by_natural_base_order():
    names = _frames("clip10_tk1", (1, 2)) + _frames("clip2_tk1", (1, 2)) + _frames("Clip3_tk1", (1, 2))
    assert [s.base for s in group_sequences("/j", names)] == ["clip2_tk1", "Clip3_tk1", "clip10_tk1"]


def test_order_independent_of_input_order():
    names = _frames("b", (1, 2)) + _frames("a", (2, 1)) + _frames("a", (1, 2), ext="png")
    forward = group_sequences("/j", names)
    backward = group_sequences("/j", list(reversed(names)))
    assert forward == backward
    assert [(s.base, s.ext) for s in forward] == [("a", "png"), ("a", "tga"), ("b", "tga")]


def test_accepts_any_iterable():
    seqs = group_sequences("/j", iter(_frames("a", (1, 2))))
    assert len(seqs) == 1


def test_seqinfo_is_frozen_and_hashable():
    s = group_sequences("/j", _frames("a", (1, 2)))[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.count = 5
    assert s in {s}


def test_is_sequence_path():
    assert is_sequence_path("/j/frames/EX01_tk1.seq") is True
    assert is_sequence_path("/j/frames/EX01_tk1.mov") is False
    assert is_sequence_path("/j/frames/EX01_tk1-0001.tga") is False
    assert is_sequence_path("") is False


def test_is_sequence_path_accepts_identity():
    s = group_sequences("/j/frames", _frames("a_tk1", (1, 2)))[0]
    assert is_sequence_path(s.identity)


def test_temp_frames_dir_name():
    assert TEMP_FRAMES_DIR == "temp_frames"


def test_seqinfo_constructible_directly():
    s = SeqInfo(dir="/j", base="a", ext="tga", pad=4, first=1, last=10, count=8)
    assert s.missing == 2 and s.identity == os.path.join("/j", "a.seq")
