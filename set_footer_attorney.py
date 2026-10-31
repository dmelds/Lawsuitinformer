#!/usr/bin/env python3
"""Bring the Informer footer in line with the attorney-advertising rules.

Lawsuit Informer sends readers to Lawsuit Center, David Meldofsky's intake and
referral practice, through its case-review CTAs. California Rule of
Professional Conduct 7.2(c) asks a lawyer advertising communication to carry
the name and address of at least one lawyer responsible for its content, so
every English page gets the same responsible-attorney line Center carries.

Three edits per page, all inside <footer>:

  1. The about paragraph. "an independent platform" is replaced with a
     sentence naming the editor, since an attorney-advertising line beside
     "independent platform" contradicts itself.
  2. The Lawsuit Center label in the Network column. "Case-review directory"
     becomes "Case review and referral", matching how Center describes
     itself since 10/12/26.
  3. The responsible-attorney line, inserted in footer-bottom directly above
     the copyright line. The "Attorney-led legal education" disclaimer above
     it stays as is.

Pages under es/ are skipped: their footers are translated and are a separate
decision. thank-you.html has no footer and is not counted.

Each edit is checked on its own, so a page that already carries one edit and
not the others gets only what it is missing. A rerun on a swept tree changes
nothing. If the name or address changes, edit ATTORNEY and ADDRESS and rerun;
the old attorney line is swapped for the new one on every page.

A page with a footer that matches none of the anchors is reported as a
problem and left untouched rather than guessed at.

The footer sits outside <main> and check_date_consistency.py drops <footer>
before diffing body text, so this sweep does not trip the stale-stamp gate
and does not move dateModified.

Usage
-----
    python3 set_footer_attorney.py
    python3 set_footer_attorney.py --apply

Options
-------
    --path DIR   directory to scan (default .)
    --apply      write changes; without it the script only reports
"""

import argparse
import os
import re

ATTORNEY = "David Meldofsky"
ADDRESS = "6210 Wilshire Blvd. Ste 200, Los Angeles, CA 90048"

ABOUT_OLD = (
    "Lawsuit Informer is an independent platform providing clear, accessible "
    "information about lawsuits, consumer safety issues, toxic exposure, and legal rights."
)
ABOUT_NEW = (
    "Lawsuit Informer is a legal education site edited by David Meldofsky, a California "
    "attorney. It explains lawsuits, consumer safety issues, toxic exposure and legal "
    "rights in plain language."
)

LABEL_OLD = "Case-review directory"
LABEL_NEW = "Case review and referral"

LINE = (
    '<p class="footer-attorney">Attorney advertising. Responsible attorney: '
    + ATTORNEY + ", " + ADDRESS + ".</p>"
)
LINE_RE = re.compile(r'<p class="footer-attorney">[^<]*</p>')
COPY_RE = re.compile(r'^([ \t]*)<p>&copy; \d{4} Lawsuit Informer\. All rights reserved\.</p>', re.M)
FOOTER_RE = re.compile(r"<footer\b.*?</footer>", re.S)


def sweep_footer(foot):
    notes, problems = [], []

    if ABOUT_OLD in foot:
        foot = foot.replace(ABOUT_OLD, ABOUT_NEW)
        notes.append("about")
    elif ABOUT_NEW not in foot:
        problems.append("about paragraph not found")

    if LABEL_OLD in foot:
        foot = foot.replace(LABEL_OLD, LABEL_NEW)
        notes.append("center label")
    elif LABEL_NEW not in foot:
        problems.append("Center label not found")

    if "footer-attorney" in foot:
        new = LINE_RE.sub(LINE, foot)
        if new != foot:
            foot = new
            notes.append("attorney line updated")
    else:
        m = list(COPY_RE.finditer(foot))
        if len(m) != 1:
            problems.append("copyright line found %d times" % len(m))
        else:
            m = m[0]
            foot = foot[: m.start()] + m.group(1) + LINE + "\n" + foot[m.start():]
            notes.append("attorney line")

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
