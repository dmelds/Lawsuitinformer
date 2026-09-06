#!/usr/bin/env python3
"""
check_medical_review.py — verify that the visible medical-review byline and the
structured data agree on every page.

Two real defects prompted this, both found by hand on 2026-09-05:

  * pfas-health-effects.html declared reviewedBy + lastReviewed "2026-06-02" in
    MedicalWebPage schema while the visible byline sat commented out awaiting
    review. A machine-readable claim, naming a real physician, for a review that
    had not happened.

  * symptoms-of-asbestos-exposure.html had a genuine, live reviewed byline, but
    its reviewedBy/lastReviewed were nested inside mainEntityOfPage — a node most
    consumers treat as a bare @id reference — so the review was effectively
    invisible to anything reading the structured data.

Neither was detectable by any existing check. The rule is simply that the byline
and the schema must both be present or both absent, and must agree on the date.

Usage:
    python3 check_medical_review.py                 # scan every page
    python3 check_medical_review.py --page X.html   # scan one page
    python3 check_medical_review.py --strict        # exit 1 on any ERROR

Notes on parsing, learned the hard way in this repo:
  * HTML comments are stripped before anything else. A commented-out byline is
    not a byline, and counting "<!--" against "-->" by hand gets this wrong.
  * Tags are never matched with a single-line pattern. Several pages in this repo
    write attributes across multiple lines.
"""

import argparse
import glob
import json
import os
import re
import sys

REVIEWER_SLUG = "dr-thomas-hatzilabrou"

# Site-information pages describe the review programme rather than carrying a
# per-page medical review, so naming the reviewer there is descriptive, not a
# claim about that page's content. Add to this list rather than loosening a rule.
EXEMPT = {"about.html", "editorial-policy.html"}

# The footer nav links the medical reviewer on every page. That is navigation,
# not a byline, so a bare link to the profile never counts as evidence of review.
BYLINE_RE = re.compile(r"Medically reviewed by", re.I)
VISIBLE_DATE_RE = re.compile(
    r"(?:Last updated and medically reviewed|Medically reviewed)\s*:?\s*"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})"
)
ROUTING_RE = re.compile(r"Route this page through Dr\. Hatzilabrou", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split(), 1)}


def strip_comments(html):
    return COMMENT_RE.sub(" ", html)


