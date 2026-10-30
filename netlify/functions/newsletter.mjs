// Lawsuit Informer weekly email: the subscriber side.
//
// One function, five routes. The list lives in this site's own Blobs store ("newsletter"), one
// record per address under sub/<id>, where <id> is the first 32 hex of the SHA-256 of the
// lowercased address. The weekly send itself runs in network-ops and reads the list through
// /api/newsletter/export.
//
// POST /api/subscribe            the signup boxes post here (form or fetch). Always answers the
//                                same "check your email" so the form never tells a stranger
//                                whether an address is on the list.
// GET  /email/confirm?t=         page with a Confirm button; POST to the same URL activates.
//                                A button rather than a bare link, because mail scanners open
//                                every GET link in a message and would confirm addresses the
//                                owner never asked for.
// GET  /email/preferences?t=     topic checkboxes; POST saves. Saving with no topic unsubscribes.
// GET  /email/unsubscribe?t=     page with an Unsubscribe button; POST unsubscribes. The weekly
//                                email's List-Unsubscribe-Post header posts here too (RFC 8058).
// GET  /api/newsletter/export    X-Export-Key -> every active subscriber with their topics and
//                                personal links. Read only. With EXPORT_KEY unset it refuses all.
//
// Every personal link carries t = <id>.<mac>, the mac being the first 32 hex of an HMAC-SHA256
// of the id under NEWSLETTER_SECRET. Nothing about the token is stored; changing the secret
// voids every link already sent.
//
// Confirmation mail goes out through Amazon SES (API v2), signed here with SigV4 so the site
// needs no AWS package. The SES_ prefix matters: Netlify runs functions on Lambda and reserves
// the AWS_ names.
//
// Netlify variables (all secret except MAIL_FROM and SES_REGION):
//   NEWSLETTER_SECRET       hex, signs the personal links
//   EXPORT_KEY              hex, read key for the network-ops weekly send
//   SES_ACCESS_KEY_ID       IAM user limited to ses:SendEmail
//   SES_SECRET_ACCESS_KEY
//   SES_REGION              e.g. us-east-1
//   MAIL_FROM               Lawsuit Informer <updates@lawsuitinformer.com>
//   NOTIFY_TO               optional; gets a short email each time a reader confirms (or comes back
//                           from the preferences page): the address, the cases and the signup page
// With SES unset, signups still save as pending and the response is unchanged; the confirm mail
// simply does not go, and the function logs why.

import { getStore } from "@netlify/blobs";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export const config = {
  path: [
    "/api/subscribe",
    "/email/confirm",
    "/email/preferences",
    "/email/unsubscribe",
    "/api/newsletter/export",
  ],
};

// The update pages a reader can follow: the status board's PAGES in generate_status_board.py.
// A page added there needs a line here before readers can pick it. "all" follows every page.
export const TOPICS = [
  ["afff-lawsuit-updates", "AFFF Firefighting Foam"],
  ["openai-lawsuits", "ChatGPT and OpenAI"],
  ["depo-provera-lawsuit-updates", "Depo-Provera"],
  ["hair-relaxer-lawsuit-updates", "Hair Relaxer"],
  ["house-ncaa-settlement-update", "House v. NCAA Settlement"],
  ["asbestos-lawsuit-updates", "Mesothelioma and Asbestos"],
  ["ozempic-lawsuit-updates", "Ozempic and GLP-1 Drugs"],
  ["paraquat-lawsuit-updates", "Paraquat"],
  ["pfas-water-contamination-lawsuit-update", "PFAS Water Contamination"],
  ["roundup-lawsuit-updates", "Roundup"],
  ["social-media-addiction-lawsuit-update", "Social Media Addiction"],
  ["suboxone-lawsuit-updates", "Suboxone Tooth Decay"],
  ["talcum-powder-lawsuit-updates", "Talcum Powder"],
  ["tylenol-lawsuit-updates", "Tylenol and Autism"],
  ["transvaginal-mesh-litigation-update", "Transvaginal Mesh"],
  ["video-game-addiction-lawsuit-update", "Video Games and Roblox"],
];
const TOPIC_NAMES = new Map(TOPICS);
const ALL = "all";

const RESEND_GAP_MS = 10 * 60 * 1000; // at most one confirm mail per address per 10 minutes
const RESEND_DAY_MAX = 4; //             and four per rolling day
const ADDRESS = "Lawsuit Informer · 6210 Wilshire Blvd. Ste 200 · Los Angeles, CA 90048";

