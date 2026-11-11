#!/usr/bin/env python3
"""Regroup the Informer footer links into Explore, About and Network columns.

The old footer had a 12-link Quick Links column that mixed reader paths,
trust pages and legal pages, and an Explore column of 3 links that repeated
Browse Lawsuits. Start Here, the second item in the header nav, had no
footer link. This sweep makes two edits per page, both inside <footer>:

  1. The footer-content block. It becomes four columns:
       brand blurb with the contact line (the question is plain text now)
       Explore: Start Here, How Lawsuits Work, Legal Guides, Browse Lawsuits,
                Illnesses, Symptoms, News & Analysis
       About:   About, Medical Reviewer, Professor Perspective,
                Editorial Policy, Write for Us, Contact
       Network: the same three sites, with each descriptor in a
                .footer-label span in place of the inline-styled span
     The block carries the class footer-content--split, which style.css uses
     for the two-column mobile layout.
  2. The copyright line. It gains the class footer-legal and carries the
     Privacy Policy and Legal Disclaimer links that left Quick Links. The
     year on the page is kept. On the three pages with a Spanish version
     (Roundup, Paraquat, Pesticide), the Español link that sat in Quick
     Links moves to the end of this row.

The about paragraph, the responsible-attorney line and the disclaimer are
untouched, so set_footer_attorney.py still reports every page as current.

The script only replaces a footer-content block whose text, with whitespace
collapsed, matches the old layout exactly. A page whose block matches neither
the old nor the new layout is reported as a problem and left untouched.

Pages under es/ are skipped: their footers are translated and keep the old
markup. The CSS for the new layout is scoped to footer-content--split, so
those pages render as before.

The footer sits outside <main> and check_date_consistency.py drops <footer>
before diffing body text, so this sweep does not trip the stale-stamp gate
and does not move dateModified.

Usage
-----
    python3 set_footer_layout.py
    python3 set_footer_layout.py --apply

Options
-------
    --path DIR   directory to scan (default .)
    --apply      write changes; without it the script only reports
"""

import argparse
import os
import re

OLD_BLOCK = """<div class="footer-content">
<div>
<h3>Lawsuit Informer</h3>
<p>
Lawsuit Informer is a legal education site edited by David Meldofsky, a California attorney. It explains lawsuits, consumer safety issues, toxic exposure and legal rights in plain language.
</p>
<p><strong>Questions about the site or its educational content?</strong></p>
<p>
<a href="mailto:hello@lawsuitinformer.com">
hello@lawsuitinformer.com
</a>
</p>
</div>
<div class="footer-col">
<h3>Quick Links</h3>
<ul class="footer-links">
<li><a href="about">About</a></li>
<li><a href="dr-thomas-hatzilabrou">Medical Reviewer</a></li>
<li><a href="professor-perspective">Professor Perspective</a></li>
<li><a href="contact">Contact</a></li>
<li><a href="editorial-policy">Editorial Policy</a></li>
<li><a href="contributor-guidelines">Write for Us</a></li>
<li><a href="legal-guides">Legal Guides</a></li>
<li><a href="browse-lawsuits">Browse Lawsuits</a></li>
<li><a href="news-and-analysis">News &amp; Analysis</a></li>
<li><a href="how-lawsuits-work">How Lawsuits Work</a></li>
<li><a href="privacy-policy">Privacy Policy</a></li>
<li><a href="disclaimer">Legal Disclaimer</a></li>
</ul>
</div>
<div class="footer-col">
<h3>Explore</h3>
<ul class="footer-links">
<li><a href="browse-lawsuits">Browse Lawsuits</a></li>
<li><a href="illnesses-linked-to-lawsuits">Illnesses</a></li>
<li><a href="symptoms-linked-to-lawsuits">Symptoms</a></li>
</ul>
</div>
<div class="footer-col">
<h3>Network</h3>
<ul class="footer-links">
<li>
<a href="https://lawsuit.center" target="_blank" rel="noopener">Lawsuit Center</a><br>
<span style="color:#888;font-size:0.9em;">Case review and referral</span>
</li>
<li>
<a href="https://lawsuitintelligencer.com" target="_blank" rel="noopener">Lawsuit Intelligencer</a><br>
<span style="color:#888;font-size:0.9em;">Industry analysis</span>
</li>
<li>
<a href="https://davidmeldofsky.com" target="_blank" rel="noopener">David Meldofsky</a><br>
<span style="color:#888;font-size:0.9em;">Editor &amp; founder</span>
</li>
</ul>
</div>
</div>"""

