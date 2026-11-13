"""사용법 매뉴얼의 두 언어(한글·영문) — 영문 글이 한글과 같은 모양인지, 한 파일에 함께 들어가 전환되는지 (Qt 없음).

영문은 한글을 블록 하나하나 옮긴 것(`manual_content_en`·`release_notes_en`)이라 한쪽만 고치면 여기서 실패한다.
전환 동작 자체(단추·기억·주소)는 브라우저가 있어야 보이므로 여기서는 만들어진 HTML의 모양과 스크립트의 글자로만 확인한다.
"""
import re
from types import SimpleNamespace

import pytest

from yesoncheck import manual_content, manual_content_en, manual_html, manual_languages, release_notes, release_notes_en
from yesoncheck.manual_content import Page
from yesoncheck.release_notes import Release
from tests.test_manual_html import fake_image

HANGUL_RE = re.compile(r"[ㄱ-ㆎ가-힣]")
LETTER_RE = re.compile(r"[A-Za-zㄱ-ㆎ가-힣]")
PRIVATE = ("/Volumes/", "/Users/", "colordata", "usadata", "USA_DB")


def strings_of(content):
    """쪽 글 모듈의 모든 글 조각 (쪽 이름표와 함께)."""
    for page in content.PAGES:
        yield page.key, page.title
        yield page.key, page.lead
        for block in page.blocks:
            kind = block[0]
            if kind == "fig":
                yield page.key, block[2]
                for item in block[3]:
                    yield page.key, item
            elif kind == "keys":
                for _spec, text in block[1]:
                    yield page.key, text
            elif kind == "table":
                for row in ((block[1],) if block[1] else ()) + tuple(block[2]):
                    for cell in row:
                        yield page.key, cell
            elif kind in ("steps", "list"):
                for item in block[1]:
                    yield page.key, item
            else:
                yield page.key, block[1]


def note_strings(notes):
    for release in notes.RELEASES:
        yield release.version, release.summary
        for title, items in release.groups:
            if title:
                yield release.version, title
            for item in items:
                yield release.version, item


def hangul_share(texts):
    joined = "".join(texts)
    return len(HANGUL_RE.findall(joined)) / max(1, len(LETTER_RE.findall(joined)))


# ---------------------------------------------------------------- 진짜 글: 영문이 한글과 같은 모양


def test_english_manual_mirrors_the_korean_one():
    assert manual_languages.parity_problems() == []


def test_english_text_is_english():
    """영문 글에 한글은 화면의 한글 이름표(단추·메뉴)를 그대로 적은 것뿐 — 번역하지 않고 남은 문장이 없음."""
    assert hangul_share(text for _where, text in strings_of(manual_content_en)) < 0.12
    assert hangul_share(text for _where, text in note_strings(release_notes_en)) < 0.12
    assert hangul_share(text for _where, text in strings_of(manual_content)) > 0.5  # 재는 법이 맞는지 (한글 글은 한글)
    for group in manual_content_en.GROUPS:
        assert not HANGUL_RE.search(group)
    assert not HANGUL_RE.search(manual_content_en.RELEASES_TITLE + manual_content_en.RELEASES_LEAD)


def test_english_text_has_no_private_paths():
    for where, text in list(strings_of(manual_content_en)) + list(note_strings(release_notes_en)):
        for needle in PRIVATE:
            assert needle not in text, (where, needle, text[:60])


def test_languages_use_their_own_modules():
    korean, english = manual_languages.LANGUAGES
    assert (korean.code, korean.content, korean.notes) == ("ko", manual_content, release_notes)
    assert (english.code, english.content, english.notes) == ("en", manual_content_en, release_notes_en)
    assert set(korean.ui) == set(english.ui)
    assert set(korean.ui["callouts"]) == set(english.ui["callouts"]) == {"note", "tip", "warn"}
    assert set(manual_html.SCRIPT_UI_KEYS) <= set(korean.ui)


# ---------------------------------------------------------------- 모양 검사가 어긋남을 잡는지 (지어낸 글로)


def content(pages, groups=("묶음",), releases_group="묶음"):
    return SimpleNamespace(PAGES=tuple(pages), GROUPS=tuple(groups), RELEASES_GROUP=releases_group)


def one(blocks, key="a", group="묶음", lead="소개"):
    return Page(key, "제목", group, lead, tuple(blocks))


