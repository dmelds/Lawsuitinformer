#!/usr/bin/env python3
"""
Cannibalization check: pages competing for one search.

Why this exists. On 10/4/26 a rewrite of the Depo-Provera hub pulled in the
case count, the settlement appointments and the court calendar, which is what
depo-provera-lawsuit-updates exists to carry, and its meta description promised
"where the lawsuit stands". The hub's science section was already near
word-for-word with depo-provera-meningioma, and that page had zero Bing
impressions. Nothing in the repo would have said so. This does.

A cluster is the set of pages about one tort (depo-provera-*, hair-relaxer-*,
roundup + glyphosate, ...). Inside a cluster, each page should own one job and
link to the pages that own the others. Four things are checked:

  BOILERPLATE    A passage that appears on BOILERPLATE_PAGES or more pages in
                 one cluster. That is a page template, not two pages copying
                 each other, so it is reported once for the cluster with the
                 page count, and excluded from the pair comparison below. The
                 asbestos trade pages share their closing paragraphs this way.

  BODY OVERLAP   Shared 6-word runs between two pages in a cluster, after the
                 template blocks (CTAs, author box, related grids, breadcrumbs),
                 the cluster boilerplate, and site-wide template text (a passage
                 on SITE_TEMPLATE_PAGES or more pages anywhere on the site, such
                 as Lawsuit Center's legal disclosures) are stripped. Reported as a share
                 of the smaller page. WARN at BODY_WARN, ERROR at BODY_ERROR.
                 The longest shared passages are printed so the duplicate is
                 visible. Before the 10/4 split, hub vs meningioma was 12.7%.

  STATUS INTENT  A cluster that has an updates page (slug ends -update or
                 -updates) should keep status language out of every other
                 page's <title>, <h1> and meta description: "where it stands",
                 "update", "status", "latest", "as of". Two pages promising
                 status to the same query is the exact failure. WARN.

  SHARED COUNTS  A number with a thousands separator ("6,412", "15,264") that
                 appears in the body of two or more pages in a cluster. A count
                 is a live figure; every page carrying it is one more place it
                 goes stale. WARN, listing the pages and the numbers. Dates are
                 not flagged: a filing date or a ruling date is an event and
                 belongs wherever it is discussed.

  GLOBAL DUPES   Across the whole site: two pages with the same normalized
                 <title> or the same meta description. ERROR. Near-identical
                 descriptions (4-word runs, >= DESC_WARN) WARN.

CROSS-SITE (--with). Added 10/4/26 for Lawsuit Center, extended 10/5/26 to any
number of sites. Informer, Center and Intelligencer all carry pages on the same
torts, and a search engine weighs them against each other the same way it
weighs two pages on one site. Pass --with once per extra site; every unordered
pair of loaded sites is then checked:

  X-BODY         Body overlap between a page on one site and a page on another,
                 same thresholds as BODY OVERLAP. Text that appears on
                 SITE_TEMPLATE_PAGES or more pages of a site is that site's
                 template and is left out before comparing.

  X-STATUS       A page promising status in a cluster where the OTHER site has
                 an updates page. Whichever site carries the -updates slug owns
                 status for that cluster. WARN.

  X-COUNTS       A live count carried on pages of two different sites in one
                 cluster. Two sites carrying one figure means two deploys to
                 keep it current. WARN. Pages matching MULTI_TORT (the mass
                 tort map, the Informer tort roundups) sit in no cluster, so
                 they get a second pass: their non-round counts are compared
                 against every page on the other site. That pass is what
                 catches the map's JPML figures on the Informer update pages.

  X-TITLES       Two pages with the same title once the site name is removed,
                 or the same meta description: ERROR. Titles that lead with the
                 same term, or whose lead terms share TITLE_WARN of their
                 3-word runs: WARN. Descriptions sharing DESC_WARN of their
                 4-word runs: WARN. Legal and site pages (CROSS_SKIP) are left
                 out.

Each site has a profile in SITE_PROFILES giving its display name and the
template blocks to strip before comparing. The profile is detected from the
canonical URL on the site's own pages, so --site is only needed when detection
fails. The extra sites' own internal clusters are not checked by a --with run;
point --path at a site to check it against itself.

Note on Informer vs Intelligencer. The two write for different readers, so
overlapping coverage of one tort is expected and is not by itself a finding.
What matters between them is a shared live figure, an identical title, or a
passage that actually repeats.

Clusters come from CLUSTER_RULES first (editable; first regex match wins),
then from the slug's first token unless it is a generic word. A page that
lands in no cluster is only part of the global checks.

Usage:
    python3 check_cannibalization.py              # whole site
    python3 check_cannibalization.py --page depo-provera-lawsuits.html
    python3 check_cannibalization.py --strict     # exit 1 on any ERROR
    python3 check_cannibalization.py --with ../lawsuits-center
    python3 check_cannibalization.py --with ../lawsuits-center --with ../lawsuitintelligencer
    python3 check_cannibalization.py --with ../lawsuits-center --page hair-relaxer-lawsuit.html
    python3 check_cannibalization.py --path ../lawsuitintelligencer --site intelligencer
"""
import html as htmlmod
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---- Tunables -------------------------------------------------------------
BODY_WARN = 8.0      # % of the smaller page's 6-word runs shared
BODY_ERROR = 12.0
DESC_WARN = 60.0     # % of 4-word runs shared between two meta descriptions
TITLE_WARN = 75.0    # % of 3-word runs shared between two title head terms (cross-site)
SHINGLE = 6
MIN_WORDS = 120      # pages shorter than this are skipped for body overlap
SHOW_RUNS = 3        # longest shared passages to print per flagged pair
MIN_RUN = 10         # words; shorter shared runs are not printed
SITE_TEMPLATE_PAGES = 5  # cross-site: a passage on this many pages of one site is that site's template

