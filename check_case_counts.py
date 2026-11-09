#!/usr/bin/env python3
"""
Case count check: every current federal case count on an update page matches the
Judicial Panel's latest report, and the copies of that count agree with each other.

A count lives in many places on one page: the status section, an at-a-glance box, the
meta, og, twitter and JSON-LD descriptions, the visible FAQ and its FAQPage JSON-LD. An
edit that moves one copy and misses another leaves the page saying two things, and none
of the other checkers reads numbers. This one does.

Source of truth: data/mdl_counts.json, the file the status board reads ("pending" is the
latest report, "prior" the one before). The Page update drafts task rewrites it when a
new Panel report lands.

Pages: the status board's PAGES (generate_status_board.py) plus EXTRA_PAGES. Each page's
MDLs are its dev-list data-mdl, its PAGES entry, and EXTRA_MDLS.

What counts as a current count claim, so dated history does not trip the check:
  - the number sits within 20 percent of a latest count (or of a sum of the page's
    counts), so dismissal tallies, settlement sizes and percentages are not read;
  - it is followed within a few words by cases, lawsuits, claims or actions, in a
    sentence that says the cases are pending, held, open, listed, faced or reached;
  - it is outside the dev-list and the Sources list, which are dated history and
    citations by design;
  - the sentence names no month before the latest report's month, and the number is
    not introduced as an earlier figure ("up from 12,381", "was", "of 72,060 ever
    filed").

Findings (warnings; the check never fails a build):
  stale   the number is the prior report's count, said as current
  off     the number matches no count in the latest report for the page's MDLs
  rounded a rounded figure ("more than 15,000", "roughly 25,800") the latest count
          no longer supports
A rounded figure the latest count supports passes.

    python3 check_case_counts.py                 # every board page
    python3 check_case_counts.py --page ozempic-lawsuit-updates.html
    python3 check_case_counts.py --path DIR      # another checkout
"""

from __future__ import annotations

import html
import importlib.util
import itertools
import json
import os
import re
import sys
from pathlib import Path

# Pages that report Panel counts but are not rows on the board. hernia-mesh-lawsuit owns
# status and every count for the hernia cluster (11/6/26); its history page is the row.
EXTRA_PAGES = ["hernia-mesh-lawsuit"]
# Board rows whose MDL is there only for the board's count. The hernia history page links
# to hernia-mesh-lawsuit for every count and must not carry one.
NO_COUNT_PAGES = {"recent-developments-hernia-mesh-litigation"}
# MDLs a page reports beyond its own data-mdl.
EXTRA_MDLS = {
    "hernia-mesh-lawsuit": ["2846", "3029", "2753"],
    "ozempic-lawsuit-updates": ["3094", "3163"],
}

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
NUM = r"(\d{1,3}(?:,\d{3})+|\d{2,})"
NOUN = r"(?:cases?|lawsuits?|claims?|actions?|suits?)"
COUNT_RE = re.compile(NUM + r"(?=\s+(?:[\w'’-]+\s+){0,3}?" + NOUN + r"\b)", re.I)
# A number that is some other tally: cases dismissed, settled, covered, filed in total, or
# a count that takes in state courts ("roughly 76,000 claims across both systems").
OTHER_RE = re.compile(r"\b(dismiss\w*|closed|settl\w*|resolv\w*|cover\w*|transferred|withdr\w*|added)\b", re.I)
STATE_RE = re.compile(r"\b(state|both systems|worldwide)\b", re.I)
YEAR_RE = re.compile(r"^(19|20)\d\d$")
# Words before a number that make it an earlier figure ("up from 12,381 in October and
# 12,129 in September", "was 6,602", "out of 72,060").
BEFORE_RE = re.compile(r"(\bfrom\b.{0,40}$)|(\b(?:was|were|had|of)\s+(?:about\s+|roughly\s+|nearly\s+)?$)", re.I)
AFTER_RE = re.compile(r"^\s*(?:[\w'’-]+\s+){0,4}?(ever filed|ever docketed|filed since|filed in all|in all|in total|"
                      r"a month earlier|the month before|in the prior|in the previous)", re.I)
