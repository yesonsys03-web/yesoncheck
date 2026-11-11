"""사용법 매뉴얼 HTML(manual_html) — 글(manual_content)·바뀐 점(release_notes)·그림을 한 파일로 (Qt 없음)."""
import base64
import os
import re
import struct
import sys
import zlib

import pytest

from yesoncheck import manual_content, manual_html, manual_open, release_notes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "yesoncheck", "manual_images")


def tiny_png(width=4, height=2):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (manual_html.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fake_image(name):
    return tiny_png()


def page(blocks, key="start", group="시작"):
    return manual_content.Page(key, "쪽 제목", group, "소개", tuple(blocks))


@pytest.fixture
def one_page(monkeypatch):
    """글을 시험용 한 쪽으로 바꿔 끼움 → 블록들을 넣어 만든 HTML을 돌려주는 함수."""

    def build(blocks, **kwargs):
        monkeypatch.setattr(manual_content, "PAGES", (page(blocks),))
        return manual_html.build(fake_image, **kwargs)

    return build


# ---------------------------------------------------------------- 진짜 글 전체


def test_real_manual_builds_with_every_page_and_release():
    text = manual_html.build(fake_image, version_text="1.9.0", current_version="1.9.0")
    assert text.startswith("<!DOCTYPE html>")
    for item in manual_content.PAGES:
        assert f'<section class="page" id="{item.key}">' in text
        assert f'<a href="#{item.key}" data-page="{item.key}">' in text
    assert f'<section class="page" id="{manual_content.RELEASES_KEY}">' in text
    for release in release_notes.RELEASES:
        assert f'id="{manual_content.RELEASES_KEY}--v{release.version}"' in text
    assert "버전 1.9.0" in text


def test_real_manual_links_all_resolve():
    """목차·쪽 안의 링크가 모두 실제 쪽·절의 id를 가리킴 (`#쪽`·`#쪽--닻` — 스크립트가 꺼져 있어도 그 자리로 감)."""
    text = manual_html.build(fake_image)
    ids = set(re.findall(r'id="([^"]+)"', text))
    targets = set(re.findall(r'href="#([^"]+)"', text))
    assert len(targets) > 60
    assert targets <= ids, sorted(targets - ids)
    assert any("--" in target for target in targets)


def test_real_manual_is_self_contained():
    """인터넷 없이 열려야 함 — 바깥 주소를 부르는 태그가 없음 (그림은 data: 로 들어감)."""
    text = manual_html.build(fake_image)
    assert not re.search(r'(src|href)="(https?:)?//', text)
    assert "<link" not in text and "@import" not in text
    assert text.count('src="data:image/png;base64,') == len(
        [block for item in manual_content.PAGES for block in item.blocks if block[0] == "fig"])


def test_shortcuts_page_lists_every_key_the_code_handles():
    """단축키 쪽을 빼놓지 않게: 코드가 받는 키(player_playback.keyPressEvent·player_base.eventFilter·검토 창 QShortcut)가 표에 있음."""
    shortcuts = next(item for item in manual_content.PAGES if item.key == "shortcuts")
    listed = []
    for block in shortcuts.blocks:
        if block[0] == "keys":
            for spec, _text in block[1]:
                listed.extend((spec,) if isinstance(spec, str) else spec)
    for key in ("Space", "←", "→", ",", ".", "+", "=", "2", "-", "1", "3", "4", "F (ㄹ)", "Shift+F", "V (ㅍ)", "N (ㅜ)", "T (ㅅ)",
                "B (ㅠ)", "P (ㅔ)", "R (ㄱ)", "Ctrl+O", "Ctrl+휠", "↑", "↓", "Enter", "\\", "F5", "F1", "D (ㅇ)", "X (ㅌ)", "Ctrl+Z"):
        assert key in listed, key


def test_manual_text_has_no_private_paths():
    """저장소가 공개 — 매뉴얼 글에 이 PC·NAS의 경로가 들어가면 안 됨 (바뀐 점은 test_release_notes가 봄)."""

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, tuple):
            for item in value:
                yield from strings(item)

    for item in manual_content.PAGES:
        for text in strings((item.title, item.lead, item.blocks)):
            for needle in ("/Volumes/", "/Users/", "colordata", "usadata", "USA_DB"):
                assert needle not in text, (item.key, needle, text[:60])


