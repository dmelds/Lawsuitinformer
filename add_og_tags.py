#!/usr/bin/env python3
"""
Inject OG + Twitter card meta tags into Lawsuit Informer .html files.

Reads each file's <title> and <meta name="description"> and generates a
standard OG/Twitter block, inserted before the first JSON-LD script in <head>.
Skips files that already have og: tags.

Usage:
    python add_og_tags.py                    # current directory
    python add_og_tags.py path/to/repo       # specific directory
    python add_og_tags.py --dry-run          # preview, no writes
"""

import os
import re
import sys
from pathlib import Path

# ---- Configuration --------------------------------------------------
SITE_URL = "https://lawsuitinformer.com"
OG_IMAGE = f"{SITE_URL}/og-default.png"           # change to .jpg if you used jpg
OG_IMAGE_ALT = "Lawsuit Informer — Attorney-led legal education"
SITE_NAME = "Lawsuit Informer"
TWITTER_CARD = "summary_large_image"
# ---------------------------------------------------------------------

TITLE_RE = re.compile(r'<title>(.*?)</title>', re.DOTALL | re.IGNORECASE)
DESC_RE = re.compile(
    r'<meta\s+name=["\']description["\'][^>]*?content=["\'](.*?)["\']',
    re.DOTALL | re.IGNORECASE,
)
DESC_RE_ALT = re.compile(
    r'<meta\s+content=["\'](.*?)["\'][^>]*?name=["\']description["\']',
    re.DOTALL | re.IGNORECASE,
)
CANONICAL_RE = re.compile(
    r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']',
    re.IGNORECASE,
)
OG_PRESENT_RE = re.compile(r'<meta\s+property=["\']og:', re.IGNORECASE)
JSON_LD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\']',
    re.IGNORECASE,
)


def extract_first(pattern, html):
    m = pattern.search(html)
    if not m:
        return None
    return " ".join(m.group(1).split())  # collapse whitespace


def make_og_block(url, title, description):
    return (
        f'  <meta property="og:type" content="article">\n'
        f'  <meta property="og:url" content="{url}">\n'
        f'  <meta property="og:title" content="{title}">\n'
        f'  <meta property="og:description" content="{description}">\n'
        f'  <meta property="og:image" content="{OG_IMAGE}">\n'
        f'  <meta property="og:image:width" content="1200">\n'
        f'  <meta property="og:image:height" content="630">\n'
        f'  <meta property="og:image:alt" content="{OG_IMAGE_ALT}">\n'
        f'  <meta property="og:site_name" content="{SITE_NAME}">\n'
        f'\n'
        f'  <meta name="twitter:card" content="{TWITTER_CARD}">\n'
        f'  <meta name="twitter:title" content="{title}">\n'
        f'  <meta name="twitter:description" content="{description}">\n'
        f'  <meta name="twitter:image" content="{OG_IMAGE}">\n'
    )


def process_file(filepath, dry_run=False):
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    if OG_PRESENT_RE.search(html):
        return "skipped (already has og: tags)"

    title = extract_first(TITLE_RE, html)
    description = extract_first(DESC_RE, html) or extract_first(DESC_RE_ALT, html)

    m = CANONICAL_RE.search(html)
    canonical = m.group(1).strip() if m else None

    if not title or not description:
        return f"skipped (title={bool(title)}, desc={bool(description)})"

    # For og:type, use "website" for homepage / hub pages, "article" otherwise.
    # Homepage is index.html; everything else defaults to article.
    if not canonical:
        fn = os.path.basename(filepath)
        canonical = f"{SITE_URL}/" if fn == "index.html" else f"{SITE_URL}/{fn}"

    og_block = make_og_block(canonical, title, description)

    # Find the first JSON-LD script and insert before it (preserving its indent).
    m = JSON_LD_RE.search(html)
    if m:
        # Find the start of the line containing the script tag
        line_start = html.rfind("\n", 0, m.start()) + 1
        new_html = html[:line_start] + og_block + "\n" + html[line_start:]
    else:
        # Fallback: insert before </head>
        idx = html.lower().find("</head>")
        if idx == -1:
            return "failed: no </head> or JSON-LD found"
        # Insert with matching indentation
        line_start = html.rfind("\n", 0, idx) + 1
        new_html = html[:line_start] + og_block + html[line_start:]

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_html)

    return "updated"


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    base_dir = args[0] if args else "."

    files = sorted(Path(base_dir).glob("*.html"))
    if not files:
        print(f"No .html files in {base_dir}")
        return

    counts = {"updated": 0, "skipped": 0, "failed": 0}
    for path in files:
        result = process_file(str(path), dry_run=dry_run)
        print(f"{path.name}: {result}")
        if result.startswith("updated"):
            counts["updated"] += 1
        elif result.startswith("failed"):
            counts["failed"] += 1
        else:
            counts["skipped"] += 1

    print()
    print(f"Updated: {counts['updated']}")
    print(f"Skipped: {counts['skipped']}")
    print(f"Failed:  {counts['failed']}")
    if dry_run:
        print("(DRY RUN — no files were written)")


if __name__ == "__main__":
    main()

