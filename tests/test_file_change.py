"""열어 둔 파일이 디스크에서 다시 쓰였는지 (`file_change`) — 연 때의 모습(크기·고친 때)을 적어 두고 나중에 견줌.

왜: 열어 둔 영상이 다시 렌더링되면 그 캡처는 예전 파일을 가리켜 더 읽지 못하는데, 오류 창은 "VideoToolbox로 영상을 읽다가 도중에
실패 … 파일이 probe보다 짧거나 잘림" 같은 기술적인 글뿐이었음 — 사용자는 무슨 일인지 모름 (사용자 보고 2026-11-26).
예시 이름만 씀 (공개 저장소).
"""

import os
import threading
import time

import pytest

from yesoncheck import file_change


def write(path, data, mtime=None):
    with open(path, "wb") as fh:
        fh.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return str(path)


def test_an_untouched_file_has_not_changed(tmp_path):
    path = write(tmp_path / "shot.mov", b"x" * 1000, mtime=1_700_000_000)
    opened = file_change.stamp(path)

    assert opened == file_change.FileStamp(size=1000, mtime_ns=1_700_000_000 * 10**9)
    assert file_change.change_since(opened, path) is None
    assert file_change.rewritten_note(opened, path) is None


def test_a_file_written_again_is_seen_by_its_size_and_time(tmp_path):
    path = write(tmp_path / "shot.mov", b"x" * 2_500_000, mtime=1_700_000_000)
    opened = file_change.stamp(path)
    write(path, b"", mtime=1_700_000_600)  # 다시 쓰기 시작한 직후: 빈 파일

    change = file_change.change_since(opened, path)

    assert "크기 2.5MB → 0바이트" in change and "고친 때" in change and "→" in change


def test_the_same_size_with_a_newer_time_is_a_change_too(tmp_path):
    """다시 렌더링한 파일이 우연히 같은 크기여도 고친 때로 알아챔."""
    path = write(tmp_path / "shot.mov", b"x" * 1000, mtime=1_700_000_000)
    opened = file_change.stamp(path)
    write(path, b"y" * 1000, mtime=1_700_000_600)

    change = file_change.change_since(opened, path)

    assert "크기" not in change and "고친 때" in change


def test_a_file_that_is_gone_is_a_change(tmp_path):
    path = write(tmp_path / "shot.mov", b"x" * 1000)
    opened = file_change.stamp(path)
    os.remove(path)

    assert "지금은 파일이 없습니다" in file_change.change_since(opened, path)


def test_a_file_that_cannot_be_checked_now_is_not_called_a_change(tmp_path, monkeypatch):
    """지금 확인하지 못하는 것(NAS 연결 끊김·권한)은 '다시 쓰였다'가 아님 — 그 오류를 그대로 올림 (부른 쪽이 원래 오류 글로)."""
    path = write(tmp_path / "shot.mov", b"x" * 1000)
    opened = file_change.stamp(path)

    def refused(target, *args, **kwargs):
        raise PermissionError(13, "Permission denied", target)

    monkeypatch.setattr(file_change.os, "stat", refused)

    with pytest.raises(PermissionError):
        file_change.change_since(opened, path)


def test_the_note_says_what_happened_and_what_to_do_in_plain_words(tmp_path):
    path = write(tmp_path / "shot.mov", b"x" * 1000, mtime=1_700_000_000)
    opened = file_change.stamp(path)
    write(path, b"x" * 400, mtime=1_700_000_600)

    note = file_change.rewritten_note(opened, path)

    lines = note.splitlines()
    assert lines[0] == file_change.REWRITTEN_HEADLINE and lines[1] == file_change.REWRITTEN_ADVICE
    assert f"파일: {path}" in lines and any(line.startswith("바뀐 것: 크기 1000바이트 → 400바이트") for line in lines)
    for word in ("VideoToolbox", "ffmpeg", "probe", "리더"):  # 첫머리에는 기술 낱말 없이
        assert word not in file_change.REWRITTEN_HEADLINE + file_change.REWRITTEN_ADVICE
    assert "다시 렌더링" in file_change.REWRITTEN_HEADLINE and "다시 눌러 열어" in file_change.REWRITTEN_ADVICE
    assert "깨진" not in note  # 새 파일이 온전한지는 보지 않음(크기·고친 때만) — '깨진 것이 아니다'라고 하지 않음 (리뷰)


def test_stamping_a_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_change.stamp(str(tmp_path / "none.mov"))


@pytest.mark.parametrize("size, text", [(0, "0바이트"), (999, "999바이트"), (1000, "1000바이트"), (150_000, "150KB"),
                                         (22_402_773, "22.4MB"), (3_200_000_000, "3.2GB")])
def test_sizes_read_like_a_person_would_say_them(size, text):
    assert file_change.size_text(size) == text


def test_stamp_at_open_gives_the_stamp_or_why_not(tmp_path):
    """캡처 생성자용: 적어 두지 못해도 여는 일을 막지 않음(여는 쪽의 오류 규칙 그대로) — 사유는 도중 실패 때 함께 알림."""
    path = write(tmp_path / "shot.mov", b"x" * 10, mtime=1_700_000_000)

    assert file_change.stamp_at_open(path) == (file_change.stamp(path), None)

    opened, problem = file_change.stamp_at_open(str(tmp_path / "none.mov"))
    assert opened is None and "열 때 파일 모습" in problem and "FileNotFoundError" in problem
    opened, problem = file_change.stamp_at_open("bad\0name.mov")  # os.stat이 ValueError
    assert opened is None and "ValueError" in problem
    opened, problem = file_change.stamp_at_open(None)  # 경로가 아닌 값(TypeError)도 올리지 않음 — 여는 쪽이 자기 오류로 알림
    assert opened is None and "TypeError" in problem