ROUND_RE = re.compile(r"\b(more than|over|nearly|almost|about|roughly|around|some|close to|"
                      r"approximately|upward of|at least|fewer than|under|less than)\s+$", re.I)
SOURCES_H2 = re.compile(r"<h2\b[^>]*>\s*Sources\s*</h2>", re.I)


def text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def load_board(root: Path):
    spec = importlib.util.spec_from_file_location("board", root / "generate_status_board.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page_mdls(slug: str, page: str, board_mdl: str) -> list:
    out = []
    for n in re.findall(r'class="[^"]*\bdev-list\b[^"]*"[^>]*data-mdl="(\d+)"', page) + [board_mdl] + EXTRA_MDLS.get(slug, []):
        if n and n not in out:
            out.append(n)
    return out


def sentences(page: str) -> list:
    """(where, sentence) for every sentence a reader or a search engine reads as current."""
    out = []
    for name in ("description", "og:description", "twitter:description"):
        m = re.search(r'<meta\s+(?:name|property)="' + re.escape(name) + r'"\s+content="([^"]*)"', page)
        if m:
            out.append((f"meta {name}", html.unescape(m.group(1))))
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("description", "text") and isinstance(v, str):
                        out += [("JSON-LD", s) for s in split(text(v))]
                    else:
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    m = re.search(r"<main\b.*?</main>", page, re.S | re.I)
    body = m.group(0) if m else page
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r'<ul[^>]*class="[^"]*\bdev-list\b[^"]*"[^>]*>.*?</ul>', " ", body, flags=re.S)
    s = SOURCES_H2.search(body)
    if s:
        nxt = re.search(r"<h2\b", body[s.end():], re.I)
        body = body[:s.start()] + (body[s.end() + nxt.start():] if nxt else "")
    for blk in re.findall(r"<(p|li|td|th|h[1-4]|figcaption|dd|dt)\b[^>]*>(.*?)</\1>", body, re.S | re.I):
        out += [("page", x) for x in split(text(blk[1]))]
    return out


def split(t: str) -> list:
    return [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"])", t) if x]


def older_month(sentence: str, report_month: int, report_year: int) -> bool:
    """True when the sentence names a month before the latest report's month."""
    for m in re.finditer(r"\b(" + "|".join(MONTHS) + r")\b(?:\s+\d{1,2},?)?(?:\s+(\d{4}))?", sentence, re.I):
        mo = MONTHS.index(m.group(1).lower()) + 1
        yr = int(m.group(2)) if m.group(2) else report_year
        if (yr, mo) < (report_year, report_month):
            return True
    return False


