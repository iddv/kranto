// Settings › Prompts (the server's /api/prompts: additions, overrides, versions). Every prompt Kranto
// sends a model, grouped by its step. A prompt's pane: what it is for and where it runs, its
// placeholders, your additions, the full prompt where it may be replaced (with its diff against
// the default), Reset, its versions, and a preview against a real item (no model call). A checker
// takes additions only: its rules can't be relaxed. Every save is a new version and nothing is
// deleted.
import { plural } from "../../lib/format";
import { drop, put, read, type Read } from "../../lib/reads.svelte";
import { SET_ST, type St } from "../../ui/settings";

/** the server's prompts (absolute: the server serves them next to the page) */
export const PROMPTS_API = "/api/prompts";

/** a version's row */
export interface VersionRow {
  n: number;
  at?: string | null;
  action: string;
  from?: number | null;
  note?: string | null;
  active?: boolean;
  same_as?: number | null;
  chars?: number | null;
  additions_chars?: number | null;
  has_template?: boolean | null;
}
/** one version opened: its text and what differs from the one in use (template_kind: a prompt's) */
export interface VersionView {
  n: number;
  text: string;
  hash: string;
  active_n: number;
  same_as_active: boolean;
  diff: string;
  restorable: boolean;
  why_not?: string | null;
  template_kind?: string;
  additions?: string | null;
}
export interface PromptRow {
  repo: string;
  id: string;
  title: string;
  group: string;
  where: string;
  editable: string;
  subject?: string | null;
  customised: boolean;
  override: boolean;
  additions: boolean;
  default_changed: boolean;
}
export interface Prompts {
  defaults_only: boolean;
  prompts: PromptRow[];
  store: string;
}
export interface Ph {
  name?: string;
  token: string;
  description: string;
  required: boolean;
}
export interface Prompt extends PromptRow {
  purpose: string;
  step: string;
  file: string;
  version: string;
  n: number;
  house_rules: boolean;
  placeholders: Ph[];
  notes?: string[];
  slots?: string[];
  sections?: string[];
  headings?: { additions?: string | null };
  default: string;
  template?: string | null;
  additions_text?: string | null;
  active: string;
  diff?: string | null;
  defaults_only?: boolean;
  versions?: VersionRow[];
  checker_note?: string | null;
  notice?: string | null;
  three_way?: { diff_default: string } | null;
}
export interface Preview {
  id: string;
  text: string;
  chars: number;
  custom: boolean;
  filled?: string[] | null;
  redactions?: { kind: string; count?: number | null }[] | null;
}

/** the shared reads: the registry and one prompt (its id), a minute old at most; a version is
 * read once (every write that changes the version in use drops them) */
export const promptsRead = (): Read<Prompts> => read<Prompts>(PROMPTS_API, 60000);
export const promptRead = (k: string): Read<Prompt> => read<Prompt>(PROMPTS_API + "/" + encodeURIComponent(k), 60000);
export const versionRead = (base: string, n: number): Read<VersionView> => read<VersionView>(base + "/versions/" + n, Infinity);

export const PGROUP_WORD: Record<string, string> = {};
export const groupWord = (g: string): string => PGROUP_WORD[g] || g;
/** a group's heading id: "p-watching" */
export const groupId = (g: string): string => "p-" + g.toLowerCase().replace(/\W+/g, "-");
/** the prompts' groups, in the order the registry lists them */
export const groupsOf = (xs: readonly PromptRow[]): string[] => [...new Set(xs.map((p) => p.group))];
export const promptState = (p: PromptRow): St => p.default_changed ? SET_ST.warn : p.customised ? SET_ST.set : SET_ST.dflt;
export const promptWord = (p: PromptRow): string =>
  p.override ? "your full prompt" + (p.additions ? " and additions" : "") : p.additions ? "your additions" : "the default";
/** a prompt's row: whose text it runs, additions only, the default changed, where it runs */
export const promptMeta = (p: PromptRow): string =>
  [promptWord(p), p.editable === "additions-only" ? "additions only" : null, p.default_changed ? "the default changed since you edited it" : null, p.where].filter(Boolean).join(" · ");
export const cap = (s: string): string => s[0]!.toUpperCase() + s.slice(1);
/** what a prompt takes, in words */
export const takes = (p: Prompt): string =>
  !p.subject || p.subject === "none" ? "no single item" : p.subject === "idea" ? "an idea card" : "a " + p.subject;

/** a prompt's text cut at its placeholders (<<x>>, $X or {x}: as the prompt names them), each
 * marked with its description */
