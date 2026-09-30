#!/usr/bin/env python3
"""
Generate news-sitemap.xml for Lawsuit Informer, submitted to Bing in Bing Webmaster Tools.

A news sitemap lists only recent articles, each with its publication date and headline. It uses
the sitemaps.org schema with the news extension, the format both Bing News and Google News read.

Which pages qualify: the same pages feed.xml carries. A page qualifies when its JSON-LD has a
datePublished and it does not declare itself a listing (CollectionPage and the like). The index,
thank-you, SMS terms and 404 pages stay out through EXCLUDE; the topic hubs and the news listing
declare CollectionPage and stay out for that; a robots noindex keeps a page out as well.

REQUIRE_NEWS_TYPE narrows that to pages whose JSON-LD declares NewsArticle. It is off: Bing News
carries evergreen pages from comparable publishers, and Informer's case pages are published with
a real date the byline shows, so a new case page is news the day it runs. Turn it on to list
only the datelined news pieces.

Which date: datePublished, the date the byline shows. A news sitemap lists publication, so an
update page revised this week after running in August stays out; it is not news again.

The window: articles published in the last WINDOW_DAYS days, counting today. Google's news
sitemap spec puts that at two days and says an empty file is harmless. Bing disagrees in its own
interface: an empty file draws "The feed was empty," and Bing asks the publisher to check the
sitemap for errors and resubmit. This file is submitted to Bing, so it follows Bing. Fourteen
days matches the Intelligencer copy of this script, and Drugwatch, which Bing News carries, had
a 13-day-old article in its own news sitemap on 9/30/26. When nothing qualifies the file is
still written, as a valid empty urlset, so the URL submitted to Bing never 404s between articles.

Shares its page parsing with generate_feed.py in the same folder, so a change to how titles or
dates are read applies to both files.

    python3 generate_news_sitemap.py                    # writes news-sitemap.xml
    python3 generate_news_sitemap.py --dry-run          # prints it instead
    python3 generate_news_sitemap.py --today 2026-09-24 # pretends today is that date
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_feed import (  # noqa: E402
    EXCLUDE, LD_BLOCK, LISTING_TYPES, PAGES, ROOT, SITE_NAME,
    _iter_nodes, _types, is_noindex, page_title, page_url, xml_escape,
)

OUT_FILE = "news-sitemap.xml"
WINDOW_DAYS = 14
LANGUAGE = "en"
REQUIRE_NEWS_TYPE = False
NEWS_TYPES = {"NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle"}


def published(html: str) -> str | None:
    """The page's JSON-LD datePublished as written (a date or a datetime), or None.

    None as well for a page that declares itself a listing, whatever dates it carries, and,
    with REQUIRE_NEWS_TYPE on, for a page whose JSON-LD never declares a news type.
    """
    found = None
    news_type = False
    for raw in LD_BLOCK.findall(html):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _iter_nodes(data):
            types = _types(node)
            if types & LISTING_TYPES:
                return None
            if types & NEWS_TYPES:
                news_type = True
            value = node.get("datePublished")
            if found is None and isinstance(value, str) and len(value) >= 10:
                try:
                    _dt.date.fromisoformat(value[:10])
                except ValueError:
                    continue
                found = value.strip()
    if REQUIRE_NEWS_TYPE and not news_type:
        return None
    return found


def collect(today: _dt.date) -> list[dict]:
    first_day = today - _dt.timedelta(days=WINDOW_DAYS - 1)
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
        stamp = published(html)
        if not stamp:
            continue
        day = _dt.date.fromisoformat(stamp[:10])
        if not (first_day <= day <= today):
            continue
        title = page_title(html)
        if not title:
            continue
        items.append({"url": page_url(path), "title": title, "published": stamp, "day": day})
    items.sort(key=lambda i: (-i["day"].toordinal(), i["url"]))
    return items


def render(items: list[dict]) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">',
    ]
    for i in items:
        out += [
            "  <url>",
            f"    <loc>{xml_escape(i['url'])}</loc>",
            "    <news:news>",
            "      <news:publication>",
            f"        <news:name>{xml_escape(SITE_NAME)}</news:name>",
            f"        <news:language>{LANGUAGE}</news:language>",
            "      </news:publication>",
            f"      <news:publication_date>{xml_escape(i['published'])}</news:publication_date>",
            f"      <news:title>{xml_escape(i['title'])}</news:title>",
            "    </news:news>",
            "  </url>",
        ]
    out += ["</urlset>", ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    today = _dt.datetime.now(_dt.timezone.utc).date()
    if "--today" in argv:
        today = _dt.date.fromisoformat(argv[argv.index("--today") + 1])
    items = collect(today)
    xml = render(items)
    if "--dry-run" in argv:
        sys.stdout.write(xml)
        print(f"\n[dry run] {len(items)} articles in the {WINDOW_DAYS}-day window ending {today}", file=sys.stderr)
        return 0
    target = ROOT / OUT_FILE
    if target.exists() and target.read_text(encoding="utf-8") == xml:
        print(f"{OUT_FILE} already up to date ({len(items)} articles).")
        return 0
    target.write_text(xml, encoding="utf-8")
    print(f"Wrote {OUT_FILE} with {len(items)} articles in the {WINDOW_DAYS}-day window ending {today}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
