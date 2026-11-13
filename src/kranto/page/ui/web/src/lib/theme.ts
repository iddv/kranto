/* Appearance (UI-v4.md 1.2, AP): two choices, apart, kept in this browser's localStorage (the
   only things the page ever stores) and applied to <html>, as static/theme.js also does before
   the first paint:
   - the base, THEME_KEY: auto follows the OS; light and dark set html[data-theme];
   - the sidebar theme, LOOK_KEY: html[data-look] (static/looks.css); none is the lavender default.
   A custom theme keeps its five colours and the tokens worked out from them under
   LOOK_CUSTOM_KEY; they are set on <html> as --c-*, which looks.css reads. The header's ◐, the
   palette's theme commands and Settings › Appearance all go through here. */
export type Base = "auto" | "light" | "dark";
/** a custom theme's five colours */
export interface Colours {
  side: string;
  active: string;
  text: string;
  accent: string;
  badge: string;
}
export interface Custom {
  in: Colours;
  vars: Record<string, string>;
}

const THEME_KEY = "kranto.theme";
const LOOK_KEY = "kranto.look";
const LOOK_CUSTOM_KEY = "kranto.look.custom";
export const LOOKS: [string, string, string][] = [["kranto", "Kranto", "the lavender default"], ["plum", "Plum", "deep purple, a bright blue highlight"], ["paper", "Paper", "a clean white sidebar, blue accent"],
  ["harbor", "Harbor", "deep navy, sky blue"], ["reef", "Reef", "teal, pale aqua"], ["fern", "Fern", "forest green, leaf"], ["clay", "Clay", "warm terracotta, sand"],
  ["graphite", "Graphite", "charcoal and mint"], ["rosewood", "Rosewood", "dusky rose, blush"], ["brass", "Brass", "slate and gold"], ["midnight", "Midnight", "near-black, violet"],
  ["contrast", "High contrast", "black and white, AAA text"]];
const html = (): HTMLElement => document.documentElement;
export function themeNow(): Base {
  try { return (localStorage.getItem(THEME_KEY) as Base | null) || "auto"; } catch { return "auto"; }
}
export function setTheme(t: Base): void {
  try { if (t === "auto") localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, t); } catch { /* storage off: this page only */ }
  if (t === "auto") html().removeAttribute("data-theme"); else html().setAttribute("data-theme", t);
}
const deviceDark = (): boolean => typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
export const isDark = (): boolean => {
  const t = html().getAttribute("data-theme");
  return t ? t === "dark" : deviceDark();
};
/** what ◐ and the palette's Switch to light/dark set: the other scheme, and Auto again whenever
 * that is the device's own, so a press never drops Auto for good (QA B18, the owner's B2: Auto,
 * then ◐, stayed dark after the device's evening switch) */
export function flipTo(): Base {
  const want = isDark() ? "light" : "dark";
  return (want === "dark") === deviceDark() ? "auto" : want;
}
/** the words for a choice once made: "Dark", "Auto: follows your device" */
export const baseWords = (t: Base): string => (t === "auto" ? `Auto: follows your device (${deviceDark() ? "dark" : "light"} now)` : t === "dark" ? "Dark, until you switch back" : "Light, until you switch back");
export function customNow(): Custom | null {
  try {
    const c = JSON.parse(localStorage.getItem(LOOK_CUSTOM_KEY) || "null") as Custom | null;
    return c && c.in && c.vars ? c : null;
  } catch { return null; }
}
export const lookChoices = (): [string, string, string][] => (customNow() ? [...LOOKS, ["custom", "Custom", "your five colours"]] : LOOKS);
export const lookNow = (): string => html().getAttribute("data-look") || "kranto";
export const lookName = (id: string): string => (lookChoices().find((x) => x[0] === id) || (LOOKS[0] as [string, string, string]))[1];
export function setLook(id: string): void {
  try { if (id === "kranto") localStorage.removeItem(LOOK_KEY); else localStorage.setItem(LOOK_KEY, id); } catch { /* storage off: this page only */ }
  if (id === "kranto") html().removeAttribute("data-look"); else html().setAttribute("data-look", id);
}
export function applyCustom(vars: Record<string, string> | null): void {
  const st = html().style;
  for (const k of [...st].filter((k) => k.startsWith("--c-"))) st.removeProperty(k);
  for (const [k, v] of Object.entries(vars || {})) if (/^--c-[a-z0-9-]+$/.test(k)) st.setProperty(k, v);
}
/** a custom theme kept, and in use */
export function saveCustom(c: Colours, vars: Record<string, string>): void {
  try { localStorage.setItem(LOOK_CUSTOM_KEY, JSON.stringify({ in: { ...c }, vars })); } catch { /* storage off: this page only */ }
  applyCustom(vars);
  setLook("custom");
}
export function removeCustom(): void {
  try { localStorage.removeItem(LOOK_CUSTOM_KEY); } catch { /* storage off */ }
  if (lookNow() === "custom") setLook("kranto");
  applyCustom(null);
}

