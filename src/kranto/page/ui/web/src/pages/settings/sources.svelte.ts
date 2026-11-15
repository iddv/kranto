// Settings › Sources and Add source (section 4; WORKSPACE.md 2.5, 2.12): the server's
// /api/sources (every source, grouped as the scout and you left them), one source's page
// (/api/sources/<id>: its fetches, how it is read), the catalog of kinds (/api/catalog) and its
// preview (POST /api/sources/preview: one fetch, nothing saved). Their shapes are generated from
// the server's web/types.py (api/afk.gen.ts). A kind's form (the fields, the topic, its preview) is
// kept here across draws, as the old page kept it.
import type { Catalog, CatalogProvider, Preset, Source, SourceLink, SourcePreview, StatusTopic } from "../../api/afk.gen";
import type { St } from "../../ui/settings";
export type { Catalog, CatalogProvider, Preset, PresetField, Source, SourcePage, Sources } from "../../api/afk.gen";
/** what one fetch found, nothing saved */
export type Preview = SourcePreview;
export { srcSt, SRC_ST } from "./health";

export const SOURCES_API = "/api/sources";
export const CATALOG_API = "/api/catalog";
/** read by the Settings pages for the navigator's "needs you" on Connections */
export const CONNECTIONS_API = "/api/connections";

/* the source list's groups, in the owner's words: [its state, its heading, what it means] */
export const GROUPS: [string, string, string][] = [["proposed", "Proposed", "found by the scout; nothing is watched until you approve it"],
  ["approved", "Watched", "read every run; items are compared with their topics before any model call"],
  ["wildcard", "Wildcards", "unrelated to the topic, watched for the patterns it may share; never approved for you"], ["broad", "No topic", "every item is judged"],
  ["retired", "Retired", "not read; their evidence stays; Watch again undoes it"], ["invalid", "Could not be fetched", "proposed, but empty or unreachable when checked"],
  ["imported", "Imported labels", "names on observations imported from Parallax; never read"]];
/* how a kind is read, in a word */
export const ACCESS: Record<string, string> = { public: "public", login: "login", not_offered: "not offered" };
export const accessWord = (a: string): string => ACCESS[a] || a;

/** topics in words, yours first: "Robotics", "AI developer tooling and LLM tooling",
 * "AI developer tooling, LLM tooling and 2 more" */
export function topicList(xs: Pick<SourceLink, "name" | "kind">[], most = 2): string {
  const o = xs.slice().sort((a, b) => Number(a.kind === "project") - Number(b.kind === "project")).map((x) => x.name);
  if (o.length <= most) return o.length === 2 ? `${o[0]} and ${o[1]}` : o.join(", ");
  return `${o.slice(0, most).join(", ")} and ${o.length - most} more`;
}
/** what a row says of its topics: on a topic's own rows (here), the others it also
 * feeds, or nothing; elsewhere, the topics it feeds, or that it has none */
