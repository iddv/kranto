// An action an assistant prepared (the server's GET /api/prepared): under "Ask me
// in the UI" nothing happens until the owner approves it. (the owner, 2026-10-29: "way too
// much … A MASSIVE full text block … No idea what Press means"): it is one line wherever it shows
// (who prepared what, its age, one button in the action's own words), and its dialog reads it back
// once: the key fields in a short list and a long text as markdown, collapsed. Plain data, so the
// tests read it.

export const PREPARED_API = "/api/prepared";

/** one change a prepared press makes: its label and new value in words; ``long`` for a text the
 * dialog draws as markdown */
export interface Change {
  label: string;
  value: string;
  long?: boolean;
}

export interface Prepared {
  uuid: string;
  verb: string;
  title: string;
  by_words: string;
  page: string | null;
  words: string | null;
  fields: Record<string, unknown>;
  subject_name?: string | null;
  subject_kind?: string | null;
  subject_id?: string | null;
  state: string;
  created_at?: string | null;
  /** the action's own words for its button ("File issue"); the server 0.6.0.dev15+ */
  button?: string;
  /** what this press will change, in one plain sentence ("Change your voice card and set Salt
   * to salty."); before the server said it, the verb's own sentence */
  says?: string;
  /** every field the press will change, with its new value, in plain words (a nested field a
   * line per entry): the Save dialog lists them all, so nothing bundled is left unsaid */
  changes?: Change[];
  /** a locked kind (a key, consent): approved in its dialog only, never a toast */
  locked?: boolean;
  /** false when its verb left Kranto (C3: a build or project verb prepared before the cut): its
   * title ends "(no longer available)", its button is Dismiss, and Press answers 410 */
  available?: boolean;
}

/** an item whose verb left Kranto: it can only be dismissed (no Review, no approve, no toast) */
export const gone = (p: Pick<Prepared, "available">): boolean => p.available === false;

