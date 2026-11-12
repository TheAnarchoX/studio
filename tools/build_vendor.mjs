// Bundles tools/vendor-entry.js into one classic-script IIFE exposing window.PM.
// Run from tools/: npm ci && node build_vendor.mjs
import { build } from "esbuild";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

await build({
  entryPoints: [resolve(here, "vendor-entry.js")],
  outfile: resolve(here, "../studio/static/vendor/prosemirror.js"),
  bundle: true,
  format: "iife",
  globalName: "PM",
  minify: true,
  legalComments: "eof",
  target: "es2020",
  charset: "utf8",
  logLevel: "info",
});
