// A cub's page, drawn by the core from its manifest (mock D's #newsletter, #toot): the helpers the page, its sheet and the confirm share. A cub gives data and the core
// gives pixels: a list is its read's groups, an object's words come from its card schema, an
// action's input from its declared fields, a ticket's read-back from the kind's typed fields.
import { href } from "../lib/router";
import type { ActionDecl, FeatureRow, ListDecl } from "./index";

/** a cub's page: #/cub/<id>, with the list (list=), the sheet (sel=) */
export const cubHref = (id: string, q: Record<string, string | null | undefined> = {}): string => href("cub/" + id, q);
/** the crumb above a cub's page: Post, where its asks wait (#/cubs itself lands on Post) */
export const POST_CRUMB = { to: "post", w: "Post" };
/** a cub's action: POST /api/f/<id>/act/<verb> */
export const actPath = (kind: string): string => {
  const [fid, verb] = kind.split(".", 2);
  return `/api/f/${fid}/act/${verb}`;
};

/** a field of an object by its key, a dotted path into it (thesis.catalyst) */
export function at(o: unknown, key: string | null | undefined): unknown {
  if (!key) return undefined;
  let v: unknown = o;
  for (const k of key.split(".")) {
    if (v == null || typeof v !== "object") return undefined;
    v = (v as Record<string, unknown>)[k];
  }
  return v;
}

/** an object's cites, from its origin field: [{label, kind, id, title, url, date}] or ["obs 5"];
 * the same cite twice is one, with how many times it was named (an issue names a brief per item),
 * and a News brief ({kind: "brief", id}) is "News brief 5", its page */
export interface Cite {
  label: string;
  obs: number | null;
  brief: number | null;
  url: string | null;
  title: string;
  date: string;
  n: number;
}
export function citesOf(v: unknown): Cite[] {
  if (!Array.isArray(v)) return [];
  const out: Cite[] = [];
  for (const x of v.slice(0, 200)) {
    let c: Cite;
    if (typeof x === "string") {
      const m = /^obs (\d+)$/.exec(x);
      c = { label: x, obs: m ? Number(m[1]) : null, brief: null, url: null, title: "", date: "", n: 1 };
    } else {
      const o = (x || {}) as Record<string, unknown>;
      const id = typeof o.id === "number" ? o.id : null;
      const brief = o.kind === "brief" && id != null ? id : null;
      const label = brief != null ? `News brief ${brief}` : String(o.label || o.kind || "");
      const url = typeof o.url === "string" && /^https?:\/\//i.test(o.url) ? o.url : null;
      c = { label, obs: o.kind === "obs" || /^obs /.test(label) ? id : null, brief, url, title: String(o.title || ""), date: String(o.date || ""), n: 1 };
    }
    const same = out.find((y) => y.label === c.label && y.url === c.url && y.obs === c.obs && y.title === c.title);
    if (same) same.n += 1;
    else if (out.length < 20) out.push(c);
  }
  return out;
}

/** the objects of a list's read, by its groups (a group is a key of the read's answer) */
export function groupsOf(l: ListDecl, data: unknown): { key: string; word: string; tone?: ListDecl["groups"][number]["tone"]; items: Record<string, unknown>[] }[] {
  const d = (data || {}) as Record<string, unknown>;
  const gs = l.groups.length ? l.groups : [{ key: "items", word: l.word }];
  return gs.map((g) => ({ ...g, items: (Array.isArray(d[g.key]) ? d[g.key] : []) as Record<string, unknown>[] }));
}

/** an object's open ticket, as the cub's read gives it ({ticket: {id, state}} or {ticket: id}) */
export function ticketOf(o: Record<string, unknown>): number | null {
  const t = o.ticket;
  if (typeof t === "number") return t;
  if (t && typeof t === "object" && (t as { state?: string }).state === "needs_confirm") return Number((t as { id: number }).id);
  return null;
}

/** the field an action's subject is passed in: newsletter_issue → issue_id, topic → topic_id */
export function subjectField(f: Pick<FeatureRow, "id">, a: Pick<ActionDecl, "subjects">): string | null {
  const s = a.subjects[0];
  if (!s) return null;
  return (s.startsWith(f.id + "_") ? s.slice(f.id.length + 1) : s) + "_id";
}