def visible_date_to_iso(text):
    m = VISIBLE_DATE_RE.search(text)
    if not m:
        return None
    month, day, year = re.match(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", m.group(1)).groups()
    if month not in MONTHS:
        return None
    return f"{year}-{MONTHS[month]:02d}-{int(day):02d}"


def walk(node, path=""):
    """Yield (path, dict) for every object in a parsed JSON-LD tree."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def inspect(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    visible = strip_comments(raw)

    live_byline = bool(BYLINE_RE.search(visible))
    routing_note = bool(ROUTING_RE.search(raw))
    visible_date = visible_date_to_iso(visible)

    reviewed_at = []      # (json-path, @type, lastReviewed, reviewer, sibling author, reviewer jobTitle)
    page_authors = set()  # every author named anywhere in the page's JSON-LD
    bad_json = []
    for block in LD_RE.findall(raw):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as exc:
            bad_json.append(str(exc)[:60])
            continue
        for jpath, obj in walk(data):
            if "reviewedBy" in obj or "lastReviewed" in obj:
                rb = obj.get("reviewedBy") or {}
                rname = rb.get("name") if isinstance(rb, dict) else str(rb)
                aut = obj.get("author") or {}
                aname = aut.get("name") if isinstance(aut, dict) else None
                rjob = rb.get("jobTitle") if isinstance(rb, dict) else None
                reviewed_at.append((jpath or "<root>",
                                    obj.get("@type"),
                                    obj.get("lastReviewed"),
                                    rname,
                                    aname,
                                    rjob))
            if "author" in obj:
                a = obj["author"]
                nm = a.get("name") if isinstance(a, dict) else None
                if nm:
                    page_authors.add(nm.split(",")[0].strip())

    errors, warnings = [], []

    if bad_json:
        errors.append(f"JSON-LD does not parse: {'; '.join(bad_json)}")

    page_name = os.path.basename(path)
    # A page whose reviewer is its own author is asserting self-review, which is
    # a different claim from independent medical review and needs no byline.
    def is_self(rname, aname):
        if not rname:
            return False
        first = rname.split(",")[0].strip()
        return first in page_authors or (aname and first == aname.split(",")[0].strip())

    self_reviewed = bool(reviewed_at) and all(
        is_self(r, a) for _, _, _, r, a, _ in reviewed_at)

    # A reviewer whose stated role is not medical is not asserting a medical
    # review, whatever the schema property is called.
    non_medical = bool(reviewed_at) and all(
        (j or "") and "medical" not in (j or "").lower()
        for _, _, _, _, _, j in reviewed_at)

    if reviewed_at and not live_byline:
        if page_name in EXEMPT:
            pass
        elif self_reviewed or non_medical:
            why = ("names the page's own author" if self_reviewed
                   else "names a reviewer whose stated role is not medical")
            warnings.append(
                f"reviewedBy {why}, so this asserts review by the site rather "
                "than independent medical review; no medical byline is expected")
        else:
            errors.append(
                "structured data claims a medical review (reviewedBy/lastReviewed) "
                "but no visible 'Medically reviewed by' byline is on the page")

    if live_byline and not reviewed_at:
        errors.append(
            "page carries a visible 'Medically reviewed by' byline but no "
            "reviewedBy in any JSON-LD block")

    if live_byline and routing_note:
        errors.append(
            "page carries a live reviewed byline AND a 'route this through "
            "Dr. Hatzilabrou before publishing' note — one of them is wrong")

    for jpath, ctype, last, _rname, _aname, _rjob in reviewed_at:
        if jpath.startswith("mainEntityOfPage"):
            warnings.append(
                "reviewedBy is nested inside mainEntityOfPage, which consumers "
                "may treat as a bare @id reference; move it to a top-level "
                "WebPage or MedicalWebPage entity")
        if ctype and ctype not in ("WebPage", "MedicalWebPage") and page_name not in EXEMPT:
            warnings.append(
                f"reviewedBy sits on @type {ctype}; schema.org defines "
                "reviewedBy and lastReviewed on WebPage and its subtypes")
        if last and visible_date and last != visible_date:
            warnings.append(
                f"lastReviewed {last} does not match the visible review date "
                f"{visible_date}")
        if not last and page_name not in EXEMPT:
            warnings.append("reviewedBy present with no lastReviewed date")

    return errors, warnings, live_byline, bool(reviewed_at)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="check a single file")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any ERROR is found")
    ap.add_argument("--root", default=".", help="directory to scan")
    args = ap.parse_args()

    if args.page:
        files = [args.page if os.path.isabs(args.page)
                 else os.path.join(args.root, args.page)]
    else:
        files = sorted(glob.glob(os.path.join(args.root, "*.html")))

    if not files:
        print("no pages found; run from the repo root")
        return 0

    n_err = n_warn = n_reviewed = 0
    err_pages, warn_pages = [], []

    for path in files:
        errors, warnings, byline, schema = inspect(path)
        if byline and schema:
            n_reviewed += 1
        name = os.path.basename(path)
        if errors:
            err_pages.append((name, errors))
            n_err += len(errors)
        if warnings:
            warn_pages.append((name, warnings))
            n_warn += len(warnings)

    print(f"Medical review check — {len(files)} pages scanned; "
          f"{n_reviewed} carry a byline and matching schema")

    if err_pages:
        print(f"\nERRORS ({len(err_pages)} pages)")
        for name, msgs in err_pages:
            print(f"  {name}")
            for m in msgs:
                print(f"      {m}")

    if warn_pages:
        print(f"\nWARNINGS ({len(warn_pages)} pages)")
        for name, msgs in warn_pages:
            print(f"  {name}")
            for m in msgs:
                print(f"      {m}")

    if not err_pages and not warn_pages:
        print("\nno issues found")

    return 1 if (args.strict and n_err) else 0


if __name__ == "__main__":
    sys.exit(main())