def test_script_routes_by_element_id_and_survives_a_broken_address():
    """주소는 `#쪽--닻`(= id)로 나누고, 깨진 퍼센트 인코딩은 모르는 쪽처럼 다룸 — 브라우저 없이는 글자로만 확인
    (동작은 헤드리스 크롬으로 봄: CLAUDE.md '사용법 매뉴얼')."""
    assert "hash.indexOf('--')" in manual_html.SCRIPT
    assert "try { hash = decodeURIComponent(hash); } catch (e) { hash = ''; }" in manual_html.SCRIPT
    assert "if (a && a.getAttribute('href') === location.hash) route();" in manual_html.SCRIPT


def test_groups_cover_every_page():
    groups = {item.group for item in manual_content.PAGES} | {manual_content.RELEASES_GROUP}
    assert groups <= set(manual_content.GROUPS)


def test_current_version_gets_the_badge_only_when_it_is_a_listed_release():
    newest, older = release_notes.RELEASES[0].version, release_notes.RELEASES[1].version
    text = manual_html.build(fake_image, current_version=older)
    assert text.count(f'<span class="badge">{manual_html.CURRENT_BADGE}</span>') == 1
    assert f'--v{older}">{older}<span class="badge">' in text
    assert f'--v{newest}">{newest}<span class="badge">' not in text
    assert '<span class="badge">' not in manual_html.build(fake_image, current_version=None)
    assert '<span class="badge">' not in manual_html.build(fake_image, current_version="0.0.1")


def test_version_text_is_optional_and_escaped():
    assert 'class="ver"' not in manual_html.build(fake_image)
    assert '<div class="ver">버전 1.2.3+abc &lt;시험&gt;</div>' in manual_html.build(fake_image, version_text="1.2.3+abc <시험>")


# ---------------------------------------------------------------- 저장소의 그림


def test_every_manual_image_is_in_the_repo_and_none_is_left_over():
    """글이 쓰는 그림이 모두 있고(빌드의 spec·앱이 읽음), 안 쓰는 그림이 폴더에 남아 있지 않음."""
    on_disk = {name[:-4] for name in os.listdir(IMAGES) if name.endswith(".png")}
    assert set(manual_html.image_names()) == on_disk
    assert [name for name in os.listdir(IMAGES) if not name.endswith(".png")] == []


def test_manual_images_are_png_at_the_capture_scale():
    for name in manual_html.image_names():
        width, height = manual_html.png_size(manual_open.load_image(name, IMAGES), name)
        assert width % manual_html.IMAGE_SCALE == 0 and height % manual_html.IMAGE_SCALE == 0, (name, width, height)
        assert width >= 200 and height >= 100, (name, width, height)


def test_real_manual_builds_from_the_repo_images():
    text = manual_html.build(lambda name: manual_open.load_image(name, IMAGES))
    assert len(text) > 1_000_000  # 그림이 들어감
    first = manual_html.image_names()[0]
    encoded = base64.b64encode(manual_open.load_image(first, IMAGES)).decode("ascii")
    assert encoded in text


