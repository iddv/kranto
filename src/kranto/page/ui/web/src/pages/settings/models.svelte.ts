// Settings › Watching › Models (the server's /api/settings/models): one row per role (the Judge, the
// Reasoner): what it calls now, or a choice not saved yet. Its pane is the choice from the one
// catalog below, the judge's gate, and Save: nothing is written until Save. No prices: a price is
// a fact about one provider on one day (the owner's ruling, 2026-10-09). The tiers take the
// router's names when the endpoint routes ("anthropic/" and a dotted version), else the API's.
import { dt, rel } from "../../lib/format";

export const AFK_MODELS = "/api/settings/models";

export interface CatModel {
  id: string;
  router: string;
  name: string;
  note: string;
}
/** the models offered (a new model is one line here): the API's id, the router's name, its
 * label, what it is for */
export const CATALOG: readonly CatModel[] = [
  { id: "claude-haiku-5-5", router: "anthropic/claude-haiku-5.5", name: "Haiku 5.5", note: "fastest and lightest: high-volume judging, short checks and summaries" },
  { id: "claude-sonnet-5-5", router: "anthropic/claude-sonnet-5.5", name: "Sonnet 5.5", note: "balanced: writing and reasoning" },
  { id: "claude-opus-5-5", router: "anthropic/claude-opus-5.5", name: "Opus 5.5", note: "strongest for long, careful work; slower" },
  { id: "claude-fable-5-1", router: "anthropic/claude-fable-5.1", name: "Fable 5.1", note: "the largest and slowest, for the hardest reasoning" },
  { id: "claude-sonnet-5", router: "anthropic/claude-sonnet-5", name: "Sonnet 5", note: "the previous Sonnet" },
  { id: "claude-haiku-4-5-20251001", router: "anthropic/claude-haiku-4.5", name: "Haiku 4.5", note: "the previous Haiku" },
];
export interface AfkRole {
  role: string;
  name: string;
  model: string;
  does?: string;
  setting?: string | null;
  gate?: number | null;
  gate_note?: string | null;
}
export interface AfkModels {
  roles: AfkRole[];
  routed: boolean;
  /** where the watcher's calls go (the provider's URL); before 0.3.84 llm.base_url, which
   * stays OpenRouter's when the Claude API is chosen */
  base_url: string;
  config: string;
  // what the metered client uses (the server's providers.in_use); absent before 0.3.84
  provider?: string;
  label?: string;
  endpoint?: string | null;
  last_call?: { provider: string; model: string; at: string } | null;
}

/** the watcher's provider in words, as the client uses it: "Claude API (https://api.anthropic.com)" */
export const watchingVia = (d: AfkModels): string =>
  d.label ? d.label + (d.endpoint ? ` (${d.endpoint})` : "") : d.base_url;
/** the ledger's newest call: which provider served it, its model, when */
export const lastCall = (c: NonNullable<AfkModels["last_call"]>, now: number = Date.now()): string =>
  `${c.provider}, ${c.model}, ${rel(dt(c.at), now)}`;
export type Role = AfkRole & { default?: string | null; set?: boolean; kind?: string };
/** one role as the page shows it */
export interface Spec {
  key: string;
  group: "Watching";
  role: Role;
  cat: readonly CatModel[];
  opts: [string, string][];
  current: string;
  set: boolean;
  endpoint: string;
  file: string;
}

export const modelEntry = (cat: readonly CatModel[], name: string | null | undefined): CatModel | null =>
  name ? cat.find((m) => m.id === name || m.router === name) || null : null;
export const modelName = (cat: readonly CatModel[], name: string | null | undefined, none?: string): string => {
  const m = modelEntry(cat, name);
  return m ? m.name : name || none || "";
};

/** every role of watching */
export function roleSpecs(d: AfkModels): Spec[] {
  const cat = CATALOG;
  return d.roles.map((role) => {
    const opts: [string, string][] = cat.map((m) => [d.routed ? m.router : m.id, m.name]);
    if (role.model && !opts.some((o) => o[0] === role.model)) opts.unshift([role.model, role.model]);
    return { key: "afk:" + role.role, group: "Watching", role, cat, opts, current: role.model, set: true,
             endpoint: watchingVia(d) + (d.provider === "claude_code" ? "" : ", your model key"), file: d.config };
  });
}

/** a choice not saved yet, by "afk:judge" (and "afk:judge:gate"): kept across redraws and shared
 * by the list (its rows say "changed, not saved") and the pane */
export const PICK = $state<Record<string, string>>({});
export const changed = (x: Spec): boolean =>
  (x.key in PICK && PICK[x.key] !== x.current) ||
  (x.role.gate != null && x.key + ":gate" in PICK && Number(PICK[x.key + ":gate"]) !== Number(x.role.gate));
export const pickOf = (x: Spec): string => (x.key in PICK ? (PICK[x.key] as string) : x.current);
