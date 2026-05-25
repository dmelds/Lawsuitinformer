def process_file(filepath, dry_run=False):
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Universal Link Cleaner: 
    # This removes .html from ALL href links (nav, footer, body, etc.)
    html = re.sub(r'href="([^"]+)\.html"', r'href="\1"', html)
    
    # Existing cleanup for meta tags
    html = html.replace('.html"', '"').replace('.html">', '">')

    # 2. Proceed with OG Tag logic
    if OG_PRESENT_RE.search(html):
        # Even if skipped, we still save the clean version if changes were made
        if ".html" in html:
            if not dry_run:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(html)
        return "skipped (already has og: tags)"

    title = extract_first(TITLE_RE, html)
    description = extract_first(DESC_RE, html) or extract_first(DESC_RE_ALT, html)

    m = CANONICAL_RE.search(html)
    canonical = m.group(1).strip() if m else None

    if not title or not description:
        return f"skipped (title={bool(title)}, desc={bool(description)})"

    if not canonical:
        fn = os.path.basename(filepath)
        canonical = f"{SITE_URL}/" if fn == "index.html" else f"{SITE_URL}/{fn.replace('.html', '')}"
    else:
        # Clean canonical URL
        canonical = canonical.replace('.html', '')

    og_block = make_og_block(canonical, title, description)

    m = JSON_LD_RE.search(html)
    if m:
        line_start = html.rfind("\n", 0, m.start()) + 1
        new_html = html[:line_start] + og_block + "\n" + html[line_start:]
    else:
        idx = html.lower().find("</head>")
        if idx == -1:
            return "failed: no </head> or JSON-LD found"
        line_start = html.rfind("\n", 0, idx) + 1
        new_html = html[:line_start] + og_block + html[line_start:]

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_html)

    return "updated"