export const actionsOf = (f: FeatureRow): ActionDecl[] => f.manifest.actions || [];
/** whether an action's switch is on (Action.when names one of the feature's true-or-false
 * settings): an action that names none is always offered */
export const actionOn = (f: FeatureRow, a: Pick<ActionDecl, "when">): boolean =>
  !a.when || (f.settings || []).find((s) => s.key === a.when)?.value === true;
/** the head's verbs (Action.place head: a feature's Stop), never one that can only refuse (UIBUGS
 * B1: a Run now while its feature is off) */
export const headActions = (f: FeatureRow): ActionDecl[] => {
  // Stop while it runs, Resume while its mode says it is halted, never both
  const halted = /halted/.test(f.mode);
  // a feature that is off refuses every action ("Newsletter is off", 409): its head offers none
  if (!f.enabled) return [];
  return actionsOf(f).filter((a) => a.place === "head" && a.doors.includes("ui") && actionOn(f, a) && !(a.kind.endsWith(".resume") && !halted) && !(a.kind.endsWith(".stop") && halted));
};
export const actionOf = (f: FeatureRow, kind: string): ActionDecl | null => actionsOf(f).find((a) => a.kind === kind) || null;

/** the words of what a cub may do (the About sheet and the install dialog: the manifest in words) */
/** a manifest's kind in words: "emails.create_draft" is "emails create draft" (the
 * About sheet listed the ids) */
export const kindWords = (k: string): string => k.replace(/[._]+/g, " ").trim();
export function permissionWords(m: Record<string, unknown>): [string, string][] {
  const out: [string, string][] = [];
  const reads = (m.reads as string[] | undefined) || [];
  if (reads.length) out.push(["Reads", reads.join(", ")]);
  const ev = (m.events as { subscribe?: { kind: string; min_trust: string }[] } | undefined)?.subscribe || [];
  if (ev.length) out.push(["Listens", ev.map((s) => `${kindWords(s.kind)}${s.min_trust !== "unreviewed" ? ` (${s.min_trust} and up)` : ""}`).join(", ")]);
  const model = m.model as { tiers?: string[]; purposes?: string[]; monthly_usd?: number | null } | undefined;
  if (model && model.tiers && model.tiers.length) out.push(["Model", `the ${model.tiers.join(" or ")} tier, through the metered client with no tools, its own line on Settings › Spend; ${model.monthly_usd == null ? "no cap of its own" : "a cap of its own"}`]);
  const search = (m.search as string[] | undefined) || [];
  if (search.length) out.push(["Searches", search.join(", ") + ", under its own name, no page fetching"]);
  const hosts = ((m.http as { hosts?: string[] } | undefined)?.hosts) || [];
  // a listed name allows its subdomains too (bears_cub.grants.host_allowed): say so
  if (hosts.length) out.push(["Calls", `${hosts.join(", ")} and ${hosts.length > 1 ? "their" : "its"} subdomains, without your credentials`]);
  const broker = (m.broker as Record<string, string[]> | undefined) || {};
  for (const [svc, ops] of Object.entries(broker)) out.push(["Through Kranto", `${svc}: ${ops.map(kindWords).join(", ")}, with your credential, which it never sees; every call logged`]);
  const req = (m.requests as string[] | undefined) || [];
  if (req.length) out.push(["Asks you", req.map(kindWords).join(", ") + ": each one waits for your approval on the page"]);
  return out;
}
export const CANNOT = "It cannot pay, post, trade or send by itself, read a key, reach the network on its own, read another feature's data, grade a card, or change a setting that is not its own.";

// -- installed cubs (the server's /api/cubs,) --------------------------------------

export const CUBS_API = "/api/cubs";
/** a cub's line: its registry state (installed, paused, removed: the core's word), the owner's
 * switch (enabled), the kinds that are live, whether its files hash to its pin */
