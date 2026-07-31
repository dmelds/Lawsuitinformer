#!/usr/bin/env python3
"""
Normalize document metadata on the court filings in /case-filings.

Search engines use a PDF's embedded /Title as the result title. Filings
arrive from PACER, from other firms, and out of word processors carrying
whatever the drafter left behind: "Microsoft Word - Complaint (FINAL)(to
be filed)", another firm's branding, a keyword-stuffed /Keywords field,
or nothing at all.

This sets /Title, strips /Author, /Subject, /Keywords and /Creator, and
removes any XMP metadata stream so the DocInfo title is the one search
engines see. Page content is never touched. The filing itself is
unchanged, and the page count is asserted before and after as a guard.

pikepdf (qpdf) rather than pypdf, because pypdf re-serializes object
streams and inflates several of these files by 50 to 70 percent.

Dispatch from .github/workflows/pdf-metadata.yml. Idempotent: files that
already carry the target metadata are skipped, so a second run commits
nothing.
"""
import os
import sys

import pikepdf

ROOT = os.path.dirname(os.path.abspath(__file__))
FILINGS = os.path.join(ROOT, "case-filings")

# filename -> /Title. Add a line here whenever a filing is added.
TITLES = {
    "angelilli-v-activision-blizzard-complaint.pdf":
        "Angelilli v. Activision Blizzard Complaint",
    "antonetti-v-activision-blizzard-complaint.pdf":
        "Antonetti v. Activision Blizzard Complaint",
    "baggaley-v-roblox-complaint.pdf":
        "Baggaley v. Roblox Complaint",
    "dunn-v-activision-blizzard-complaint.pdf":
        "Dunn v. Activision Blizzard Complaint",
    "johnson-v-activision-blizzard-complaint.pdf":
        "Johnson v. Activision Blizzard Complaint",
    "lacey-v-openai-complaint.pdf":
        "Lacey v. OpenAI Complaint",
    "mdl-3109-order-denying-transfer.pdf":
        "In re Video Game Addiction MDL No. 3109 Order Denying Transfer",
    "new-york-v-3m-pfas-complaint.pdf":
        "New York v. 3M PFAS Complaint",
    "parish-v-openai-complaint.pdf":
        "Parish v. OpenAI Complaint",
    "shamblin-v-openai-complaint.pdf":
        "Shamblin v. OpenAI Amended Complaint",
}

# Wiped on every filing. Third-party drafter names and inherited SEO
# keyword stuffing serve no purpose on a document we host but did not write.
CLEARED = ("/Author", "/Subject", "/Keywords", "/Creator")


def state(path: str):
    """Return (title, leftovers, has_xmp, pages) for a filing."""
    with pikepdf.open(path) as pdf:
        title = str(pdf.docinfo.get("/Title", ""))
        leftovers = [k for k in CLEARED if k in pdf.docinfo]
        has_xmp = "/Metadata" in pdf.Root
        return title, leftovers, has_xmp, len(pdf.pages)


def rewrite(path: str, title: str) -> tuple:
    before_size = os.path.getsize(path)
    _, _, _, before_pages = state(path)

    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        if "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]
        for key in CLEARED:
            if key in pdf.docinfo:
                del pdf.docinfo[key]
        pdf.docinfo["/Title"] = title
        pdf.save(path, object_stream_mode=pikepdf.ObjectStreamMode.preserve)

    _, _, _, after_pages = state(path)
    if after_pages != before_pages:
        raise SystemExit(
            f"ABORT {os.path.basename(path)}: page count changed "
            f"{before_pages} -> {after_pages}"
        )
    return before_size, os.path.getsize(path), after_pages


def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

    if not os.path.isdir(FILINGS):
        print(f"No case-filings directory at {FILINGS}")
        return 1

    on_disk = {f for f in os.listdir(FILINGS) if f.lower().endswith(".pdf")}
    changed = 0

    for name in sorted(TITLES):
        if name not in on_disk:
            print(f"GONE  {name} (mapped but not on disk)")
            continue

        path = os.path.join(FILINGS, name)
        want = TITLES[name]
        try:
            title, leftovers, has_xmp, pages = state(path)
        except Exception as exc:
            print(f"ERROR {name}: {exc}")
            return 1

        if title == want and not leftovers and not has_xmp:
            print(f"ok    {name}")
            continue

        changed += 1
        if dry_run:
            was = title or "(no title)"
            extra = ", ".join(list(leftovers) + (["XMP"] if has_xmp else []))
            print(f"WOULD {name}")
            print(f"        was: {was}")
            print(f"        now: {want}")
            if extra:
                print(f"        clear: {extra}")
            continue

        b, a, pages = rewrite(path, want)
        print(f"WROTE {name} -> {want}  ({b:,} -> {a:,} bytes, {pages} pages)")

    for name in sorted(on_disk - set(TITLES)):
        print(f"SKIP  {name} (no title mapped, add it to TITLES)")

    verb = "would change" if dry_run else "changed"
    print(f"\n{verb} {changed} of {len(on_disk)} filings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
