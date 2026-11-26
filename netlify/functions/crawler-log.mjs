// Crawler log export. Added 2026-11-26.
//
// Reads what netlify/edge-functions/crawler-log.js recorded and adds it up.
//
//   GET /api/crawlers/export            last 7 days, production site
//   GET /api/crawlers/export?days=28    1 to 31 days
//   GET /api/crawlers/export?env=test   hits on staging and deploy previews
//   GET /api/crawlers/export?bot=DuckAssistBot   one crawler only
//
// Every call needs the header x-export-key, matched against the EXPORT_KEY environment
// variable: the same key the newsletter and question exports use. Without it the answer
// is 401 and nothing is read.
//
// The answer is JSON:
//   { generated_utc, env, days, total, by_bot: { <crawler>: <hits> },
//     rows: [ { day, bot, page, hits, first_utc, last_utc } ] }
// One row per day, crawler and page, newest day first, then most hits first.
// It only lists blob keys. It reads no blob, writes nothing and deletes nothing.

import { getStore } from "@netlify/blobs";
import { timingSafeEqual } from "node:crypto";

export const config = { path: "/api/crawlers/export" };

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" },
  });

function sameKey(given, expected) {
  const a = Buffer.from(String(given || ""));
  const b = Buffer.from(String(expected || ""));
  return b.length > 0 && a.length === b.length && timingSafeEqual(a, b);
}

// "d/2026-11-26/prod/DuckAssistBot/es~roundup-lawsuit/1795734714509-ab12cd"
export function parseKey(key) {
  const parts = String(key).split("/");
  if (parts.length !== 6 || parts[0] !== "d") return null;
  const ms = Number(parts[5].split("-")[0]);
  if (!Number.isFinite(ms)) return null;
  const token = parts[4];
  return { day: parts[1], env: parts[2], bot: parts[3], page: token === "index" ? "/" : "/" + token.replace(/~/g, "/"), ms };
}

export function lastDays(n, now = Date.now()) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(new Date(now - i * 86400000).toISOString().slice(0, 10));
  return out;
}

export function addUp(keys, onlyBot = "") {
  const groups = new Map();
  const byBot = {};
  let total = 0;
  for (const key of keys) {
    const hit = parseKey(key);
    if (!hit || (onlyBot && hit.bot.toLowerCase() !== onlyBot.toLowerCase())) continue;
    total += 1;
    byBot[hit.bot] = (byBot[hit.bot] || 0) + 1;
    const id = `${hit.day}|${hit.bot}|${hit.page}`;
    const row = groups.get(id) || { day: hit.day, bot: hit.bot, page: hit.page, hits: 0, first: hit.ms, last: hit.ms };
    row.hits += 1;
    row.first = Math.min(row.first, hit.ms);
    row.last = Math.max(row.last, hit.ms);
    groups.set(id, row);
  }
  const rows = [...groups.values()]
    .sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : b.hits - a.hits || a.bot.localeCompare(b.bot) || a.page.localeCompare(b.page)))
    .map((r) => ({ day: r.day, bot: r.bot, page: r.page, hits: r.hits, first_utc: new Date(r.first).toISOString(), last_utc: new Date(r.last).toISOString() }));
  return { total, by_bot: byBot, rows };
}

export default async (req) => {
  if (req.method !== "GET") return json(405, { error: "GET only" });
  if (!sameKey(req.headers.get("x-export-key") || "", process.env.EXPORT_KEY || "")) return json(401, { error: "export key missing or wrong" });

  const url = new URL(req.url);
  const days = Math.min(31, Math.max(1, parseInt(url.searchParams.get("days") || "7", 10) || 7));
  const env = url.searchParams.get("env") === "test" ? "test" : "prod";
  const bot = (url.searchParams.get("bot") || "").replace(/[^A-Za-z0-9-]/g, "").slice(0, 40);

  const store = getStore("crawler-log");
  const keys = [];
  for (const day of lastDays(days)) {
    const { blobs } = await store.list({ prefix: `d/${day}/${env}/` });
    for (const b of blobs) keys.push(b.key);
  }
  return json(200, { generated_utc: new Date().toISOString(), env, days, ...addUp(keys, bot) });
};
