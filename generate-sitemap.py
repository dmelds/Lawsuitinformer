#!/usr/bin/env python3
"""
Auto-generate sitemap.xml for lawsuitinformer.com, with a <lastmod> for every URL.

<lastmod> is taken from each file's last GIT COMMIT date. That stays accurate in
CI, because file modification times get reset whenever Netlify/GitHub checks out
the repo. Falls back to file mtime, then today's date, if git history isn't there.

Runs automatically from .github/workflows/sitemap.yml on every push.
Place this file in your repo ROOT (same folder as your .html pages).
"""
import glob
import os
import subprocess
import datetime

BASE_URL = "https://lawsuitinformer.com"   # no trailing slash
ROOT = os.path.dirname(os.path.abspath(__file__))

# Pages kept OUT of the sitemap (matches your current exclusions). Add more as needed.
EXCLUDE = {"thank-you.html", "sms-terms.html"}


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def git_date(path: str):
    """Last commit date (YYYY-MM-DD) for a file, or None if git can't tell us."""
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", path],
            cwd=ROOT, capture_output=True, text=True,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def lastmod(path: str) -> str:
    d = git_date(path)
    if d:
        return d
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except Exception:
        return datetime.date.today().isoformat()


def loc(fname: str) -> str:
    slug = fname[:-5].replace(os.sep, "/")  # drop ".html"; es/ subdir keeps its prefix
    # homepage -> "/" (matches its canonical); everything else extensionless, no slash
    return BASE_URL + "/" if slug == "index" else f"{BASE_URL}/{slug}"


def main() -> None:
    patterns = [os.path.join(ROOT, "*.html"), os.path.join(ROOT, "es", "*.html")]
    files = [os.path.relpath(p, ROOT) for pat in patterns for p in glob.glob(pat)]
    files = [f for f in files if os.path.basename(f) not in EXCLUDE]
    files.sort(key=lambda f: (f != "index.html", f))   # homepage first, then A-Z (es/ after root)

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for f in files:
        out.append(
            f'  <url><loc>{xml_escape(loc(f))}</loc>'
            f'<lastmod>{lastmod(os.path.join(ROOT, f))}</lastmod></url>'
        )
    out.append("</urlset>")

    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"Wrote sitemap.xml with {len(files)} URLs.")


if __name__ == "__main__":
    main()