PRIMARY_NAME = "lawsuitinformer.com"      # kept: default when detection fails
SECONDARY_NAME = "lawsuit.center"

# ---- Clusters: (regex on slug, cluster name). First match wins. Editable. ----
CLUSTER_RULES = [
    (r"^(roundup|glyphosate|monsanto)", "roundup"),
    (r"^(pfas|afff|forever-chemicals)", "pfas"),
    (r"^(tylenol|acetaminophen)", "tylenol"),
    (r"^(openai|chatgpt|raine-v|lacey-v|parish-v|shamblin-v|carrier-v|"
     r"gourley-v|jccp-5431|tumbler-ridge|florida-v-openai|hugging-face)", "openai"),
    (r"-v-openai|-v-altman|^ai-wrongful-death", "openai"),
    (r"^(social-media|instagram|tiktok|snapchat|facebook|meta-)", "social-media"),
    (r"^(video-game|roblox|fortnite|minecraft|epic-games|angelilli|antonetti|"
     r"dunn-v-activision|johnson-v-activision|baggaley-v-roblox|is-video-game)", "video-game"),
    (r"^(asbestos|mesothelioma|peritoneal|pleural|lung-cancer-asbestos|"
     r"lung-cancer-from-asbestos)", "asbestos"),
    (r"-asbestos-lawyers$", "asbestos"),
    (r"^(talcum|talc-)", "talc"),
    (r"^(house-ncaa|college-athlete)", "house-ncaa"),
    (r"^(grok|xai|deepfake)", "grok"),
    (r"^(camp-lejeune|lejeune)", "camp-lejeune"),
    (r"hair-relaxer", "hair-relaxer"),      # anywhere: arizona-v-loreal-hair-relaxer
    (r"^(hernia-mesh|recent-developments-hernia)", "hernia-mesh"),
    (r"^transvaginal-mesh", "transvaginal-mesh"),
    (r"^(ultra-processed|processed-food)", "processed-food"),
    (r"^(ozempic|glp-1|wegovy|mounjaro)", "glp-1"),
    (r"^character-ai|^garcia-v-character", "character-ai"),
    (r"^(depo-provera|coming-off-depo)", "depo"),
]
# First tokens that never define a cluster on their own.
GENERIC_FIRST = {
    "what", "is", "how", "does", "do", "can", "where", "why", "when", "who",
    "which", "the", "a", "an", "legal", "symptoms", "illnesses", "current",
    "browse", "about", "contact", "privacy", "editorial", "news", "index",
    "toxic", "chemical", "environmental", "consumer", "product", "mass",
    "class", "bellwether", "mdl", "statute", "attorney", "find", "are",
    "has", "published", "david", "dr", "professor", "sms", "thank", "404",
    "case", "states", "ai", "family", "air", "banking", "business", "car",
    "catastrophic", "civil", "construction", "defamation", "dog", "drug",
    "employment", "financial", "insurance", "medical", "nursing", "personal",
    "premises", "sexual", "truck", "wrongful", "workers",
    # utility and site pages, mostly on Lawsuit Center
    "disclaimer", "advertising", "footer", "search", "resources", "for",
    "law", "lawsuit", "lawsuits", "marketing", "educational", "default",
    "cancer", "real", "stock", "slip", "pedestrian", "motorcycle",
}