BASE_BLOCKS = (
    ("h", "절", "sec"),
    ("p", "글 {Space} [[a/sec|여기]]"),
    ("fig", "shot", "그림", ("하나", "둘")),
    ("keys", (("Space", "재생"), (("←", ","), "이전"), ("마우스 휠", "이동"), ("F (ㄹ)", "전체 화면"))),
    ("table", ("가", "나"), (("1", "2"), ("3", "4"))),
    ("steps", ("첫째", "둘째")),
    ("note", "알림"),
)
SAME_SHAPE = (
    ("h", "Section", "sec"),
    ("p", "Text {Space} [[a/sec|here]]"),
    ("fig", "shot", "Picture", ("one", "two")),
    ("keys", (("Space", "Play"), (("←", ","), "Previous"), ("Mouse wheel", "Move"), ("F (ㄹ)", "Full screen"))),
    ("table", ("A", "B"), (("1", "2"), ("3", "4"))),
    ("steps", ("first", "second")),
    ("note", "Note"),
)


def with_block(index, block):
    blocks = list(SAME_SHAPE)
    blocks[index] = block
    return content([one(blocks)])


def test_parity_check_accepts_a_faithful_translation():
    assert manual_languages.content_problems(content([one(BASE_BLOCKS)]), content([one(SAME_SHAPE)])) == []


@pytest.mark.parametrize("other, word", [
    (content([one(SAME_SHAPE), one((), key="b")]), "쪽 이름"),
    (content([one(SAME_SHAPE[:-1])]), "블록의 종류"),
    (with_block(0, ("h", "Section", "other")), "닻"),
    (with_block(1, ("p", "Text {Space} [[a|here]]")), "링크"),
    (with_block(1, ("p", "Text [[a/sec|here]]")), "키 표시"),
    (with_block(2, ("fig", "another", "Picture", ("one", "two"))), "그림이 다름"),
    (with_block(2, ("fig", "shot", "Picture", ("one",))), "그림 설명의 수"),
    (with_block(3, ("keys", (("Space", "Play"),))), "단축키 줄의 수"),
    (with_block(3, ("keys", (("Enter", "Play"), (("←", ","), "Previous"), ("Mouse wheel", "Move"), ("F (ㄹ)", "Full")))), "키가 다름"),
    (with_block(3, ("keys", (("Space", "Play"), ("←", "Previous"), ("Mouse wheel", "Move"), ("F (ㄹ)", "Full")))), "키의 수"),
    (with_block(3, ("keys", (("Space", "Play"), (("←", ","), "Previous"), ("Mouse wheel", "Move"), ("F", "Full")))), "키가 다름"),
    (with_block(4, ("table", None, (("1", "2"), ("3", "4")))), "표 머리"),
    (with_block(4, ("table", ("A", "B"), (("1", "2"),))), "표의 줄"),
    (with_block(5, ("steps", ("first",))), "항목의 수"),
    (content([one(SAME_SHAPE)], groups=("A", "B"), releases_group="B"), "묶음"),
])
def test_parity_check_names_what_differs(other, word):
    problems = manual_languages.content_problems(content([one(BASE_BLOCKS)]), other)
    assert problems and any(word in problem for problem in problems), problems


def notes(*releases):
    return SimpleNamespace(RELEASES=tuple(releases))


def test_notes_parity():
    base = notes(Release("1.1.0", "2026-01-02", "요약 [[a]]", (("묶음", ("하나", "둘")), ("", ("셋",)))))
    same = notes(Release("1.1.0", "2026-01-02", "Summary [[a]]", (("Group", ("one", "two")), ("", ("three",)))))
    assert manual_languages.notes_problems(base, same) == []
    for other, word in [
        (notes(), "버전·날짜"),
        (notes(Release("1.1.0", "2026-01-03", "Summary [[a]]", same.RELEASES[0].groups)), "버전·날짜"),
        (notes(Release("1.1.0", "2026-01-02", "Summary [[a]]", (("Group", ("one",)), ("", ("three",))))), "묶음·항목의 수"),
        (notes(Release("1.1.0", "2026-01-02", "Summary [[a]]", (("Group", ("one", "two")), ("Extra", ("three",))))), "묶음·항목의 수"),
        (notes(Release("1.1.0", "2026-01-02", "Summary", same.RELEASES[0].groups)), "링크"),
    ]:
        problems = manual_languages.notes_problems(base, other)
        assert problems and any(word in problem for problem in problems), problems


# ---------------------------------------------------------------- 한 파일에 두 언어


@pytest.fixture(scope="module")
def document():
    return manual_html.build(fake_image, version_text="1.2.3", current_version=release_notes.RELEASES[0].version)


def language_part(document, tag, code):
    """그 언어의 목차(nav) 또는 쪽들(div.doc) 부분."""
    classes = "l doc" if tag == "div" else "l"
    start = document.index(f'<{tag} class="{classes}" lang="{code}">')
    others = [document.find(f'<{tag} class="{classes}" lang="', start + 1), document.find("</aside>" if tag == "nav" else '<div class="pager">')]
    return document[start:min(position for position in others if position > start)]


