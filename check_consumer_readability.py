#!/usr/bin/env python3
"""Check that consumer-facing AI pages read for a consumer.

Companion to check_date_consistency.py. That script catches pages that lie
about when they were updated. This one catches pages written for the wrong
reader: trade vocabulary, run-on enumerations, FAQ markup that disagrees
with the page, and copy that tells a visitor whether they have a claim.

Every rule here exists because the defect was found by hand on a live page,
not because it seemed like a good idea.

Scope
-----
PAGES below, which is the AI-litigation cluster plus the listing pages that
carry its cards. Everything else on the site is out of scope: the asbestos
and tort-update pages have a different reader and a different voice, and
running these thresholds against them would produce noise, not signal.

Rules
-----
ERROR  Reader-adjudicating language. Copy that tells a visitor they do or do
       not have a claim. The site is operated by a licensed attorney and
       cannot make that call about a reader it knows nothing about. This is
       the only rule that is always an error regardless of page.
ERROR  FAQ schema that does not match the visible FAQ. Either a question in
       the markup has no visible answer on the page, or a visible answer has
       drifted from the one in the markup. Google expects FAQ content to be
       visible, and drifted answers go stale invisibly.
ERROR  Grade level above GRADE_MAX on a case page. These pages are read by
       families, often in the worst week of their lives.
WARN   Jargon term from BLOCKLIST. Each has a plain equivalent. Some survive
       review (a docket number, a statute a page is genuinely about), so
       this warns rather than blocks.
WARN   Sentence at or above SENTENCE_MAX words. Usually an enumeration that
       wants to be a list.
WARN   Ellipses, or a title over 60 / description outside 110-160. House
       conventions, checked here because nothing else checks them.

Usage
-----
    python3 check_consumer_readability.py              # report, exit 0
    python3 check_consumer_readability.py --strict     # exit 1 on any ERROR
    python3 check_consumer_readability.py --page X.html
"""
import json
import re
import sys
from pathlib import Path

try:
    import textstat
except ImportError:
    sys.exit("needs textstat:  pip install textstat --break-system-packages")

GRADE_MAX = 10.5
SENTENCE_MAX = 45

# Case pages held to GRADE_MAX. Hubs and listing pages are scanned for
# everything else but not graded, since card text skews the score.
CASE_PAGES = [
    "raine-v-openai-lawsuit.html",
    "parish-v-openai-lawsuit.html",
    "lacey-v-openai-lawsuit.html",
    "shamblin-v-openai-lawsuit.html",
    "carrier-v-openai-lawsuit.html",
    "chatgpt-overdose-lawsuit-scott.html",
    "chatgpt-fsu-shooting-lawsuit.html",
    "tumbler-ridge-openai-lawsuits.html",
    "garcia-v-character-ai-lawsuit.html",
    "openai-school-shooting-lawsuits-ai-product-liability.html",
]
OTHER_PAGES = [
    "openai-lawsuits.html",
    # State enforcement action. No claimant pool, so it is not a page a family
    # lands on to find out whether they have a claim, and the case-page grade
    # ceiling does not fit it. Excluded from the CTA sweep for the same reason.
    "florida-v-openai-lawsuit.html",
    "jccp-5431-chatgpt-product-liability-cases.html",
    "ai-output-product-or-content.html",
    "ai-lawsuits.html",
    "character-ai-lawsuit.html",
    "news-and-analysis.html",
    "browse-lawsuits.html",
]
PAGES = CASE_PAGES + OTHER_PAGES

# Trade vocabulary with a plain equivalent. Value is the suggestion shown.
BLOCKLIST = {
    r"\bdoctrinal(ly)?\b": "say what the question is",
    r"\bcauses? of action\b": "claims",
    r"\bpleads?\b|\bpleaded\b|\bpleading\b": "says / argues",
    r"\bdispositive\b": "rulings that end the case",
    r"\bpretrial\b": "before trial",
    r"\bcognizable\b": "drop it",
    r"\bpreclusive\b": "drop it",
    r"\bthreshold (question|dispute)\b": "the question that comes first",
    r"\bsafer alternative design\b": "a safer version was possible",
    r"\bstrict products? liability\b": "treating it like a defective product",
    r"\bproximate cause\b": "whether it actually caused the harm",
    r"\bbattleground\b": "combat metaphor",
    r"\bplaybook\b": "trade framing",
    r"\bpotential value\b": "never describe a death case's value",
    r"\bdocket\b": "cases / the courts",
    r"\bpatterned? (its|their) theories\b": "borrowed from",
    r"\bmoving papers\b|\bmotion practice\b": "arguments before the judge",
}

ADJUDICATING = [
    r"would not cover you",
    r"you do not have a (claim|case)",
    r"you have no (claim|case)",
    r"does not apply to you",
    r"for most people reading this,? no",
    r"you (cannot|can't) sue",
    r"this will not affect you",
    r"you are not eligible",
]