export function hiSegs(text: string | null | undefined, phs: Ph[]): { text: string; ph: boolean; title: string | null }[] {
  const ph = phs.filter((x) => x.token), toks = ph.map((x) => x.token).sort((a, b) => b.length - a.length);
  if (!toks.length) return [{ text: text || "", ph: false, title: null }];
  const re = new RegExp("(" + toks.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "g");
  return String(text || "").split(re).map((s, i) => i % 2 ? { text: s, ph: true, title: ph.find((x) => x.token === s)?.description || null } : { text: s, ph: false, title: null });
}
/** under the placeholders: who fills them, and what a full prompt must keep */
export function phLine(p: Prompt): string {
  const opt = p.placeholders.filter((x) => !x.required).length, secs = p.sections || [];
  return `Filled in by the code when it runs. A full prompt must keep the ${plural(p.placeholders.length - opt, "required one")}${secs.length ? " and its " + secs.map((s) => `<!-- section: ${s} -->`).join(", ") + " part" : ""}.`;
}
/** where your additions go */
export const addTip = (p: Prompt): string =>
  `Inserted under "${(p.headings || {}).additions || "The owner's additions"}"${(p.slots || []).includes("additions") ? " where the prompt has a place for them" : ", at the end of its main part"}. At most 8000 characters; empty is none.`;
/** above the preview: what it is against */
export const previewWhat = (p: Prompt): string =>
  !p.subject || p.subject === "none" ? "This prompt takes no single item: the preview shows it with every placeholder described."
    : `Against a real ${p.subject === "idea" ? "idea card" : p.subject}: exactly what would be sent, secrets removed. No model is called.`;
/** a unified diff's lines, each with its class (add, del, hunk) */
export const diffLines = (text: string | null | undefined): { cls: string | null; text: string }[] =>
  String(text || "").split("\n").map((l) => ({ cls: /^\+(?!\+\+)/.test(l) ? "add" : /^-(?!--)/.test(l) ? "del" : /^@@/.test(l) ? "hunk" : null, text: l + "\n" }));

/** the versions of a prompt, newest first; nothing is ever deleted */
export const VWORD: Record<string, string> = { additions: "additions saved", template: "full prompt saved", reset: "reset to the default", restore: "restored" };
export const versionTitle = (v: VersionRow): string => (VWORD[v.action] || v.action) + (v.from ? ` from v${v.from}` : "");
export const versionMeta = (v: VersionRow): string =>
  [v.note ? `“${v.note}”` : null, v.active ? "in use" : null, v.same_as ? `same as v${v.same_as}` : null, v.chars != null ? plural(v.chars, "character") : null,
    v.additions_chars ? `additions ${v.additions_chars} characters` : null, v.has_template ? "full prompt" : null].filter(Boolean).join(" · ");
/** an opened version in one line: what it is, its hash, against the one in use */
export function versionLine(x: VersionView): string {
  const what = [x.template_kind === "override" ? "your full prompt" : "the default text", x.additions ? "your additions" : "no additions"].join(" and ");
  return [`v${x.n}: ${what}`, `hash ${x.hash}`, x.same_as_active ? `the same text as the version in use (v${x.active_n})` : `differs from the version in use (v${x.active_n})`].join(" · ");
}
/** a preview in one line: its size, whose text, what was filled, what was removed */
export const previewLine = (x: Preview): string =>
  [`${x.chars.toLocaleString("en-GB")} characters`, x.custom ? "your version" : "the default", x.filled && x.filled.length ? "filled: " + x.filled.join(", ") : null,
    (x.redactions || []).length ? "removed: " + (x.redactions || []).map((r) => r.count ? `${r.count} ${r.kind}` : r.kind).join(", ") : "nothing secret found"].filter(Boolean).join(" · ");

/** what is typed and not saved yet, by "id:add", "id:tpl": kept across redraws and selections
 * until its Save (only Save writes) */
export const PDRAFT = $state<Record<string, string>>({});
/** the open version row, by base ("/api/prompts/<id>") */
export const VOPEN = $state<Record<string, number | null>>({});
/** a note being typed, by base + "#" + n + "@" + the version in use */
export const VNOTE = $state<Record<string, string>>({});
/** a preview, by id: the item chosen, the answer or why it failed, busy while it runs */
export const PPREV = $state<Record<string, { subject: string | null; data?: Preview | null; error?: string | null; busy?: boolean }>>({});
/** "What changed in the default" folds kept open across redraws, by id */
export const THREE = $state<Record<string, boolean>>({});

/** after a write: the registry is read again, and this prompt's answer is what it shows */
export function saved(k: string, x: Prompt): void {
  drop(PROMPTS_API, true);
  put(promptBase(k), x);
}
/** a prompt's own path ("/api/prompts/judge"): its reads and its writes */
export const promptBase = (k: string): string => PROMPTS_API + "/" + encodeURIComponent(k);
/** a write changed the version in use: the opened versions are read again */
export const dropVersions = (base: string): void => drop(base + "/versions/");
/** a version restored: its drafts and its opened versions are gone, its row closes */
export function restored(base: string, k: string): void {
  for (const d of Object.keys(PDRAFT)) if (d.startsWith(k + ":")) delete PDRAFT[d];
  dropVersions(base);
  VOPEN[base] = null;
}
