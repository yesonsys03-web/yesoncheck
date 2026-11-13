"""사용법 매뉴얼을 HTML 한 파일로 만들기 (Qt 없음).

`build(load_image, version_text, current_version)` → 글(`manual_content`)·버전별 바뀐 점(`release_notes`)·그림을 모두 담은 HTML 문자열.
그림은 base64로 파일 안에 넣어 **파일 하나**만 있으면 어디서나 열림(앱 묶음 밖으로 복사해도, 인터넷 없이도).
왼쪽 목차에서 기능을 고르면 그 쪽만 보이고(주소 `#쪽` 또는 `#쪽/닻`), 스크립트가 꺼진 브라우저에서는 모든 쪽이 이어서 보임.

만들 때 확인하는 것(틀리면 ValueError — 조용히 넘기지 않음): 모르는 쪽·닻을 가리키는 링크, 모르는 블록 종류,
같은 쪽 안의 겹치는 닻, 목차 묶음에 없는 쪽, 짝이 안 맞는 `**`·`` ` ``, 빈 키. 그림이 없으면 `load_image`가 낸 예외가 그대로 올라옴.

글 안의 표시는 **원문에서** 왼쪽부터 토큰으로 나눠 조각마다 escape함(escape한 글에 정규식을 걸면 `{<}`가 두 번 escape되고
코드 안의 `**`가 굵게로 바뀜): `` `코드` `` 안은 글자 그대로, `**굵게**` 안은 다시 나눔, `[[쪽/닻|글]]`의 글과 `{키}`는 글자 그대로.
쪽 안의 절 주소는 id와 같은 `#쪽--닻` — 스크립트가 꺼져 있어도 그 자리로 감.

**두 언어**(`manual_languages.LANGUAGES` — 한글·영문): 한 파일에 언어마다의 목차와 쪽들을 함께 넣고 목차 위의 단추로 전환.
고른 언어는 브라우저에 기억하고(localStorage), 처음에는 브라우저 언어가 한국어면 한글·아니면 영문. 주소(`#쪽--닻`)는 언어와
무관 — 전환해도 보던 쪽에 머묾. 첫째 언어(한글)가 기준: 요소 id에 앞말이 없고(둘째부터는 `en:쪽--닻`) 그림을 품음 —
그림은 한 번만 넣고 다른 언어의 `<img data-img=이름>`은 스크립트가 같은 그림을 가리키게 함(파일 크기가 두 배가 되지 않게).
스크립트가 꺼진 브라우저에서는 한글만 보임.
"""
import base64
import html
import json
import re
import struct

from yesoncheck import manual_content
from yesoncheck.manual_languages import KOREAN, LANGUAGES

IMAGE_SCALE = 2  # 스크린샷을 찍은 배율 (tools/make_manual_screenshots.SCALE) — 보일 크기 = 픽셀 / 배율
NARROW_IMAGE = 430  # 이보다 좁은 그림은 설명을 옆에 둠
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CURRENT_BADGE = KOREAN.ui["current"]
CALLOUT_LABELS = KOREAN.ui["callouts"]

_CODE = r"`(?P<code>[^`]+)`"
_LINK = r"\[\[(?P<page>[a-z_]+)(?:/(?P<anchor>[a-z0-9_.]+))?(?:\|(?P<label>[^\]]+))?\]\]"
_BOLD = r"\*\*(?P<bold>.+?)\*\*"
_KEY = r"\{(?P<key>[^{}]+)\}"
TOKEN_RE = re.compile("|".join((_CODE, _LINK, _BOLD, _KEY)))
TOKEN_NO_KEYS_RE = re.compile("|".join((_CODE, _LINK, _BOLD)))  # 업데이트 내역: {}를 키로 보지 않음
KEY_SPLIT_RE = re.compile(r"\+(?=.)")  # "Shift+F" → Shift, F — 끝의 +("Ctrl++")는 더하기 키로 남김
HANGUL_KEY_RE = re.compile(r"^(.+?) \((.)\)$")  # "F (ㄹ)" → 키와 한글 자판의 같은 키


def png_size(data, name):
    """PNG의 (너비, 높이) 픽셀. PNG가 아니면 ValueError."""
    if len(data) < 24 or data[:8] != PNG_MAGIC or data[12:16] != b"IHDR":
        raise ValueError(f"PNG가 아닌 그림입니다: {name}")
    return struct.unpack(">II", data[16:24])


def target(page, anchor=None):
    """쪽(과 그 안의 절)의 주소 = 그 요소의 id — `쪽` 또는 `쪽--닻`."""
    return page if anchor is None else f"{page}--{anchor}"


