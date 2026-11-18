"""사용법 매뉴얼 HTML(manual_html) — 글(manual_content)·바뀐 점(release_notes)·그림을 한 파일로 (Qt 없음)."""
import base64
import os
import re
import struct
import sys
import zlib

import pytest

from yesoncheck import manual_content, manual_content_en, manual_html, manual_open, release_notes
from yesoncheck.manual_languages import KOREAN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "yesoncheck", "manual_images")


def tiny_png(width=4, height=2):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (manual_html.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fake_image(name, language="ko"):
    return tiny_png()


def coloured_png(width, height, value):
    """value로 칠한 PNG — 바이트가 값마다 다름 (두 언어의 그림이 같은지·다른지를 보는 시험용)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + bytes((value, value, value)) * width for _ in range(height))
    return (manual_html.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def language_part(document, tag, code):
    """그 언어의 목차(nav) 또는 쪽들(div.doc) 부분 (test_manual_languages.language_part와 같은 자르기 — 그 모듈이 이 모듈을 불러 순환이 되므로 여기에도)."""
    classes = "l doc" if tag == "div" else "l"
    start = document.index(f'<{tag} class="{classes}" lang="{code}">')
    others = [document.find(f'<{tag} class="{classes}" lang="', start + 1), document.find("</aside>" if tag == "nav" else '<div class="pager">')]
    return document[start:min(position for position in others if position > start)]


def build_korean(load_image=fake_image, **kwargs):
    """한글만 든 매뉴얼 — 한글 글을 시험용으로 바꿔 끼운 시험이 씀 (두 언어가 함께 든 문서는 test_manual_languages)."""
    return manual_html.build(load_image, languages=(KOREAN,), **kwargs)


def page(blocks, key="start", group="시작"):
    return manual_content.Page(key, "쪽 제목", group, "소개", tuple(blocks))


@pytest.fixture
def one_page(monkeypatch):
    """글을 시험용 한 쪽으로 바꿔 끼움 → 블록들을 넣어 만든 HTML을 돌려주는 함수."""

    def build(blocks, **kwargs):
        monkeypatch.setattr(manual_content, "PAGES", (page(blocks),))
        return build_korean(**kwargs)

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
                "B (ㅠ)", "P (ㅔ)", "R (ㄱ)", "Ctrl+O", "Ctrl+휠", "↑", "↓", "Enter", "\\", "F5", "F1", "D (ㅇ)", "X (ㅌ)", "Ctrl+Z",
                # UI 개편(2026-11-16): 처음·끝(재생 줄), 영상 A 열기·폴더 열기·반복 재생·와이프 켜기(player_menus.KEY_SHORTCUTS)
                "Home", "End", "O (ㅐ)", "I (ㅑ)", "L (ㅣ)", "W (ㅈ)",
                # 사이드바 우클릭 메뉴의 일(player_menus.ITEM_KEY_SHORTCUTS, 2026-11-18): 파일 복사·합치기·미디어 정보·비디오 A·B로 열기
                "C (ㅊ)", "J (ㅓ)", "M (ㅡ)", "[", "]"):
        assert key in listed, key


def all_texts(content):
    """매뉴얼 글의 모든 글(쪽 제목·소개·절 제목·문단·그림 설명·표·목록·차례·알림 상자)."""
    texts = []
    for item in content.PAGES:
        texts += [item.title, item.lead]
        for block in item.blocks:
            kind = block[0]
            if kind in ("h", "p", "note", "tip", "warn"):
                texts.append(block[1])
            elif kind == "fig":
                texts += [block[2], *block[3]]
            elif kind == "keys":
                texts += [text for _spec, text in block[1]]
            elif kind == "table":
                texts += [cell for row in ([block[1]] if block[1] else []) + list(block[2]) for cell in row]
            elif kind in ("steps", "list"):
                texts += list(block[1])
    return texts


def test_korean_manual_names_main_window_texts_through_the_text_table():
    """메인 창의 이름은 {{키}}로 — 손으로 굵게 적은 글이 글자 표의 한국어 글과 같으면 실패 (글자 표를 고치면 매뉴얼이 따라가게).
    한 글자짜리('X'·'Y')와 값 자리가 든 글은 빼고."""
    from yesoncheck import ui_text

    values = {text for entry in ui_text.TEXTS.values() if "{" not in entry["ko"]
              for text in [manual_html._without_mnemonic(entry["ko"])] if len(text) >= 2}
    bolds = [found for text in all_texts(manual_content) for found in re.findall(r"\*\*(.+?)\*\*", text)]
    assert sorted({bold for bold in bolds if bold in values}) == []


def test_manual_text_has_no_private_paths():
    """저장소가 공개 — 매뉴얼 글에 이 PC·NAS의 경로나 작품 폴더 이름(`…_Animatic` 꼴)이 들어가면 안 됨
    (바뀐 점은 test_release_notes가 봄)."""

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
            assert "_animatic" not in text.lower(), (item.key, text[:60])  # 작품 폴더 이름 꼴 — 대소문자와 상관없이


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


def test_every_manual_image_is_in_the_repo_for_both_languages_and_none_is_left_over():
    """글이 쓰는 그림이 언어마다 모두 있고(빌드의 spec·앱이 읽음), 안 쓰는 그림이 남아 있지 않음 — 그림은 언어 폴더(ko·en)에만."""
    assert manual_html.IMAGE_LANGUAGES == ("ko", "en")
    for code in manual_html.IMAGE_LANGUAGES:
        folder = os.path.join(IMAGES, code)
        assert {name[:-4] for name in os.listdir(folder) if name.endswith(".png")} == set(manual_html.image_names()), code
        assert [name for name in os.listdir(folder) if not name.endswith(".png")] == [], code
    assert sorted(os.listdir(IMAGES)) == sorted(manual_html.IMAGE_LANGUAGES)  # 폴더 바로 아래에 그림이 남지 않음


def test_manual_images_are_png_at_the_capture_scale():
    for code in manual_html.IMAGE_LANGUAGES:
        for name in manual_html.image_names():
            width, height = manual_html.png_size(manual_open.load_image(name, code, folder=IMAGES), name)
            assert width % manual_html.IMAGE_SCALE == 0 and height % manual_html.IMAGE_SCALE == 0, (code, name, width, height)
            assert width >= 200 and height >= 100, (code, name, width, height)


def test_real_manual_builds_from_the_repo_images():
    text = manual_html.build(lambda name, code: manual_open.load_image(name, code, folder=IMAGES))
    assert len(text) > 1_000_000  # 그림이 들어감
    first = manual_html.image_names()[0]
    for code in manual_html.IMAGE_LANGUAGES:
        encoded = base64.b64encode(manual_open.load_image(first, code, folder=IMAGES)).decode("ascii")
        assert encoded in text, code


def test_each_language_gets_its_own_picture_and_identical_bytes_go_in_once(monkeypatch):
    """English 화면으로 찍은 그림은 영문 쪽에 제 그림으로 — 두 언어의 그림이 바이트까지 같으면(딸린 창만 찍은 그림) 한 번만 넣고
    영문 쪽은 이름으로 가리킴 (파일이 덜 커지게)."""
    from yesoncheck import manual_content_en

    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "shot", "그림", ()), ("fig", "same", "같은 그림", ())]),))
    monkeypatch.setattr(manual_content_en, "PAGES", (page([("fig", "shot", "Picture", ()), ("fig", "same", "Same", ())],
                                                          group=manual_content_en.GROUPS[0]),))
    pictures = {("shot", "ko"): coloured_png(400, 200, 1), ("shot", "en"): coloured_png(400, 200, 2),
                ("same", "ko"): coloured_png(400, 200, 3), ("same", "en"): coloured_png(400, 200, 3)}
    loaded = []

    def load(name, language):
        loaded.append((name, language))
        return pictures[(name, language)]

    document = manual_html.build(load)
    assert sorted(loaded) == sorted(pictures)
    korean, english = language_part(document, "div", "ko"), language_part(document, "div", "en")
    assert korean.count("data:image/png;base64,") == 2
    assert english.count("data:image/png;base64,") == 1
    assert base64.b64encode(pictures[("shot", "en")]).decode("ascii") in english  # shot은 English 그림 그대로
    assert english.count('<img data-img="same"') == 1  # same은 한국어 그림을 가리킴
    assert 'data-img="shot"' not in english  # 제 그림을 넣은 것은 이름 표를 덮지 않음


# ---------------------------------------------------------------- 화면 글자 표시 {{키}}

@pytest.mark.parametrize("source, korean, english", [
    ("{{sidebar.open_folder}}", '<strong class="ui">폴더 열기</strong>', '<strong class="ui">Open folder</strong>'),
    ("{{menu.file}} 메뉴", '<strong class="ui">File</strong> 메뉴', '<strong class="ui">File</strong> 메뉴'),  # &File의 & 지움
    ("{{transport.wipe}}", '<strong class="ui">A|B 와이프</strong>', '<strong class="ui">A|B Wipe</strong>'),
])
def test_ui_text_markup_shows_the_screen_text_of_each_language(monkeypatch, source, korean, english):
    from yesoncheck import manual_content_en

    monkeypatch.setattr(manual_content, "PAGES", (page([("p", source)]),))
    monkeypatch.setattr(manual_content_en, "PAGES", (page([("p", source)], group=manual_content_en.GROUPS[0]),))
    document = manual_html.build(fake_image)
    assert f"<p>{korean}</p>" in language_part(document, "div", "ko")
    assert f"<p>{english}</p>" in language_part(document, "div", "en")


def test_ui_text_mnemonic_ampersands_are_removed_but_a_doubled_one_stays():
    assert manual_html._without_mnemonic("&File") == "File"
    assert manual_html._without_mnemonic("A && B") == "A & B"
    assert manual_html._without_mnemonic("&&File &x") == "&File x"


@pytest.mark.parametrize("source, message", [
    ("{{sidebar.nope}}", "모르는 화면 글자 키: sidebar.nope"),
    ("{{open_with.app}}", "값이 필요한 화면 글자는 매뉴얼에 쓸 수 없음: open_with.app"),  # 글에 {app}
])
def test_ui_text_markup_with_an_unknown_key_or_a_value_slot_fails_the_build(one_page, source, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        one_page([("p", source)])


def test_ui_text_markup_is_plain_text_in_alt_and_not_a_key(one_page):
    """그림의 alt는 화면 글자 그대로(굵게 없이), 표시 안의 {a.b}가 키 표시로 잘못 나뉘지 않음."""
    text = one_page([("fig", "shot", "{{sidebar.refresh}} 단추", ()), ("p", "{{sidebar.refresh}}")])
    assert 'alt="새로고침 단추"' in text
    assert "<kbd>" not in text


def test_release_notes_do_not_read_ui_text_markup(monkeypatch):
    releases = (release_notes.Release("9.9.9", None, "요약 {{sidebar.refresh}}", (("", ("항목",)),)),)
    monkeypatch.setattr(release_notes, "RELEASES", releases)
    assert "요약 {{sidebar.refresh}}" in build_korean(fake_image)


def test_screenshot_tool_makes_exactly_the_images_the_manual_uses():
    """그림을 찍는 도구의 샷 이름 = 매뉴얼이 쓰는 그림 이름 (한쪽에만 더하면 여기서 드러남)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import make_manual_screenshots
    finally:
        sys.path.remove(os.path.join(ROOT, "tools"))
    assert set(make_manual_screenshots.SHOTS) == set(manual_html.image_names())
    assert make_manual_screenshots.SCALE == manual_html.IMAGE_SCALE
    assert make_manual_screenshots.LANGUAGES == manual_html.IMAGE_LANGUAGES  # 그림 두 벌 — 매뉴얼의 두 언어


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
    text = build_korean(fake_image)
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
        build_korean(fake_image)
    monkeypatch.setattr(manual_content, "PAGES", (page([], key="a"), page([], key="a")))
    with pytest.raises(ValueError, match="겹칩니다"):
        build_korean(fake_image)
    monkeypatch.setattr(manual_content, "PAGES", (page([], key=manual_content.RELEASES_KEY),))
    with pytest.raises(ValueError, match="업데이트 내역"):
        build_korean(fake_image)


def test_figure_size_legend_and_layout(monkeypatch):
    sizes = {"narrow": (400, 600), "wide": (2000, 1000)}
    monkeypatch.setattr(manual_content, "PAGES", (page([
        ("fig", "narrow", "좁은 <그림>", ("**하나**", "둘")),
        ("fig", "wide", "넓은 그림", ("하나",)),
        ("fig", "wide", "설명 없는 그림", ()),
    ]),))
    loaded = []

    def load(name, language="ko"):
        loaded.append(name)
        return tiny_png(*sizes[name])

    text = build_korean(load)
    assert loaded == ["narrow", "wide", "wide"]
    assert '<figure class="fig beside">' in text and 'width="200" height="300" alt="좁은 &lt;그림&gt;"' in text
    assert '<figure class="fig below">' in text and 'width="1000" height="500"' in text
    assert '<figure class="fig">' in text
    assert '<ol class="legend"><li><span class="n">1</span><div><strong>하나</strong></div></li><li><span class="n">2</span>' in text
    assert "<figcaption>좁은 &lt;그림&gt;</figcaption>" in text


def test_missing_image_error_is_not_swallowed(monkeypatch):
    def missing(name, language="ko"):
        raise FileNotFoundError(name)

    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "nowhere", "그림", ())]),))
    with pytest.raises(FileNotFoundError, match="nowhere"):
        build_korean(missing)