export function topicWords(s: Pick<Source, "topics" | "group" | "review"> & { found_for?: SourceLink | null }, here?: number | string | null): string | null {
  // a proposal says the topic it was proposed for, a wildcard that it is unrelated to it
  if (s.review === "proposed") {
    const f = s.found_for;
    if (!f || (here != null && String(f.id) === String(here))) return s.group === "wildcard" && f ? "wildcard: unrelated, may carry its patterns" : null;
    return s.group === "wildcard" ? `wildcard for ${f.name}: unrelated, may carry its patterns` : `for ${f.name}`;
  }
  if (here != null) {
    const others = s.topics.filter((x) => String(x.id) !== String(here));
    return others.length ? "also feeds " + topicList(others) : null;
  }
  if (s.topics.length) return topicList(s.topics);
  return s.group === "broad" || (s.group === "wildcard" && s.review === "approved") ? "no topic: every item is judged" : null;
}
/** "muted until 12 Nov", "reads less"; null when it is not muted */
export const dayWord = (s: string | null | undefined): string => (s ? new Date(s).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
export const muteWord = (m: Source["mute"]): string | null => (!m ? null : m.muted_until ? `muted until ${dayWord(m.muted_until)}` : "reads less");
/** a word in any of the fields (the toolbar's search) */
export const match = (q: string | null | undefined, ...fields: (string | null | undefined)[]): boolean =>
  !q || fields.join(" ").toLowerCase().includes(q.trim().toLowerCase());
/** a link from the server's data: http(s), # and relative addresses only (the old module's h()) */
export const safeHref = (v: string | null | undefined): string | null =>
  v && /^(https?:|#|\/|[\w./-]*(\?|#|$))/i.test(v) ? v : null;

/** the list's filters (Filter ▾): the state, the site */
export function srcSelects(sites: string[]): [string, string, [string, string][]][] {
  return [["status", "Status", [["", ""], ["proposed", "proposed"], ["approved", "watched"], ["broad", "no topic"], ["retired", "retired"], ["attention", "needs you"]]],
    ["site", "Site", [["", ""], ...sites.map((s): [string, string] => [s, s])]]];
}
/** the sources the filters let through: a state (or "needs you": failing, paced or needs an
 * account), a site, words */
export const filterSources = (srcs: Source[], q: Record<string, string>): Source[] =>
  srcs.filter((s) => (!q.status || listGroup(s) === q.status || (q.status === "attention" && ["failing", "needs_login", "paced"].includes(s.status)))
    && (!q.site || s.site_name === q.site) && match(q.q, s.label, s.site_name, s.why, s.detail, s.topics.map((t) => t.name).join(" ")));

/** the topic a proposal is approved for: none for a wildcard (every item is judged), else the one
 * it was proposed for; undefined when that is not known (Review it instead) */
export function proposalTopic(s: Source, topics: Pick<StatusTopic, "id" | "name">[] | null): number | null | undefined {
  if (s.group === "wildcard") return null;
  const t = s.topics[0] || (topics ? topics.find((x) => x.name === s.proposed_for) : undefined);
  return t ? t.id : undefined;
}
/** a kind by its key, with its site */
export function findPreset(cat: Catalog, key: string | null | undefined): [CatalogProvider | null, Preset | null] {
  for (const p of cat.providers) for (const s of p.presets) if (s.key === key) return [p, s];
  return [null, null];
}
/** a kind's row in the catalog: its state, how it is read and what it reads */
export function presetWords(s: Preset, cat: Catalog): { st: St; meta: string } {
  const can = s.available, acct = (cat.connected[s.needs || ""] || []).find((a) => a.state === "connected");
  const login = s.access === "login" && can && !acct;
  // the account it is read with is Settings › Accounts' (SRC D5, D7): who it reads as, or where to connect one
  const how = !can && s.access === "login" ? "next update" : s.access === "login" && can ? (acct ? `with your account · connected as ${acct.account}` : "with your account") : accessWord(s.access);
  const st: St = !can ? ["closed", "grey", "Not offered"] : s.access === "login" ? ["open", "blue", "With your account"] : ["check", "green", "Public"];
  return { st, meta: [how, can ? s.blurb + (login ? " Connect it first under Settings › Watching." : "") : s.reason].filter(Boolean).join(" · ") };
}
/** the group a row is listed under on Watch › Sources: a proposal is Proposed, a wildcard too
 * while it waits (SRC D6: the Wildcards group is the watched ones) */
export const listGroup = (s: Pick<Source, "group" | "review">): string => (s.review === "proposed" ? "proposed" : s.group);
/** what the catalog's filter reads of a kind */
export const presetText = (p: CatalogProvider, s: Preset): string => [p.name, s.name, s.blurb, s.reason || "", s.access].join(" ");

/** the preset pane's state: the kind (or the proposal) it is for, the fields typed, the topic,
 * the last preview and its error; kept across draws, made again for another kind */
export interface SourceForm {
  key: string;
  fields: Record<string, unknown>;
  topic: string;
  preview: Preview | null;
  error: string | null;
}
export const FORM = $state<{ f: SourceForm | null }>({ f: null });
/** the form for a kind (preset:<key>) or a proposal (review:<id>), made when another is opened */
export function sourceForm(key: string, fields: Record<string, unknown> | null, topic: string): SourceForm {
  if (!FORM.f || FORM.f.key !== key) {
    FORM.f = { key, fields: { ...(fields || {}) }, topic, preview: null, error: null };
  }
  return FORM.f;
}
/** what a preview (or the scout's test fetch) found, in one line */
export function previewLine(p: Preview | null, v: Source["validation"]): { line: string; sim: number | null | undefined } {
  const sim = p ? p.median_similarity : v.median_similarity;
  const line = p ? `${p.items} items; ${p.recent} in the last 30 days` + (sim != null ? `; similarity to the topic ${sim.toFixed(2)}` : "")
    : `${v.items || 0} items; ${v.recent || 0} in the last 30 days` + (sim != null ? `; similarity to the topic ${Number(sim).toFixed(2)}` : "");
  return { line, sim };
}