class _Builder:
    """한 언어의 목차와 쪽들. primary(기준 언어)는 id에 앞말이 없고 그림을 품음."""

    def __init__(self, load_image, version_text, current_version, language=KOREAN, primary=True):
        self.load_image = load_image
        self.version_text = version_text
        self.current_version = current_version
        self.language = language
        self.content = language.content
        self.notes = language.notes
        self.ui = language.ui
        self.primary = primary
        self.prefix = "" if primary else f"{language.code}:"
        self.pages = {page.key: page for page in self.content.PAGES}
        if len(self.pages) != len(self.content.PAGES):
            raise ValueError("쪽 이름(key)이 겹칩니다")
        if manual_content.RELEASES_KEY in self.pages:
            raise ValueError(f"쪽 이름 {manual_content.RELEASES_KEY!r}는 업데이트 내역 쪽의 것입니다")
        self.titles = {key: page.title for key, page in self.pages.items()}
        self.titles[manual_content.RELEASES_KEY] = self.content.RELEASES_TITLE
        self.anchors = {key: self._page_anchors(page) for key, page in self.pages.items()}
        self.anchors[manual_content.RELEASES_KEY] = {f"v{release.version}" for release in self.notes.RELEASES}
        self.images_used = []

    def element_id(self, page, anchor=None):
        """요소의 id — 기준 언어는 주소 그대로(`쪽--닻`), 다른 언어는 앞말을 붙여 겹치지 않게."""
        return self.prefix + target(page, anchor)

    @staticmethod
    def _page_anchors(page):
        anchors = [block[2] for block in page.blocks if block[0] == "h"]
        if len(anchors) != len(set(anchors)):
            raise ValueError(f"쪽 {page.key!r}에 겹치는 닻이 있습니다: {anchors}")
        return set(anchors)

    # ---- 글 안의 표시

    def inline(self, text, keys=True):
        pattern = TOKEN_RE if keys else TOKEN_NO_KEYS_RE
        out, at = [], 0
        for match in pattern.finditer(text):
            out.append(self._plain(text[at:match.start()], text))
            at = match.end()
            if match.group("code") is not None:
                out.append(f"<code>{html.escape(match.group('code'), quote=False)}</code>")
            elif match.group("page") is not None:
                out.append(self._link(match))
            elif match.group("bold") is not None:
                out.append(f"<strong>{self.inline(match.group('bold'), keys)}</strong>")
            else:
                out.append(self.key(match.group("key")))
        out.append(self._plain(text[at:], text))
        return "".join(out)

    @staticmethod
    def _plain(piece, whole):
        """표시가 아닌 글 조각 — 짝이 안 맞아 남은 `**`·`` ` ``는 깨진 글이므로 멈춤."""
        if "**" in piece or "`" in piece:
            raise ValueError(f"짝이 안 맞는 ** 또는 ` 표시: {whole!r}")
        return html.escape(piece, quote=False)

    def _link(self, match):
        page, anchor, label = match.group("page"), match.group("anchor"), match.group("label")
        if page not in self.titles:
            raise ValueError(f"모르는 쪽을 가리키는 링크: {match.group(0)}")
        if anchor is not None and anchor not in self.anchors[page]:
            raise ValueError(f"모르는 닻을 가리키는 링크: {match.group(0)}")
        text = html.escape(self.titles[page] if label is None else label, quote=False)
        return f'<a class="xref" href="#{target(page, anchor)}">{text}</a>'

    @staticmethod
    def key(spec):
        """키 하나("Space")나 함께 누르는 키("Shift+F")를 키 모양으로. "F (ㄹ)"의 괄호는 한글 자판의 같은 키."""
        hangul = ""
        match = HANGUL_KEY_RE.match(spec)
        if match:
            spec, hangul = match.group(1), f'<span class="hangul">{html.escape(match.group(2))}</span>'
        parts = KEY_SPLIT_RE.split(spec)
        if not all(parts) or any(len(part) > 1 and part.endswith("+") for part in parts):  # "+F"·"Ctrl+"
            raise ValueError(f"빈 키가 있는 키 표시: {spec!r}")
        caps = '<span class="plus">+</span>'.join(f"<kbd>{html.escape(part)}</kbd>" for part in parts)
        return f'<span class="keycombo">{caps}{hangul}</span>'

    def text_only(self, text):
        """표시를 벗긴 평문 (그림의 alt 글) — 코드·굵게·키는 그 안의 글, 링크는 보이는 글."""
        out, at = [], 0
        for match in TOKEN_RE.finditer(text):
            out.append(text[at:match.start()])
            at = match.end()
            if match.group("page") is not None:
                out.append(match.group("label") or self.titles.get(match.group("page"), ""))
            elif match.group("bold") is not None:
                out.append(self.text_only(match.group("bold")))
            else:
                out.append(match.group("code") or match.group("key"))
        out.append(text[at:])
        return "".join(out)

    def key_cell(self, spec):
        specs = (spec,) if isinstance(spec, str) else spec
        return '<span class="or">·</span>'.join(self.key(item) for item in specs)

    # ---- 블록

    def figure(self, name, caption, legend):
        data = self.load_image(name)
        width, height = png_size(data, name)
        shown_w, shown_h = round(width / IMAGE_SCALE), round(height / IMAGE_SCALE)
        self.images_used.append(name)
        name_attr = html.escape(name, quote=True)
        if self.primary:
            source = f'src="data:image/png;base64,{base64.b64encode(data).decode("ascii")}" '
            mark = f' data-img="{name_attr}"'
        else:  # 스크립트가 기준 언어의 같은 그림을 가리키게 함
            source = f'data-img="{name_attr}" '
            mark = ""
        classes = ["fig"]
        if legend:
            classes.append("beside" if shown_w <= NARROW_IMAGE else "below")  # 좁은 그림은 설명을 옆에, 넓은 그림은 아래에
        items = "".join(f'<li><span class="n">{number}</span><div>{self.inline(text)}</div></li>'
                        for number, text in enumerate(legend, 1))
        legend_html = f'<ol class="legend">{items}</ol>' if legend else ""
        return (f'<figure class="{" ".join(classes)}"><div class="shot"><img {source}width="{shown_w}" height="{shown_h}" '
                f'alt="{html.escape(self.text_only(caption), quote=True)}" loading="lazy"{mark}><figcaption>{self.inline(caption)}</figcaption></div>'
                f"{legend_html}</figure>")

    def block(self, page, block):
        kind = block[0]
        if kind == "h":
            _kind, title, anchor = block
            return f'<h2 id="{self.element_id(page.key, anchor)}">{self.inline(title)}</h2>'
        if kind == "p":
            return f"<p>{self.inline(block[1])}</p>"
        if kind == "fig":
            _kind, name, caption, legend = block
            return self.figure(name, caption, legend)
        if kind == "keys":
            rows = "".join(f'<tr><th scope="row">{self.key_cell(spec)}</th><td>{self.inline(text)}</td></tr>'
                           for spec, text in block[1])
            return f'<table class="keys"><tbody>{rows}</tbody></table>'
        if kind == "table":
            _kind, head, rows = block
            head_html = ""
            if head is not None:
                head_html = "<thead><tr>" + "".join(f"<th>{self.inline(cell)}</th>" for cell in head) + "</tr></thead>"
            body = "".join(
                "<tr>" + f'<th scope="row">{self.inline(row[0])}</th>' + "".join(f"<td>{self.inline(cell)}</td>" for cell in row[1:])
                + "</tr>" for row in rows)
            return f'<table class="tbl">{head_html}<tbody>{body}</tbody></table>'
        if kind == "steps":
            return '<ol class="steps">' + "".join(f"<li>{self.inline(item)}</li>" for item in block[1]) + "</ol>"
        if kind == "list":
            return "<ul>" + "".join(f"<li>{self.inline(item)}</li>" for item in block[1]) + "</ul>"
        if kind in self.ui["callouts"]:
            return (f'<div class="callout {kind}"><span class="label">{html.escape(self.ui["callouts"][kind])}</span>'
                    f"<div>{self.inline(block[1])}</div></div>")
        raise ValueError(f"모르는 블록 종류: {kind!r} (쪽 {page.key})")

    # ---- 쪽

    def page_section(self, page):
        sections = [(block[2], block[1]) for block in page.blocks if block[0] == "h"]
        chips = ""
        if len(sections) >= 3:
            chips = '<div class="onpage">' + "".join(
                f'<a href="#{target(page.key, anchor)}">{self.inline(title)}</a>' for anchor, title in sections) + "</div>"
        body = "".join(self.block(page, block) for block in page.blocks)
        return (f'<section class="page" id="{self.element_id(page.key)}"><header><div class="crumb">{html.escape(page.group)}</div>'
                f"<h1>{html.escape(page.title)}</h1><p class=\"lead\">{self.inline(page.lead)}</p>{chips}</header>{body}</section>")

    def releases_section(self):
        key = manual_content.RELEASES_KEY
        links = "".join(f'<a href="#{target(key, "v" + release.version)}">{release.version}</a>'
                        for release in self.notes.RELEASES)
        chips = f'<div class="onpage">{links}</div>'
        articles = []
        for release in self.notes.RELEASES:
            badge = (f'<span class="badge">{html.escape(self.ui["current"])}</span>'
                     if release.version == self.current_version else "")
            date = f'<span class="date">{release.date}</span>' if release.date else ""
            groups = []
            for title, items in release.groups:
                heading = f"<h3>{self.inline(title, keys=False)}</h3>" if title else ""
                groups.append(heading + "<ul>" + "".join(f"<li>{self.inline(item, keys=False)}</li>" for item in items) + "</ul>")
            articles.append(
                f'<article class="release"><h2 id="{self.element_id(key, "v" + release.version)}">{release.version}{badge}{date}</h2>'
                f'<p class="summary">{self.inline(release.summary, keys=False)}</p>{"".join(groups)}</article>')
        content = self.content
        return (f'<section class="page" id="{self.element_id(key)}"><header><div class="crumb">{html.escape(content.RELEASES_GROUP)}</div>'
                f"<h1>{html.escape(content.RELEASES_TITLE)}</h1><p class=\"lead\">{html.escape(content.RELEASES_LEAD)}</p>{chips}</header>"
                f'{"".join(articles)}</section>')

    def nav(self):
        content = self.content
        entries = [(page.group, page.key, page.title) for page in content.PAGES]
        entries.append((content.RELEASES_GROUP, manual_content.RELEASES_KEY, content.RELEASES_TITLE))
        unknown = sorted({group for group, _key, _title in entries} - set(content.GROUPS))
        if unknown:
            raise ValueError(f"목차 묶음(GROUPS)에 없는 묶음: {unknown}")
        parts = []
        for group in content.GROUPS:
            links = "".join(f'<a href="#{key}" data-page="{key}">{html.escape(title)}</a>'
                            for entry_group, key, title in entries if entry_group == group)
            if links:
                parts.append(f'<div class="group">{html.escape(group)}</div>{links}')
        return "".join(parts)

    def brand(self):
        """목차 맨 위의 이름과 버전 (이 언어의 글자로)."""
        version = ""
        if self.version_text:
            version = f'<div class="ver">{html.escape(self.ui["version"])} {html.escape(self.version_text)}</div>'
        return f'<div class="name">YesonCheck <span>{html.escape(self.ui["manual"])}</span></div>{version}'

    def sections(self):
        return "".join(self.page_section(page) for page in self.content.PAGES) + self.releases_section()


