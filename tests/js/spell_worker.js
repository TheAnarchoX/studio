/* Runs the spelling worker (studio/static/book-spell-worker.js) in node, in a scope made to look like a classic Web
   Worker: importScripts and fetch read /static/… from the folder given, postMessage collects the replies. It loads the
   vendored Hunspell (vendor/hunspell.js) and the bundled dictionaries exactly as the browser does. Used by
   tests/test_spelling.py.

     node spell_worker.js <studio/static>
     output: {"replies": {"<name>": reply, …}}   (each reply as the worker posted it, without its id) */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const [staticDir] = process.argv.slice(2);

const fromStatic = url => {
  const m = /^\/static\/(.+)$/.exec(String(url));
  if (!m) return null;
  return path.join(staticDir, ...m[1].split("/"));
};
const posted = [];
const scope = {
  console, setTimeout, clearTimeout, setInterval, clearInterval, TextDecoder, TextEncoder, crypto: globalThis.crypto,
  performance: globalThis.performance, WebAssembly, URL,
  location: {href: "http://localhost/static/book-spell-worker.js"},
  postMessage: msg => posted.push(JSON.parse(JSON.stringify(msg))),
  importScripts: (...urls) => {
    for (const u of urls) {
      const file = fromStatic(u);
      if (!file) throw new Error("importScripts outside /static/: " + u);
      vm.runInContext(fs.readFileSync(file, "utf8"), scope, {filename: file});
    }
  },
  // the dictionaries from the folder; anything else (Hunspell's own data: URL) as node fetches it
  fetch: async url => {
    const file = fromStatic(url);
    if (!file) return globalThis.fetch(url);
    if (!fs.existsSync(file)) return {ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0)};
    const buf = fs.readFileSync(file);
    return {ok: true, status: 200, arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)};
  },
};
vm.createContext(scope);
// a worker's global object is a WorkerGlobalScope, and `self` (hunspell-asm's loader looks for one)
vm.runInContext(`class WorkerGlobalScope {}
  Object.setPrototypeOf(globalThis, WorkerGlobalScope.prototype);
  globalThis.WorkerGlobalScope = WorkerGlobalScope;
  globalThis.self = globalThis;`, scope);
scope.importScripts("/static/book-spell-worker.js");

let seq = 0;
/* sends a message and waits for the reply with its id (or, for a load, its language) */
function ask(msg, timeout = 30000) {
  const id = ++seq, sent = msg.type === "load" ? msg : {...msg, id};
  const match = r => msg.type === "load" ? (r.type === "loaded" || r.type === "error") && r.lang === msg.lang : r.id === id;
  scope.onmessage({data: sent});
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    (function poll() {
      const i = posted.findIndex(match);
      if (i >= 0) { const r = posted.splice(i, 1)[0]; delete r.id; return resolve(r); }
      if (Date.now() - t0 > timeout) return reject(new Error("no reply to " + JSON.stringify(msg)));
      setTimeout(poll, 5);
    })();
  });
}
const dict = lang => ({type: "load", lang, aff: `/static/dictionaries/${lang}/index.aff`, dic: `/static/dictionaries/${lang}/index.dic`});

(async () => {
  const replies = {};
  // all three at once, as the editor sends them; a check sent meanwhile waits for its dictionaries
  const loads = ["nl", "en", "en-GB"].map(l => ask(dict(l)));
  const early = ask({type: "check", words: [["maandag", ["nl"]], ["gigantsiche", ["nl"]]]});
  [replies["load nl"], replies["load en"], replies["load en-GB"]] = await Promise.all(loads);
  replies["check before loaded"] = await early;
  replies["load missing"] = await ask(dict("xx"));
  const dutch = ["maandag", "kliniek", "gigantsiche", "timeout"];
  replies["dutch in nl"] = await ask({type: "check", words: dutch.map(w => [w, ["nl"]])});
  replies["dutch in nl and en"] = await ask({type: "check", words: dutch.map(w => [w, ["nl", "en"]])});
  replies["Oktober in nl"] = await ask({type: "check", words: [["Oktober", ["nl"]]]});
  replies["a lang span in en"] = await ask({type: "check", words: [["beautfil", ["en"]], ["maandag", ["en"]], ["beautiful", ["en"]], ["kliniek", ["nl"]]]});
  replies["British in en-GB"] = await ask({type: "check", words: [["colour", ["en-GB"]], ["realise", ["en-GB"]], ["colour", ["en"]]]});
  replies["apostrophes"] = await ask({type: "check", words: [["auto’s", ["nl"]], ["auto's", ["nl"]], ["don’t", ["en"]]]});
  replies["no dictionary"] = await ask({type: "check", words: [["qwzx", ["xx"]], ["qwzx", ["nl", "xx"]]]});
  replies["suggest gigantsiche"] = await ask({type: "suggest", word: "gigantsiche", langs: ["nl"]});
  replies["suggest beautfil in nl and en"] = await ask({type: "suggest", word: "beautfil", langs: ["nl", "en"]});
  process.stdout.write(JSON.stringify({replies}));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
