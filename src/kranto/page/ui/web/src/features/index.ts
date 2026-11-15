// The features' slots in today's shell. the server's GET /api/features says which
// features there are, whether each is on and what it fills; this file draws that in the shell as
// it is now: a navigator entry under the heading the manifest names (News under Desk) and each feature's page registered by its node. The area shell 
// designed waits for the owner's review; when it lands, a feature becomes an area here and its
// pages move unchanged. A feature that is off leaves no entry (its route still opens, and says
// how to turn it on).
import { lazy, register } from "../lib/pages.svelte";
import { read } from "../lib/reads.svelte";

export const FEATURES_API = "/api/features";

export interface FeatureNav {
  route: string;
  word: string;
  under: string;
  count: string | null;
}
/** a field of a form, or of an action that takes input (row 4) */
export interface FormField {
  key: string;
  label: string;
  kind: "text" | "markdown" | "enum" | "choice" | "bool" | "int" | "usd";
  choices: (string | number)[];
  read: string | null;
  hint: string;
  required: boolean;
}
export interface TodayRowDecl {
  kind: string;
  read: string;
  group: "needs_you" | "new";
  primary: string;
  card: string | null;
}
export interface ListDecl {
  id: string;
  word: string;
  read: string;
  card: string;
  /** tone (the server 0.5.19): its rows' glyph and state word */
  groups: { key: string; word: string; tone?: "new" | "wait" | "quiet" | "good" | "bad" }[];
  count: string | null;
  /** what the list says with nothing in it (none: "Nothing here yet.") */
  empty?: string;
}
export interface FormDecl {
  id: string;
  word: string;
  submit: string;
  fields: FormField[];
  cost: string;
  says: string;
}
export interface ActionDecl {
  kind: string;
  title: string;
  doors: string[];
  click: "click" | "confirm" | "house";
  subjects: string[];
  says: string;
  fields: FormField[];
  place: "card" | "head";
  /** one of the feature's true-or-false settings: the page offers the action only while it is on */
  when?: string;
}
export interface SettingRow {
  key: string;
  value: unknown;
  type: string;
  default: unknown;
  choices: (string | number)[];
  lo: number | null;
  hi: number | null;
  words: string;
  sensitive: boolean;
  by_hand: boolean;
  per_topic: boolean;
  /** its place on Settings › <Feature> (the server from 0.5.19): the group's
   * heading (empty: "<Feature>'s settings"), or under Advanced */
  group?: string;
  advanced?: boolean;
  /** the two lines (the server's Setting(default_stable=)): this install's
   * line, and the other line's default when it differs (null when both share one) */
  line?: "stable" | "nightly";
  default_other?: unknown;
}
/** "Nightly's default is new: stable keeps classic until it is turned on for stable." */
export function otherLine(r: SettingRow): string | null {
  if (r.default_other === undefined || r.default_other === null || !r.line) return null;
  const v = (x: unknown) => (Array.isArray(x) ? x.join(", ") : String(x));
  return r.line === "stable"
    ? `Nightly's default is ${v(r.default_other)}: stable keeps ${v(r.default)} until it is turned on for stable.`
    : `Stable's default is ${v(r.default_other)}: stable installs keep it until it is turned on for stable.`;
}
export interface Tile {
  line: string;
  count: number | null;
  words: string;
  tone: "new" | "wait" | "quiet";
}
export interface FeatureRow {
  id: string;
  title: string;
  says: string;
  version: string;
  trust: string;
  enabled: boolean;
  mode: string;
  tickets_open: number;
  /** what it asks you now, as Needs you lists it (the server 0.6.0.dev16+, SEND) */
  asks?: number;
  tile?: Tile | null;
  last_run?: { kind: string; status: string; finished_at: string } | null;
  spend?: { month_usd: number; today_usd: number; calls: number };
  settings?: SettingRow[];
  manifest: {
    actions?: ActionDecl[];
    requests?: string[];
    reads?: string[];
    /** the services Kranto performs operations on for it, with the owner's credential */
    broker?: Record<string, string[]>;
    /** its spend lines, and the setting keys that cap them (key: the words on Spend) */
    spend?: { purposes?: string[]; caps?: Record<string, string> };
    ui: {
      nav: FeatureNav[];
      pages?: string[];
      cards: Record<string, CardSchema>;
      kind?: string;
      glyph?: string;
      tile?: { line: string; count: string | null; words: string; tone: string } | null;
      today_rows?: TodayRowDecl[];
      lists?: ListDecl[];
      forms?: FormDecl[];
      /** the page's one primary: a form's id, or an action in its head (none: its first form) */
      primary?: string | null;
    };
  };
}
/** a request kind's read-back schema: the confirm dialog's typed fields */
export interface RequestSchema {
  title: string;
  doors: string[];
  page_only: boolean;
  performs: boolean;
  expires_hours: number;
  per_day: number;
  fields: { key: string; label: string; type: string; choices: (string | number)[] }[];
  /** its button's word (the server 0.6.0.dev16+, SEND: "Send", "Post toot") */
  button?: string;
}
export interface Features {
  features: FeatureRow[];
  api: string;
  reads: string[];
  request_kinds: string[];
  request_schemas?: Record<string, RequestSchema>;
}
/** a declarative card (MR-RESEARCH): the object's field that is the title, the fields shown
 * as lines, the labelled fields with their kinds, the field with its cites (origin); drawn by
 * ui/Card.svelte. A key may be a dotted path into the object. */