def test_document_holds_both_languages_and_a_switch(document):
    for code, name in (("ko", "한국어"), ("en", "English")):
        assert f'<button type="button" data-lang="{code}">{name}</button>' in document
        assert f'<nav class="l" lang="{code}">' in document
        assert f'<div class="l doc" lang="{code}">' in document
    assert '<div class="ver">버전 1.2.3</div>' in document and '<div class="ver">Version 1.2.3</div>' in document
    assert "YesonCheck <span>사용법</span>" in document and "YesonCheck <span>Manual</span>" in document
    assert document.startswith('<!DOCTYPE html>\n<html lang="ko">')


def test_each_language_has_every_page_in_its_own_words(document):
    korean, english = language_part(document, "div", "ko"), language_part(document, "div", "en")
    for ko_page, en_page in zip(manual_content.PAGES, manual_content_en.PAGES):
        assert f'<section class="page" id="{ko_page.key}">' in korean
        assert f'<section class="page" id="en:{en_page.key}">' in english
        assert f"<h1>{ko_page.title}</h1>".replace("&", "&amp;") in korean
        assert f"<h1>{en_page.title}</h1>".replace("&", "&amp;") in english
    assert f"<h1>{manual_content_en.RELEASES_TITLE}</h1>" in english
    for release in release_notes_en.RELEASES:
        assert f'id="en:{manual_content.RELEASES_KEY}--v{release.version}"' in english
    assert '<span class="badge">지금 버전</span>' in korean and '<span class="badge">Current version</span>' in english
    assert '<span class="label">Note</span>' in english and '<span class="label">참고</span>' not in english
    nav = language_part(document, "nav", "en")
    for group in manual_content_en.GROUPS:
        assert f'<div class="group">{group.replace("&", "&amp;")}</div>' in nav


def test_ids_are_unique_and_addresses_are_shared(document):
    """요소 id는 문서에서 하나씩(영문은 `en:` 앞말), 링크의 주소는 두 언어가 같음 — 전환해도 보던 쪽에 머묾."""
    ids = re.findall(r' id="([^"]+)"', document)
    assert len(ids) == len(set(ids))
    korean, english = language_part(document, "div", "ko"), language_part(document, "div", "en")
    korean_ids = set(re.findall(r' id="([^"]+)"', korean))
    english_ids = set(re.findall(r' id="([^"]+)"', english))
    assert english_ids == {f"en:{value}" for value in korean_ids}
    targets = set(re.findall(r'href="#([^"]+)"', english)) | set(re.findall(r'href="#([^"]+)"', language_part(document, "nav", "en")))
    assert len(targets) > 60
    assert {f"en:{value}" for value in targets} <= english_ids


def test_pictures_are_embedded_once(document):
    """그림은 기준 언어(한글) 쪽에만 들어가고 영문 쪽은 이름으로 가리킴 — 파일 크기가 두 배가 되지 않게."""
    korean, english = language_part(document, "div", "ko"), language_part(document, "div", "en")
    figures = sum(1 for page in manual_content.PAGES for block in page.blocks if block[0] == "fig")
    assert document.count('src="data:image/png;base64,') == korean.count('src="data:image/png;base64,') == figures
    assert english.count("<img data-img=") == figures and "base64" not in english
    names = re.findall(r'<img data-img="([^"]+)" width="\d+" height="\d+"', english)
    assert names == re.findall(r'loading="lazy" data-img="([^"]+)">', korean)
    assert "sources[img.getAttribute('data-img')]" in manual_html.SCRIPT


def test_without_a_script_only_the_first_language_shows(document):
    assert ".l[lang] { display:none; }" in document
    assert ':root:not([data-lang]) .l[lang="ko"] { display:revert; }' in document
    for code in ("ko", "en"):
        assert f':root[data-lang="{code}"] .l[lang="{code}"] {{ display:revert; }}' in document


def test_script_gets_the_languages_and_their_words(document):
    assert "__CODES__" not in document and "__UI__" not in document
    assert 'var CODES = ["ko", "en"];' in document
    for words in ('"found": "{n}개 쪽에서 찾음 — Enter로 이동"', '"found": "Found on {n} page(s) — press Enter to go"',
                  '"manual": "사용법"', '"manual": "Manual"', '"search": "Search"', '"none": "No matches"'):
        assert words in document
    script = manual_html.SCRIPT
    assert "localStorage.getItem(LANG_KEY)" in script and "localStorage.setItem(LANG_KEY, lang)" in script
    assert "(navigator.language || '').toLowerCase().split('-')[0]" in script  # 처음에는 브라우저 언어
    assert "document.getElementById(prefix() + key + '--' + anchor)" in script  # 지금 언어의 절로
    assert "root.setAttribute('data-lang', lang);" in script and "root.setAttribute('lang', lang);" in script
    assert "q.value = '';  // 찾던 낱말은 앞 언어의 것" in script  # 언어를 바꾸면 찾기 칸을 비움