def test_not_a_png_is_rejected(monkeypatch):
    monkeypatch.setattr(manual_content, "PAGES", (page([("fig", "x", "그림", ())]),))
    with pytest.raises(ValueError, match="PNG가 아닌"):
        build_korean(lambda name, language="ko": b"GIF89a" + b"\x00" * 40)


def test_release_notes_do_not_turn_braces_into_keys(monkeypatch):
    releases = (release_notes.Release("9.9.9", None, "요약 {이건 키가 아님} **굵게** `코드`", (("", ("항목 {그대로}",)),)),)
    monkeypatch.setattr(release_notes, "RELEASES", releases)
    text = build_korean(fake_image)
    assert "요약 {이건 키가 아님} <strong>굵게</strong> <code>코드</code>" in text
    assert "<li>항목 {그대로}</li>" in text
    assert "<h3>" not in text.split('id="releases"')[1]  # 제목 없는 묶음은 제목 줄이 없음


UI_PARTICLE_RE = re.compile(r"\{\{(?P<key>[a-z0-9_.]+)\}\}(?P<particle>으로|로|이|가|을|를|은|는|과|와)(?![가-힣])")
UI_THEN_KEY_RE = re.compile(r"\{\{(?P<ui>[a-z0-9_.]+)\}\}(?P<gap>[^{}\n]{0,6}?)(?<!\{)\{(?P<key>[^{}]+)\}(?!\})")


