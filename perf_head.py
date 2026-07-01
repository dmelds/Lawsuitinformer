#!/usr/bin/env python3
"""
perf_head.py — sitewide render-blocking CSS fix for lawsuitinformer.com

What it does, per HTML page:
  1. Extracts "critical" (above-the-fold) rules from style.css and inlines
     them in a <style> block in <head>, wrapped in marker comments.
  2. Replaces the render-blocking <link rel="stylesheet" href="style.css">
     with an async preload-swap loader (+ <noscript> fallback).
  3. Standardizes font preloads (Fraunces 600 + Source Serif 400).
Plus:
  4. index.html: removes the head-blocking search-data.js and appends a
     lazy loader (fetches on search focus, or when the browser goes idle).
  5. browse-lawsuits.html: adds `defer` to its synchronous search-data.js.
  6. _headers: appends long-cache rules for fonts/icons (marker-guarded).

Idempotent: re-running replaces the critical block with a fresh extraction
from the current style.css, so this doubles as a maintenance task after
stylesheet edits. Run with --dry-run to preview.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DRY = "--dry-run" in sys.argv

MARK_START = "<!-- perf:critical-css:start -->"
MARK_END = "<!-- perf:critical-css:end -->"
MARK_LAZY = "<!-- perf:search-lazy -->"
MARK_HEADERS = "# perf:cache-policy"

# ---------------------------------------------------------------- CSS parse

def parse_blocks(css: str):
    """Yield (prelude, body) for each top-level rule. Handles nesting."""
    i, n = 0, len(css)
    while i < n:
        # skip whitespace
        while i < n and css[i].isspace():
            i += 1
        # skip comments
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if i >= n:
            break
        brace = css.find("{", i)
        if brace == -1:
            break
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            c = css[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif css.startswith("/*", j):
                end = css.find("*/", j + 2)
                j = n - 1 if end == -1 else end + 1
            j += 1
        yield prelude, css[brace + 1 : j - 1]
        i = j


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def minify(css: str) -> str:
    css = strip_comments(css)
    css = re.sub(r"\s+", " ", css)
    for a, b in (("; ", ";"), (" ;", ";"), ("{ ", "{"), (" {", "{"),
                 ("} ", "}"), (" }", "}"), (": ", ":"), (", ", ","),
                 (";}", "}")):
        css = css.replace(a, b)
    return css.strip()


# Exact-match base selectors (normalized whitespace).
BASE = {
    "*, *::before, *::after", "*", "html, body", "html", "body", "img",
    "a", "a:hover", "ul, ol", "button, input, textarea, select",
    "::selection", ":focus-visible", ".content-page",
}

# Substring tokens: a rule is critical if its selector contains any of these.
TOKENS = [
    ".sr-only", ".skip-link", ".container", ".narrow",
    ".site-header", ".header-inner", ".logo", ".site-logo", ".brand",
    ".site-nav", "#site-nav", "#site-menu", ".main-nav", "header nav",
    ".nav-toggle", ".menu-toggle",
    ".btn", ".cta-buttons", ".next-buttons", ".hero-buttons",
    ".eyebrow",
    ".hero", ".page-hero", ".browse-hero", ".review-hero", ".page-intro",
    ".search-helper", ".search-examples", ".popular-topics-bar",
    ".start-here-bridge",
    ".start-here",
    ".content-page,", ".content-page h", ".content-page p",
    ".content-page li", ".content-page ul", ".content-page ol",
    ".content-page >",
    ".breadcrumb", ".article-reviewer", ".article-date", ".article-intro",
    ".article-disclaimer", ".on-this-page", ".toc-list", ".author-hero",
]


def selector_is_critical(sel: str) -> bool:
    s = re.sub(r"\s+", " ", sel).strip()
    if s in BASE:
        return True
    return any(t in s for t in TOKENS)


def extract_critical(css_text: str) -> str:
    out = []
    for prelude, body in parse_blocks(strip_comments(css_text)):
        if prelude.startswith("@font-face"):
            out.append(f"{prelude}{{{body}}}")
        elif prelude.startswith("@media"):
            inner = [
                f"{p}{{{b}}}"
                for p, b in parse_blocks(body)
                if selector_is_critical(p)
            ]
            if inner:
                out.append(f"{prelude}{{{''.join(inner)}}}")
        elif prelude.startswith("@"):
            continue  # other at-rules: skip
        elif prelude == ":root" or selector_is_critical(prelude):
            out.append(f"{prelude}{{{body}}}")
    return minify("".join(out))


# ---------------------------------------------------------------- head block

def build_head_block(critical: str) -> str:
    return f"""{MARK_START}