export interface CardSchema {
  title: string;
  lines: string[];
  fields: { key: string; label: string; kind: string }[];
  actions: string[];
  origin?: string | null;
  image_ref?: string | null;
  /** page: an object you read opens as a page of its own (cub/<id>/o/<oid>), body its text */
  open?: "sheet" | "page";
  body?: string | null;
}

/** the four doors that are features (News): not cubs, never under Cubs */
export const DOOR_FEATURES = ["news"];
/** the features drawn as cubs (the posting cubs and, from 0.5, other people's) */
export const cubsOf = (f: Features | null): FeatureRow[] => (f ? f.features.filter((x) => !DOOR_FEATURES.includes(x.id)) : []);

/** a trust in words, on every tile, row and head: a cub's row never reads as Kranto's own */
export const TRUST_WORD: Record<string, string> = {
  "first-party": "built-in", owner: "yours", reviewed: "reviewed", listed: "listed", unreviewed: "unreviewed", generated: "made by Kranto",
};
export const trustWord = (t: string): string => TRUST_WORD[t] || t;
/** the closed set of glyphs the core draws for a cub (never an image of its own) */
export const GLYPH: Record<string, string> = { mail: "✉", pen: "✎", up: "↗", plane: "✈", play: "▶", target: "◎", swap: "⇄", grid: "▤", dot: "•" };
export const glyphOf = (g: string | undefined): string => GLYPH[g || "dot"] || GLYPH.dot!;
/** a cub's kind in words: More cubs and the gallery group by it */
export const KIND_WORD: Record<string, string> = { post: "Post and send", send: "Post and send", money: "Watch and money", watch: "Watch and money", book: "Book", make: "Make", other: "Other" };
/** the mode tag's wash: paper and practice amber (an older the server's dry run too), live green, off grey */
export const modeTone = (m: string): string => (/^(paper|practice|dry|drafts)/.test(m) ? "amber" : m === "live" ? "green" : "grey");
/** a mode in the owner's words: an older the server's dry modes are practice (SEND) */
export const modeWord = (m: string): string => m.replace(/^(dry run|drafts only)$/, "practice").replace(/^dry \(/, "practice (");

/** the features as the server lists them; null without the server or before the read arrives */
export function features(host: boolean): Features | null {
  return host ? read<Features>(FEATURES_API, 60000).data || null : null;
}

/** a feature's read: GET /api/f/<feature>/<name> with its query */
export function featurePath(feature: string, name: string, q: Record<string, string | number> = {}): string {
  const qs = new URLSearchParams(Object.entries(q).map(([k, v]) => [k, String(v)])).toString();
  return `/api/f/${feature}/${name}` + (qs ? "?" + qs : "");
}

/** the navigator's entries a heading gets from the features that are on, each with the count its
 * manifest names (one of its own reads answering {count}) */
export function featureNav(under: string, host: boolean): { to: string; w: string; n: number | null }[] {
  const f = features(host);
  if (!f) return [];
  const out: { to: string; w: string; n: number | null }[] = [];
  for (const x of f.features) {
    if (!x.enabled) continue;
    for (const n of x.manifest.ui.nav || []) {
      if (n.under !== under) continue;
      const c = n.count ? read<{ count: number }>(featurePath(x.id, n.count), 60000).data : null;
      out.push({ to: n.route, w: n.word, n: c && c.count ? c.count : null });
    }
  }
  return out;
}

/** a feature's card schema, by kind */
export function cardOf(host: boolean, feature: string, kind: string): CardSchema | null {
  const f = features(host)?.features.find((x) => x.id === feature);
  return (f && f.manifest.ui.cards[kind]) || null;
}

// News: a brief per topic (sel=f<brief id>)
register("news", {
  list: lazy(() => import("./news/NewsList.svelte")),
  pane: lazy(() => import("./news/NewsPane.svelte")),
});
// with the doors on: News › Earlier (every brief, one in the sheet) and Topics
register("news/earlier", { list: lazy(() => import("./news/NewsEarlier.svelte")), pane: lazy(() => import("./news/NewsPane.svelte")) });
register("news/topics", { list: lazy(() => import("./news/NewsTopics.svelte")), pane: lazy(() => import("./news/NewsTopicPane.svelte")) });
// the things you read are pages: a brief, an item, an article;
// stages, one reading column, no sheet
register("news/b", { list: lazy(() => import("./news/BriefPage.svelte")) });
register("news/i", { list: lazy(() => import("./news/StoryPage.svelte")) });
register("news/a", { list: lazy(() => import("./news/StoryPage.svelte")) });
