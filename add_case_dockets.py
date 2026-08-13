#!/usr/bin/env python3
"""Surface case docket numbers in the title family of Lawsuit Informer case pages.

Why
---
Bing query data shows people searching docket numbers directly. `cgc-26-637986`
drew impressions at position 2 -- that is the Parish docket, which currently
lives in the page body but not in the title. The one case page that does carry
its docket in the title, Raine (CGC-25-628528), converts its name queries at
46-50% click-through from positions 2.7 and 6.0. This applies the Raine pattern
to the pages where the docket is unique to that page.

Deliberately NOT applied to Lacey, Shamblin and Carrier: those three share
JCCP 5431 and nothing else, so putting the same docket in all three titles
would have them compete with each other and with the JCCP hub on one query.
Add them here only once individual case numbers are known.

What it touches
---------------
<title> only. og:title and twitter:title are deliberately left alone: they
drive the social share card, where a docket number is noise rather than signal,
and this repo already lets those diverge from <title> on some pages.

It does not touch <h1>, the JSON-LD
headline, or any Month YYYY stamp, so check_date_consistency.py is unaffected
-- that script compares month stamps across fields, not full title text, and
your titles already diverge from h1 on some pages.

Tag matching tolerates attributes split across lines. The head tags in this
repo are formatted multi-line, and a single-line regex silently misses them.

Idempotent: a page whose title already contains its docket is left alone.

Usage
-----
    python3 add_case_dockets.py                 # dry run, prints before/after
    python3 add_case_dockets.py --apply         # write changes
    python3 add_case_dockets.py --path ~/repo   # repo root (default .)

Review with `git diff` before committing. Suggested commit message:
    Surface case dockets in titles [skip lastmod] [skip actions]
"""
import argparse
import re
import sys
from pathlib import Path

# slug -> (new <title>, docket string that must appear for the edit to be a no-op)
# Titles follow the proven Raine shape: "<Case> Lawsuit Status <year> (<docket>)".
# Edit these strings if you want different wording -- they are the whole config.
TITLES = {
    "parish-v-openai-lawsuit": (
        "Parish v. OpenAI Lawsuit Status 2026 (CGC-26-637986)",
        "CGC-26-637986",
    ),
    "chatgpt-fsu-shooting-lawsuit": (
        "OpenAI Sued Over FSU Shooting | Chabba (4:26-cv-00222)",
        "4:26-cv-00222",
    ),
}

def replace_title_tag(text, new_title):
    """Replace the contents of <title>...</title>. Returns (text, old or None)."""
    m = re.search(r"(?is)(<title[^>]*>)(.*?)(</title>)", text)
    if not m:
        return text, None
    old = m.group(2).strip()
    return text[: m.start(2)] + new_title + text[m.end(2) :], old



def process(path, new_title, docket, apply_changes):
    text = path.read_text(encoding="utf-8", errors="ignore")

    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if tm and docket in tm.group(1):
        return "already-done", []

    changes = []
    text, old = replace_title_tag(text, new_title)
    if old is None:
        return "no-title", []
    changes.append(("title", old, new_title))

    if apply_changes:
        path.write_text(text, encoding="utf-8")
    return "updated", changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.path)
    mode = "APPLIED" if args.apply else "DRY RUN (no files written)"
    print(f"Case docket titles -- {mode}\n")

    updated = skipped = missing = 0
    for slug, (new_title, docket) in TITLES.items():
        path = root / f"{slug}.html"
        if not path.exists():
            print(f"  MISSING  {path}")
            missing += 1
            continue
        status, changes = process(path, new_title, docket, args.apply)
        if status == "already-done":
            print(f"  skip     {slug} -- title already contains {docket}")
            skipped += 1
            continue
        if status == "no-title":
            print(f"  ERROR    {slug} -- no <title> tag found")
            missing += 1
            continue
        updated += 1
        print(f"  {slug}  ({len(new_title)} chars)")
        for label, old, new in changes:
            print(f"      {label}")
            print(f"        - {old}")
            if new:
                print(f"        + {new}")
        print()

    print(f"{updated} updated, {skipped} already correct, {missing} not actionable")
    if updated and not args.apply:
        print("\nRerun with --apply to write, then review with: git diff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
