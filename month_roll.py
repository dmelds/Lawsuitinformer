#!/usr/bin/env python3
"""Month roll for Lawsuit Informer's month-stamped pages.

Every page whose <title> carries a currency month ("Update October 2026",
"(October 2026)", "October 2026 Status") goes stale on the 1st. The standing
rule decides each one by hand: if the docket moved, update the content and roll
the stamp with it; if only the calendar moved, de-stamp and leave dateModified
alone. This script does the three mechanical parts of that and none of the
judgment.

  plan      Lists every page whose title month is behind the target month, with
            the evidence for the call: dateModified, the newest dated entry,
            li:status, li:next and whether that date has passed, scheduled
            dates in the body that have passed since the edit, the JPML count
            change for the page's MDL, and the rolled title with its length.
            Prints a table, or writes Markdown with --md for the monthly issue.
            With --evidence <json> (written by network-ops roll_plan.py from
            the wire review and the Panel's counts) each page also lists the
            wire stories and docket entries waiting since its last edit, and
            a page with any of those is called MOVED.

  stamp     For a page whose content HAS been updated. With --date it first
            moves dateModified (every JSON-LD node carrying the page's date)
            and both visible "Last updated" stamps to that day. It then rolls
            every currency stamp to that month: title, og:title, twitter:title,
            the three descriptions, JSON-LD headline/description, h1-h3, and
            "As of <Month YYYY>" in the body. It refuses when dateModified is
            not in the target month, because a November stamp on an October
            edit is the false freshness check_date_consistency.py blocks.

  destamp   For a page whose docket did not move. Removes the currency month
            from the title, og/twitter titles, descriptions, JSON-LD headline
            and h1-h3. dateModified, the visible stamps and body sentences
            ("As of October 2026, no settlement...") are left alone: they were
            true when written and still say so.

Event references are never touched by either command: "October 2026 Ruling",
"sued in October 2026", "the October 2026 order". Anything in the head or a
heading that still names the old month after a run is printed so it can be
read, not rewritten.

Pages owned by a generator are skipped: current-mass-tort-cases.html gets its
title month from generate_status_board.py.

Usage
-----
    python3 month_roll.py plan [--month 2026-11] [--md roll.md] [--evidence ev.json]
    python3 month_roll.py stamp hernia-mesh-lawsuit.html --date 2026-11-03
    python3 month_roll.py stamp hernia-mesh-lawsuit.html      # dateModified already November
    python3 month_roll.py destamp grok-lawsuits.html coca-cola-lawsuit.html
    add --dry-run to stamp/destamp to print the changes and write nothing
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import check_date_consistency as cdc

MONTHS = cdc.MONTHS
NAMES = cdc.NAMES
MY = r"(?:" + "|".join(MONTHS) + r")\s+20\d{2}"
MYC = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b")

GENERATED = {
    "current-mass-tort-cases.html":
        "generate_status_board.py writes this title month; the status-board workflow rolls it",
}
TITLE_MAX = 60

# Currency patterns. Each has an optional `pre`, the stamp `my`, an optional
# `post`. Event phrasing ("October 2026 ruling", "sued in October 2026") does
# not match any of them, so it is never rolled or removed.
CURRENCY = [
    ("update", re.compile(r"(?P<pre>\bUpdates?:?\s+)(?P<my>" + MY + r")(?P<post>)")),
    ("paren", re.compile(r"(?P<pre>\s*\()(?P<my>" + MY + r")(?P<post>\))")),
    ("trailing", re.compile(r"(?P<pre>,\s+)(?P<my>" + MY + r")(?P<post>)(?=\s*(?:\||—|&mdash;|-\s|$))")),
    ("status", re.compile(r"(?P<pre>)(?P<my>" + MY + r")(?P<post>\s+(?:Status|Snapshot)\b)")),
    ("stand", re.compile(r"(?P<pre>\b(?:stands?|stood|standing)\s+in\s+)(?P<my>" + MY + r")(?P<post>)")),
    ("asof", re.compile(r"(?P<pre>\b[Aa]s of\s+)(?P<my>" + MY + r")(?P<post>)")),
]

HEAD_META = {"og:title", "twitter:title", "description", "og:description", "twitter:description",
             "og:image:alt", "twitter:image:alt"}
LD_KEYS = r"(?:headline|alternativeHeadline|description|name)"

TITLE_SPAN = re.compile(r"(<title[^>]*>)(.*?)(</title>)", re.S | re.I)
META_TAG = re.compile(r"<meta\b[^>]*>", re.S | re.I)
LD_BLOCK = re.compile(r"(<script[^>]+application/ld\+json[^>]*>)(.*?)(</script>)", re.S | re.I)
LD_STR = re.compile(r'("' + LD_KEYS + r'"\s*:\s*")((?:[^"\\]|\\.)*)(")')
# FAQ answers in JSON-LD mirror the visible FAQ, so they take the prose pass.
LD_TEXT = re.compile(r'("text"\s*:\s*")((?:[^"\\]|\\.)*)(")')
HEADING = re.compile(r"(<h([123])\b[^>]*>)(.*?)(</h\2>)", re.S | re.I)
MAIN = re.compile(r"(<main\b[^>]*>)(.*?)(</main>)", re.S | re.I)
DM = re.compile(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})([^"]*)"')
DEV_ID = re.compile(r'id="dev-(\d{4}-\d{2}-\d{2})')
DATA_MDL = re.compile(r'class="[^"]*\bdev-list\b[^"]*"[^>]*data-mdl="(\d+)"')
LI_META = re.compile(r'<meta\s+name="li:(status|next)"\s+content="([^"]*)"', re.I)


def label(ym):
    return f"{NAMES[ym[1]]} {ym[0]}"


def parse_ym(s):
    y, m = s.split("-")[:2]
    return int(y), int(m)


def unesc(s):
    return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            .replace("&mdash;", "—"))


def currency_months(value):
    """(year, month) of every currency stamp in a string."""
    out = []
    for _, rx in CURRENCY:
        for m in rx.finditer(value):
            mm = MYC.search(m.group("my"))
            out.append((int(mm.group(2)), MONTHS[mm.group(1)]))
    return out


# ---------------------------------------------------------------- transforms

def roll_text(value, new_label, kinds=None):
    """Roll every currency stamp in value to new_label. Returns (value, n)."""
    n = 0
    for kind, rx in CURRENCY:
        if kinds and kind not in kinds:
            continue
        value, k = rx.subn(lambda m: m.group("pre") + new_label + m.group("post"), value)
        n += k
    return value, n


def strip_text(value):
    """Remove every currency stamp from value. Returns (value, n, review)."""
    n, review = 0, False

    for kind, rx in CURRENCY:
        if kind == "update":
            value, k = rx.subn(lambda m: m.group("pre").rstrip(), value)
        elif kind in ("paren", "trailing"):
            value, k = rx.subn("", value)
        elif kind == "status":
            value, k = rx.subn(lambda m: m.group("post").lstrip(), value)
            review = review or k > 0
        elif kind == "stand":
            value, k = rx.subn(lambda m: re.sub(r"\s+in\s+$", "", m.group("pre")), value)
        else:  # asof: drop "as of Month YYYY," and recapitalise
            new, k = re.subn(r"\b([Aa])s of\s+" + MY + r",?\s*",
                             lambda m: "\x00CAP" if m.group(1) == "A" else "", value)
            new = re.sub("\x00CAP(.)", lambda m: m.group(1).upper(), new)
            value = new
            review = review or k > 0
        n += k
    value = re.sub(r"\s{2,}", " ", value).replace(" :", ":").replace(" ,", ",")
    return value, n, review


def apply_fields(html, fn, prose_fn=None):
    """Run fn(text) -> (text, n) over head fields, JSON-LD strings and h1-h3,
    and prose_fn, when given, over body prose and JSON-LD FAQ answer text.

    Returns (html, changes) where changes is a list of (field, before, after).
    """
    changes = []

    def run(field, value, f=None):
        new, n = (f or fn)(value)
        if n and new != value:
            changes.append((field, unesc(value), unesc(new)))
        return new

    html = TITLE_SPAN.sub(lambda m: m.group(1) + run("title", m.group(2)) + m.group(3), html, count=1)

    def meta(m):
        tag = m.group(0)
        key = re.search(r'(?:name|property)\s*=\s*"([^"]+)"', tag)
        if not key or key.group(1) not in HEAD_META:
            return tag
        return re.sub(r'(content\s*=\s*")([^"]*)(")',
                      lambda c: c.group(1) + run(key.group(1), c.group(2)) + c.group(3), tag, count=1)

    html = META_TAG.sub(meta, html)

    def ld(m):
        body = LD_STR.sub(lambda s: s.group(1) + run("json-ld " + s.group(1).split('"')[1], s.group(2)) + s.group(3),
                          m.group(2))
        if prose_fn:
            body = LD_TEXT.sub(lambda s: s.group(1) + run("json-ld faq text", s.group(2), prose_fn) + s.group(3), body)
        return m.group(1) + body + m.group(3)

    html = LD_BLOCK.sub(ld, html)
    html = HEADING.sub(lambda m: m.group(1) + run("h" + m.group(2), m.group(3)) + m.group(4), html)

    if prose_fn:
        def main(m):
            inner = m.group(2)
            # Headings were handled above; this pass is prose only.
            parts = re.split(r"(<h[123]\b.*?</h[123]>)", inner, flags=re.S | re.I)
            for i in range(0, len(parts), 2):
                parts[i] = run("body as-of", parts[i], prose_fn)
            return m.group(1) + "".join(parts) + m.group(3)
        html = MAIN.sub(main, html, count=1)
    return html, changes


def leftovers(html, old_ym):
    """Old-month mentions still in the head, JSON-LD or headings after a run."""
    old = label(old_ym)
    found = []
    head = html.split("</head>", 1)[0]
    for m in re.finditer(re.escape(old), head):
        found.append(("head", cdc.text(head[max(0, m.start() - 50):m.end() + 30])))
    for m in HEADING.finditer(html):
        if old in m.group(3):
            found.append(("h" + m.group(2), cdc.text(m.group(3))))
    seen, out = set(), []
    for where, snip in found:
        key = MYC.sub("", snip)[:60]
        if key not in seen:
            seen.add(key)
            out.append((where, snip))
    return out


def length_notes(html):
    """Title and meta description length against the house limits."""
    notes = []
    t = TITLE_SPAN.search(html)
    if t and len(unesc(cdc.text(t.group(2)))) > TITLE_MAX:
        notes.append(f"title is {len(unesc(cdc.text(t.group(2))))} chars (max {TITLE_MAX})")
    for tag in META_TAG.findall(html):
        if re.search(r'name\s*=\s*"description"', tag):
            c = re.search(r'content\s*=\s*"([^"]*)"', tag)
            n = len(unesc(c.group(1))) if c else 0
            if not 110 <= n <= 160:
                notes.append(f"meta description is {n} chars (house range 110-160)")
    return notes


def set_date(html, new_iso):
    """Move dateModified and both visible stamps to new_iso. Returns (html, old_iso)."""
    m = DM.search(html)
    if not m:
        raise SystemExit("no JSON-LD dateModified on the page")
    old_iso = m.group(1)
    if new_iso < old_iso:
        raise SystemExit(f"--date {new_iso} is earlier than dateModified {old_iso}")
    html = re.sub(r'("dateModified"\s*:\s*")' + re.escape(old_iso), r"\g<1>" + new_iso, html)
    html = re.sub(r'(property="article:modified_time"\s+content=")' + re.escape(old_iso),
                  r"\g<1>" + new_iso, html)
    old_d, new_d = date.fromisoformat(old_iso), date.fromisoformat(new_iso)
    old_txt = f"{NAMES[old_d.month]} {old_d.day}, {old_d.year}"
    new_txt = f"{NAMES[new_d.month]} {new_d.day}, {new_d.year}"

    def visible(region):
        region = region.replace(f'datetime="{old_iso}"', f'datetime="{new_iso}"')
        return re.sub(re.escape(old_txt).replace(r"\ ", r"\s+"), new_txt, region)

    html = re.sub(r'<p class="article-date">.*?</p>', lambda r: visible(r.group(0)), html, flags=re.S)
    html = re.sub(r'<strong>\s*Last Updated:\s*</strong>.*?(?:</p>|</li>|</div>|\n)',
                  lambda r: visible(r.group(0)), html, flags=re.S | re.I)
    return html, old_iso


def check(path, today):
    errors, _ = cdc.scan(path, None, None)
    return errors


# ---------------------------------------------------------------------- plan

def load_counts(root):
    p = root / "data" / "mdl_counts.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def plan_rows(root, target, today, evidence=None):
    counts = load_counts(root)
    evidence = evidence or {}
    rows, done, generated = [], [], []
    for path in sorted(root.glob("*.html")):
        html = path.read_text(encoding="utf-8", errors="ignore")
        tm = TITLE_SPAN.search(html)
        if not tm:
            continue
        title = cdc.text(tm.group(2))
        cur = currency_months(title)
        if not cur:
            continue
        stamp = max(cur)
        if path.name in GENERATED:
            generated.append((path.name, GENERATED[path.name]))
            continue
        dmm = DM.search(html)
        dm_iso = dmm.group(1) if dmm else ""
        dm_ym = parse_ym(dm_iso) if dm_iso else None
        if stamp >= target and dm_ym and dm_ym >= target:
            done.append(path.name)
            continue

        r = {"page": path.name, "title": unesc(title), "stamp": stamp, "dm": dm_iso}
        devs = sorted(DEV_ID.findall(html))
        r["newest"] = devs[-1] if devs else ""
        meta = {k.lower(): unesc(v) for k, v in LI_META.findall(html)}
        r["status"] = meta.get("status", "")
        nxt = meta.get("next", "")
        r["next"], r["next_passed"] = "", False
        if "|" in nxt:
            nd, what = nxt.split("|", 1)
            r["next"] = f"{nd} {what}"
            r["next_passed"] = nd < today.isoformat() and (not dm_iso or nd > dm_iso)
        mdl = DATA_MDL.search(html)
        r["mdl"] = ""
        if mdl and counts.get("mdls", {}).get(mdl.group(1)):
            c = counts["mdls"][mdl.group(1)]
            r["mdl"] = (f"MDL {mdl.group(1)}: {c.get('pending'):,} pending "
                        f"(was {c.get('prior'):,}) per JPML {counts.get('report_date', '?')}")
        passed = []
        if dmm:
            d = tuple(int(x) for x in dm_iso.split("-"))
            _, warns = cdc.body_dates(html, d, (today.year, today.month, today.day))
            passed = [w for w in warns if "scheduled" in w]
        r["passed"] = passed
        ev = evidence.get(path.stem, {})
        r["topic"] = ev.get("topic", "")
        r["severity"] = ev.get("severity", "")
        items = ev.get("items", [])
        r["items"] = items
        r["items_since"] = [i for i in items if (i.get("date") or "") > dm_iso]
        # The Panel's latest count from BigQuery beats data/mdl_counts.json.
        live = ev.get("mdl") or []
        if live:
            r["mdl"] = "; ".join(f"MDL {c['mdl']}: {c['pending']:,} pending (was {c.get('prior') or 0:,}) "
                                 f"per JPML {c['report_date']}" for c in live)
        rolled, _ = roll_text(title, label(target))
        r["rolled"], r["rolled_len"], r["title_len"] = rolled, len(rolled), len(unesc(title))
        age = (today - date.fromisoformat(dm_iso)).days if dm_iso else None
        r["age"] = age
        if r["items_since"]:
            n = len(r["items_since"])
            kinds = sorted({i.get("kind", "item") for i in r["items_since"]})
            r["call"] = (f"MOVED: {n} {'/'.join(kinds)} item{'s' if n != 1 else ''} since the edit. "
                         f"Update, then stamp.")
        elif r["next_passed"] or passed:
            r["call"] = "MOVED: a scheduled date passed since the edit. Update, then stamp."
        elif evidence and path.stem in evidence and not items:
            r["call"] = (f"QUIET: the wire review lists nothing for this page since {dm_iso}. "
                         f"De-stamp unless you know of movement.")
        elif evidence and path.stem in evidence:
            n = len(items)
            r["call"] = (f"QUIET: the topic's {n} waiting item{'s' if n != 1 else ''} "
                         f"{'predate' if n != 1 else 'predates'} the {dm_iso} edit. "
                         f"De-stamp unless you know of movement.")
        elif age is not None and age > 45:
            r["call"] = f"QUIET {age} days: de-stamp unless the docket moved."
        else:
            r["call"] = f"CHECK the docket since {dm_iso}: roll if it moved, de-stamp if not."
        rows.append(r)
    return rows, done, generated, counts


def plan_markdown(rows, done, generated, counts, target, today):
    L = [f"## Month roll: {label(target)}", "",
         "Rule: roll a stamp only when the docket moved and the page was updated with it. "
         "If only the calendar moved, de-stamp. Never roll a month onto an unchanged page.", ""]
    if rows:
        L += ["| Page | Title stamp | dateModified | Next date | Call |", "|---|---|---|---|---|"]
        for r in rows:
            nxt = r["next"] + (" (PASSED)" if r["next_passed"] else "") if r["next"] else ""
            L.append(f"| `{r['page']}` | {label(r['stamp'])} | {r['dm']} | {nxt} | {r['call']} |")
        L += ["", "### Evidence by page", ""]
        for r in rows:
            L.append(f"**{r['page']}**")
            L.append(f"- Title now: {r['title']}")
            warn = ""
            if r["rolled_len"] > TITLE_MAX:
                warn = (f" (over {TITLE_MAX}; already {r['title_len']} before the roll)"
                        if r["title_len"] > TITLE_MAX else f" (over {TITLE_MAX}: shorten on the roll)")
            L.append(f"- Title if rolled: {r['rolled']} ({r['rolled_len']} chars){warn}")
            if r["status"]:
                L.append(f"- Status line: {r['status']}")
            if r["newest"]:
                L.append(f"- Newest dated entry on the page: {r['newest']}")
            if r["mdl"]:
                L.append(f"- {r['mdl']}")
            for p in r["passed"]:
                L.append(f"- Body: {p}")
            if r.get("severity"):
                L.append(f"- Wire review: {r['severity']} on \"{r['topic']}\"")
            shown = r.get("items_since") or []
            if shown:
                L.append(f"- Waiting since the edit ({len(shown)}):")
                for i in shown[:8]:
                    t = i.get("title") or "(untitled)"
                    link = f"[{t}]({i['url']})" if i.get("url") else t
                    src = f" — {i['source']}" if i.get("source") else ""
                    L.append(f"  - {i.get('date', '')} {i.get('kind', '')}: {link}{src}")
                if len(shown) > 8:
                    L.append(f"  - and {len(shown) - 8} more in wire.review_items")
            older = [i for i in (r.get("items") or []) if i not in shown]
            if older:
                L.append(f"- On the topic before the edit ({len(older)}), presumably covered: " +
                         "; ".join((i.get("title") or "")[:70] for i in older[:3]))
            L.append("")
    else:
        L += ["Nothing to roll: every month-stamped page is current.", ""]
    if done:
        L += [f"Already rolled ({len(done)}): " + ", ".join(f"`{d}`" for d in done), ""]
    for name, why in generated:
        L += [f"Skipped `{name}`: {why}.", ""]
    rd = counts.get("report_date", "")
    L += ["### Also this month", ""]
    if rd and parse_ym(rd) < target:
        L.append(f"- `data/mdl_counts.json` still carries the JPML report of {rd}. "
                 "Update it once the Panel posts this month's report (network-ops jpml_to_bq).")
    elif rd:
        L.append(f"- `data/mdl_counts.json` is on the {rd} JPML report.")
    L += ["- Intelligencer: the masthead issue line rolls itself on the 1st (Issue roll workflow). "
          "`mass-tort-map` and `state-ai-enforcement-tracker` roll only with their monthly rewrite.",
          "", "### Commands", "",
          "After the content edit on a page that moved:",
          "```", "python3 month_roll.py stamp <page>.html --date YYYY-MM-DD", "```",
          "For pages that did not move: run Informer's **Month roll** workflow with the page names, "
          "or locally:",
          "```", "python3 month_roll.py destamp <page>.html <page>.html", "```", "",
          f"_Generated {today.isoformat()} by month_roll.py._"]
    return "\n".join(L)


def cmd_plan(args, root, target, today):
    evidence = None
    if args.evidence:
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    rows, done, generated, counts = plan_rows(root, target, today, evidence)
    md = plan_markdown(rows, done, generated, counts, target, today)
    if args.md:
        Path(args.md).write_text(md + "\n", encoding="utf-8")
    print(f"Month roll plan for {label(target)}: {len(rows)} to decide, {len(done)} already rolled")
    for r in rows:
        print(f"\n  {r['page']}  [{label(r['stamp'])}, dateModified {r['dm']}]")
        print(f"      {r['call']}")
        if r["next"]:
            print(f"      next: {r['next']}{'  (PASSED)' if r['next_passed'] else ''}")
        for p in r["passed"]:
            print(f"      body: {p}")
        for i in (r.get("items_since") or [])[:4]:
            print(f"      {i.get('date', '')} {i.get('kind', '')}: {(i.get('title') or '')[:100]}")
        if r["rolled_len"] > TITLE_MAX:
            was = f", already {r['title_len']} now" if r["title_len"] > TITLE_MAX else ""
            print(f"      rolled title is {r['rolled_len']} chars{was}: {r['rolled']}")
    for name, why in generated:
        print(f"\n  skipped {name}: {why}")
    return 0


# ------------------------------------------------------------- stamp/destamp

def pages(args, root):
    out = []
    for p in args.pages:
        path = root / (p if p.endswith(".html") else p + ".html")
        if not path.exists():
            raise SystemExit(f"no such page: {path.name}")
        if path.name in GENERATED:
            raise SystemExit(f"{path.name}: {GENERATED[path.name]}")
        out.append(path)
    return out


def report(path, changes, extra=()):
    print(f"\n  {path.name}")
    for field, before, after in changes:
        print(f"      {field}:")
        print(f"         was  {before[:160]}")
        print(f"         now  {after[:160]}")
    for line in extra:
        print(f"      {line}")


def cmd_stamp(args, root, target, today):
    bad = 0
    for path in pages(args, root):
        html = path.read_text(encoding="utf-8")
        extra = []
        if args.date:
            html, old = set_date(html, args.date)
            extra.append(f"dateModified and visible stamps: {old} -> {args.date}")
        m = DM.search(html)
        dm_ym = parse_ym(m.group(1)) if m else None
        if dm_ym != target:
            print(f"\n  {path.name}: REFUSED. dateModified is {m.group(1) if m else 'missing'}; "
                  f"a {label(target)} stamp needs a {label(target)} edit. Update the content, "
                  f"then pass --date with the edit day.")
            bad += 1
            continue
        tm = TITLE_SPAN.search(html)
        cur = currency_months(cdc.text(tm.group(2))) if tm else []
        old_ym = max(cur) if cur else None
        new_label = label(target)
        html, changes = apply_fields(html, lambda v: roll_text(v, new_label),
                                     prose_fn=lambda v: roll_text(v, new_label, kinds={"asof"}))
        if old_ym and old_ym != target:
            for where, snippet in leftovers(html, old_ym):
                extra.append(f"still names {label(old_ym)} ({where}), read it: {snippet[:140]}")
        rolled_facts = [c for c in changes if c[0] in ("body as-of", "json-ld faq text")]
        if rolled_facts:
            extra.append(f"CONFIRM: {len(rolled_facts)} 'as of' statement(s) in the body/FAQ now claim "
                         f"{new_label}. Each must still be true on the edit day.")
        extra += length_notes(html)
        report(path, changes, extra)
        if not args.dry_run:
            path.write_text(html, encoding="utf-8")
            for e in check(path, today):
                print(f"      DATE GATE: {e}")
                bad += 1
    return 1 if bad else 0


def cmd_destamp(args, root, target, today):
    bad = 0
    for path in pages(args, root):
        html = path.read_text(encoding="utf-8")
        tm = TITLE_SPAN.search(html)
        cur = currency_months(cdc.text(tm.group(2))) if tm else []
        if not cur:
            print(f"\n  {path.name}: no currency stamp in the title, nothing to remove")
            continue
        old_ym = max(cur)
        title_txt = cdc.text(tm.group(2))
        if CURRENCY[3][1].search(title_txt) and not any(rx.search(title_txt) for k, rx in CURRENCY if k != "status"):
            print(f"\n  {path.name}: REFUSED. The title's month is its own clause "
                  f"(\"{unesc(title_txt)}\"); cutting it leaves a bare 'Status'. Retitle by hand, "
                  f"then run destamp for the rest of the page.")
            bad += 1
            continue
        review = []

        def fn(v):
            new, n, rv = strip_text(v)
            if rv:
                review.append(1)
            return new, n

        html, changes = apply_fields(html, fn)
        extra = [f"{where} still names {label(old_ym)}, read it: {s[:140]}"
                 for where, s in leftovers(html, old_ym)]
        if review:
            extra.append("a 'Month YYYY Status' or 'as of' stamp was cut: read the new wording")
        extra += length_notes(html)
        extra.append("dateModified and visible stamps left as they were (de-stamp is not an edit)")
        report(path, changes, extra)
        if not args.dry_run:
            path.write_text(html, encoding="utf-8")
            for e in check(path, today):
                print(f"      DATE GATE: {e}")
                bad += 1
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["plan", "stamp", "destamp"])
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--month", help="target month YYYY-MM (default: this month, UTC; for stamp: the --date month)")
    ap.add_argument("--date", help="stamp: the edit day YYYY-MM-DD; moves dateModified and visible stamps")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    ap.add_argument("--md", help="plan: write the Markdown report here")
    ap.add_argument("--evidence", help="plan: JSON of wire/docket items and MDL counts per page")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default=".")
    args = ap.parse_args()

    root = Path(args.path)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    if args.month:
        target = parse_ym(args.month)
    elif args.command == "stamp" and args.date:
        target = parse_ym(args.date)
    else:
        target = (today.year, today.month)
    if args.command != "plan" and not args.pages:
        ap.error(f"{args.command} needs at least one page")
    return {"plan": cmd_plan, "stamp": cmd_stamp, "destamp": cmd_destamp}[args.command](args, root, target, today)


if __name__ == "__main__":
    sys.exit(main())