/* WCAG 2.1 contrast, worked out as tests/page/test_looks.py does */
const rgbOf = (c: string): number[] => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const hexOf = (a: number[]): string => "#" + a.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
const mixHex = (a: string, b: string, t: number): string => { const x = rgbOf(a), y = rgbOf(b); return hexOf(x.map((v, i) => v + ((y[i] as number) - v) * t)); };
const lumOf = (c: string): number => {
  const [r, g, b] = rgbOf(c).map((v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a: string, b: string): number => { const [x, y] = [lumOf(a), lumOf(b)].sort((p, q) => q - p) as [number, number]; return (x + 0.05) / (y + 0.05); };
const inkOn = (bg: string, pref?: string): string => (pref && contrast(pref, bg) >= 4.5 ? pref : contrast("#ffffff", bg) >= contrast("#000000", bg) ? "#ffffff" : "#000000");
function fitInk(c: string, bgs: string[], need: number, toward: string): string {     // c, moved toward black or white until it reads on every bg
  for (let i = 0; i <= 20; i++) { const x = mixHex(c, toward, i / 20); if (Math.min(...bgs.map((b) => contrast(x, b))) >= need) return x; }
  return toward;
}
/* a custom theme: five colours picked, the rest worked out from them, and the pairs checked as the
   test checks the built-in themes. The accent is darkened for the light base and lightened for the
   dark one as far as AA needs; the sidebar's text and the badge are yours, so they block Save. */
/* its page (TH): tinted neutrals in the sidebar's hue (the accent's, when the sidebar is a grey), at
   the lightness of the built-in themes: [HSL lightness, saturation] a token, on the light base (l)
   and the dark one (d). The accent is fitted to read on these surfaces and on its selected row, which
   is the accent faded into a card until every ink reads on it (#8f5a00: kranto.css's amber, the
   faintest status). tests/page/test_looks.py works the same table out over every hue and checks it. */
type B = "l" | "d";
const CUSTOM_PAGE: Record<B, Record<string, [number, number]>> = {
  l: { bg: [96.5, 45], box: [99.3, 40], subtle: [94.5, 38], head: [93.5, 38], inset: [92.5, 30], border: [84, 26], "border-2": [91, 28], btn: [99.3, 40],
    "btn-border": [80, 22], counter: [88, 45], text: [14, 40], muted: [34, 16], ink3: [37, 13], scroll: [75, 12] },
  d: { bg: [7, 35], box: [9.5, 32], subtle: [12.5, 30], head: [12, 30], inset: [15, 28], border: [22, 24], "border-2": [17, 26], btn: [15, 28],
    "btn-border": [28, 20], counter: [20, 30], text: [94, 25], muted: [76, 14], ink3: [68, 13], scroll: [30, 14] } };
const CUSTOM_SEL: Record<B, [number, string, string[]]> = { l: [0.86, "#000000", ["#8f5a00"]], d: [0.82, "#ffffff", []] };      // the accent's share kept out of a card, where the accent moves, more ink
function hslOf(c: string): [number, number] {
  const [r, g, b] = rgbOf(c).map((v) => v / 255) as [number, number, number], hi = Math.max(r, g, b), lo = Math.min(r, g, b), l = (hi + lo) / 2, d = hi - lo;
  if (!d) return [0, 0];
  const h = hi === r ? ((g - b) / d) % 6 : hi === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, d / (1 - Math.abs(2 * l - 1))];
}
function hslHex(h: number, s: number, l: number): string {
  const k = (n: number): number => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  return hexOf([0, 8, 4].map((n) => (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))) * 255));
}
function customPage(c: Colours): Record<B, Record<string, string>> {
  let [h, s] = hslOf(c.side);
  if (s < 0.12) { [h, s] = hslOf(c.accent); s *= 0.5; }
  const k = Math.min(1, s / 0.45), out = {} as Record<B, Record<string, string>>;
  for (const b of ["l", "d"] as B[]) {
    const P: Record<string, string> = out[b] = {};
    for (const [t, [L, S]] of Object.entries(CUSTOM_PAGE[b])) P[t] = hslHex(h, S / 100 * k, L / 100);
    const [share, toward, more] = CUSTOM_SEL[b], on = ["bg", "box", "subtle", "head", "inset"].map((t) => P[t] as string);
    const ink = [P.text, P.muted, P.ink3, ...more] as string[];
    P.link = toward; P.sel = P.subtle as string;
    fit: for (let i = 0; i <= 20; i++) {
      const x = mixHex(c.accent, toward, i / 20);
      if (Math.min(...on.map((y) => contrast(x, y))) < 4.5) continue;
      for (let j = 0; j < 8; j++) {
        const sel = mixHex(x, P.box as string, share + j * (1 - share) / 8);
        if (Math.min(...[...ink, x].map((y) => contrast(y, sel))) >= 4.5) { P.link = x; P.sel = sel; break fit; }
      }
    }
  }
  return out;
}
/** a check: what is checked, its ratio, the ratio it needs */
export type Check = [string, number, number];
export function customTokens(c: Colours): { vars: Record<string, string>; checks: Check[]; ok: boolean; moved: string[] } {
  const s = c.side, tx = c.text;
  let muted = mixHex(tx, s, 0.3);
  if (contrast(muted, s) < 4.5) muted = fitInk(muted, [s], 4.5, tx);
  let hover = mixHex(s, tx, 0.08);
  if (contrast(tx, hover) < 4.5 || contrast(muted, hover) < 4.5) hover = s;
  const pg = customPage(c), linkL = pg.l.link as string, linkD = pg.d.link as string, selL = pg.l.sel as string, selD = pg.d.sel as string;
  const vars: Record<string, string> = { "--c-side-bg": s, "--c-side-text": tx, "--c-side-muted": muted, "--c-side-hover": hover, "--c-side-active": c.active, "--c-side-active-text": inkOn(c.active, tx),
    "--c-side-bar": contrast(c.active, s) >= 3 ? c.active : tx, "--c-side-border": mixHex(s, tx, 0.15), "--c-side-badge": c.badge, "--c-side-badge-text": inkOn(c.badge),
    "--c-side-dot": ["#2bac76", "#7ef0b0", "#0b5a2a"].reduce((a, b) => (contrast(b, s) > contrast(a, s) ? b : a)), "--c-side-scheme": lumOf(s) < 0.18 ? "dark" : "light",
    "--c-side-scroll": mixHex(s, muted, 0.45),
    "--c-link-l": linkL, "--c-primary-text-l": inkOn(linkL), "--c-sel-l": selL, "--c-link-d": linkD, "--c-primary-text-d": inkOn(linkD), "--c-sel-d": selD };
  for (const b of ["l", "d"] as B[]) for (const t of Object.keys(CUSTOM_PAGE[b])) vars[`--c-${t}-${b}`] = pg[b][t] as string;
  const surf = ["bg", "box", "subtle", "head", "inset"], worst = (fg: string, b: B): number => Math.min(...surf.map((t) => contrast(pg[b][fg] as string, pg[b][t] as string)));
  const checks: Check[] = [["Text on the sidebar", contrast(tx, s), 4.5], ["Muted text on the sidebar", contrast(muted, s), 4.5],
    ["The current row's text", contrast(vars["--c-side-active-text"] as string, c.active), 4.5], ["The badge on the sidebar", contrast(c.badge, s), 3],
    ["The badge's number", contrast(vars["--c-side-badge-text"] as string, c.badge), 4.5],
    ["Text on light pages", Math.min(worst("text", "l"), worst("muted", "l"), worst("ink3", "l")), 4.5], ["Text on dark pages", Math.min(worst("text", "d"), worst("muted", "d"), worst("ink3", "d")), 4.5],
    ["Links on light pages", worst("link", "l"), 4.5], ["Links on dark pages", worst("link", "d"), 4.5],
    ["Button text", Math.min(contrast(vars["--c-primary-text-l"] as string, linkL), contrast(vars["--c-primary-text-d"] as string, linkD)), 4.5],
    ["Text on a selected row", Math.min(...["text", "muted", "ink3", "link"].flatMap((t) => [contrast(pg.l[t] as string, selL), contrast(pg.d[t] as string, selD)])), 4.5]];
  return { vars, checks, ok: checks.every(([, r, n]) => r >= n), moved: [linkL !== c.accent ? "darker on light pages" : null, linkD !== c.accent ? "lighter on dark ones" : null].filter((x): x is string => !!x) };
}
/** a custom theme saved before it had a page of its own (TH): its colours are worked out again
    from the five it keeps, once, as the app loads */
export function upgradeCustom(): void {
  const saved = customNow();
  if (!saved || saved.vars["--c-bg-l"]) return;
  const t = customTokens(saved.in);
  try { localStorage.setItem(LOOK_CUSTOM_KEY, JSON.stringify({ in: saved.in, vars: t.vars })); } catch { /* storage off: this page only */ }
  applyCustom(t.vars);
}