# Template blocks stripped before comparing bodies. Class prefix match.
TEMPLATE_CLASSES = (
    "hero-action-strip", "inline-cta", "cta-box", "case-review-box",
    "related-guides", "related-box", "content-box", "on-this-page",
    "editor-note", "start-here-inline", "author-box", "article-meta",
    "info-box", "key-takeaways-box", "breadcrumb", "subscribe-box",
    "topic-grid", "pdf-embed", "link-list", "toc-list", "stat-block-wrap",
)
# Lawsuit Center template blocks, used for the --with site only: the intake
# form and its consent copy, the sponsored firm cards (firm-card), the closing
# CTA band, the related topics grid and the legal note. Do not add "firms":
# Center pages use that class for their overview text and fact list, and
# stripping it hid the overview (and the counts in it) from the comparison.
SECONDARY_TEMPLATE_CLASSES = TEMPLATE_CLASSES + (
    "related-topics-module", "firm-card", "final", "legal-note", "form",
    "form-card", "form-fineprint", "form-note", "hero-actions", "actions",
    "small-text", "checkbox-row", "field", "site-header", "site-footer",
    "firm-meta",
)
# Lawsuit Intelligencer template blocks. Its masthead and footer already go out
# with <header>/<footer>; what is left is the recent-articles grid (other
# articles' headlines and deks), the eyebrow labels, the jump bar and the
# end-of-article byline. Figures and data tables are page-specific and stay in.
# Do not add "entry": the enforcement tracker uses that class for each matter
# and stripping it removed 60% of the page from the comparison.
INTELLIGENCER_TEMPLATE_CLASSES = TEMPLATE_CLASSES + (
    "recent", "section-eyebrow", "li-jump", "article-byline-end",
    "footer-disclosure", "masthead", "featured", "article-eyebrow",
    "li-disclosure",
)

# name: display name, template classes, and the tag-drop pattern for that site.
SITE_PROFILES = {
    "informer": (PRIMARY_NAME, TEMPLATE_CLASSES, "primary"),
    "center": (SECONDARY_NAME, SECONDARY_TEMPLATE_CLASSES, "full"),
    "intelligencer": ("lawsuitintelligencer.com", INTELLIGENCER_TEMPLATE_CLASSES, "primary"),
}
# canonical-URL domain -> profile key, for detecting a folder's site.
DOMAIN_TO_SITE = {
    "lawsuitinformer.com": "informer",
    "lawsuit.center": "center",
    "lawsuitintelligencer.com": "intelligencer",
}
CANONICAL = re.compile(r'<link[^>]+rel="canonical"[^>]+href="https?://(?:www\.)?([^/"]+)', re.I)

# Pages that carry live counts for MANY torts at once (the mass tort map, the
# Informer tort roundups). They belong to no single cluster, so the per-cluster
# X-COUNTS pass never sees them. They are compared for counts against every
# page on the other site instead. Round thousands ("1,000", "10,000") are
# skipped in that pass only: they are thresholds and estimates, not counts.
MULTI_TORT = re.compile(r"^(mass-tort-map|mass-torts|current-mass-tort-cases)$")
ROUND = re.compile(r"^\d{1,3},000$")

BOILERPLATE_PAGES = 3   # a passage on this many pages in a cluster is template, not a pair problem
TEMPLATE_P_CLASSES = ("article-byline", "article-date", "article-disclaimer",
                      "link-cluster", "cta-note", "form-note", "hero-action-note")

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
FULLDATE = re.compile(r"\b(?:" + MONTHS + r")\s+\d{1,2},\s*20\d{2}\b")
COUNT = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
STATUS = re.compile(
    r"\b(update|updates|status|latest|as of|where .{0,40}?stand|"
    r"case count|right now|this month|settlement status|what(?:'s| is) new)\b",
    re.I)
UPDATES_SLUG = re.compile(r"-(update|updates)$|^recent-developments|-litigation-update")
BRAND = re.compile(r"\s*[|\-–—:]\s*(lawsuit\s+center|lawsuit\s+informer|"
                   r"lawsuit\s+intelligencer|lawsuitinformer\.com|lawsuit\.center|"
                   r"lawsuitintelligencer\.com)\s*$", re.I)

TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
META_DESC = re.compile(
    r'<meta\s+name="description"\s+content="([^"]*)"', re.S | re.I)
