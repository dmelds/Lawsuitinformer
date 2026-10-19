#!/usr/bin/env python3
"""
Situation-param check: Informer CTA links that promise a prefilled Center form.

Why this exists. On 10/19/26 the one real intake click of the day (DuckDuckGo
visitor, Depo-Provera hero, "I was diagnosed with a meningioma") landed at the
top of lawsuit.center/depo-provera-case-review and left nine seconds later. The
hero button carried no ?situation= value, so nothing preselected the form or
scrolled to it. A sweep the same afternoon found that of 305 hero buttons on
this site, 171 carry no situation value and a further set carry a value that
matches no option on the Center form they point to. Those look correct in the
HTML and silently do nothing on arrival. Nothing in either repo checked the
two sides against each other. This does.

How prefill works on Center (lead-events.js, PREFILL). Informer links append
?situation=<value>. On a Center page that carries the param, every <select> in
every intake form (method POST, form name not in NOT_A_LEAD) is scanned for an
option whose value attribute equals the param after whitespace is collapsed.
The first match is selected and the page scrolls to the form. The match is on
the option VALUE, never its label. A value that matches nothing leaves the
form alone, and the visitor lands at the top of the page as if no param were
sent. That last case is what this script exists to catch.

Three things are checked, for every <a href="https://lawsuit.center/..."> on
every Informer page outside <header>, <nav> and <footer>:

  BAD VALUE     The link carries situation=<value> and no option on any
                intake-form select of the target Center page has that value.
                ERROR. The nearest option values are printed so the fix is
                visible. This is the silent failure.

  NO FORM       The link carries situation= but the target Center page has no
                intake form (a hub, a guide, a page that does not exist in the
                Center checkout). ERROR. The param can do nothing there.

  MISSING       A hero-action-btn link to a page WITH an intake form carries
                no situation= at all. NOTE, not an error: whether prefill earns
                leads is unproven as of 10/19/26 (US hero arrivals since 9/15:
                44 without prefill produced 4 leads, 44 with a matched prefill
                produced 3), so the missing ones are listed and counted and
                the decision to add them stays with the editor. Inline and
                closing CTAs are not listed here; they are generic by design.

The Center checkout is read from --center (default: _center, then
../lawsuits-center). Both repos are public, so the workflow checks Center out
next to this repo with no token, the same way cannibalization.yml does.

Exit status is 0 unless --strict is passed and at least one ERROR was found.

    python3 check_situation_params.py --center _center
    python3 check_situation_params.py --center ../lawsuits-center --strict
    python3 check_situation_params.py --center _center --page depo-provera-lawsuit-updates.html
"""

import difflib
import html
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CENTER_HOST = "lawsuit.center"
PARAM = "situation"

# Mirrors NOT_A_LEAD in Center's lead-events.js. Forms named here post to a
# thank-you page but are not claimant intakes, so prefill ignores them.
NOT_A_LEAD = {"site-contact", "law-firm-inquiry", "retainer-review"}

