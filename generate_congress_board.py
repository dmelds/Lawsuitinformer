#!/usr/bin/env python3
"""
Generate mass-tort-bills-in-congress.html, the Congress board, from Hill Wire.

The board is the status board's sibling for Congress. One row per bill Hill Wire
watches that touches a case this site covers, grouped by case, with where the
bill stands, the last thing Congress did with it, and one plain-language line on
what it would do for people in that case.

Two inputs:

  data/congress_bills.json   Hill Wire's watch list, saved from its /api/state.
                             `--fetch` refreshes it when HILL_KEY is set (the
                             workflow does this), and rewrites the file only when
                             a bill's stage, moves or text hits changed, so a quiet
                             poll commits nothing. Without the key, or when Hill
                             Wire cannot be reached, the saved file is used as is.
  data/congress_lines.txt    The reader-facing words, kept by hand:
                               [cases]   topic|case name as the board shows it
                               [bills]   bill id|name on the board|what the bill
                                         would do, plain (empty name = Hill Wire's label)
                               [riders]  phrase|why that phrase matters, plain
                             A bill shows only when it has a [bills] line here.
                             Hill Wire's own notes are desk notes, written for
                             the desk, so they never reach this page.

Which bills show: Hill Wire topic is not "-", one of the bill's pages is on
lawsuitinformer.com, and data/congress_lines.txt has a line for it. A watched
bill that passes the first two tests and has no line is printed as a warning
and left off. Bills whose only page is on Intelligencer (the ByHeart formula
bills, the qui tam bill) never show here; Intelligencer's board carries them.

What a row shows, all from the saved state:
  stage       Hill Wire's stage, renamed for readers (Reported -> Cleared committee)
  last move   the newest action that changes where the bill stands, by the same
              rule network-ops hill_review.py uses (passage, committee approval,
              calendar, cloture, sent to or signed by the President, an amendment
              adopted or rejected). Referrals and floor procedure never count.
  track       six steps from Filed to Law, for bills (amendments get a pill only)

Bills from a Congress that has ended are shown as expired, never as still in
committee: every bill dies when its Congress ends (the 119th ends January 3,
2027) and comes back, if at all, with a new number.

The page shell (head, header, footer, dark mode, scripts) is the existing page
on disk, as with the status board. On the first run, when the page does not
exist yet, the shell is copied from current-mass-tort-cases.html with the URL,
title and breadcrumb swapped and the status board's signup box left out. Only the
<main> block, the <title>, the descriptions and the JSON-LD dates are rewritten
after that, so the site's sweeps keep working on this file like any other.

The page is written only when the rows changed, and then dateModified and the
visible stamp move to today. A day with no change leaves it untouched.

The same run keeps two links to the board in step, the way generate_status_board.py
does for the status board:
  index.html     a "Latest in Congress" strip, the five bills that moved most
                 recently, between <!-- LI-CONGRESS:BEGIN --> and END. It goes right
                 after the status board's strip (<!-- LI-BOARD:END -->), or after the
                 credibility strip when that strip is missing. It reuses that strip's
                 styles inside a tinted panel (HOME_CSS) so the two read as separate.
  case pages     every lawsuitinformer.com page a bill on the board names gets one line
                 under its stamp: "Congress is weighing N bills tied to this case",
                 linked to that case on the board. It sits after the status board's
                 line when the page has one, between <!-- LI-CONGRESS-LINK:BEGIN -->
                 and END. A page whose bills all expire loses the line.
Each file is written only when its block changed. The case-page line is navigation,
so the workflow commits those pages with [skip lastmod].

    python3 generate_congress_board.py --fetch       # refresh the data, then build
    python3 generate_congress_board.py               # build from the saved data
    python3 generate_congress_board.py --dry-run     # print the rows, write nothing
    python3 generate_congress_board.py --force       # write even if unchanged
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
import urllib.error
import urllib.request

SITE = "https://lawsuitinformer.com"
SLUG = "mass-tort-bills-in-congress"
OUT = SLUG + ".html"
SHELL_FROM = "current-mass-tort-cases.html"
DATA = os.path.join("data", "congress_bills.json")
LINES = os.path.join("data", "congress_lines.txt")
HILL_URL = (os.environ.get("HILL_URL") or "https://hill.masstortwire.com").rstrip("/")
UA = "lawsuitinformer congress board (+https://lawsuitinformer.com)"
TITLE = "Mass Tort Bills in Congress: Where Each One Stands"
H1 = "Bills in Congress That Could Change Mass Tort Cases"
RECENT_DAYS = 30        # the "moved in the last 30 days" count in the band
LATEST_MOVES = 8        # rows in LATEST MOVES
MOVES_KEPT = 10         # per bill, in the saved data
MOVES_SINCE = 120       # days: older moves stay off LATEST MOVES
CAMPAIGN = "congress_board"

# The day each Congress ends. Bills from a Congress past its end date are expired.
CONGRESS_ENDS = {119: "2027-01-03", 120: "2029-01-03"}

# Same expressions as network-ops scripts/hill_review.py (and Hill Wire's page for
# PROCEDURAL). Change all of them together.
# NOT_A_MOVE leaves out motions to recommit: their "Failed" is a vote on sending the bill
# back to committee, so a reader would take it for the bill itself failing.
PROCEDURAL = re.compile(
    r"^(debate|postponed proceedings|considered (as unfinished business|under suspension|by unanimous consent)|"
    r"the house (rose|resolved|adopted the amendments en gros)|committee of the whole|the previous question|"
    r"motion to reconsider laid on the table|the clerk was authorized|at the conclusion of debate|"
    r"on motion that the committee rise|pursuant to the provisions)|"
    r"moved (to recommit|that the committee rise|to suspend the rules)|rises leaving|"
    r"motion to proceed to consideration of measure (made|withdrawn)|"
    r"cloture motion on the motion to proceed .*presented|motion by senator .* to reconsider the vote|"
    r"^mr\.|^ms\.|^mrs\.", re.I)
KEY_MOVE = re.compile(
    r"became public law|signed by (the )?president|presented to (the )?president|vetoed|"
    r"\bpassed\b|\bfailed\b|agreed to|withdrawn|\breported\b|placed on .*calendar|"
    r"cloture .*(invoked|not invoked)|conference report|resolving differences", re.I)
NOT_A_MOVE = re.compile(
    r"^referred to|^introduced in|^read twice and referred|^received in the|supplemental report|"
    r"motion to reconsider|^(on )?motion to recommit|motion to proceed to consideration of measure|mark-?up session held", re.I)

TYPE_LABEL = {"hr": "H.R.", "s": "S.", "hjres": "H.J.Res.", "sjres": "S.J.Res.",
              "hconres": "H.Con.Res.", "sconres": "S.Con.Res.", "hres": "H.Res.",
              "sres": "S.Res.", "samdt": "S.Amdt.", "hamdt": "H.Amdt.", "suamdt": "S.Up.Amdt."}

# Hill Wire stage -> (reader label, step on the six-step track, pill tone)
STAGES = {
    "Introduced": ("Filed", 1, "quiet"),
    "In committee": ("In committee", 2, "quiet"),
    "Reported": ("Cleared committee", 3, "watch"),
    "Passed House": ("Passed the House", 4, "watch"),
    "Passed Senate": ("Passed the Senate", 4, "watch"),
    "Passed both": ("Passed Congress", 5, "live"),
    "To President": ("Sent to the President", 5, "live"),
    "Law": ("Law", 6, "live"),
}
AMDT_STAGES = {
    "Filed": ("Filed, no vote yet", 0, "quiet"),
    "Submitted": ("Filed, no vote yet", 0, "quiet"),
    "Proposed": ("Offered on the floor", 0, "watch"),
    "Agreed to": ("Adopted", 0, "live"),
    "Not agreed to": ("Voted down", 0, "quiet"),
    "Withdrawn": ("Withdrawn", 0, "quiet"),
}
TRACK = ["Filed", "Committee", "Cleared committee", "One chamber", "Both chambers", "Law"]


def warn(msg: str) -> None:
    print(f"::warning::{msg}")


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def is_amdt(t: str) -> bool:
    return (t or "").endswith("amdt")


def id_text(b: dict) -> str:
    return f"{TYPE_LABEL.get(b.get('type', ''), (b.get('type') or '').upper())} {b.get('number', '')}".strip()


def to_date(s):
    try:
        return _dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def short(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return d.strftime("%b").upper() + " " + str(d.day) + ", " + str(d.year)


def long_(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return d.strftime("%B") + f" {d.day}, {d.year}"


# ---------------------------------------------------------------- the data file


def is_move(text: str) -> bool:
    t = (text or "").strip()
    if not t or PROCEDURAL.search(t) or NOT_A_MOVE.search(t):
        return False
    return bool(KEY_MOVE.search(t))


def moves_of(actions: list) -> list:
    """Key moves, newest first, a same-day line folded into the longer line that repeats it."""
    acts = [a for a in actions or [] if is_move(a.get("text"))]
    keep = []
    for a in acts:
        if any(o is not a and o.get("date") == a.get("date") and len(o["text"]) > len(a["text"])
               and a["text"] in o["text"] for o in acts):
            continue
        keep.append({"date": (a.get("date") or "")[:10], "text": a["text"].strip()})
    keep.sort(key=lambda a: a["date"], reverse=True)
    return keep[:MOVES_KEPT]


def trim_state(state: dict) -> dict:
    """The parts of Hill Wire's state the boards read, with poll times left out so a quiet poll
    produces the same file."""
    bills = {}
    for key, b in (state.get("bills") or {}).items():
        bid = b.get("id") or key
        latest = b.get("latest") or {}
        bills[bid] = {
            "id": bid, "congress": b.get("congress"), "type": b.get("type"), "number": str(b.get("number") or ""),
            "label": b.get("label") or "", "title": b.get("title") or "", "topic": b.get("topic") or "-",
            "pages": b.get("pages") or [], "url": b.get("url") or "", "introduced": (b.get("introduced") or "")[:10],
            "stage": b.get("stage") or "",
            "latest": {"date": (latest.get("date") or "")[:10], "text": (latest.get("text") or "").strip()},
            "moves": moves_of(b.get("actions")),
            "amended_bill": ({"label": id_text(b["amendedBill"]), "url": b["amendedBill"].get("url", ""),
                              "title": b["amendedBill"].get("title", "")}
                             if b.get("amendedBill") else None),
        }
    hits = []
    for h in (state.get("hits") or {}).values():
        bill = h.get("bill") or {}
        hits.append({
            "phrase": h.get("phrase") or "", "topic": h.get("topic") or "-", "pages": h.get("pages") or [],
            "bill": id_text(bill), "bill_id": bill.get("id") or "", "bill_url": bill.get("url") or "",
            "label": h.get("title") or "", "link": h.get("link") or "", "removed": bool(h.get("removed")),
            "version_date": (h.get("versionDate") or "")[:10], "version_type": h.get("versionType") or "",
            "first_seen": (h.get("firstSeen") or "")[:10],
        })
    hits.sort(key=lambda x: (x["bill_id"], x["phrase"], x["removed"]))
    return {"source": HILL_URL + "/api/state", "bills": dict(sorted(bills.items())), "hits": hits}


def fetch(dry_run: bool) -> None:
    key = (os.environ.get("HILL_KEY") or "").strip()
    if not key:
        warn("HILL_KEY is not set; building from the saved data/congress_bills.json")
        return
    req = urllib.request.Request(HILL_URL + "/api/state", headers={"X-Wire-Key": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            state = (json.loads(r.read().decode("utf-8")) or {}).get("state")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            warn("Hill Wire refused HILL_KEY (401). It must equal the WIRE_KEY on the hill-wire Netlify project. "
                 "Building from the saved data.")
        else:
            warn(f"Hill Wire answered HTTP {e.code}; building from the saved data")
        return
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        warn(f"Hill Wire could not be read ({e}); building from the saved data")
        return
    if not state or not state.get("bills"):
        warn("Hill Wire has no saved state yet; building from the saved data")
        return
    run = state.get("lastRun") or {}
    print(f"Hill Wire last polled {run.get('at', '?')}: {run.get('billCount', '?')} bills, ok={run.get('ok')}")
    new = trim_state(state)
    old = None
    if os.path.exists(DATA):
        try:
            with open(DATA, encoding="utf-8") as fh:
                old = json.load(fh)
        except ValueError:
            old = None
    if old == new:
        print(f"{DATA} unchanged")
        return
    if dry_run:
        print(f"{DATA} would change")
        return
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {DATA}")


# ---------------------------------------------------------------- reader lines


def load_lines() -> dict:
    out = {"cases": {}, "bills": {}, "riders": {}}
    if not os.path.exists(LINES):
        sys.exit(f"{LINES} not found")
    section = None
    with open(LINES, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\[(cases|bills|riders)\]$", line, re.I)
            if m:
                section = m.group(1).lower()
                continue
            if not section or "|" not in line:
                continue
            if section == "bills":
                parts = [p.strip() for p in line.split("|", 2)]
                if len(parts) == 3 and parts[0] and parts[2]:
                    out["bills"][parts[0]] = (parts[1], parts[2])
                else:
                    warn(f"{LINES}: [bills] line needs id|name|line: {line[:60]!r}")
                continue
            k, v = (p.strip() for p in line.split("|", 1))
            if k and v:
                out[section][k.lower()] = v
    return out


# ---------------------------------------------------------------- rows


def informer_pages(pages: list) -> list:
    return [p for p in pages or [] if p.startswith(SITE + "/")]


def rel(url: str) -> str:
    return url[len(SITE) + 1:] if url.startswith(SITE + "/") else url


VOTE = re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})")


def plain_move(text: str, bill_type: str) -> str:
    """One Congress.gov action in reader words."""
    t = text or ""
    low = t.lower()
    v = VOTE.search(t)
    votes = f", {v.group(1)} to {v.group(2)}" if v else ""
    house = bill_type.startswith("h")
    if re.search(r"became public law|signed by (the )?president", low):
        return "Signed into law"
    if "vetoed" in low:
        return "Vetoed by the President"
    if re.search(r"presented to (the )?president", low):
        return "Sent to the President"
    if re.search(r"conference report|resolving differences", low):
        return "House and Senate worked on one shared version"
    if is_amdt(bill_type):
        if "not agreed to" in low:
            return "Voted down" + votes
        if "withdrawn" in low:
            return "Withdrawn"
        if "agreed to" in low:
            return "Adopted" + votes
    if re.search(r"cloture .*not invoked", low):
        return "A Senate vote to start debate failed" + votes
    if re.search(r"cloture .*invoked", low):
        return "The Senate voted to start debate" + votes
    if re.search(r"passed (the )?house|passed/agreed to in house|agreed to in house|on passage passed", low):
        return "Passed the House" + votes
    if re.search(r"passed (the )?senate|passed/agreed to in senate", low):
        return "Passed the Senate" + (" with no objection" if "unanimous consent" in low else votes)
    if "rules committee resolution" in low:
        return "House leaders set the terms for a House vote"
    if re.search(r"placed on senate legislative calendar", low):
        return "Cleared committee and waits for a Senate vote"
    if re.search(r"placed on the (union|house) calendar", low):
        return "Cleared committee and waits for a House vote"
    if re.search(r"ordered to be reported|reported by|reported with|reported without|\breported\b", low):
        return f"Approved by a {'House' if house else 'Senate'} committee" + votes
    if re.search(r"\bfailed\b", low):
        return "Failed in a vote" + votes
    first = re.split(r"(?<=[a-z])\.\s", t, maxsplit=1)[0].rstrip(".")
    return first[:140]


def bill_stage(b: dict, today: _dt.date):
    """(label, step, tone, expired)."""
    amdt = is_amdt(b.get("type"))
    table = AMDT_STAGES if amdt else STAGES
    label, step, tone = table.get(b.get("stage") or "", ("Filed" if not amdt else "Filed, no vote yet", 1 if not amdt else 0, "quiet"))
    end = CONGRESS_ENDS.get(int(b.get("congress") or 0))
    if end and today >= _dt.date.fromisoformat(end) and b.get("stage") != "Law":
        return ("Expired", step, "quiet", True)
    return (label, step, tone, False)


def read_rows(today: _dt.date) -> tuple:
    if not os.path.exists(DATA):
        sys.exit(f"{DATA} not found; run with --fetch and HILL_KEY set first")
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    lines = load_lines()
    rows, missing = [], []
    for bid, b in (data.get("bills") or {}).items():
        topic = (b.get("topic") or "-").strip()
        ipages = informer_pages(b.get("pages"))
        if topic == "-" or not ipages:
            continue
        name, line = lines["bills"].get(bid, ("", ""))
        case = lines["cases"].get(topic.lower())
        if not line or not case:
            missing.append(f"{bid} ({b.get('label')})" + ("" if case else f", no [cases] name for topic {topic!r}"))
            continue
        label, step, tone, expired = bill_stage(b, today)
        moves = [m for m in (b.get("moves") or []) if is_move(m.get("text"))]
        last = moves[0] if moves else None
        rows.append({
            "id": bid, "bill": id_text(b), "type": b.get("type") or "", "label": name or b.get("label") or b.get("title") or bid,
            "url": b.get("url") or "", "topic": topic, "case": case, "page": rel(ipages[0]),
            "ipages": [rel(p) for p in ipages],
            "introduced": b.get("introduced") or "", "stage": label, "step": step, "tone": tone, "expired": expired,
            "amdt": is_amdt(b.get("type")), "line": line,
            "amended": (b.get("amended_bill") or {}).get("label", ""),
            "last_date": last["date"] if last else "", "last": plain_move(last["text"], b.get("type") or "") if last else "",
            "moves": [(m["date"], plain_move(m["text"], b.get("type") or "")) for m in moves],
        })
    for m in missing:
        warn(f"no reader line in {LINES} for {m}; left off the board")
    riders = []
    for h in data.get("hits") or []:
        ipages = informer_pages(h.get("pages"))
        why = lines["riders"].get((h.get("phrase") or "").lower())
        if (h.get("topic") or "-") == "-" or not ipages:
            continue
        if not why:
            warn(f"no [riders] line in {LINES} for {h.get('phrase')!r}; hit left off the board")
            continue
        case = lines["cases"].get((h.get("topic") or "").lower(), "")
        name = lines["bills"].get(h.get("bill_id") or "", ("", ""))[0]
        riders.append({**h, "label": name or h.get("label") or h.get("bill"), "why": why,
                       "page": rel(ipages[0]), "case": case})
    riders.sort(key=lambda r: (r.get("first_seen") or r.get("version_date") or ""), reverse=True)
    return rows, riders


# ---------------------------------------------------------------- rendering


def cta(slot: str) -> str:
    return (f"https://lawsuit.center/case-review?utm_source=lawsuitinformer&amp;utm_medium=referral"
            f"&amp;utm_campaign={CAMPAIGN}&amp;utm_content={slot}")


CSS = r"""
<style id="li-congress-board">
/* Congress board. Same ruled column as the status board, one row per bill, grouped by case. */
:root{--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;--cb-live:#3e6b4f;--cb-watch:#9a6d1f;--cb-quiet:#6e6a5e;--cb-panel:#f4f1e8;--cb-mark:#f1ddb4;--cb-on:#9a6d1f;}
:root[data-theme="dark"]{--cb-live:#7db38e;--cb-watch:#d4a04a;--cb-quiet:#9a968a;--cb-panel:#1d1a15;--cb-mark:#4a3b1d;--cb-on:#d4a04a;}
#main>.cb-band,#main>.cb-section,#main>.cb-case,#main>.cb-row,#main>.cb-moves,#main>.cb-note{max-width:var(--reading);margin-inline:auto;}
#main .cb-band{border:1px solid var(--rule);border-top:3px solid var(--cb-watch);background:var(--cb-panel);padding:12px 18px;margin-block:28px 8px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;font-family:var(--sans);}
#main .cb-band.quiet{border-top-color:var(--cb-live);}
#main .cb-band-title{font-family:var(--mono);font-size:11px;letter-spacing:.15em;color:var(--ink-strong);}
#main .cb-band-sum{font-size:15px;color:var(--ink-muted);min-width:0;flex:1 1 280px;}
#main .cb-band-sum b{color:var(--ink-strong);font-weight:600;}
#main .cb-band-when{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;color:var(--ink-soft);}
#main .cb-section{font-family:var(--mono);font-size:11px;letter-spacing:.15em;color:var(--ink-soft);margin-block:40px 0;padding:0 0 8px;border-top:0;border-bottom:1px solid var(--rule);font-weight:500;}
#main .cb-case{font-family:var(--display);font-size:24px;line-height:1.25;margin:40px auto 0;padding:0 0 8px;border-top:0;border-bottom:2px solid var(--ink-strong);display:flex;flex-wrap:wrap;gap:4px 14px;align-items:baseline;}
#main .cb-case a{color:var(--ink-strong);border-bottom:0;}
#main .cb-case a:hover{color:var(--link);}
#main .cb-case .cb-count{font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--ink-soft);font-weight:400;margin-left:auto;}
#main .cb-row{padding:16px 0;border-bottom:1px solid var(--rule);font-family:var(--sans);}
#main .cb-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;}
#main .cb-name{font-family:var(--display);font-size:19px;line-height:1.3;margin:0;font-weight:600;min-width:0;color:var(--ink-strong);}
#main .cb-pill{font-family:var(--mono);font-size:10px;letter-spacing:.11em;padding:2px 7px;border:1px solid currentColor;line-height:1.5;white-space:nowrap;}
#main .cb-live{color:var(--cb-live);}
#main .cb-watch{color:var(--cb-watch);}
#main .cb-quiet{color:var(--cb-quiet);}
#main .cb-new{font-family:var(--mono);font-size:10px;letter-spacing:.11em;padding:2px 7px;background:var(--cb-mark);color:var(--ink-strong);line-height:1.5;}
#main .cb-num{font-family:var(--mono);font-size:11px;color:var(--ink-soft);margin-left:auto;white-space:nowrap;}
#main .cb-track{list-style:none;display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:3px;margin:10px 0 0;padding:0;max-width:440px;}
#main .cb-track li{margin:0;height:6px;background:var(--rule);}
#main .cb-track li.on{background:var(--cb-on);}
#main .cb-track.law li.on{background:var(--cb-live);}
#main .cb-steps{font-family:var(--mono);font-size:10px;letter-spacing:.06em;color:var(--ink-soft);margin-top:4px;}
#main .cb-line{font-family:var(--serif);font-size:17px;line-height:1.55;color:var(--ink);margin:10px 0 0;max-width:68ch;}
#main .cb-last{font-family:var(--sans);font-size:15px;line-height:1.5;color:var(--ink-muted);margin:8px 0 0;}
#main .cb-last time{font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--ink-soft);margin-right:8px;}
#main .cb-foot{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14.5px;}
#main .cb-moves{list-style:none;padding:0;margin:12px auto 0;border-top:1px solid var(--rule);}
#main .cb-moves li{display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;padding:9px 0;margin:0;border-bottom:1px solid var(--rule);font-family:var(--sans);font-size:15.5px;}
#main .cb-moves time{font-family:var(--mono);font-size:11px;color:var(--ink-soft);padding-top:3px;font-variant-numeric:tabular-nums;}
#main .cb-moves a{color:var(--ink-strong);font-weight:600;border-bottom:0;margin-right:8px;}
#main .cb-moves a:hover{color:var(--link);}
#main .cb-what{color:var(--ink-muted);}
#main .cb-tag{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink-soft);margin-left:8px;}
#main .cb-note{font-family:var(--sans);font-size:14px;color:var(--ink-soft);margin-block:18px 0;}
@media (max-width:600px){#main .cb-num{margin-left:0;width:100%;}#main .cb-case{font-size:21px;}#main .cb-case .cb-count{margin-left:0;width:100%;}#main .cb-moves li{grid-template-columns:1fr;gap:2px;}}
</style>
"""


def render_row(r: dict, today: _dt.date) -> str:
    h = [f'<article class="cb-row" id="{esc(r["id"])}">']
    h.append(f'<div class="cb-head"><h3 class="cb-name">{esc(r["label"])}</h3>'
             f'<span class="cb-pill cb-{r["tone"]}">{esc(r["stage"].upper())}</span>')
    if r["last_date"] and (today - _dt.date.fromisoformat(r["last_date"])).days <= RECENT_DAYS:
        h.append('<span class="cb-new">MOVED</span>')
    num = r["bill"] + (f" · ON {r['amended']}" if r["amended"] else "")
    h.append(f'<span class="cb-num">{esc(num)}</span></div>')
    if not r["amdt"] and not r["expired"]:
        law = " law" if r["step"] >= 6 else ""
        dots = "".join(f'<li class="on"></li>' if i < r["step"] else "<li></li>" for i in range(len(TRACK)))
        h.append(f'<ol class="cb-track{law}" aria-label="Step {r["step"]} of {len(TRACK)}: {esc(r["stage"])}">{dots}</ol>'
                 f'<div class="cb-steps" aria-hidden="true">STEP {r["step"]} OF {len(TRACK)} · {esc(TRACK[r["step"] - 1].upper())}</div>')
    h.append(f'<p class="cb-line">{esc(r["line"])}</p>')
    if r["expired"]:
        last = "This bill expired when its Congress ended. A new version would need a new number."
        h.append(f'<p class="cb-last">{esc(last)}</p>')
    elif r["last_date"]:
        h.append(f'<p class="cb-last"><time datetime="{r["last_date"]}">{short(r["last_date"])}</time>{esc(r["last"])}.</p>')
    elif r["introduced"]:
        what = "Filed. No vote yet." if not r["amdt"] else "Filed. The Senate has not voted on it." if r["type"].startswith("s") else "Filed. The House has not voted on it."
        h.append(f'<p class="cb-last"><time datetime="{r["introduced"]}">{short(r["introduced"])}</time>{esc(what)}</p>')
    h.append(f'<div class="cb-foot"><a href="/{esc(r["page"])}">Read more about {esc(r["case"])}</a>'
             f'<a href="{esc(r["url"])}" rel="noopener" target="_blank">{esc(r["bill"])} on Congress.gov</a></div></article>')
    return "\n".join(h)


def latest_moves(rows: list, today: _dt.date) -> list:
    out = []
    floor = today - _dt.timedelta(days=MOVES_SINCE)
    for r in rows:
        for d, what in r["moves"]:
            dd = to_date(d)
            if dd and floor <= dd <= today:
                out.append((d, r, what))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:LATEST_MOVES]


def render_rider(h: dict) -> str:
    when = h.get("version_date") or h.get("first_seen") or ""
    verb = "no longer includes" if h["removed"] else "includes"
    which = h.get("label") or h.get("bill") or "the bill"
    t = f'<time datetime="{when}">{short(when)}</time>' if when else "<time></time>"
    return (f"<li>{t}<span><a href=\"{esc(h.get('link') or h.get('bill_url'))}\" rel=\"noopener\" target=\"_blank\">{esc(which)}</a>"
            f"<span class=\"cb-what\">The newest text {verb} the words &ldquo;{esc(h['phrase'])}.&rdquo; {esc(h['why'])} "
            f"<a href=\"/{esc(h['page'])}\">Read more about {esc(h['case'] or 'this case')}</a></span></span></li>")


def render_main(rows: list, riders: list, today: _dt.date, stamp: str) -> str:
    live = [r for r in rows if not r["expired"]]
    expired = [r for r in rows if r["expired"]]
    recent = [r for r in live if r["last_date"] and (today - _dt.date.fromisoformat(r["last_date"])).days <= RECENT_DAYS]
    furthest = max(live, key=lambda r: (r["step"], r["last_date"]), default=None)
    cases = {}
    for r in rows:
        cases.setdefault(r["case"], []).append(r)
    total = len(rows)

    band = (f"<b>{len(recent)}</b> of {total} bills moved in the last {RECENT_DAYS} days."
            if recent else f"None of the {total} bills moved in the last {RECENT_DAYS} days.")
    if furthest and furthest["step"] >= 3:
        st = furthest["stage"]
        band += f" Furthest along: <b>{esc(furthest['label'])}</b>, {esc(st[:1].lower() + st[1:])}."

    h = [CSS,
         '<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<a href="browse-lawsuits">Browse Lawsuits</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<span aria-current="page">Bills in Congress</span></nav>',
         f"<h1>{esc(H1)}</h1>",
         '<p class="article-byline">By <a href="david-meldofsky">David Meldofsky</a>, California-licensed attorney &middot; Founder, Lawsuit Informer</p>',
         f'<p class="article-date">Last updated: <time datetime="{stamp}">{long_(stamp)}</time></p>',
         "<p>Congress is weighing bills that could change some of the cases we cover. Some would make it easier for injured people to sue. Others would shield companies from lawsuits. "
         "This page lists each bill we follow, grouped by case, and shows how far it has gotten.</p>",
         "<p>A bill becomes law only after both the House and the Senate pass it and the President signs it. Most bills stop in committee. "
         'For where each case stands in court, see <a href="current-mass-tort-cases">the status board</a>.</p>',
         f'<div class="cb-band{"" if recent else " quiet"}" role="status"><span class="cb-band-title">IN CONGRESS</span>'
         f'<span class="cb-band-sum">{band}</span>'
         f'<span class="cb-band-when">BUILT {short(stamp)} FROM CONGRESS.GOV</span></div>',
         '<div class="hero-action-strip"><p class="hero-action-prompt">'
         "A bill can take years to pass, and the deadline to file a lawsuit keeps running in the meantime. "
         "If you were hurt by a product on this page, a free case review can check your dates. Pick what fits:</p>"
         '<div class="hero-action-buttons">'
         f'<a class="hero-action-btn" href="{cta("congress_hero_review")}" rel="noopener">Request a free case review</a>'
         f'<a class="hero-action-btn" href="{cta("congress_hero_unsure")}" rel="noopener">I am not sure which case fits</a>'
         "</div>"
         '<p class="hero-action-note">Free and no obligation. Whether your history supports a claim depends on your facts. Submitting a review request does not create an attorney-client relationship.</p></div>']

    moves = latest_moves(rows, today)
    if moves:
        h.append('<h2 class="cb-section" id="latest-moves">LATEST MOVES</h2>')
        h.append('<ul class="cb-moves">' + "".join(
            f'<li><time datetime="{d}">{short(d)}</time><span><a href="#{esc(r["id"])}">{esc(r["label"])}</a>'
            f'<span class="cb-what">{esc(what)}.</span><span class="cb-tag">{esc(r["case"].upper())}</span></span></li>'
            for d, r, what in moves) + "</ul>")
    if riders:
        h.append('<h2 class="cb-section" id="inside-bigger-bills">INSIDE BIGGER BILLS</h2>')
        h.append('<p class="cb-note">Some changes to the law ride inside large bills that must pass, like the farm bill or the defense bill. We read the newest text of those bills for language tied to these cases.</p>')
        h.append('<ul class="cb-moves">' + "".join(render_rider(x) for x in riders) + "</ul>")

    h.append('<h2 class="cb-section" id="by-case">BILLS BY CASE</h2>')

    def case_key(item):
        rs = item[1]
        return (max((r["last_date"] or r["introduced"] or "") for r in rs), max(r["step"] for r in rs))

    ordered = sorted(cases.items(), key=case_key, reverse=True)
    mid = max(1, len(ordered) // 2)
    for i, (case, rs) in enumerate(ordered):
        rs.sort(key=lambda r: (not r["expired"], r["step"], r["last_date"] or r["introduced"] or ""), reverse=True)
        anchor = case_anchor(case)
        n = f"{len(rs)} BILL{'S' if len(rs) != 1 else ''}"
        h.append(f'<h2 class="cb-case" id="{anchor}"><a href="/{esc(rs[0]["page"])}">{esc(case)}</a><span class="cb-count">{n}</span></h2>')
        h += [render_row(r, today) for r in rs]
        if i == mid - 1:
            h.append('<div class="inline-cta"><p><strong>A bill in Congress does not pause the deadline to file.</strong> '
                     "Each state sets its own deadline, and it usually runs from the date of diagnosis. A free review checks your dates.</p>"
                     f'<a class="btn btn-primary" href="{cta("congress_inline_cta")}" rel="noopener">Check My Filing Deadline</a>'
                     '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    if expired:
        h.append(f'<p class="cb-note">{len(expired)} of these bills expired when their Congress ended. They stay listed until we remove them.</p>')
    h.append('<p class="cb-note">How this page works: we follow these bills on Congress.gov, the official record, and check them three times a day. '
             "The stage shows how far each bill has gotten. The last move is the newest vote or step that changed where the bill stands.</p>")
    h.append('<div class="cta-box"><h2>Find Out If You May Have a Case</h2>'
             "<p>If a product on this page hurt you or someone in your family, a free case review can look at your records and your diagnosis date. It can tell you which deadlines apply to you.</p>"
             f'<div class="cta-buttons"><a class="btn btn-primary" href="{cta("congress_ctabox")}" rel="noopener">Get a Free Case Review</a>'
             '<a class="btn btn-secondary" href="current-mass-tort-cases">See Where Each Case Stands</a></div>'
             '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    return "\n".join(h)


def case_anchor(case: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", case.lower()).strip("-")


# ---------------------------------------------------------------- links to the board

HOME = "index.html"
HOME_ROWS = 5
HOME_BEGIN, HOME_END = "<!-- LI-CONGRESS:BEGIN -->", "<!-- LI-CONGRESS:END -->"
HOME_AFTER = "<!-- LI-BOARD:END -->"
HOME_ANCHOR = "<!-- ===================== END CREDIBILITY STRIP ===================== -->"
LINK_BEGIN, LINK_END = "<!-- LI-CONGRESS-LINK:BEGIN -->", "<!-- LI-CONGRESS-LINK:END -->"
BOARD_LINK_END = "<!-- LI-BOARD-LINK:END -->"
STAMP = re.compile(r'<p class="article-date">.*?</p>', re.S)


def first_sentence(text: str) -> str:
    """The line's first sentence, or its first two when the first is a bare label
    ("The yearly defense bill.") that says nothing about what the bill would do."""
    parts = re.findall(r".+?[.!?](?=\s|$)", text.strip())
    if not parts:
        return text
    lead = parts[0].strip()
    if len(lead.split()) < 8 and len(parts) > 1:
        lead = (lead + " " + parts[1].strip()).strip()
    return lead


# The Congress strip sits right under the status board's "Latest in Court" strip and reuses its
# classes. A tinted panel with rules above and below (the site's .section.alt) and a gap before it
# keeps the two strips from reading as one list.
HOME_CSS = """<style id="li-congress-strip">
.hb.hb-congress{margin-top:32px;padding:30px 0 22px;}
.hb.hb-congress .hb-head h2::before{content:"";display:inline-block;width:10px;height:10px;margin-right:10px;background:var(--amber-deep);vertical-align:2px;}
</style>"""


def render_home(rows: list, stamp: str) -> str:
    """The homepage strip, in the status board strip's own classes: the bills that moved most
    recently, then the furthest along, HOME_ROWS in all. Empty when no bill is live."""
    live = [r for r in rows if not r["expired"]]
    if not live:
        return ""
    picks = sorted(live, key=lambda r: (r["last_date"] or "", r["step"], r["introduced"] or ""), reverse=True)[:HOME_ROWS]
    items = []
    for r in picks:
        when = (f"LAST MOVE {short(r['last_date'])}" if r["last_date"]
                else f"FILED {short(r['introduced'])}" if r["introduced"] else "")
        items.append(
            f'<li><span><a class="hb-name" href="{SLUG}#{esc(r["id"])}">{esc(r["label"])}</a>'
            f'<span class="hb-pill hb-{r["tone"]}">{esc(r["stage"].upper())}</span></span>'
            f'<span class="hb-meta">{when}</span>'
            f'<p class="hb-lead">{esc(r["case"])}: {esc(first_sentence(r["line"]))}</p></li>')
    d = _dt.date.fromisoformat(stamp)
    return (f"{HOME_BEGIN}\n{HOME_CSS}\n"
            '<section class="section alt hb hb-congress"><div class="container narrow">'
            f'<div class="hb-head"><h2>Latest in Congress</h2><span class="hb-when">AS OF {short(stamp)}</span>'
            f'<a class="hb-all" href="{SLUG}">All {len(live)} bills we follow &rarr;</a></div>'
            "<ul>" + "".join(items) + "</ul></div></section>\n" + HOME_END)


def write_home(rows: list, stamp: str, dry_run: bool) -> bool:
    if not os.path.exists(HOME):
        warn(f"{HOME} not found, homepage strip skipped")
        return False
    with open(HOME, encoding="utf-8") as fh:
        home = fh.read()
    block = render_home(rows, stamp)
    if HOME_BEGIN in home and HOME_END in home:
        start, end = home.index(HOME_BEGIN), home.index(HOME_END) + len(HOME_END)
        new = home[:start] + block + home[end:]
        if not block:
            new = re.sub(r"\n{3,}", "\n\n", new)
    elif not block:
        return False
    elif HOME_AFTER in home:
        new = home.replace(HOME_AFTER, HOME_AFTER + "\n" + block, 1)
    elif HOME_ANCHOR in home:
        new = home.replace(HOME_ANCHOR, HOME_ANCHOR + "\n\n" + block + "\n", 1)
    else:
        warn(f"{HOME} has neither the status board strip nor the credibility-strip anchor, strip skipped")
        return False
    if new == home:
        print("homepage Congress strip unchanged")
        return False
    if dry_run:
        print("homepage Congress strip would change")
        return False
    with open(HOME, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"wrote {HOME} (Congress strip)")
    return True


def page_links(rows: list) -> dict:
    """page -> (live bill count, case anchor with the most bills on that page)."""
    by_page = {}
    for r in rows:
        if r["expired"]:
            continue
        for p in r["ipages"]:
            by_page.setdefault(p, []).append(r["case"])
    out = {}
    for p, cases in by_page.items():
        top = max(sorted(set(cases)), key=cases.count)
        out[p] = (len(cases), case_anchor(top))
    return out


def render_page_link(n: int, anchor: str) -> str:
    what = ("Congress is weighing a bill tied to this case. "
            f'<a href="{SLUG}#{anchor}">See where it stands &rarr;</a>') if n == 1 else \
           (f"Congress is weighing {n} bills tied to this case. "
            f'<a href="{SLUG}#{anchor}">See where each bill stands &rarr;</a>')
    return (f"{LINK_BEGIN}\n"
            f'  <p class="article-date board-link" style="margin-top:-16px">{what}</p>\n'
            f"  {LINK_END}")


def write_page_links(rows: list, dry_run: bool) -> list:
    """Put the Congress line on every case page a live bill names, and take it off pages no live
    bill names any more. Returns the files written (or that would be)."""
    want = page_links(rows)
    written = []
    names = set(want)
    for f in sorted(os.listdir(".")):
        if f.endswith(".html") and f != OUT:
            slug = f[:-5]
            if slug in names:
                continue
            with open(f, encoding="utf-8") as fh:
                if LINK_BEGIN in fh.read():
                    names.add(slug)
    for slug in sorted(names):
        path = f"{slug}.html"
        if not os.path.exists(path):
            warn(f"{path} is named by a bill but is not in the repo; Congress line skipped")
            continue
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        block = render_page_link(*want[slug]) if slug in want else ""
        if LINK_BEGIN in page and LINK_END in page:
            extra = re.compile(r"\n*[ \t]*" + re.escape(LINK_BEGIN) + r".*?" + re.escape(LINK_END), re.S)
            start = page.index(LINK_BEGIN)
            first_end = page.index(LINK_END, start) + len(LINK_END)
            rest = extra.sub("", page[first_end:])
            if block:
                new = page[:start] + block + rest
            else:
                new = re.sub(r"\n[ \t]*$", "", page[:start]) + rest
        elif not block:
            continue
        elif BOARD_LINK_END in page:
            i = page.index(BOARD_LINK_END) + len(BOARD_LINK_END)
            new = page[:i] + "\n  " + block + page[i:]
        else:
            m = STAMP.search(page)
            if not m:
                warn(f"{path} has no <p class=\"article-date\">, Congress line skipped")
                continue
            new = page[:m.end()] + "\n\n  " + block + page[m.end():]
        if new == page:
            continue
        written.append(path)
        if not dry_run:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    verb = "would get" if dry_run else "got"
    print(f"Congress line: {len(written)} page(s) {verb} it" + (": " + ", ".join(written) if written else ""))
    return written


def rows_digest(rows: list, riders: list) -> str:
    sig = json.dumps({"rows": rows, "riders": riders}, sort_keys=True, default=str)
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the page shell


def first_shell(today: _dt.date) -> str:
    """The status board's shell, re-pointed at this page. Used once, when the page is new."""
    if not os.path.exists(SHELL_FROM):
        sys.exit(f"{OUT} does not exist and {SHELL_FROM} is not here to copy its shell from")
    with open(SHELL_FROM, encoding="utf-8") as fh:
        s = fh.read()
    s = s.replace(f"{SITE}/current-mass-tort-cases\"", f"{SITE}/{SLUG}\"")
    s = s.replace(f"{SITE}/og/current-mass-tort-cases.jpg", f"{SITE}/og/{SLUG}.jpg")
    s = re.sub(r'(<meta\s+property="og:image:alt"\s+content=")[^"]*(")',
               lambda m: m.group(1) + esc(TITLE) + " — Lawsuit Informer" + m.group(2), s, count=1)
    s = re.sub(r'("name":\s*)"[^"]*"(,\s*"item":\s*"' + re.escape(f"{SITE}/{SLUG}") + '")',
               lambda m: m.group(1) + json.dumps(TITLE) + m.group(2), s)
    s = re.sub(r'"datePublished":\s*"[^"]*"', f'"datePublished": "{today.isoformat()}"', s, count=1)
    # The status board's signup box is the status board's (add_signup_boxes.py owns it).
    s = re.sub(r"\n*<!-- LI-SIGNUP-BOARD:BEGIN -->.*?<!-- LI-SIGNUP-BOARD:END -->\n*", "\n\n", s, count=1, flags=re.S)
    s = re.sub(r"<!-- board:rows:[0-9a-f]{16}:\d{4}-\d{2}-\d{2} -->", "", s)
    return s


def set_head(shell: str, stamp: str, desc: str) -> str:
    shell = re.sub(r"<title>.*?</title>", f"<title>{esc(TITLE)}</title>", shell, count=1, flags=re.S)
    for pat in (r'(<meta\s+name="description"\s+content=")[^"]*(")',
                r'(<meta\s+property="og:description"\s+content=")[^"]*(")',
                r'(<meta\s+name="twitter:description"\s+content=")[^"]*(")'):
        shell = re.sub(pat, lambda m: m.group(1) + esc(desc) + m.group(2), shell, count=1)
    for pat in (r'(<meta\s+property="og:title"\s+content=")[^"]*(")',
                r'(<meta\s+name="twitter:title"\s+content=")[^"]*(")'):
        shell = re.sub(pat, lambda m: m.group(1) + esc(TITLE) + m.group(2), shell, count=1)

    def fix_ld(m):
        block = m.group(0)
        block = re.sub(r'"name":\s*"[^"]*"', '"name": ' + json.dumps(TITLE), block, count=1)
        block = re.sub(r'"description":\s*"[^"]*"', '"description": ' + json.dumps(desc), block, count=1)
        block = re.sub(r'"dateModified":\s*"[^"]*"', f'"dateModified": "{stamp}"', block, count=1)
        return block
    shell = re.sub(r'<script type="application/ld\+json">\s*\{\s*"@context": "https://schema.org",\s*"@type": "CollectionPage".*?</script>',
                   fix_ld, shell, count=1, flags=re.S)
    return shell


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="refresh data/congress_bills.json from Hill Wire first")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="write even when the rows did not change")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for tests")
    args = ap.parse_args()
    today = _dt.date.fromisoformat(args.today) if args.today else _dt.date.today()

    if args.fetch:
        fetch(args.dry_run)

    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            shell = fh.read()
    else:
        shell = first_shell(today)
        print(f"{OUT} is new; shell copied from {SHELL_FROM}")
    m = re.search(r"<!-- congress:rows:([0-9a-f]{16}):(\d{4}-\d{2}-\d{2}) -->", shell)
    old_digest, old_stamp = (m.group(1), m.group(2)) if m else ("", "")

    rows, riders = read_rows(today)
    if not rows:
        sys.exit("no rows read; nothing written")
    digest = rows_digest(rows, riders)
    changed = digest != old_digest
    stamp = today.isoformat() if (changed or not old_stamp) else old_stamp

    live = [r for r in rows if not r["expired"]]
    ncases = len({r["case"] for r in rows})
    desc = (f"Where {len(live)} bills in Congress stand as of {long_(stamp)}, across {ncases} cases: "
            f"what each would do and the last step Congress took.")
    if len(desc) > 160:
        desc = f"Where {len(live)} bills in Congress on {ncases} mass tort cases stand as of {long_(stamp)}."
    main_html = (f'<main id="main" class="content-page">\n<!-- congress:rows:{digest}:{stamp} -->\n'
                 + render_main(rows, riders, today, stamp) + "\n</main>")
    out = re.sub(r'<main id="main" class="content-page">.*?</main>', lambda _: main_html, shell, count=1, flags=re.S)
    out = set_head(out, stamp, desc)
    out = re.sub(r"(<strong>Last Updated:</strong>\s*)(?:<time[^>]*>[^<]*</time>|[A-Z][a-z]+ \d{1,2}, \d{4})",
                 lambda mm: mm.group(1) + f'<time datetime="{stamp}">{long_(stamp)}</time>', out, count=1)

    print(f"{len(rows)} bills in {ncases} cases, {len(riders)} rider hit(s), digest {digest}"
          + (" (changed)" if changed else " (unchanged)"))
    if args.dry_run:
        for r in rows:
            print(f"  {r['case']:<26} {r['bill']:<13} {r['stage']:<22} last {r['last_date'] or '-'}  {r['last'][:60]}")
        write_home(rows, stamp, dry_run=True)
        write_page_links(rows, dry_run=True)
        return 0
    if not changed and not args.force:
        print("rows unchanged; file left alone")
    else:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"wrote {OUT}, stamp {stamp}")
    # The strip follows the board's stamp, so the two never disagree about the date.
    write_home(rows, stamp, dry_run=False)
    write_page_links(rows, dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
