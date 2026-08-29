#!/usr/bin/env python3
"""
Auto-generate the client-side search index (search-data.js).

Mirrors the sitemap approach: it discovers pages automatically and indexes
everything that isn't explicitly excluded. It is NON-DESTRUCTIVE — your existing
hand-curated entries are preserved exactly. Only pages that are not already in
the index get appended.

Duplicate protection runs on BOTH url and normalized title. A curated entry
pointing at an anchor (browse-lawsuits#ai-lawsuits) and a real page (ai-lawsuits)
have different urls but the same title, and the results grid renders title plus
category, so one query returns two identical-looking cards. Pages whose title
already exists in the index are skipped and reported instead of appended.

Per-page overrides (optional): add either meta tag to any page's <head> to take
control of how it is indexed instead of relying on auto-extraction:
    <meta name="search-category" content="Court Filing">
    <meta name="search-keywords" content="dunn activision blizzard mdl 3109 ...">

Usage:
    python generate_search_index.py                 # append new pages
    python generate_search_index.py --dry-run       # preview only
    python generate_search_index.py --rebuild-text  # refresh keyword blobs in place

--rebuild-text regenerates the `text` field of every entry that maps to a real
page, and touches nothing else. Titles and categories are left exactly as they
are, because they are hand-curated: eleven of the fourteen categories in use
(Illness Topic, Symptom Topic, News and Analysis, Exposure Site and the rest)
cannot be reproduced by CATEGORY_RULES, so regenerating them would flatten more
than a hundred entries to "Legal Guide". Entries with no matching .html file,
such as browse-section anchors, are copied through untouched.
"""
import os, re, sys, html

INDEX_FILE = "search-data.js"

# --- Pages never indexed (utility / legal / nav / author / template). Editable. ---
EXCLUDE = {
    "index",                      # homepage
    "case-filing-template",       # template, not a page
    "about", "contact",
    "privacy-policy", "disclaimer", "editorial-policy",
    "contributor-guidelines", "sms-terms", "thank-you",
    "david-meldofsky", "dr-thomas-hatzilabrou", "professor-perspective",
    "404",
}

# --- Category inference: first matching rule wins. (regex on slug, category). Editable. ---
CATEGORY_RULES = [
    (r"mdl-\d+.*order", "Court Filing"),
    (r"-v-",            "Court Filing"),
    (r"^(what-|how-)",  "Legal Guide"),
    (r"(guide|basics|glossary|questions-|mistakes|qualify|worth-suing|demand-letter|retainer|ignore-a-lawsuit|evidence)", "Legal Guide"),
    (r"-lawsuit$",      "Lawsuit Topic"),
]
DEFAULT_CATEGORY = "Legal Guide"

# Brand suffixes stripped from <title> to get a clean display title.
BRAND_SUFFIXES = (" | Lawsuit Informer", " | Informer", " — Lawsuit Informer")

STOPWORDS = set("a an and are as at be by for from in is it its of on or the to with this that you your".split())

# How many leading <p> blocks feed the keyword blob. Two was too narrow: whether a
# page matched a query depended on whether the word happened to land in the opening
# lines, so sibling pages on one subject matched inconsistently. Six roughly doubles
# the corpus while barely moving the largest entry, because repeat tokens are
# deduped below. Indexing every paragraph pushes single entries past 10k characters
# and dilutes scoring, where text is only worth +1 per term.
PARA_WINDOW = 6

# Bridges between how a subject is written and how it is searched. The browser-side
# matcher gives terms of three characters or fewer a word-boundary test, which stops
# "ai" matching "chair" and "said" but also stops it matching inside "openai". Rather
# than loosening that rule, the tokens on the right are appended to the blob at BUILD
# time when any trigger on the left is present, so the expansion is visible in the
# committed file instead of computed at runtime. Keep this small and specific.
SYNONYMS = [
    (("openai", "chatgpt", "gpt", "xai", "grok", "anthropic", "claude",
      "gemini", "copilot", "chatbot", "chatbots", "llm"),
     "ai artificial intelligence"),
    (("ai",), "artificial intelligence"),
    (("pfas", "pfoa", "pfos"), "forever chemicals"),
    (("mesothelioma", "asbestosis"), "asbestos"),
]


