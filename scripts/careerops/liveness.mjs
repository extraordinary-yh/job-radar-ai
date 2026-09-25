#!/usr/bin/env node
// Zero-browser liveness for job URLs, using career-ops's ATS API rung only.
// Input: JSON array of URLs on stdin (or as argv). Output: {url: {result, code, reason} | null}.
// null means "no public ATS API for this host" or an inconclusive answer; callers show nothing for it.
// The Playwright rung (check-liveness.mjs) is deliberately not used: it imports a browser at module
// top and can open a headed window, neither of which belongs in a cron job.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const vendor = join(here, '..', '..', 'vendor', 'career-ops');
const { checkLivenessViaApi } = await import(pathToFileURL(join(vendor, 'liveness-api.mjs')).href);

let urls = process.argv.slice(2);
if (urls.length === 0) {
  const text = readFileSync(0, 'utf-8').trim();
  urls = text ? JSON.parse(text) : [];
}
const out = {};
for (const url of urls) {
  try {
    out[url] = await checkLivenessViaApi(String(url));
  } catch (err) {
    out[url] = null;
  }
}
process.stdout.write(JSON.stringify(out) + '\n');
