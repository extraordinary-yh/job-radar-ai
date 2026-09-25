#!/usr/bin/env node
// Fetch one portal entry through career-ops's provider layer and print the postings as JSON.
// Input: a portals.yml-style entry as JSON (argv[2] or stdin): {name, provider?, careers_url?, api?, max_pages?, ...}.
// Output: {provider, jobs: [{title, url, company, location, description?, postedAt?, dedupKey?}]}.
// This is the read-only half of scan.mjs: no filters, no tracker writes, no pipeline.md.
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const vendor = join(here, '..', '..', 'vendor', 'career-ops');
const { loadProviders, resolveProvider } = await import(pathToFileURL(join(vendor, 'providers', '_registry.mjs')).href);
const { makeHttpCtx } = await import(pathToFileURL(join(vendor, 'providers', '_http.mjs')).href);

const raw = process.argv[2] ?? readFileSync(0, 'utf-8');
const entry = JSON.parse(raw);
if (!entry || typeof entry !== 'object' || !entry.name) {
  console.error('fetch.mjs: entry JSON with at least {name} required');
  process.exit(2);
}
const providers = await loadProviders(join(vendor, 'providers'));
const resolved = resolveProvider(entry, providers, { skipIds: ['local-parser'] });
if (!resolved || resolved.error || !resolved.provider) {
  console.error(`fetch.mjs: ${resolved?.error || 'no provider matches this entry (set provider: or a recognised careers_url)'}`);
  process.exit(3);
}
const provider = resolved.provider;
const ctx = { ...makeHttpCtx(), sleep: (ms) => new Promise((r) => setTimeout(r, ms)) };
if (Number.isFinite(Number(entry.max_pages))) ctx.maxPages = Number(entry.max_pages);
const jobs = await provider.fetch(entry, ctx);
const out = [];
for (const j of Array.isArray(jobs) ? jobs : []) {
  if (!j || !j.title || !j.url) continue;
  let dedupKey = null;
  try { dedupKey = typeof provider.dedupKey === 'function' ? provider.dedupKey(j) : null; } catch { dedupKey = null; }
  out.push({
    title: String(j.title), url: String(j.url), company: String(j.company || ''), location: String(j.location || ''),
    description: j.description ? String(j.description) : '', postedAt: Number.isFinite(j.postedAt) ? j.postedAt : null,
    dedupKey: dedupKey ? String(dedupKey) : null,
  });
}
process.stdout.write(JSON.stringify({ provider: provider.id, jobs: out }) + '\n');
