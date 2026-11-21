"use strict";
/* The writing log (spec W1-W6): words written per day, week and month, from GET /api/writing. The page is
   #/writing (showWritingLog); Home gets a short section through window.homeSections. Dates are YYYY-MM-DD strings,
   worked out in UTC so a daylight-saving change never moves a day; weeks start on Monday. The helpers at the top
   touch no DOM, so tests/js/writing.js runs them in node. */
(function (root) {
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ——— dates (no DOM) ——— */
  const parse = iso => { const [y, m, d] = String(iso).split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const fmt = d => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = parse(iso); d.setUTCDate(d.getUTCDate() + n); return fmt(d); };
  const weekStart = iso => addDays(iso, -((parse(iso).getUTCDay() + 6) % 7));
  const monthStart = (iso, back = 0) => { const d = parse(iso); return fmt(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - back, 1))); };
  const monthEnd = iso => { const d = parse(iso); return fmt(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0))); };
  const dm = iso => `${parse(iso).getUTCDate()} ${MON[parse(iso).getUTCMonth()]}`;
  const dayLabel = iso => `${DOW[parse(iso).getUTCDay()]} ${dm(iso)}`;
  const weekLabel = (a, b) => parse(a).getUTCMonth() === parse(b).getUTCMonth()
    ? `${parse(a).getUTCDate()}–${dm(b)}` : `${dm(a)}–${dm(b)}`;
  const monthLabel = iso => `${MON[parse(iso).getUTCMonth()]} ${parse(iso).getUTCFullYear()}`;

  /* ——— sums ——— */
  /* the poems' words and each book's words on the days from start to end */
  function sumRange(data, start, end) {
    let poems = 0;
    const books = {};
    for (const [iso, d] of Object.entries(data.days || {})) {
      if (iso < start || iso > end) continue;
      for (const n of Object.values(d.poems || {})) poems += n;
      for (const [id, n] of Object.entries(d.books || {})) books[id] = (books[id] || 0) + n;
    }
    return {poems, books, total: poems + Object.values(books).reduce((a, b) => a + b, 0)};
  }
  const totals = (data, iso) => sumRange(data, iso, iso);

  function periods(data, mode, count) {
    const today = data.today, out = [];
    for (let i = 0; i < count; i++) {
      let start, end, label;
      if (mode === "weeks") { start = addDays(weekStart(today), -7 * i); end = addDays(start, 6); label = weekLabel(start, end); }
      else if (mode === "months") { start = monthStart(today, i); end = monthEnd(start); label = monthLabel(start); }
      else { start = end = addDays(today, -i); label = dayLabel(start); }
      const s = sumRange(data, start, end);
      out.push({label, start, end, poems: s.poems, books: s.books, total: s.total});
    }
    return out;
  }

  function summary(data) {
    const t = data.today, sum = start => sumRange(data, start, t).total;
    return {today: sum(t), week: sum(weekStart(t)), month: sum(monthStart(t)), year: sum(t.slice(0, 4) + "-01-01")};
  }

  /* How often a book's daily goal was met over the last `span` days, or since its first day when that is later. */
  function goalStats(days, goal, today, span = 30) {
    const keys = Object.keys(days || {}).filter(k => days[k]).sort();
    if (!keys.length) return {met: 0, of: 0, since: null};
    const early = addDays(today, -(span - 1)), first = keys[0];
    const start = first > early ? first : early;
    let met = 0, of = 0;
    for (let d = start; d <= today; d = addDays(d, 1)) { of++; if ((days[d] || 0) >= goal) met++; }
    return {met, of, since: first > early ? first : null};
  }

  const WritingLog = {weekStart, addDays, totals, periods, goalStats, summary};
  root.WritingLog = WritingLog;
  if (typeof document === "undefined") return;

  /* ——— the page and the Home section ——— */
  const W = WritingLog;
  const num = n => Number(n).toLocaleString("en-GB");
  const words = n => `${num(n)} ${n === 1 ? "word" : "words"}`;
  const cell = n => n ? num(n) : `<span class="wl-nil">—</span>`;
  const MODES = [["days", "Days", 30], ["weeks", "Weeks", 12], ["months", "Months", 12]];
  const bookDays = (data, id) => {
    const out = {};
    for (const [iso, d] of Object.entries(data.days)) if (d.books?.[id]) out[iso] = d.books[id];
    return out;
  };
  const load = () => api("/api/writing");

  function table(data, mode) {
    const [, , count] = MODES.find(m => m[0] === mode);
    const rows = W.periods(data, mode, count);
    const poems = rows.some(r => r.poems);
    const books = data.books.filter(b => b.goal || rows.some(r => r.books[b.id]));
    const goalCol = b => mode === "days" && b.goal;       // a daily goal can be met on a day, not in a week
    const top = Math.max(...rows.map(r => r.total), 0);
    const head = `<tr><th scope="col" class="wl-p">${mode === "days" ? "Day" : mode === "weeks" ? "Week" : "Month"}</th>${
      poems ? `<th scope="col" class="wl-n"><span class="wl-t">Poems</span></th>` : ""}${
      books.map(b => `<th scope="col" class="wl-n${goalCol(b) ? " wl-g" : ""}" title="${esc(b.title)}"><span class="wl-t">${esc(b.title)}</span></th>`).join("")}
      <th scope="col" class="wl-n"><span class="wl-t">Total</span></th><th scope="col" class="wl-b"><span class="wl-sr">Share of the largest</span></th></tr>`;
    const body = rows.map(r => `<tr><th scope="row" class="wl-p">${esc(r.label)}</th>${
      poems ? `<td class="wl-n">${cell(r.poems)}</td>` : ""}${
      books.map(b => {
        const n = r.books[b.id] || 0;
        const met = goalCol(b) && n >= b.goal;
        return `<td class="wl-n${goalCol(b) ? " wl-g" : ""}">${met ? `<span class="wl-v">${num(n)}<span class="wl-gm">goal met</span></span>` : cell(n)}</td>`;
      }).join("")}
      <td class="wl-n wl-tot">${cell(r.total)}</td>
      <td class="wl-b" aria-hidden="true"><span class="wl-track"><span class="wl-fill" style="width:${top ? (r.total / top * 100).toFixed(1) : 0}%"></span></span></td></tr>`).join("");
    return `<div class="wl-scroll"><table class="wl-table" aria-label="Words written, ${mode === "days" ? "by day" : mode === "weeks" ? "by week" : "by month"}"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  }

  function booksList(data) {
    if (!data.books.length) return "";
    const month = W.periods(data, "months", 1)[0];
    return `<section class="section wl-sec"><div class="sectionhead"><h2 class="h2">Books</h2></div>
      <ul class="wl-books">${data.books.map(b => {
        let goal = "No daily goal";
        if (b.goal) {
          const g = W.goalStats(bookDays(data, b.id), b.goal, data.today);
          goal = `Daily goal ${words(b.goal)}` + (!g.of ? "" : g.since ? ` · met on ${g.met} of ${g.of} days since ${dm(g.since)}`
            : ` · met on ${g.met} of the last ${g.of} days`);
        }
        return `<li class="wl-book"><a class="wl-bt" href="${bookHash(b.id)}">${esc(b.title)}</a>
          <span class="wl-bm">${esc(goal)}</span><span class="wl-bw">${words(month.books[b.id] || 0)} this month</span></li>`;
      }).join("")}</ul></section>`;
  }

  function poemsLine(data) {
    const month = W.periods(data, "months", 1)[0];
    const ids = new Set();
    for (const [iso, d] of Object.entries(data.days)) if (iso >= month.start && iso <= month.end) for (const id of Object.keys(d.poems || {})) ids.add(id);
    return `<section class="section wl-sec"><div class="sectionhead"><h2 class="h2">Poems</h2></div>
      <p class="wl-line">${month.poems ? `${words(month.poems)} this month, in ${plural(ids.size, "poem")}` : "No words in poems this month."}</p></section>`;
  }

  function renderPage(data) {
    const recorded = Object.keys(data.days).length > 0;
    const saved = pref.get("writing.period", "days");
    const mode = MODES.some(m => m[0] === saved) ? saved : "days";
    const s = W.summary(data);
    app.innerHTML = `<header class="pagehead"><div><p class="kicker">Studio</p><h1 class="display">Writing log</h1></div></header>
      ${recorded ? `<p class="wl-sum">Today ${words(s.today)} · this week ${num(s.week)} · this month ${num(s.month)} · this year ${num(s.year)}</p>
      <div class="wl-ctl"><div class="seg" role="group" aria-label="Period">${MODES.map(([k, l]) =>
        `<button type="button" data-period="${k}" aria-pressed="${k === mode}">${l}</button>`).join("")}</div></div>
      <div id="wl-table">${table(data, mode)}</div>${booksList(data)}${poemsLine(data)}`
      : `<p class="empty">Nothing written yet. Words you add to poems and books are counted here, day by day.</p>`}`;
    $$("[data-period]").forEach(b => b.onclick = () => {
      pref.set("writing.period", b.dataset.period);
      $$("[data-period]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      $("#wl-table").innerHTML = table(data, b.dataset.period);
    });
  }

  root.showWritingLog = async function showWritingLog() {
    state.view = "writing"; setNav("writing"); document.title = "Writing log — Studio";
    try { const data = await load(); if (state.view === "writing") renderPage(data); }
    catch (e) { if (state.view === "writing") app.innerHTML = `<p class="empty">The writing log couldn't be read: ${esc(e.message)}.</p>`; }
  };

  /* ——— Home ——— */
  root.homeSections = root.homeSections || [];
  root.homeSections.push({
    id: "writing",
    render: () => "",                    // drawn by bind once the log has been read
    async bind(el) {
      let data;
      try { data = await load(); } catch { return; }
      if (!el.isConnected || !Object.keys(data.days).length) return;
      const s = W.summary(data);
      const rows = W.periods(data, "days", 14).reverse();
      const top = Math.max(...rows.map(r => r.total), 0);
      el.innerHTML = `<section class="section wl-home"><div class="sectionhead"><h2 class="h2">Writing</h2><a class="btn quiet" href="#/writing">Writing log →</a></div>
        <p class="wl-line">Today ${words(s.today)} · this week ${num(s.week)}</p>
        <div class="wl-days">${rows.map(r => { const t = `${r.label}: ${words(r.total)}`;
          return `<span class="wl-day" role="img" title="${esc(t)}" aria-label="${esc(t)}"><span style="height:${top && r.total ? Math.max(r.total / top * 100, 4).toFixed(1) : 0}%"></span></span>`; }).join("")}</div></section>`;
    },
  });
})(typeof window !== "undefined" ? window : globalThis);