def _language_css(codes):
    """언어를 가리는 CSS: 고른 언어(html의 data-lang)의 것만 보이고, 스크립트가 꺼져 있으면(data-lang 없음) 첫째 언어."""
    # 가리는 요소는 div·nav뿐이라 block (display:revert는 모르는 브라우저가 있어 그 줄을 버리면 전부 숨은 채 남음)
    rules = [f':root:not([data-lang]) .l[lang="{codes[0]}"] {{ display:block; }}']
    rules += [f':root[data-lang="{code}"] .l[lang="{code}"] {{ display:block; }}' for code in codes]
    return "\n".join(rules) + "\n"


def _in_language(tag, builder, inner, classes=""):
    """한 언어에서만 보이는 요소 (CSS가 `.l[lang]`으로 가려 줌)."""
    names = f"l {classes}".strip()
    return f'<{tag} class="{names}" lang="{builder.language.code}">{inner}</{tag}>'


def build(load_image, version_text=None, current_version=None, languages=None):
    """매뉴얼 HTML — 두 언어(한글·영문)가 함께 들어 있고 목차 위의 단추로 전환. `load_image(이름)` → 그 그림(PNG)의 바이트.
    `version_text`는 목차 위에 보일 지금 앱의 버전 글(없으면 표시하지 않음), `current_version`("1.9.0")이 '업데이트 내역'에
    있으면 그 버전에 '지금 버전' 표시. `languages`는 넣을 언어들(기본 `LANGUAGES` 전부 — 첫째가 기준; 하나면 전환 단추 없음)."""
    builders = [_Builder(load_image, version_text, current_version, language, primary=index == 0)
                for index, language in enumerate(LANGUAGES if languages is None else languages)]
    first = builders[0].language
    brands = "".join(_in_language("div", builder, builder.brand()) for builder in builders)
    switch = ""
    if len(builders) > 1:
        switch = '<div class="langs">' + "".join(
            f'<button type="button" data-lang="{builder.language.code}">{html.escape(builder.language.name)}</button>'
            for builder in builders) + "</div>"
    navs = "".join(_in_language("nav", builder, builder.nav()) for builder in builders)
    docs = "".join(_in_language("div", builder, builder.sections(), "doc") for builder in builders)
    codes = [builder.language.code for builder in builders]
    script = (SCRIPT.replace("__CODES__", json.dumps(codes))
              .replace("__UI__", json.dumps({builder.language.code: {key: builder.ui[key] for key in SCRIPT_UI_KEYS}
                                             for builder in builders}, ensure_ascii=False)))
    search, theme = html.escape(first.ui["search"], quote=True), html.escape(first.ui["theme"], quote=True)
    return (
        f'<!DOCTYPE html>\n<html lang="{first.code}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>YesonCheck {html.escape(first.ui['manual'])}</title><style>{CSS}{_language_css(codes)}</style></head><body>"
        f'<aside class="side"><div class="brand">{brands}</div>{switch}'
        f'<div class="tools"><input id="q" type="search" placeholder="{search}" aria-label="{search}" autocomplete="off">'
        f'<button id="theme" type="button" title="{theme}" aria-label="{theme}">◐</button></div>'
        f'<div id="hits" class="hits"></div>{navs}</aside>'
        f'<main>{docs}<div class="pager"><a id="prev"></a><a id="next"></a></div></main>'
        '<div id="zoom" class="zoom" hidden><img alt=""></div>'
        f"<script>{script}</script></body></html>\n")


