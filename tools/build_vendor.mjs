// Bundles tools/vendor-entry.js into one classic-script IIFE exposing window.PM (the book editor), and
// tools/hunspell-entry.js into one exposing HunspellAsm (Hunspell for the spelling worker, which loads it with
// importScripts). Also copies KaTeX (js, css rewritten to woff2 only, fonts, licence) into static/vendor/katex/.
// Run from tools/: npm ci && node build_vendor.mjs
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const iife = {
  bundle: true,
  format: "iife",
  minify: true,
  legalComments: "eof",
  target: "es2020",
  charset: "utf8",
  logLevel: "info",
};

await build({
  ...iife,
  entryPoints: [resolve(here, "vendor-entry.js")],
  outfile: resolve(here, "../studio/static/vendor/prosemirror.js"),
  globalName: "PM",
});

await build({
  ...iife,
  entryPoints: [resolve(here, "hunspell-entry.js")],
  outfile: resolve(here, "../studio/static/vendor/hunspell.js"),
  globalName: "HunspellAsm",
});

// KaTeX: copy the minified build, keep only woff2 fonts (every browser Studio targets reads them).
const kdist = resolve(here, "node_modules/katex/dist");
const vendor = resolve(here, "../studio/static/vendor");
const kout = resolve(vendor, "katex");
rmSync(kout, { recursive: true, force: true });
mkdirSync(resolve(kout, "fonts"), { recursive: true });
copyFileSync(resolve(kdist, "katex.min.js"), resolve(kout, "katex.min.js"));
const css = readFileSync(resolve(kdist, "katex.min.css"), "utf8").replace(
  /src:url\((fonts\/[^)]+\.woff2)\) format\("woff2"\),[^;}]*/g,
  'src:url($1) format("woff2")',
);
writeFileSync(resolve(kout, "katex.min.css"), css);
for (const f of readdirSync(resolve(kdist, "fonts")).filter((n) => n.endsWith(".woff2")).sort()) {
  copyFileSync(resolve(kdist, "fonts", f), resolve(kout, "fonts", f));
}
copyFileSync(resolve(here, "node_modules/katex/LICENSE"), resolve(vendor, "LICENSE-katex.txt"));
