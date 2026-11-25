// Reader questions from the "Ask a question" box (add_question_box.py) on the busiest Informer
// pages. A question is saved to the Netlify Blobs store "questions" and emailed to the owner.
// Nothing is sent back to the reader by email except one note, later and by hand, when the page
// answers the question and the reader left an address.
//
// GET  /api/question                 hands the box its bot-check token (same token as the signup box)
// POST /api/question                 question, page, optional email -> saved + owner email
//                                    JSON in, JSON out from the box; a plain form POST (no
//                                    JavaScript) gets a small HTML page instead
// GET  /api/question/export          X-Export-Key -> every saved question, newest first
//                                    (?since=YYYY-MM-DD limits it), for a network-ops read later
//
// Netlify variables, all already set for the newsletter:
//   NEWSLETTER_SECRET   signs the bot-check token (gateToken in newsletter.mjs)
//   SES_ACCESS_KEY_ID, SES_SECRET_ACCESS_KEY, SES_REGION, MAIL_FROM   send the owner email
//   NOTIFY_TO           where the owner email goes; QUESTIONS_TO, when set, takes its place
//   EXPORT_KEY          guards /api/question/export
//
// Bot check: the same rules as the signup box. The JSON post must carry a token from GET that is
// at least 2.5 seconds and at most 2 hours old, plus a count of real clicks and key presses. A
// browser that reports automation gets "ok" and nothing is kept. A plain form POST without a good
// token gets a page with one button, "Send my question", carrying its own token. Every question
// the check turns back logs one line with the reason and the page, never the text.
//
// Limits on top of the bot check:
//   - A question must be 10 to 1500 characters and carry at most two links. The reader is told
//     which rule the question broke, so a real reader can fix it and send again.
//   - The page must be on PAGES below. A post naming any other page is dropped and logged. Without
//     this, a script could name a new page on every post and walk around the per-page limit.
//   - At most 20 questions an hour from one page, 40 an hour from all pages together, and 150 a
//     day. Past a limit the reader still sees "ok", nothing is saved, and one line is logged.
//     Each saved question sends one owner email, so these limits also cap that mail.

import { getStore } from "@netlify/blobs";
import { createHmac, timingSafeEqual, randomBytes } from "node:crypto";
import { gateToken, signSes } from "./newsletter.mjs";

export const config = { path: ["/api/question", "/api/question/export"] };

// Every page that may carry the box. add_question_box.py PAGES (the pages that carry it now) must
// be a subset of this list; the script refuses to run otherwise. Adding a page here changes
// nothing a reader sees until the script lists it too.
export const PAGES = [
  "afff-lawsuit-updates",
  "talcum-powder-lawsuit-updates",
  "roundup-lawsuit-updates",
  "pfas-water-contamination-lawsuit-update",
  "paraquat-lawsuit-updates",
  "ozempic-lawsuit-updates",
  "hernia-mesh-lawsuit",
  "depo-provera-lawsuit-updates",
  "hair-relaxer-lawsuit-updates",
  "raine-v-openai-lawsuit",
  "openai-lawsuits",
  "jccp-5431-chatgpt-product-liability-cases",
];
const PAGE_SET = new Set(PAGES);

const MIN_LEN = 10;
const MAX_LEN = 1500;
const MAX_LINKS = 2;
const PAGE_HOUR_MAX = 20;
const ALL_HOUR_MAX = 40;
const DAY_MAX = 150;
const GATE_MIN_MS = 2500;
const GATE_MAX_MS = 2 * 3600 * 1000;

const site = () => (process.env.SITE_URL || process.env.URL || "https://lawsuitinformer.com").replace(/\/$/, "");
const store = () => getStore({ name: "questions", consistency: "strong" });
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------------------------------------------------------------- bot check

export function gateState(g, now = Date.now()) {
  const m = /^(\d{13})\.([0-9a-f]{32})$/.exec(String(g || ""));
  if (!m) return g ? "bad" : "none";
  const want = (gateToken(Number(m[1])).split(".")[1] || "");
  if (!want || !timingSafeEqual(Buffer.from(m[2]), Buffer.from(want))) return "bad";
  const age = now - Number(m[1]);
  if (age < GATE_MIN_MS) return "fast";
  if (age > GATE_MAX_MS) return "old";
  return "ok";
}

function sameKey(got, want) {
  if (!want) return false;
  const a = createHmac("sha256", "k").update(String(got)).digest();
  const b = createHmac("sha256", "k").update(String(want)).digest();
  return timingSafeEqual(a, b);
}

// ---------------------------------------------------------------- input

// { q } when the question can be saved, or { error: "short" | "long" | "links" }.
export function cleanQuestion(v) {
  const q = String(v || "").replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  if (q.length < MIN_LEN) return { error: "short" };
  if (q.length > MAX_LEN) return { error: "long" };
  if ((q.match(/https?:\/\/|www\./gi) || []).length > MAX_LINKS) return { error: "links" };
  return { q };
}
export function cleanEmail(v) {
  const e = String(v || "").trim();
  if (!e) return "";
  if (e.length < 6 || e.length > 254) return "";
  return /^[^\s@<>()",;:]+@[^\s@<>()",;:]+\.[a-z]{2,}$/i.test(e) ? e : "";
}
// The page slug when it is on PAGES, otherwise "".
export const cleanPage = (v) => {
  const p = String(v || "").trim().toLowerCase();
  return PAGE_SET.has(p) ? p : "";
};

