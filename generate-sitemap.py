#!/usr/bin/env python3
"""
Auto-generate sitemap.xml for lawsuitinformer.com, with a <lastmod> for every URL.

<lastmod> is taken from each file's last GIT COMMIT date. That stays accurate in
CI, because file modification times get reset whenever Netlify/GitHub checks out
the repo. Falls back to file mtime, then today's date, if git history isn't there.

Runs automatically from .github/workflows/sitemap.yml on every push.
Place this file in your repo ROOT (same folder as your .html pages).

SKIP_TOKEN marks mechanical, site-wide commits (analytics snippets, handler
cleanups, formatting sweeps). Commits whose message contains it are ignored
when computing <lastmod>, so a 200-file sweep does not reset every date to the
same day and flatten the signal. Put the token in the commit message:

    git commit -m "Strip dead handlers [skip lastmod] [skip actions]"

A pull request whose TITLE contains the token marks every commit it merges,
so a GitHub web upload ("Add files via upload") needs nothing typed in its own
message box. A commit merged that way still counts for a page whose
dateModified it moved. See merged_skip_commits() and moved_page_date().

"""
import glob
import os
import re
import subprocess
import datetime

BASE_URL = "https://lawsuitinformer.com"   # no trailing slash
ROOT = os.path.dirname(os.path.abspath(__file__))

# SKIP_TOKEN marks mechanical, site-wide commits (analytics snippets, handler
# See the module docstring note below for usage.
SKIP_TOKEN = "[skip lastmod]"

# Commits to ignore for <lastmod> even though their message lacks SKIP_TOKEN.
# One full or abbreviated SHA per line in lastmod-skip-commits.txt at the repo
# root; blank lines and lines starting with # are ignored. For a mechanical
# sweep that went up without the token (a GitHub web upload keeps its default
# "Add files via upload" message), add the upload commit here and re-run the
# generator rather than rewriting history. Added 2026-10-14 after the byline
# sweep (2207acc) rolled 28 pages to the same day.
SKIP_COMMITS_FILE = os.path.join(ROOT, "lastmod-skip-commits.txt")


def skip_commits() -> list:
    try:
        with open(SKIP_COMMITS_FILE, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []

_MERGED_SKIPS = None


def merged_skip_commits() -> set:
    """Commits that reached main through a pull request whose title carries
    SKIP_TOKEN.

    GitHub writes the pull request title into the merge commit's message, and
    leaves each upload commit under it with its own message ("Add files via
    upload"). So a web upload merged under a "[skip lastmod]" title used to
    count as a change all the same: on 2026-11-18 a wording-only pass on four
    pages, merged that way, moved all four dates to that day. Added that day.
    A merge's own commits are the ones its second parent has and its first
    parent does not.
    """
    global _MERGED_SKIPS
    if _MERGED_SKIPS is not None:
        return _MERGED_SKIPS
    found = set()
    try:
        merges = subprocess.run(
            ["git", "log", "--merges", "-F", f"--grep={SKIP_TOKEN}", "--format=%H"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        for m in merges:
            r = subprocess.run(
                ["git", "rev-list", "--no-merges", f"{m}^1..{m}^2"],
                cwd=ROOT, capture_output=True, text=True,
            )
            if r.returncode == 0:
                found.update(r.stdout.split())
    except Exception:
        pass
    _MERGED_SKIPS = found
    return found


def moved_page_date(sha, path):
    """True when this commit changed the page's own dateModified.

    A pull request title covers every file in the pull request, and a title
    with SKIP_TOKEN is also how a same-day correction gets past the date gate.
    A real edit can ride in that pull request beside the correction (on
    2026-11-12 depo-provera.html did on Lawsuit Center). A commit that moved
    the page's dateModified is a change the page itself reports, so it keeps
    counting.
    """
    try:
        r = subprocess.run(
            ["git", "show", "--format=", "--unified=0", sha, "--", path],
            cwd=ROOT, capture_output=True, text=True,
        )
    except Exception:
        return False
    return bool(re.search(r'^\+.*"dateModified"', r.stdout, re.M))


# Pages kept OUT of the sitemap. Anything carrying a robots noindex is also
# dropped automatically by is_noindex() below, so this list is only a backstop.
EXCLUDE = {"404.html", "thank-you.html", "sms-terms.html"}


ROBOTS_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
ROBOTS_NAME = re.compile(r"name\s*=\s*[\"']robots[\"']", re.IGNORECASE)
NOINDEX = re.compile(r"\bnoindex\b", re.IGNORECASE)


def is_noindex(path: str) -> bool:
    """True if the page carries a robots noindex directive."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            head = fh.read(8000)
    except OSError:
        return False
    for tag in ROBOTS_TAG.findall(head):
        if ROBOTS_NAME.search(tag) and NOINDEX.search(tag):
            return True
    return False


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def git_date(path: str):
    """Last commit date (YYYY-MM-DD) for a file, or None if git can't tell us.

    Commits whose message contains SKIP_TOKEN are ignored, so mechanical
    site-wide sweeps don't reset every <lastmod> to the same day. Falls back
    to the unfiltered date for files that have only marked commits.
    """
    # --no-merges is load-bearing: without it the PR merge that lands a
    # mechanical sweep is reported as the file's last change, and the skip
    # token is bypassed for every file the merge was not TREESAME to a parent
    # on. A merge whose own message carries SKIP_TOKEN (the pull request title)
    # marks every commit it brought in; merged_skip_commits() lists those, and
    # moved_page_date() keeps the ones that moved the page's own date.
    skipped = skip_commits()
    merged = merged_skip_commits()
    for extra in (["-F", f"--grep={SKIP_TOKEN}", "--invert-grep"], []):
        try:
            r = subprocess.run(
                ["git", "log", "--no-merges", "--format=%H %cs", *extra, "--", path],
                cwd=ROOT, capture_output=True, text=True,
            )
        except Exception:
            return None
        for line in r.stdout.splitlines():
            sha, _, d = line.partition(" ")
            if extra and any(sha.startswith(x) for x in skipped):
                continue
            if extra and sha in merged and not moved_page_date(sha, path):
                continue
            if d:
                return d
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
    files = [f for f in files if not is_noindex(os.path.join(ROOT, f))]
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
