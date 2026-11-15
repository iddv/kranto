// The attention budget over a drawn page: what the
// owner is given on the screen, counted in the page as tests/page/contrast.js counts contrast. Called
// as page.evaluate(BUDGET, {phone, allow}) by tests/page/test_browser_budget.py and once a case by the
// functional suite (tests/page/functional/browser.py). It returns every finding: {check, rule, where,
// text, allowed}; allowed is the index of the allowlist entry whose selector the finding's element
// sits in (tests/page/budget_allow.json; a route-only entry is matched by the caller), else -1.
//
// The checks (the design's table):
//   rows        a li.row taller than 36 px (60 on a phone), over 14 words, more than one verb and
//               one quiet control, or its title cut at 1400 (R1)
//   dialog      #dlg over 60 words above its foot, over 3 facts (dt), a preview over 3 lines
//               closed, more than one enabled verb beside Cancel (R2)
//   primary     more than one .btn.primary in the first viewport (R3)
//   fold        more than 7 rows with a verb in the first viewport, 5 on a phone (R4)
//   internal    a uuid, a version, draft:n, ticket #n, brief #n, obs n, web n, #n, a setting
//               key, a price, N tokens, N model calls in a row, a dialog, the band or a toast (R5)
//   twice       a fragment of 12+ characters shown twice, but a state phrase shared by sibling
//               rows (R6)
//   numbers     more than one number in a row (its age aside), more than three in a dialog (R7)
//   fold-words  over 250 words in the first viewport of a list, 150 of a sheet, 40 in the chrome
//               (the top bar, the status bar and the band) (R8)
//   tells       an all-caps label, → or ↗ ending a control, a monospace text outside code, more
//               than one " · " in a row (R9)
//   words       press, ticket, dry, readback, typed fields, ladder, verb, kind, manifest, schema,
//               uuid, daemon, pid and "cub ·" on the screen (R10; the smoke's owner_words checks
//               keys and nulls)
(args) => {
  const phone = !!(args && args.phone);
  const allow = (args && args.allow) || [];
  const H = innerHeight;
  const out = [];
  const shown = (e) => !!e && e.getClientRects().length > 0 && (!e.checkVisibility || e.checkVisibility({ visibilityProperty: true, opacityProperty: true }));
  const words = (s) => String(s || "").split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
  const text = (e) => String((e && e.innerText) || "").replace(/\s+/g, " ").trim();
  const above = (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < H; };
  const name = (e) => {
    const parts = [];
    for (let x = e; x && x !== document.body && parts.length < 3; x = x.parentElement) {
      const id = x.id ? "#" + x.id : "";
      const sel = x.getAttribute && x.getAttribute("data-sel") ? `[data-sel="${x.getAttribute("data-sel")}"]` : "";
      const cls = typeof x.className === "string" && x.className ? "." + x.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      parts.unshift(x.tagName.toLowerCase() + (id || sel || cls));
      if (id) break;
    }
    return parts.join(" > ");
  };
  const allowedAt = (check, e, t) => allow.findIndex((a) => (a.check === check || a.check === "*") && a.sel &&
    (!a.pattern || new RegExp(a.pattern, "u").test(t)) && a.sel.some((s) => { try { return !!(e && e.closest(s)); } catch { return false; } }));
  const find = (check, rule, e, t) => out.push({ check, rule, where: e ? name(e) : "page", text: String(t).slice(0, 160), allowed: allowedAt(check, e, String(t)) });

  const rows = [...document.querySelectorAll("li.row")].filter(shown);
  const quiet = (b) => b.classList.contains("quiet") || b.classList.contains("row-more") || /^[✕×⋯]$/.test(text(b));

  // R1: a row is one line, at most 14 words, one verb and one quiet control, its title whole
  for (const r of rows) {
    const h = r.getBoundingClientRect().height;
    if (h > (phone ? 60 : 36)) find("rows", "R1", r, `${Math.round(h)} px: ${text(r)}`);
    if (words(text(r)) > 14) find("rows", "R1", r, `${words(text(r))} words: ${text(r)}`);
    const btns = [...r.querySelectorAll(".btn, .r-act button, .r-act a")].filter(shown).filter((b, i, a) => a.indexOf(b) === i);
    const loud = btns.filter((b) => !quiet(b)), soft = btns.filter(quiet);
    if (loud.length > 1 || soft.length > 1) find("rows", "R1", r, `${loud.length} verbs and ${soft.length} quiet: ${btns.map(text).join(" | ")}`);
    const t = r.querySelector(".r-title");
    if (!phone && t && shown(t) && t.scrollWidth > t.clientWidth + 1) find("rows", "R1", t, `title cut: ${text(t)}`);
  }

  // R2: a decision dialog is short
  const dlg = document.getElementById("dlg");
  if (shown(dlg)) {
    const foot = dlg.querySelector(".dlg-f, .f, footer, .acts");
    const top = foot ? foot.getBoundingClientRect().top : Infinity;
    let n = 0;
    const walker = document.createTreeWalker(dlg, NodeFilter.SHOW_TEXT);
    for (let x = walker.nextNode(); x; x = walker.nextNode()) {
      const p = x.parentElement;
      if (!p || !shown(p) || (foot && foot.contains(p))) continue;
      const rr = document.createRange(); rr.selectNodeContents(x);
      const b = rr.getBoundingClientRect();
      if (b.height && b.bottom <= top + 1) n += words(x.textContent);
    }
    if (n > 60) find("dialog", "R2", dlg, `${n} words above the action`);
    const dts = [...dlg.querySelectorAll("dt")].filter(shown);
    if (dts.length > 3) find("dialog", "R2", dlg, `${dts.length} facts: ${dts.map(text).join(", ")}`);
    for (const pv of dlg.querySelectorAll(".pd-body, .preview, .k-preview")) {
      const lh = parseFloat(getComputedStyle(pv).lineHeight) || 20;
      if (shown(pv) && pv.getBoundingClientRect().height > lh * 3 + 4 && !pv.closest(".open, [open]")) find("dialog", "R2", pv, "a preview over three lines, closed");
    }
    if (foot) {
      const verbs = [...foot.querySelectorAll("button, a.btn")].filter(shown).filter((b) => !b.disabled && !/^(Cancel|Close|Details|Show all)$/.test(text(b)));
      if (verbs.length > 1) find("dialog", "R2", foot, `${verbs.length} verbs: ${verbs.map(text).join(" | ")}`);
    }
    if ([...dlg.querySelectorAll("dd, p, li")].filter(shown).some((e) => (text(e).match(/\d+(?:[.,:]\d+)*/g) || []).length > 3)) find("numbers", "R7", dlg, "a dialog's line with more than three numbers");
  }

  // R3: one primary in the first viewport (the band's verb is Kranto's own surface, Needs you
  // on a refused key has two, the band's and the one thing's, as the design counts it)
  // with a dialog open, the dialog is the surface (its scrim covers the page)
  const surface = shown(document.getElementById("dlg")) ? document.getElementById("dlg") : document;
  const prim = [...surface.querySelectorAll(".btn.primary")].filter(shown).filter(above).filter((b) => !b.closest("#incident-band"));
  if (prim.length > 1) find("primary", "R3", prim[1], `${prim.length} primaries: ${prim.map(text).join(" | ")}`);

  // R4: at most seven decisions before scrolling
  const acts = rows.filter(above).filter((r) => [...r.querySelectorAll(".r-act .btn, .r-act button, .r-act a")].some(shown));
  if (acts.length > (phone ? 5 : 7)) find("fold", "R4", acts[phone ? 5 : 7], `${acts.length} rows with a verb above the fold`);

  // R5: nothing internal on a row, a dialog, the band or a toast
  const INTERNAL = [
    ["a uuid", /\b[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b/i],
    ["a version", /(?<![\d.])\d+\.\d+\.\d+(?:[.-]?(?:dev|rc|a|b)\d+)?(?:\+g[0-9a-f]+)?\b(?!\.\d)|\bv\d+\.\d+\.\d+/],
    ["a ref", /\bdraft:\d+|\bticket #\d+|\bbrief #\d+|\bobs \d+|\bweb \d+/i],
    ["a #n", /(?<![\w&])#\d+\b/],
    ["a setting key", /\b(?:shell|ingest|grading|projects|maintain|update|chat|ideas|loop|watch|news|invest|telemetry|spend|cubs|publish|intake|gate)\.[a-z_]+(?:\.[a-z_]+)*\b/],
    ["a price", /\$\d+(?:\.\d+)?/],
    ["a token count", /\b\d[\d.,]*\s?[kKM]? tokens?\b/],
    ["model calls", /\b\d+ model calls?\b/],
  ];
  const surfaces = [...rows, ...[dlg, document.getElementById("incident-band"), ...document.querySelectorAll(".toast, #toast")].filter(shown)];
  for (const s of surfaces) {
    const t = text(s);
    for (const [what, re] of INTERNAL) { const m = t.match(re); if (m) find("internal", "R5", s, `${what} (${m[0]}): ${t}`); }
  }

  // R6: every fact once (a state phrase shared by sibling rows aside)
  const scope = [...document.querySelectorAll("#rows, #detail, #dlg, #home")].filter(shown);
  const frags = new Map();
  for (const root of scope) {
    for (const e of root.querySelectorAll("*")) {
      if (!shown(e) || e.closest("button, .btn, [role=button], .toc") || [...e.childNodes].some((c) => c.nodeType === 1 && shown(c) && text(c))) continue;
      for (const f of text(e).split(/ · |\n/).map((x) => x.trim()).filter((x) => x.length >= 12)) {
        if (!frags.has(f)) frags.set(f, []);
        if (!frags.get(f).includes(e)) frags.get(f).push(e);
      }
    }
  }
  for (const [f, es] of frags) {
    if (es.length < 2) continue;
    // siblings of one shape: the same element, parent and grandparent, under one container
    const shape = (e) => [e, e.parentElement, e.parentElement && e.parentElement.parentElement].map((x) => (x ? x.tagName + "." + x.className : "")).join(">");
    const box = (e) => e.parentElement && e.parentElement.parentElement && e.parentElement.parentElement.parentElement;
    const sib = new Set(es.map(shape)).size === 1 && new Set(es.map(box)).size === 1;
    if (!sib) find("twice", "R6", es[1], `said ${es.length} times: ${f}`);
  }

  // R7: a number only when it changes what the owner does
  for (const r of rows) {
    const c = r.cloneNode(true); c.querySelectorAll(".c-age").forEach((x) => x.remove());
    // a path or an address is one fact, whatever digits it holds
    const nums = (text(c).replace(/\S*\/\S*/g, " path ").match(/\d+(?:[.,:]\d+)*/g) || []);
    if (nums.length > 1) find("numbers", "R7", r, `${nums.length} numbers: ${text(r)}`);
  }

  // R8: the first screen is short
  const foldWords = (root) => {
    let n = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let x = walker.nextNode(); x; x = walker.nextNode()) {
      const p = x.parentElement;
      if (!p || !shown(p)) continue;
      const rr = document.createRange(); rr.selectNodeContents(x);
      const b = rr.getBoundingClientRect();
      if (b.height && b.bottom > 0 && b.top < H) n += words(x.textContent);
    }
    return n;
  };
  const list = document.getElementById("rows");
  if (shown(list) && foldWords(list) > 250) find("fold-words", "R8", list, `${foldWords(list)} words above the fold`);
  const sheet = document.getElementById("detail");
  if (shown(sheet) && sheet.getBoundingClientRect().width > 200 && foldWords(sheet) > 150) find("fold-words", "R8", sheet, `${foldWords(sheet)} words above the fold of the sheet`);
  const chrome = [document.getElementById("top"), document.getElementById("bar"), document.getElementById("incident-band")].filter(shown);
  const cw = chrome.reduce((a, e) => a + foldWords(e), 0);
  if (cw > 40) find("fold-words", "R8", chrome[0], `${cw} words in the chrome: ${chrome.map(text).join(" | ")}`);

  // R9: no template chrome
  const own = (e) => [...e.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent).join("").trim();
  for (const e of document.querySelectorAll("body *")) {
    const t = own(e);
    if (!t || !/[\p{L}\p{N}]/u.test(t) || !shown(e)) continue;
    const cs = getComputedStyle(e);
    if (cs.textTransform === "uppercase") find("tells", "R9", e, `all caps: ${t}`);
    if (/mono/i.test(cs.fontFamily) && !e.closest("code, pre, kbd, samp, .xterm, .lines, textarea, input, select")) find("tells", "R9", e, `monospace: ${t}`);
  }
  for (const c of document.querySelectorAll("a, button")) {
    const t = text(c);
    if (shown(c) && /[→↗]$/.test(t)) find("tells", "R9", c, `an arrow on a control: ${t}`);
  }
  for (const r of rows) if ((text(r).match(/ · /g) || []).length > 1) find("tells", "R9", r, `more than one " · ": ${text(r)}`);

  // R10: plain words (what the owner reads: no code span, no field's value)
  const BANNED = /\b(press(?:es|ed|ing)?|tickets?|dry|read-?backs?|typed fields|ladder|verbs?|kinds?|manifests?|schemas?|uuids?|daemons?|pid)\b|\bcubs? ·/gi;
  const live = [...document.querySelectorAll("body *")].filter((e) => shown(e) && own(e) && !e.closest("code, kbd, pre, input, textarea, select, script, style, .xterm"));
  for (const e of live) {
    const t = own(e);
    BANNED.lastIndex = 0;
    const m = t.match(BANNED);
    if (m && !/press release/i.test(t)) find("words", "R10", e, `says ${JSON.stringify(m[0])}: ${t}`);
  }
  return out;
}