def test_screenshot_tool_makes_exactly_the_images_the_manual_uses():
    """그림을 찍는 도구의 샷 이름 = 매뉴얼이 쓰는 그림 이름 (한쪽에만 더하면 여기서 드러남)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import make_manual_screenshots
    finally:
        sys.path.remove(os.path.join(ROOT, "tools"))
    assert set(make_manual_screenshots.SHOTS) == set(manual_html.image_names())
    assert make_manual_screenshots.SCALE == manual_html.IMAGE_SCALE


def test_legend_numbers_do_not_exceed_what_fits_a_badge():
    for item in manual_content.PAGES:
        for block in item.blocks:
            if block[0] == "fig":
                assert len(block[3]) <= 9, (item.key, block[1])


# ---------------------------------------------------------------- 글 안의 표시·블록


def test_inline_markup(one_page):
    text = one_page([("p", "**굵게** `코드 <a>` {Space} 그리고 <이름> & 끝")])
    assert "<p><strong>굵게</strong> <code>코드 &lt;a&gt;</code> " in text
    assert '<span class="keycombo"><kbd>Space</kbd></span>' in text
    assert "&lt;이름&gt; &amp; 끝</p>" in text


@pytest.mark.parametrize("source, expected", [
    ("`**`와 **굵게**", "<code>**</code>와 <strong>굵게</strong>"),  # 코드 안의 **는 굵게가 아님
    ("`{x}` 와 `[[nowhere]]`", "<code>{x}</code> 와 <code>[[nowhere]]</code>"),  # 코드 안은 글자 그대로 (모르는 쪽이어도)
    ("`a < b & c`", "<code>a &lt; b &amp; c</code>"),
    ("{<} {Shift+&}", '<span class="keycombo"><kbd>&lt;</kbd></span> <span class="keycombo"><kbd>Shift</kbd>'
                      '<span class="plus">+</span><kbd>&amp;</kbd></span>'),  # 키 안의 글자를 두 번 escape하지 않음
    ("**a `b` {F5}**", '<strong>a <code>b</code> <span class="keycombo"><kbd>F5</kbd></span></strong>'),
    ("[[start|<b> & 글]]", '<a class="xref" href="#start">&lt;b&gt; &amp; 글</a>'),
    ("**[[start]]**", '<strong><a class="xref" href="#start">쪽 제목</a></strong>'),
])
def test_inline_markup_is_tokenized_from_the_source_text(one_page, source, expected):
    assert f"<p>{expected}</p>" in one_page([("p", source)])


@pytest.mark.parametrize("broken", ["**짝 없는 굵게", "짝 없는 ` 코드", "**a `b**c` d**", "{Ctrl+}", "{+F}"])
def test_unbalanced_markup_and_empty_keys_fail_the_build(one_page, broken):
    """깨진 HTML을 조용히 만들지 않음."""
    with pytest.raises(ValueError):
        one_page([("p", broken)])


def test_figure_alt_text_has_no_markup(monkeypatch):
    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "x", "**굵은** `코드` {F5} [[start|글]] <끝>", ())]),))
    text = manual_html.build(fake_image)
    assert 'alt="굵은 코드 F5 글 &lt;끝&gt;"' in text
    assert "<figcaption><strong>굵은</strong> <code>코드</code> " in text


def test_key_shapes():
    key = manual_html._Builder.key
    assert key("Space") == '<span class="keycombo"><kbd>Space</kbd></span>'
    assert key("Shift+F") == '<span class="keycombo"><kbd>Shift</kbd><span class="plus">+</span><kbd>F</kbd></span>'
    assert key("+") == '<span class="keycombo"><kbd>+</kbd></span>'  # 더하기 키 자신은 나누지 않음
    assert key("F (ㄹ)") == '<span class="keycombo"><kbd>F</kbd><span class="hangul">ㄹ</span></span>'
    assert key("\\") == '<span class="keycombo"><kbd>\\</kbd></span>'
    assert key("Ctrl++") == '<span class="keycombo"><kbd>Ctrl</kbd><span class="plus">+</span><kbd>+</kbd></span>'  # 끝의 +는 키


def test_keys_table_takes_one_key_or_several(one_page):
    text = one_page([("keys", (("Space", "재생"), (("←", ","), "이전 프레임")))])
    assert '<table class="keys">' in text
    assert '<kbd>←</kbd></span><span class="or">·</span><span class="keycombo"><kbd>,</kbd>' in text
    assert "<td>이전 프레임</td>" in text


def test_table_steps_list_and_callouts(one_page):
    text = one_page([
        ("table", ("이름", "뜻"), (("**첫 칸**", "둘째 칸"),)),
        ("table", None, (("머리 없는 표", "값"),)),
        ("steps", ("하나", "둘")),
        ("list", ("점 하나",)),
        ("note", "참고 글"), ("tip", "팁 글"), ("warn", "주의 글"),
    ])
    assert "<thead><tr><th>이름</th><th>뜻</th></tr></thead>" in text
    assert '<tr><th scope="row"><strong>첫 칸</strong></th><td>둘째 칸</td></tr>' in text
    assert text.count("<thead>") == 1
    assert '<ol class="steps"><li>하나</li><li>둘</li></ol>' in text
    assert "<ul><li>점 하나</li></ul>" in text
    for kind, label in manual_html.CALLOUT_LABELS.items():
        assert f'<div class="callout {kind}"><span class="label">{label}</span>' in text


def test_headings_get_page_scoped_ids_and_chips_from_three(one_page):
    text = one_page([("h", "하나", "a"), ("h", "둘", "b")])
    assert '<h2 id="start--a">하나</h2>' in text
    assert 'class="onpage"' not in text.split("</style>")[1].split('id="releases"')[0]
    text = one_page([("h", "하나", "a"), ("h", "둘", "b"), ("h", "셋", "c")])
    assert '<div class="onpage"><a href="#start--a">하나</a><a href="#start--b">둘</a><a href="#start--c">셋</a></div>' in text


def test_links_between_pages(one_page):
    text = one_page([("h", "절", "part"), ("p", "[[start]] 그리고 [[start/part|그 절]] 그리고 [[releases]]")])
    assert '<a class="xref" href="#start">쪽 제목</a>' in text
    assert '<a class="xref" href="#start--part">그 절</a>' in text  # 주소 = 그 절의 id (스크립트 없이도 감)
    assert f'<a class="xref" href="#releases">{manual_content.RELEASES_TITLE}</a>' in text


@pytest.mark.parametrize("bad, message", [
    ("[[nowhere]]", "모르는 쪽"),
    ("[[start/nowhere]]", "모르는 닻"),
])
def test_broken_links_fail_the_build(one_page, bad, message):
    with pytest.raises(ValueError, match=message):
        one_page([("p", bad)])


def test_unknown_block_duplicate_anchor_and_unknown_group_fail_the_build(one_page, monkeypatch):
    with pytest.raises(ValueError, match="모르는 블록"):
        one_page([("video", "x")])
    with pytest.raises(ValueError, match="겹치는 닻"):
        one_page([("h", "하나", "a"), ("h", "둘", "a")])
    monkeypatch.setattr(manual_content, "PAGES", (page([], group="없는 묶음"),))
    with pytest.raises(ValueError, match="없는 묶음"):
        manual_html.build(fake_image)
    monkeypatch.setattr(manual_content, "PAGES", (page([], key="a"), page([], key="a")))
    with pytest.raises(ValueError, match="겹칩니다"):
        manual_html.build(fake_image)
    monkeypatch.setattr(manual_content, "PAGES", (page([], key=manual_content.RELEASES_KEY),))
    with pytest.raises(ValueError, match="업데이트 내역"):
        manual_html.build(fake_image)


def test_figure_size_legend_and_layout(monkeypatch):
    sizes = {"narrow": (400, 600), "wide": (2000, 1000)}
    monkeypatch.setattr(manual_content, "PAGES", (page([
        ("fig", "narrow", "좁은 <그림>", ("**하나**", "둘")),
        ("fig", "wide", "넓은 그림", ("하나",)),
        ("fig", "wide", "설명 없는 그림", ()),
    ]),))
    loaded = []

    def load(name):
        loaded.append(name)
        return tiny_png(*sizes[name])

    text = manual_html.build(load)
    assert loaded == ["narrow", "wide", "wide"]
    assert '<figure class="fig beside">' in text and 'width="200" height="300" alt="좁은 &lt;그림&gt;"' in text
    assert '<figure class="fig below">' in text and 'width="1000" height="500"' in text
    assert '<figure class="fig">' in text
    assert '<ol class="legend"><li><span class="n">1</span><div><strong>하나</strong></div></li><li><span class="n">2</span>' in text
    assert "<figcaption>좁은 &lt;그림&gt;</figcaption>" in text


def test_missing_image_error_is_not_swallowed(monkeypatch):
    def missing(name):
        raise FileNotFoundError(name)

    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "nowhere", "그림", ())]),))
    with pytest.raises(FileNotFoundError, match="nowhere"):
        manual_html.build(missing)


def test_not_a_png_is_rejected(monkeypatch):
    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "x", "그림", ())]),))
    with pytest.raises(ValueError, match="PNG가 아닌"):
        manual_html.build(lambda name: b"GIF89a" + b"\x00" * 40)


def test_release_notes_do_not_turn_braces_into_keys(monkeypatch):
    releases = (release_notes.Release("9.9.9", None, "요약 {이건 키가 아님} **굵게** `코드`", (("", ("항목 {그대로}",)),)),)
    monkeypatch.setattr(release_notes, "RELEASES", releases)
    text = manual_html.build(fake_image)
    assert "요약 {이건 키가 아님} <strong>굵게</strong> <code>코드</code>" in text
    assert "<li>항목 {그대로}</li>" in text
    assert "<h3>" not in text.split('id="releases"')[1]  # 제목 없는 묶음은 제목 줄이 없음