def check_page(slug: str, page: str, mdls: list, counts: dict, report: str) -> list:
    latest = {n: counts[n]["pending"] for n in mdls if n in counts and counts[n].get("pending") is not None}
    prior = {n: counts[n].get("prior") for n in mdls if n in counts}
    if not latest:
        return []
    ry, rm = int(report[:4]), int(report[5:7])
    sums = {}
    for r in range(2, len(latest) + 1):
        for combo in itertools.combinations(latest, r):
            sums[" + ".join(combo)] = sum(latest[c] for c in combo)
    targets = dict(latest)
    targets.update(sums)
    findings, seen = [], set()
    sents = sentences(page)
    # 1. The latest count is on the page at all. When it is missing, every count the page
    #    gives is older than the report, whatever month it names.
    flat = " ".join(x for _, x in sents)
    for n, v in latest.items():
        if not re.search(r"(?<![\d,])" + re.escape(f"{v:,}") + r"(?![\d,])", flat) and \
           not re.search(r"(?<![\d,])" + str(v) + r"(?![\d,])", flat):
            findings.append(f"missing: the page never gives MDL {n}'s count from the {report} report ({v:,})")
    # 2. Every copy said as current agrees with it. A sentence naming an earlier month is
    #    dated history once the latest count is on the page; check 1 covers it otherwise.
    for where, sent in sents:
        if older_month(sent, rm, ry):
            continue
        for m in COUNT_RE.finditer(sent):
            if YEAR_RE.match(m.group(1)):
                continue
            n = int(m.group(1).replace(",", ""))
            near = [k for k, v in targets.items() if 0.8 * v <= n <= 1.2 * v]
            if not near or n in latest.values() or n in sums.values():
                continue
            before, after = sent[:m.start()], sent[m.end():]
            if BEFORE_RE.search(before[-60:]) or AFTER_RE.search(after) or OTHER_RE.search(before[-40:]) or \
                    STATE_RE.search(before[-40:] + " " + after[:40]):
                continue
            rnd = ROUND_RE.search(before[-25:])
            key = (where, n)
            if key in seen:
                continue
            seen.add(key)
            k = min(near, key=lambda x: abs(targets[x] - n))
            v = targets[k]
            label = f"MDL {k}" if " + " not in k else f"MDLs {k}"
            if rnd:
                word = rnd.group(1).lower()
                if word in ("more than", "over", "at least", "upward of"):
                    ok = v >= n and n >= 0.9 * v
                elif word in ("fewer than", "under", "less than"):
                    ok = v <= n and n <= 1.1 * v
                elif word in ("nearly", "almost", "close to"):
                    ok = n >= v and n <= 1.05 * v
                else:
                    ok = abs(n - v) <= max(0.02 * v, 50)
                if not ok:
                    findings.append(f"rounded: {where} says \"{rnd.group(1)} {m.group(1)}\" but {label} has "
                                    f"{v:,} in the {report} report: \"{snip(sent, m.start())}\"")
                continue
            if k in prior and prior.get(k) == n:
                findings.append(f"stale: {where} gives {m.group(1)} as current, the prior report's count for {label}; "
                                f"the {report} report has {v:,}: \"{snip(sent, m.start())}\"")
            else:
                findings.append(f"off: {where} gives {m.group(1)}, which is no count in the {report} report "
                                f"({label} has {v:,}): \"{snip(sent, m.start())}\"")
    return findings


def snip(sent: str, at: int) -> str:
    a = max(0, at - 60)
    b = min(len(sent), at + 60)
    return ("…" if a else "") + sent[a:b] + ("…" if b < len(sent) else "")


def main() -> int:
    root = Path(".")
    if "--path" in sys.argv:
        root = Path(sys.argv[sys.argv.index("--path") + 1])
    only = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
    try:
        data = json.loads((root / "data" / "mdl_counts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Case count check — data/mdl_counts.json unreadable: {exc}")
        return 1
    counts, report = data.get("mdls", {}), data.get("report_date", "")
    board = load_board(root)
    pages = [(slug, mdl) for slug, _name, _dock, mdl, _intake in board.PAGES] + [(s, "") for s in EXTRA_PAGES]
    if only:
        only_slug = Path(only).name.removesuffix(".html")
        pages = [p for p in pages if p[0] == only_slug] or [(only_slug, "")]
    warned, scanned = {}, 0
    for slug, mdl in pages:
        path = root / f"{slug}.html"
        if not path.exists():
            continue
        page = path.read_text(encoding="utf-8")
        mdls = page_mdls(slug, page, mdl)
        if not mdls or slug in NO_COUNT_PAGES:
            continue
        scanned += 1
        found = check_page(slug, page, mdls, counts, report)
        if found:
            warned[f"{slug}.html"] = found
    print(f"Case count check — {scanned} pages scanned (data/mdl_counts.json report: {report})")
    if warned:
        print(f"\nWARNINGS ({len(warned)} pages)")
        for p in sorted(warned):
            print(f"  {p}")
            for line in warned[p]:
                print(f"      {line}")
    else:
        print("\nEvery current count matches the latest report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
