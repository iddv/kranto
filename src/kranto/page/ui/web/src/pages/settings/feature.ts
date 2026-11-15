// Settings › <Feature>: every feature and cub has its own Settings page at
// #/settings/<id>, generated from its manifest in the eight pages' shape. What the page draws,
// as data: its On and off row, its settings in their groups, Advanced, its caps (Spend), the
// accounts it uses. The page (FeaturePage.svelte) and the sheet (FeaturePane.svelte) draw this.
import type { FeatureRow, SettingRow } from "../../features/index";
import { SET_ST, type St } from "../../ui/settings";

/** the address of a feature's own page: News is a door, any other a cub page */
export const featureHref = (f: Pick<FeatureRow, "id">): string => (f.id === "news" ? "#/news" : `#/cub/${f.id}`);
/** a feature's Settings page */
export const settingsPath = (id: string): string => `settings/${id}`;

/** a key's words: its declared words without a null's note, else its name */
export function keyWord(f: Pick<FeatureRow, "id">, r: SettingRow): string {
  const w = (r.words || r.key.slice(f.id.length + 1).replace(/[._]/g, " ")).replace(/\s*\(null: [^)]*\)/, "");
  return w.charAt(0).toUpperCase() + w.slice(1);
}
/** a value in words: "no cap", "none", "every topic", "On" */
export function valueWords(r: SettingRow, topics: { id: number; name: string }[] = []): string {
  const v = r.value === undefined ? r.default : r.value;
  if (r.type === "bool") return v ? "On" : "Off";
  if (v == null || v === "") return r.type === "usd" ? "no cap" : "not set";
  if (r.type === "topics") {
    const ids = Array.isArray(v) ? v.map(Number) : [];
    return ids.length ? ids.map((i) => topics.find((t) => t.id === i)?.name || `topic ${i}`).join(", ") : "every topic";
  }
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  if (r.type === "usd") return `$${Number(v).toFixed(2)}`;
  return String(v);
}
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
/** a row's state word (default · set · by hand) */
export function stateOf(r: SettingRow): St {
  if (r.by_hand) return SET_ST.hand;
  return r.value === undefined || r.value === null || same(r.value, r.default) ? SET_ST.dflt : SET_ST.set;
}

export interface FeatureGroups {
  /** <id>.enabled: the switch in On and off */
  on: SettingRow | null;
  /** its settings by group heading, in the order the manifest declares them */
  groups: { word: string; rows: SettingRow[] }[];
  /** under the Advanced fold: the keys marked advanced, and every key written by hand */
  advanced: SettingRow[];
  /** the keys that cap its spend (manifest.spend.caps): drawn under Spend */
  caps: SettingRow[];
}
export function groupsOf(f: FeatureRow): FeatureGroups {
  const rows = f.settings || [];
  const capKeys = Object.keys(f.manifest.spend?.caps || {});
  const on = rows.find((r) => r.key === `${f.id}.enabled`) || null;
  const out: FeatureGroups = { on, groups: [], advanced: [], caps: [] };
  const by = new Map<string, SettingRow[]>();
  for (const r of rows) {
    if (r === on) continue;
    if (capKeys.includes(r.key)) out.caps.push(r);
    else if (r.advanced || r.by_hand) out.advanced.push(r);
    else {
      const w = r.group || `${f.title}'s settings`;
      if (!by.has(w)) by.set(w, []);
      by.get(w)!.push(r);
    }
  }
  out.groups = [...by.entries()].map(([word, rs]) => ({ word, rows: rs }));
  return out;
}
/** where a per-topic key is set, in words */
export function perTopicWhere(f: Pick<FeatureRow, "id">): string {
  return f.id === "news" ? "set per topic under News › Topics" : "set per topic on its page";
}
/** a feature's state in one line, for Settings' Features group: "on · live · 1.2.0 · ran Mon 08:00 ok" */
export function featureLine(f: FeatureRow): string {
  const run = f.last_run ? `ran ${(f.last_run.finished_at || "").slice(5, 16).replace("T", " ")} ${f.last_run.status}` : null;
  const spent = f.spend && f.spend.month_usd ? `$${f.spend.month_usd.toFixed(2)} this month` : null;
  return [f.enabled ? "on" : "off", f.enabled ? f.mode : null, f.trust === "first-party" ? null : f.version, run, spent].filter(Boolean).join(" · ");
}
/** a feature's glyph's wash, by its kind (the cub page's tglyph washes) */
export const KIND_WASH: Record<string, string> = { post: "blue", watch: "blue", send: "violet", money: "green", book: "amber", make: "red" };
/** a cub's keys Kranto holds for it (cubs.<id>.*), and the shell's two switches */
export const CORE_CAPS: [string, string][] = [["monthly_usd", "Model calls and searches a month"], ["calls_per_day", "Calls through Kranto and web calls a day"], ["tickets_per_day", "Asks of a kind a day"]];