/** a route's path without its query: "#/settings/privacy?sel=x" and "settings/privacy" alike */
export const pathOf = (h: string | null | undefined): string => String(h || "").replace(/^#?\/?/, "").split("?")[0]!.replace(/\/$/, "");

/** a route's selection: "#/ideas?sel=i12" → "i12" */
export const selOf = (h: string | null | undefined): string | null => new URLSearchParams(String(h || "").split("?")[1] || "").get("sel");

/** the pages whose rows already list every prepared item (one row each): no line under the head
 * there, so an item is never said twice on one screen */
export const LISTED_ON = ["needs", "home", "today", ""];

/** the open items prepared for the page at ``hash``: an item's page is matched where it lands
 * (``land``: the router's redirects, so #/ideas/12 is #/ideas?sel=i12; PAR: the cards of
 * ideas, sources and moved settings never showed), and one for a selection is not drawn while
 * another is open. On Needs you and the home none: their rows say them. */
export function preparedHere(rows: Prepared[] | null | undefined, hash: string, land: (h: string) => string = (h) => h): Prepared[] {
  const here = pathOf(hash), sel = selOf(hash);
  if (LISTED_ON.includes(here)) return [];
  return (rows || []).filter((p) => {
    if (p.state !== "open" || !p.page) return false;
    const at = land(p.page);
    return pathOf(at) === here && (!sel || !selOf(at) || selOf(at) === sel);
  });
}

/** the open ones, newest first */
export const waitingItems = (rows: Prepared[] | null | undefined): Prepared[] => (rows || []).filter((p) => p.state === "open");

const SMALL = new Set(["a", "an", "the", "kranto", "Kranto's", "your", "this"]);
/** the button's words: the server's, else the title's ("File a Kranto issue" → "File issue") */
export function buttonOf(p: Pick<Prepared, "button" | "title" | "available">): string {
  if (gone(p)) return "Dismiss";
  if (p.button) return p.button;
  const w = String(p.title || "").replace(/[….\s]+$/, "").split(/\s+/).filter((x) => x && !SMALL.has(x.toLowerCase()));
  return !w.length ? "Approve" : w.length <= 4 ? w.join(" ") : w[0]!;
}

/** who prepared it: "Claude Code" from "by Claude Code" */
export const whoOf = (p: Pick<Prepared, "by_words">): string => String(p.by_words || "").replace(/^by /, "") || "An assistant";

/** a field's words: a string, or a list of parts each {text} (post.edit's parts: the words of
 *  a short post or a thread, one paragraph a part); null for anything else */
function textOf(v: unknown): string | null {
  if (typeof v === "string") return v;
  if (Array.isArray(v) && v.length && v.every((x) => !!x && typeof x === "object" && typeof (x as { text?: unknown }).text === "string"))
    return v.map((x) => (x as { text: string }).text).join("\n\n");
  return null;
}

/** a field's short value, or null when it is a long text (the dialog's markdown body) */
function shortValue(v: unknown): string | null {
  if (v === null || v === undefined || v === "") return null;
  const words = Array.isArray(v) ? textOf(v) : null;
  if (words !== null) return words.length > 120 || words.includes("\n") ? null : words;
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (typeof v === "object") return null;
  const s = String(v);
  return s.length > 120 || s.includes("\n") ? null : s;
}

/** a card the item is about, by its name when the server gave one, else its number */
function cardOf(p: Prepared, ref: unknown): string {
  const n = String(ref ?? "").replace(/^(card:|idea:|i)/, "");
  return p.subject_name || (n ? `card #${n}` : "the card");
}
/** the verbs a person meets in Needs you, said as the page says them (16, Codex 12: the
 * dialog read "target_id: 153 · value: not_useful" and "about: card:160 · as: blog"): its title,
 * what it is about, and the fields that are said by those words */
export function plainOf(p: Prepared): { title: string; subject: string; hide: string[] } | null {
  const f = p.fields || {};
  if (p.verb === "feedback.add" && f.target === "idea" && (f.value === "not_useful" || f.value === "useful"))
    return { title: f.value === "not_useful" ? "Pass" : "Grade useful", subject: cardOf(p, f.target_id), hide: ["target", "target_id", "value"] };
  if (p.verb === "post.write") {
    const about = String(f.about || ""), what = f.as === "toot" ? "Write a short post" : "Write a blog post";
    return { title: what, subject: about === "week" ? "about this week's news" : /^card:/.test(about) ? `about ${cardOf(p, about)}` : `about ${about}`, hide: ["about", "as"] };
  }
  if (p.verb === "idea.later")
    return { title: "Later", subject: `${cardOf(p, p.subject_id)}, back in ${Number(f.days ?? 7)} days`, hide: ["days"] };
  // an assistant's new words for a waiting draft: the words themselves are the dialog's body
  if (p.verb === "post.edit")
    return { title: "New words for a draft", subject: p.subject_id ? `draft #${p.subject_id}` : "a draft", hide: [] };
  return null;
}

/** whether the dialog lists the server's ``changes`` (every field, in words): a server that
 * sends them, an item still available, and a verb the page does not say in its own words */
export const usesChanges = (p: Prepared): boolean => Array.isArray(p.changes) && !gone(p) && !plainOf(p);

/** the server's one sentence for the change, without its full stop, when it gave one (servers
 * with ``changes``); null before */
function sentenceOf(p: Prepared): string | null {
  if (!usesChanges(p)) return null;
  const s = String(p.says || "").trim().replace(/\.$/, "");
  return s || null;
}
/** the item's title in the page's words ("Pass", "Write a blog post"), else the server's */
export const plainTitle = (p: Prepared): string => plainOf(p)?.title || p.title;

/** the main field's value: its one line in the row ("Needs you doesn't update live…") */
export function subjectOf(p: Prepared): string {
  const pl = plainOf(p);
  if (pl) return pl.subject;
  const f = p.fields || {};
  for (const k of ["issue", "title", "name", "topic", "label", "mode", "words"]) {
    const v = shortValue(f[k]);
    if (v) return v;
  }
  // what it acts on, when no field says it: "Archive: topic #1"
  return p.subject_name || (p.subject_kind && p.subject_kind !== "new" && p.subject_id ? `${p.subject_kind} #${p.subject_id}` : "");
}

/** what the row says, in one line: "File a Kranto issue: Needs you doesn't update live…" */
export function lineOf(p: Prepared): string {
  if (!plainOf(p)) {
    const said = sentenceOf(p);
    if (said) return said;
  }
  const s = subjectOf(p), t = plainTitle(p);
  return s ? `${t}: ${s}` : t;
}

/** the row's second line: that nothing happens until the owner chooses its button (the change
 * itself is the row's title; the verb's own documentation is never shown: it read "samples
 * (samples_add [{text, site}] …)") */
export const whyOf = (_p: Prepared, button: string): string => `Nothing happens until you choose ${button}.`;

/** the Save dialog's title: the change as a question ("Change your voice card and set Salt to
 * salty?"), else the action's own words */
export function dialogTitle(p: Prepared): string {
  const s = sentenceOf(p);
  return s ? `${s}?` : `${plainTitle(p)}?`;
}

/** the dialog's one line under its title: none when the title says the change already */
export const dialogSubject = (p: Prepared): string => (sentenceOf(p) ? "" : subjectOf(p));

// where a factory issue goes (the page's chat.factory_repos defaults: Kranto's own, the watcher's)
const FACTORY_REPOS: Record<string, string> = { kranto: "iddv/kranto", watcher: "iddv/kranto" };

/** the dialog's short list: [label, value] for every short field, and where it goes */
export function keyFields(p: Prepared): [string, string][] {
  const f = p.fields || {};
  const out: [string, string][] = [];
  // the server's plain list of every change (a nested field a line per entry: Salt, a
  // disclosure line), so the dialog never leaves a bundled field out
  // (the verbs said in the page's own words, plainOf's, keep their own short list)
  if (usesChanges(p)) {
    for (const c of p.changes!) if (!c.long) out.push([c.label, c.value]);
    if (p.page) out.push(["where", `shows on ${p.page}`]);
    return out;
  }
  const main = ["issue", "title", "name"].find((k) => shortValue(f[k]));
  const said = new Set(plainOf(p)?.hide || []);
  for (const [k, v] of Object.entries(f)) {
    if (k === main || k === "repo" || k === "fingerprint" || said.has(k)) continue;
    const s = shortValue(v);
    if (s) out.push([k, s]);
  }
  if (p.verb === "b.factory_issue") out.push(["where", `a new issue on ${FACTORY_REPOS[String(f.repo || "kranto")] || FACTORY_REPOS.kranto}`]);
  else if (p.page) out.push(["where", `shows on ${p.page}`]);
  return out;
}

/** the long texts (a factory issue's body): [label, markdown] */
export function longFields(p: Prepared): [string, string][] {
  if (usesChanges(p)) return p.changes!.filter((c) => c.long && c.value).map((c) => [c.label, c.value]);
  return Object.entries(p.fields || {}).filter(([, v]) => textOf(v) !== null && shortValue(v) === null && textOf(v) !== "").map(([k, v]) => [k, textOf(v)!]);
}

/** the toast's one line for the items waiting now: one says who prepared what; several merge */
export function toastLine(items: Prepared[]): string {
  if (!items.length) return "";
  if (items.length === 1) return `${whoOf(items[0]!)} prepared: ${lineOf(items[0]!)}`;
  return `${items.length} waiting: review`;
}
