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
Two tiers.

SITEWIDE, every page: the reader-adjudicating rule, the FAQ-schema rule,
the paragraph-length rule and the CTA rules (CTA_EXEMPT aside). All three are universal by nature. Copy that tells a visitor whether they have a
claim is wrong on any page the site publishes, and FAQ markup that disagrees
with the page is broken markup wherever it sits. Scoping them to one cluster
was an accident of how this script grew: on 2026-09-05 a sitewide run found
169 drifted FAQ questions across 47 pages, 31 of which were declaring
questions to Google that appeared nowhere on the page.

PAGES below, the AI-litigation cluster: everything else. The jargon
blocklist, sentence length, ellipses and the title/description conventions
are calibrated for that cluster's reader and would be noise elsewhere. The
grade ceiling applies to CASE_PAGES only, since card text on hubs skews the
score.

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
WARN   Prose block (<p>, <li>, <blockquote>, <dd>, <td>) at or above
       PARAGRAPH_MAX words, sitewide. Added 2026-09-25
       after a 171-word, eight-sentence paragraph on meta-lawsuit.html that
       carried a case's filing, verdict, penalty and the company's response
       as one block. A reader on a phone sees a wall. Split at the change of
       subject: what happened, what the jury found, what comes next. When
       the rule was added, 120 words flagged 34 paragraphs on 19 pages.
       Widened the same day to list items and other prose blocks after a
       199-word <li> on openai-lawsuits.html passed unflagged.
WARN   Ellipses, or a title over 60 / description outside 110-160. House
       conventions, checked here because nothing else checks them.
