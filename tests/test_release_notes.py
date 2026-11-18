"""버전별 바뀐 점(release_notes) — 사용법 매뉴얼의 '업데이트 내역'과 배포 노트의 한 출처."""
import os
import re
import subprocess
import sys

import pytest

from yesoncheck import release_notes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def test_releases_are_newest_first_without_duplicates():
    keys = [release_notes.version_key(release.version) for release in release_notes.RELEASES]
    assert keys == sorted(keys, reverse=True)
    assert len(set(keys)) == len(keys)


def test_every_release_has_a_summary_and_items():
    for release in release_notes.RELEASES:
        assert release.summary.strip(), release.version
        assert release.groups, release.version
        for title, items in release.groups:
            assert isinstance(title, str) and items, (release.version, title)
            assert all(isinstance(item, str) and item.strip() for item in items), (release.version, title)


def test_only_the_newest_release_may_lack_a_date():
    """날짜가 없는 항목은 아직 배포하지 않은 맨 위 하나뿐 — 그 아래는 배포한 날(한국 시각)이 적혀 있어야 함."""
    for index, release in enumerate(release_notes.RELEASES):
        if release.date is None:
            assert index == 0, release.version
        else:
            assert DATE_RE.fullmatch(release.date), (release.version, release.date)


def test_notes_have_no_private_paths():
    """저장소가 공개 — 배포 노트·매뉴얼에 이 PC·NAS의 경로나 작품 폴더 이름(`…_Animatic` 꼴)이 들어가면 안 됨."""
    for release in release_notes.RELEASES:
        text = release_notes.notes_text(release.version)
        for needle in ("/Volumes/", "/Users/", "colordata", "usadata"):
            assert needle not in text, (release.version, needle)
        assert "_animatic" not in text.lower(), release.version  # 작품 폴더 이름 꼴 — 대소문자와 상관없이


def test_notes_text_shape():
    release = release_notes.find("1.8.1")
    text = release_notes.notes_text("1.8.1")
    blocks = text.rstrip("\n").split("\n\n")
    assert blocks[0] == release.summary
    assert len(blocks) == 1 + len(release.groups)
    first_title, first_items = release.groups[0]
    assert blocks[1].split("\n") == [first_title] + [f"- {item}" for item in first_items]
    assert blocks[-1] == "- Mac은 B 키 글자 외에 바뀐 것이 없습니다."  # 제목 없는 묶음은 항목만
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_unknown_version_is_not_invented():
    with pytest.raises(LookupError, match="9.9.9"):
        release_notes.find("9.9.9")
    with pytest.raises(LookupError):
        release_notes.notes_text("9.9.9")


@pytest.mark.parametrize("bad", ["1.9", "v1.9.0", "1.9.0+abc", ""])
def test_version_key_rejects_other_shapes(bad):
    with pytest.raises(ValueError):
        release_notes.version_key(bad)


def test_version_key_orders_by_number_not_text():
    assert release_notes.version_key("1.10.0") > release_notes.version_key("1.9.0")


def test_command_prints_the_notes_for_deploy():
    """배포할 때 `python -m yesoncheck.release_notes X.Y.Z > notes.md`로 노트 파일을 뽑음."""
    version = release_notes.RELEASES[0].version
    done = subprocess.run([sys.executable, "-m", "yesoncheck.release_notes", version], cwd=ROOT, capture_output=True,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert done.stdout.decode("utf-8").replace("\r\n", "\n") == release_notes.notes_text(version)


def test_command_fails_loudly_for_an_unknown_version():
    done = subprocess.run([sys.executable, "-m", "yesoncheck.release_notes", "9.9.9"], cwd=ROOT, capture_output=True,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert done.returncode != 0
    assert done.stdout == b""
    assert "9.9.9" in done.stderr.decode("utf-8", "replace")


def test_newest_release_is_the_ui_redesign():
    """2.0.0(UI 개편 — 사용자 결정 2026-11-17, 1.10.0이 아니라 2.0.0)의 노트가 두 언어로 맨 위에 — 날짜는 배포의 0번에서
    넣음 (BUILD.md 7-1)."""
    from yesoncheck import release_notes_en

    for notes in (release_notes, release_notes_en):
        assert [(r.version, r.date) for r in notes.RELEASES[:2]] == [("2.0.1", "2026-11-18"), ("2.0.0", "2026-11-17")], notes.__name__
    text = release_notes.notes_text("2.0.0")
    assert "화면 언어" in text and "재생 줄" in text
    text = release_notes.notes_text("2.0.1")  # 2.0.1 — 사이드바 키·와이프를 끄면 B를 닫음·매뉴얼 설치 쪽 (사용자 지시 2026-11-18)
    assert "사이드바 단축키" in text and "와이프" in text and "설치" in text
