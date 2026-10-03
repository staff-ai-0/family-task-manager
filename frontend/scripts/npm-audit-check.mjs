#!/usr/bin/env node
// CI gate around `npm audit` with time-boxed exceptions.
//
// `npm audit --audit-level=high` has no way to accept a single advisory, so
// the moment an advisory lands with NO patched version (2026-10-03:
// http-cache-semantics via astro, patched_version: none) every PR goes red
// and the gate turns into a badge people learn to ignore — which is the
// failure the supply-chain job exists to prevent.
//
// Exceptions live in ../audit-exceptions.json:
//   [{ "id": "GHSA-…", "package": "…", "reason": "…", "expires": "YYYY-MM-DD" }]
// An exception silences exactly one advisory id until its expiry date; an
// expired one fails the run again (with the expiry in the message), so a
// deferral cannot quietly become permanent. Unused exceptions are reported
// so they get removed once upstream ships a fix.
//
// Usage (from frontend/): node scripts/npm-audit-check.mjs [--level=high]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const LEVELS = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 };
const levelArg = process.argv.find((a) => a.startsWith("--level="))?.split("=")[1] ?? "high";
const threshold = LEVELS[levelArg];
if (threshold === undefined) {
  console.error(`unknown --level=${levelArg}; one of ${Object.keys(LEVELS).join(", ")}`);
  process.exit(2);
}

const exceptions = JSON.parse(readFileSync(new URL("../audit-exceptions.json", import.meta.url), "utf8"));
for (const e of exceptions) {
  if (!/^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$/.test(e.id) || !/^\d{4}-\d{2}-\d{2}$/.test(e.expires) || !e.reason) {
    console.error(`audit-exceptions.json: bad entry ${JSON.stringify(e)} (need id GHSA-xxxx-xxxx-xxxx, reason, expires YYYY-MM-DD)`);
    process.exit(2);
  }
}

// npm audit exits non-zero whenever it finds anything; the JSON is on stdout
// either way. Only a missing/unparseable report is an error here.
let raw;
try {
  raw = execFileSync("npm", ["audit", "--omit=dev", "--json"], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
} catch (err) {
  raw = err.stdout;
}
let report;
try {
  report = JSON.parse(raw);
} catch {
  console.error("npm audit produced no parseable JSON report:\n" + String(raw).slice(0, 2000));
  process.exit(2);
}

const today = new Date().toISOString().slice(0, 10);
const failures = [];
const accepted = [];
const used = new Set();

for (const [name, vuln] of Object.entries(report.vulnerabilities ?? {})) {
  // `via` mixes advisory objects (this package is the vulnerable one) with
  // bare package names (this package merely depends on a vulnerable one).
  // Only the former carries an advisory id; the dependents are judged
  // through it, so a single exception covers the whole chain.
  for (const via of vuln.via) {
    if (typeof via !== "object") continue;
    if (LEVELS[via.severity] < threshold) continue;
    const id = via.url.split("/").pop();
    const exception = exceptions.find((e) => e.id === id);
    if (exception && exception.expires >= today) {
      used.add(id);
      accepted.push(`${name} ${via.severity}: ${via.title} (${id}) — accepted until ${exception.expires}: ${exception.reason}`);
      continue;
    }
    const expired = exception ? ` — exception EXPIRED ${exception.expires}, re-evaluate` : "";
    failures.push(`${name} ${via.severity}: ${via.title} ${via.url}${expired}`);
  }
}

for (const line of accepted) console.log("accepted  " + line);
for (const e of exceptions) {
  if (!used.has(e.id)) console.log(`unused    ${e.id} (${e.package}) no longer reported — remove it from audit-exceptions.json`);
}
if (failures.length) {
  console.error(`\nnpm audit: ${failures.length} advisory(ies) at or above '${levelArg}' without a valid exception:`);
  for (const line of failures) console.error("  - " + line);
  process.exit(1);
}
console.log(`npm audit: nothing at or above '${levelArg}' without a valid exception`);
