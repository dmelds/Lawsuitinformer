#!/usr/bin/env python3
"""Check that every Month YYYY freshness stamp on a page agrees with the page itself.

Replaces check_title_freshness.py, which only looked at <title>. Looking at the
title alone produced the failure mode this script exists to catch: the title got
bumped to the new month to clear the gate while the meta description, og/twitter
tags, JSON-LD headline, H1, and dateModified all stayed behind. Search results
show the description, so the bump bought nothing and the page ended up claiming
two different months at once.

Rules
-----
ERROR  A stamp is NEWER than the month in JSON-LD dateModified. A page cannot
       claim a currency month it was never edited in. This is the false-freshness
       case and it blocks the merge under --strict.
ERROR  The <title> stamp disagrees with the <h1> stamp or the og:title stamp.
WARN   The <title> or <h1> stamp is OLDER than the dateModified month. The page
       was edited but the stamp did not move. Warn only: the stamp may be
       referring to an event rather than to currency.
WARN   The <title> stamp is OLDER than the month the check is running in, even
       though the page is internally consistent. This is the case the
       dateModified comparison cannot see: a page edited in July and stamped
       July agrees with itself forever, and silently keeps claiming July in
       August. Searchers type the month ("bard hernia mesh lawsuit update july
       2026"), so a title promising a month that has passed reads as abandoned.
       Warn only, and never on a PR: the stamp goes stale by the calendar
       turning over, not by anything the commit did.

Historical references are safe by construction. "the May 2025 ruling" in a page
modified in 2026 is older than dateModified, so it never errors.

Fields scanned: <title>, og:title, twitter:title, meta description,
og:description, twitter:description, first <h1>, and the headline/description
of any JSON-LD node that carries its own dateModified. Headlines inside an
ItemList on a listing page are ignored, since they date other articles.

Usage
-----
    python3 check_date_consistency.py            # report, exit 0
    python3 check_date_consistency.py --strict   # exit 1 on any ERROR
    python3 check_date_consistency.py --path .   # scan root (default .)
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MONTHS = {m: i + 1 for i, m in enumerate([
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
])}
NAMES = {v: k for k, v in MONTHS.items()}
STAMP = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b")

TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
META = re.compile(r"<meta\b[^>]*>", re.S | re.I)
ATTR = re.compile(r'(\w[\w:-]*)\s*=\s*"([^"]*)"', re.S)
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
TAGS = re.compile(r"<[^>]+>")


def text(raw):
    return " ".join(TAGS.sub(" ", raw or "").split())


def stamps(value):
    """Return list of (year, month) found in a string."""
    return [(int(y), MONTHS[m]) for m, y in STAMP.findall(value or "")]


def label(ym):
    return f"{NAMES[ym[1]]} {ym[0]}"


def metas(html):
    """Map of meta name/property -> content."""
    out = {}
    for tag in META.findall(html):
        attrs = dict(ATTR.findall(tag))
        key = attrs.get("name") or attrs.get("property")
        if key and "content" in attrs:
            out.setdefault(key.lower(), attrs["content"])
    return out


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def jsonld(html):
    """Return (date_modified, [(field, value), ...]) from JSON-LD blocks."""
    modified = None
    fields = []
    for block in LD.findall(html):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for node in walk(data):
            if not isinstance(node, dict):
                continue
            dm = node.get("dateModified")
            if isinstance(dm, str) and not modified:
                modified = dm
            # Only read headline/description off the node that actually dates
            # itself. Listing pages carry an ItemList of other articles, and
            # those headlines describe their own months, not this page's.
            if not isinstance(dm, str):
                continue
            for key in ("headline", "description"):
                val = node.get(key)
                if isinstance(val, str):
                    fields.append((f"ld:{key}", val))
    return modified, fields


def modified_ym(value):
    if not value:
        return None
    m = re.match(r"(20\d{2})-(\d{2})", value)
    return (int(m.group(1)), int(m.group(2))) if m else None


def scan(path, now_ym=None):
    html = path.read_text(encoding="utf-8", errors="ignore")
    m = TITLE.search(html)
    if not m:
        return [], []
    title = text(m.group(1))
    h1m = H1.search(html)
    h1 = text(h1m.group(1)) if h1m else ""
    mt = metas(html)
    dm_raw, ld_fields = jsonld(html)
    dm = modified_ym(dm_raw)

    fields = [("title", title), ("h1", h1)]
    for key in ("description", "og:title", "og:description",
                "twitter:title", "twitter:description"):
        if key in mt:
            fields.append((key, mt[key]))
    fields.extend(ld_fields)

    errors, warnings = [], []

    if dm:
        for name, value in fields:
            for ym in stamps(value):
                if ym > dm:
                    errors.append(
                        f"{name} claims {label(ym)} but dateModified is "
                        f"{dm_raw} ({label(dm)})"
                    )

    t_stamps = stamps(title)
    if t_stamps:
        newest = max(t_stamps)
        for name, value in (("h1", h1), ("og:title", mt.get("og:title", ""))):
            other = stamps(value)
            if other and max(other) != newest:
                errors.append(
                    f"title says {label(newest)} but {name} says "
                    f"{label(max(other))}"
                )
        if dm and newest < dm:
            warnings.append(
                f"title stamp {label(newest)} is older than dateModified "
                f"{dm_raw} — page was edited, stamp was not"
            )
        if now_ym and newest < now_ym:
            months = (now_ym[0] - newest[0]) * 12 + (now_ym[1] - newest[1])
            warnings.append(
                f"title stamp {label(newest)} is {months} month"
                f"{'s' if months != 1 else ''} behind the current month "
                f"({label(now_ym)}) — the page still reads as current to the "
                f"checker but not to a searcher"
            )
    h_stamps = stamps(h1)
    if h_stamps and dm and max(h_stamps) < dm and not t_stamps:
        warnings.append(
            f"h1 stamp {label(max(h_stamps))} is older than dateModified {dm_raw}"
        )

    return errors, warnings


def main():
    strict = "--strict" in sys.argv
    # The calendar rule is time-dependent, not commit-dependent: the same tree
    # passes in July and warns in August. Keep it off the PR gate so a merge
    # never fails for a reason the branch did not cause.
    calendar = "--no-calendar" not in sys.argv and not strict
    root = Path(".")
    if "--path" in sys.argv:
        root = Path(sys.argv[sys.argv.index("--path") + 1])

    today = datetime.now(timezone.utc)
    now_ym = (today.year, today.month) if calendar else None

    bad, warned, scanned = {}, {}, 0
    for path in sorted(root.rglob("*.html")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        scanned += 1
        errors, warnings = scan(path, now_ym)
        if errors:
            bad[str(path)] = errors
        if warnings:
            warned[str(path)] = warnings

    print(
        f"Date consistency check — {scanned} pages scanned "
        f"(build month: {today.strftime('%B %Y')}"
        f"{'' if calendar else '; calendar rule off'})"
    )

    if bad:
        print(f"\nERRORS ({len(bad)} pages)")
        for path in sorted(bad):
            print(f"  {path}")
            for line in bad[path]:
                print(f"      {line}")
    if warned:
        print(f"\nWARNINGS ({len(warned)} pages)")
        for path in sorted(warned):
            print(f"  {path}")
            for line in warned[path]:
                print(f"      {line}")
    if not bad and not warned:
        print("\nAll date signals consistent.")

    return 1 if (bad and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
