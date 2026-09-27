#!/usr/bin/env python3
"""
Generate feed.xml: an RSS 2.0 feed of the site's most recently updated pages.

One script serves every site in the network. The constants under
SITE CONSTANTS are the only lines that differ between copies.

Which pages qualify: a page is in the feed when its JSON-LD carries a
dateModified or datePublished and does not declare itself a listing
(CollectionPage and the like). That is the same date the sitemap claims and
the byline shows, so the feed never disagrees with either. Utility pages
(index, about, thank-you) carry no date in their schema and stay out on their
own; topic hubs and the news listing declare CollectionPage and stay out for
that; EXCLUDE is a backstop for the rest, and a robots noindex also keeps a
page out. Title comes from <title> with the site suffix stripped; og:title is
the fallback.

Item date: dateModified first, then datePublished. An update page that is
revised today therefore moves back to the top of the feed, and its <guid>
changes with the date so a feed reader shows the revision as a new entry.
Mass Tort Wire keys stories on <link>, so it shows each page once.

The feed carries no <lastBuildDate> clock: <lastBuildDate> is the newest item
date, so the file changes only when a page does and the workflow commits only
then.

No third-party dependencies. Runs on the stock Python 3 on the GitHub Actions
ubuntu-latest runner, and locally:

    python3 generate_feed.py            # writes feed.xml
    python3 generate_feed.py --dry-run  # prints what it would write
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from email.utils import format_datetime
from pathlib import Path

# ── SITE CONSTANTS ── the only lines that differ per site.
BASE_URL = "https://lawsuitinformer.com"      # no trailing slash
SITE_NAME = "Lawsuit Informer"
SITE_DESCRIPTION = "Plain-language updates on mass tort and product liability lawsuits."
# How many directories above this script the pages live: 0 when the script
# sits in the repo root beside the pages, 1 when it lives in scripts/.
ROOT_UP = 0

FEED_FILE = "feed.xml"
MAX_ITEMS = 40
EXCLUDE = {"404.html", "thank-you.html", "sms-terms.html", "index.html"}
# Site-name suffixes stripped from <title>: "Headline | Lawsuit Informer" -> "Headline".
SITE_SUFFIXES = ("Lawsuit Informer", "Informer")

# Written into every item. The wire reads <link>, readers read <guid>.
DATE_KEYS = ("dateModified", "datePublished")

ROOT = Path(__file__).resolve().parents[ROOT_UP]
PAGES = ROOT

LD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S,
)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
ATTR = re.compile(r"""([a-zA-Z:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
ROBOTS_TAG = re.compile(r"<meta\b[^>]*>", re.I)
ROBOTS_NAME = re.compile(r"name\s*=\s*[\"']robots[\"']", re.I)
NOINDEX = re.compile(r"\bnoindex\b", re.I)
ENTITY = re.compile(r"&(#\d+|#x[0-9a-f]+|amp|lt|gt|quot|apos|nbsp|ndash|mdash|rsquo|lsquo|rdquo|ldquo|hellip);", re.I)
NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ", "ndash": "–",
         "mdash": "—", "rsquo": "’", "lsquo": "‘", "rdquo": "”", "ldquo": "“",
         "hellip": "…"}


def unescape(text: str) -> str:
    """Decode the entities a <title> or meta content is likely to carry."""
    def sub(m: re.Match) -> str:
        code = m.group(1)
        if code.startswith("#x") or code.startswith("#X"):
            return chr(int(code[2:], 16))
        if code.startswith("#"):
            return chr(int(code[1:]))
        return NAMED.get(code.lower(), m.group(0))
    return ENTITY.sub(sub, text)


def xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


def _iter_nodes(obj):
    """Walk every dict in a JSON-LD document, including @graph and arrays."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_nodes(item)


def _as_date(value) -> _dt.date | None:
    """'2026-08-15' or '2026-08-15T06:00:00-07:00' -> the calendar date as written."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


LISTING_TYPES = {"CollectionPage", "ProfilePage", "AboutPage", "ContactPage", "SearchResultsPage"}


def _types(node) -> set:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()


def schema_date(html: str) -> _dt.date | None:
    """dateModified, else datePublished, from the page's JSON-LD. None when it has neither,
    and None for a page that declares itself a listing, whatever dates it carries."""
    found: dict[str, _dt.date] = {}
    for raw in LD_BLOCK.findall(html):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _iter_nodes(data):
            if _types(node) & LISTING_TYPES:
                return None
            for key in DATE_KEYS:
                if key not in found:
                    date = _as_date(node.get(key))
                    if date:
                        found[key] = date
    for key in DATE_KEYS:
        if key in found:
            return found[key]
    return None


def is_noindex(html: str) -> bool:
    for tag in ROBOTS_TAG.findall(html[:8000]):
        if ROBOTS_NAME.search(tag) and NOINDEX.search(tag):
            return True
    return False


def meta_content(html: str, attr: str, value: str) -> str:
    """content= of the first <meta> whose `attr` equals `value`, whatever the attribute order."""
    for tag in META_TAG.findall(html):
        attrs = {}
        for m in ATTR.finditer(tag):
            attrs[m.group(1).lower()] = next(g for g in m.groups()[1:] if g is not None)
        if attrs.get(attr, "").lower() == value:
            return attrs.get("content", "")
    return ""


def page_title(html: str) -> str:
    # <title> first: it is the field the date-consistency check keeps honest. og:title is the fallback.
    m = TITLE.search(html)
    title = m.group(1) if m else meta_content(html, "property", "og:title")
    title = unescape(re.sub(r"\s+", " ", title)).strip()
    for suffix in SITE_SUFFIXES:
        for sep in (" | ", " \u2013 ", " - "):
            if title.endswith(sep + suffix):
                title = title[: -len(sep + suffix)].strip()
    return title


def page_description(html: str) -> str:
    return unescape(re.sub(r"\s+", " ", meta_content(html, "name", "description"))).strip()


def page_url(path: Path) -> str:
    slug = path.relative_to(PAGES).with_suffix("").as_posix()
    return f"{BASE_URL}/{slug}"


def rfc822(date: _dt.date) -> str:
    # Noon UTC keeps the calendar date intact in every US time zone.
    return format_datetime(_dt.datetime(date.year, date.month, date.day, 12, tzinfo=_dt.timezone.utc))


def collect() -> list[dict]:
    items = []
    for path in sorted(PAGES.glob("*.html")):
        if path.name in EXCLUDE:
            continue
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if is_noindex(html):
            continue
        date = schema_date(html)
        if not date:
            continue
        title = page_title(html)
        if not title:
            continue
        items.append({"url": page_url(path), "title": title, "description": page_description(html), "date": date})
    # Newest first; same-day pages A-Z so the order is stable between runs.
    items.sort(key=lambda i: (-i["date"].toordinal(), i["url"]))
    return items[:MAX_ITEMS]


def render(items: list[dict]) -> str:
    newest = items[0]["date"] if items else _dt.date.today()
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"  <title>{xml_escape(SITE_NAME)}</title>",
        f"  <link>{xml_escape(BASE_URL)}/</link>",
        f"  <description>{xml_escape(SITE_DESCRIPTION)}</description>",
        "  <language>en-us</language>",
        f"  <lastBuildDate>{rfc822(newest)}</lastBuildDate>",
        f'  <atom:link href="{xml_escape(BASE_URL)}/{FEED_FILE}" rel="self" type="application/rss+xml"/>',
    ]
    for i in items:
        out.append("  <item>")
        out.append(f"    <title>{xml_escape(i['title'])}</title>")
        out.append(f"    <link>{xml_escape(i['url'])}</link>")
        out.append(f'    <guid isPermaLink="false">{xml_escape(i["url"])}#{i["date"].isoformat()}</guid>')
        out.append(f"    <pubDate>{rfc822(i['date'])}</pubDate>")
        if i["description"]:
            out.append(f"    <description>{xml_escape(i['description'])}</description>")
        out.append("  </item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    items = collect()
    xml = render(items)
    if dry_run:
        sys.stdout.write(xml)
        print(f"\n[dry run] {len(items)} items; newest {items[0]['date'] if items else 'n/a'}", file=sys.stderr)
        return 0
    target = ROOT / FEED_FILE
    before = target.read_text(encoding="utf-8") if target.exists() else None
    if before == xml:
        print(f"{FEED_FILE} already up to date ({len(items)} items).")
        return 0
    target.write_text(xml, encoding="utf-8")
    print(f"Wrote {FEED_FILE} with {len(items)} items; newest {items[0]['date'] if items else 'n/a'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