def image_names():
    """매뉴얼이 쓰는 그림 이름들 (글에 나오는 차례, 겹치면 한 번)."""
    names = []
    for page in manual_content.PAGES:
        for block in page.blocks:
            if block[0] == "fig" and block[1] not in names:
                names.append(block[1])
    return names


_DARK = """
  --bg:#17181b; --panel:#1d1f23; --text:#e7e8ea; --muted:#9aa1ab; --line:#2c2f35; --soft:#22252a;
  --accent:#ff9f1a; --link:#79b8ff; --code-bg:#2a2d33; --code:#ffd08a; --kbd-bg:#2e3239; --kbd-line:#4a505a; --kbd:#f3f4f6;
  --note:#1f2a37; --note-bar:#4c9aff; --tip:#1d2b22; --tip-bar:#3fb970; --warn:#33231d; --warn-bar:#ff7a45; --shadow:rgba(0,0,0,.5);
"""

CSS = """
:root {
  --bg:#ffffff; --panel:#f6f7f9; --text:#1c2430; --muted:#5d6877; --line:#e1e5ea; --soft:#f3f5f7;
  --accent:#d9730d; --link:#0b63ce; --code-bg:#eef1f4; --code:#9a3412; --kbd-bg:#ffffff; --kbd-line:#c5ccd5; --kbd:#1c2430;
  --note:#eef5ff; --note-bar:#2f7de1; --tip:#edf8f0; --tip-bar:#2f9e5b; --warn:#fff3ea; --warn-bar:#e8590c; --shadow:rgba(20,30,50,.18);
  --callout:#ff2d6f;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {""" + _DARK + """} }
:root[data-theme="dark"] {""" + _DARK + """}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); line-height:1.72; font-size:15px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
  -webkit-font-smoothing:antialiased; word-break:keep-all; overflow-wrap:anywhere; }
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }

.side { position:fixed; inset:0 auto 0 0; width:268px; background:var(--panel); border-right:1px solid var(--line);
  display:flex; flex-direction:column; }
.brand { padding:22px 22px 12px; }
.brand .name { font-size:18px; font-weight:750; letter-spacing:-.01em; }
.brand .name span { color:var(--accent); }
.brand .ver { margin-top:2px; color:var(--muted); font-size:12.5px; }
.l[lang] { display:none; }
.langs { display:none; gap:0; margin:0 18px 10px; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.js .langs { display:flex; }
.langs button { flex:1; padding:5px 0; border:0; background:var(--bg); color:var(--muted); font:inherit; font-size:12.5px; cursor:pointer; }
.langs button + button { border-left:1px solid var(--line); }
.langs button:hover { color:var(--accent); }
.langs button.active { background:var(--accent); color:#fff; font-weight:650; }
.tools { display:flex; gap:8px; padding:0 18px 8px; }
#q { flex:1; min-width:0; padding:7px 11px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text);
  font:inherit; font-size:13.5px; outline:none; }
#q:focus { border-color:var(--accent); }
#theme { width:34px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--muted); cursor:pointer; font-size:15px; }
#theme:hover { color:var(--accent); border-color:var(--accent); }
.hits { padding:0 22px; color:var(--muted); font-size:12px; min-height:16px; }
nav { overflow-y:auto; padding:4px 12px 28px; flex:1; }
nav .group { margin:16px 10px 5px; color:var(--muted); font-size:11.5px; font-weight:700; letter-spacing:.06em; }
nav a { display:block; padding:6px 10px; border-radius:7px; color:var(--text); font-size:14px; }
nav a:hover { background:var(--soft); text-decoration:none; }
nav a.active { background:var(--accent); color:#fff; font-weight:650; }
nav a.dim { display:none; }

main { margin-left:268px; padding:44px 56px 72px; }
.page, .pager { max-width:900px; margin:0 auto; }
.page { scroll-margin-top:120px; }
.js .page { display:none; }
.js .page.active { display:block; }
.page + .page { margin-top:72px; padding-top:40px; border-top:1px solid var(--line); }
.js .page + .page { margin-top:0; padding-top:0; border-top:0; }
.crumb { color:var(--accent); font-size:12.5px; font-weight:700; letter-spacing:.05em; }
h1 { margin:4px 0 10px; font-size:30px; line-height:1.3; letter-spacing:-.02em; }
.lead { margin:0 0 18px; color:var(--muted); font-size:16.5px; }
.onpage { display:flex; flex-wrap:wrap; gap:7px; margin:0 0 6px; }
.onpage a { padding:3px 11px; border:1px solid var(--line); border-radius:999px; color:var(--muted); font-size:12.5px; }
.onpage a:hover { border-color:var(--accent); color:var(--accent); text-decoration:none; }
header { padding-bottom:18px; margin-bottom:8px; border-bottom:1px solid var(--line); }
h2 { margin:40px 0 12px; font-size:20px; letter-spacing:-.01em; scroll-margin-top:18px; }
h2::before { content:""; display:inline-block; width:4px; height:17px; margin-right:10px; border-radius:2px; background:var(--accent);
  vertical-align:-2px; }
h3 { margin:20px 0 6px; font-size:15px; color:var(--muted); }
p { margin:10px 0; }
ul, ol { margin:10px 0; padding-left:22px; }
li { margin:5px 0; }
strong { font-weight:680; }
code { padding:1px 6px; border-radius:5px; background:var(--code-bg); color:var(--code);
  font-family:"SF Mono",Menlo,Consolas,"D2Coding",monospace; font-size:.88em; }
kbd { display:inline-block; min-width:24px; padding:1px 7px; border:1px solid var(--kbd-line); border-bottom-width:2px; border-radius:6px;
  background:var(--kbd-bg); color:var(--kbd); font-family:inherit; font-size:12.5px; font-weight:600; line-height:1.55; text-align:center;
  white-space:nowrap; }
.keycombo { white-space:nowrap; }
.plus { margin:0 3px; color:var(--muted); font-size:12px; }
.or { margin:0 6px; color:var(--muted); }
.hangul { margin-left:6px; color:var(--muted); font-size:12.5px; }
.hangul::before { content:"("; } .hangul::after { content:")"; }

table { width:100%; border-collapse:collapse; margin:12px 0 16px; font-size:14.5px; }
th, td { padding:9px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
thead th { color:var(--muted); font-size:12.5px; font-weight:700; border-bottom:2px solid var(--line); }
tbody th { font-weight:650; }
.keys tbody th { width:230px; white-space:nowrap; padding-right:22px; font-weight:400; }
.tbl tbody th { width:30%; }
tbody tr:hover { background:var(--soft); }

.steps { list-style:none; padding:0; counter-reset:step; }
.steps li { position:relative; margin:9px 0; padding-left:38px; counter-increment:step; }
.steps li::before { content:counter(step); position:absolute; left:0; top:1px; width:25px; height:25px; border-radius:50%;
  background:var(--accent); color:#fff; font-size:13px; font-weight:700; line-height:25px; text-align:center; }

.callout { display:flex; gap:12px; margin:16px 0; padding:12px 16px; border-left:4px solid var(--note-bar); border-radius:0 8px 8px 0;
  background:var(--note); }
.callout .label { flex:none; font-size:12.5px; font-weight:750; color:var(--note-bar); padding-top:2px; }
.callout.tip { background:var(--tip); border-color:var(--tip-bar); } .callout.tip .label { color:var(--tip-bar); }
.callout.warn { background:var(--warn); border-color:var(--warn-bar); } .callout.warn .label { color:var(--warn-bar); }

.fig { margin:20px 0 24px; }
.shot { display:inline-block; max-width:100%; }
.shot img { display:block; max-width:100%; height:auto; border:1px solid var(--line); border-radius:10px; background:#232323;
  box-shadow:0 6px 22px var(--shadow); cursor:zoom-in; }
figcaption { margin-top:8px; color:var(--muted); font-size:13px; text-align:center; }
.legend { list-style:none; margin:14px 0 0; padding:0; }
.legend li { display:flex; gap:11px; margin:7px 0; }
.legend .n { flex:none; width:23px; height:23px; margin-top:2px; border-radius:50%; background:var(--callout); color:#fff; font-size:12.5px;
  font-weight:700; line-height:23px; text-align:center; }
.fig.beside { display:flex; gap:28px; align-items:flex-start; }
.fig.beside .shot { flex:none; max-width:46%; }
.fig.beside .legend { margin-top:4px; flex:1; }
.fig.below .legend { columns:2; column-gap:34px; }
.fig.below .legend li { break-inside:avoid; }

.release { padding-bottom:6px; }
.release h2 { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.release h2::before { margin-right:0; }
.badge { padding:2px 9px; border-radius:999px; background:var(--accent); color:#fff; font-size:11.5px; font-weight:700; }
.date { color:var(--muted); font-size:13px; font-weight:400; }
.summary { color:var(--text); font-size:15.5px; }

.pager { display:flex; justify-content:space-between; gap:16px; margin-top:52px; padding-top:20px; border-top:1px solid var(--line); }
.pager a { color:var(--muted); font-size:14px; } .pager a:hover { color:var(--accent); text-decoration:none; }
.pager a:empty { visibility:hidden; }
html:not(.js) .pager { display:none; }

.zoom { position:fixed; inset:0; z-index:9; display:flex; align-items:center; justify-content:center; padding:24px;
  background:rgba(0,0,0,.82); cursor:zoom-out; }
.zoom[hidden] { display:none; }
.zoom img { max-width:100%; max-height:100%; border-radius:8px; box-shadow:0 10px 40px rgba(0,0,0,.6); }

@media (max-width: 900px) {
  .side { position:static; width:auto; border-right:0; border-bottom:1px solid var(--line); }
  nav { max-height:240px; }
  main { margin-left:0; padding:28px 20px 56px; }
  .fig.beside { display:block; } .fig.beside .shot { max-width:100%; } .fig.below .legend { columns:1; }
}
@media print {
  .side, .pager, .zoom { display:none !important; }
  main { margin:0; padding:0; }
  .js .page { display:block; page-break-after:always; }
  .shot img { box-shadow:none; }
}
"""