<style id="critical-css">{critical}</style>
<link rel="preload" href="/fonts/fraunces-v38-latin-600.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/source-serif-4-v14-latin-regular.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/style.css" as="style" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link rel="stylesheet" href="/style.css"></noscript>
{MARK_END}"""


RX_STYLESHEET = re.compile(
    r'[ \t]*<link\s+rel="stylesheet"\s+href="/?style\.css"\s*/?>\s*\n?'
)
RX_FRAUNCES_PRELOAD = re.compile(
    r'[ \t]*<link\s+rel="preload"\s+href="/fonts/fraunces-v38-latin-600\.woff2"[^>]*>\s*\n?'
)
RX_VIEWPORT_LINE = re.compile(r'^.*name="viewport".*$', re.M)

LAZY_SNIPPET = f"""{MARK_LAZY}
<script>
(function () {{
  var done = false;
  function load() {{
    if (done || window.SEARCH_INDEX) return;
    done = true;
    var s = document.createElement("script");
    s.src = "search-data.js";
    document.head.appendChild(s);
  }}
  var input = document.getElementById("homepage-search");
  if (input) {{
    input.addEventListener("focus", load, {{ once: true }});
    input.addEventListener("touchstart", load, {{ once: true, passive: true }});
  }}
  (window.requestIdleCallback || function (f) {{ setTimeout(f, 3000); }})(load);
}})();
</script>"""


def transform_page(path: Path, head_block: str) -> str:
    html = path.read_text(encoding="utf-8")
    status = []

    if MARK_START in html and MARK_END in html:
        # Refresh existing block in place.
        html = re.sub(
            re.escape(MARK_START) + r".*?" + re.escape(MARK_END),
            head_block, html, count=1, flags=re.S,
        )
        status.append("refreshed critical block")
    else:
        n_css = len(RX_STYLESHEET.findall(html))
        html = RX_STYLESHEET.sub("", html)
        html = RX_FRAUNCES_PRELOAD.sub("", html)
        if n_css == 0:
            status.append("WARN: no stylesheet link found")
        m = RX_VIEWPORT_LINE.search(html)
        if m:
            html = html[: m.end()] + "\n" + head_block + html[m.end():]
        else:
            html = html.replace("<head>", "<head>\n" + head_block, 1)
            status.append("no viewport meta; inserted after <head>")
        status.append("inlined critical css + async loader")

    # Page-specific: homepage search index
    if path.name == "index.html":
        before = html
        html = re.sub(
            r'[ \t]*<!--[^>]*?SEARCH_INDEX[^>]*?-->\s*\n?', "", html, flags=re.S
        )
        html = re.sub(
            r'[ \t]*<script\s+src="search-data\.js"\s+defer\s*>\s*</script>\s*\n?',
            "", html,
        )
        if html != before:
            status.append("removed head search-data.js")
        if MARK_LAZY not in html:
            html = html.replace("</body>", LAZY_SNIPPET + "\n</body>", 1)
            status.append("appended lazy search loader")

    # Page-specific: browse-lawsuits sync script -> defer
    if path.name == "browse-lawsuits.html":
        new = html.replace(
            '<script src="search-data.js"></script>',
            '<script src="search-data.js" defer></script>',
        )
        if new != html:
            html = new
            status.append("deferred search-data.js")

    if not DRY:
        path.write_text(html, encoding="utf-8")
    print(f"{path.name}: {'; '.join(status)}")
    return html


def update_headers_file():
    hp = ROOT / "_headers"
    text = hp.read_text(encoding="utf-8") if hp.exists() else ""
    if MARK_HEADERS in text:
        print("_headers: cache policy already present")
        return
    block = f"""

{MARK_HEADERS}
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
/*.png
  Cache-Control: public, max-age=604800
/*.ico
  Cache-Control: public, max-age=604800
/*.webmanifest
  Cache-Control: public, max-age=604800
"""
    if not DRY:
        hp.write_text(text.rstrip("\n") + block, encoding="utf-8")
    print("_headers: appended cache policy")


def main():
    css_path = ROOT / "style.css"
    critical = extract_critical(css_path.read_text(encoding="utf-8"))
    kb = len(critical) / 1024
    print(f"critical css: {kb:.1f} KB minified ({len(critical)} chars)")
    if kb > 16:
        print("WARN: critical block is large; consider trimming TOKENS")

    head_block = build_head_block(critical)
    pages = sorted(ROOT.glob("*.html"))
    print(f"transforming {len(pages)} pages{' (dry run)' if DRY else ''}\n")
    for p in pages:
        transform_page(p, head_block)
    update_headers_file()
    print("\ndone.")


if __name__ == "__main__":
    main()
