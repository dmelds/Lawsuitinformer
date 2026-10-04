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
ERROR  The two visible "Last Updated" stamps disagree with each other. A page
       carries one under the byline and a second in the article-meta footer,
       and nothing tied them together, so editing one and not the other left
       the page showing a reader two different dates.
ERROR  A visible stamp is NEWER than dateModified. Same false-freshness case as
       above, in the one place a reader actually looks.
WARN   A visible stamp is OLDER than dateModified. The page was edited and that
       stamp did not move.
ERROR  The body describes an event, in past tense, dated AFTER dateModified.
       The page reports a ruling it claims to predate: it was edited after that
       ruling and the stamp was not rolled (house-ncaa-settlement-update,
       10/4/26: three October docket events under a September 16 stamp, every
       stamp on the page agreeing with every other). Not time-dependent, so it
       runs under --strict.
WARN   The body cites a scheduled date (set for, due, runs to) that is AFTER
       dateModified and has now passed. The page was right when written and the
       calendar moved past it; nothing on the page says what happened.
       Time-dependent like the calendar rule, so off under --strict.
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
og:description, twitter:description, first <h1>, both visible "Last Updated"
byline stamps, and the headline/description
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

# Visible "Last Updated" stamps. These use "Month D, YYYY" rather than the bare
# "Month YYYY" the STAMP pattern looks for, so STAMP cannot see them at all.
#
# Both patterns tolerate markup between the label and the date. Six pages wrap
# the stamp in a <time> element (afff, depo-provera, ozempic, roundup, talcum and
# tylenol updates pages). The old BYLINE capture was [^<]+?, which stops at the
# "<" of <time>, and the old FOOTER required the date to follow </strong> with
# nothing in between. On those six pages BOTH visible checks silently matched
# nothing, so the page reported clean without either stamp ever being read.
# WRAP allows any run of tags before the date while still anchoring on a real
# date, so a missing stamp stays a miss rather than a runaway capture.
FULLDATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*(20\d{2})\b")
WRAP = r'(?:<[^>]+>\s*)*'
DATETEXT = r'([A-Za-z]+\s+\d{1,2},\s*20\d{2})'
BYLINE = re.compile(
    r'<p class="article-date">\s*Last updated:\s*' + WRAP + DATETEXT,
    re.S | re.I)
FOOTER = re.compile(
    r'<strong>\s*Last Updated:\s*</strong>\s*' + WRAP + DATETEXT,
    re.S | re.I)


# Body dates. Everything above reads the stamps and the metadata. None of it
# reads the prose, so a page can narrate an October ruling under September
# stamps and pass clean. The body scan takes <main>, drops script/style/nav/
# footer blocks and the two visible stamps, then reads the sentence around each
# "Month D, YYYY" date that falls after dateModified.
#
# Which tier a hit lands in depends on the words in that sentence. Scheduling
# language wins over past tense when both appear, because "trial now begins
# October 26" is a schedule even though "reset" sits earlier in the paragraph.
# A sentence with neither is reported as a WARN so a reader can decide; the
# scan classifies, it does not adjudicate.
MAIN = re.compile(r"<main\b.*?</main>", re.S | re.I)
DROP = re.compile(r"<(script|style|nav|footer|noscript)\b.*?</\1>", re.S | re.I)
ARTICLE_DATE = re.compile(r'<p class="article-date">.*?</p>', re.S | re.I)
SCHED = re.compile(
    r"\b(set for|is set|was set|were set|are set|set to|scheduled|expected|"
    r"runs? to|due|deadline|will|would|tentatively|through|until|by|"
    r"starts?|begins?|closes?|opens?|hears?|takes? up)\b", re.I)
PAST = re.compile(
    r"\b(filed|ruled|denied|granted|ordered|held|overruled|signed|issued|"
    r"entered|reset|dismissed|withdrew|withdrawn|served|sued|announced|argued|"
    r"refused|rejected|affirmed|reversed|vacated|approved|adopted|certified|"
    r"settled|paid|reported|released|published|appealed|asked|sought|barred|"
    r"blocked|found|came|went|ended|opposed|tied|cut|turned down|stepped in)\b",
    re.I)
