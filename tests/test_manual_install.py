"""사용법 매뉴얼의 설치 쪽 — 자리와, 적은 사실(설치 폴더·macOS 최소 버전·파일·앱 이름)이 설치 설정과 같은지.

설치 파일(`installer/yesoncheck.iss`)·빌드 설정(spec·`build_app.sh`)이 바뀌면 매뉴얼의 글이 틀린 채 남지 않게, 값을 그 파일에서 읽어
쪽의 글과 견줌 (두 언어)."""
import pathlib
import re

import pytest

from yesoncheck import manual_content, manual_content_en

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENTS = pytest.mark.parametrize("content", (manual_content, manual_content_en), ids=("ko", "en"))


def install_page(content):
    pages = [item for item in content.PAGES if item.key == "install"]
    assert len(pages) == 1, [item.key for item in content.PAGES]
    return pages[0]


def page_text(item):
    """쪽 하나의 글 전부 (제목·소개·절 제목·문단·그림 설명·표 칸·목록·차례·알림 상자)."""
    texts = [item.title, item.lead]
    for block in item.blocks:
        kind = block[0]
        if kind in ("h", "p", "note", "tip", "warn"):
            texts.append(block[1])
        elif kind == "fig":
            texts += [block[2], *block[3]]
        elif kind == "keys":
            texts += [text for _spec, text in block[1]]
        elif kind == "table":
            texts += [cell for row in ((block[1] or ()), *block[2]) for cell in row]
        elif kind in ("steps", "list"):
            texts += list(block[1])
        else:
            raise AssertionError(f"모르는 블록: {kind}")
    return "\n".join(texts)


def setting(path, pattern):
    found = re.findall(pattern, (ROOT / path).read_text(encoding="utf-8"), re.MULTILINE)
    assert found, (path, pattern)
    return found


@CONTENTS
def test_install_page_follows_start_in_first_group(content):
    assert [item.key for item in content.PAGES][:2] == ["start", "install"]
    assert install_page(content).group == content.GROUPS[0]


@CONTENTS
def test_install_page_folder_matches_installer(content):
    (folder,) = setting("installer/yesoncheck.iss", r"^DefaultDirName=\{sd\}\\(\S+)\s*$")
    assert f"`C:\\{folder}`" in page_text(install_page(content))


@CONTENTS
def test_install_page_macos_minimum_matches_spec(content):
    (version,) = setting("YesonCheck_Autocut.spec", r"^MIN_MACOS = '([\d.]+)'")
    assert f"macOS {version}" in page_text(install_page(content))


@CONTENTS
def test_install_page_names_match_build(content):
    (setup,) = setting("installer/yesoncheck.iss", r"^OutputBaseFilename=(\w+_)\{#AppFileTag\}\s*$")
    (app_name,) = setting("installer/yesoncheck.iss", r'^#define MyAppName "([^"]+)"')
    labels = setting("build_app.sh", r'LABEL="(\w+)"')
    assert sorted(labels) == ["AppleSilicon", "Intel"]
    text = page_text(install_page(content))
    for name in (setup, app_name, *(f"YesonCheck_Autocut_{label}" for label in labels)):
        assert name in text, name