def test_korean_particles_after_screen_text_follow_the_text():
    """{{키}} 바로 뒤에 손으로 붙인 조사가 글자 표의 그 글과 맞음 — '주석로'·'목록로' 같은 글이 렌더되지 않게, 글자 표의 글이
    바뀌면 여기서 드러나게 (UI 개편 PR 4 리뷰 I-1). 읽는 소리를 모르는 끝(영문·괄호)은 ui_text.particle이 두 꼴을 함께 주므로 건너뜀."""
    from yesoncheck import ui_text

    pair_of = {part: pair for pair in ui_text.PARTICLE_PAIRS for part in pair.split("/")}
    wrong = []
    for text in all_texts(manual_content):
        for match in UI_PARTICLE_RE.finditer(text):
            screen = manual_html._without_mnemonic(ui_text.TEXTS[match["key"]]["ko"])
            expected = ui_text.particle(screen, pair_of[match["particle"]])
            if "(" in expected:
                continue
            if expected != match["particle"]:
                wrong.append(f"{screen}{match['particle']} → {screen}{expected}")
    assert wrong == []


@pytest.mark.parametrize("content", [manual_content, manual_content_en], ids=["ko", "en"])
def test_shortcut_already_in_screen_text_is_not_written_again(content):
    """글자 표의 글에 이미 '(L)'처럼 단축키가 들어 있으면 바로 뒤에 {L}을 또 적지 않음 — '반복 재생 (L)(L)'·'북마크 관리… (P)나 P'
    (UI 개편 PR 4 리뷰 I-1)."""
    from yesoncheck import ui_text

    language = "ko" if content is manual_content else "en"
    doubled = []
    for text in all_texts(content):
        for match in UI_THEN_KEY_RE.finditer(text):
            screen = manual_html._without_mnemonic(ui_text.TEXTS[match["ui"]][language])
            if f"({match['key']})" in screen:
                doubled.append(match.group(0))
    assert doubled == []