# Indented two spaces per level; the first line takes the page's own indent.
NEW_BLOCK = """<div class="footer-content footer-content--split">
  <div class="footer-brand">
    <h3>Lawsuit Informer</h3>
    <p>Lawsuit Informer is a legal education site edited by David Meldofsky, a California attorney. It explains lawsuits, consumer safety issues, toxic exposure and legal rights in plain language.</p>
    <p class="footer-contact">Questions about the site or its educational content?<br><a href="mailto:hello@lawsuitinformer.com">hello@lawsuitinformer.com</a></p>
  </div>

  <div class="footer-col">
    <h3>Explore</h3>
    <ul class="footer-links">
      <li><a href="start-here">Start Here</a></li>
      <li><a href="how-lawsuits-work">How Lawsuits Work</a></li>
      <li><a href="legal-guides">Legal Guides</a></li>
      <li><a href="browse-lawsuits">Browse Lawsuits</a></li>
      <li><a href="illnesses-linked-to-lawsuits">Illnesses</a></li>
      <li><a href="symptoms-linked-to-lawsuits">Symptoms</a></li>
      <li><a href="news-and-analysis">News &amp; Analysis</a></li>
    </ul>
  </div>

  <div class="footer-col">
    <h3>About</h3>
    <ul class="footer-links">
      <li><a href="about">About</a></li>
      <li><a href="dr-thomas-hatzilabrou">Medical Reviewer</a></li>
      <li><a href="professor-perspective">Professor Perspective</a></li>
      <li><a href="editorial-policy">Editorial Policy</a></li>
      <li><a href="contributor-guidelines">Write for Us</a></li>
      <li><a href="contact">Contact</a></li>
    </ul>
  </div>

  <div class="footer-col footer-col--network">
    <h3>Network</h3>
    <ul class="footer-links">
      <li><a href="https://lawsuit.center" target="_blank" rel="noopener">Lawsuit Center</a><span class="footer-label">Case review and referral</span></li>
      <li><a href="https://lawsuitintelligencer.com" target="_blank" rel="noopener">Lawsuit Intelligencer</a><span class="footer-label">Industry analysis</span></li>
      <li><a href="https://davidmeldofsky.com" target="_blank" rel="noopener">David Meldofsky</a><span class="footer-label">Editor &amp; founder</span></li>
    </ul>
  </div>
</div>"""

FOOTER_RE = re.compile(r"<footer\b.*?</footer>", re.S)
# footer-content block: from its opening tag up to the line that opens footer-bottom
BLOCK_RE = re.compile(
    r'^([ \t]*)(<div class="footer-content[^"]*">.*?)\n(?=[ \t]*<div class="footer-bottom">)',
    re.S | re.M,
)
COPY_OLD_RE = re.compile(r'<p>&copy; (\d{4}) Lawsuit Informer\. All rights reserved\.</p>')
COPY_NEW = (
    '<p class="footer-legal">&copy; {year} Lawsuit Informer. All rights reserved. '
    '<a href="privacy-policy">Privacy Policy</a> <a href="disclaimer">Legal Disclaimer</a></p>'
)
COPY_NEW_RE = re.compile(r'<p class="footer-legal">&copy; \d{4} Lawsuit Informer\.')
# Roundup, Paraquat and Pesticide carry a link to their Spanish page in Quick
# Links. It moves to the end of the legal row.
ES_RE = re.compile(r'[ \t]*<li><a href="(/es/[^"]+)" lang="es">Español</a></li>\n?')
ES_LINK = ' <a href="{href}" lang="es">Español</a>'


def collapse(s):
    """Markup with all whitespace next to tags removed, so indentation and
    line-wrapping variants of the same footer compare equal."""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r">\s+", ">", s)
    s = re.sub(r"\s+<", "<", s)
    return s.strip()


OLD_KEY = collapse(OLD_BLOCK)
NEW_KEY = collapse(NEW_BLOCK)


def indent(block, pad):
    return "\n".join((pad + line) if line else "" for line in block.split("\n"))


def sweep_footer(foot):
    notes, problems = [], []
    es_href = None

    m = BLOCK_RE.search(foot)
    if not m:
        problems.append("footer-content block not found")
    else:
        pad, block = m.group(1), m.group(2).rstrip()
        es = ES_RE.search(block)
        if es:
            es_href = es.group(1)
            block = ES_RE.sub("", block, count=1)
        key = collapse(block)
        if key == OLD_KEY:
            foot = foot[: m.start()] + indent(NEW_BLOCK, pad) + "\n" + foot[m.end():]
            notes.append("columns")
        elif key != NEW_KEY:
            problems.append("footer-content matches neither the old nor the new layout")

    if COPY_OLD_RE.search(foot):
        row = COPY_NEW
        if es_href:
            row = row[: -len("</p>")] + ES_LINK.format(href=es_href) + "</p>"
            notes.append("Español link")
        foot = COPY_OLD_RE.sub(lambda c: row.format(year=c.group(1)), foot, count=1)
        notes.append("legal row")
    elif not COPY_NEW_RE.search(foot):
        problems.append("copyright line not found")

    return foot, notes, problems


def sweep(html):
    footers = list(FOOTER_RE.finditer(html))
    if not footers:
        return html, [], []
    if len(footers) != 1:
        return html, [], ["%d footers" % len(footers)]
    f = footers[0]
    foot, notes, problems = sweep_footer(f.group(0))
    if problems:
        return html, [], problems
    return html[: f.start()] + foot + html[f.end():], notes, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    changed, current, problems = [], [], []
    for root, dirs, files in os.walk(args.path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        rel_root = os.path.relpath(root, args.path)
        if rel_root.split(os.sep)[0] == "es":
            dirs[:] = []
            continue
        for fn in sorted(files):
            if not fn.endswith(".html"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, args.path)
            with open(p, encoding="utf-8") as fh:
                html = fh.read()
            if "<footer" not in html:
                continue
            new, notes, probs = sweep(html)
            if probs:
                problems.append((rel, probs))
                continue
            if new == html:
                current.append(rel)
                continue
            changed.append((rel, notes))
            if args.apply:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(new)

    verb = "changed" if args.apply else "would change"
    print(f"{len(changed):3d} pages {verb}")
    print(f"{len(current):3d} pages already current")
    print(f"{len(problems):3d} pages with problems")
    print()
    for rel, notes in changed:
        print(f"  {rel}: {', '.join(notes)}")
    if problems:
        print()
        for rel, probs in problems:
            print(f"  PROBLEM {rel}: {', '.join(probs)}")
        print()
        print("Problem pages were left untouched. Fix their footer, then rerun.")


if __name__ == "__main__":
    main()