def expand(words):
    """Append synonym tokens for any trigger present, without duplicating."""
    have = set(words)
    extra = []
    for triggers, addition in SYNONYMS:
        if have.isdisjoint(triggers):
            continue
        for tok in addition.split():
            if tok not in have and tok not in extra:
                extra.append(tok)
    return words + extra


def clean_title(raw):
    t = html.unescape(raw or "").strip()
    # drop a trailing brand segment after the last pipe if it mentions the brand
    if " | " in t:
        head, _, tail = t.rpartition(" | ")
        if "informer" in tail.lower():
            t = head.strip()
    for s in BRAND_SUFFIXES:
        if t.endswith(s):
            t = t[: -len(s)].strip()
    return t


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s)


def meta_content(h, name):
    m = re.search(r'<meta\s+name=["\']%s["\']\s+content=["\'](.*?)["\']' % name, h, re.I | re.S)
    if not m:
        m = re.search(r'<meta\s+content=["\'](.*?)["\']\s+name=["\']%s["\']' % name, h, re.I | re.S)
    return html.unescape(m.group(1).strip()) if m else ""


def build_text(slug, title, h):
    """Auto keyword blob: slug words + title + description + (main) headings + first paragraphs."""
    # Restrict to main content so header/footer/nav boilerplate doesn't pollute the index.
    m = re.search(r"<main\b.*?>(.*?)</main>", h, re.I | re.S)
    if m:
        body = m.group(1)
    else:
        body = re.sub(r"<header\b.*?</header>|<footer\b.*?</footer>|<nav\b.*?</nav>", " ", h, flags=re.I | re.S)
    parts = [slug.replace("-", " "), title, meta_content(h, "description")]
    for tag in ("h1", "h2", "h3"):
        parts += [strip_tags(x) for x in re.findall(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), body, re.I | re.S)]
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body, re.I | re.S)[:PARA_WINDOW]
    parts += [strip_tags(p) for p in paras]
    words, seen = [], set()
    for tok in re.findall(r"[a-z0-9]+", " ".join(parts).lower()):
        if tok in STOPWORDS or len(tok) == 1:
            continue
        if tok not in seen:
            seen.add(tok); words.append(tok)
    return " ".join(expand(words))


def norm_title(t):
    """Comparison key for titles: case, spacing and punctuation insensitive."""
    return re.sub(r"[^a-z0-9]", "", html.unescape(t or "").lower())


def infer_category(slug):
    for pat, cat in CATEGORY_RULES:
        if re.search(pat, slug):
            return cat
    return DEFAULT_CATEGORY


def is_indexable(slug, h):
    if slug in EXCLUDE:
        return False
    if "@@" in h or "{{" in h:          # unfilled template
        return False
    if re.search(r'name=["\']robots["\'][^>]*noindex', h, re.I):
        return False
    if not re.search(r"<title>.*?</title>", h, re.S):
        return False
    return True


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def rebuild_text():
    """Refresh only the `text` field of entries that map to a real page."""
    dry = "--dry-run" in sys.argv
    src = open(INDEX_FILE, encoding="utf-8").read()
    entry_re = re.compile(
        r'(\{\s*title:\s*"(?P<title>(?:[^"\\]|\\.)*)",\s*'
        r'url:\s*"(?P<url>(?:[^"\\]|\\.)*)",\s*'
        r'category:\s*"(?P<cat>(?:[^"\\]|\\.)*)",\s*'
        r'text:\s*")(?P<text>(?:[^"\\]|\\.)*)(")',
        re.S,
    )
    changed, skipped = [], []

    def sub(m):
        slug = m.group("url")
        path = slug + ".html"
        if "#" in slug or not os.path.exists(path):
            skipped.append(slug)
            return m.group(0)
        h = open(path, encoding="utf-8").read()
        title = clean_title(m.group("title"))
        new = meta_content(h, "search-keywords") or build_text(slug, title, h)
        if new != m.group("text"):
            changed.append((slug, len(m.group("text")), len(new)))
        return m.group(1) + esc(new) + '"'

    out = entry_re.sub(sub, src)
    print("Rebuilt keyword text for %d entr(y/ies); %d left as-is (anchors or missing pages)."
          % (len(changed), len(skipped)))
    if dry:
        print("(dry run - no changes written)")
        return
    open(INDEX_FILE, "w", encoding="utf-8").write(out)
    print("Wrote %s (%d bytes)." % (INDEX_FILE, len(out)))