export interface CubLine {
  id: string;
  title: string;
  version: string;
  trust: string;
  state: "installed" | "paused" | "removed";
  enabled: boolean;
  mode: string;
  live: string[];
  source: { kind: string; path?: string; url?: string; ref?: string | null; sha?: string | null };
  installed_at: string | null;
  pinned: boolean;
  tree_ok: boolean;
  /** an update staged and waiting for the owner; needs and adds from the server 0.5.11 (what it may now do);
   * why it waits for a press from 0.5.15 ("asks for one more permission") */
  update: { version: string | null; sha: string | null; job: string; needs?: "house" | "confirm" | null; adds?: string[]; why?: string | null } | null;
  /** its last update applied, from the server 0.5.15: by itself (cubs.auto_update) or by you */
  updated?: { version: string | null; at: string; by: "itself" | "you" } | null;
  paused: { note: string | null } | null;
  /** its source folder is gone, so it gets no updates (the server 0.6.0.dev5+,):
   * the words and the command that points it elsewhere */
  source_gone?: { path: string; words: string; fix: string } | null;
  tickets_open: number;
  /** what it asks you now (the server 0.6.0.dev16+, SEND) */
  asks?: number;
  spend: { month_usd: number; cap_usd: number | null; calls_today: number; calls_per_day: number };
}
export interface CubsList { cubs: CubLine[]; enabled: boolean; stop_file: boolean; limits_mode: string; sandbox: boolean }
export interface CubDetail extends CubLine {
  words: [string, string][];
  grants: { requests?: string[] };
  inventory: { findings: { level: string; text: string }[] } | null;
}
/** a fetch job (an add or an update), as the install sheet polls it */
export interface CubJob {
  id: string;
  kind: "add" | "update" | "remove";
  state: string;
  error?: string | null;
  needs?: "house" | "confirm";
  cub?: {
    id: string;
    title: string;
    version: string;
    trust: string;
    sha: string | null;
    source: { kind: string; path?: string; url?: string; ref?: string | null };
    inventory: { files: number; bytes: number; licence: string; findings: { level: string; text: string }[] };
    words: [string, string][];
    delta?: { added: Record<string, string[]>; removed: Record<string, string[]>; grown: boolean; high_trust: boolean; same: boolean };
    diff?: { counts: { added: number; removed: number; changed: number } };
  };
}
/** a job still working: the sheet asks again */
export const JOB_WORKING = ["queued", "fetching", "fetched", "inspected", "placing", "placed", "pinned"];
export const cubPath = (id: string, verb = ""): string => `${CUBS_API}/${id}${verb ? "/" + verb : ""}`;

/** a read-back value that is a text to read (a body, a post): more than one line or longer
 *  than a line holds; the confirm shows it as a block of text, never as markup */
export const isText = (v: string): boolean => v.includes("\n") || v.length > 160;
/** how much of a text the confirm shows before "Show all" (Confirm waits for the rest) */
export const TEXT_SHOWN = 2000;

/** a read-back on one line, for a list row: a text cut to its start */
export const readbackLine = (rb: [string, string][]): string =>
  rb.map(([, v]) => (isText(v) ? v.replace(/\s+/g, " ").slice(0, 80) + "…" : v)).join(" · ");

/** an approval of a kind, in words: what for real does, and what practice does instead */
export function modeWords(kind: string, live: boolean): string {
  const [does, nothing] = kind.startsWith("send.") ? ["sends it", "sends nothing"]
    : kind.startsWith("post.") ? ["posts it", "posts nothing"] : ["does it", "does nothing"];
  return live ? `for real: approving it ${does} now` : `practice: approving it ${nothing}`;
}

/** the word of a cub's ask button (its first kind's, as the server says it: "Send", "Post toot");
 * from an older server, the kind's own verb (send.*: Send, post.*: Post), else Approve */
export function askVerb(f: Pick<FeatureRow, "manifest">, schemas: Record<string, { button?: string }> | null | undefined): string {
  const k = (f.manifest.requests || [])[0];
  return (k && schemas?.[k]?.button) || (k?.startsWith("send.") ? "Send" : k?.startsWith("post.") ? "Post" : "Approve");
}
