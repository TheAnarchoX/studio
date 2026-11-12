"use strict";
/* The first-run welcome: three short steps in one overlay, each skippable. A classic script after app.js and styles.js.
   showWelcome(info) resolves when the person has finished or skipped; by then the settings file exists. */

async function showWelcome(info) {
  const inApp = !!window.pywebview?.api?.pick_folder;
  const s = info.settings, pick = {
    library: info.env_library ? info.library : s.library, signature: s.signature || "", look: s.default_look, examples: true};
  let looks = [], step = 0;
  try {
    const st = await loadStyles();
    looks = st.looks;
    if (!looks.some(l => l.name === pick.look)) pick.look = st.default_look;
  } catch { /* without looks the third step is left out */ }
  const steps = looks.length ? 3 : 2;
  const root = document.createElement("div");
  root.className = "welcome"; root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-labelledby", "wl-title");
  document.body.appendChild(root);
  const behind = [...document.body.children].filter(el => el !== root && el.id !== "toast");
  behind.forEach(el => el.setAttribute("inert", ""));

  return new Promise(resolve => {
    /* Settings are always saved (that is what ends the first run) and the library is always made; skipping
       everything keeps Studio's own defaults and adds no examples. */
    const finish = async skipAll => {
      $("#wl-next").disabled = true; $("#wl-skip").disabled = true;
      try {
        const body = {create: true, library: pick.library};
        if (pick.signature.trim()) body.signature = pick.signature.trim();
        if (!skipAll) body.default_look = pick.look;
        const saved = await api("/api/settings", body);
        if (saved.library !== info.library) { SD = null; await refreshFonts().catch(() => {}); }   // another folder: its own fonts
        if (pick.examples && !skipAll && steps === 3) await api("/api/examples", {});
      } catch (e) {
        toast(e.message, true); step = 0; paint();
        return;
      }
      behind.forEach(el => el.removeAttribute("inert"));
      document.body.removeChild(root);
      state.home = null;
      resolve();
    };
    const next = () => step + 1 >= steps ? finish(false) : (step++, paint());

    function read() {
      if (step === 0) pick.library = $("#wl-lib").value.trim() || pick.library;
      if (step === 1) pick.signature = $("#wl-sig").value;
      if (step === 2) pick.examples = $("#wl-ex").checked;
    }

    function paint() {
      const last = step + 1 >= steps;
      const copy = [
        ["Where your work lives", "Poems and their artwork are plain files in one folder. Studio makes it if it isn’t there yet.",
          `<label class="label" for="wl-lib">Folder</label><div class="pathrow"><input class="input" id="wl-lib" value="${esc(pick.library)}" spellcheck="false" autocomplete="off"${info.env_library ? " readonly" : ""}>
            ${inApp ? `<button type="button" class="btn" id="wl-pick">Choose…</button>` : ""}</div>
            ${info.env_library ? `<p class="hint">Set by STUDIO_ART in the environment.</p>` : ""}`],
        ["Your name", "New poems and designs are signed with it. You can leave it empty and add it later in Settings.",
          `<label class="label" for="wl-sig">Name</label><input class="input big" id="wl-sig" value="${esc(pick.signature)}" placeholder="Your name" autocomplete="name">`],
        ["A starting look", "Colours and type for your first series. Every look can be changed or replaced in Styles.",
          `<div class="wl-looks" role="radiogroup" aria-label="Starting look">${looks.map(l => `<button type="button" class="wl-look" role="radio" aria-checked="${l.name === pick.look}" data-look="${esc(l.name)}">
            <span class="slide" aria-hidden="true"></span><span class="nm">${esc(l.name)}</span></button>`).join("")}</div>
          <label class="switch wl-ex"><input type="checkbox" id="wl-ex" ${pick.examples ? "checked" : ""}><span>Add a series of examples to try Studio with</span></label>`]][step];
      root.innerHTML = `<div class="wl-card">
        <p class="kicker" aria-live="polite">Step ${step + 1} of ${steps}</p>
        <h1 class="display wl-h" id="wl-title">${copy[0]}</h1><p class="lede">${copy[1]}</p>
        <div class="wl-body">${copy[2]}</div>
        <div class="wl-foot"><button type="button" class="btn quiet" id="wl-back" ${step ? "" : "hidden"}>Back</button><span class="grow"></span>
          <button type="button" class="btn quiet" id="wl-skip">${last ? "Skip and finish" : "Skip"}</button>
          <button type="button" class="btn solid" id="wl-next">${last ? "Finish" : "Continue"}</button></div></div>`;
      $("#wl-back").onclick = () => { read(); step--; paint(); };
      $("#wl-next").onclick = () => { read(); next(); };
      $("#wl-skip").onclick = () => last ? finish(true) : next();
      if (step === 0 && inApp) $("#wl-pick").onclick = async () => { const p = await window.pywebview.api.pick_folder($("#wl-lib").value); if (p) $("#wl-lib").value = p; };
      for (const inp of $$("input.input", root)) inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $("#wl-next").click(); } });
      if (step === 2) {
        const cards = $$(".wl-look", root);
        cards.forEach(c => {
          c.onclick = () => { pick.look = c.dataset.look; cards.forEach(x => x.setAttribute("aria-checked", x === c)); };
          const look = looks.find(l => l.name === c.dataset.look);
          drawLook($(".slide", c), look, 116);
        });
      }
      ($("input.input", root) || $(".wl-look[aria-checked=true]", root))?.focus();
    }
    paint();
  });
}
