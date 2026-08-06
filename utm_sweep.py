#!/usr/bin/env python3
"""Normalize cross-property UTM tags on in-content links.

Two problems this fixes.

1. utm_medium values like article, sticky, intent, redirect and checker are not
   values GA4 recognizes, so every tagged cross-property click is bucketed as
   Unassigned instead of Referral. The placement detail already lives in
   utm_content, so the medium can safely become referral and the old value is
   preserved into utm_content when that parameter is missing.

2. Most in-content links to the partner property carry no UTM at all, so the
   handoff is invisible in GA4 either way.

Only in-content anchors are touched. Anything inside <head>, <nav>, <footer>,
<script>, <style> or an HTML comment is left alone, because tagging navigation
and footer links fires a campaign on every page view and buries real referrals.

A URL whose query string sits after the fragment (path#anchor?utm_source=...)
is reported and skipped rather than rewritten. Those parameters are inside the
fragment, so they never reach the server and no analytics tool has ever seen
them; appending a second, valid set in front of the fragment produces a URL
carrying two contradictory campaigns. Fix the source link by hand, then rerun.

Usage
-----
    python3 utm_sweep.py --source lawsuitinformer --partner lawsuit.center
    python3 utm_sweep.py --source lawsuitinformer --partner lawsuit.center --apply

Options
-------
    --campaign NAME   utm_campaign for links that had no tags (default cross_property)
    --path DIR        directory to scan (default .)
    --apply           write changes; without it the script only reports
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Mediums GA4 maps to a real channel on its own.
GA4_MEDIUMS = {"referral", "organic", "cpc", "email", "social", "affiliate",
               "display", "banner", "paid_social", "paid_search", "video", "audio"}
TARGET_MEDIUM = "referral"

SKIP_BLOCKS = re.compile(
    r"<nav\b.*?</nav>|<footer\b.*?</footer>|<script\b.*?</script>"
    r"|<style\b.*?</style>|<!--.*?-->",
    re.S | re.I,
)
HEAD_END = re.compile(r"</head\s*>", re.I)
ANCHOR = re.compile(r'<a\b[^>]*?href="([^"]+)"', re.I)


def skip_spans(html):
    spans = []
    m = HEAD_END.search(html)
    if m:
        spans.append((0, m.end()))
    for b in SKIP_BLOCKS.finditer(html):
        spans.append((b.start(), b.end()))
    return spans


def in_span(pos, spans):
    return any(a <= pos < b for a, b in spans)


def parse_query(raw):
    """Ordered list of (key, value) from an HTML-encoded query string."""
    out = []
    if not raw:
        return out
    for part in raw.replace("&amp;", "&").split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        out.append((key, value))
    return out


def build_query(pairs):
    return "&amp;".join(f"{k}={v}" if v != "" else k for k, v in pairs)


def retag(url, source, campaign, slug):
    """Return (new_url, action) where action is None, 'malformed', 'medium' or 'tagged'."""
    parts = urlsplit(url)
    if "?" in parts.fragment:
        # Query string authored after the fragment. Dead parameters, and not
        # safe to rewrite automatically — see module docstring.
        return url, "malformed"
    pairs = parse_query(parts.query)
    keys = {k for k, _ in pairs}

    if "utm_source" not in keys and "utm_medium" not in keys:
        pairs += [("utm_source", source), ("utm_medium", TARGET_MEDIUM),
                  ("utm_campaign", campaign), ("utm_content", slug)]
        action = "tagged"
    else:
        medium = next((v for k, v in pairs if k == "utm_medium"), None)
        if medium is None:
            pairs.append(("utm_medium", TARGET_MEDIUM))
            action = "medium"
        elif medium.lower() in GA4_MEDIUMS:
            return url, None
        else:
            pairs = [(k, TARGET_MEDIUM if k == "utm_medium" else v) for k, v in pairs]
            if "utm_content" not in keys:
                pairs.append(("utm_content", medium))
            action = "medium"
        if "utm_source" not in keys:
            pairs.insert(0, ("utm_source", source))

    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       build_query(pairs), parts.fragment)), action


def sweep_file(path, source, partner, campaign, apply_changes):
    html = path.read_text(encoding="utf-8", errors="ignore")
    spans = skip_spans(html)
    slug = path.stem
    edits = []

    for m in ANCHOR.finditer(html):
        if in_span(m.start(), spans):
            continue
        url = m.group(1)
        host = urlsplit(url).netloc.lower()
        if host != partner and host != "www." + partner:
            continue
        new_url, action = retag(url, source, campaign, slug)
        if action == "malformed":
            edits.append((None, None, url, url, action))
            continue
        if action:
            edits.append((m.start(1), m.end(1), url, new_url, action))

    if not edits:
        return []

    writable = [e for e in edits if e[0] is not None]
    if apply_changes and writable:
        out = html
        for start, end, _old, new_url, _a in reversed(writable):
            out = out[:start] + new_url + out[end:]
        path.write_text(out, encoding="utf-8")

    return [(str(path), old, new, action) for _s, _e, old, new, action in edits]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="utm_source to write, e.g. lawsuitinformer")
    ap.add_argument("--partner", required=True, help="partner host, e.g. lawsuit.center")
    ap.add_argument("--campaign", default="cross_property")
    ap.add_argument("--path", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.path)
    changes = []
    for path in sorted(root.rglob("*.html")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        changes += sweep_file(path, args.source, args.partner.lower(),
                              args.campaign, args.apply)

    mode = "APPLIED" if args.apply else "DRY RUN (no files written)"
    files = sorted({c[0] for c in changes})
    medium = [c for c in changes if c[3] == "medium"]
    tagged = [c for c in changes if c[3] == "tagged"]
    malformed = [c for c in changes if c[3] == "malformed"]
    print(f"UTM sweep — {mode}")
    print(f"  partner: {args.partner}   source: {args.source}")
    print(f"  {len(changes)} links across {len(files)} files")
    print(f"    medium normalized to {TARGET_MEDIUM}: {len(medium)}")
    print(f"    newly tagged: {len(tagged)}")
    print(f"    skipped, query after fragment: {len(malformed)}")
    for path, old, new, action in changes:
        if action == "malformed":
            print(f"\n  {path}  [SKIPPED — query sits after the fragment, fix by hand]")
            print(f"    ! {old}")
            continue
        print(f"\n  {path}  [{action}]")
        print(f"    - {old}")
        print(f"    + {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
