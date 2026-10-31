#!/usr/bin/env python3
"""Regenerate the two managed blocks in _redirects.

1. Forced .html -> extensionless 301s. Scans the repo root for *.html pages
   and rewrites the block between the HTML BEGIN/END markers. Exact self-pair
   rules like "/page.html  /page  301!" found outside the block are treated as
   generated and swept into it.

2. Blocked repo tooling. Netlify publishes the repo root, so every checker and
   generator script at the root was downloadable from the live site (confirmed
   10/31/26 at /check_cannibalization.py). This block answers each root tooling
   file with the site 404 page, forced (!) so it fires even though the file
   exists. It also blocks the netlify/ and .github/ folders, which hold the
   newsletter function source and the workflow files. Netlify still runs the
   function at /.netlify/functions/..., a different path that this block does
   not touch. A new script added to the root is picked up on the next run.

Everything outside the two markers is preserved. Idempotent: running twice
produces no further changes.

Usage: python generate_redirects.py [--dry-run]
"""
import os, re, sys, difflib

REDIRECTS_FILE = "_redirects"
EXCLUDE = {"404", "index"}  # pages that must NOT be redirected
BEGIN = "# BEGIN AUTO-GENERATED HTML REDIRECTS (managed by generate_redirects.py - do not edit)"
END = "# END AUTO-GENERATED HTML REDIRECTS"
SELF_PAIR = re.compile(r"^/([A-Za-z0-9._-]+)\.html\s+/\1\s+301!\s*$")

TOOL_BEGIN = "# BEGIN BLOCKED REPO TOOLING (managed by generate_redirects.py - do not edit)"
TOOL_END = "# END BLOCKED REPO TOOLING"
# Root files that exist to build or check the site, never to be served.
TOOL_SUFFIXES = (".py", ".yml", ".yaml", ".sql", ".md", ".toml", ".sh")
TOOL_NAMES = {"package.json", "package-lock.json", "lastmod-skip-commits.txt"}
# Folders served from the root that hold source, not pages.
TOOL_DIRS = ("netlify", ".github")


def tooling_files():
    names = []
    for f in os.listdir("."):
        if not os.path.isfile(f):
            continue
        if f.endswith(TOOL_SUFFIXES) or f in TOOL_NAMES:
            names.append(f)
    return sorted(names)


def strip_block(lines, begin, end, sweep=None):
    """Remove a marker block (and swept stray lines). Return (kept, insert_at)."""
    kept, insert_at, in_block = [], None, False
    for ln in lines:
        s = ln.strip()
        if s == begin:
            in_block = True
            if insert_at is None:
                insert_at = len(kept)
            continue
        if s == end:
            in_block = False
            continue
        if in_block:
            continue
        if sweep and sweep(s):
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(ln)
    return kept, insert_at


def main():
    dry = "--dry-run" in sys.argv
    stems = sorted(
        f[:-5] for f in os.listdir(".")
        if f.endswith(".html") and f[:-5] not in EXCLUDE
    )
    tools = tooling_files()
    old = open(REDIRECTS_FILE).read() if os.path.exists(REDIRECTS_FILE) else ""
    lines = old.splitlines()

    # Tooling block: always first in the file, ahead of every other rule.
    lines, _ = strip_block(lines, TOOL_BEGIN, TOOL_END)
    while lines and not lines[0].strip():
        lines.pop(0)

    # HTML block: stays wherever it already sits.
    kept, insert_at = strip_block(
        lines, BEGIN, END,
        sweep=lambda s: bool(SELF_PAIR.match(s)) or (s.startswith("#") and "REGENERATE" in s),
    )
    if insert_at is None:
        insert_at = len(kept)
    html_block = [BEGIN] + [f"/{s}.html  /{s}  301!" for s in stems] + [END]
    body = kept[:insert_at] + html_block + kept[insert_at:]

    tool_block = (
        [TOOL_BEGIN]
        + [f"/{f}  /404.html  404!" for f in tools]
        + [f"/{d}/*  /404.html  404!" for d in TOOL_DIRS]
        + [TOOL_END, ""]
    )
    new = "\n".join(tool_block + body).rstrip("\n") + "\n"

    summary = f"{len(stems)} html rules, {len(tools)} tooling files + {len(TOOL_DIRS)} folders blocked"
    if new == old:
        print(f"{REDIRECTS_FILE} already up to date ({summary}).")
        return
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     fromfile=REDIRECTS_FILE, tofile=REDIRECTS_FILE, lineterm=""))
    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    if dry:
        print("\n".join(diff))
        print(f"\nDRY RUN: would write {summary} (+{adds}/-{dels} lines).")
    else:
        open(REDIRECTS_FILE, "w").write(new)
        print(f"Wrote {REDIRECTS_FILE}: {summary} (+{adds}/-{dels} lines).")


if __name__ == "__main__":
    main()