WARN   CTA set, sitewide outside CTA_EXEMPT. Added 2026-10-02 after a
       rewrite of peritoneal-mesothelioma.html shipped with only the two
       closing boxes it inherited, both reporting under one utm_content
       slot, while the strongest asbestos pages carry a top strip and
       mid-page CTAs. A CTA here is an <a> to lawsuit.center outside header,
       nav and footer, matching what the cta_click listener counts. The page
       is flagged when it has fewer than CTA_MIN of them, none before the
       second <h2> (the reader's first screen or two), two that share a
       utm_content slot, or one with no utm_content at all. A shared or
       missing slot means GA4 cannot say which placement earned the click.
       When the rule was added it flagged 212 of the 245 pages it covers:
       160 with fewer than CTA_MIN, 85 of those with none at all, 122 with
       nothing before the second <h2>, 6 sharing a slot and 4 with untagged
       links. mesothelioma-lawsuit.html and who-qualifies-for-an-asbestos-
       lawsuit.html were among the 85: their CTA boxes link to other
       Informer pages, never to Center.

Setup
-----
textstat scores grade level with NLTK's CMU pronouncing dictionary, which it
downloads on first use. Where that download is refused (a sandbox whose proxy
NLTK's SSRF guard rejects, or a host that cannot reach
raw.githubusercontent.com), fetch the same file with git instead:

    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/nltk/nltk_data.git /tmp/nltk_data_src
    git -C /tmp/nltk_data_src sparse-checkout set packages/corpora
    mkdir -p ~/nltk_data/corpora
    cp /tmp/nltk_data_src/packages/corpora/cmudict.zip ~/nltk_data/corpora/
    cd ~/nltk_data/corpora && unzip -o cmudict.zip

Only the grade rule needs it, and only CASE_PAGES are graded, so a --page
run on any other page works without it. Do not substitute a homemade
syllable count: on 2026-10-02 one read 10.3 on a page textstat scored 9.8.

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
PARAGRAPH_MAX = 120
CTA_MIN = 3

# Pages with no intake job: legal notices, people pages, the form's own
# confirmation page. Add to this set rather than loosening a CTA rule.
CTA_EXEMPT = {
    "404.html", "thank-you.html", "privacy-policy.html", "disclaimer.html",
    "sms-terms.html", "about.html", "contact.html", "editorial-policy.html",
    "david-meldofsky.html", "dr-thomas-hatzilabrou.html",
}
CTA_LINK = re.compile(
    r'<a\b[^>]*\bhref="(https?://(?:www\.)?lawsuit\.center[^"]*)"', re.I)

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
    "ai-injury-lawsuits.html",
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


# Every element a reader sees as one block of prose. A <li> in a dated
# "Recent Developments" list reads exactly like a paragraph, and one ran to
# 199 words on openai-lawsuits.html before this counted it (2026-09-25).
BLOCKS = ("p", "li", "blockquote", "dd", "td")


def paragraphs(html):
    """Word count and opening words of every prose block (<p>, <li>,
    <blockquote>, <dd>, <td>) outside header, nav and footer. A block that
    contains another block (a <li> holding a nested list, a <blockquote>
    holding <p>s) is skipped so the inner blocks are counted once each."""
    body = STRIP.sub(" ", html)
    out = []
    for tag in BLOCKS:
        pat = rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>"
        for m in re.finditer(pat, body, re.S | re.I):
            inner = m.group(1)
            if re.search(r"<(?:p|li|ul|ol|blockquote|dd|table)[\s>]", inner, re.I):
                continue
            t = norm(re.sub(r"<[^>]+>", " ", inner))
            if t:
                out.append((len(t.split()), t))
    return out


DICT_HELP = (
    "textstat needs NLTK's cmudict and could not load it. See Setup in this "
    "file's docstring for the git-based install.")


def grade_level(text):
    """Flesch-Kincaid grade, or a clean exit with the install steps when the
    dictionary is missing, instead of a two-screen NLTK traceback."""
    try:
        return textstat.flesch_kincaid_grade(text)
    except LookupError:
        sys.exit(DICT_HELP)


def cta_problems(html):
    """CTA-set findings for one page. Counts the same links the cta_click
    listener counts: lawsuit.center anchors outside header, nav and footer.
    HTML comments are stripped first, since a commented-out CTA is not one."""
    body = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    body = STRIP.sub(" ", body)
    links = [(m.start(), m.group(1).replace("&amp;", "&"))
             for m in CTA_LINK.finditer(body)]
    out = []
    if len(links) < CTA_MIN:
        out.append(f"{len(links)} CTA(s) to lawsuit.center; want at least "
                   f"{CTA_MIN} (top strip, mid-page inline-cta, closing box)")
    if not links:
        return out
    h2 = [m.start() for m in re.finditer(r"<h2[\s>]", body, re.I)]
    cut = h2[1] if len(h2) > 1 else len(body)
    if not any(pos < cut for pos, _ in links):
        out.append("no CTA before the second <h2>; the first one sits below "
                   "the reader's first screen or two")
    slots = []
    for _, href in links:
        m = re.search(r"[?&]utm_content=([^&#]+)", href)
        slots.append(m.group(1) if m else None)
    untagged = slots.count(None)
    if untagged:
        out.append(f"{untagged} CTA(s) with no utm_content; GA4 records "
                   f"them as slot 'unknown'")
    seen = {}
    for sl in slots:
        if sl:
            seen[sl] = seen.get(sl, 0) + 1
    for sl, n in seen.items():
        if n > 1:
            out.append(f"utm_content={sl} used by {n} CTAs; each placement "
                       f"needs its own slot")
    return out


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


def check(path, in_cluster):
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

    for n, t in paragraphs(html):
        if n >= PARAGRAPH_MAX:
            warnings.append(f"{n}-word paragraph: {t[:90]}...")

    if name not in CTA_EXEMPT:
        warnings.extend(cta_problems(html))

    if not in_cluster:
        # Sitewide tier stops here: adjudicating language, FAQ drift,
        # paragraph length and the CTA set only.
        return errors, warnings

    if name in CASE_PAGES:
        grade = grade_level(text)
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

    if only:
        targets = [root / only] if (root / only).exists() else []
    else:
        targets = sorted(root.glob("*.html"))
    if not targets:
        print("no pages found; run from the repo root")
        return 1

    cluster = set(PAGES)
    n_err = n_warn = 0
    n_cluster = sum(1 for p in targets if p.name in cluster)
    print(f"Consumer readability check - {len(targets)} pages scanned "
          f"({n_cluster} in the AI cluster, held to grade max {GRADE_MAX} "
          f"and sentence max {SENTENCE_MAX}; every page checked for "
          f"reader-adjudicating language, FAQ drift, paragraphs of "
          f"{PARAGRAPH_MAX}+ words and the CTA set)\n")
    for path in targets:
        errors, warnings = check(path, path.name in cluster)
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
