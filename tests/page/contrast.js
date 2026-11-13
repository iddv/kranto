// The WCAG contrast of every visible text on the page against what is drawn under it
// (tests/page/test_browser_contrast.py). The foreground is the text's colour with the opacity of it
// and its ancestors; the background is the colours of the element and its ancestors composited
// down to the page's canvas. Text under 4.5:1 (3:1 at 24 px, or 18.66 px bold) is returned, once
// per (selector, colours). A disabled control is exempt (WCAG 1.4.3), as is text over an image.
() => {
  const parse = (s) => {
    const m = s && s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const over = (top, bot) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + bot[i] * (1 - a)).concat(1); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = (c) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const canvas = () => {
    const c = parse(getComputedStyle(document.documentElement).backgroundColor);
    if (c && c[3] > 0) return c;
    const b = parse(getComputedStyle(document.body).backgroundColor);
    return b && b[3] >= 1 ? b : [255, 255, 255, 1];
  };
  const under = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== "none" && !/^linear-gradient/.test(s.backgroundImage)) return null;
      const c = parse(s.backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let base = canvas();
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
  const name = (el) => {
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(s + "#" + e.id); break; }
      const cls = Array.from(e.classList).filter((c) => !c.startsWith("svelte-")).slice(0, 2);
      if (cls.length) s += "." + cls.join(".");
      parts.unshift(s);
    }
    return parts.join(" > ");
  };
  const els = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) if (n.textContent.trim() && n.parentElement) els.add(n.parentElement);
  const low = [], seen = new Set();
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || el.closest("svg, script, style, noscript, [aria-hidden=true], [hidden]")) continue;
    if (el.closest("[disabled], [aria-disabled=true]")) continue;
    let fg = parse(s.color);
    const bg = under(el);
    if (!fg || !bg) continue;
    let o = 1;
    for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity);
    if (o < 0.05) continue;
    fg = over([fg[0], fg[1], fg[2], fg[3] * o], bg);
    const cr = ratio(fg, bg), size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight, 10) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (cr >= need) continue;
    const key = name(el) + fg + bg;
    if (seen.has(key)) continue;
    seen.add(key);
    low.push({ el: name(el), text: (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 50), ratio: Math.round(cr * 100) / 100, need, fg: hex(fg), bg: hex(bg) });
  }
  return low;
}
