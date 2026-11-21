// Entry for the vendored spelling bundle: Hunspell compiled to WebAssembly (hunspell-asm), as HunspellAsm.loadModule.
// Its WebAssembly is inside the bundle as base64, so studio/static/book-spell-worker.js loads it with one importScripts.
// The CommonJS build, not the package's ES one: its preamble is a CommonJS function the loader calls, which an ES
// namespace import would hide. Rebuild with build_vendor.mjs (see CONTRIBUTING.md, "Rebuilding the vendored editor").
export { loadModule } from "hunspell-asm/dist/cjs/index.js";