SCRIPT_UI_KEYS = ("manual", "search", "theme", "found", "none")  # 스크립트가 쓰는 화면 글자 (manual_languages의 ui)

SCRIPT = r"""
(function () {
  var root = document.documentElement;
  root.classList.add('js');
  var CODES = __CODES__;  // 언어 — 첫째가 기준 (요소 id에 앞말이 없음)
  var UI = __UI__;
  var slice = function (list) { return Array.prototype.slice.call(list); };
  var prev = document.getElementById('prev'), next = document.getElementById('next');
  var q = document.getElementById('q'), hits = document.getElementById('hits'), theme = document.getElementById('theme');
  var langButtons = slice(document.querySelectorAll('.langs button'));
  var lang, pages, links, order, texts;

  function prefix() { return lang === CODES[0] ? '' : lang + ':'; }
  function keyOf(page) { return page.id.slice(prefix().length); }
  function titleOf(key) {
    for (var i = 0; i < links.length; i++) if (links[i].getAttribute('data-page') === key) return links[i].textContent;
    return '';
  }
  function show(key, anchor) {
    if (order.indexOf(key) < 0) { key = order[0]; anchor = null; }
    pages.forEach(function (p) { p.classList.toggle('active', keyOf(p) === key); });
    links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-page') === key); });
    var at = order.indexOf(key);
    prev.textContent = at > 0 ? '← ' + titleOf(order[at - 1]) : '';
    prev.setAttribute('href', at > 0 ? '#' + order[at - 1] : '#');
    next.textContent = at < order.length - 1 ? titleOf(order[at + 1]) + ' →' : '';
    next.setAttribute('href', at < order.length - 1 ? '#' + order[at + 1] : '#');
    document.title = titleOf(key) + ' — YesonCheck ' + UI[lang].manual;
    var section = anchor ? document.getElementById(prefix() + key + '--' + anchor) : null;
    if (section) section.scrollIntoView(); else window.scrollTo(0, 0);
  }
  function route() {
    var hash = location.hash.replace(/^#/, '');
    try { hash = decodeURIComponent(hash); } catch (e) { hash = ''; }  // 깨진 주소는 모르는 쪽처럼 첫 쪽으로
    var cut = hash.indexOf('--');
    show(cut < 0 ? hash : hash.slice(0, cut), cut < 0 ? null : hash.slice(cut + 2));
  }
  window.addEventListener('hashchange', route);
  // 지금 주소와 같은 링크를 다시 누르면 hashchange가 오지 않으므로 직접 그 자리로
  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (a && a.getAttribute('href') === location.hash) route();
  });

  // 찾기: 글에 낱말이 모두 들어 있는 쪽만 목차에 남김, Enter는 첫 쪽으로 (지금 언어의 글에서)
  function matches() {
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    return order.filter(function (key) { return words.every(function (w) { return texts[key].indexOf(w) >= 0; }); });
  }
  function search() {
    var found = matches(), active = q.value.trim() !== '';
    links.forEach(function (a) { a.classList.toggle('dim', active && found.indexOf(a.getAttribute('data-page')) < 0); });
    hits.textContent = active ? (found.length ? UI[lang].found.replace('{n}', found.length) : UI[lang].none) : '';
  }
  q.addEventListener('input', search);
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { var found = matches(); if (found.length) location.hash = '#' + found[0]; }
    if (e.key === 'Escape') { q.value = ''; search(); }
  });

  // 언어: 고른 언어의 목차·쪽만 보임 (주소는 언어와 무관 — 전환해도 보던 쪽에 머묾). 처음에는 브라우저 언어를 따름
  var LANG_KEY = 'yesoncheck-manual-lang';
  function setLang(value) {
    lang = CODES.indexOf(value) < 0 ? CODES[0] : value;
    root.setAttribute('data-lang', lang);
    root.setAttribute('lang', lang);
    pages = slice(document.querySelectorAll('.doc[lang="' + lang + '"] .page'));
    links = slice(document.querySelectorAll('nav[lang="' + lang + '"] a[data-page]'));
    order = links.map(function (a) { return a.getAttribute('data-page'); });
    texts = {};
    pages.forEach(function (p) { texts[keyOf(p)] = p.textContent.toLowerCase(); });
    q.setAttribute('placeholder', UI[lang].search);
    q.setAttribute('aria-label', UI[lang].search);
    theme.setAttribute('title', UI[lang].theme);
    theme.setAttribute('aria-label', UI[lang].theme);
    langButtons.forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-lang') === lang); });
    q.value = '';  // 찾던 낱말은 앞 언어의 것 — 지움
    search();
    route();
  }
  langButtons.forEach(function (b) {
    b.addEventListener('click', function () {
      setLang(b.getAttribute('data-lang'));
      try { localStorage.setItem(LANG_KEY, lang); } catch (e) {}
    });
  });
  var chosen = null;
  try { chosen = localStorage.getItem(LANG_KEY); } catch (e) {}
  if (!chosen) {
    var browser = (navigator.language || '').toLowerCase().split('-')[0];
    chosen = CODES.indexOf(browser) >= 0 ? browser : CODES[CODES.length - 1];
  }
  setLang(chosen);

  // 그림은 기준 언어 쪽에만 들어 있음 — 다른 언어의 같은 그림이 그것을 가리키게
  var sources = {};
  slice(document.querySelectorAll('img[data-img][src]')).forEach(function (img) { sources[img.getAttribute('data-img')] = img.getAttribute('src'); });
  slice(document.querySelectorAll('img[data-img]:not([src])')).forEach(function (img) {
    var source = sources[img.getAttribute('data-img')];
    if (source) img.setAttribute('src', source);
  });

  // 밝게 / 어둡게 (기본은 시스템 설정을 따름)
  var KEY = 'yesoncheck-manual-theme';
  try { var saved = localStorage.getItem(KEY); if (saved) root.setAttribute('data-theme', saved); } catch (e) {}
  theme.addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    var value = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', value);
    try { localStorage.setItem(KEY, value); } catch (e) {}
  });

  // 그림을 누르면 크게
  var zoom = document.getElementById('zoom'), big = zoom.querySelector('img');
  document.addEventListener('click', function (e) {
    if (e.target.matches && e.target.matches('.shot img')) { big.src = e.target.src; zoom.hidden = false; }
    else if (!zoom.hidden) zoom.hidden = true;
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') zoom.hidden = true; });
})();
"""