async function readBody(req) {
  const type = req.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const j = await req.json().catch(() => ({}));
    return { get: (k) => j[k] };
  }
  const f = await req.formData().catch(() => new FormData());
  return { get: (k) => f.get(k) };
}
const wantsJson = (req) =>
  (req.headers.get("accept") || "").includes("application/json") ||
  (req.headers.get("content-type") || "").includes("application/json");

function json(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function page(status, title, inner) {
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>${esc(title)} | Lawsuit Informer</title>
<style>
body{margin:0;background:#fafaf7;color:#1a1a1a;font:18px/1.65 Georgia,"Times New Roman",serif}
main{max-width:620px;margin:0 auto;padding:48px 22px}
.brand{display:block;font:600 22px/1.2 "Times New Roman",serif;color:#1a1a1a;text-decoration:none;padding-bottom:14px;border-bottom:3px solid #d4a24e;margin-bottom:28px}
h1{font:600 28px/1.2 "Times New Roman",serif;margin:0 0 14px}
a{color:#b04a2f}
button{min-height:44px;padding:11px 22px;border:0;border-radius:999px;background:#b04a2f;color:#fafaf7;font:600 15px/1 Arial,sans-serif;cursor:pointer}
.small{font-size:14px;color:#5a5750}
</style></head><body><main><a class="brand" href="${site()}/">Lawsuit Informer</a>
${inner}
</main></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } }
  );
}

// ---------------------------------------------------------------- owner email

async function sendMail(to, subject, html, text) {
  const { SES_ACCESS_KEY_ID: keyId, SES_SECRET_ACCESS_KEY: secret, MAIL_FROM: from } = process.env;
  const region = process.env.SES_REGION || "us-east-1";
  if (!keyId || !secret || !from) {
    console.log("question: SES not configured, owner email not sent");
    return false;
  }
  const body = JSON.stringify({
    FromEmailAddress: from,
    Destination: { ToAddresses: [to] },
    Content: {
      Simple: {
        Subject: { Data: subject, Charset: "UTF-8" },
        Body: { Html: { Data: html, Charset: "UTF-8" }, Text: { Data: text, Charset: "UTF-8" } },
      },
    },
  });
  const { url, headers } = signSes({ body, region, keyId, secret });
  try {
    const res = await fetch(url, { method: "POST", headers, body });
    if (!res.ok) {
      console.log(`question: SES ${res.status} ${(await res.text()).slice(0, 300)}`);
      return false;
    }
    return true;
  } catch (e) {
    console.log(`question: SES unreachable: ${e}`);
    return false;
  }
}

export function ownerMail(rec) {
  const where = `${site()}/${rec.page}`;
  const subject = `Informer question: ${rec.page}`;
  const text = `A reader asked a question on ${where}

${rec.question}

Email: ${rec.email || "none left"}
Time: ${rec.at}
Saved as: ${rec.key}`;
  const html = `<!doctype html><html><body style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#1a1a1a">
<p style="margin:0 0 10px">A reader asked a question on <a href="${esc(where)}">${esc(where)}</a></p>
<blockquote style="margin:0 0 14px;padding:10px 14px;border-left:3px solid #d4a24e;background:#f4f3ee;white-space:pre-wrap">${esc(rec.question)}</blockquote>
<p style="margin:0">Email: ${esc(rec.email || "none left")}<br>Time: ${esc(rec.at)}<br>Saved as: ${esc(rec.key)}</p>
</body></html>`;
  return { subject, text, html };
}

// ---------------------------------------------------------------- routes

function thanksPage(pageSlug) {
  return page(
    200,
    "Question received",
    `<h1>Your question reached us</h1>
<p>We read every question. When we answer one, the answer goes on the page, so every reader can see it.</p>
<p>A question about your own situation needs a lawyer to look at the facts.</p>
<p>Filing deadlines keep running while a question waits for an answer.</p>
<p><a href="${site()}/${esc(pageSlug)}">${pageSlug ? "Back to the page" : "Back to Lawsuit Informer"}</a></p>`
  );
}

function verifyPage(q, pageSlug, email, tooFast) {
  return page(
    200,
    "Send your question",
    `<h1>One more step</h1>
<p>Press the button to send your question.</p>
${tooFast ? "<p>That was quick. Press the button once more.</p>\n" : ""}<form method="post" action="/api/question">
<input type="hidden" name="question" value="${esc(q)}">
<input type="hidden" name="page" value="${esc(pageSlug)}">
<input type="hidden" name="email" value="${esc(email)}">
<input type="hidden" name="g" value="${esc(gateToken())}">
<p hidden><label>Leave this empty: <input name="bot-field" tabindex="-1" autocomplete="off"></label></p>
<button type="submit">Send my question</button>
</form>
<p class="small" style="margin-top:22px">This extra step keeps automated messages out.</p>
<p class="small"><a href="${site()}/${esc(pageSlug)}">Back to the page</a></p>`
  );
}

const BAD = {
  short: ["Add a little more", "Add a little more to your question", "Go back and write a full question, then send it again."],
  long: ["Shorten your question", "That question is too long to send", "Go back and cut it to 1,500 characters or fewer, then send it again."],
  links: ["Take out the links", "Take the links out of your question", "Go back, remove the web links, then send it again."],
};

// true when this question fits under every limit; counts it when it does.
async function underLimits(s, pageSlug, now) {
  const iso = new Date(now).toISOString();
  const keys = [
    [`rate/h/${iso.slice(0, 13)}/${pageSlug}`, PAGE_HOUR_MAX, "hourly limit for the page"],
    [`rate/h/${iso.slice(0, 13)}/all`, ALL_HOUR_MAX, "hourly limit for all pages"],
    [`rate/d/${iso.slice(0, 10)}`, DAY_MAX, "daily limit"],
  ];
  const counts = [];
  for (const [key, max, what] of keys) {
    const n = Number(await s.get(key)) || 0;
    if (n >= max) {
      console.log(`question: ${what} reached, question from ${pageSlug} not saved`);
      return false;
    }
    counts.push(n);
  }
  for (let i = 0; i < keys.length; i++) await s.set(keys[i][0], String(counts[i] + 1));
  return true;
}

async function ask(req) {
  const asJson = wantsJson(req);
  const f = await readBody(req);
  const pageSlug = cleanPage(f.get("page"));
  const ok = () => (asJson ? json(200, { ok: true }) : thanksPage(pageSlug));

  if (f.get("bot-field")) return ok();
  if (!pageSlug) {
    console.log(`question: dropped, page not on the list (${String(f.get("page") || "").replace(/[^a-z0-9-]/gi, "").slice(0, 60) || "none"})`);
    return ok();
  }
  const { q: question, error } = cleanQuestion(f.get("question"));
  const rawEmail = String(f.get("email") || "").trim();
  const email = cleanEmail(rawEmail);
  if (error) {
    const [title, head, body] = BAD[error];
    return asJson ? json(400, { ok: false, error }) : page(400, title, `<h1>${head}</h1><p>${body}</p>`);
  }
  if (rawEmail && !email) {
    return asJson
      ? json(400, { ok: false, error: "email" })
      : page(400, "Check the address", `<h1>That email address did not look right</h1><p>Go back and check it, or leave it empty.</p>`);
  }

  const now = Date.now();
  const gate = gateState(f.get("g"), now);
  if (asJson) {
    if (String(f.get("wd")) === "true") {
      console.log(`question: bot check dropped a question (automated browser) on ${pageSlug}`);
      return ok();
    }
    const real = Number(f.get("ev")) || 0;
    if (gate !== "ok" || real < 1) {
      console.log(`question: bot check turned back a question (${gate !== "ok" ? `token ${gate}` : "no real click or key"}) on ${pageSlug}`);
      return json(400, { ok: false, error: "verify" });
    }
  } else if (gate !== "ok") {
    console.log(`question: bot check showed the one-button page (token ${gate}) on ${pageSlug}`);
    return verifyPage(question, pageSlug, email, gate === "fast");
  }

  const s = store();
  if (!(await underLimits(s, pageSlug, now))) return ok();

  const at = new Date(now).toISOString();
  const key = `q/${at}-${randomBytes(4).toString("hex")}`;
  const rec = { key, page: pageSlug, question, email, at, status: "new" };
  await s.setJSON(key, rec);

  const to = (process.env.QUESTIONS_TO || process.env.NOTIFY_TO || "").trim();
  if (to) {
    const m = ownerMail(rec);
    await sendMail(to, m.subject, m.html, m.text);
  } else {
    console.log("question: QUESTIONS_TO and NOTIFY_TO unset, owner email not sent");
  }
  return ok();
}

async function exportAll(req, url) {
  if (!sameKey(req.headers.get("x-export-key") || "", process.env.EXPORT_KEY || "")) {
    return json(401, { error: "key" });
  }
  const since = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get("since") || "") ? url.searchParams.get("since") : "";
  const s = store();
  const out = [];
  const { blobs } = await s.list({ prefix: "q/" });
  for (const b of blobs) {
    if (since && b.key.slice(2, 12) < since) continue;
    const rec = await s.get(b.key, { type: "json" });
    if (rec) out.push(rec);
  }
  out.sort((a, b) => (a.at < b.at ? 1 : -1));
  return json(200, { count: out.length, questions: out });
}

export default async function handler(req) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/$/, "");
  if (path === "/api/question/export") {
    if (req.method !== "GET") return json(405, { error: "method" });
    return exportAll(req, url);
  }
  if (req.method === "GET") return json(200, { g: gateToken() });
  if (req.method !== "POST") return json(405, { error: "method" });
  return ask(req);
}
