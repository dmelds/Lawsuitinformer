#!/usr/bin/env python3
"""
Put the weekly-email signup box on the homepage and on every update page.

The box posts to /api/subscribe (netlify/functions/newsletter.mjs). It works without JavaScript
as a plain form POST, and with JavaScript it posts in place and shows the result in the box.

  index.html             the full box: "Every case we track" plus one checkbox per update page.
                         It replaces the old Netlify-forms <section class="subscribe-box"> on the
                         first run, then lives between <!-- LI-SIGNUP-HOME:BEGIN --> and
                         <!-- LI-SIGNUP-HOME:END -->.
  current-mass-tort-cases.html
                         the status board: the full box with "Every case we track" already
                         checked, right after </main>. generate_status_board.py rewrites only
                         the board's <main>, so the box sits just outside it and survives every
                         board run. Between <!-- LI-SIGNUP-BOARD:BEGIN --> and END.
  each update page       a box with that page's case already checked and the other cases behind
                         "Follow other cases too". It goes at the end of the Recent developments
                         section (just before the <h2> that follows the dev-list), or before the
                         closing cta-box on a page with no dev-list, between
                         <!-- LI-SIGNUP:BEGIN --> and <!-- LI-SIGNUP:END -->.

The case list is the status board's PAGES (generate_status_board.py), so a page added to the
board gets a box and a checkbox on the next run. The newsletter function keeps its own TOPICS
list, because it validates what readers send; this script refuses to run when the two lists
disagree, so a reader can never tick a case the function would drop.

The box is navigation, so it never moves a page's dateModified or visible stamp; the workflow
commits it with [skip lastmod]. A page is written only when its box changed.

    python3 add_signup_boxes.py            # write the pages that changed
    python3 add_signup_boxes.py --dry-run  # list what would change, write nothing
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = "index.html"
ACTION = "/api/subscribe"
PRIVACY = "/privacy-policy"
BEGIN, END = "<!-- LI-SIGNUP:BEGIN -->", "<!-- LI-SIGNUP:END -->"
HBEGIN, HEND = "<!-- LI-SIGNUP-HOME:BEGIN -->", "<!-- LI-SIGNUP-HOME:END -->"
BOARD = "current-mass-tort-cases.html"
BBEGIN, BEND = "<!-- LI-SIGNUP-BOARD:BEGIN -->", "<!-- LI-SIGNUP-BOARD:END -->"

esc = lambda s: html.escape(s, quote=True)  # noqa: E731


def load_pages() -> list:
    spec = importlib.util.spec_from_file_location("board", os.path.join(ROOT, "generate_status_board.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [(slug, name) for slug, name, *_ in mod.PAGES]


def function_topics() -> set:
    path = os.path.join(ROOT, "netlify", "functions", "newsletter.mjs")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    block = re.search(r"export const TOPICS = \[(.*?)\n\];", src, re.S)
    return set(re.findall(r'\["([a-z0-9-]+)",', block.group(1))) if block else set()


CSS = """<style id="li-signup-css">
.li-signup{margin:40px 0;padding:24px;background:var(--bg-alt);border:1px solid var(--border);border-left:3px solid var(--amber);border-radius:var(--radius);font-family:var(--sans);text-align:left}
.li-signup .li-signup-eyebrow{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--link);margin:0 0 8px}
.li-signup .li-signup-title{font-family:var(--display);font-weight:600;font-size:1.4rem;line-height:1.25;letter-spacing:-.01em;color:var(--ink-strong);margin:0 0 8px;padding:0;border:0}
.li-signup .li-signup-text{font-family:var(--serif);font-size:1.02rem;line-height:1.6;color:var(--ink);margin:0 0 14px}
.li-signup .li-signup-topic{display:flex;align-items:center;gap:10px;min-height:44px;font-size:15px;line-height:1.3;color:var(--ink);cursor:pointer}
.li-signup input[type=checkbox]{width:20px;height:20px;margin:0;flex:none;accent-color:var(--link)}
.li-signup details{margin:0 0 8px}
.li-signup summary{display:flex;align-items:center;min-height:44px;cursor:pointer;font-size:14px;font-weight:500;color:var(--link)}
.li-signup .li-signup-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:18px;margin:0 0 6px}
.li-signup .li-signup-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}
.li-signup .li-signup-row input[type=email]{flex:1 1 240px;min-width:0;min-height:44px;padding:11px 16px;border:1px solid var(--border-strong);border-radius:999px;background:var(--surface);color:var(--ink);font-size:15px}
.li-signup .li-signup-row input[type=email]:focus{outline:none;border-color:var(--link)}
.li-signup .li-signup-row button{flex:0 0 auto;min-height:44px;padding:11px 22px;border:0;border-radius:999px;background:var(--link);color:var(--bg);font-family:var(--sans);font-size:14.5px;font-weight:600;cursor:pointer}
.li-signup .li-signup-row button:hover{background:var(--link-hover)}
.li-signup .li-signup-row button:disabled{opacity:.6;cursor:default}
.li-signup .li-signup-status{margin:10px 0 0;font-size:14.5px;line-height:1.5;color:var(--ink-strong)}
.li-signup .li-signup-status:empty{display:none}
.li-signup .li-signup-note{margin:10px 0 0;font-size:12.5px;line-height:1.5;color:var(--ink-muted)}
.li-signup form.is-done .li-signup-fields{display:none}
.li-signup form.is-done .li-signup-status{font-size:1rem;font-family:var(--serif);margin:0}
@media (max-width:600px){.li-signup{padding:20px 18px}.li-signup .li-signup-grid{grid-template-columns:1fr}.li-signup .li-signup-row button{width:100%}}
</style>"""

# Posts in place when fetch exists; otherwise the browser does a normal form POST and the
# function answers with its own "Check your email" page. "Every case we track" and the single
# cases are kept exclusive so a reader never sends both.
JS = """<script>
(function(){
  if (window.__liSignup) return; window.__liSignup = true;
  function boot(){
    var forms = document.querySelectorAll('form.li-signup-form');
    Array.prototype.forEach.call(forms, function(f){
      var all = f.querySelector('input[name="topic"][value="all"]');
      var st = f.querySelector('.li-signup-status');
      var btn = f.querySelector('button[type="submit"]');
      f.addEventListener('change', function(e){
        var t = e.target;
        if (t.name !== 'topic' || !t.checked) return;
        if (t === all) {
          Array.prototype.forEach.call(f.querySelectorAll('input[name="topic"]'), function(c){ if (c !== all) c.checked = false; });
        } else if (all) { all.checked = false; }
      });
      f.addEventListener('submit', function(e){
        if (!window.fetch || !window.JSON) return;
        e.preventDefault();
        var topics = Array.prototype.map.call(f.querySelectorAll('input[name="topic"]:checked'), function(c){ return c.value; });
        var email = f.querySelector('input[name="email"]').value.trim();
        if (!topics.length) { st.textContent = 'Pick at least one case to follow.'; return; }
        if (!email) { st.textContent = 'Enter your email address.'; return; }
        btn.disabled = true; st.textContent = 'Sending';
        fetch(f.getAttribute('action'), {
          method: 'POST',
          headers: {'content-type': 'application/json', 'accept': 'application/json'},
          body: JSON.stringify({email: email, topic: topics, source: f.getAttribute('data-source') || '',
                                'bot-field': f.querySelector('input[name="bot-field"]').value})
        }).then(function(r){
          return r.json().then(function(j){ return {ok: r.ok, j: j}; }, function(){ return {ok: false, j: {}}; });
        }).then(function(x){
          if (x.ok) {
            f.classList.add('is-done');
            st.textContent = 'Check your email. We sent you a link to confirm. Updates start after you confirm.';
            if (typeof window.gtag === 'function') {
              window.gtag('event', 'newsletter_signup', {topics: topics.join(','), source: f.getAttribute('data-source') || ''});
            }
          } else {
            btn.disabled = false;
            st.textContent = x.j.error === 'email' ? 'That email address did not look right. Check it and try again.'
              : x.j.error === 'topics' ? 'Pick at least one case to follow.'
              : 'The signup did not go through. Try again in a minute.';
          }
        }).catch(function(){
          btn.disabled = false;
          st.textContent = 'The signup did not go through. Try again in a minute.';
        });
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
</script>"""


def checkbox(slug: str, name: str, checked: bool = False) -> str:
    c = " checked" if checked else ""
    return (f'<label class="li-signup-topic"><input type="checkbox" name="topic" value="{esc(slug)}"{c}> '
            f'{esc(name)}</label>')


def form(source: str, first: str, rest: str, input_id: str) -> str:
    return f"""<form class="li-signup-form" method="post" action="{ACTION}" data-source="{esc(source)}">
    <div class="li-signup-fields">
      <input type="hidden" name="source" value="{esc(source)}">
      <p hidden><label>Leave this empty: <input name="bot-field" tabindex="-1" autocomplete="off"></label></p>
      {first}
      {rest}
      <div class="li-signup-row">
        <label for="{input_id}" class="sr-only">Email address</label>
        <input type="email" id="{input_id}" name="email" placeholder="Your email address" autocomplete="email" required>
        <button type="submit">Send me updates</button>
      </div>
      <p class="li-signup-note">We email you a link to confirm first. Nothing else arrives until you confirm. Each email has a link to change cases or unsubscribe. <a href="{PRIVACY}">Privacy policy</a></p>
    </div>
    <p class="li-signup-status" role="status" aria-live="polite"></p>
  </form>"""


def page_box(slug: str, name: str, pages: list) -> str:
    others = "\n        ".join(checkbox(s, n) for s, n in sorted(pages, key=lambda p: p[1].lower()) if s != slug)
    rest = f"""<details>
        <summary>Follow other cases too</summary>
        <div class="li-signup-grid">
        {checkbox("all", "Every case we track")}
        {others}
        </div>
      </details>"""
    return f"""{BEGIN}
{CSS}
<aside class="li-signup" aria-label="Weekly email updates for {esc(name)}">
  <p class="li-signup-eyebrow">Weekly email</p>
  <p class="li-signup-title">Follow {esc(name)} by email</p>
  <p class="li-signup-text">Once a week, we email you the new developments we add to this page. You can add other cases or stop the emails at any time.</p>
  {form(slug, checkbox(slug, name, checked=True), rest, "li-signup-email")}
</aside>
{JS}
{END}"""


def home_box(pages: list) -> str:
    grid = "\n        ".join(checkbox(s, n) for s, n in sorted(pages, key=lambda p: p[1].lower()))
    rest = f"""<div class="li-signup-grid">
        {grid}
      </div>"""
    return f"""{HBEGIN}
{CSS}
    <section class="section">
      <div class="container narrow">
        <div class="li-signup" id="weekly-updates">
          <p class="li-signup-eyebrow">Weekly email</p>
          <h2 class="li-signup-title">Get weekly case updates</h2>
          <p class="li-signup-text">Pick the cases you want to follow. Once a week, we email you the new developments we add to those case pages.</p>
          {form("home", checkbox("all", "Every case we track"), rest, "li-signup-email-home")}
        </div>
      </div>
    </section>
{JS}
{HEND}"""


def place_page(text: str, block: str) -> tuple:
    """(new_text, how) for an update page."""
    if BEGIN in text:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, text, count=1, flags=re.S)
        return new, "replaced"
    m = re.search(r'<ul[^>]*class="[^"]*\bdev-list\b', text)
    if m:
        at = text.find("<h2", m.end())
        if at != -1:
            return text[:at] + block + "\n\n  " + text[at:], "after developments"
    at = text.find('<div class="cta-box">')
    if at != -1:
        return text[:at] + block + "\n\n  " + text[at:], "before cta-box"
    return text, ""


def board_box(pages: list) -> str:
    grid = "\n        ".join(checkbox(s, n) for s, n in sorted(pages, key=lambda p: p[1].lower()))
    rest = f"""<details>
        <summary>Pick cases instead</summary>
        <div class="li-signup-grid">
        {grid}
        </div>
      </details>"""
    return f"""{BBEGIN}
{CSS}
<div class="content-page li-signup-board" style="margin-top:0;padding-top:0">
<aside class="li-signup" id="weekly-updates" aria-label="Weekly email updates">
  <p class="li-signup-eyebrow">Weekly email</p>
  <p class="li-signup-title">Get these updates by email</p>
  <p class="li-signup-text">Once a week, we email you the new developments we add to the case pages on this board. Follow every case, or pick the ones you care about.</p>
  {form("current-mass-tort-cases", checkbox("all", "Every case we track", checked=True), rest, "li-signup-email-board")}
</aside>
</div>
{JS}
{BEND}"""


def place_board(text: str, block: str) -> tuple:
    if BBEGIN in text:
        new = re.sub(re.escape(BBEGIN) + r".*?" + re.escape(BEND), lambda _: block, text, count=1, flags=re.S)
        return new, "replaced"
    at = text.find("</main>")
    if at != -1:
        at += len("</main>")
        return text[:at] + "\n" + block + text[at:], "after main"
    return text, ""


def place_home(text: str, block: str) -> tuple:
    if HBEGIN in text:
        new = re.sub(re.escape(HBEGIN) + r".*?" + re.escape(HEND), lambda _: block, text, count=1, flags=re.S)
        return new, "replaced"
    m = re.search(r'[ \t]*<section class="subscribe-box">.*?</section>', text, re.S)
    if m:
        return text[: m.start()] + block + text[m.end():], "replaced old form"
    return text, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)

    pages = load_pages()
    board = {s for s, _ in pages}
    fn = function_topics()
    if board != fn:
        print("::error::the status board's PAGES and TOPICS in netlify/functions/newsletter.mjs disagree")
        for s in sorted(board - fn):
            print(f"  on the board, missing from the function: {s}")
        for s in sorted(fn - board):
            print(f"  in the function, not on the board: {s}")
        return 1

    changed, missing = [], []
    targets = [(HOME, place_home, home_box(pages)), (BOARD, place_board, board_box(pages))] + [
        (slug + ".html", place_page, page_box(slug, name, pages)) for slug, name in pages]
    for path, place, block in targets:
        if not os.path.exists(path):
            missing.append(path)
            continue
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
        new, how = place(old, block)
        if not how:
            missing.append(path)
            continue
        if new != old:
            changed.append((path, how))
            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)

    verb = "would change" if args.dry_run else "changed"
    print(f"{verb} {len(changed)} file(s)")
    for path, how in changed:
        print(f"  {path}: {how}")
    for path in missing:
        print(f"::warning::{path}: no place for the box (missing file, no dev-list, no cta-box)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
