#!/usr/bin/env python3
"""
Fold the reference boxes at the top of each update page into closed panels, so the status
section starts sooner on a phone.

Between the <h1> and the first <h2> an update page carries up to four reference boxes: the
"On This Page" list, "Related pages", "Start here" and the "Important" notice. Open, they
push the status section two to four phone screens down. This script puts each one behind a
one-line toggle, in the shape hair-relaxer-lawsuit-updates.html already uses:

    <div class="page-disclosures">
      <details class="page-disclosure"><summary>On this page</summary> ... </details>
      ...
    </div>

The group goes directly above the status <h2>. Every word and every link inside a box is
kept as it was; only the box's bold label becomes the toggle's label. Nothing else on the
page moves: the intro, the hero action strip, a crisis box and a Key Takeaways box stay
where they are and stay open.

Which pages: the status board's PAGES (generate_status_board.py) plus EXTRA, minus SKIP.
A page that already carries a hand-built page-disclosures group (hair relaxer) is left
alone, and so is a page with no box to fold.

The panels' styles ride in each page's <head> between <!-- LI-FOLD-CSS:BEGIN --> and END,
because style.css loads late and the panels sit near the top of the page. The group sits
between <!-- LI-FOLD:BEGIN --> and END. A rerun refreshes the styles, folds any box a later
rewrite of the page put back, and writes nothing when a page is already in shape.

The change is navigation, so it never moves a page's dateModified or visible stamp; the
workflow commits it with [skip lastmod] [skip actions].

    python3 fold_update_tops.py            # dry run: list what would change, write nothing
    python3 fold_update_tops.py --apply    # write the pages that changed
    python3 fold_update_tops.py --undo     # dry run of the reverse: the boxes open again, in their
                                           # old order, directly above the status section
                                           # (add --apply to write it)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXTRA = ["hernia-mesh-lawsuit"]       # owns hernia mesh status; its board row is the dated history page
SKIP = {"openai-lawsuits"}            # the hub keeps its own layout (LAYOUT_EXEMPT in check_date_consistency.py)

BEGIN, END = "<!-- LI-FOLD:BEGIN -->", "<!-- LI-FOLD:END -->"
CBEGIN, CEND = "<!-- LI-FOLD-CSS:BEGIN -->", "<!-- LI-FOLD-CSS:END -->"

# kind -> (toggle label, the bold labels a box of that kind opens with). Order is panel order.
KINDS = [
    ("toc", "On this page", ("On This Page", "On this page")),
    ("related", "Related pages", ("Related pages:", "Related pages")),
    ("start", "Start here", ("Start here:", "Start here")),
    ("notice", "Important notice", ("Important:", "Important note", "Important notice", "Important")),
]
LABEL = {k: lab for k, lab, _ in KINDS}
ORDER = {k: i for i, (k, _, _) in enumerate(KINDS)}

# The hair relaxer page's own panel rules, so every update page's toggles look the same.
CSS = """<style id="li-fold">
.page-disclosures{margin:0 0 28px;border-top:1px solid var(--rule)}
details.page-disclosure{border-bottom:1px solid var(--rule)}
details.page-disclosure>summary{font-family:var(--sans);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 2px;min-height:46px;box-sizing:border-box;font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-muted);cursor:pointer;list-style:none}
details.page-disclosure>summary::-webkit-details-marker{display:none}
details.page-disclosure>summary::after{content:"";width:8px;height:8px;flex-shrink:0;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:translateY(-2px) rotate(45deg);transition:transform .2s var(--ease)}
details.page-disclosure[open]>summary::after{transform:translateY(2px) rotate(-135deg)}
details.page-disclosure>summary:hover{color:var(--link)}
details.page-disclosure>summary:focus-visible{outline:2px solid var(--link);outline-offset:2px}
details.page-disclosure .disclosure-body{padding:0 0 18px}
details.page-disclosure .disclosure-body>p{font-family:var(--serif);font-size:1rem;line-height:1.6;color:var(--ink);margin:0}
details.page-disclosure .disclosure-body>ul{margin-top:0;margin-bottom:0}
details.page-disclosure .on-this-page{margin:0;padding:0;border:0;background:none}
details.page-disclosure .toc-list{border-top:0}
details.page-disclosure .toc-list li:last-child{border-bottom:0}
@media (prefers-reduced-motion:reduce){details.page-disclosure>summary::after{transition:none}}
</style>"""

OPEN_BOX = re.compile(r'<div class="(info-box|content-box on-this-page|on-this-page)">\s*<strong>([^<]+)</strong>')
PANEL = re.compile(r'<details class="page-disclosure" data-fold="([a-z]+)" data-box="([^"]+)">\s*<summary>[^<]*</summary>\s*'
                   r'<div class="disclosure-body">\n?(.*?)\n?[ \t]*</div>\s*</details>', re.S)


def load_pages() -> list:
    spec = importlib.util.spec_from_file_location("board", os.path.join(ROOT, "generate_status_board.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    slugs = [row[0] for row in mod.PAGES] + EXTRA
    return [s for s in dict.fromkeys(slugs) if s not in SKIP]


def div_end(text: str, start: int) -> int:
    """Index just past the </div> that closes the <div> opening at start."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", text[start:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            return start + m.end()
    return -1


def kind_of(cls: str, label: str) -> str:
    label = label.strip()
    for kind, _, labels in KINDS:
        if label in labels and ((kind == "toc") == ("on-this-page" in cls)):
            return kind
    return ""


def region(text: str) -> tuple:
    """(start, end) of the stretch between the </h1> and the first <h2 inside <main>."""
    m = text.find("<main")
    a = text.find("</h1>", m)
    b = text.find("<h2", a)
    return (a + len("</h1>"), b) if m != -1 and a != -1 and b != -1 else (-1, -1)


def take_boxes(top: str) -> tuple:
    """(top with the foldable boxes cut out, [(kind, box class, label as written, inner html, place in line)])."""
    found, out, pos = [], [], 0
    for m in OPEN_BOX.finditer(top):
        if m.start() < pos:
            continue
        kind = kind_of(m.group(1), m.group(2))
        end = div_end(top, m.start())
        if not kind or end == -1:
            continue
        inner = top[m.end():end - len("</div>")].strip("\n").rstrip()
        found.append((kind, m.group(1), m.group(2), inner, len(found)))
        line = top.rfind("\n", 0, m.start()) + 1          # take the box's own indent with it
        cut_from = line if not top[line:m.start()].strip() else m.start()
        out.append(top[pos:cut_from])
        pos = end
        while top[pos:pos + 1] == "\n" and top[pos + 1:pos + 2] == "\n":
            pos += 1                                      # one blank line where the box was, not two
    out.append(top[pos:])
    return "".join(out), found


def take_panels(top: str) -> tuple:
    """(top with an existing LI-FOLD group cut out, the panels that were in it)."""
    a, b = top.find(BEGIN), top.find(END)
    if a == -1 or b == -1:
        return top, []
    group = top[a:b + len(END)]
    panels = []
    for kind, box, inner in PANEL.findall(group):
        place, cls, label = box.replace("&quot;", '"').split("|", 2)
        if kind == "toc":                                 # drop the wrapper render() adds
            inner = re.sub(r'^\s*<div class="content-box on-this-page">\n', "", inner)
            inner = re.sub(r"\n\s*</div>\s*$", "", inner)
        panels.append((kind, cls, label, inner, int(place)))
    line = top.rfind("\n", 0, a) + 1
    return top[:line].rstrip("\n") + "\n\n" + top[b + len(END):].lstrip("\n"), panels


def render(panels: list) -> str:
    rows = []
    for kind, cls, label, inner, place in sorted(panels, key=lambda p: ORDER[p[0]]):
        box = f"{place}|{cls}|{label}".replace('"', "&quot;")
        body = inner
        if kind == "toc":
            body = f'<div class="content-box on-this-page">\n{inner}\n        </div>'
        rows.append(f'    <details class="page-disclosure" data-fold="{kind}" data-box="{box}">\n'
                    f"      <summary>{LABEL[kind]}</summary>\n"
                    f'      <div class="disclosure-body">\n{body}\n      </div>\n'
                    f"    </details>")
    return BEGIN + '\n  <div class="page-disclosures">\n' + "\n".join(rows) + "\n  </div>\n  " + END


def unfold(panels: list) -> str:
    """The boxes as they were written before folding, open, in the order they were in."""
    out = []
    for kind, cls, label, inner, _ in sorted(panels, key=lambda p: p[4]):
        out.append(f'  <div class="{cls}">\n    <strong>{label}</strong>\n{inner}\n  </div>')
    return "\n\n".join(out)


def set_css(text: str, want: bool) -> str:
    block = f"{CBEGIN}\n{CSS}\n{CEND}\n"
    if CBEGIN in text:
        text = re.sub(re.escape(CBEGIN) + r".*?" + re.escape(CEND) + r"\n?", lambda _: block if want else "", text,
                      count=1, flags=re.S)
    elif want:
        at = text.find("</head>")
        text = text[:at] + block + text[at:]
    return text


def fold(text: str, undo: bool = False) -> tuple:
    """(new text, note). The note says what was done, or why the page was left alone."""
    if 'class="page-disclosures"' in text and BEGIN not in text:
        return text, "already folded by hand"
    a, b = region(text)
    if a == -1:
        return text, "no <h1> then <h2> inside <main>"
    top = text[a:b]
    top, old = take_panels(top)
    top, new = take_boxes(top)
    panels = old + [(k, c, lab, inner, len(old) + i) for k, c, lab, inner, i in new]
    if not panels:
        return text, "no box to fold"
    block = unfold(panels) if undo else render(panels)
    top = top.rstrip() + "\n\n  " + block.lstrip() + "\n\n  "
    out = set_css(text[:a] + top + text[b:], want=not undo)
    kinds = ", ".join(LABEL[k] for k, *_ in sorted(panels, key=lambda p: ORDER[p[0]]))
    return out, ("unfolded: " if undo else "folded: ") + kinds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the pages that changed")
    ap.add_argument("--undo", action="store_true", help="open the boxes again, in their old order, above the status section")
    args = ap.parse_args()
    os.chdir(ROOT)

    changed = 0
    for slug in load_pages():
        path = slug + ".html"
        if not os.path.exists(path):
            print(f"  {path}: not found")
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new, note = fold(text, undo=args.undo)
        if new == text:
            print(f"  {path}: unchanged ({note})")
            continue
        changed += 1
        print(f"  {path}: {note}")
        if args.apply:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    verb = "changed" if args.apply else "would change"
    print(f"  {changed} pages {verb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
