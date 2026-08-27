"""Render an HTML page as markdown-equivalent prose.

Prose Structure scores four signals — heading hierarchy, code blocks, section
size, and staleness markers. All four are detected with markdown syntax, so
rather than teach the check a second dialect we normalize HTML into the same
shape and let the existing, tested scoring run over it unchanged.

The conversion is deliberately lossy. It keeps exactly what the check reads —
`<h1>`-`<h6>` become ATX headings, `<pre>` blocks become fences carrying the
language from the usual highlighter class conventions, block elements become
line breaks — and drops everything else. It is not a general-purpose HTML to
markdown converter and should not grow into one.

Scoring the converted text rather than the raw HTML also avoids a class of
false positives: `class="legacy-sidebar"` or a `deprecated` CSS rule would
otherwise trip the staleness markers, which are meant to read prose.

Stdlib only. artie's whole value proposition is starting fast under `uvx`,
and a markup dependency is not worth four regexes.
"""

from __future__ import annotations

from html.parser import HTMLParser

# Content inside these is markup machinery, not documentation. Anything else
# is kept -- being conservative here beats guessing that a <nav> or <footer>
# holds nothing a reader would score.
_SKIP_CONTENT = {"script", "style", "noscript", "svg", "template", "head"}

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Elements that end a line of prose. Without these the whole page collapses
# into one run-on section and the chunk-size signal reads as a single wall.
_BLOCK = {
    "p", "div", "section", "article", "header", "footer", "nav", "main",
    "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "th", "td",
    "blockquote", "figure", "figcaption", "form", "fieldset", "hr", "br",
    "aside", "address", "details", "summary",
}

# Class-name conventions highlighters use to record a fence's language:
# `language-python` (CommonMark, Prism, highlight.js), `lang-python`
# (older Rouge/Redcarpet output), `highlight-python` (GitHub/Jekyll).
_LANG_CLASS_PREFIXES = ("language-", "lang-", "highlight-")


def _language_from_attrs(attrs: list[tuple[str, str | None]]) -> str:
    """Pull a fence language out of a <pre>/<code> tag's attributes."""
    mapping = {key.lower(): (value or "") for key, value in attrs}
    for key in ("data-language", "data-lang"):
        if mapping.get(key):
            return mapping[key].strip()
    for token in mapping.get("class", "").split():
        for prefix in _LANG_CLASS_PREFIXES:
            if token.startswith(prefix) and len(token) > len(prefix):
                return token[len(prefix):].strip()
    return ""


class _ProseExtractor(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs is on by default, so &amp; and friends arrive
        # already decoded through handle_data.
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._heading_level = 0
        self._heading_text: list[str] = []
        self._in_pre = False
        self._pre_text: list[str] = []
        self._pre_lang = ""

    # -- helpers ---------------------------------------------------------
    def _emit(self, text: str) -> None:
        self.parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag in _SKIP_CONTENT:
            self._skip_tag = tag
            self._skip_depth = 1
            return

        if self._in_pre:
            # A <code> inside <pre> may carry the language; nested markup
            # (highlighter <span>s) contributes only its text.
            if tag == "code" and not self._pre_lang:
                self._pre_lang = _language_from_attrs(attrs)
            return

        if tag in _HEADINGS:
            self._heading_level = int(tag[1])
            self._heading_text = []
            return

        if tag == "pre":
            self._in_pre = True
            self._pre_text = []
            self._pre_lang = _language_from_attrs(attrs)
            return

        if tag in _BLOCK:
            self._emit("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("br", "hr") and not self._skip_depth and not self._in_pre:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return

        if tag == "pre" and self._in_pre:
            body = "".join(self._pre_text).strip("\n")
            self._emit(f"\n\n```{self._pre_lang}\n{body}\n```\n\n")
            self._in_pre = False
            self._pre_text = []
            self._pre_lang = ""
            return

        if tag in _HEADINGS and self._heading_level:
            text = " ".join("".join(self._heading_text).split())
            if text:
                self._emit(f"\n\n{'#' * self._heading_level} {text}\n\n")
            self._heading_level = 0
            self._heading_text = []
            return

        if tag in _BLOCK:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_pre:
            self._pre_text.append(data)
        elif self._heading_level:
            self._heading_text.append(data)
        else:
            self._emit(data)


def html_to_prose(html: str) -> str:
    """Convert an HTML page into the markdown subset Prose Structure reads."""
    parser = _ProseExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # HTMLParser is lenient, but a pathological page should degrade to a
        # partial render rather than take the whole run down.
        pass
    text = "".join(parser.parts)

    # Collapse the runs of whitespace the block-element rule produces, while
    # leaving code fences alone -- indentation inside a fence is meaningful.
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line.strip())
            continue
        out.append(line if in_fence else " ".join(line.split()))
    collapsed = "\n".join(out)

    while "\n\n\n" in collapsed:
        collapsed = collapsed.replace("\n\n\n", "\n\n")
    return collapsed.strip()
