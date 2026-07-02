#!/usr/bin/env python3
"""Regenerate the forced .html -> extensionless redirect block in _redirects.

Scans the repo root for *.html pages and rewrites the block between the
BEGIN/END markers below. Everything outside the markers is preserved,
including custom redirects (only exact self-pair rules like
"/page.html  /page  301!" are treated as generated and swept into the block).
Idempotent: running twice produces no further changes.

Usage: python generate_redirects.py [--dry-run]
"""
import os, re, sys, difflib

REDIRECTS_FILE = "_redirects"
EXCLUDE = {"404", "index"}  # pages that must NOT be redirected
BEGIN = "# BEGIN AUTO-GENERATED HTML REDIRECTS (managed by generate_redirects.py - do not edit)"
END = "# END AUTO-GENERATED HTML REDIRECTS"
SELF_PAIR = re.compile(r"^/([A-Za-z0-9._-]+)\.html\s+/\1\s+301!\s*$")

def main():
    dry = "--dry-run" in sys.argv
    stems = sorted(
        f[:-5] for f in os.listdir(".")
        if f.endswith(".html") and f[:-5] not in EXCLUDE
    )
    old = open(REDIRECTS_FILE).read() if os.path.exists(REDIRECTS_FILE) else ""
    lines = old.splitlines()

    kept, insert_at, in_block = [], None, False
    for ln in lines:
        s = ln.strip()
        if s == BEGIN:
            in_block = True
            if insert_at is None: insert_at = len(kept)
            continue
        if s == END:
            in_block = False
            continue
        if in_block:
            continue
        if SELF_PAIR.match(s) or (s.startswith("#") and "REGENERATE" in s):
            if insert_at is None: insert_at = len(kept)
            continue
        kept.append(ln)

    if insert_at is None:
        insert_at = len(kept)
    block = [BEGIN] + [f"/{s}.html  /{s}  301!" for s in stems] + [END]
    new_lines = kept[:insert_at] + block + kept[insert_at:]
    new = "\n".join(new_lines).rstrip("\n") + "\n"

    if new == old:
        print(f"{REDIRECTS_FILE} already up to date ({len(stems)} rules).")
        return
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     fromfile=REDIRECTS_FILE, tofile=REDIRECTS_FILE, lineterm=""))
    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    if dry:
        print("\n".join(diff))
        print(f"\nDRY RUN: would write {len(stems)} rules (+{adds}/-{dels} lines).")
    else:
        open(REDIRECTS_FILE, "w").write(new)
        print(f"Wrote {REDIRECTS_FILE}: {len(stems)} rules (+{adds}/-{dels} lines).")

if __name__ == "__main__":
    main()