FORM_RE = re.compile(r"<form\b[^>]*>.*?</form>", re.S | re.I)
FORM_NAME_RE = re.compile(r'\bname\s*=\s*"([^"]*)"', re.I)
FORM_METHOD_RE = re.compile(r'\bmethod\s*=\s*"([^"]*)"', re.I)
SELECT_RE = re.compile(r"<select\b[^>]*>.*?</select>", re.S | re.I)
OPTION_RE = re.compile(r'<option\b[^>]*\bvalue\s*=\s*"([^"]*)"', re.I)
LINK_RE = re.compile(r'<a\b([^>]*)\bhref\s*=\s*"(https?://(?:www\.)?lawsuit\.center/[^"]*)"([^>]*)>(.*?)</a>', re.S | re.I)
CLASS_RE = re.compile(r'\bclass\s*=\s*"([^"]*)"', re.I)
STRIP_RE = re.compile(r"<(header|nav|footer)\b.*?</\1>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def norm(value):
    return WS_RE.sub(" ", html.unescape(value)).strip()


def load_center(center):
    """path ('/slug') -> set of option values across every intake-form select,
    or None when the page exists but has no intake form."""
    forms = {}
    for page in sorted(center.glob("*.html")):
        text = page.read_text(encoding="utf-8", errors="ignore")
        values = set()
        has_form = False
        for form in FORM_RE.findall(text):
            method = (FORM_METHOD_RE.search(form) or [None, ""])[1].upper()
            name = (FORM_NAME_RE.search(form) or [None, ""])[1]
            if method != "POST" or name in NOT_A_LEAD:
                continue
            has_form = True
            for select in SELECT_RE.findall(form):
                for value in OPTION_RE.findall(select):
                    value = norm(value)
                    if value:
                        values.add(value)
        forms["/" + page.stem] = values if has_form else None
    forms.setdefault("/", None)
    return forms


def center_path(href):
    path = urlparse(href).path or "/"
    if path.endswith(".html"):
        path = path[:-5]
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return path


def scan_page(page, forms):
    text = page.read_text(encoding="utf-8", errors="ignore")
    body = STRIP_RE.sub("", text)
    errors, notes = [], []
    for attrs_a, href, attrs_b, label in LINK_RE.findall(body):
        href = html.unescape(href)
        classes = (CLASS_RE.search(attrs_a + " " + attrs_b) or [None, ""])[1].split()
        is_hero = "hero-action-btn" in classes
        query = parse_qs(urlparse(href).query, keep_blank_values=True)
        slot = query.get("utm_content", ["(untagged)"])[0]
        path = center_path(href)
        label = norm(TAG_RE.sub("", label))
        wanted = query.get(PARAM)
        if wanted is None:
            if is_hero and path in forms and forms[path]:
                notes.append((slot, path, label))
            continue
        wanted = norm(wanted[0])
        options = forms.get(path, "absent")
        if options == "absent":
            errors.append(("NO FORM", slot, path, wanted, label, "page not in the Center checkout"))
        elif options is None:
            errors.append(("NO FORM", slot, path, wanted, label, "page has no intake form"))
        elif wanted not in options:
            near = difflib.get_close_matches(wanted, sorted(options), n=3, cutoff=0.4)
            hint = "nearest: " + " | ".join(near) if near else "options: " + " | ".join(sorted(options))
            errors.append(("BAD VALUE", slot, path, wanted, label, hint))
    return errors, notes


def main(argv):
    center = None
    strict = False
    only = None
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--center" and i + 1 < len(args):
            center = Path(args[i + 1]); i += 2
        elif args[i] == "--strict":
            strict = True; i += 1
        elif args[i] == "--page" and i + 1 < len(args):
            only = args[i + 1]; i += 2
        else:
            print(f"unknown argument: {args[i]}"); return 2
    if center is None:
        for candidate in (Path("_center"), Path("../lawsuits-center")):
            if candidate.is_dir():
                center = candidate
                break
    if center is None or not center.is_dir():
        print("Center checkout not found: pass --center <path to lawsuits-center>")
        return 2

    forms = load_center(center)
    intake_pages = sum(1 for v in forms.values() if v)
    print(f"Center: {len(forms)} pages, {intake_pages} with an intake form ({center})")

    here = Path(".")
    pages = [here / only] if only else sorted(here.glob("*.html"))
    total_errors, total_notes, links_with_param = 0, 0, 0
    missing_by_page = []

    for page in pages:
        if not page.is_file():
            print(f"{page}: not found"); return 2
        errors, notes = scan_page(page, forms)
        links_with_param += 0
        if errors:
            print(f"\n{page.name}")
            for kind, slot, path, wanted, label, hint in errors:
                print(f"  ERROR {kind:9} {slot:30} -> {path}")
                print(f"        sends situation={wanted!r}  button: {label!r}")
                print(f"        {hint}")
            total_errors += len(errors)
        if notes:
            missing_by_page.append((page.name, notes))
            total_notes += len(notes)

    if missing_by_page:
        print(f"\nNOTE  hero buttons with no situation= (target form exists): {total_notes} on {len(missing_by_page)} pages")
        for name, notes in missing_by_page:
            slots = ", ".join(slot for slot, _, _ in notes)
            print(f"  {name}: {slots}")

    print(f"\n{total_errors} error(s), {total_notes} hero button(s) without a situation value")
    if strict and total_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
