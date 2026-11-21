"use strict";
/* Backups (spec B8-B16): the Settings section, drawn by showSettings through window.settingsSections, and a line on
   Home when backups have failed or stopped (window.homeSections). The endpoints are in studio/routes_library.py.
   The helpers at the top are pure, so tests/test_library_static.py runs them in node. */
window.settingsSections = window.settingsSections || [];
window.homeSections = window.homeSections || [];

window.Backups = (() => {
  /* ——— pure helpers ——— */
  /* v with d decimals as Python's format writes it: a tie goes to the even digit (toFixed takes it away from zero).
     A size can only tie at x.5 for whole numbers and at x.25 or x.75 for one decimal, and those are exact. */
  const fixed = (v, d) => {
    const q = v * (d ? 4 : 2);
    if (Number.isInteger(q) && q % 2) { const n = Math.floor(v * 10 ** d); return ((n % 2 ? n + 1 : n) / 10 ** d).toFixed(d); }
    return v.toFixed(d);
  };
  /* Bytes as the server says them (backup.size_text): "940 KB", "12 MB", "1.2 GB", one decimal under 10. */
  function sizeText(n) {
    n = Math.max(0, Math.floor(Number(n) || 0));
    if (n < 1024 ** 2) return `${Math.max(1, Number(fixed(n / 1024, 0)))} KB`;
    for (const [unit, div] of [["MB", 1024 ** 2], ["GB", 1024 ** 3], ["TB", 1024 ** 4]]) {
      const v = n / div;
      if (v < 1024 || unit === "TB") return `${fixed(v, v < 10 ? 1 : 0)} ${unit}`;
    }
  }
  /* For the restore filter: case and accents don't matter ("cafe" finds "Café"). */
  const fold = s => String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").normalize("NFC").toLowerCase();
  /* Whether every word of q is somewhere in the texts. */
  const matches = (q, texts) => {
    const hay = fold(texts.join("\n"));
    return fold(q).split(/\s+/).filter(Boolean).every(w => hay.includes(w));
  };

  /* ——— words and dates ——— */
  const DESCRIPTION = "Studio keeps copies of your poems, books and styles in a folder you choose: every backup from the last day, "
    + "then one a day for a week, one a week for a month and one a month for a year.";
  const SAME_DISK = "This folder is on the same disk as your library. It protects against mistakes, not against a failing disk: "
    + "choose a folder on another drive, or one your cloud service syncs, for that.";
  const fmtTime = new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit"});
  /* "13 Nov 2026, 03:00": backups are kept for a year, so the year is always there */
  const at = iso => { const d = new Date(iso); return isNaN(d) ? String(iso ?? "") : `${day(iso)}, ${fmtTime.format(d)}`; };
  /* "14:20" today, "12 Nov, 14:20" on another day */
  const clock = iso => { const d = new Date(iso); return isNaN(d) ? "" : d.toDateString() === new Date().toDateString() ? fmtTime.format(d) : when(iso); };
  const num = n => Number(n).toLocaleString("en-GB");
  const files = n => `${num(n)} ${n === 1 ? "file" : "files"}`;
  const names = list => list.length > 4 ? `${list.slice(0, 3).join(", ")} and ${list.length - 3} more`
    : list.length > 1 ? `${list.slice(0, -1).join(", ")} and ${list.at(-1)}` : list.join("");
  const norm = p => String(p || "").replace(/[\\/]+/g, "/").replace(/\/$/, "").toLowerCase();

  /* ——— Settings → Backups ——— */
  let page = 0;           // the Settings page being drawn: a newer one stops the older one's polling
  let jump = false;       // Home's link asked for this section

  function html(s) {
    const inApp = !!window.pywebview?.api;
    return `<div class="sh"><h2 class="h2">Backups</h2><p class="muted">${esc(DESCRIPTION)}</p></div>
      <div class="sb">
        <label class="switch"><input type="checkbox" id="lb-on" ${s.backups ? "checked" : ""}><span>Back up automatically (when Studio starts, then once a day)</span></label>
        <p class="hint" id="lb-off" ${s.backups ? "hidden" : ""}>Automatic backups are off.</p>
        <label class="label lb-gap" for="lb-folder">Backup folder</label>
        <div class="pathrow"><input class="input" id="lb-folder" value="${esc(s.backup_folder || "")}" spellcheck="false" autocomplete="off">
          ${inApp ? `<button type="button" class="btn" id="lb-pick">Choose…</button>` : ""}</div>
        <div id="lb-where"></div>
        <div id="lb-now"></div>
        <div id="lb-news"></div>
        <div class="lb-list" id="lb-list" role="list" aria-label="Backups in the folder"></div>
      </div>`;
  }

  function bind(root, s, info) {
    if (!root) return;
    const me = ++page;
    const v = {root, info, data: null, error: "", refused: "", news: "", newsPath: "", started: false, timer: 0};
    const live = () => me === page && root.isConnected && state.view === "settings";
    const field = $("#lb-folder", root);

    v.load = async () => {
      try { v.data = await api("/api/backups"); v.error = ""; } catch (e) { v.error = e.message; }
      if (!live()) return;
      paint(v);
      clearTimeout(v.timer);
      if (v.data?.running) v.timer = setTimeout(() => { if (live()) v.load(); }, 1000);
      else if (v.started) {         // a backup asked for here has ended: say how
        v.started = false;
        const st = v.data?.state || {};
        if (st.last_result === "failed") toast(st.last_error?.message || "The backup didn't finish", true);
        else if (st.last_result === "made") toast("Backup made");
      }
    };

    $("#lb-on", root).onchange = async e => {
      const on = e.target.checked;
      try { await api("/api/settings", {backups: on}); $("#lb-off", root).hidden = on; }
      catch (err) { e.target.checked = !on; toast(err.message, true); }
    };
    const saveFolder = async value => {
      try {
        await api("/api/settings", {backup_folder: value});
        v.refused = "";
        toast(value ? "Backups go to the new folder" : "Backups go to the default folder");
        v.load();
      } catch (err) { v.refused = err.message; paintWhere(v); }
    };
    field.onchange = () => saveFolder(field.value.trim());
    field.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); field.blur(); } };     // saved by its change, never the whole form
    const pick = $("#lb-pick", root);
    if (pick) pick.onclick = async () => {
      const p = await window.pywebview.api.pick_folder(field.value.trim() || v.data?.folder || "");
      if (p) { field.value = p; saveFolder(p); }
    };

    root.addEventListener("click", e => {
      const b = e.target.closest("button[data-lb]");
      if (!b || b.disabled) return;
      const act = b.dataset.lb, backup = v.data?.backups?.[+b.dataset.i];
      if (act === "run") runNow(v);
      else if (act === "show") reveal({});
      else if (act === "choose" && backup) chooseDialog(v, backup);
      else if (act === "use") useLibrary(v.newsPath);
      else if (act === "showpath") reveal({path: v.newsPath});
    });
    $("#lb-list", root).addEventListener("contextmenu", ev => {
      const row = ev.target.closest(".lb-row"), b = row && v.data?.backups?.[+row.dataset.i];
      if (!b) return;
      StudioMenu.open(ev, [
        {label: "Choose what to restore…", disabled: !b.readable, act: () => chooseDialog(v, b)},
        {label: "Restore the whole backup…", disabled: !b.readable, act: () => restoreAll(v, b)},
        "-",
        {label: "Show in folder", act: () => reveal({name: b.name})},
      ]);
    });
    if (jump) { jump = false; root.scrollIntoView({block: "start"}); }
    v.load();
  }

  function paint(v) {
    paintWhere(v);
    paintNow(v);
    paintNews(v);
    paintList(v);
  }

  /* Under the folder field: why it can't be used, that the environment overrides it, or that it is on the library's disk. */
  function paintWhere(v) {
    const d = v.data, field = $("#lb-folder", v.root);
    if (d) field.placeholder = d.default_folder || "";
    const env = !!d?.env_folder;        // the server says so: STUDIO_BACKUPS is set
    const told = d?.state?.last_result === "failed" && d.state.last_error?.message === d.folder_problem;   // the line below says it
    $("#lb-where", v.root).innerHTML = v.refused ? `<p class="hint bad" role="alert">${esc(v.refused)}</p>`
      : !d ? ""
      : d.folder_problem && !told ? `<p class="hint bad">${esc(d.folder_problem)}</p>`
      : env ? `<p class="hint bad">STUDIO_BACKUPS is set in the environment and overrides this (now ${esc(d.folder)}).</p>`
      : d.same_disk ? `<p class="hint">${esc(SAME_DISK)}</p>` : "";
  }

  /* The state: the last backup, the failure, or the backup that runs; the buttons; what isn't backed up. */
  function paintNow(v) {
    const host = $("#lb-now", v.root), d = v.data;
    if (!d) { host.innerHTML = v.error ? `<p class="hint bad lb-status">${esc(v.error)}</p>` : ""; return; }
    const st = d.state || {}, newest = (d.backups || []).find(b => b.readable && b.same_library);
    const ok = st.last_ok || newest, failed = st.last_result === "failed" && st.last_error?.message;
    const last = ok ? `Last backup ${at(ok.when)} · ${sizeText(ok.bytes)}` : "";
    let line;
    if (d.running) {
      const {done = 0, total = 0} = d.running;
      line = `Backing up…${total ? ` ${num(done)} of ${files(total)}` : ""}`;
    } else if (failed) {
      line = `<span class="bad">${esc(st.last_error.message)}</span>${ok ? ` ${esc(`The last backup is from ${at(ok.when)}.`)}` : ""}`;
    } else if (ok) {
      line = esc(last + (st.last_result === "unchanged" && st.last_check ? ` · checked ${clock(st.last_check)}, nothing changed since` : ""));
    } else line = d.backups?.length ? "No backup of this library yet." : "No backup yet.";      // the list holds others'
    const notes = !failed && !d.running && st.last_ok?.warnings?.length ? st.last_ok.warnings : [];
    const o = d.outside || {}, folders = o.folders || [];
    const what = [folders.length ? plural(folders.length, "other folder") : "",
      o.files ? plural(o.files, folders.length ? "file" : "other file") : ""].filter(Boolean).join(" and ");
    host.innerHTML = `<p class="hint lb-status"${failed ? ` role="alert"` : ""}>${line}</p>
      ${notes.length ? `<p class="hint">From the last backup: ${esc(notes.slice(0, 3).join(" "))}${notes.length > 3 ? ` And ${notes.length - 3} more.` : ""}</p>` : ""}
      <div class="lb-acts"><button type="button" class="btn small" data-lb="run" ${d.running ? "disabled" : ""}>${failed ? "Try again" : "Back up now"}</button><button type="button" class="btn quiet small" data-lb="show">Show in folder</button></div>
      ${what ? `<p class="hint">${esc(`Not backed up: ${what} in the library (${sizeText(o.bytes)})${folders.length ? `: ${names(folders)}` : ""}.`)}</p>` : ""}`;
  }

  /* What a restore did, with where to go next. */
  function paintNews(v) {
    const host = $("#lb-news", v.root);
    if (!v.newsPath) { host.innerHTML = v.news; return; }
    host.innerHTML = `<div class="lb-news"><p class="hint">Unpacked into ${esc(v.newsPath)}</p>
      <div class="lb-acts"><button type="button" class="btn small" data-lb="use">Use it as the library</button><button type="button" class="btn quiet small" data-lb="showpath">Show in folder</button></div></div>`;
  }

  function paintList(v) {
    const lib = norm(v.info?.library);
    $("#lb-list", v.root).innerHTML = (v.data?.backups || []).map((b, i) => {
      const note = !b.readable ? "Not readable" : b.same_library ? ""
        : b.library && norm(b.library) === lib ? `From another computer${b.computer ? ` (${b.computer})` : ""}`
        : `From another library${b.library ? ` (${b.library})` : ""}`;
      return `<div class="lb-row" role="listitem" data-i="${i}"><span class="lb-when">${esc(at(b.when))}</span>
        <span class="lb-num">${esc(sizeText(b.bytes))}</span><span class="lb-num">${b.files == null ? "" : esc(files(b.files))}</span>
        <span class="lb-note">${esc(note)}</span>
        ${b.readable ? `<button type="button" class="btn small" data-lb="choose" data-i="${i}">Restore…</button>` : "<span></span>"}</div>`;
    }).join("");
  }

  async function runNow(v) {
    try {
      const st = await api("/api/backups/run", {});
      v.data = {...v.data, ...st};
      v.started = true;
      v.load();
    } catch (e) {
      if (e.status === 409) { toast(e.message); v.load(); }      // one is running already: show it, and its progress
      else toast(e.message, true);
    }
  }

  const reveal = body => api("/api/backups/reveal", body).catch(e => toast(e.message, true));

  /* ——— restoring ——— */
  /* The backup's poems (by series) and books (with their pieces) as rows, in the order the dialog shows them. */
  function rowsOf(it) {
    const out = [], bySeries = new Map();
    for (const p of it.poems || []) {
      if (!bySeries.has(p.series)) bySeries.set(p.series, []);
      bySeries.get(p.series).push(p);
    }
    for (const [series, poems] of bySeries) {
      for (const p of poems) out.push({kind: "poem", key: "poem:" + p.id, id: p.id, title: p.title, series, exists: p.exists, hay: [p.title, series]});
    }
    for (const b of it.books || []) {
      const book = {kind: "book", key: "book:" + b.id, id: b.id, title: b.title, exists: b.exists, pieces: (b.pieces || []).length, hay: [b.title]};
      out.push(book);
      for (const x of b.pieces || []) {
        out.push({kind: "piece", key: `piece:${b.id}/${x.file}`, book, file: x.file, title: x.title, exists: x.exists, hay: [x.title, b.title]});
      }
    }
    return out;
  }

  async function chooseDialog(v, b) {
    let it;
    try { it = await api("/api/backups/items?name=" + encodeURIComponent(b.name)); } catch (e) { toast(e.message, true); return; }
    const rows = rowsOf(it);
    let shown = rows, sel = 0;
    const from = !b.same_library && b.library ? (norm(b.library) === norm(v.info?.library)
      ? `From another computer${b.computer ? ` (${b.computer})` : ""}` : `From another library (${b.library})`) : "";
    const form = openDialog(`<form class="lb-dlg">
      <h2>Choose what to restore</h2>
      <p class="lb-from">${esc(`From the backup of ${at(b.when)}${from ? ` · ${from}` : ""}`)}</p>
      <input class="input" id="lb-q" placeholder="Filter by title, series or book" aria-label="Filter" aria-controls="lb-tree" spellcheck="false" autocomplete="off">
      <div class="lb-tree" id="lb-tree" role="listbox" tabindex="0" aria-label="Poems and books in this backup"></div>
      <p class="lb-line" id="lb-line" aria-live="polite"></p>
      <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="button" class="btn quiet" id="lb-all">Restore the whole backup…</button>
        <span class="lb-dacts"><button type="button" class="btn" id="lb-replace">Replace…</button><button type="submit" class="btn solid" id="lb-do">Restore a copy</button></span></div>
    </form>`, async () => {
      const x = shown[sel];
      if (x) await restoreOne(v, b, x, x.exists ? "copy" : "restore");
    });
    const q = $("#lb-q", form), tree = $("#lb-tree", form), line = $("#lb-line", form);
    const replace = $("#lb-replace", form), go = $("#lb-do", form);
    // the new-computer path: everything, into a new folder next to the library (the same confirmation as the menu's)
    $("#lb-all", form).onclick = () => restoreAll(v, b, () => $("#dlg").close());
    const orphan = x => x.kind === "piece" && !x.exists && !x.book.exists;     // its book must come back first

    const mark = () => {
      $$(".lb-i", tree).forEach(o => o.setAttribute("aria-selected", +o.dataset.n === sel));
      const o = $(`#lb-o${sel}`, tree);
      if (o) { tree.setAttribute("aria-activedescendant", o.id); o.scrollIntoView({block: "nearest"}); }
      else tree.removeAttribute("aria-activedescendant");
      const x = shown[sel];
      if (x) {
        const where = x.kind === "poem" ? x.series : x.kind === "book" ? plural(x.pieces, "piece") : x.book.title;
        line.textContent = `“${x.title}” · ${where} · ${x.exists ? "in the library now" : "not in the library now"}`
          + (orphan(x) ? `. Restore the book “${x.book.title}” first.` : "");
      } else line.textContent = "";
      replace.hidden = !x?.exists;
      go.textContent = x && !x.exists ? "Restore" : "Restore a copy";
      go.disabled = !x || orphan(x);
    };
    const draw = () => {
      const key = shown[sel]?.key, hit = new Set(rows.filter(x => matches(q.value, x.hay)));
      for (const x of [...hit]) if (x.kind === "piece") hit.add(x.book);         // a piece shows under its book
      shown = rows.filter(x => hit.has(x));
      sel = Math.max(0, shown.findIndex(x => x.key === key));
      let out = "", group = null, series = null;
      shown.forEach((x, i) => {
        const g = x.kind === "poem" ? "Poems" : "Books";
        if (g !== group) { group = g; series = null; out += `<div class="lb-g" role="presentation">${g}</div>`; }
        if (x.kind === "poem" && x.series !== series) { series = x.series; out += `<div class="lb-s" role="presentation">${esc(series)}</div>`; }
        out += `<div class="lb-i${x.kind === "book" ? " book" : ""}" role="option" id="lb-o${i}" data-n="${i}" aria-selected="false">`
          + `<span class="t">${esc(x.title)}</span>${x.exists ? "" : `<span class="h">not in the library now</span>`}</div>`;
      });
      tree.innerHTML = out || `<p class="lb-none">${rows.length ? `Nothing matches “${esc(q.value.trim())}”.` : "This backup holds no poems or books."}</p>`;
      mark();
    };
    const move = to => { if (shown.length) { sel = Math.max(0, Math.min(shown.length - 1, to)); mark(); } };

    q.oninput = draw;
    form.addEventListener("keydown", e => {
      if (e.target !== q && e.target !== tree) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); move(sel + (e.key === "ArrowDown" ? 1 : -1)); }
      else if (e.target === tree && (e.key === "Home" || e.key === "End")) { e.preventDefault(); move(e.key === "Home" ? 0 : shown.length - 1); }
      else if (e.key === "Enter") { e.preventDefault(); if (!go.disabled) go.focus(); }        // never a restore by itself
    });
    tree.onclick = e => { const o = e.target.closest(".lb-i"); if (o) { sel = +o.dataset.n; mark(); tree.focus(); } };
    replace.onclick = async () => {
      const x = shown[sel];
      if (!x?.exists) return;
      if (!confirm(`“${x.title}” as it is now goes to the trash (${x.kind === "poem" ? "Poems" : "Books"}/.trash), and the copy from ${at(b.when)} takes its place.`)) return;
      replace.disabled = go.disabled = true;
      try { await restoreOne(v, b, x, "replace"); $("#dlg").close(); }
      catch (e) { toast(e.message, true); }
      finally { replace.disabled = false; mark(); }
    };
    draw();
  }

  async function restoreOne(v, b, x, mode) {
    const ref = x.kind === "piece" ? {book: x.book.id, file: x.file} : x.id;
    const r = await api("/api/backups/restore", {name: b.name, kind: x.kind, ref, mode});
    state.home = null;
    const said = mode === "copy" ? `Restored a copy of “${x.title}”` : mode === "replace" ? `Replaced “${x.title}” with the copy from ${at(b.when)}`
      : `Restored “${x.title}”`;
    toast(said);
    const more = mode === "copy" && r.title && r.title !== x.title ? ` as “${r.title}”` : "";
    v.newsPath = "";
    v.news = `<p class="hint lb-news">${esc(`${said}${more}.${mode === "replace" ? " The one it replaced is in the trash." : ""}`)}&nbsp;<a href="${esc(r.href)}">Open</a></p>`;
    if (v.root.isConnected) paintNews(v);
  }

  /* `confirmed`: what to do once the author says yes (the restore dialog closes; a no leaves it open) */
  async function restoreAll(v, b, confirmed) {
    if (!confirm(`Unpack the backup from ${at(b.when)} into a new folder next to your library? Nothing in your library changes.`)) return;
    confirmed?.();
    v.newsPath = "";
    v.news = `<p class="hint lb-news">Unpacking the backup from ${esc(at(b.when))}…</p>`;
    paintNews(v);
    try {
      const r = await api("/api/backups/restore", {name: b.name, all: true});
      v.newsPath = r.path;
      toast("Backup unpacked");
    } catch (e) { v.news = ""; toast(e.message, true); }
    if (v.root.isConnected) paintNews(v);
  }

  async function useLibrary(path) {
    if (!path || !confirm(`Studio will switch to ${path}. Your current library stays where it is; switch back in Settings → Library.`)) return;
    try { await api("/api/settings", {library: path}); location.reload(); } catch (e) { toast(e.message, true); }
  }

  window.settingsSections.push({id: "backups", html, bind});

  /* ——— Home: one quiet line, only when backups have failed or stopped (B13) ——— */
  window.homeSections.push({id: "backups", render: () => "", bind(root) {
    if (!root) return;
    api("/api/backups/brief").then(r => {
      if (!r?.problem || !root.isConnected) return;
      root.innerHTML = `<p class="lt-home-warn">${esc(r.problem)} <a href="#/settings">Settings → Backups</a></p>`;
      $("a", root).onclick = () => { jump = true; };
    }).catch(() => { /* Home without the line */ });
  }});

  return {sizeText, fold, matches};
})();
