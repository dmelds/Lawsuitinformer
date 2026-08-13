#!/usr/bin/env python3
"""Install the outbound cta_click GA4 listener on every page.

The intake form lives on lawsuit.center, so a click on an outbound Center link
is the only conversion signal this property can record on its own side. That
listener currently exists on two pages, which leaves the other ~520 outbound
links across the site invisible in GA4.

The listener is delegated and idempotent: it attaches one click and one
auxclick handler on the document, reads utm_content off the clicked href for
the slot name, and no-ops when window.gtag has not loaded. It is inserted into
the existing LI-DARK-JS block immediately after the decorate() call, which is
the one anchor present exactly once in every page on this site.

A page that already defines ctaClick is left untouched, so the script is safe
to rerun and safe to schedule.

Usage
-----
    python3 add_cta_events.py
    python3 add_cta_events.py --apply

Options
-------
    --path DIR   directory to scan (default .)
    --apply      write changes; without it the script only reports
"""
import argparse
import io
import re
import sys
from pathlib import Path

MARKER = "LI-DARK-JS:BEGIN"
GUARD = "cta_click listener v2"

ANCHOR = "\n  decorate();\n"

BLOCK = """
  /* Outbound CTA click -> GA4. cta_click listener v2. The form lives on
     lawsuit.center, so this is the only conversion signal Informer can record
     on its own side. */
  function ctaClick(e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href*="lawsuit.center"]') : null;
    if (!a || typeof window.gtag !== 'function') return;
    /* Chrome is not a CTA. The sitewide footer link to lawsuit.center appears on
       every page untagged, so counting it would bury every real referral under
       one enormous 'unknown' slot. */
    if (a.closest && a.closest('footer, nav, header')) return;
    var slot = 'unknown';
    try { slot = new URL(a.href, location.href).searchParams.get('utm_content') || 'unknown'; }
    catch (err) {}
    window.gtag('event', 'cta_click', {
      cta_slot: slot,
      cta_page: location.pathname,
      cta_label: (a.textContent || '').trim().slice(0, 60)
    });
  }
  document.addEventListener('click', ctaClick, true);
  document.addEventListener('auxclick', ctaClick, true);
"""

CENTER_LINK = re.compile(r'https://lawsuit\.center[^"\']*')

V1_BLOCK = """
  /* Outbound CTA click -> GA4. The form lives on lawsuit.center, so this is the
     only conversion signal Informer can record on its own side. */
  function ctaClick(e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href*="lawsuit.center"]') : null;
    if (!a || typeof window.gtag !== 'function') return;
    var slot = 'unknown';
    try { slot = new URL(a.href, location.href).searchParams.get('utm_content') || 'unknown'; }
    catch (err) {}
    window.gtag('event', 'cta_click', {
      cta_slot: slot,
      cta_page: location.pathname,
      cta_label: (a.textContent || '').trim().slice(0, 60)
    });
  }
  document.addEventListener('click', ctaClick, true);
  document.addEventListener('auxclick', ctaClick, true);
"""


def scan(path):
    """Return (status, center_links, untagged_links) for one file."""
    html = io.open(path, encoding="utf-8").read()
    links = CENTER_LINK.findall(html)
    untagged = [u for u in links if "utm_content=" not in u]

    if MARKER not in html:
        return "no-block", html, links, untagged
    if GUARD in html:
        return "present", html, links, untagged
    if html.count(ANCHOR) != 1:
        return "no-anchor", html, links, untagged
    # A page carrying the v1 listener is upgraded, not skipped. Leaving v1 in
    # place while inserting v2 would define ctaClick twice in one scope and
    # register the surviving definition twice, doubling every event.
    if V1_BLOCK in html:
        return "upgrade", html, links, untagged
    if "function ctaClick" in html:
        return "unknown-version", html, links, untagged
    return "patch", html, links, untagged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.path)
    patched, present, problems = [], [], []
    total_links = total_untagged = 0

    for path in sorted(root.rglob("*.html")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        status, html, links, untagged = scan(path)
        total_links += len(links)
        total_untagged += len(untagged)

        if status == "present":
            present.append(str(path))
        elif status in ("patch", "upgrade"):
            patched.append((str(path), len(links), len(untagged), status))
            if args.apply:
                out = html.replace(V1_BLOCK, "", 1) if status == "upgrade" else html
                out = out.replace(ANCHOR, ANCHOR + BLOCK, 1)
                io.open(path, "w", encoding="utf-8").write(out)
        else:
            problems.append((str(path), status))

    mode = "APPLIED" if args.apply else "DRY RUN (no files written)"
    print(f"cta_click sweep - {mode}")
    print(f"  {len(patched)} files patched, {len(present)} already carried the listener")
    print(f"  {len(problems)} files could not be patched")
    upgrades = sum(1 for p in patched if p[3] == "upgrade")
    if upgrades:
        print(f"  of those, {upgrades} were upgraded from the v1 listener")
    print(f"  outbound lawsuit.center links seen: {total_links}")
    print(f"    in footer/nav/header, deliberately not counted: {total_untagged}")

    for path, status in problems:
        print(f"\n  {path}  [SKIPPED - {status}]")

    if not args.apply:
        for path, links, untagged, status in patched:
            verb = "^ upgraded from v1" if status == "upgrade" else "+ ctaClick listener"
            print(f"\n  {path}")
            print(f"    {verb}   ({links} Center links, {untagged} in chrome and not counted)")

    # A file that carries the dark block but not the anchor is a real drift
    # signal, not a routine skip. Fail so the scheduled run notifies.
    return 1 if any(s in ("no-anchor", "unknown-version") for _, s in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
