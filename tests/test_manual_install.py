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
def test_install_page_names_match_build(content):
    (setup,) = setting("installer/yesoncheck.iss", r"^OutputBaseFilename=(\w+_)\{#AppFileTag\}\s*$")
    (app_name,) = setting("installer/yesoncheck.iss", r'^#define MyAppName "([^"]+)"')
    labels = setting("build_app.sh", r'LABEL="(\w+)"')
    assert sorted(labels) == ["AppleSilicon", "Intel"]
    text = page_text(install_page(content))
    for name in (setup, app_name, *(f"YesonCheck_Autocut_{label}" for label in labels)):
        assert name in text, name


TEXT_FOR = {"ko": manual_content, "en": manual_content_en}


def release_tool():
    """tools/release.py — Release 파일 이름을 정하는 곳 (패키지가 아니라 파일에서 불러옴)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_for_manual", ROOT / "tools" / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("language, version_word", (("ko", "<버전>"), ("en", "<version>")))
def test_install_page_lists_the_release_file_names(language, version_word):
    """표의 파일 이름이 배포 도구가 Release에 올리는 이름 그대로 (버전 자리만 <버전>)."""
    text = page_text(install_page(TEXT_FOR[language]))
    templates = release_tool().ASSET_TEMPLATES
    assert sorted(templates) == ["mac-arm64", "mac-x86_64", "windows"]
    for template in templates.values():
        assert f"`{template.format(version_word)}`" in text, template


MINIMUM_PHRASE = {"ko": "macOS {} 이상", "en": "macOS {} or later"}  # 최소 버전을 말하는 문장 — 쪽의 'macOS 12는'·'macOS 15부터'와 섞이지 않게


@pytest.mark.parametrize("language", ("ko", "en"))
def test_install_page_states_the_exact_macos_minimum(language):
    (version,) = setting("YesonCheck_Autocut.spec", r"^MIN_MACOS = '([\d.]+)'")
    text = page_text(install_page(TEXT_FOR[language]))
    assert MINIMUM_PHRASE[language].format(version) in text
    # 버전이 바뀌면(예: 12) 실패하는지 — 쪽의 다른 'macOS 12…' 글에 맞아 잘못 통과하지 않음
    assert MINIMUM_PHRASE[language].format(version.split(".")[0]) not in text


@pytest.mark.parametrize("language, says", (("ko", "업데이트를 설치할 수 없"), ("en", "cannot install updates")))
def test_install_page_says_an_app_run_inside_the_dmg_cannot_update(language, says):
    """dmg 안(/Volumes)에서 연 Mac 앱은 업데이트도 기본 앱도 안 됨 (update_install·default_app) — 쪽이 둘 다 말함."""
    from yesoncheck import default_app, update_install

    inside = "/Volumes/YesonCheck_Autocut_AppleSilicon/YesonCheck_Autocut_AppleSilicon.app"
    assert update_install.refuse_reason_mac(inside) is not None
    assert default_app.location_problem(inside) is not None
    assert says in page_text(install_page(TEXT_FOR[language]))


@CONTENTS
def test_install_page_warns_against_installing_in_the_app_data_folder(content, tmp_path, monkeypatch):
    """Windows: 앱의 설정·기록 폴더(%LOCALAPPDATA%\\YesonCheck) 안에 설치한 앱은 업데이트할 수 없음 — 쪽이 그 폴더를 피하라고 말함."""
    from yesoncheck import paths, update_install

    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert update_install.refuse_reason_windows(str(tmp_path / "YesonCheck")) is not None
    assert "`%LOCALAPPDATA%\\YesonCheck`" in page_text(install_page(content))