def test_no_note_at_failure_for_an_untouched_file(tmp_path):
    """파일이 그대로면 쉬운 말 없음 — 캡처는 예전 글 그대로 알림. → (쉬운 말, 확인 못 한 사유 한 줄, 그 트레이스백)"""
    path = write(tmp_path / "shot.mov", b"x" * 10)
    opened, problem = file_change.stamp_at_open(path)

    assert file_change.note_at_failure(opened, problem, path) == (None, "", "")


def test_note_at_failure_for_a_rewritten_file(tmp_path):
    """다시 쓰였으면 쉬운 말(rewritten_note) — 캡처가 알림 창의 본문으로 씀."""
    path = write(tmp_path / "shot.mov", b"x" * 2000, mtime=1_700_000_000)
    opened, problem = file_change.stamp_at_open(path)
    write(path, b"", mtime=1_700_000_600)

    note, unchecked, trace = file_change.note_at_failure(opened, problem, path)

    assert (unchecked, trace) == ("", "") and note == file_change.rewritten_note(opened, path)
    assert note.startswith(file_change.REWRITTEN_HEADLINE) and note.count(f"파일: {path}") == 1


def test_note_at_failure_when_the_file_cannot_be_checked_says_so(tmp_path, monkeypatch):
    """지금 확인하지 못하면(NAS 끊김·권한) 다시 쓰였다고 하지 않음 — 쉬운 말 없이, 사유는 한 줄(창의 머리 쪽에 둘 글)과
    트레이스백(기록에 둘 글)으로 따로: 트레이스백을 창의 끝에 붙이면 거기 있어야 할 ffmpeg stderr가 밀려남 (리뷰)."""
    path = write(tmp_path / "shot.mov", b"x" * 10)
    opened, problem = file_change.stamp_at_open(path)

    def refused(target):
        raise PermissionError(13, "Permission denied", target)

    monkeypatch.setattr(file_change, "stamp", refused)
    note, unchecked, trace = file_change.note_at_failure(opened, problem, path)

    assert note is None and unchecked.startswith(f"{file_change.UNCHECKED_HEADLINE} — PermissionError: ")
    assert "\n" not in unchecked and path in unchecked
    assert trace.startswith("Traceback (most recent call last)") and "PermissionError" in trace


def test_note_at_failure_never_raises_even_on_an_unexpected_error(tmp_path, monkeypatch):
    """read 안에서 불림 — 견주다 난 예상 못 한 예외도 올리지 않고 글로 (원래 실패는 그대로 알려야 함)."""
    path = write(tmp_path / "shot.mov", b"x" * 10)
    opened, problem = file_change.stamp_at_open(path)

    def broken(target):
        raise RuntimeError("시험이 낸 오류\n둘째 줄")

    monkeypatch.setattr(file_change, "stamp", broken)
    note, unchecked, trace = file_change.note_at_failure(opened, problem, path)

    assert note is None and unchecked == f"{file_change.UNCHECKED_HEADLINE} — RuntimeError: 시험이 낸 오류"  # 한 줄만
    assert "RuntimeError: 시험이 낸 오류\n둘째 줄" in trace


def test_note_at_failure_without_a_stamp_from_open_says_why(tmp_path):
    """열 때 적어 두지 못했으면 견줄 것이 없음 — 쉬운 말 없이 그 사유."""
    path = str(tmp_path / "shot.mov")
    opened, problem = file_change.stamp_at_open(path)  # 없는 파일
    write(path, b"x" * 10)

    assert file_change.note_at_failure(opened, problem, path) == (None, f"{file_change.UNCHECKED_HEADLINE} — {problem}", "")


def test_note_at_failure_does_not_wait_for_storage_that_does_not_answer(tmp_path, monkeypatch):
    """NAS가 멈춰서 난 실패(캡처의 30초 한도)에서 같은 NAS의 파일을 확인하느라 화면이 또 멈추면 안 됨 — 확인은 한도
    (CHECK_TIMEOUT_S) 안에서만 기다리고, 넘으면 다시 쓰였다고 하지 않고 그 사유를 알림 (리뷰: hard mount의 stat은 끝없이 기다림)."""
    path = write(tmp_path / "shot.mov", b"x" * 10)
    opened, problem = file_change.stamp_at_open(path)
    gate = threading.Event()

    def stalled(target):
        gate.wait(20)  # 응답하지 않는 저장소
        raise OSError("시험 끝")

    monkeypatch.setattr(file_change, "stamp", stalled)
    monkeypatch.setattr(file_change, "CHECK_TIMEOUT_S", 0.2)
    started = time.monotonic()
    try:
        note, unchecked, trace = file_change.note_at_failure(opened, problem, path)
        waited = time.monotonic() - started
    finally:
        gate.set()

    assert waited < 5, f"확인을 {waited:.1f}초 기다렸습니다"
    assert note is None and trace == ""
    assert unchecked == f"{file_change.UNCHECKED_HEADLINE} — 0.2초 안에 파일을 확인하지 못함 (저장소가 응답하지 않는 것으로 보임)"


def test_module_has_no_qt():
    source = open(file_change.__file__, encoding="utf-8").read()
    assert "PyQt5" not in source