STRIP = re.compile(
    r"<script.*?</script>|<style.*?</style>|<header.*?</header>"
    r"|<footer.*?</footer>|<nav.*?</nav>", re.S | re.I)
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def visible_text(html):
    body = STRIP.sub(" ", html)
    body = re.sub(r"<[^>]+>", " ", body)
    body = (body.replace("&mdash;", "-").replace("&rsquo;", "'")
                .replace("&amp;", "&").replace("&nbsp;", " "))
    return " ".join(body.split())


def visible_faq(html):
    """Question -> answer for the on-page FAQ, if there is one.

    Anchor on the heading element, never on bare text. Pages carry a
    table-of-contents link with the same wording, and matching that instead
    of the real heading yields an empty section and a page-full of phantom
    "not visible" errors.
    """
    m = re.search(r'<h2[^>]*\bid="faq"', html)
    if not m:
        m = re.search(r"<h2[^>]*>[^<]*(?:Common [Qq]uestions|Frequently [Aa]sked)", html)
    if not m:
        return {}
    start = m.start()
    stops = [html.find("<h2", start + 10)]
    for tag in ("<footer", "</main>", "</article>"):
        k = html.find(tag, start + 10)
        if k > 0:
            stops.append(k)
    stops = [k for k in stops if k > 0]
    end = min(stops) if stops else len(html)
    chunk = html[start:end]
    out = {}
    for m in re.finditer(r"<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", chunk, re.S):
        q = " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split())
        a = " ".join(re.sub(r"<[^>]+>", "", m.group(2)).split())
        out[norm(q)] = norm(a)
    return out


def schema_faq(html):
    out = {}
    for block in LD.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "FAQPage":
            continue
        for q in data.get("mainEntity", []):
            name = q.get("name", "")
            ans = q.get("acceptedAnswer", {}).get("text", "")
            out[norm(name)] = norm(ans)
    return out


def norm(s):
    s = (s.replace("&rsquo;", "'").replace("&amp;", "&")
          .replace("&mdash;", "-").replace("\u2019", "'"))
    return " ".join(s.split())


def check(path):
    html = path.read_text(encoding="utf-8")
    name = path.name
    text = visible_text(html)
    errors, warnings = [], []

    for pat in ADJUDICATING:
        for m in re.finditer(pat, text, re.I):
            errors.append(f"tells the reader whether they have a claim: "
                          f"...{text[max(0, m.start()-60):m.end()+60]}...")

    vis, sch = visible_faq(html), schema_faq(html)
    if sch:
        for q, a in sch.items():
            if q not in vis:
                errors.append(f"FAQ schema question is not visible on the page: {q!r}")
            elif vis[q] != a:
                errors.append(f"FAQ answer differs between page and schema: {q!r}")

    if name in CASE_PAGES:
        grade = textstat.flesch_kincaid_grade(text)
        if grade > GRADE_MAX:
            errors.append(f"reading grade {grade:.1f} is above {GRADE_MAX} "
                          f"for a case page read by families")

    for pat, hint in BLOCKLIST.items():
        hits = re.findall(pat, text, re.I)
        if hits:
            warnings.append(f"{len(hits)}x {pat.strip(chr(92)+'b')}  ->  {hint}")

    for s in re.split(r"(?<=[.!?])\s+", text):
        n = len(s.split())
        if n >= SENTENCE_MAX:
            warnings.append(f"{n}-word sentence: {s[:90]}...")

    if "..." in html or "\u2026" in html:
        warnings.append("ellipses present (house style: none)")

    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    if t and len(norm(t.group(1))) > 60:
        warnings.append(f"title {len(norm(t.group(1)))} chars (max 60)")
    d = re.search(r'name="description"\s*\n?\s*content="([^"]+)"', html)
    if d and not (110 <= len(d.group(1)) <= 160):
        warnings.append(f"meta description {len(d.group(1))} chars (want 110-160)")

    return errors, warnings


def main():
    strict = "--strict" in sys.argv
    root = Path(".")
    only = None
    if "--page" in sys.argv:
        only = sys.argv[sys.argv.index("--page") + 1]

    targets = [root / p for p in PAGES if (only is None or p == only)]
    targets = [p for p in targets if p.exists()]
    if not targets:
        print("no pages found; run from the repo root")
        return 1

    n_err = n_warn = 0
    print(f"Consumer readability check - {len(targets)} pages "
          f"(grade max {GRADE_MAX}, sentence max {SENTENCE_MAX})\n")
    for path in targets:
        errors, warnings = check(path)
        if not errors and not warnings:
            continue
        print(path.name)
        for e in errors:
            n_err += 1
            print(f"    ERROR  {e}")
        for w in warnings:
            n_warn += 1
            print(f"    warn   {w}")
        print()

    print(f"{n_err} errors, {n_warn} warnings across {len(targets)} pages.")
    if strict and n_err:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