// ---------------------------------------------------------------- helpers

const site = () => (process.env.SITE_URL || process.env.URL || "https://lawsuitinformer.com").replace(/\/$/, "");
const store = () => getStore({ name: "newsletter", consistency: "strong" });
const hex = (h) => h.digest("hex");

export function idFor(email) {
  return hex(createHash("sha256").update(email.trim().toLowerCase())).slice(0, 32);
}
function mac(id) {
  const secret = process.env.NEWSLETTER_SECRET || "";
  if (!secret) return "";
  return hex(createHmac("sha256", secret).update("v1:" + id)).slice(0, 32);
}
export function tokenFor(id) {
  const m = mac(id);
  return m ? `${id}.${m}` : "";
}
function idFromToken(t) {
  const m = /^([0-9a-f]{32})\.([0-9a-f]{32})$/.exec(t || "");
  if (!m) return null;
  const want = mac(m[1]);
  if (!want || !timingSafeEqual(Buffer.from(m[2]), Buffer.from(want))) return null;
  return m[1];
}
function sameKey(got, want) {
  if (!want || !got || got.length !== want.length) return false;
  return timingSafeEqual(Buffer.from(got), Buffer.from(want));
}

function cleanEmail(v) {
  const e = String(v || "").trim();
  if (e.length < 6 || e.length > 254) return "";
  return /^[^\s@<>()",;:]+@[^\s@<>()",;:]+\.[a-z]{2,}$/i.test(e) ? e : "";
}
function cleanTopics(list) {
  const out = [];
  for (const raw of list) {
    const t = String(raw || "").trim();
    if (t === ALL) return [ALL];
    if (TOPIC_NAMES.has(t) && !out.includes(t)) out.push(t);
  }
  return out;
}
function topicLabel(topics) {
  if (topics.includes(ALL)) return "every case we track";
  return topics.map((t) => TOPIC_NAMES.get(t)).join(", ");
}