def main():
    if "--rebuild-text" in sys.argv:
        return rebuild_text()
    dry = "--dry-run" in sys.argv
    src = open(INDEX_FILE, encoding="utf-8").read()
    existing = set(re.findall(r'url:\s*"([^"]+)"', src))
    # Curated entries can point at an anchor (browse-lawsuits#ai-lawsuits) while a
    # real page carries the same title (ai-lawsuits). Deduping on url alone lets
    # both into the index, and the results grid renders title + category, so the
    # same name comes back twice for one query. Track normalized titles as well.
    existing_titles = {norm_title(t) for t in re.findall(r'title:\s*"([^"]+)"', src)}
    collisions = []

    pages = sorted(f[:-5] for f in os.listdir(".") if f.endswith(".html"))
    new_entries = []
    for slug in pages:
        if slug in existing:
            continue
        h = open(slug + ".html", encoding="utf-8").read()
        if not is_indexable(slug, h):
            continue
        title_m = re.search(r"<title>(.*?)</title>", h, re.S)
        title = clean_title(title_m.group(1))
        category = meta_content(h, "search-category") or infer_category(slug)
        text = meta_content(h, "search-keywords") or build_text(slug, title, h)
        key = norm_title(title)
        if key in existing_titles:
            collisions.append((slug, title))
            continue
        existing_titles.add(key)
        new_entries.append({"title": title, "url": slug, "category": category, "text": text})

    if collisions:
        print("Skipped %d page(s) whose title is already in %s:" % (len(collisions), INDEX_FILE))
        for slug, title in collisions:
            print("  ! %-44s %r" % (slug, title))
        print("  Fix by deleting the stale curated entry or retitling the page, then")
        print("  re-run. No page is indexed twice under the same title.")

    if not new_entries:
        print("Search index already up to date — no new pages to add.")
        return

    print("Will add %d page(s) to %s:" % (len(new_entries), INDEX_FILE))
    for e in new_entries:
        print("  + %-44s [%s]" % (e["url"], e["category"]))

    if dry:
        print("\n(dry run — no changes written)")
        return

    block = ""
    for e in new_entries:
        block += (
            "  {\n"
            '    title: "%s",\n'
            '    url: "%s",\n'
            '    category: "%s",\n'
            '    text: "%s"\n'
            "  },\n" % (esc(e["title"]), esc(e["url"]), esc(e["category"]), esc(e["text"]))
        )

    pos = src.rstrip().rfind("];")
    if pos == -1:
        print("ERROR: could not find closing '];' in %s" % INDEX_FILE); sys.exit(1)
    head = src[:pos].rstrip()
    if not head.endswith(","):       # ensure trailing comma before our insert
        head += ","
    out = head + "\n" + block + "];\n"
    open(INDEX_FILE, "w", encoding="utf-8").write(out)
    print("\nWrote %s (%d total entries)." % (INDEX_FILE, len(existing) + len(new_entries)))


if __name__ == "__main__":
    main()
