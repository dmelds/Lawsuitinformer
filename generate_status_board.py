#!/usr/bin/env python3
"""
Generate current-mass-tort-cases.html, the status board, from the update pages.

The board is one row per litigation the site keeps an update page for, newest
change first. Everything on it is read from the update pages themselves, so
the board can never say something the page it links to does not say:

  dateModified          the page's JSON-LD date; decides which band the row sits in
  <meta name="li:status">   the row's status label ("Trial set", "Sign-up deadline")
  <meta name="li:next">     "YYYY-MM-DD|what happens" — the next court date; a date
                            that has passed is dropped, so the board never shows a
                            stale "next hearing"
  <ul class="dev-list">     the dated entries: each <li> with a <time datetime>, a
                            data-kind and a bold lead sentence. The first two are
                            shown, the rest sit behind a <details>. A list item with
                            no <time> is skipped. Pages with no list get one line,
                            the page's meta description.
  data-mdl / MDLS           the federal docket, for the pending count

Pending counts come from data/mdl_counts.json, written by whoever loads the
JPML report (see network-ops jpml_to_bq). Shape:

  {"report_date": "2026-10-01",
   "mdls": {"3060": {"pending": 12381, "prior": 12129}, ...}}

Missing file, missing MDL: the row shows no count. Never an error.

The page shell (head, header, footer, dark mode, scripts) is the existing
current-mass-tort-cases.html on disk. Only the <main> block, the <title>, the
descriptions and the JSON-LD dates are rewritten, so the perf, dark-mode and
CTA sweeps keep working on this file like any other.

The file is written only when the rows changed. A day with no change leaves
the file untouched and the workflow commits nothing, so the sitemap lastmod,
the feed and the Last updated stamp move only when a reader would see
something new. When the rows change, dateModified and both visible stamps move
to today.

The homepage carries a short strip of the same rows, the five most recently
changed open cases, between <!-- LI-BOARD:BEGIN --> and <!-- LI-BOARD:END --> in
index.html. On the first run the block is inserted after the credibility strip;
after that it is replaced in place. index.html is written only when the strip
changed, on the same rule as the board.

Each update page in PAGES carries one line under its "Last updated" stamp that
points readers to the board, between <!-- LI-BOARD-LINK:BEGIN --> and
<!-- LI-BOARD-LINK:END -->. The first run inserts it after the page's
<p class="article-date">; later runs replace it in place, so an update page
added to PAGES picks the line up on its next run and a change to the wording
reaches every page at once. A page is written only when its line changed. The
line is navigation, not content, so it never moves the page's dateModified or
stamp; the workflow commits these pages separately with [skip lastmod].

    python3 generate_status_board.py            # writes the page if it changed
    python3 generate_status_board.py --dry-run  # prints what would change
    python3 generate_status_board.py --force    # writes even if unchanged
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html
import json
import os
import re
import sys

SITE = "https://lawsuitinformer.com"
OUT = "current-mass-tort-cases.html"
HOME = "index.html"
HOME_ROWS = 5
HOME_BEGIN = "<!-- LI-BOARD:BEGIN -->"
HOME_END = "<!-- LI-BOARD:END -->"
HOME_ANCHOR = "<!-- ===================== END CREDIBILITY STRIP ===================== -->"
LINK_BEGIN = "<!-- LI-BOARD-LINK:BEGIN -->"
LINK_END = "<!-- LI-BOARD-LINK:END -->"
# The stamp paragraph on every update page; the line goes right after its closing </p>.
LINK_ANCHOR = re.compile(r'<p class="article-date">.*?</p>', re.S)
COUNTS = os.path.join("data", "mdl_counts.json")
SHOW = 2            # entries shown before the "show more" fold
WEEK = 7            # days: the "changed in the last 7 days" band

# slug -> (name, docket label, federal MDL number or "", Center intake for a deadline row or "")
PAGES = [
    ("pfas-water-contamination-lawsuit-update", "PFAS Water Contamination", "MDL 2873 · D.S.C.", "2873", ""),
    ("afff-lawsuit-updates", "AFFF Firefighting Foam", "MDL 2873 · D.S.C.", "2873", ""),
    ("depo-provera-lawsuit-updates", "Depo-Provera", "MDL 3140 · N.D. Fla.", "3140", "depo-provera-case-review"),
    ("roundup-lawsuit-updates", "Roundup", "MDL 2741 · N.D. Cal.", "2741", ""),
    ("paraquat-lawsuit-updates", "Paraquat", "MDL 3004 · S.D. Ill.", "3004", ""),
    ("tylenol-lawsuit-updates", "Tylenol and Autism", "MDL 3043 · S.D.N.Y.", "3043", ""),
    ("asbestos-lawsuit-updates", "Mesothelioma and Asbestos", "State courts and trusts", "", ""),
    ("talcum-powder-lawsuit-updates", "Talcum Powder", "MDL 2738 · D.N.J.", "2738", ""),
    ("ozempic-lawsuit-updates", "Ozempic and GLP-1 Drugs", "MDL 3094 · E.D. Pa.", "3094", ""),
    ("hair-relaxer-lawsuit-updates", "Hair Relaxer", "MDL 3060 · N.D. Ill.", "3060", ""),
    ("suboxone-lawsuit-updates", "Suboxone Tooth Decay", "MDL 3092 · N.D. Ohio", "3092", ""),
    ("social-media-addiction-lawsuit-update", "Social Media Addiction", "MDL 3047 · N.D. Cal.", "3047", ""),
    ("house-ncaa-settlement-update", "House v. NCAA Settlement", "N.D. Cal. · 9th Cir. appeal", "", ""),
    ("video-game-addiction-lawsuit-update", "Video Games and Roblox", "JCCP 5363 · MDL 3166", "3166", ""),
    ("transvaginal-mesh-litigation-update", "Transvaginal Mesh", "State courts", "", ""),
    # The OpenAI hub doubles as the AI litigation's update page: its Recent Developments list is
    # a dev-list and it carries li:status / li:next like the update pages.
    ("openai-lawsuits", "ChatGPT and OpenAI", "JCCP 5431 · N.D. Cal. · N.D. Fla.", "", "openai-case-review"),
]

# Status labels that put a row in the closed band at the foot of the board.
CLOSED_WORDS = re.compile(r"\b(closed|wound down|concluded)\b", re.I)
# A deadline the READER has to act on: settlement sign-ups, claim filing, opt-outs, registration.
# Red on the board and in the weekly email means this and nothing else, and every red date
# carries the word DEADLINE so the color never has to explain itself. Court-schedule dates
# ("expert discovery closes", "deadline for Kenvue to ask the Supreme Court") are deliberately
# left out: they are the court's dates, not the reader's. To mark a reader deadline, word the
# page's li:next with one of these terms (e.g. "Settlement sign-ups close").
URGENT_WORDS = re.compile(
    r"\b(sign-?ups?|sign up|claims? (?:deadline|due|close|closes|window)|claim forms?|"
    r"opt-?outs?|opting out|registration|enrollment)\b", re.I)
LIVE_WORDS = re.compile(r"\b(trial|verdict|hearing)\b", re.I)

CAMPAIGN = "status_board"
# The hero and closing CTAs point at Center's general /case-review form, whose select has no
# "Not Sure" value, so no button here sends situation= (check_situation_params fails a value
# the target form cannot take). Row CTAs name a dedicated intake and send nothing either.


def cta(path: str, slot: str, extra: str = "") -> str:
    return (f"https://lawsuit.center/{path}?utm_source=lawsuitinformer&amp;utm_medium=referral"
            f"&amp;utm_campaign={CAMPAIGN}&amp;utm_content={slot}{extra}")


# ---------------------------------------------------------------- reading the pages


def text(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s)).split())


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def meta(page: str, name: str) -> str:
    m = re.search(r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), page)
    return html.unescape(m.group(1)).strip() if m else ""


def date_modified(page: str) -> str:
    m = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})', page)
    return m.group(1) if m else ""


def description(page: str) -> str:
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', page, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def dev_entries(page: str, slug: str) -> list:
    """[(iso, kind, lead, anchor)] from the page's dev-list, newest first."""
    m = re.search(r'<ul[^>]*class="[^"]*\bdev-list\b[^"]*"[^>]*>(.*?)</ul>', page, re.S)
    if m:
        block = m.group(1)
    else:
        # Pages not yet converted: every list between the recent-developments heading and
        # the next <h2>, read for <time> inside the bold lead. Items with no <time> are skipped.
        sec = re.search(r'<h2[^>]*id="recent-developments"[^>]*>.*?</h2>(.*?)(?=<h2\b|</main>)', page, re.S)
        if not sec:
            return []
        block = "".join(re.findall(r"<ul[^>]*>(.*?)</ul>", sec.group(1), re.S))
    out = []
    for attrs, body in re.findall(r"<li([^>]*)>(.*?)</li>", block, re.S):
        t = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})', body)
        if not t:
            continue
        iso = t.group(1)
        k = re.search(r'data-kind="([a-z]+)"', attrs)
        kind = k.group(1) if k else "other"
        i = re.search(r'id="([^"]+)"', attrs)
        anchor = f"/{slug}#{i.group(1)}" if i else f"/{slug}#recent-developments"
        s = re.search(r"<strong>(.*?)</strong>", body, re.S)
        lead = text(s.group(1)) if s else text(body)
        # "October 22, 2026, the judge ..." -> "The judge ..."
        lead = re.sub(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s*\d{4},?\s*", "", lead)
        # Headline-style leads ("Texas sues OpenAI and Sam Altman:") drop the colon that
        # introduces the body on the page.
        lead = lead.rstrip().rstrip(":").rstrip()
        lead = lead[:1].upper() + lead[1:] if lead else lead
        out.append((iso, kind, lead, anchor))
    out.sort(key=lambda e: e[0], reverse=True)
    return out


def load_counts() -> dict:
    try:
        with open(COUNTS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def read_rows(today: _dt.date) -> list:
    counts = load_counts().get("mdls", {})
    rows = []
    for slug, name, dock, mdl, intake in PAGES:
        path = slug + ".html"
        if not os.path.exists(path):
            print(f"::warning::{path} missing, row skipped")
            continue
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        mod = date_modified(page)
        if not mod:
            print(f"::warning::{path} has no dateModified, row skipped")
            continue
        status = meta(page, "li:status") or "Claims open"
        nxt = meta(page, "li:next")
        next_date, next_what = "", ""
        if "|" in nxt:
            d, w = nxt.split("|", 1)
            try:
                if _dt.date.fromisoformat(d.strip()) >= today:
                    next_date, next_what = d.strip(), w.strip()
            except ValueError:
                print(f"::warning::{path} li:next has a bad date: {nxt!r}")
        page_mdl = re.search(r'data-mdl="(\d+)"', page)
        mdl = (page_mdl.group(1) if page_mdl else mdl) or ""
        c = counts.get(mdl, {}) if mdl else {}
        rows.append({
            "slug": slug, "name": name, "dock": dock, "mod": mod, "status": status,
            "next_date": next_date, "next_what": next_what,
            "pending": c.get("pending"), "prior": c.get("prior"),
            "entries": dev_entries(page, slug), "line": description(page),
            "intake": intake,
            "closed": bool(CLOSED_WORDS.search(status)),
            "deadline": bool(next_date and URGENT_WORDS.search(next_what)),
            # Pinned: a row with an open reader deadline sits in its own band at the top of the
            # board until the date passes (li:next drops the row's next_date the day after).
            "pinned": bool(next_date and URGENT_WORDS.search(next_what)),
        })
    rows.sort(key=lambda r: r["mod"], reverse=True)
    return rows


# ---------------------------------------------------------------- rendering


def short(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return d.strftime("%b").upper() + " " + str(d.day)


def long_(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return d.strftime("%B") + f" {d.day}, {d.year}"


def tone(row: dict) -> str:
    if (row["next_date"] and URGENT_WORDS.search(row["next_what"] or "")) or URGENT_WORDS.search(row["status"]):
        return "urgent"
    if LIVE_WORDS.search(row["status"]):
        return "live"
    if row["closed"]:
        return "quiet"
    return "watch"


def render_row(row: dict, today: _dt.date) -> str:
    age = (today - _dt.date.fromisoformat(row["mod"])).days
    t = tone(row)
    h = [f'<article class="sb-row" id="{row["slug"]}">']
    h.append(f'<div class="sb-head"><h3 class="sb-name"><a href="/{row["slug"]}">{esc(row["name"])}</a></h3>'
             f'<span class="sb-pill sb-{t}">{esc(row["status"].upper())}</span>')
    if age <= WEEK:
        h.append('<span class="sb-new">NEW</span>')
    h.append(f'<span class="sb-dock">{esc(row["dock"])}</span></div>')
    sub = [f"<span>UPDATED {short(row['mod'])}</span>"]
    if row["pending"] is not None:
        delta = ""
        if row["prior"] is not None and row["prior"] != row["pending"]:
            d = row["pending"] - row["prior"]
            delta = f" ({'+' if d > 0 else ''}{d:,})"
        sub.append(f"<span>{row['pending']:,} FEDERAL CASES PENDING{delta}</span>")
    if row["next_date"]:
        if row["deadline"]:
            sub.append(f'<span class="sb-ev sb-ev-dl">DEADLINE {short(row["next_date"])} · {esc(row["next_what"].upper())}</span>')
        else:
            sub.append(f'<span class="sb-ev">NEXT {short(row["next_date"])} · {esc(row["next_what"].upper())}</span>')
    h.append('<div class="sb-sub">' + "".join(sub) + "</div>")
    entries = row["entries"]
    if entries:
        def li(e):
            iso, kind, lead, anchor = e
            hot = " sb-k-hot" if kind in ("order", "ruling", "settlement", "verdict", "deadline") else ""
            return (f'<li><time class="sb-when" datetime="{iso}">{short(iso)}</time><span class="sb-it">'
                    f'<span class="sb-kind{hot}">{kind.upper()}</span>'
                    f'<a class="sb-ititle" href="{anchor}">{esc(lead)}</a></span></li>')
        h.append('<ul class="sb-items">' + "".join(li(e) for e in entries[:SHOW]) + "</ul>")
        if len(entries) > SHOW:
            n = len(entries) - SHOW
            h.append(f'<details class="sb-more"><summary><span class="sb-caret" aria-hidden="true">&#9656;</span>'
                     f'SHOW {n} MORE ON {esc(row["name"].upper())}</summary><ul class="sb-items">'
                     + "".join(li(e) for e in entries[SHOW:]) + "</ul></details>")
    else:
        h.append(f'<p class="sb-line">{esc(row["line"])}</p>')
    foot = [f'<a href="/{row["slug"]}">Read the full {esc(row["name"])} update</a>']
    if row["intake"] and row["next_date"] and t == "urgent":
        foot.append(f'<a class="sb-cta" href="{cta(row["intake"], "status_" + row["slug"].split("-")[0] + "_row")}" rel="noopener">'
                    f'Ask about a {esc(row["name"])} claim before {esc(long_(row["next_date"]))}</a>')
    h.append('<div class="sb-foot">' + "".join(foot) + "</div></article>")
    return "\n".join(h)


def render_upcoming(rows: list) -> str:
    items = sorted([(r["next_date"], r["name"], r["next_what"], r["slug"]) for r in rows if r["next_date"]])
    if not items:
        return ""
    h, month = [], None
    for iso, name, what, slug in items:
        m = _dt.date.fromisoformat(iso).strftime("%B %Y").upper()
        if m != month:
            if month:
                h.append("</ol>")
            h.append(f'<h3 class="sb-month">{m}</h3><ol class="sb-up">')
            month = m
        dl = bool(URGENT_WORDS.search(what))
        urgent = ' class="sb-up-urgent"' if dl else ""
        tag = '<span class="sb-dl">DEADLINE</span>' if dl else ""
        h.append(f'<li{urgent}><time datetime="{iso}">{short(iso)}</time><span>{tag}<a href="/{slug}">{esc(name)}</a>'
                 f'<span class="sb-upwhat">{esc(what)}</span></span></li>')
    h.append("</ol>")
    return "".join(h)


CSS = r"""
<style id="li-status-board">
/* Status board. One ruled column of rows, newest change first. Scoped under #main so the
   site's content-page rules keep their reading column. */
:root{--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;--sb-urgent:#a2412a;--sb-urgent-bg:#f6e3dc;--sb-live:#3e6b4f;--sb-watch:#9a6d1f;--sb-quiet:#6e6a5e;--sb-panel:#f4f1e8;--sb-mark:#f1ddb4;}
:root[data-theme="dark"]{--sb-urgent:#e07a5f;--sb-urgent-bg:#3a2119;--sb-live:#7db38e;--sb-watch:#d4a04a;--sb-quiet:#9a968a;--sb-panel:#1d1a15;--sb-mark:#4a3b1d;}
#main>.sb-band,#main>.sb-section,#main>.sb-row,#main>.sb-closed,#main>.sb-coming,#main>.sb-powered{max-width:var(--reading);margin-inline:auto;}
#main .sb-band{border:1px solid var(--rule);border-top:3px solid var(--sb-urgent);background:var(--sb-panel);padding:12px 18px;margin-block:28px 8px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;font-family:var(--sans);}
#main .sb-band.quiet{border-top-color:var(--sb-live);}
#main .sb-band-title{font-family:var(--mono);font-size:11px;letter-spacing:.15em;color:var(--ink-strong);}
#main .sb-band-sum{font-size:15px;color:var(--ink-muted);min-width:0;flex:1 1 280px;}
#main .sb-band-sum b{color:var(--ink-strong);font-weight:600;}
#main .sb-band-when{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;color:var(--ink-soft);}
#main .sb-section{font-family:var(--mono);font-size:11px;letter-spacing:.15em;color:var(--ink-soft);margin-block:40px 0;padding-top:0;padding-bottom:8px;border-top:0;border-bottom:1px solid var(--rule);font-weight:500;}
#main .sb-row{padding:18px 0;border-bottom:1px solid var(--rule);font-family:var(--sans);}
#main .sb-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;}
#main .sb-name{font-family:var(--display);font-size:22px;line-height:1.25;margin:0;font-weight:600;min-width:0;}
#main .sb-name a{color:var(--ink-strong);border-bottom:0;}
#main .sb-name a:hover{color:var(--link);}
#main .sb-pill{font-family:var(--mono);font-size:10px;letter-spacing:.11em;padding:2px 7px;border:1px solid currentColor;line-height:1.5;white-space:nowrap;}
#main .sb-urgent{color:var(--sb-urgent);background:var(--sb-urgent-bg);}
#main .sb-live{color:var(--sb-live);}
#main .sb-watch{color:var(--sb-watch);}
#main .sb-quiet{color:var(--sb-quiet);}
#main .sb-new{font-family:var(--mono);font-size:10px;letter-spacing:.11em;padding:2px 7px;background:var(--sb-mark);color:var(--ink-strong);line-height:1.5;}
#main .sb-dock{font-family:var(--mono);font-size:11px;color:var(--ink-soft);margin-left:auto;white-space:nowrap;}
#main .sb-sub{font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--ink-soft);margin-top:6px;display:flex;flex-wrap:wrap;gap:3px 16px;font-variant-numeric:tabular-nums;}
#main .sb-sub .sb-ev{color:var(--ink-strong);}
#main .sb-sub .sb-ev-dl{color:var(--sb-urgent);font-weight:700;}
#main .sb-line{font-family:var(--serif);font-size:17px;line-height:1.55;color:var(--ink);margin:10px 0 0;max-width:68ch;}
#main .sb-items{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:10px;}
#main .sb-items li{display:grid;grid-template-columns:62px minmax(0,1fr);gap:12px;margin:0;}
#main .sb-when{font-family:var(--mono);font-size:11px;color:var(--ink-soft);padding-top:3px;font-variant-numeric:tabular-nums;}
#main .sb-it{min-width:0;font-family:var(--serif);font-size:16.5px;line-height:1.5;}
#main .sb-kind{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:var(--ink-soft);border:1px solid var(--rule);padding:1px 5px;margin-right:8px;vertical-align:2px;white-space:nowrap;}
#main .sb-kind.sb-k-hot{color:var(--sb-urgent);border-color:var(--sb-urgent);}
#main .sb-ititle{color:var(--ink);border-bottom:1px solid var(--rule);}
#main .sb-ititle:hover{color:var(--link);border-bottom-color:var(--link);}
#main .sb-more{margin-top:10px;}
#main .sb-more>summary{list-style:none;cursor:pointer;display:inline-block;font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;color:var(--ink);border:1px solid var(--rule);padding:4px 9px;}
#main .sb-more>summary::-webkit-details-marker{display:none;}
#main .sb-more>summary:hover{border-color:var(--ink);background:var(--sb-mark);}
#main .sb-more>summary:focus-visible{outline:2px solid var(--link);outline-offset:2px;}
#main .sb-caret{display:inline-block;margin-right:6px;transition:transform .15s;}
#main .sb-more[open]>summary .sb-caret{transform:rotate(90deg);}
#main .sb-foot{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;font-size:14.5px;}
#main .sb-cta{background:var(--sb-urgent);color:#fff !important;border:0;padding:7px 14px;font-weight:600;font-size:14px;}
#main .sb-closed{padding:16px 0 4px;font-family:var(--sans);font-size:15px;color:var(--ink-muted);}
#main .sb-closed .names{font-family:var(--mono);font-size:11px;letter-spacing:.06em;margin-top:4px;}
#main .sb-coming{margin-top:12px;}
#main .sb-month{font-family:var(--mono);font-size:11px;letter-spacing:.15em;color:var(--ink-soft);margin:22px 0 6px;font-weight:500;}
#main .sb-up{list-style:none;padding:0;margin:0;border-top:1px solid var(--rule);}
#main .sb-up li{display:grid;grid-template-columns:62px minmax(0,1fr);gap:12px;padding:9px 0;margin:0;border-bottom:1px solid var(--rule);font-family:var(--sans);font-size:15.5px;}
#main .sb-up time{font-family:var(--mono);font-size:11px;color:var(--ink-soft);padding-top:3px;font-variant-numeric:tabular-nums;}
#main .sb-up a{color:var(--ink-strong);font-weight:600;border-bottom:0;margin-right:8px;}
#main .sb-up a:hover{color:var(--link);}
#main .sb-upwhat{color:var(--ink-muted);}
#main .sb-up li.sb-up-urgent time,#main .sb-up li.sb-up-urgent .sb-upwhat{color:var(--sb-urgent);}
#main .sb-up .sb-dl{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;color:var(--sb-urgent);border:1px solid var(--sb-urgent);padding:1px 5px;margin-right:8px;vertical-align:1px;}
#main .sb-powered{font-family:var(--sans);font-size:14px;color:var(--ink-soft);margin-block:18px 0;}
@media (max-width:600px){#main .sb-dock{margin-left:0;width:100%;}#main .sb-name{font-size:20px;}#main .sb-items li,#main .sb-up li{grid-template-columns:52px minmax(0,1fr);gap:10px;}}
@media (prefers-reduced-motion:reduce){#main .sb-caret{transition:none;}}
</style>
"""


def render_main(rows: list, today: _dt.date, stamp: str) -> str:
    open_rows = [r for r in rows if not r["closed"]]
    closed = [r for r in rows if r["closed"]]
    pinned = sorted([r for r in open_rows if r["pinned"]], key=lambda r: r["next_date"])
    week = [r for r in open_rows if (today - _dt.date.fromisoformat(r["mod"])).days <= WEEK]
    earlier = [r for r in open_rows if r not in week and r not in pinned]
    upcoming = sorted([(r["next_date"], r["name"], r["next_what"]) for r in rows if r["next_date"]])
    nxt = upcoming[0] if upcoming else None
    total = len(rows)

    band_sum = (f"<b>{len(week)}</b> of {total} cases changed in the last {WEEK} days."
                if week else f"No case changed in the last {WEEK} days.")
    if nxt:
        band_sum += f" Next court date: <b>{esc(long_(nxt[0]))}</b>, {esc(nxt[2][:1].lower() + nxt[2][1:])} in the {esc(nxt[1])} cases."

    # The hero names the soonest deadline, if one is open, so a reader with that case sees it first.
    deadline = next((u for u in upcoming if URGENT_WORDS.search(u[2])), None)
    hero_lead = (f"<strong>{esc(deadline[1])}: {esc(deadline[2].lower())} on {esc(long_(deadline[0]))}.</strong> "
                 if deadline else "")

    h = [CSS,
         '<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<a href="browse-lawsuits">Browse Lawsuits</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<span aria-current="page">Current Mass Tort Cases</span></nav>',
         "<h1>Current Mass Tort Cases: Where Each One Stands</h1>",
         '<p class="article-byline">By <a href="david-meldofsky">David Meldofsky</a>, California-licensed attorney &middot; Founder, Lawsuit Informer</p>',
         f'<p class="article-date">Last updated: <time datetime="{stamp}">{long_(stamp)}</time></p>',
         "<p>This page lists every case we track, with the newest changes first. Each row shows what happened, when, and the next date the court has set. Each one links to the full update page for that case.</p>",
         f'<div class="sb-band{"" if week else " quiet"}" role="status"><span class="sb-band-title">THIS WEEK</span>'
         f'<span class="sb-band-sum">{band_sum}</span>'
         f'<span class="sb-band-when">BUILT {short(stamp)}, {_dt.date.fromisoformat(stamp).year} FROM {total} UPDATE PAGES</span></div>',
         '<div class="hero-action-strip"><p class="hero-action-prompt">' + hero_lead +
         "If you were hurt by a product on this page, you can ask for a free case review. Whether your history supports a claim depends on your facts. Pick what fits:</p>"
         '<div class="hero-action-buttons">'
         f'<a class="hero-action-btn" href="{cta("case-review", "status_hero_review")}" rel="noopener">Request a free case review</a>'
         f'<a class="hero-action-btn" href="{cta("case-review", "status_hero_unsure")}" rel="noopener">I am not sure which case fits</a>'
         "</div>"
         '<p class="hero-action-note">Free and no obligation. Deadlines are set by your state and usually run from the date of diagnosis. Submitting a review request does not create an attorney-client relationship.</p></div>']
    if pinned:
        h.append('<h2 class="sb-section" id="open-deadlines">OPEN DEADLINES</h2>')
        h += [render_row(r, today) for r in pinned]
    week_rows = [r for r in week if r not in pinned]
    if week_rows:
        h.append(f'<h2 class="sb-section" id="this-week">CHANGED IN THE LAST {WEEK} DAYS</h2>')
        h += [render_row(r, today) for r in week_rows]
    if earlier:
        h.append('<h2 class="sb-section" id="earlier">EARLIER</h2>')
        h += [render_row(r, today) for r in earlier]
    h.append('<div class="inline-cta"><p><strong>Every case on this page has its own filing deadline, set by your state.</strong> '
             "A free review checks your dates against the deadline that applies to you.</p>"
             f'<a class="btn btn-primary" href="{cta("case-review", "status_inline_cta")}" rel="noopener">Check My Filing Deadline</a>'
             '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    if closed:
        names = " &middot; ".join(f'<a href="/{r["slug"]}">{esc(r["name"].upper())}</a> (updated {short(r["mod"])})' for r in closed)
        h.append(f'<div class="sb-closed">Cases that have wound down. These pages explain what happened and what to check now.<div class="names">{names}</div></div>')
    up = render_upcoming(rows)
    if up:
        h.append('<h2 class="sb-section" id="coming-up">COMING UP</h2>')
        h.append(f'<div class="sb-coming">{up}</div>')
    h.append('<div class="cta-box"><h2>Find Out If You May Have a Case</h2>'
             "<p>If a product on this page hurt you or someone in your family, a free case review can look at your records and your diagnosis date. It can tell you which deadlines apply to you.</p>"
             f'<div class="cta-buttons"><a class="btn btn-primary" href="{cta("case-review", "status_ctabox")}" rel="noopener">Get a Free Case Review</a>'
             '<a class="btn btn-secondary" href="browse-lawsuits">Browse All Lawsuits</a></div>'
             '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    return "\n".join(h)


def rows_digest(rows: list, today: _dt.date) -> str:
    """What a reader would see, minus the build date. Equal digests mean nothing changed."""
    sig = json.dumps([{k: v for k, v in r.items()} for r in rows], sort_keys=True, default=str)
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- writing the page


def set_head(shell: str, stamp: str, desc: str) -> str:
    title = f"Current Mass Tort Cases {_dt.date.fromisoformat(stamp).strftime('%B %Y')}: Where Each One Stands"
    shell = re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", shell, count=1, flags=re.S)
    for pat in (r'(<meta\s+name="description"\s+content=")[^"]*(")',
                r'(<meta\s+property="og:description"\s+content=")[^"]*(")',
                r'(<meta\s+name="twitter:description"\s+content=")[^"]*(")'):
        shell = re.sub(pat, lambda m: m.group(1) + esc(desc) + m.group(2), shell, count=1)
    for pat in (r'(<meta\s+property="og:title"\s+content=")[^"]*(")',
                r'(<meta\s+name="twitter:title"\s+content=")[^"]*(")'):
        shell = re.sub(pat, lambda m: m.group(1) + esc(title) + m.group(2), shell, count=1)
    # CollectionPage JSON-LD: name, description and the dates the checkers anchor the stamp to.
    def fix_ld(m):
        block = m.group(0)
        block = re.sub(r'"name":\s*"[^"]*"', '"name": ' + json.dumps(title), block, count=1)
        block = re.sub(r'"description":\s*"[^"]*"', '"description": ' + json.dumps(desc), block, count=1)
        if '"dateModified"' in block:
            block = re.sub(r'"dateModified":\s*"[^"]*"', f'"dateModified": "{stamp}"', block, count=1)
        else:
            block = block.replace('"url":', f'"dateModified": "{stamp}",\n  "url":', 1)
        if '"datePublished"' not in block:
            block = block.replace('"dateModified":', '"datePublished": "2026-06-10",\n  "dateModified":', 1)
        return block
    shell = re.sub(r'<script type="application/ld\+json">\s*\{\s*"@context": "https://schema.org",\s*"@type": "CollectionPage".*?</script>',
                   fix_ld, shell, count=1, flags=re.S)
    shell = re.sub(r'("name":\s*)"Current Mass Tort Cases in 2026"(,\s*"item":\s*"https://lawsuitinformer.com/current-mass-tort-cases")',
                   lambda m: m.group(1) + json.dumps(title) + m.group(2), shell)
    return shell


HOME_CSS = """<style id="li-board-strip">
.hb{padding:28px 0 8px;}
.hb .hb-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:10px;}
.hb .hb-head h2{margin:0;font-size:1.35rem;}
.hb .hb-when{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;font-size:10.5px;letter-spacing:.08em;color:var(--ink-soft);}
.hb .hb-all{margin-left:auto;font-family:var(--sans);font-size:14px;font-weight:600;}
.hb ul{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule);}
.hb li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 16px;padding:11px 0;border-bottom:1px solid var(--rule);align-items:baseline;}
.hb .hb-name{font-family:var(--display);font-weight:600;font-size:17px;color:var(--ink-strong);border-bottom:0;}
.hb .hb-name:hover{color:var(--link);}
.hb .hb-pill{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;font-size:9.5px;letter-spacing:.1em;padding:1px 6px;border:1px solid currentColor;margin-left:8px;white-space:nowrap;vertical-align:2px;}
.hb .hb-urgent{color:#a2412a;}.hb .hb-live{color:#3e6b4f;}.hb .hb-watch{color:#9a6d1f;}.hb .hb-quiet{color:#6e6a5e;}
:root[data-theme="dark"] .hb .hb-urgent{color:#e07a5f;}:root[data-theme="dark"] .hb .hb-live{color:#7db38e;}:root[data-theme="dark"] .hb .hb-watch{color:#d4a04a;}:root[data-theme="dark"] .hb .hb-quiet{color:#9a968a;}
.hb .hb-lead{grid-column:1 / -1;font-family:var(--serif);font-size:15.5px;line-height:1.5;color:var(--ink);margin:0;}
.hb .hb-meta{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;font-size:10.5px;letter-spacing:.05em;color:var(--ink-soft);white-space:nowrap;}
.hb .hb-meta .hb-dl{color:#a2412a;font-weight:700;}:root[data-theme="dark"] .hb .hb-meta .hb-dl{color:#e07a5f;}
@media (max-width:600px){.hb li{grid-template-columns:1fr;}.hb .hb-meta{white-space:normal;}.hb .hb-all{margin-left:0;}}
</style>"""


def render_home(rows: list, today: _dt.date, stamp: str) -> str:
    """The homepage strip: the HOME_ROWS most recently changed open cases."""
    picks = [r for r in rows if not r["closed"]][:HOME_ROWS]
    items = []
    for r in picks:
        lead = r["entries"][0][2] if r["entries"] else r["line"]
        meta_bits = [f"UPDATED {short(r['mod'])}"]
        if r["next_date"]:
            if r["deadline"]:
                meta_bits.append(f'<span class="hb-next hb-dl">DEADLINE {short(r["next_date"])}</span>')
            else:
                meta_bits.append(f'<span class="hb-next">NEXT {short(r["next_date"])}</span>')
        items.append(
            f'<li><span><a class="hb-name" href="{r["slug"]}">{esc(r["name"])}</a>'
            f'<span class="hb-pill hb-{tone(r)}">{esc(r["status"].upper())}</span></span>'
            f'<span class="hb-meta">{" &middot; ".join(meta_bits)}</span>'
            f'<p class="hb-lead">{esc(lead)}</p></li>')
    return (f"{HOME_BEGIN}\n{HOME_CSS}\n"
            '<section class="section hb"><div class="container narrow">'
            f'<div class="hb-head"><h2>Latest in Court</h2><span class="hb-when">AS OF {short(stamp)}, {_dt.date.fromisoformat(stamp).year}</span>'
            f'<a class="hb-all" href="current-mass-tort-cases">All {len(rows)} cases we track &rarr;</a></div>'
            "<ul>" + "".join(items) + "</ul></div></section>\n" + HOME_END)


def write_home(rows: list, today: _dt.date, stamp: str, dry_run: bool) -> bool:
    """Put the strip into index.html. Returns True when the file was written."""
    if not os.path.exists(HOME):
        print(f"::warning::{HOME} not found, homepage strip skipped")
        return False
    with open(HOME, encoding="utf-8") as fh:
        home = fh.read()
    block = render_home(rows, today, stamp)
    if HOME_BEGIN in home and HOME_END in home:
        start, end = home.index(HOME_BEGIN), home.index(HOME_END) + len(HOME_END)
        new = home[:start] + block + home[end:]
    elif HOME_ANCHOR in home:
        new = home.replace(HOME_ANCHOR, HOME_ANCHOR + "\n\n" + block + "\n", 1)
    else:
        print(f"::warning::{HOME} has neither the LI-BOARD markers nor the credibility-strip anchor, strip skipped")
        return False
    if new == home:
        print("homepage strip unchanged")
        return False
    if dry_run:
        print("homepage strip would change")
        return False
    with open(HOME, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"wrote {HOME} (homepage strip)")
    return True


# The board line opens "This case is one of N"; a page that covers many suits gets its own subject.
LINK_SUBJECT = {"openai-lawsuits": "The OpenAI cases are"}


def render_page_link(count: int, slug: str = "") -> str:
    # Sits under the stamp and reads as part of it: same class, pulled up toward the stamp.
    subject = LINK_SUBJECT.get(slug, "This case is")
    return (f'{LINK_BEGIN}\n'
            f'  <p class="article-date board-link" style="margin-top:-16px">{subject} one of {count} we track. '
            f'<a href="current-mass-tort-cases">See where each one stands &rarr;</a></p>\n'
            f'  {LINK_END}')


def write_page_links(count: int, dry_run: bool) -> list:
    """Put the board line on every update page. Returns the files written (or that would be)."""
    written = []
    for slug, *_ in PAGES:
        block = render_page_link(count, slug)
        path = f"{slug}.html"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        if LINK_BEGIN in page and LINK_END in page:
            start = page.index(LINK_BEGIN)
            # One line per page. A page uploaded from a copy that already carried the line can
            # arrive with two blocks; every extra block goes, with the blank line before it, and
            # the first one is rewritten in place.
            extra = re.compile(r"\n*[ \t]*" + re.escape(LINK_BEGIN) + r".*?" + re.escape(LINK_END), re.S)
            first_end = page.index(LINK_END, start) + len(LINK_END)
            rest = extra.sub("", page[first_end:])
            new = page[:start] + block + rest
        else:
            m = LINK_ANCHOR.search(page)
            if not m:
                print(f"::warning::{path} has no <p class=\"article-date\">, board line skipped")
                continue
            new = page[:m.end()] + "\n\n  " + block + page[m.end():]
        if new == page:
            continue
        written.append(path)
        if not dry_run:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    verb = "would get" if dry_run else "got"
    print(f"board line: {len(written)} update page(s) {verb} it" + (": " + ", ".join(written) if written else ""))
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="write even when the rows did not change")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for tests")
    args = ap.parse_args()
    today = _dt.date.fromisoformat(args.today) if args.today else _dt.date.today()

    if not os.path.exists(OUT):
        sys.exit(f"{OUT} not found; the generator rewrites the existing page's <main>")
    with open(OUT, encoding="utf-8") as fh:
        shell = fh.read()
    m = re.search(r"<!-- board:rows:([0-9a-f]{16}):(\d{4}-\d{2}-\d{2}) -->", shell)
    old_digest, old_stamp = (m.group(1), m.group(2)) if m else ("", "")

    rows = read_rows(today)
    if not rows:
        sys.exit("no rows read; nothing written")
    digest = rows_digest(rows, today)
    changed = digest != old_digest
    stamp = today.isoformat() if (changed or not old_stamp) else old_stamp

    week = sum(1 for r in rows if not r["closed"] and (today - _dt.date.fromisoformat(r["mod"])).days <= WEEK)
    desc = (f"Where every mass tort we track stands as of {long_(stamp)}: {week} changed this week, "
            f"with the latest court dates, case counts and deadlines on one page.")
    main_html = f'<main id="main" class="content-page">\n<!-- board:rows:{digest}:{stamp} -->\n' + render_main(rows, today, stamp) + "\n</main>"
    out = re.sub(r'<main id="main" class="content-page">.*?</main>', lambda _: main_html, shell, count=1, flags=re.S)
    out = set_head(out, stamp, desc)
    out = re.sub(r"(<strong>Last Updated:</strong>\s*)(?:<time[^>]*>[^<]*</time>|[A-Z][a-z]+ \d{1,2}, \d{4})",
                 lambda mm: mm.group(1) + f'<time datetime="{stamp}">{long_(stamp)}</time>', out, count=1)

    print(f"{len(rows)} rows, {week} changed in the last {WEEK} days, rows digest {digest}"
          + (" (changed)" if changed else " (unchanged)"))
    if args.dry_run:
        for r in rows:
            print(f"  {r['mod']}  {r['name']:<28} {r['status']:<22} entries {len(r['entries']):>2}  next {r['next_date'] or '-'}")
        write_home(rows, today, stamp, dry_run=True)
        write_page_links(len(rows), dry_run=True)
        return 0
    if not changed and not args.force:
        print("rows unchanged; file left alone")
    else:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"wrote {OUT}, stamp {stamp}")
    # The strip follows the board's stamp, so the two never disagree about the date.
    write_home(rows, today, stamp, dry_run=False)
    write_page_links(len(rows), dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