async function readBody(req) {
  const type = req.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const j = await req.json().catch(() => ({}));
    return { get: (k) => j[k], all: (k) => [].concat(j[k] ?? []) };
  }
  const f = await req.formData().catch(() => new FormData());
  return { get: (k) => f.get(k), all: (k) => f.getAll(k) };
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

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function page(status, title, inner) {
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>${esc(title)} | Lawsuit Informer</title>
<style>
:root{--bg:#fafaf7;--panel:#ffffff;--ink:#1a1a1a;--muted:#5a5750;--rule:#e5e3dc;--link:#b04a2f;--link-hover:#8a3621;--accent:#d4a24e}
@media (prefers-color-scheme:dark){:root{--bg:#15130f;--panel:#1d1a15;--ink:#ece9e1;--muted:#a7a397;--rule:#36322a;--link:#e58a6c;--link-hover:#f0a58c;--accent:#d4a24e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 "Source Serif 4",Georgia,"Times New Roman",serif}
main{max-width:560px;margin:0 auto;padding:40px 16px 64px}
.brand{display:block;font:600 22px/1.2 "Fraunces","Times New Roman",serif;color:var(--ink);text-decoration:none;padding-bottom:14px;border-bottom:3px solid var(--accent);margin-bottom:28px}
h1{font:500 30px/1.2 "Fraunces","Times New Roman",serif;margin:0 0 14px}
p{margin:0 0 14px}
a{color:var(--link)}a:hover{color:var(--link-hover)}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:20px;margin:0 0 20px}
fieldset{border:0;padding:0;margin:0 0 18px}
legend{font:600 12px/1.4 "IBM Plex Sans",system-ui,sans-serif;letter-spacing:.1em;color:var(--muted);margin-bottom:10px}
label.topic{display:flex;align-items:center;gap:10px;min-height:44px;padding:4px 0;border-bottom:1px solid var(--rule);cursor:pointer}
label.topic:last-child{border-bottom:0}
input[type=checkbox]{width:20px;height:20px;accent-color:var(--link);flex:none}
button{font:600 15px/1 "IBM Plex Sans",system-ui,sans-serif;background:var(--link);color:#fff;border:0;border-radius:4px;padding:14px 20px;min-height:44px;cursor:pointer}
button:hover{background:var(--link-hover)}
button.quiet{background:transparent;color:var(--link);border:1px solid var(--rule)}
.small{font:13px/1.6 "IBM Plex Sans",system-ui,sans-serif;color:var(--muted)}
.foot{margin-top:36px;padding-top:16px;border-top:1px solid var(--rule)}
</style>
</head>
<body>
<main>
<a class="brand" href="${site()}/">Lawsuit Informer</a>
${inner}
<p class="small foot">${esc(ADDRESS)}</p>
</main>
</body>
</html>`;
  return new Response(html, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

const badLink = () =>
  page(
    400,
    "Link not recognized",
    `<h1>This link did not work</h1>
<p>It may have been copied only in part. Open the link again from the most recent email, or sign up again on <a href="${site()}/">Lawsuit Informer</a>.</p>`
  );

// ---------------------------------------------------------------- SES (API v2, SigV4)

const sha256 = (s) => hex(createHash("sha256").update(s, "utf8"));
const hmacRaw = (key, s) => createHmac("sha256", key).update(s, "utf8").digest();

export function signSes({ body, region, keyId, secret, now = new Date() }) {
  const host = `email.${region}.amazonaws.com`;
  const path = "/v2/email/outbound-emails";
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const day = amzDate.slice(0, 8);
  const signed = "content-type;host;x-amz-date";
  const canonical = [
    "POST",
    path,
    "",
    `content-type:application/json\nhost:${host}\nx-amz-date:${amzDate}\n`,
    signed,
    sha256(body),
  ].join("\n");
  const scope = `${day}/${region}/ses/aws4_request`;
  const toSign = ["AWS4-HMAC-SHA256", amzDate, scope, sha256(canonical)].join("\n");
  let k = hmacRaw("AWS4" + secret, day);
  k = hmacRaw(k, region);
  k = hmacRaw(k, "ses");
  k = hmacRaw(k, "aws4_request");
  const signature = createHmac("sha256", k).update(toSign, "utf8").digest("hex");
  return {
    url: `https://${host}${path}`,
    headers: {
      "content-type": "application/json",
      "x-amz-date": amzDate,
      authorization: `AWS4-HMAC-SHA256 Credential=${keyId}/${scope}, SignedHeaders=${signed}, Signature=${signature}`,
    },
  };
}

async function sendMail(to, subject, html, text) {
  const { SES_ACCESS_KEY_ID: keyId, SES_SECRET_ACCESS_KEY: secret, MAIL_FROM: from } = process.env;
  const region = process.env.SES_REGION || "us-east-1";
  if (!keyId || !secret || !from) {
    console.log("newsletter: SES not configured, confirm mail not sent");
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
  let res;
  try {
    res = await fetch(url, { method: "POST", headers, body });
  } catch (e) {
    // A network failure must never cost a reader their signup: the record still saves.
    console.log(`newsletter: SES unreachable: ${e}`);
    return false;
  }
  if (!res.ok) {
    console.log(`newsletter: SES ${res.status} ${(await res.text()).slice(0, 300)}`);
    return false;
  }
  return true;
}

function confirmMail(link, topics) {
  const what = topicLabel(topics);
  const html = `<!doctype html><html><body style="margin:0;background:#ece9e1;padding:24px 12px;font-family:Georgia,'Times New Roman',serif;color:#1a1a1a">
<div style="max-width:560px;margin:0 auto;background:#fafaf7;border:1px solid #e5e3dc">
<div style="padding:22px 28px;border-bottom:3px solid #d4a24e;font-size:22px;font-weight:bold">Lawsuit Informer</div>
<div style="padding:28px">
<p style="margin:0 0 14px;font-size:22px">Confirm your weekly case updates</p>
<p style="margin:0 0 14px;font-size:16px;line-height:1.6">Someone, hopefully you, asked to get Lawsuit Informer's weekly updates at this address for: ${esc(what)}.</p>
<p style="margin:0 0 22px;font-size:16px;line-height:1.6">Press the button to start them. If you did not ask, ignore this email and nothing will be sent.</p>
<a href="${link}" style="display:inline-block;background:#b04a2f;color:#ffffff;text-decoration:none;padding:13px 20px;border-radius:4px;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Confirm my updates</a>
</div>
<div style="padding:18px 28px;border-top:1px solid #d8d5cc;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;color:#5a5750">${esc(ADDRESS)}</div>
</div></body></html>`;
  const text = `Confirm your weekly case updates from Lawsuit Informer

Someone, hopefully you, asked to get Lawsuit Informer's weekly updates at this address for: ${what}.

Open this link to start them:
${link}

If you did not ask, ignore this email and nothing will be sent.

${ADDRESS}`;
  return { subject: "Confirm your Lawsuit Informer updates", html, text };
}

function manageMail(link) {
  const html = `<!doctype html><html><body style="margin:0;background:#ece9e1;padding:24px 12px;font-family:Georgia,'Times New Roman',serif;color:#1a1a1a">
<div style="max-width:560px;margin:0 auto;background:#fafaf7;border:1px solid #e5e3dc">
<div style="padding:22px 28px;border-bottom:3px solid #d4a24e;font-size:22px;font-weight:bold">Lawsuit Informer</div>
<div style="padding:28px">
<p style="margin:0 0 14px;font-size:22px">You already get our weekly updates</p>
<p style="margin:0 0 22px;font-size:16px;line-height:1.6">This address signed up again on Lawsuit Informer. To add or drop topics, use the button below.</p>
<a href="${link}" style="display:inline-block;background:#b04a2f;color:#ffffff;text-decoration:none;padding:13px 20px;border-radius:4px;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Change my topics</a>
</div>
<div style="padding:18px 28px;border-top:1px solid #d8d5cc;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;color:#5a5750">${esc(ADDRESS)}</div>
</div></body></html>`;
  const text = `You already get Lawsuit Informer's weekly updates

This address signed up again. To add or drop topics, open this link:
${link}

${ADDRESS}`;
  return { subject: "Your Lawsuit Informer topics", html, text };
}

// The owner's notice when a reader becomes active. Never blocks or fails the reader's request.
async function notify(rec, how) {
  const to = (process.env.NOTIFY_TO || "").trim();
  if (!to) return;
  const what = topicLabel(rec.topics || []);
  const from = rec.source ? (rec.source === "home" ? "the homepage" : `${site()}/${rec.source}`) : "unknown";
  const text = `${rec.email} ${how}.

Cases: ${what}
Signed up from: ${from}
Time: ${new Date().toISOString()}`;
  const html = `<!doctype html><html><body style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#1a1a1a">
<p style="margin:0 0 10px"><strong>${esc(rec.email)}</strong> ${esc(how)}.</p>
<p style="margin:0">Cases: ${esc(what)}<br>Signed up from: ${esc(from)}<br>Time: ${esc(new Date().toISOString())}</p>
</body></html>`;
  try {
    await sendMail(to, `New Informer subscriber: ${rec.email}`, html, text);
  } catch (e) {
    console.log(`newsletter: notify failed: ${e}`);
  }
}

// ---------------------------------------------------------------- routes

function mayResend(rec, now) {
  const sends = (rec.sends || []).filter((t) => now - t < 24 * 3600 * 1000);
  if (sends.length >= RESEND_DAY_MAX) return false;
  if (sends.length && now - sends[sends.length - 1] < RESEND_GAP_MS) return false;
  return true;
}

async function subscribe(req) {
  const asJson = wantsJson(req);
  const f = await readBody(req);
  const done = () =>
    asJson
      ? json(200, { ok: true })
      : page(
          200,
          "Check your email",
          `<h1>Check your email</h1>
<p>We sent a link to confirm your weekly updates. Updates start only after you press the button in that email.</p>
<p class="small">Nothing there in a few minutes? Check your spam folder.</p>
<p><a href="${site()}/">Back to Lawsuit Informer</a></p>`
        );

  if (f.get("bot-field")) return done(); // honeypot: look the same, keep nothing
  const email = cleanEmail(f.get("email"));
  const topics = cleanTopics(f.all("topic"));
  if (!email) {
    return asJson
      ? json(400, { ok: false, error: "email" })
      : page(400, "Check the address", `<h1>That email address did not look right</h1><p>Go back and check it, then try again.</p>`);
  }
  if (!topics.length) {
    return asJson
      ? json(400, { ok: false, error: "topics" })
      : page(400, "Pick a topic", `<h1>Pick at least one case to follow</h1><p>Go back, check one or more boxes, then try again.</p>`);
  }

  const s = store();
  const id = idFor(email);
  const key = `sub/${id}`;
  const now = Date.now();
  const iso = new Date(now).toISOString();
  const rec = (await s.get(key, { type: "json" })) || { email, createdAt: iso, status: "new" };
  const token = tokenFor(id);
  if (!token) {
    console.log("newsletter: NEWSLETTER_SECRET unset, signup not saved");
    return done();
  }

  if (rec.status === "active") {
    // Someone typed an active address. Topics stay as the owner set them; the owner gets a link
    // to change them, so a stranger can neither read nor change another reader's choices.
    if (mayResend(rec, now)) {
      const m = manageMail(`${site()}/email/preferences?t=${token}`);
      if (await sendMail(rec.email, m.subject, m.html, m.text)) rec.sends = [...(rec.sends || []), now].slice(-8);
      await s.setJSON(key, rec);
    }
    return done();
  }

  rec.email = email;
  rec.topics = topics;
  rec.status = "pending";
  rec.source = String(f.get("source") || "").slice(0, 120);
  rec.updatedAt = iso;
  if (mayResend(rec, now)) {
    const m = confirmMail(`${site()}/email/confirm?t=${token}`, topics);
    if (await sendMail(email, m.subject, m.html, m.text)) rec.sends = [...(rec.sends || []), now].slice(-8);
  }
  await s.setJSON(key, rec);
  return done();
}

async function confirm(req, id, token) {
  const s = store();
  const key = `sub/${id}`;
  const rec = await s.get(key, { type: "json" });
  if (!rec) return badLink();
  const self = `${site()}/email/confirm?t=${token}`;

  if (req.method === "POST") {
    if (rec.status !== "active") {
      rec.status = "active";
      rec.confirmedAt = new Date().toISOString();
      rec.updatedAt = rec.confirmedAt;
      await s.setJSON(key, rec);
      await notify(rec, "confirmed");
    }
    return page(
      200,
      "You are signed up",
      `<h1>You are signed up</h1>
<p>Your first weekly update comes on the next send. It covers ${esc(topicLabel(rec.topics || []))}.</p>
<p><a href="${site()}/email/preferences?t=${token}">Change topics</a> · <a href="${site()}/">Back to Lawsuit Informer</a></p>`
    );
  }
  if (rec.status === "active") {
    return page(
      200,
      "Already confirmed",
      `<h1>You are already signed up</h1><p><a href="${site()}/email/preferences?t=${token}">Change topics</a> · <a href="${site()}/">Back to Lawsuit Informer</a></p>`
    );
  }
  return page(
    200,
    "Confirm your updates",
    `<h1>Confirm your weekly updates</h1>
<p>You asked for updates on ${esc(topicLabel(rec.topics || []))}.</p>
<form method="post" action="${self}"><button type="submit">Confirm my updates</button></form>`
  );
}

function topicForm(action, chosen) {
  const all = chosen.includes(ALL);
  const rows = TOPICS.map(
    ([slug, name]) =>
      `<label class="topic"><input type="checkbox" name="topic" value="${slug}"${!all && chosen.includes(slug) ? " checked" : ""}> ${esc(name)}</label>`
  ).join("\n");
  return `<form method="post" action="${action}">
<div class="panel">
<fieldset>
<legend>EVERYTHING</legend>
<label class="topic"><input type="checkbox" name="topic" value="${ALL}"${all ? " checked" : ""}> Every case we track</label>
</fieldset>
<fieldset>
<legend>OR PICK CASES</legend>
${rows}
</fieldset>
</div>
<button type="submit">Save my topics</button>
</form>`;
}

async function preferences(req, id, token) {
  const s = store();
  const key = `sub/${id}`;
  const rec = await s.get(key, { type: "json" });
  if (!rec) return badLink();
  const self = `${site()}/email/preferences?t=${token}`;
  const unsub = `${site()}/email/unsubscribe?t=${token}`;

  if (req.method === "POST") {
    const f = await readBody(req);
    const topics = cleanTopics(f.all("topic"));
    rec.updatedAt = new Date().toISOString();
    if (!topics.length) {
      rec.status = "unsubscribed";
      rec.unsubscribedAt = rec.updatedAt;
      await s.setJSON(key, rec);
      return page(
        200,
        "Unsubscribed",
        `<h1>You are unsubscribed</h1><p>You saved with no topics picked, so no more weekly emails will come.</p>
<p><a href="${self}">Pick topics again</a></p>`
      );
    }
    rec.topics = topics;
    const cameBack = rec.status !== "active";
    if (cameBack) {
      // Reaching this page took a link from our own email, which proves the address.
      rec.status = "active";
      rec.confirmedAt = rec.confirmedAt || rec.updatedAt;
    }
    await s.setJSON(key, rec);
    if (cameBack) await notify(rec, "came back from the preferences page");
    return page(
      200,
      "Topics saved",
      `<h1>Your topics are saved</h1><p>Weekly updates will cover ${esc(topicLabel(topics))}.</p>
<p><a href="${self}">Change them again</a> · <a href="${site()}/">Back to Lawsuit Informer</a></p>`
    );
  }

  const state =
    rec.status === "active"
      ? `<p>Updates go to <strong>${esc(rec.email)}</strong>. Check the cases you want and save.</p>`
      : `<p><strong>${esc(rec.email)}</strong> is not getting updates right now. Pick cases and save to start them.</p>`;
  return page(
    200,
    "Your topics",
    `<h1>Your weekly update topics</h1>
${state}
${topicForm(self, rec.topics || [])}
<p class="small" style="margin-top:20px"><a href="${unsub}">Unsubscribe from all updates</a></p>`
  );
}

async function unsubscribe(req, id, token) {
  const s = store();
  const key = `sub/${id}`;
  const rec = await s.get(key, { type: "json" });
  if (!rec) return badLink();
  const self = `${site()}/email/unsubscribe?t=${token}`;

  if (req.method === "POST") {
    if (rec.status !== "unsubscribed") {
      rec.status = "unsubscribed";
      rec.unsubscribedAt = new Date().toISOString();
      rec.updatedAt = rec.unsubscribedAt;
      await s.setJSON(key, rec);
    }
    if (!(req.headers.get("content-type") || "").includes("form") && !wantsJson(req)) {
      return new Response("", { status: 200 }); // a mail client's one-click POST
    }
    return page(
      200,
      "Unsubscribed",
      `<h1>You are unsubscribed</h1><p>No more weekly emails will go to ${esc(rec.email)}.</p>
<p><a href="${site()}/email/preferences?t=${token}">Changed your mind? Pick topics again</a></p>`
    );
  }
  if (rec.status === "unsubscribed") {
    return page(
      200,
      "Already unsubscribed",
      `<h1>You are already unsubscribed</h1><p><a href="${site()}/email/preferences?t=${token}">Pick topics again</a></p>`
    );
  }
  return page(
    200,
    "Unsubscribe",
    `<h1>Stop the weekly updates?</h1>
<p>This stops every Lawsuit Informer weekly email to ${esc(rec.email)}.</p>
<form method="post" action="${self}"><button type="submit">Unsubscribe</button></form>
<p class="small" style="margin-top:20px">Too many emails? <a href="${site()}/email/preferences?t=${token}">Drop some topics instead</a>.</p>`
  );
}

async function exportList(req) {
  if (!sameKey(req.headers.get("x-export-key") || "", process.env.EXPORT_KEY || "")) {
    return json(401, { error: "unauthorized" });
  }
  const s = store();
  const { blobs } = await s.list({ prefix: "sub/" });
  const out = [];
  const counts = { active: 0, pending: 0, unsubscribed: 0 };
  for (const b of blobs) {
    const rec = await s.get(b.key, { type: "json" });
    if (!rec) continue;
    counts[rec.status] = (counts[rec.status] || 0) + 1;
    if (rec.status !== "active") continue;
    const token = tokenFor(b.key.slice(4));
    out.push({
      email: rec.email,
      topics: rec.topics || [],
      confirmedAt: rec.confirmedAt || "",
      preferences: `${site()}/email/preferences?t=${token}`,
      unsubscribe: `${site()}/email/unsubscribe?t=${token}`,
    });
  }
  return json(200, { generated: new Date().toISOString(), counts, topics: TOPICS, subscribers: out });
}

export default async function handler(req) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/$/, "");

  if (path === "/api/subscribe") {
    if (req.method !== "POST") return json(405, { error: "method" });
    return subscribe(req);
  }
  if (path === "/api/newsletter/export") {
    if (req.method !== "GET") return json(405, { error: "method" });
    return exportList(req);
  }

  if (req.method !== "GET" && req.method !== "POST") return json(405, { error: "method" });
  const token = url.searchParams.get("t") || "";
  const id = idFromToken(token);
  if (!id) return badLink();
  if (path === "/email/confirm") return confirm(req, id, token);
  if (path === "/email/preferences") return preferences(req, id, token);
  if (path === "/email/unsubscribe") return unsubscribe(req, id, token);
  return json(404, { error: "not found" });
}
