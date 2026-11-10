#!/usr/bin/env python3
"""
Generate state-laws-on-mass-tort-cases.html, the state board, from Hill Wire.

The state board is the Congress board's sibling for state legislatures. One row per
state law or bill Hill Wire's STATES tab watches that touches a case this site covers,
grouped by case, with whether it is law yet, when it takes effect, the last thing the
state did with it, and one plain-language line on what it does for people in that case.

Two inputs:

  data/state_bills.json   Hill Wire's state watch list, saved from the "states" part of
                          its /api/state. `--fetch` refreshes it when HILL_KEY is set
                          (the workflow does this), and rewrites the file only when a
                          bill's stage or moves changed, so a quiet poll commits
                          nothing. Without the key, or when Hill Wire cannot be
                          reached, the saved file is used as is.
  data/state_lines.txt    The reader-facing words, kept by hand:
                            [cases]  topic|case name as the board shows it
                            [bills]  state and bill|name on the board|what it does,
                                     plain|date it takes effect (optional)
                          A bill shows only when it has a [bills] line here. Hill
                          Wire's own notes are desk notes, so they never reach this page.

Which bills show: Hill Wire topic is not "-", one of the bill's pages is on
lawsuitinformer.com, and data/state_lines.txt has a line for it. A watched bill that
passes the first two tests and has no line is printed as a warning and left off.

What a row shows:
  stage      Hill Wire's stage, renamed for readers (Reported -> Cleared committee)
  in force   for a law with a date in its [bills] line: "In force since" or "Takes
             effect", worked out against the day of the run
  last move  the newest step that changes where the bill stands (a committee vote, a
             floor vote, the governor's signature or veto). Filings and referrals never
             count, and neither does a step dated in the future, such as an effective date.
  track      six steps from Filed to Law

The page shell, the styles and the small helpers are the Congress board's
(generate_congress_board.py is imported for them), so the two boards look alike and a
change to the shell reaches both. On the first run, when the page does not exist yet,
the shell is copied from current-mass-tort-cases.html the same way.

The page is written only when the rows changed, and then dateModified and the visible
stamp move to today. A day with no change leaves it untouched.

The same run keeps the board's links in step: a "Latest in the States" strip on
index.html, under the Congress strip (five rows, newest move first, at most two per case so
a case with many laws cannot fill it), and one line under the stamp of every case page a
law or bill names (under the Congress line where the page has one).

    python3 generate_state_board.py --fetch       # refresh the data, then build
    python3 generate_state_board.py               # build from the saved data
    python3 generate_state_board.py --dry-run     # print the rows, write nothing
    python3 generate_state_board.py --force       # write even if unchanged
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

import generate_congress_board as cb

SITE = cb.SITE
SLUG = "state-laws-on-mass-tort-cases"
OUT = SLUG + ".html"
DATA = os.path.join("data", "state_bills.json")
LINES = os.path.join("data", "state_lines.txt")
HILL_URL = cb.HILL_URL
UA = "lawsuitinformer state board (+https://lawsuitinformer.com)"
TITLE = "State Laws on Mass Tort Cases: Where Each One Stands"
H1 = "State Laws and Bills Tied to Mass Tort Cases"
RECENT_DAYS = 30
LATEST_MOVES = 8
MOVES_KEPT = 10
MOVES_SINCE = 120
CAMPAIGN = "state_board"

# The shell helpers in generate_congress_board read these names when they run.
cb.SLUG, cb.OUT, cb.TITLE, cb.CAMPAIGN = SLUG, OUT, TITLE, CAMPAIGN

warn, esc, short, long_, to_date, cta = cb.warn, cb.esc, cb.short, cb.long_, cb.to_date, cb.cta

TRACK = ["Filed", "Committee", "Cleared committee", "One chamber", "Both chambers", "Law"]
# Hill Wire stage -> (reader label, step on the track, tone)
STAGES = {
    "Introduced": ("Filed", 1, "quiet"),
    "In committee": ("In committee", 2, "quiet"),
    "Reported": ("Cleared committee", 3, "watch"),
    "Passed both": ("Passed both chambers", 5, "watch"),
    "To governor": ("With the governor", 5, "watch"),
    "Law": ("Law", 6, "live"),
    "Vetoed": ("Vetoed", 0, "quiet"),
    "Failed": ("Failed", 0, "quiet"),
}

# Steps that change where a bill stands, and paperwork that does not. The same two rules
# Hill Wire's STATES tab uses (public/index.html, STATE_MOVE_TEXT and stateProcedural).
MOVE_TEXT = re.compile(r"^(re-?reported|reported)\b|\breported (out|favorably|with|without)\b|\bpassed\b|\bsigned\b|"
                       r"\bvetoed\b|\bchaptered\b|\bconcurred\b|\benacted\b", re.I)
PAPER_TEXT = re.compile(r"^(introduced|read (the )?first time|first reading|referred to|re-?referred to|prefiled|"
                        r"pre-filed|filed|bill electronically reproduced)", re.I)
KEY_TAGS = {"executive-signature", "executive-veto", "executive-veto-line-item", "became-law", "executive-receipt",
            "passage", "committee-passage", "committee-passage-favorable", "failure", "committee-failure",
            "withdrawal", "veto-override-passage"}
# A bill sent back out of a committee unchanged on its way to the floor (Pennsylvania's
# "Re-reported as committed"). The committee's real vote was the earlier report.
ROUTINE = re.compile(r"^re-?reported as committed\b", re.I)
AGREED = re.compile(r"\bconcurr|\bagreed (to )?(house|senate|assembly)\b", re.I)


def is_move(a: dict) -> bool:
    """A step that changes where the bill stands: a committee report, a floor vote, agreement
    between the chambers, delivery to the governor, a signature or a veto. Readings, tabling,
    amendments and messages between the chambers are left out."""
    t = (a.get("text") or "").strip()
    tags = set(a.get("classification") or a.get("tags") or [])
    if t and ROUTINE.search(t):
        return False
    if t and PAPER_TEXT.search(t) and not MOVE_TEXT.search(t):
        return False
    return bool(tags & KEY_TAGS) or bool(t and (MOVE_TEXT.search(t) or AGREED.search(t)))


def move_rank(m: dict) -> int:
    """Lower is further along. Used to pick one step when a bill has several on one day."""
    tags = set(m.get("tags") or m.get("classification") or [])
    low = (m.get("text") or "").lower()
    for i, (tagset, pat) in enumerate([
            ({"executive-signature", "executive-veto", "executive-veto-line-item", "became-law"}, r"\bsigned\b|\bvetoed\b|chaptered|enacted"),
            ({"executive-receipt"}, r"to (the )?governor"),
            (set(), r"\bconcurr|\bagreed (to )?(house|senate|assembly)\b"),
            ({"passage"}, r"\bpassed\b"),
            ({"committee-passage", "committee-passage-favorable"}, r"\breported\b")]):
        if tags & tagset or re.search(pat, low):
            return i
    return 9


def day_best(moves: list) -> list:
    """One move per day, the furthest along, newest day first."""
    by_day = {}
    for m in moves:
        d = m.get("date") or ""
        if d and (d not in by_day or move_rank(m) < move_rank(by_day[d])):
            by_day[d] = m
    return [by_day[d] for d in sorted(by_day, reverse=True)]


# ---------------------------------------------------------------- the data file


def trim_states(states: dict) -> dict:
    """The parts of Hill Wire's state watch the board reads, with poll times left out so a
    quiet poll produces the same file."""
    bills = {}
    for key, b in (states.get("bills") or {}).items():
        bid = b.get("id") or key
        latest = b.get("latest") or {}
        moves = [{"date": (a.get("date") or "")[:10], "text": (a.get("text") or "").strip(),
                  "chamber": a.get("chamber") or "", "tags": a.get("classification") or []}
                 for a in (b.get("actions") or []) if is_move(a)]
        moves.sort(key=lambda m: m["date"], reverse=True)
        bills[bid] = {
            "id": bid, "state": b.get("state") or "", "state_name": b.get("stateName") or "",
            "session": b.get("session") or "", "identifier": b.get("identifier") or "",
            "label": b.get("label") or "", "title": b.get("title") or "", "topic": b.get("topic") or "-",
            "pages": b.get("pages") or [], "url": b.get("url") or "", "introduced": (b.get("introduced") or "")[:10],
            "stage": b.get("stage") or "",
            "latest": {"date": (latest.get("date") or "")[:10], "text": (latest.get("text") or "").strip()},
            "moves": moves[:MOVES_KEPT],
        }
    return {"source": HILL_URL + "/api/state", "bills": dict(sorted(bills.items()))}


def fetch(dry_run: bool) -> None:
    key = (os.environ.get("HILL_KEY") or "").strip()
    if not key:
        warn(f"HILL_KEY is not set; building from the saved {DATA}")
        return
    req = urllib.request.Request(HILL_URL + "/api/state", headers={"X-Wire-Key": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            states = (json.loads(r.read().decode("utf-8")) or {}).get("states")
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
    if not states or not states.get("bills"):
        warn("Hill Wire has no saved state watch yet; building from the saved data")
        return
    run = states.get("lastRun") or {}
    print(f"Hill Wire last polled the states {run.get('at', '?')}: {run.get('billCount', '?')} bills, ok={run.get('ok')}")
    # A bill Hill Wire could not refresh on this poll carries no stage yet. Keep the saved
    # copy of it, so one missed poll never blanks a row.
    new = trim_states(states)
    old = None
    if os.path.exists(DATA):
        try:
            with open(DATA, encoding="utf-8") as fh:
                old = json.load(fh)
        except ValueError:
            old = None
    if old:
        for bid, b in new["bills"].items():
            if not b["stage"] and bid in (old.get("bills") or {}):
                kept = dict(old["bills"][bid])
                kept.update({"label": b["label"], "topic": b["topic"], "pages": b["pages"]})
                new["bills"][bid] = kept
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


def line_key(state: str, identifier: str) -> str:
    return (state or "").lower() + " " + re.sub(r"[.\s]+", "", (identifier or "").upper())


def load_lines() -> dict:
    out = {"cases": {}, "bills": {}}
    if not os.path.exists(LINES):
        sys.exit(f"{LINES} not found")
    section = None
    with open(LINES, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\[(cases|bills)\]$", line, re.I)
            if m:
                section = m.group(1).lower()
                continue
            if not section or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if section == "cases":
                if parts[0] and parts[1]:
                    out["cases"][parts[0].lower()] = parts[1]
                continue
            if len(parts) < 3 or not parts[0] or not parts[2]:
                warn(f"{LINES}: [bills] line needs state and bill|name|line: {line[:60]!r}")
                continue
            st, _, ident = parts[0].partition(" ")
            eff = parts[3] if len(parts) > 3 else ""
            if eff and not to_date(eff):
                warn(f"{LINES}: effective date {eff!r} is not YYYY-MM-DD; ignored for {parts[0]}")
                eff = ""
            out["bills"][line_key(st, ident)] = (parts[1], parts[2], eff)
    return out


# ---------------------------------------------------------------- rows


def informer_pages(pages: list) -> list:
    return [p for p in pages or [] if p.startswith(SITE + "/")]


def rel(url: str) -> str:
    return url[len(SITE) + 1:] if url.startswith(SITE + "/") else url


def plain_move(m: dict) -> str:
    """One state action, in plain words. States word the same step fifty ways, so the tags
    Open States puts on the action decide the wording wherever they can."""
    t = (m.get("text") or "").strip()
    tags = set(m.get("tags") or [])
    chamber = (m.get("chamber") or "").strip()
    low = t.lower()
    if "executive-veto" in tags or "executive-veto-line-item" in tags or "vetoed" in low:
        return "The governor vetoed it"
    if "executive-signature" in tags or re.search(r"\bsigned\b.*\bgovernor\b|\bgovernor signed\b|\bapproved by (the )?governor\b|^signed chap", low):
        return "The governor signed it into law"
    if "became-law" in tags or "chaptered" in low or "enacted" in low:
        return "It became law"
    if "executive-receipt" in tags or re.search(r"(delivered|sent|presented|transmitted) to (the )?governor", low):
        return "It went to the governor"
    if AGREED.search(low) and "passage" not in tags:
        return "Both chambers agreed on the final wording"
    if "passage" in tags or re.search(r"\bpassed\b", low):
        where = chamber if chamber and len(chamber) < 20 and chamber.lower() != "governor" else ""
        return f"It passed the {where}" if where else "It passed a floor vote"
    if tags & {"committee-passage", "committee-passage-favorable"} or re.search(r"^(re-?reported|reported)\b|\breported (out|favorably|with|without)\b", low):
        return "A committee approved it"
    if tags & {"failure", "committee-failure"}:
        return "It failed a vote"
    if "withdrawal" in tags:
        return "Its sponsor withdrew it"
    t = re.sub(r"\s+", " ", t).rstrip(". ")
    return t[:1].upper() + t[1:] if t else "It moved"


def read_rows(today: _dt.date) -> list:
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
        name, line, eff = lines["bills"].get(line_key(b.get("state"), b.get("identifier")), ("", "", ""))
        case = lines["cases"].get(topic.lower())
        num = f"{(b.get('state') or '').upper()} {b.get('identifier') or ''}".strip()
        if not line or not case:
            missing.append(f"{num} ({b.get('label')})" + ("" if case else f", no [cases] name for topic {topic!r}"))
            continue
        raw_stage = b.get("stage") or ""
        if raw_stage.startswith("Passed ") and raw_stage != "Passed both":
            label, step, tone = "Passed one chamber", 4, "watch"
        else:
            label, step, tone = STAGES.get(raw_stage, (raw_stage or "Filed", 1, "quiet"))
        moves = day_best([m for m in (b.get("moves") or [])
                          if m.get("date") and m["date"] <= today.isoformat() and is_move(m)])
        last = moves[0] if moves else None
        force = ""
        if step == 6 and eff:
            force = ("In force since " if eff <= today.isoformat() else "Takes effect ") + long_(eff)
        rows.append({
            "id": re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-"), "bill": num,
            "state": b.get("state_name") or (b.get("state") or "").upper(),
            "label": name or b.get("label") or b.get("title") or num, "url": b.get("url") or "",
            "topic": topic, "case": case, "page": rel(ipages[0]), "ipages": [rel(x) for x in ipages], "introduced": b.get("introduced") or "",
            "stage": label, "step": step, "tone": tone, "line": line, "force": force,
            "last_date": last["date"] if last else "", "last": plain_move(last) if last else "",
            "moves": [(m["date"], plain_move(m)) for m in moves],
        })
    for m in missing:
        warn(f"no reader line in {LINES} for {m}; left off the board")
    return rows


# ---------------------------------------------------------------- rendering

CSS = cb.CSS.replace('id="li-congress-board"', 'id="li-state-board"').replace(
    "/* Congress board.", "/* State board. Styles shared with the Congress board.") + """<style id="li-state-board-extra">
