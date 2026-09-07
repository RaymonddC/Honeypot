/**
 * Verify every translation key used in the code resolves in BOTH locales.
 *
 * next-intl resolves keys at runtime, so a missing or clobbered key is
 * invisible to `tsc` and to `next build` — it surfaces only as a raw
 * "login.enterConsole" rendered in the UI. This script closes that gap.
 *
 *   node scripts/check-messages.mjs
 *
 * Only literal keys are checked. Template keys (t(`pillars.${k}`)) are resolved
 * where the prefix is static by asserting the prefix exists and is an object;
 * fully dynamic keys are reported as unverifiable rather than silently passed.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const LOCALES = ["en", "id"];

const messages = Object.fromEntries(
  LOCALES.map((l) => [l, JSON.parse(readFileSync(join(ROOT, `messages/${l}.json`), "utf8"))]),
);

function walkFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (name === "node_modules" || name === ".next") continue;
    if (statSync(p).isDirectory()) walkFiles(p, out);
    else if (/\.tsx?$/.test(p)) out.push(p);
  }
  return out;
}

const lookup = (obj, dotted) =>
  dotted.split(".").reduce((acc, k) => (acc && typeof acc === "object" ? acc[k] : undefined), obj);

const problems = [];
const unverifiable = [];

for (const file of [...walkFiles(join(ROOT, "app")), ...walkFiles(join(ROOT, "components"))]) {
  const src = readFileSync(file, "utf8");
  const rel = relative(ROOT, file).replace(/\\/g, "/");

  // Namespaces this file binds, e.g. const t = useTranslations("login")
  const namespaces = [...src.matchAll(/useTranslations\(\s*"([^"]*)"\s*\)/g)].map((m) => m[1]);
  if (namespaces.length === 0) continue;

  const lines = src.split("\n");
  lines.forEach((line, i) => {
    // literal: t("a.b") / t.rich("a.b")
    for (const m of line.matchAll(/\bt(?:\.rich)?\(\s*"([^"`$]+)"/g)) {
      const key = m[1];
      const resolved = namespaces.some((ns) =>
        LOCALES.every((l) => typeof lookup(messages[l], ns ? `${ns}.${key}` : key) === "string"),
      );
      if (!resolved) {
        const missing = LOCALES.filter(
          (l) => !namespaces.some((ns) => typeof lookup(messages[l], ns ? `${ns}.${key}` : key) === "string"),
        );
        problems.push(`${rel}:${i + 1}  ${namespaces.join("|")}.${key}  missing in: ${missing.join(", ")}`);
      }
    }
    // template with a static prefix: t(`pillars.${k}`) -> require `pillars` object
    for (const m of line.matchAll(/\bt(?:\.rich)?\(\s*`([^`$]*)\$\{/g)) {
      const prefix = m[1].replace(/\.$/, "");
      if (!prefix) {
        unverifiable.push(`${rel}:${i + 1}  fully dynamic key`);
        continue;
      }
      const ok = namespaces.some((ns) =>
        LOCALES.every((l) => {
          const node = lookup(messages[l], ns ? `${ns}.${prefix}` : prefix);
          return node && typeof node === "object";
        }),
      );
      if (!ok) problems.push(`${rel}:${i + 1}  ${namespaces.join("|")}.${prefix}.*  prefix missing or not an object`);
    }
  });
}

// Keys present in one locale but not the other — the clobbering failure mode.
const flatten = (o, p = "", out = []) => {
  for (const [k, v] of Object.entries(o)) {
    const key = p ? `${p}.${k}` : k;
    if (v && typeof v === "object") flatten(v, key, out);
    else out.push(key);
  }
  return out;
};
const [a, b] = LOCALES.map((l) => new Set(flatten(messages[l])));
for (const k of a) if (!b.has(k)) problems.push(`messages: "${k}" in ${LOCALES[0]} but not ${LOCALES[1]}`);
for (const k of b) if (!a.has(k)) problems.push(`messages: "${k}" in ${LOCALES[1]} but not ${LOCALES[0]}`);

if (unverifiable.length) {
  console.log(`${unverifiable.length} fully-dynamic key(s), not checkable:`);
  for (const u of unverifiable) console.log("  " + u);
  console.log("");
}
if (problems.length) {
  console.error(`✗ ${problems.length} message problem(s):\n`);
  for (const p of problems) console.error("  " + p);
  process.exit(1);
}
console.log(`✓ all translation keys resolve in ${LOCALES.join(" + ")}`);