MAIN = re.compile(r"<main\b.*?</main>", re.S | re.I)
DROP = re.compile(r"<(script|style|nav|footer|noscript|svg|header|form)\b.*?</\1>",
                  re.S | re.I)
DROP_PRIMARY = re.compile(r"<(script|style|nav|footer|noscript|svg|header)\b.*?</\1>",
                          re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
SVG_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S | re.I)
HREF = re.compile(r'href="([^"#?]+)')

EXCLUDE = {"index", "404", "case-filing-template", "thank-you"}
EXCLUDE_PREFIX = ("thank-you-",)
# Legal and site pages that every site carries under the same name. Left out
# of the cross-site title and description comparison.
CROSS_SKIP = {"privacy-policy", "editorial-policy", "disclaimer", "about",
              "contact", "terms", "terms-of-use", "advertising-disclosure",
              "search", "resources", "footer", "sitemap", "accessibility",
              "david-meldofsky",
              # Intelligencer site pages
              "editorial-standards", "contribute", "interviews", "welcome"}


def text(raw):
    return " ".join(TAGS.sub(" ", htmlmod.unescape(raw or "")).split())


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def title_core(title):
    """The head term: the brand-stripped title up to its first separator."""
    return re.split(r"\s+[|:\-–—]\s+|:\s+", strip_brand(title), maxsplit=1)[0]


def strip_brand(title):
    t = title
    while True:
        u = BRAND.sub("", t)
        if u == t:
            return t
        t = u


def strip_blocks(h, tag, pred):
    """Remove <tag ...>...</tag> blocks whose attrs satisfy pred, nesting-aware."""
    out, i = [], 0
    open_re = re.compile(r"<%s\b([^>]*)>" % tag, re.I)
    any_re = re.compile(r"<(/?)%s\b[^>]*>" % tag, re.I)
    while True:
        m = open_re.search(h, i)
        if not m:
            out.append(h[i:])
            break
        if not pred(m.group(1)):
            out.append(h[i:m.end()])
            i = m.end()
            continue
        out.append(h[i:m.start()])
        depth, j = 1, m.end()
        while depth:
            n = any_re.search(h, j)
            if not n:
                j = len(h)
                break
            depth += -1 if n.group(1) else 1
            j = n.end()
        i = j
    return "".join(out)


def has_class(attrs, prefixes):
    m = re.search(r'class="([^"]*)"', attrs or "")
    if not m:
        return False
    return any(c.startswith(prefixes) for c in m.group(1).split())


def body_text(h, classes=TEMPLATE_CLASSES, drop=DROP_PRIMARY):
    m = MAIN.search(h)
    raw = m.group(0) if m else h
    raw = drop.sub(" ", raw)
    raw = strip_blocks(raw, "div", lambda a: has_class(a, classes))
    raw = strip_blocks(raw, "section", lambda a: has_class(a, classes))
    raw = strip_blocks(raw, "aside", lambda a: has_class(a, classes))
    raw = strip_blocks(raw, "p", lambda a: has_class(a, TEMPLATE_P_CLASSES))
    return text(raw)