#main .cb-force{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;color:var(--ink-soft);margin:8px 0 0;}
#main .cb-state{font-family:var(--mono);font-size:10px;letter-spacing:.11em;color:var(--ink-soft);}
</style>
"""


def render_row(r: dict, today: _dt.date) -> str:
    h = [f'<article class="cb-row" id="{esc(r["id"])}">']
    h.append(f'<div class="cb-head"><h3 class="cb-name">{esc(r["label"])}</h3>'
             f'<span class="cb-pill cb-{r["tone"]}">{esc(r["stage"].upper())}</span>')
    if r["last_date"] and (today - _dt.date.fromisoformat(r["last_date"])).days <= RECENT_DAYS:
        h.append('<span class="cb-new">MOVED</span>')
    h.append(f'<span class="cb-num">{esc(r["bill"])}</span></div>')
    if r["step"]:
        law = " law" if r["step"] >= 6 else ""
        dots = "".join('<li class="on"></li>' if i < r["step"] else "<li></li>" for i in range(len(TRACK)))
        h.append(f'<ol class="cb-track{law}" aria-label="Step {r["step"]} of {len(TRACK)}: {esc(r["stage"])}">{dots}</ol>'
                 f'<div class="cb-steps" aria-hidden="true">STEP {r["step"]} OF {len(TRACK)} · {esc(TRACK[r["step"] - 1].upper())}</div>')
    if r["force"]:
        h.append(f'<p class="cb-force">{esc(r["force"].upper())}</p>')
    h.append(f'<p class="cb-line">{esc(r["line"])}</p>')
    if r["last_date"]:
        h.append(f'<p class="cb-last"><time datetime="{r["last_date"]}">{short(r["last_date"])}</time>{esc(r["last"])}.</p>')
    elif r["introduced"] and r["step"] in (1, 2):
        h.append(f'<p class="cb-last"><time datetime="{r["introduced"]}">{short(r["introduced"])}</time>Filed. No vote yet.</p>')
    link = (f'<a href="{esc(r["url"])}" rel="noopener" target="_blank">{esc(r["bill"])} on Open States</a>' if r["url"] else "")
    h.append(f'<div class="cb-foot"><a href="/{esc(r["page"])}">Read more about {esc(r["case"])}</a>{link}</div></article>')
    return "\n".join(h)


def latest_moves(rows: list, today: _dt.date) -> list:
    out = []
    floor = today - _dt.timedelta(days=MOVES_SINCE)
    for r in rows:
        seen = set()
        for d, what in r["moves"]:
            dd = to_date(d)
            if dd and floor <= dd <= today and (d, what) not in seen:
                seen.add((d, what))
                out.append((d, r, what))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:LATEST_MOVES]


def render_main(rows: list, today: _dt.date, stamp: str) -> str:
    laws = [r for r in rows if r["step"] == 6]
    pending = [r for r in rows if 0 < r["step"] < 6]
    recent = [r for r in rows if r["last_date"] and (today - _dt.date.fromisoformat(r["last_date"])).days <= RECENT_DAYS]
    nstates = len({r["state"] for r in rows})
    cases = {}
    for r in rows:
        cases.setdefault(r["case"], []).append(r)

    band = (f"<b>{len(laws)}</b> state law{'s' if len(laws) != 1 else ''} and <b>{len(pending)}</b> pending "
            f"bill{'s' if len(pending) != 1 else ''} in {nstates} states.")
    band += (f" {len(recent)} moved in the last {RECENT_DAYS} days." if recent
             else f" None moved in the last {RECENT_DAYS} days.")

    h = [CSS,
         '<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<a href="browse-lawsuits">Browse Lawsuits</a> <span class="breadcrumb-separator">&rsaquo;</span> '
         '<span aria-current="page">State Laws and Bills</span></nav>',
         f"<h1>{esc(H1)}</h1>",
         '<p class="article-byline">By <a href="david-meldofsky">David Meldofsky</a>, California-licensed attorney &middot; Founder, Lawsuit Informer</p>',
         f'<p class="article-date">Last updated: <time datetime="{stamp}">{long_(stamp)}</time></p>',
         "<p>State lawmakers are writing rules for some of the products in the cases we cover. A state law can add safety rules, let injured people sue, or limit what a lawsuit can claim. "
         "This page lists each state law and bill we follow, grouped by case.</p>",
         "<p>A state bill becomes law only after both chambers pass it and the governor signs it. A new law often starts months after it is signed, so each law shows its start date. "
         'For bills in Washington, see <a href="mass-tort-bills-in-congress">bills in Congress</a>. '
         'For where each case stands in court, see <a href="current-mass-tort-cases">the status board</a>.</p>',
         f'<div class="cb-band{"" if recent else " quiet"}" role="status"><span class="cb-band-title">IN THE STATES</span>'
         f'<span class="cb-band-sum">{band}</span>'
         f'<span class="cb-band-when">BUILT {short(stamp)} FROM STATE RECORDS</span></div>',
         '<div class="hero-action-strip"><p class="hero-action-prompt">'
         "A state law can change what a company must do. The deadline to file a lawsuit keeps running either way. "
         "If you were hurt by a product on this page, a free case review can check your dates. Pick what fits:</p>"
         '<div class="hero-action-buttons">'
         f'<a class="hero-action-btn" href="{cta("state_hero_review")}" rel="noopener">Request a free case review</a>'
         f'<a class="hero-action-btn" href="{cta("state_hero_unsure")}" rel="noopener">I am not sure which case fits</a>'
         "</div>"
         '<p class="hero-action-note">Free and no obligation. Whether your history supports a claim depends on your facts. Submitting a review request does not create an attorney-client relationship.</p></div>']

    moves = latest_moves(rows, today)
    if moves:
        h.append('<h2 class="cb-section" id="latest-moves">LATEST MOVES</h2>')
        h.append('<ul class="cb-moves">' + "".join(
            f'<li><time datetime="{d}">{short(d)}</time><span><a href="#{esc(r["id"])}">{esc(r["label"])}</a>'
            f'<span class="cb-what">{esc(what)}.</span><span class="cb-tag">{esc(r["case"].upper())}</span></span></li>'
            for d, r, what in moves) + "</ul>")

    h.append('<h2 class="cb-section" id="by-case">LAWS AND BILLS BY CASE</h2>')

    def case_key(item):
        rs = item[1]
        return (len(rs), max((r["last_date"] or r["introduced"] or "") for r in rs))

    ordered = sorted(cases.items(), key=case_key, reverse=True)
    mid = max(1, len(ordered) // 2)
    for i, (case, rs) in enumerate(ordered):
        rs.sort(key=lambda r: (r["step"], r["last_date"] or r["introduced"] or ""), reverse=True)
        anchor = cb.case_anchor(case)
        nl = sum(1 for r in rs if r["step"] == 6)
        nb = len(rs) - nl
        bits = ([f"{nl} LAW{'S' if nl != 1 else ''}"] if nl else []) + ([f"{nb} BILL{'S' if nb != 1 else ''}"] if nb else [])
        h.append(f'<h2 class="cb-case" id="{anchor}"><a href="/{esc(rs[0]["page"])}">{esc(case)}</a>'
                 f'<span class="cb-count">{" · ".join(bits)}</span></h2>')
        h += [render_row(r, today) for r in rs]
        if i == mid - 1:
            h.append('<div class="inline-cta"><p><strong>A new state law does not pause the deadline to file.</strong> '
                     "Each state sets its own deadline to file a lawsuit. A free review checks your dates.</p>"
                     f'<a class="btn btn-primary" href="{cta("state_inline_cta")}" rel="noopener">Check My Filing Deadline</a>'
                     '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    h.append('<p class="cb-note">How this page works: we follow these laws and bills through Open States, which collects each legislature&rsquo;s official record, and check them three times a day. '
             "The stage shows how far each one has gotten. The last move is the newest vote or signature that changed where it stands. "
             "We list the state laws and bills we have read, so a state missing here may still have a law on the subject.</p>")
    h.append('<div class="cta-box"><h2>Find Out If You May Have a Case</h2>'
             "<p>If a product on this page hurt you or someone in your family, a free case review can look at your records and your diagnosis date. It can tell you which deadlines apply to you.</p>"
             f'<div class="cta-buttons"><a class="btn btn-primary" href="{cta("state_ctabox")}" rel="noopener">Get a Free Case Review</a>'
             '<a class="btn btn-secondary" href="current-mass-tort-cases">See Where Each Case Stands</a></div>'
             '<p class="cta-note">Free and no obligation. Submitting a request does not create an attorney-client relationship.</p></div>')
    return "\n".join(h)


# ---------------------------------------------------------------- homepage strip and case-page lines

HOME = "index.html"
HOME_ROWS = 3
HOME_PER_CASE = 2                                    # most rows one case may take on the homepage strip
HOME_BEGIN, HOME_END = "<!-- LI-STATES:BEGIN -->", "<!-- LI-STATES:END -->"
HOME_AFTER = [cb.HOME_END, cb.HOME_AFTER]            # after the Congress strip, else after the status board strip
LINK_BEGIN, LINK_END = "<!-- LI-STATE-LINK:BEGIN -->", "<!-- LI-STATE-LINK:END -->"
LINK_AFTER = [cb.LINK_END, cb.BOARD_LINK_END]        # under the Congress line, else under the status board line
HOME_CSS = """<style id="li-states-strip">
.hb.hb-states{margin-top:32px;padding:30px 0 22px;}
</style>"""


def render_home(rows: list, stamp: str) -> str:
    """The homepage strip, in the status board strip's own classes: HOME_ROWS laws and bills,
    newest move first, with no case taking more than HOME_PER_CASE of them. One case with
    many laws (AI chatbots) would otherwise fill every row. When fewer cases have a law or
    bill than there are rows, the rows left over go to the next most recent, whatever the case."""
    live = [r for r in rows if r["step"]]
    if not live:
        return ""
    ranked = sorted(live, key=lambda r: (r["last_date"] or "", r["step"], r["introduced"] or ""), reverse=True)
    picks, taken = [], {}
    for r in ranked:
        if taken.get(r["case"], 0) < HOME_PER_CASE:
            picks.append(r)
            taken[r["case"]] = taken.get(r["case"], 0) + 1
    picks = picks[:HOME_ROWS]
    for r in ranked:                                 # top up when the cap leaves rows empty
        if len(picks) >= HOME_ROWS:
            break
        if r not in picks:
            picks.append(r)
    picks.sort(key=ranked.index)
    items = []
    for r in picks:
        when = (f"LAST MOVE {short(r['last_date'])}" if r["last_date"]
                else f"FILED {short(r['introduced'])}" if r["introduced"] else "")
        items.append(
            f'<li><span><a class="hb-name" href="{SLUG}#{esc(r["id"])}">{esc(r["label"])}</a>'
            f'<span class="hb-pill hb-{r["tone"]}">{esc(r["stage"].upper())}</span></span>'
            f'<span class="hb-meta">{when}</span>'
            f'<p class="hb-lead">{esc(r["case"])}: {esc(cb.first_sentence(r["line"]))}</p></li>')
    return (f"{HOME_BEGIN}\n{HOME_CSS}\n"
            '<section class="section alt hb hb-states"><div class="container narrow">'
            f'<div class="hb-head"><h2>Latest in the States</h2><span class="hb-when">AS OF {short(stamp)}</span>'
            f'<a class="hb-all" href="{SLUG}">All {len(live)} state laws and bills we follow &rarr;</a></div>'
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
    else:
        after = next((a for a in HOME_AFTER if a in home), "")
        if not after:
            warn(f"{HOME} has neither the Congress strip nor the status board strip, state strip skipped")
            return False
        new = home.replace(after, after + "\n" + block, 1)
    if new == home:
        print("homepage state strip unchanged")
        return False
    if dry_run:
        print("homepage state strip would change")
        return False
    with open(HOME, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"wrote {HOME} (state strip)")
    return True


def page_links(rows: list) -> dict:
    """page -> (laws, bills, case anchor with the most rows on that page)."""
    by_page = {}
    for r in rows:
        if not r["step"]:
            continue
        for p in r["ipages"]:
            by_page.setdefault(p, []).append(r)
    out = {}
    for p, rs in by_page.items():
        cases = [r["case"] for r in rs]
        top = max(sorted(set(cases)), key=cases.count)
        laws = sum(1 for r in rs if r["step"] == 6)
        out[p] = (laws, len(rs) - laws, cb.case_anchor(top))
    return out


def render_page_link(laws: int, bills: int, anchor: str) -> str:
    parts = []
    if laws:
        parts.append(f"{laws} state law{'s' if laws != 1 else ''}")
    if bills:
        parts.append(f"{bills} state bill{'s' if bills != 1 else ''}")
    n = laws + bills
    what = (f"{' and '.join(parts)} {'touches' if n == 1 else 'touch'} this case. "
            f'<a href="{SLUG}#{anchor}">See what {"it does" if n == 1 else "each one does"} &rarr;</a>')
    what = what[:1].upper() + what[1:]
    return (f"{LINK_BEGIN}\n"
            f'  <p class="article-date board-link" style="margin-top:-16px">{what}</p>\n'
            f"  {LINK_END}")


def write_page_links(rows: list, dry_run: bool) -> list:
    """Put the state line on every case page a law or bill names, and take it off pages none
    names any more. Returns the files written (or that would be)."""
    want = page_links(rows)
    written = []
    names = set(want)
    for f in sorted(os.listdir(".")):
        if f.endswith(".html") and f != OUT and f[:-5] not in names:
            with open(f, encoding="utf-8") as fh:
                if LINK_BEGIN in fh.read():
                    names.add(f[:-5])
    for slug in sorted(names):
        path = f"{slug}.html"
        if not os.path.exists(path):
            warn(f"{path} is named by a state bill but is not in the repo; state line skipped")
            continue
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        block = render_page_link(*want[slug]) if slug in want else ""
        if LINK_BEGIN in page and LINK_END in page:
            extra = re.compile(r"\n*[ \t]*" + re.escape(LINK_BEGIN) + r".*?" + re.escape(LINK_END), re.S)
            start = page.index(LINK_BEGIN)
            first_end = page.index(LINK_END, start) + len(LINK_END)
            rest = extra.sub("", page[first_end:])
            new = (page[:start] + block + rest) if block else (re.sub(r"\n[ \t]*$", "", page[:start]) + rest)
        elif not block:
            continue
        else:
            after = next((a for a in LINK_AFTER if a in page), "")
            if after:
                i = page.index(after) + len(after)
                new = page[:i] + "\n  " + block + page[i:]
            else:
                m = cb.STAMP.search(page)
                if not m:
                    warn(f'{path} has no <p class="article-date">, state line skipped')
                    continue
                new = page[:m.end()] + "\n\n  " + block + page[m.end():]
        if new == page:
            continue
        written.append(path)
        if not dry_run:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    verb = "would get" if dry_run else "got"
    print(f"State line: {len(written)} page(s) {verb} it" + (": " + ", ".join(written) if written else ""))
    return written


def rows_digest(rows: list) -> str:
    return hashlib.sha1(json.dumps(rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help=f"refresh {DATA} from Hill Wire first")
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
        shell = cb.first_shell(today)
        shell = re.sub(r"<!-- congress:rows:[0-9a-f]{16}:\d{4}-\d{2}-\d{2} -->", "", shell)
        print(f"{OUT} is new; shell copied from {cb.SHELL_FROM}")
    m = re.search(r"<!-- states:rows:([0-9a-f]{16}):(\d{4}-\d{2}-\d{2}) -->", shell)
    old_digest, old_stamp = (m.group(1), m.group(2)) if m else ("", "")

    rows = read_rows(today)
    if not rows:
        sys.exit("no rows read; nothing written")
    digest = rows_digest(rows)
    changed = digest != old_digest
    stamp = today.isoformat() if (changed or not old_stamp) else old_stamp

    nlaws = sum(1 for r in rows if r["step"] == 6)
    ncases = len({r["case"] for r in rows})
    desc = (f"{nlaws} state laws and {len(rows) - nlaws} bills on {ncases} mass tort cases as of {long_(stamp)}: "
            f"what each does, when it takes effect and its last step.")
    if len(desc) > 160:
        desc = f"{nlaws} state laws and {len(rows) - nlaws} bills on {ncases} mass tort cases, as of {long_(stamp)}."
    main_html = (f'<main id="main" class="content-page">\n<!-- states:rows:{digest}:{stamp} -->\n'
                 + render_main(rows, today, stamp) + "\n</main>")
    out = re.sub(r'<main id="main" class="content-page">.*?</main>', lambda _: main_html, shell, count=1, flags=re.S)
    out = cb.set_head(out, stamp, desc)
    out = re.sub(r"(<strong>Last Updated:</strong>\s*)(?:<time[^>]*>[^<]*</time>|[A-Z][a-z]+ \d{1,2}, \d{4})",
                 lambda mm: mm.group(1) + f'<time datetime="{stamp}">{long_(stamp)}</time>', out, count=1)

    print(f"{len(rows)} laws and bills in {ncases} cases, digest {digest}" + (" (changed)" if changed else " (unchanged)"))
    if args.dry_run:
        for r in rows:
            print(f"  {r['case']:<26} {r['bill']:<12} {r['stage']:<20} {r['force'] or '-':<34} last {r['last_date'] or '-'}  {r['last'][:50]}")
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
