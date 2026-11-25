#!/usr/bin/env python3
"""
Put the "Ask a question" box on Informer pages, and take it off pages no longer listed.

The box is one closed line, "Have a question this page does not answer? Ask it here". A reader
opens it to get the form. It posts to /api/question (netlify/functions/question.mjs), which
saves the question and emails it to the owner. Answers go on the page itself, in its FAQ or
status copy, so every reader sees them. After a reader sends a question, the box shows one
Center case-review link for a question about the reader's own situation. That link is the box's
only CTA. It carries the page's own utm_campaign and the utm_content slot <prefix>_ask_cta.

PAGES is the list of pages that carry the box now. It is the whole control: add a line and run
to put the box on a page, delete a line and run to take it off. Every page here must also be on
PAGES in question.mjs, which lists every page allowed to send a question; the script refuses to
run when one is missing there.

First batch, 11/25/26: four pages with 75+ GA4 sessions in 28 days and no open test window.

Held, with the reason and the day each can be added (all are already on the function's list):
  roundup-lawsuit-updates                    title test open until 12/4; rebuild due 12/5
  ozempic-lawsuit-updates                    title test open until 11/27
  depo-provera-lawsuit-updates               test open until 11/27; sign-up deadline 11/30, and the
                                             page gets new copy after it
  hair-relaxer-lawsuit-updates               test open until 11/27; rebuild due 11/28
  pfas-water-contamination-lawsuit-update    hero strip moved up 11/25 to bring leads back; let that read
  raine-v-openai-lawsuit, openai-lawsuits,
  jccp-5431-chatgpt-product-liability-cases  AI pages: decide separately (JCCP test open until 11/27)

How the box is measured: network-ops scripts/edit_ledger.py files the box as a test edit on each
page ("cta": it adds a case-review link), so a page holds no other title, description, link or
form test for the 14 days after its box goes on, and wire.v_edit_scores scores case-review clicks
per visit before and after. Put the box only on a page with no test window open. Held pages that
stay without the box (Roundup, PFAS) are the comparison.

Each entry names the h2 id the box goes in front of:
  update pages   before "recent-developments", right after the status section
  case pages     before the FAQ heading
  hernia-mesh    before "what-is-hernia-mesh", right after the update section

The box sits between <!-- LI-ASK:BEGIN --> and <!-- LI-ASK:END -->. A later run replaces it in
place, wherever it now sits, so a hand move survives. The box is navigation, so it never moves a
page's dateModified or visible stamp; the workflow commits with [skip lastmod]. A page is written
only when its box changed.

    python3 add_question_box.py            # write the pages that changed
    python3 add_question_box.py --dry-run  # list what would change, write nothing
    python3 add_question_box.py --list     # print the page files that carry the box
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ACTION = "/api/question"
PRIVACY = "/privacy-policy"
BEGIN, END = "<!-- LI-ASK:BEGIN -->", "<!-- LI-ASK:END -->"
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
PLACED = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n\n", re.S)

# (page slug, h2 id the box goes in front of, utm_content prefix the page already uses)
PAGES = [
    ("afff-lawsuit-updates", "recent-developments", "afffupd"),
    ("talcum-powder-lawsuit-updates", "recent-developments", "talcupd"),
    ("paraquat-lawsuit-updates", "recent-developments", "pqupd"),
    ("hernia-mesh-lawsuit", "what-is-hernia-mesh", "hml"),
]
# Held. Move a line up into PAGES to add the page (see the dates in the header).
#   ("roundup-lawsuit-updates", "recent-developments", "rupd"),
#   ("ozempic-lawsuit-updates", "recent-developments", "ozupd"),
#   ("depo-provera-lawsuit-updates", "recent-developments", "depoupd"),
#   ("hair-relaxer-lawsuit-updates", "recent-developments", "hrupd"),
#   ("pfas-water-contamination-lawsuit-update", "recent-developments", "pfasupd"),
#   ("raine-v-openai-lawsuit", "faq", "raine"),
#   ("openai-lawsuits", "recent-developments", "openai"),
#   ("jccp-5431-chatgpt-product-liability-cases", "faq", "jccp"),

esc = lambda s: html.escape(s, quote=True)  # noqa: E731

CENTER = re.compile(
    r'href="https://lawsuit\.center/([a-z0-9-]+)\?[^"]*?utm_campaign=([a-z0-9_]+)', re.I)


def function_pages() -> set:
    path = os.path.join(ROOT, "netlify", "functions", "question.mjs")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    block = re.search(r"export const PAGES = \[(.*?)\n\];", src, re.S)
    return set(re.findall(r'"([a-z0-9-]+)"', block.group(1))) if block else set()


CSS = """<style id="li-ask-css">
.li-ask{margin:40px 0;background:var(--bg-alt);border:1px solid var(--border);border-left:3px solid var(--amber);border-radius:var(--radius);font-family:var(--sans);text-align:left}
.li-ask>details>summary{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:44px;padding:18px 24px;cursor:pointer;list-style:none}
.li-ask>details>summary::-webkit-details-marker{display:none}
.li-ask>details>summary::after{content:"";width:9px;height:9px;flex-shrink:0;border-right:2px solid var(--link);border-bottom:2px solid var(--link);transform:translateY(-3px) rotate(45deg);transition:transform .2s var(--ease)}
.li-ask>details[open]>summary::after{transform:translateY(2px) rotate(-135deg)}
.li-ask>details>summary:focus-visible{outline:2px solid var(--ink-strong);outline-offset:2px}
.li-ask .li-ask-title{display:block;font-family:var(--display);font-weight:600;font-size:1.2rem;line-height:1.3;letter-spacing:-.01em;color:var(--ink-strong)}
.li-ask .li-ask-open{display:block;margin-top:4px;font-size:14px;font-weight:600;color:var(--link)}
.li-ask>details[open] .li-ask-open{display:none}
.li-ask form{padding:0 24px 22px}
.li-ask .li-ask-text{font-family:var(--serif);font-size:1.02rem;line-height:1.6;color:var(--ink);margin:0 0 14px}
.li-ask label{display:block;font-size:14px;font-weight:600;color:var(--ink-strong);margin:12px 0 6px}
.li-ask label span{font-weight:400;color:var(--ink-muted)}
.li-ask .li-ask-hint{font-size:13px;line-height:1.5;color:var(--ink-muted);margin:-2px 0 6px}
.li-ask textarea,.li-ask input[type=email]{display:block;width:100%;min-height:44px;padding:11px 14px;border:1px solid var(--border-strong);border-radius:var(--radius);background:var(--surface);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.5}
.li-ask textarea{min-height:96px;resize:vertical}
.li-ask textarea:focus,.li-ask input[type=email]:focus{outline:none;border-color:var(--link)}
.li-ask button{margin-top:14px;min-height:44px;padding:11px 22px;border:0;border-radius:999px;background:var(--link);color:var(--bg);font-family:var(--sans);font-size:14.5px;font-weight:600;cursor:pointer}
.li-ask button:hover{background:var(--link-hover)}
.li-ask button:disabled{opacity:.6;cursor:default}
.li-ask .li-ask-status{margin:10px 0 0;font-size:14.5px;line-height:1.5;color:var(--ink-strong)}
.li-ask .li-ask-status:empty{display:none}
.li-ask .li-ask-note{margin:12px 0 0;font-size:12.5px;line-height:1.5;color:var(--ink-muted)}
.li-ask form.is-done .li-ask-fields{display:none}
.li-ask form.is-done .li-ask-status{font-family:var(--serif);font-size:1rem;margin:0 0 12px}
.li-ask .li-ask-done p{font-family:var(--serif);font-size:1rem;line-height:1.6;color:var(--ink);margin:0 0 12px}
.li-ask .li-ask-done .li-ask-note{font-family:var(--sans);font-size:12.5px;color:var(--ink-muted)}
.li-ask .li-ask-done .btn{border-bottom:0}
@media (max-width:600px){.li-ask>details>summary{padding:16px 18px}.li-ask form{padding:0 18px 20px}.li-ask button{width:100%}}
@media (prefers-reduced-motion:reduce){.li-ask>details>summary::after{transition:none}}
</style>"""

# Same bot check as the signup box (rules in the header of netlify/functions/newsletter.mjs and
# question.mjs): the first touch inside the form asks GET /api/question for a token, the post
# carries it back with a count of real clicks and key presses, and a post sooner than 2.5 seconds
# after the token waits out the difference. When there is no token, or the function answers
# "verify", the box falls back to a plain form POST, and the function answers with its own
# one-button page. Without JavaScript the box still opens (it is a <details>) and posts plainly.
# GA4: question_open when a reader opens the box, question_start on the first real touch inside
# the form, question_sent on success. None carries the question's text.
JS = """<script>
(function(){
  if (window.__liAsk) return; window.__liAsk = true;
  function boot(){
    var forms = document.querySelectorAll('form.li-ask-form');
    Array.prototype.forEach.call(forms, function(f){
      var st = f.querySelector('.li-ask-status');
      var btn = f.querySelector('button[type="submit"]');
      var done = f.querySelector('.li-ask-done');
      var fold = f.closest ? f.closest('details') : null;
      var page = f.getAttribute('data-page') || '';
      var g = '', gAt = 0, asked = false, real = 0, started = false, opened = false;
      function ga(name, extra){
        if (typeof window.gtag !== 'function') return;
        var p = {page: page}; for (var k in (extra || {})) p[k] = extra[k];
        window.gtag('event', name, p);
      }
      if (fold) fold.addEventListener('toggle', function(){
        if (fold.open && !opened) { opened = true; ga('question_open'); }
      });
      function ask(){
        if (asked || !window.fetch) return;
        asked = true;
        fetch(f.getAttribute('action'), {headers: {'accept': 'application/json'}})
          .then(function(r){ return r.json(); })
          .then(function(j){ g = (j && j.g) || ''; gAt = Date.now(); })
          .catch(function(){ gAt = -1; });
      }
      ['pointerdown', 'touchstart', 'keydown', 'click'].forEach(function(type){
        f.addEventListener(type, function(e){
          if (!e.isTrusted) return;
          real++; ask();
          if (!started) { started = true; ga('question_start'); }
        }, true);
      });
      f.addEventListener('focusin', ask);
      function plain(){ HTMLFormElement.prototype.submit.call(f); }
      function show(){
        var box = (f.closest && f.closest('.li-ask')) || f;
        var r = box.getBoundingClientRect();
        var vh = window.innerHeight || document.documentElement.clientHeight;
        if (r.top >= 0 && r.bottom <= vh) return;
        var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        try { box.scrollIntoView({block: 'center', behavior: calm ? 'auto' : 'smooth'}); }
        catch (err) { box.scrollIntoView(); }
      }
      var MSG = {
        email: 'That email address did not look right. Check it, or leave it empty.',
        short: 'Add a little more to your question, then send it again.',
        long: 'That question is too long to send. Cut it to 1,500 characters or fewer, then send it again.',
        links: 'Take the web links out of your question, then send it again.'
      };
      f.addEventListener('submit', function(e){
        if (!window.fetch || !window.JSON) return;
        e.preventDefault();
        var q = f.querySelector('textarea[name="question"]').value.trim();
        var email = f.querySelector('input[name="email"]').value.trim();
        if (q.length < 10) { st.textContent = MSG.short; return; }
        btn.disabled = true; st.textContent = 'Sending';
        ask();
        var tries = 0;
        function post(){
          fetch(f.getAttribute('action'), {
            method: 'POST',
            headers: {'content-type': 'application/json', 'accept': 'application/json'},
            body: JSON.stringify({question: q, email: email, page: page,
                                  'bot-field': f.querySelector('input[name="bot-field"]').value,
                                  g: g, ev: real, wd: navigator.webdriver === true})
          }).then(function(r){
            return r.json().then(function(j){ return {ok: r.ok, j: j}; }, function(){ return {ok: false, j: {}}; });
          }).then(function(x){
            if (x.ok) {
              f.classList.add('is-done');
              st.textContent = 'Your question reached us. When we answer it, the answer goes on this page.';
              if (done) done.hidden = false;
              show();
              ga('question_sent', {with_email: email ? 'yes' : 'no'});
            } else if (x.j.error === 'verify') {
              plain();
            } else {
              btn.disabled = false;
              st.textContent = MSG[x.j.error] || 'Your question did not go through. Try again in a minute.';
            }
          }).catch(function(){
            btn.disabled = false;
            st.textContent = 'Your question did not go through. Try again in a minute.';
          });
        }
        (function go(){
          if (!gAt && tries++ < 25) { setTimeout(go, 200); return; }
          if (!g) { plain(); return; }
          var wait = 2600 - (Date.now() - gAt);
          if (wait > 0) { setTimeout(go, wait); return; }
          post();
        })();
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
</script>"""


def center_link(text: str, prefix: str) -> str:
    m = CENTER.search(text)
    if not m:
        return ""
    path, campaign = m.group(1), m.group(2)
    return (f"https://lawsuit.center/{path}?utm_source=lawsuitinformer&amp;utm_medium=referral"
            f"&amp;utm_campaign={campaign}&amp;utm_content={prefix}_ask_cta")


def box(slug: str, href: str) -> str:
    return f"""{BEGIN}
{CSS}
<aside class="li-ask" id="ask-a-question" aria-label="Ask a question about this page">
  <details>
    <summary><span><span class="li-ask-title">Have a question this page does not answer?</span><span class="li-ask-open">Ask it here</span></span></summary>
    <form class="li-ask-form" method="post" action="{ACTION}" data-page="{esc(slug)}">
      <div class="li-ask-fields">
        <p class="li-ask-text">We read every question. When we answer one, the answer goes on this page, where every reader can see it. Please leave out names, medical records and other private details.</p>
        <input type="hidden" name="page" value="{esc(slug)}">
        <p hidden><label>Leave this empty: <input name="bot-field" tabindex="-1" autocomplete="off"></label></p>
        <label for="li-ask-q">Your question</label>
        <textarea id="li-ask-q" name="question" rows="3" minlength="10" maxlength="1500" required></textarea>
        <label for="li-ask-email">Email <span>(optional)</span></label>
        <p class="li-ask-hint" id="li-ask-email-hint">Leave your email if you want a note when this page answers your question.</p>
        <input type="email" id="li-ask-email" name="email" autocomplete="email" aria-describedby="li-ask-email-hint">
        <button type="submit">Send my question</button>
        <p class="li-ask-note">Answers on this page are general information for every reader. A question about your own situation needs a lawyer to review the facts. <a href="{PRIVACY}">Privacy policy</a></p>
      </div>
      <p class="li-ask-status" role="status" aria-live="polite"></p>
      <div class="li-ask-done" hidden>
        <p>Is your question about your own situation? A lawyer has to look at the facts before anyone can answer it. Filing deadlines keep running while a question waits for an answer.</p>
        <a class="btn btn-primary" href="{href}" rel="noopener">Request a free case review</a>
        <p class="li-ask-note cta-note">Free and no obligation. Submitting a review request does not create an attorney-client relationship.</p>
      </div>
    </form>
  </details>
</aside>
{JS}
{END}"""


def place(text: str, block: str, anchor: str) -> tuple:
    if BEGIN in text:
        return BLOCK.sub(lambda _: block, text, count=1), "replaced"
    m = re.search(r'<h2\b[^>]*\bid="' + re.escape(anchor) + r'"', text)
    if not m:
        return text, ""
    at = text.rfind("\n", 0, m.start()) + 1  # start of the heading's line, so indentation stays
    return text[:at] + block + "\n\n" + text[at:], f"before #{anchor}"


def remove(text: str) -> str:
    """The page as it was before the box went on."""
    new = PLACED.sub("", text, count=1)
    return new if new != text else BLOCK.sub("", text, count=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)

    if args.list:
        print(" ".join(slug + ".html" for slug, _, _ in PAGES))
        return 0

    allowed = function_pages()
    missing = sorted(slug for slug, _, _ in PAGES if slug not in allowed)
    if missing:
        print("::error::these pages are in PAGES here and missing from PAGES in netlify/functions/question.mjs, "
              "so the function would drop their questions: " + ", ".join(missing))
        return 1

    changed, problems = [], []
    listed = {slug + ".html" for slug, _, _ in PAGES}
    for slug, anchor, prefix in PAGES:
        path = slug + ".html"
        if not os.path.exists(path):
            problems.append(f"{path}: file not found")
            continue
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
        href = center_link(old, prefix)
        if not href:
            problems.append(f"{path}: no lawsuit.center link to copy the case-review path and campaign from")
            continue
        new, how = place(old, box(slug, href), anchor)
        if not how:
            problems.append(f'{path}: no <h2 id="{anchor}"> to put the box in front of')
            continue
        if new != old:
            changed.append((path, how))
            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)

    # A page that carries the box and is no longer listed loses it.
    for path in sorted(glob.glob("*.html")):
        if path in listed:
            continue
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
        if BEGIN not in old:
            continue
        changed.append((path, "removed (not in PAGES)"))
        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(remove(old))

    verb = "would change" if args.dry_run else "changed"
    print(f"{verb} {len(changed)} file(s)")
    for path, how in changed:
        print(f"  {path}: {how}")
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
