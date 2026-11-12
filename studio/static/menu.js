"use strict";
/* Studio's right-click menu, shared by every view.
   StudioMenu.open(event, items): items are {label, kbd?, act, danger?, disabled?, checked?} or "-" (a divider)
   or {label, items: [...]} for a submenu. */
const StudioMenu = (() => {
  let el = null, sub = null;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function close() { el?.remove(); sub?.remove(); el = sub = null; }

  function build(items, x, y, isSub) {
    const m = document.createElement("div");
    m.className = "ctx" + (isSub ? " sub" : "");
    m.setAttribute("role", "menu");
    m.innerHTML = items.filter(Boolean).map((it, i) => it === "-" ? `<div class="sep" role="separator"></div>`
      : `<button role="menuitem" data-i="${i}" class="${it.danger ? "danger" : ""} ${it.items ? "has-sub" : ""}" ${it.disabled ? "disabled" : ""}>
          <span class="ck">${it.checked ? "✓" : ""}</span><span class="lb">${esc(it.label)}</span><span class="kb">${it.items ? "›" : esc(it.kbd || "")}</span></button>`).join("");
    document.body.appendChild(m);
    const r = m.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 4)) + "px";
    m.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 4)) + "px";
    const list = items.filter(Boolean);
    m.querySelectorAll("button[data-i]").forEach(b => {
      const it = list[+b.dataset.i];
      if (it.items) {
        b.onmouseenter = b.onclick = () => {
          sub?.remove();
          const br = b.getBoundingClientRect();
          sub = build(it.items, br.right - 2, br.top - 5, true);
        };
      } else {
        b.onmouseenter = () => { if (!isSub) { sub?.remove(); sub = null; } };
        b.onclick = ev => { ev.stopPropagation(); close(); it.act?.(); };
      }
    });
    return m;
  }

  function open(ev, items) {
    ev.preventDefault(); ev.stopPropagation();
    close();
    el = build(items, ev.clientX, ev.clientY, false);
    el.querySelector("button:not([disabled])")?.focus({preventScroll: true});
  }

  addEventListener("pointerdown", e => { if (el && !e.target.closest(".ctx")) close(); }, true);
  addEventListener("keydown", e => {
    if (!el) return;
    if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); e.stopPropagation();
      const menu = sub && sub.contains(document.activeElement) ? sub : el;
      const bs = [...menu.querySelectorAll("button:not([disabled])")], i = bs.indexOf(document.activeElement);
      bs[(i + (e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length]?.focus();
    }
  }, true);
  addEventListener("blur", close);
  addEventListener("resize", close);
  addEventListener("wheel", close, {passive: true});
  return {open, close};
})();