def shingles(t, n):
    w = t.split()
    return set(" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1)))


def shared_runs(a, b, n=SHINGLE):
    """Longest contiguous passages of `a` whose every n-gram is in `b`."""
    wa, B = a.split(), shingles(b, n)
    runs, cur = [], None
    for i in range(len(wa) - n + 1):
        if " ".join(wa[i:i + n]) in B:
            cur = [i, i + n] if cur is None else [cur[0], i + n]
        elif cur:
            runs.append(" ".join(wa[cur[0]:cur[1]]))
            cur = None
    if cur:
        runs.append(" ".join(wa[cur[0]:cur[1]]))
    runs = [r for r in runs if len(r.split()) >= MIN_RUN]
    return sorted(runs, key=lambda r: -len(r.split()))


def show(r):
    return f"\n          shared: \"{r[:150]}{'…' if len(r) > 150 else ''}\" ({len(r.split())}w)"


def cluster_of(slug):
    for rx, name in CLUSTER_RULES:
        if re.search(rx, slug):
            return name
    first = slug.split("-")[0]
    return None if first in GENERIC_FIRST else first


def load(root, classes=TEMPLATE_CLASSES, drop=DROP_PRIMARY):
    pages = {}
    for path in sorted(root.glob("*.html")):
        slug = path.stem
        if slug in EXCLUDE or slug.startswith(EXCLUDE_PREFIX):
            continue
        h = path.read_text(encoding="utf-8", errors="ignore")
        t = TITLE.search(h)
        if not t:
            continue
        d = META_DESC.search(h)
        h1 = H1.search(h)
        body = body_text(h, classes, drop)
        # Counts inside inline SVG charts (bar labels, data points). SVG is
        # dropped from the body text on purpose, but a figure drawn on a chart
        # is still a live figure the page is carrying.
        svg_counts = set()
        for svg in SVG_BLOCK.findall(h):
            for node in SVG_TEXT.findall(svg):
                svg_counts.update(COUNT.findall(text(node)))
        pages[slug] = {
            "title": text(t.group(1)),
            "h1": text(h1.group(1)) if h1 else "",
            "desc": htmlmod.unescape(d.group(1)) if d else "",
            "body": norm(body),
            "counts": set(COUNT.findall(body)) | svg_counts,
            "words": len(body.split()),
            "links": set(x.rstrip("/").split("/")[-1].replace(".html", "")
                         for x in HREF.findall(h)),
            "cluster": cluster_of(slug),
        }
    return pages


def check_cluster(name, slugs, pages, errors, warnings, tmpl=frozenset()):
    slugs = sorted(slugs)
    updates = [s for s in slugs if UPDATES_SLUG.search(s)]

    # --- status intent on non-updates pages ---
    if updates:
        for s in slugs:
            if s in updates:
                continue
            p = pages[s]
            for field in ("title", "h1", "desc"):
                m = STATUS.search(p[field])
                if m:
                    warnings[s].append(
                        f"{field} promises status (\"{m.group(0)}\") but "
                        f"{', '.join(updates)} owns status for this cluster — "
                        f"one page per job, or the two split one search")
                    break

    # --- cluster boilerplate: shingles on >= BOILERPLATE_PAGES pages ---
    sh = {s: shingles(pages[s]["body"], SHINGLE) for s in slugs
          if pages[s]["words"] >= MIN_WORDS}
    count = defaultdict(int)
    for s, A in sh.items():
        for g in A:
            count[g] += 1
    boiler = {g for g, c in count.items() if c >= BOILERPLATE_PAGES} - set(tmpl)
    if boiler:
        # stitch the boilerplate shingles back into passages using the page
        # that carries the most of them, so the report shows real sentences
        carrier = max(sh, key=lambda s: len(sh[s] & boiler))
        wa = pages[carrier]["body"].split()
        runs, cur = [], None
        for i in range(len(wa) - SHINGLE + 1):
            if " ".join(wa[i:i + SHINGLE]) in boiler:
                cur = [i, i + SHINGLE] if cur is None else [cur[0], i + SHINGLE]
            elif cur:
                runs.append(" ".join(wa[cur[0]:cur[1]])); cur = None
        if cur:
            runs.append(" ".join(wa[cur[0]:cur[1]]))
        runs = sorted((r for r in runs if len(r.split()) >= MIN_RUN),
                      key=lambda r: -len(r.split()))
        if runs:
            on = sorted(s for s, A in sh.items() if len(A & boiler) >= SHINGLE)
            msg = (f"{len(on)} pages share the same passages (template text, not "
                   f"page-specific): {', '.join(on[:8])}"
                   + (f" (+{len(on)-8} more)" if len(on) > 8 else ""))
            for r in runs[:SHOW_RUNS]:
                msg += show(r)
            warnings[f"[cluster {name}]"].append(msg)

    # --- body overlap, pairwise, boilerplate excluded ---
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            pa, pb = pages[a], pages[b]
            if a not in sh or b not in sh:
                continue
            A, B = sh[a] - boiler - tmpl, sh[b] - boiler - tmpl
            if not A or not B:
                continue
            pct = 100.0 * len(A & B) / min(len(A), len(B))
            if pct < BODY_WARN:
                continue
            linked = (b in pa["links"]) or (a in pb["links"])
            msg = (f"{pct:.1f}% of the smaller page's text is shared with "
                   f"{b}.html" + ("" if linked else
                                  " — and neither page links to the other"))
            runs = [r for r in shared_runs(pa["body"], pb["body"])
                    if not shingles(r, SHINGLE) <= (boiler | tmpl)][:SHOW_RUNS]
            for r in runs:
                msg += show(r)
            (errors if pct >= BODY_ERROR else warnings)[a].append(msg)

    # --- shared counts ---
    if len(slugs) > 1:
        where = defaultdict(set)
        for s in slugs:
            for f in pages[s]["counts"]:
                where[f].add(s)
        dupes = {f: v for f, v in where.items() if len(v) > 1}
        if dupes:
            for s in slugs:
                mine = sorted(f for f, v in dupes.items() if s in v)
                if not mine:
                    continue
                others = sorted(set().union(*[dupes[f] for f in mine]) - {s})
                shown = ", ".join(mine[:6]) + (f" (+{len(mine)-6} more)" if len(mine) > 6 else "")
                warnings[s].append(
                    f"count(s) also on {', '.join(o + '.html' for o in others)}: {shown} "
                    f"— one page should own the live figure; the rest should link to it")


def check_global(pages, errors, warnings, only=None):
    by_title, by_desc = defaultdict(list), defaultdict(list)
    for s, p in pages.items():
        by_title[norm(p["title"])].append(s)
        if p["desc"]:
            by_desc[norm(p["desc"])].append(s)
    for key, group in list(by_title.items()) + list(by_desc.items()):
        if len(group) < 2:
            continue
        kind = "title" if key in by_title and group == by_title[key] else "meta description"
        for s in group:
            if only and s != only:
                continue
            errors[s].append(
                f"{kind} is identical to {', '.join(o + '.html' for o in group if o != s)} "
                f"— search engines pick one and drop the other")
    # near-identical descriptions
    descs = [(s, shingles(norm(p["desc"]), 4)) for s, p in pages.items() if p["desc"]]
    for i, (a, A) in enumerate(descs):
        if only and a != only:
            continue
        for b, B in descs[i + 1:] if not only else [(x, y) for x, y in descs if x != a]:
            if not A or not B or norm(pages[a]["desc"]) == norm(pages[b]["desc"]):
                continue
            pct = 100.0 * len(A & B) / min(len(A), len(B))
            if pct >= DESC_WARN:
                warnings[a].append(
                    f"meta description shares {pct:.0f}% of its wording with {b}.html")


def site_template(pages):
    """6-word runs on SITE_TEMPLATE_PAGES or more pages of one site."""
    count = defaultdict(int)
    for p in pages.values():
        for g in shingles(p["body"], SHINGLE):
            count[g] += 1
    return {g for g, c in count.items() if c >= SITE_TEMPLATE_PAGES}


def detect_site(root, fallback="informer"):
    """Read the canonical domain off the folder's pages to pick a profile."""
    for path in sorted(root.glob("*.html"))[:40]:
        m = CANONICAL.search(path.read_text(encoding="utf-8", errors="ignore"))
        if m and m.group(1).lower() in DOMAIN_TO_SITE:
            return DOMAIN_TO_SITE[m.group(1).lower()]
    return fallback


def load_site(root, key):
    name, classes, dropkind = SITE_PROFILES[key]
    drop = DROP if dropkind == "full" else DROP_PRIMARY
    return name, load(root, classes, drop)


def check_cross(a_pages, a_name, b_pages, b_name, errors, warnings, only=None):
    """One site's pages against another's. Findings are keyed <site>/<slug>."""
    A_ = lambda s: f"{a_name}/{s}"
    B_ = lambda s: f"{b_name}/{s}"
    tmpl = site_template(a_pages) | site_template(b_pages)

    clusters_a, clusters_b = defaultdict(set), defaultdict(set)
    for s, p in a_pages.items():
        if p["cluster"]:
            clusters_a[p["cluster"]].add(s)
    for s, p in b_pages.items():
        if p["cluster"]:
            clusters_b[p["cluster"]].add(s)
    shared = sorted(set(clusters_a) & set(clusters_b))

    def wanted(a, b):
        return not only or only in (a, b)

    for name in shared:
        as_, bs_ = sorted(clusters_a[name]), sorted(clusters_b[name])
        a_updates = [x for x in as_ if UPDATES_SLUG.search(x)]
        b_updates = [x for x in bs_ if UPDATES_SLUG.search(x)]

        # X-STATUS, in both directions: the side holding the -updates slug owns
        # status for the cluster, and the other side should not promise it.
        for owner, owner_fmt, others, other_pages, other_fmt in (
                (a_updates, A_, bs_, b_pages, B_),
                (b_updates, B_, as_, a_pages, A_)):
            if not owner:
                continue
            for s in others:
                if only and only not in (s, *owner):
                    continue
                p = other_pages[s]
                for field in ("title", "h1", "desc"):
                    m = STATUS.search(p[field])
                    if m:
                        warnings[other_fmt(s)].append(
                            f"{field} promises status (\"{m.group(0)}\") but "
                            f"{', '.join(owner_fmt(u) for u in owner)} owns status for "
                            f"'{name}' — the two compete for the status search")
                        break

        # X-BODY
        sha = {x: shingles(a_pages[x]["body"], SHINGLE) - tmpl for x in as_
               if a_pages[x]["words"] >= MIN_WORDS}
        shb = {x: shingles(b_pages[x]["body"], SHINGLE) - tmpl for x in bs_
               if b_pages[x]["words"] >= MIN_WORDS}
        for b, B in shb.items():
            for a, A in sha.items():
                if not wanted(a, b) or not A or not B:
                    continue
                pct = 100.0 * len(A & B) / min(len(A), len(B))
                if pct < BODY_WARN:
                    continue
                linked = (a in b_pages[b]["links"]) or (b in a_pages[a]["links"])
                msg = (f"{pct:.1f}% of the smaller page's text is shared with "
                       f"{A_(a)}" + ("" if linked else
                                     " — and neither page links to the other"))
                runs = [r for r in shared_runs(b_pages[b]["body"], a_pages[a]["body"])
                        if not shingles(r, SHINGLE) <= tmpl][:SHOW_RUNS]
                for r in runs:
                    msg += show(r)
                (errors if pct >= BODY_ERROR else warnings)[B_(b)].append(msg)

        # X-COUNTS
        for b in bs_:
            hits = defaultdict(list)
            for f in b_pages[b]["counts"]:
                for a in as_:
                    if f in a_pages[a]["counts"] and wanted(a, b):
                        hits[f].append(a)
            if hits:
                on = sorted(set(x for v in hits.values() for x in v))
                nums = sorted(hits)
                shown = ", ".join(nums[:6]) + (f" (+{len(nums)-6} more)" if len(nums) > 6 else "")
                warnings[B_(b)].append(
                    f"count(s) also on {', '.join(A_(o) for o in on)}: {shown} "
                    f"— two sites carrying one live figure means two places it goes stale")

    # X-COUNTS, multi-tort pages: a map or roundup on either side against every
    # page on the other side, whatever cluster that page is in.
    for src_pages, src_fmt, dst_pages, dst_fmt in ((a_pages, A_, b_pages, B_),
                                                   (b_pages, B_, a_pages, A_)):
        for m_slug, mp in src_pages.items():
            if not MULTI_TORT.search(m_slug):
                continue
            figs = {f for f in mp["counts"] if not ROUND.match(f)}
            hits = defaultdict(list)
            for d_slug, dp in dst_pages.items():
                if d_slug in CROSS_SKIP or not wanted(m_slug, d_slug):
                    continue
                for f in figs & dp["counts"]:
                    hits[d_slug].append(f)
            for d_slug, fs in sorted(hits.items()):
                fs = sorted(fs)
                shown = ", ".join(fs[:6]) + (f" (+{len(fs)-6} more)" if len(fs) > 6 else "")
                warnings[dst_fmt(d_slug)].append(
                    f"count(s) also on {src_fmt(m_slug)}: {shown} "
                    f"— when the report rolls, both pages roll or one goes stale")

    # X-TITLES: identical titles or descriptions, or the same head term
    for b, pb in b_pages.items():
        if b in CROSS_SKIP:
            continue
        tb = norm(strip_brand(pb["title"]))
        cb = norm(title_core(pb["title"]))
        db = norm(pb["desc"])
        cB, dB = shingles(cb, 3), shingles(db, 4)
        for a, pa in a_pages.items():
            if a in CROSS_SKIP or not wanted(a, b):
                continue
            ta = norm(strip_brand(pa["title"]))
            ca = norm(title_core(pa["title"]))
            da = norm(pa["desc"])
            pair = f"(\"{strip_brand(pb['title'])}\" / \"{strip_brand(pa['title'])}\")"
            if ta and ta == tb:
                errors[B_(b)].append(
                    f"title matches {A_(a)} once the site name is removed {pair} "
                    f"— the two pages ask for one search")
            elif ca and ca == cb:
                warnings[B_(b)].append(
                    f"title leads with the same term as {A_(a)} {pair} "
                    f"— both pages target that search")
            elif cB:
                cA = shingles(ca, 3)
                if cA:
                    pct = 100.0 * len(cA & cB) / max(len(cA), len(cB))
                    if pct >= TITLE_WARN:
                        warnings[B_(b)].append(
                            f"title head shares {pct:.0f}% of its wording with {A_(a)} {pair}")
            if da and da == db:
                errors[B_(b)].append(f"meta description is identical to {A_(a)}")
            elif dB:
                dA = shingles(da, 4)
                if dA:
                    pct = 100.0 * len(dA & dB) / min(len(dA), len(dB))
                    if pct >= DESC_WARN:
                        warnings[B_(b)].append(
                            f"meta description shares {pct:.0f}% of its wording with {A_(a)}")

    return shared, clusters_a, clusters_b


def report(label, errors, warnings, suffix=".html"):
    if errors:
        print(f"\n{label}ERRORS ({len(errors)} pages)")
        for s in sorted(errors):
            print(f"  {s}{'' if s.startswith('[') else suffix}")
            for line in errors[s]:
                print(f"      {line}")
    if warnings:
        print(f"\n{label}WARNINGS ({len(warnings)} pages)")
        for s in sorted(warnings):
            print(f"  {s}{'' if s.startswith('[') else suffix}")
            for line in warnings[s]:
                print(f"      {line}")


def main():
    strict = "--strict" in sys.argv
    only = None
    if "--page" in sys.argv:
        only = Path(sys.argv[sys.argv.index("--page") + 1]).stem
    root = Path(sys.argv[sys.argv.index("--path") + 1]) if "--path" in sys.argv else Path(".")

    # --with may be repeated, once per extra site.
    others = [Path(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--with"]
    for o in others:
        if not o.is_dir():
            print(f"--with {o}: folder not found")
            return 1

    if "--site" in sys.argv:
        key = sys.argv[sys.argv.index("--site") + 1]
        if key not in SITE_PROFILES:
            print(f"--site {key}: expected one of {', '.join(sorted(SITE_PROFILES))}")
            return 1
    else:
        key = detect_site(root)
    prim_name, pages = load_site(root, key)

    loaded = [(prim_name, pages)]
    for o in others:
        loaded.append(load_site(o, detect_site(o, "center")))

    tmpl = site_template(pages)
    clusters = defaultdict(set)
    for s, p in pages.items():
        if p["cluster"]:
            clusters[p["cluster"]].add(s)

    known = set(pages) | set().union(*[set(d) for _, d in loaded[1:]]) if others else set(pages)
    if only and only not in known:
        print(f"{only}.html not found")
        return 1

    errors, warnings = defaultdict(list), defaultdict(list)
    if only and only not in pages:
        targets = {}
    elif only:
        c = pages[only]["cluster"]
        targets = {c: clusters[c]} if c else {}
    else:
        targets = clusters
    if not only or only in pages:
        for name, slugs in sorted(targets.items()):
            if len(slugs) > 1:
                check_cluster(name, slugs, pages, errors, warnings, tmpl)
        check_global(pages, errors, warnings, only)

    if only:
        errors = {k: v for k, v in errors.items() if k == only}
        warnings = {k: v for k, v in warnings.items() if k == only}

    multi = sum(1 for v in clusters.values() if len(v) > 1)
    print(f"Cannibalization check — {prim_name}, {len(pages)} pages, {multi} clusters "
          f"of 2+ (body overlap warns at {BODY_WARN:g}%, errors at {BODY_ERROR:g}%)")
    if only and only in pages:
        c = pages[only]["cluster"]
        print(f"  scope: {only}.html" + (f" in cluster '{c}' with "
              f"{', '.join(sorted(clusters[c] - {only}))}" if c else " (no cluster)"))
    report("", errors, warnings)

    any_cross_errors = False
    if others:
        print(f"\nLoaded {len(loaded)} sites: "
              + ", ".join(f"{n} ({len(d)} pages)" for n, d in loaded))
        for i in range(len(loaded)):
            for j in range(i + 1, len(loaded)):
                a_name, a_pages = loaded[i]
                b_name, b_pages = loaded[j]
                xerr, xwarn = defaultdict(list), defaultdict(list)
                shared, ca, cb = check_cross(a_pages, a_name, b_pages, b_name,
                                             xerr, xwarn, only)
                print(f"\n=== CROSS-SITE: {a_name} vs {b_name} ===")
                print(f"  {len(shared)} clusters have pages on both sites"
                      + (": " + ", ".join(f"{n} ({len(ca[n])}+{len(cb[n])})"
                                          for n in shared) if shared else ""))
                if only:
                    print(f"  scope: pairs that include {only}.html")
                report("CROSS-SITE ", xerr, xwarn, suffix="")
                if not xerr and not xwarn:
                    print("  No cross-site signals.")
                any_cross_errors = any_cross_errors or bool(xerr)

    if not errors and not warnings and not others:
        print("\nNo cannibalization signals.")
    return 1 if ((errors or any_cross_errors) and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
