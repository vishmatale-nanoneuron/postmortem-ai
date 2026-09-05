#!/usr/bin/env node
// Pushes the site's real URLs to IndexNow (api.indexnow.org) so Bing and
// Yandex crawl them promptly instead of waiting on their own schedule --
// no account or login required, unlike Google Search Console. The key
// file (apps/web/public/<key>.txt) was added in commit e843407 but the
// actual submission was never made -- a key file alone does nothing by
// itself, it only lets IndexNow verify a submission when one arrives.
// This closes that gap and makes it a real, rerunnable step instead of a
// one-off manual curl: run this again whenever real page content changes
// (new blog post, a published postmortem, a meaningfully updated page) --
// not on every deploy, the same "real content change, not a rebuild"
// bar sitemap.ts's own LAST_MODIFIED dates already use.
//
// Doesn't help Google directly -- Google doesn't participate in
// IndexNow. Search Console (needs your own Google account) is still the
// real fix for Google specifically.
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE = "https://www.nanoneuron.ai";

function findKey() {
  const publicDir = path.join(__dirname, "..", "apps", "web", "public");
  const keyFile = readdirSync(publicDir).find((name) => /^[0-9a-f]{32}\.txt$/.test(name));
  if (!keyFile) {
    console.error("No IndexNow key file found in apps/web/public/ (expected a 32-hex-char <key>.txt).");
    process.exit(1);
  }
  const key = keyFile.replace(/\.txt$/, "");
  const fileContent = readFileSync(path.join(publicDir, keyFile), "utf8").trim();
  if (fileContent !== key) {
    console.error(`Key file ${keyFile}'s content ("${fileContent}") doesn't match its filename -- fix before submitting.`);
    process.exit(1);
  }
  return key;
}

async function fetchSitemapUrls() {
  const response = await fetch(`${SITE}/sitemap.xml`);
  if (!response.ok) {
    console.error(`Could not fetch ${SITE}/sitemap.xml: ${response.status}`);
    process.exit(1);
  }
  const xml = await response.text();
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
}

async function main() {
  const key = findKey();
  const urlList = await fetchSitemapUrls();
  if (urlList.length === 0) {
    console.error("Sitemap returned no URLs -- refusing to submit an empty list.");
    process.exit(1);
  }

  const response = await fetch("https://api.indexnow.org/indexnow", {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      host: new URL(SITE).host,
      key,
      keyLocation: `${SITE}/${key}.txt`,
      urlList,
    }),
  });

  // IndexNow's own documented responses: 200/202 accepted, 400 malformed,
  // 403 key not found/doesn't match, 422 URLs don't belong to the host,
  // 429 too many requests.
  console.log(`Submitted ${urlList.length} URLs. IndexNow response: ${response.status}`);
  for (const url of urlList) console.log(`  ${url}`);
  if (response.status !== 200 && response.status !== 202) {
    console.error("Submission was not accepted -- see the status code above against IndexNow's documented meanings.");
    process.exit(1);
  }
}

main();
