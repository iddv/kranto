// Settings › Overview: every setting's name, where it is, for the
// Overview's search: the pages and their groups, every cap, the rows people look for by name.
import { href } from "../../lib/router";
import { CAP_DEFS } from "./caps";
import { SETTINGS_PAGES } from "./pagedefs";

export interface Found {
  /** the setting's name */
  w: string;
  /** where it is: "Spend › Caps" */
  at: string;
  href: string;
  /** what else the search reads (a key) */
  also?: string;
}

/** the index the Overview searches; every entry opens its page, and its row where there is one */
export function settingsIndex(): Found[] {
  const out: Found[] = [];
  for (const p of SETTINGS_PAGES) {
    out.push({ w: p.title, at: "Settings", href: href("settings/" + p.key) });
    for (const g of p.groups) out.push({ w: g, at: p.title, href: href("settings/" + p.key) });
  }
  for (const c of CAP_DEFS) out.push({ w: c.word, at: "Spend › Caps", href: href("settings/spend", { sel: "ecap:" + c.key }), also: c.field + " cap" });
  out.push({ w: "Provider and key", at: "Watching", href: href("settings/watching", { sel: "ekey" }), also: "claude api openrouter endpoint claude code key" });
  out.push({ w: "Search with", at: "Watching › Live search", href: href("settings/watching", { sel: "esearch" }), also: "live web search exa brave tavily anthropic key search.provider" });
  out.push({ w: "Who searches", at: "Watching › Live search", href: href("settings/watching", { sel: "esearch:callers" }), also: "live search search.callers scout cards" });
  out.push({ w: "Usage reports", at: "Privacy & access", href: href("settings/privacy", { sel: "emode" }), also: "telemetry" });
  out.push({ w: "Automatic updates", at: "System › Updates", href: href("settings/system", { sel: "eauto" }) });
  out.push({ w: "Channel", at: "System › Updates", href: href("settings/system", { sel: "echannel" }), also: "stable rc main" });
  out.push({ w: "Theme", at: "Appearance", href: href("settings/appearance", { sel: "etheme" }), also: "light dark" });
  return out;
}

/** what a search finds: every word of the query in the name, where it is or its key */
export function findSettings(q: string, all: Found[] = settingsIndex()): Found[] {
  const ws = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!ws.length) return [];
  return all.filter((f) => {
    const t = [f.w, f.at, f.also || ""].join(" ").toLowerCase();
    return ws.every((w) => t.includes(w));
  });
}