# Prose states a year once and drops it: "On September 16, 2026, Judge Boyle
# reset them. Mousser now begins October 26." A yearless date is read in the
# dateModified year. If that lands more than YEARLESS_WINDOW days after the
# stamp it is taken as last year's date and ignored: an unstamped edit is
# weeks behind its stamp, not most of a year, and a January page saying
# "October 2" means the October before. Carrying the year forward from the
# previous full date was tried and rejected: one "September 7, 2027" trial
# date pulled every later yearless date on the page into 2027.
# Capitalised month only, so "may 30 days" is not a date.
YEARLESS_WINDOW = 120
MONTHDAY = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\b(?!,?\s*20\d{2})(?!\d)")
# A document dated after the stamp is the same failure as an event dated after
# it: nobody cites an October 2 status report in a September 16 edit. The date
# sits directly in front of the document noun ("October 2, 2026 joint status
# report"), so CITES is matched against the text right after the date, not the
# whole sentence. "The order puts the records in their hands on October 30" is
# a schedule and must not land here.
CITES = re.compile(
    r"^\s*,?\s*(?:joint\s+)?(?:status\s+|case\s+management\s+|minute\s+)?"
    r"(report|order|ruling|opinion|filing|letter|notice|entry|transcript|"
    r"complaint|motion|brief|decision)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def text(raw):
    return " ".join(TAGS.sub(" ", raw or "").split())


def body_text(html):
    """Prose a reader sees, with the stamps and non-content blocks removed."""
    m = MAIN.search(html)
    raw = m.group(0) if m else html
    raw = DROP.sub(" ", raw)
    raw = ARTICLE_DATE.sub(" ", raw)
    raw = FOOTER.sub(" ", raw)
    return text(raw)


def body_dates(html, dm_full, today_ymd):
    """Classify body dates after dateModified. Returns (errors, warnings)."""
    errors, warnings = [], []
    if not dm_full:
        return errors, warnings
    prose = body_text(html)
    sentences = SENTENCE.split(prose)
    seen = set()
    dm_dt = datetime(*dm_full)
    for sent in sentences:
        found = []
        for m in FULLDATE.finditer(sent):
            found.append((m.start(), int(m.group(3)), MONTHS[m.group(1)],
                          int(m.group(2)), m.group(0)))
        for m in MONTHDAY.finditer(sent):
            found.append((m.start(), None, MONTHS[m.group(1)],
                          int(m.group(2)), m.group(0)))
        for start, y, mo, d, raw in sorted(found):
            after = sent[start + len(raw):]
            yearless = y is None
            if yearless:
                y = dm_full[0]
            ymd = (y, mo, d)
            try:
                dt = datetime(*ymd)
            except ValueError:
                continue
            if ymd <= dm_full:
                continue
            if yearless and (dt - dm_dt).days > YEARLESS_WINDOW:
                continue
            if ymd in seen:
                continue
            seen.add(ymd)
            dm_raw = "%04d-%02d-%02d" % dm_full
            if SCHED.search(sent):
                if today_ymd and ymd <= today_ymd:
                    warnings.append(
                        f"body says something was scheduled for {raw}; that date "
                        f"has passed and the page has not been updated since "
                        f"{dm_raw}")
            elif PAST.search(sent) or CITES.search(after):
                errors.append(
                    f"body describes an event or document dated {raw} but "
                    f"dateModified is {dm_raw} — the page was edited after that "
                    f"date and the stamp was not rolled")
            elif today_ymd and ymd <= today_ymd:
                warnings.append(
                    f"body cites {raw}, after dateModified {dm_raw} — check "
                    f"whether this is a past event or a schedule")
    return errors, warnings


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


def full_date(value):
    """Return (year, month, day) from a 'Month D, YYYY' string, or None."""
    m = FULLDATE.search(value or "")
    if not m:
        return None
    return (int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def modified_ymd(value):
    """Return (year, month, day) from an ISO dateModified, or None."""
    if not value:
        return None
    m = re.match(r"(20\d{2})-(\d{2})-(\d{2})", value)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def modified_ym(value):
    if not value:
        return None
    m = re.match(r"(20\d{2})-(\d{2})", value)
    return (int(m.group(1)), int(m.group(2))) if m else None


def scan(path, now_ym=None, today_ymd=None):
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
    dm_full = modified_ymd(dm_raw)

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
    # Visible byline stamps. These are the only dates a reader actually sees,
    # and they sit outside every field above: one under the byline, a second in
    # the article-meta footer. Nothing tied the two to each other or to
    # dateModified, so a page could be genuinely updated, have its byline moved,
    # and keep telling readers a date months behind in the footer.
    visible = []
    for name, rx in (("byline", BYLINE), ("footer", FOOTER)):
        vm = rx.search(html)
        if not vm:
            continue
        raw = text(vm.group(1))
        ymd = full_date(raw)
        if ymd:
            visible.append((name, ymd, raw))

    if len(visible) == 2 and visible[0][1] != visible[1][1]:
        errors.append(
            f"byline says {visible[0][2]} but footer says {visible[1][2]} — "
            f"two different visible Last Updated dates on one page"
        )

    if dm_full:
        for name, ymd, raw in visible:
            if ymd > dm_full:
                errors.append(
                    f"{name} stamp {raw} is newer than dateModified {dm_raw} — "
                    f"the page shows a date it was never edited on"
                )
            elif ymd < dm_full:
                warnings.append(
                    f"{name} stamp {raw} is older than dateModified {dm_raw} — "
                    f"page was edited, stamp was not"
                )

    h_stamps = stamps(h1)
    if h_stamps and dm and max(h_stamps) < dm and not t_stamps:
        warnings.append(
            f"h1 stamp {label(max(h_stamps))} is older than dateModified {dm_raw}"
        )

    b_err, b_warn = body_dates(html, dm_full, today_ymd)
    errors.extend(b_err)
    warnings.extend(b_warn)

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
    # The passed-schedule rule needs today's date, which makes it time-dependent
    # in exactly the way the calendar rule is. Same gate.
    today_ymd = (today.year, today.month, today.day) if calendar else None

    bad, warned, scanned = {}, {}, 0
    for path in sorted(root.rglob("*.html")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        scanned += 1
        errors, warnings = scan(path, now_ym, today_ymd)
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
