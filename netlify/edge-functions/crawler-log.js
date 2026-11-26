// Crawler log (edge function). Added 2026-11-26.
//
// WHAT IT DOES
// Records one small marker each time a named search or AI crawler requests a page:
// which crawler, which page, and when. It never changes the request or the response.
// The page is served exactly as it would be without this file.
//
// WHY
// The Netlify plan this site is on shows a request chart with no search, so there is
// no way to see whether DuckDuckGo's answer crawler (DuckAssistBot), Bingbot, or the
// ChatGPT, Claude and Perplexity crawlers fetch a given page. The AI citation reads in
// network-ops record which pages each engine cites. This records which pages each
// engine fetched, so the two can be compared.
//
// WHEN IT RUNS
// Only on requests whose User-Agent names one of the crawlers in the `header` rule at
// the bottom of this file. A visitor's browser never starts it, so it adds nothing to
// a reader's page load and uses edge function invocations for crawler requests only.
//
// WHERE THE DATA GOES
// Netlify Blobs store "crawler-log". Each hit is one blob whose KEY carries the data:
//   d/<YYYY-MM-DD>/<prod|test>/<crawler>/<page>/<millisecond time>-<random>
// The value is "1". netlify/functions/crawler-log.mjs lists the keys and adds them up,
// behind the same x-export-key the newsletter export uses. No visitor data is stored:
// no IP address, no cookie, and no request from a person's browser.
//
// IF IT FAILS
// `onError: "bypass"` serves the page as if this function did not exist.
//
// TO ADD A CRAWLER
// Add its User-Agent name in both places: the BOTS list and the `header` rule.

import { getStore } from "@netlify/blobs";

// Name recorded -> pattern looked for in the User-Agent. First match wins, so the more
// specific names sit above the general ones.
const BOTS = [
  ["DuckAssistBot", /duckassistbot/i],
  ["DuckDuckBot", /duckduckbot/i],
  ["OAI-SearchBot", /oai-searchbot/i],
  ["ChatGPT-User", /chatgpt-user/i],
  ["GPTBot", /gptbot/i],
  ["Claude-SearchBot", /claude-searchbot/i],
  ["Claude-User", /claude-user/i],
  ["ClaudeBot", /claudebot/i],
  ["Perplexity-User", /perplexity-user/i],
  ["PerplexityBot", /perplexitybot/i],
  ["bingbot", /bingbot/i],
  ["Yahoo-Slurp", /slurp/i],
];

const ASSET = /\.(css|js|mjs|map|json|xml|txt|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|mp4|webm)$/i;

export function botName(userAgent) {
  const ua = String(userAgent || "");
  for (const [name, pattern] of BOTS) if (pattern.test(ua)) return name;
  return "";
}

// "/es/roundup-lawsuit" -> "es~roundup-lawsuit". Keys keep to letters, digits and . _ ~ -
export function pageToken(pathname) {
  const clean = String(pathname || "/").replace(/^\/+/, "").replace(/\/+$/, "") || "index";
  return clean.replace(/\//g, "~").replace(/[^A-Za-z0-9._~-]/g, "_").slice(0, 160);
}

export function hitKey(bot, pathname, hostname, now = Date.now()) {
  const day = new Date(now).toISOString().slice(0, 10);
  const env = /(^|\.)lawsuitinformer\.com$/i.test(String(hostname || "")) ? "prod" : "test";
  const rand = Math.random().toString(36).slice(2, 8) || "0";
  return `d/${day}/${env}/${bot}/${pageToken(pathname)}/${now}-${rand}`;
}

async function record(request) {
  if (request.method !== "GET") return;
  const bot = botName(request.headers.get("user-agent"));
  if (!bot) return;
  const url = new URL(request.url);
  if (ASSET.test(url.pathname) || url.pathname.startsWith("/api/") || url.pathname.startsWith("/.netlify/")) return;
  const key = hitKey(bot, url.pathname, url.hostname);
  await getStore("crawler-log").set(key, "1");
  console.log(`crawler-log ${bot} ${url.pathname}`);
}

export default async (request, context) => {
  const work = record(request).catch((err) => console.log(`crawler-log error ${err && err.message}`));
  if (context && typeof context.waitUntil === "function") context.waitUntil(work);
  else await work;
  // Returning nothing hands the request on unchanged.
};

export const config = {
  path: "/*",
  excludedPath: ["/api/*", "/.netlify/*", "/fonts/*", "/*.css", "/*.js", "/*.png", "/*.jpg", "/*.svg", "/*.ico", "/*.woff2", "/*.webp"],
  method: "GET",
  header: {
    "user-agent":
      "(DuckAssistBot|DuckDuckBot|OAI-SearchBot|ChatGPT-User|GPTBot|Claude-SearchBot|Claude-User|ClaudeBot|Perplexity-User|PerplexityBot|[Bb]ingbot|Slurp)",
  },
  onError: "bypass",
};
