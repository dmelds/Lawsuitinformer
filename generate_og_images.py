#!/usr/bin/env python3
"""
Generate a social-preview image for every page and point the page at it.

Each page gets og/<slug>.jpg, a 1200 by 630 card in the site's own type and colors: the wordmark,
an optional section label, the page's headline set in Fraunces, and the tagline. Bing named Open
Graph images as the thumbnail source for Bing News after it retired PubHub, and one shared
og-default.jpg gave every page the same thumbnail.

Headline: the page's <h1>, with entities and inner tags removed. When a page has no <h1> the
<title> is used with the site suffix stripped, through page_title() in generate_feed.py.

Section label: the JSON-LD articleSection when the page declares one; "News & Analysis" when the
page declares NewsArticle and no articleSection; otherwise no label.

Which pages: every .html file in the root and in es/, except EXCLUDE from generate_feed.py and
pages carrying a robots noindex. A page is patched only when its og:image is og-default.jpg or is
already its own card, so a page given a custom image by hand is left alone.

What changes in a page: every reference to og-default.jpg (og:image, twitter:image, and the
JSON-LD image url where present) becomes the page's own card, and the default og:image:alt
becomes the headline. Nothing else in the file is touched.

og/manifest.json records what each card was rendered from. A card is re-rendered only when its
headline, label or the template version changes, so a page edit that leaves the headline alone
produces no image churn in git. Cards whose page no longer exists are removed.

Fonts: the site's own woff2 files in fonts/ are converted to TTF in a temporary folder at run
time. Needs Pillow, fonttools and brotli:

    pip install pillow fonttools brotli

    python3 generate_og_images.py             # render cards and patch pages
    python3 generate_og_images.py --dry-run   # report what would change, write nothing
    python3 generate_og_images.py --only raine-v-openai-lawsuit   # one page, for a look
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_feed import (  # noqa: E402
    BASE_URL, EXCLUDE, LD_BLOCK, ROOT, _iter_nodes, _types, is_noindex, page_title, unescape,
)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: pip install pillow fonttools brotli")

TEMPLATE_VERSION = 1
OUT_DIR = ROOT / "og"
MANIFEST = OUT_DIR / "manifest.json"
DEFAULT_IMAGE = f"{BASE_URL}/og-default.jpg"
DEFAULT_ALT = "Lawsuit Informer — Attorney-led legal education"
LOGO = ROOT / "lawsuit-informer-1.png"
FONT_DIR = ROOT / "fonts"
PAGE_DIRS = (ROOT, ROOT / "es")

W, H = 1200, 630
MARGIN = 72
BG = (250, 250, 247)        # --bg
INK = (26, 26, 26)          # --ink
MUTED = (90, 87, 80)        # --ink-muted
RUST = (176, 74, 47)        # --link
AMBER = (212, 162, 78)      # --amber
TAGLINE = "Attorney-led legal education  ·  David Meldofsky"
DOMAIN = "lawsuitinformer.com"

H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
TAGS = re.compile(r"<[^>]+>")
OG_IMAGE = re.compile(r"""<meta\s+property=["']og:image["']\s+content=["']([^"']*)["']""", re.I)
OG_ALT = re.compile(
    r"""(<meta\s+property=["']og:image:alt["']\s+content=["'])([^"']*)(["'])""", re.I)


# ---------------------------------------------------------------- fonts

def load_fonts() -> dict:
    """Convert the site's woff2 files to TTF in a temp folder and return loaded faces."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:  # pragma: no cover
        sys.exit("fonttools and brotli are required: pip install fonttools brotli")
    tmp = Path(tempfile.mkdtemp(prefix="og-fonts-"))
    wanted = {
        "display": "fraunces-v38-latin-700.woff2",
        "sans": "ibm-plex-sans-v23-latin-500.woff2",
        "sans_bold": "ibm-plex-sans-v23-latin-600.woff2",
    }
    paths = {}
    for key, name in wanted.items():
        src = FONT_DIR / name
        if not src.exists():
            sys.exit(f"missing font {src}")
        f = TTFont(str(src))
        f.flavor = None
        out = tmp / (src.stem + ".ttf")
        f.save(str(out))
        paths[key] = out
    return paths


def face(paths: dict, key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(paths[key]), size)


# ---------------------------------------------------------------- page reading

def headline(html: str) -> str:
    m = H1.search(html)
    if m:
        text = unescape(TAGS.sub("", m.group(1)))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text
    return page_title(html)


def section(html: str) -> str:
    label = ""
    news = False
    for raw in LD_BLOCK.findall(html):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _iter_nodes(data):
            if not label:
                value = node.get("articleSection")
                if isinstance(value, str) and value.strip():
                    label = value.strip()
            if _types(node) & {"NewsArticle"}:
                news = True
    if label:
        return label
    return "News & Analysis" if news else ""


def card_rel(path: Path) -> str:
    """og/<slug>.jpg, or og/es/<slug>.jpg for the Spanish folder."""
    rel = path.relative_to(ROOT).with_suffix(".jpg")
    return str(Path("og") / rel).replace("\\", "/")


def pages() -> list[Path]:
    out = []
    for d in PAGE_DIRS:
        if d.is_dir():
            out += sorted(d.glob("*.html"))
    return [p for p in out if p.name not in EXCLUDE]


# ---------------------------------------------------------------- drawing

def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = text.split()
    lines, line = [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def fit_headline(draw, text: str, paths: dict, width: int, height: int):
    """Largest Fraunces size from 66 down to 38 that fits the box in at most four lines."""
    for size in range(66, 37, -2):
        font = face(paths, "display", size)
        lines = wrap(draw, text, font, width)
        leading = int(size * 1.16)
        if len(lines) <= 4 and len(lines) * leading <= height:
            return font, lines, leading
    font = face(paths, "display", 38)
    lines = wrap(draw, text, font, width)[:4]
    return font, lines, int(38 * 1.16)


def spaced(draw, xy, text: str, font, fill, tracking: float):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def render(head: str, label: str, paths: dict, logo: Image.Image) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # Rust band across the top, the site's link color.
    d.rectangle([0, 0, W, 10], fill=RUST)

    # Wordmark, top left; domain, top right.
    lw = 250
    lh = round(logo.height * lw / logo.width)
    im.paste(logo.resize((lw, lh), Image.LANCZOS), (MARGIN, 52), logo.resize((lw, lh), Image.LANCZOS))
    f_dom = face(paths, "sans", 22)
    d.text((W - MARGIN, 52 + lh // 2), DOMAIN, font=f_dom, fill=MUTED, anchor="rm")

    # Optional section label.
    y = 176
    if label:
        f_kick = face(paths, "sans_bold", 21)
        spaced(d, (MARGIN, y), label.upper(), f_kick, RUST, 2.4)
        y += 46

    # Headline box runs from y to the tagline rule.
    box_top = y
    box_bottom = 528
    font, lines, leading = fit_headline(d, head, paths, W - 2 * MARGIN, box_bottom - box_top)
    ty = box_top
    for line in lines:
        d.text((MARGIN, ty), line, font=font, fill=INK)
        ty += leading

    # Amber rule and tagline at the foot.
    d.rectangle([MARGIN, 548, MARGIN + 120, 551], fill=AMBER)
    f_tag = face(paths, "sans", 22)
    d.text((MARGIN, 568), TAGLINE, font=f_tag, fill=MUTED)
    return im


# ---------------------------------------------------------------- main

def fingerprint(head: str, label: str) -> str:
    return hashlib.sha1(f"{TEMPLATE_VERSION}|{label}|{head}".encode("utf-8")).hexdigest()[:16]


def patch(html: str, card_url: str, head: str) -> str:
    out = html.replace(DEFAULT_IMAGE, card_url)
    alt = _html.escape(f"{head} — Lawsuit Informer", quote=True)
    out = OG_ALT.sub(lambda m: m.group(1) + alt + m.group(3) if m.group(2) == DEFAULT_ALT else m.group(0), out)
    return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    only = argv[argv.index("--only") + 1] if "--only" in argv else None

    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}

    paths = load_fonts()
    logo = Image.open(LOGO).convert("RGBA")

    rendered = patched = skipped = 0
    seen = set()
    for path in pages():
        if only and path.stem != only:
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        if is_noindex(html):
            continue
        m = OG_IMAGE.search(html)
        if not m:
            continue
        rel = card_rel(path)
        card_url = f"{BASE_URL}/{rel}"
        current = m.group(1)
        if current not in (DEFAULT_IMAGE, card_url):
            skipped += 1
            continue
        head = headline(html)
        if not head:
            continue
        label = section(html)
        seen.add(rel)

        fp = fingerprint(head, label)
        target = ROOT / rel
        if manifest.get(rel) != fp or not target.exists():
            if not dry:
                target.parent.mkdir(parents=True, exist_ok=True)
                render(head, label, paths, logo).save(target, "JPEG", quality=86, optimize=True, progressive=True)
            manifest[rel] = fp
            rendered += 1
            print(f"render  {rel}  <- {head[:70]}")

        new_html = patch(html, card_url, head)
        if new_html != html:
            if not dry:
                path.write_text(new_html, encoding="utf-8")
            patched += 1
            print(f"patch   {path.relative_to(ROOT)}")

    # Drop cards whose page is gone, unless this is a partial run.
    removed = 0
    if not only:
        for rel in [r for r in manifest if r not in seen]:
            f = ROOT / rel
            if f.exists() and not dry:
                f.unlink()
            manifest.pop(rel, None)
            removed += 1
            print(f"remove  {rel}")

    if not dry and not only:
        OUT_DIR.mkdir(exist_ok=True)
        MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=0) + "\n", encoding="utf-8")

    mode = "[dry run] " if dry else ""
    print(f"{mode}{rendered} cards rendered, {patched} pages patched, {removed} cards removed, "
          f"{skipped} pages with a custom image left alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
