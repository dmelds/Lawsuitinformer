#!/usr/bin/env python3
"""Flag pages whose <title> carries a Month YYYY stamp older than the build month.

Usage:
    python3 check_title_freshness.py            # warn only, exit 0
    python3 check_title_freshness.py --strict   # exit 1 if any stale stamp found

GitHub Actions step (add to an existing workflow, e.g. before deploy):

    - name: Check title freshness
      run: python3 check_title_freshness.py --strict

Scans every .html file under the repo root (skips .git). English month
names only, which matches how title stamps are written on this site.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MONTHS = {m: i + 1 for i, m in enumerate([
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
])}
STAMP = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b")
TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def main() -> int:
    strict = "--strict" in sys.argv
    now = datetime.now(timezone.utc)
    current = (now.year, now.month)
    stale = []

    for path in sorted(Path(".").rglob("*.html")):
        if ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = TITLE.search(text)
        if not m:
            continue
        title = " ".join(m.group(1).split())
        for month_name, year in STAMP.findall(title):
            if (int(year), MONTHS[month_name]) < current:
                stale.append((str(path), f"{month_name} {year}", title))

    if stale:
        print(f"STALE TITLE STAMPS (build month: {now.strftime('%B %Y')})")
        for path, stamp, title in stale:
            print(f"  {path}: '{stamp}' in <title>{title}</title>")
        if strict:
            return 1
    else:
        print("All title stamps current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
