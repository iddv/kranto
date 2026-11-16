// News's page data (the server's features/news/api.py): a brief per topic, each item cited to an
// observation or a dated search result. Reads are the feature's own (GET /api/f/news/<name>);
// presses are its actions (POST /api/f/news/act/<verb>).
import { href } from "../../lib/router";
import { app } from "../../lib/shell.svelte";
import { read } from "../../lib/reads.svelte";
import { PRODUCT } from "../../lib/product";

/** why no brief can be written now, in the words Activity and Watching use, or null (8,
 * Codex 6, Gemini 18: News said "being written" and gave a next run with the scheduler off and
 * no model key) */
export function whyNothingRuns(): { text: string; link: { href: string; w: string } | null } | null {
  const h = (app()?.host() || null) as { scheduler?: boolean } | null;
  if (h && h.scheduler === false) {
    return { text: "Nothing is read and no brief is written: Kranto runs with the scheduler off (kranto serve --no-scheduler).", link: { href: "#/activity", w: "Activity ›" } };
  }
  const key = h ? read<{ key?: { set?: boolean } }>("/api/setup", 30000).data?.key : null;
  if (key && key.set === false) {
    return { text: "No brief yet: no model is chosen.", link: { href: "#/welcome", w: `Set up ${PRODUCT} ›` } };
  }
  return null;
}
/** News's one line while the server runs no jobs (serve --no-scheduler; the status's scheduler:
 * false): the briefs already written stay, and no new one comes until jobs run again */
export const JOBS_OFF = "No new briefs are made while jobs are off.";
export function jobsOff(): boolean {
  const h = (app()?.host() || null) as { scheduler?: boolean } | null;
  return !!h && h.scheduler === false;
}
/** the early first brief's line: written while the first read went on, from
 * the items kept by then; the first read's own brief takes its place when the read ends */
export function earlyWords(b: { checks?: Record<string, unknown> | null }): string {
  const n = Number((b.checks || {}).observations);
  return `From the first ${Number.isFinite(n) && n > 0 ? n + " " : ""}items. The read is still going.`;
}
/** a topic's next brief, or why there is none */
export const nextWords = (nextDue: string | null | undefined): string =>
  whyNothingRuns() ? " · not while nothing runs" : nextDue ? " · next " + nextDue.slice(0, 16).replace("T", " ") : "";
import { confirmThen } from "../../ui/dialog.svelte";
import { featurePath } from "../index";

export interface BriefSource {
  label: string;
  kind: string;
  id: number | null;
  title: string;
  url: string | null;
  date: string | null;
  source?: string | null;
}
export interface BriefItem {
  headline: string;
  body: string;
  why: string;
  cites: string[];
  date: string | null;
  background: boolean;
  observation_ids: number[];
  urls: string[];
  sources: BriefSource[];
}
/** a point of a figure's timeline: a dated event and the lines it rests on */
export interface TimePoint {
  date: string;
  event?: string;
  cites?: string[];
}
/** an item's article as a brief carries it (Today's tag and thumbnail, the item page's link) */
export interface ItemArticle {
  id: number;
  topic_id?: number;
  status: "ok" | "quiet" | "failed";
  kind: string | null;
  headline: string | null;
  minutes: number;
  words: number | null;
  diagram: string | null;
  timeline: TimePoint[];
  quiet: string | null;
  error: string | null;
  created_at: string;
  image: LeadImage | null;
  running?: boolean;
}
/** a source's own picture, as the outlet offers it for sharing: an address, never stored */
export interface LeadImage {
  url: string;
  site: string;
  alt?: string;
  page?: string;
}
export interface Para {
  text: string;
  cites: string[];
}
export interface ArticleBody {
  sections: { id: string; title: string; paragraphs: Para[] }[];
  numbers: { label: string; value: string; unit: string; cites: string[] }[];
  timeline: TimePoint[];
  series: { name: string; unit: string; cites: string[]; points: { x: string; y: number }[] } | null;
  entities: { name: string; kind: string; cites: string[] }[];
  relations: { from: string; to: string; kind: string; cites: string[] }[];
  themes: string[];
  idea_seed: string | null;
  standfirst_cites: string[];
  evidence_timeline: TimePoint[];
  image: LeadImage | null;
  item?: { headline: string; body: string; why: string };
}
export interface ArticleSource extends BriefSource {
  n?: number;
  obs?: number;
  fetched_at?: string;
}
export interface Article extends ItemArticle {
  topic_id: number;
  topic: string | null;
  brief_id: number;
  item_n: number;
  standfirst: string | null;
  trigger: string;
  body: ArticleBody;
  sources: ArticleSource[];
  checks: Record<string, number | boolean | Record<string, number>>;
  material: { counts: Record<string, number>; earlier: number; pages: { url: string; label?: string; skipped?: string; error?: string; chars?: number }[]; search: { live?: boolean; labels?: string[] } | null };
  model: string | null;
  prompt_version: string | null;
  brief_at: string | null;
  newest_id: number;
}
/** a story's idea, chosen by rule from stored rows (the server features/news/ideas.py) */
export interface StoryIdea {
  idea: { id: number; title: string; state: string | null; rule: number; more: number } | null;
  theme: { lineage_id: string; name: string; size: number } | null;
  no_theme: string | null;
  /** brief:<id>:<item>, the item counted from 1 */
  story: string;
}
/** how a story's idea was found, said on the brief's item and the story's page (a
 * card only on the same map theme read as made from the story): rule 1 a card made from this
 * story, 2 a card citing its evidence, 3 a card of its theme */
export function ideaLabel(rule: number | null | undefined): string {
  return rule === 1 ? "Idea from this story" : rule === 2 ? "An idea that cites this story" : "An idea on the same theme";
}
export interface Brief {
  id: number;
  /** each item's article, by the item's number as text (briefs.get and latest) */
  articles?: Record<string, ItemArticle>;
  /** each item's idea and theme, by the item's number as text (the page's reads) */
  stories?: Record<string, StoryIdea>;
  topic_id: number;
  status: "ok" | "quiet" | "failed";
  period_start: string;
  period_end: string;
  items: BriefItem[];
  quiet: string | null;
  error: string | null;
  search: { live?: boolean; labels?: string[]; searched_at?: string; note?: string | null };
  checks: Record<string, unknown>;
  cost_usd: number | null;
  equiv_usd: number | null;
  model: string | null;
  trigger: string | null;
  created_at: string;
}
export interface NewsSetting {
  topic_id: number;
  enabled: boolean;
  cadence: "daily" | "weekdays" | "weekly";
  hour: number;
  weekday: number;
}
export interface TopicRow {
  id: number;
  name: string;
  status: string;
  news: NewsSetting;
  running: boolean;
  next_due: string | null;
  last: { id: number; status: string; created_at: string; items: number } | null;
}
export interface TopicRows {
  topics: TopicRow[];
  enabled: boolean;
  search_off: string | null;
  spend: { month_usd: number; today_usd: number; calls: number; equiv_usd: number } | null;
}
/** a topic's newest try when it failed: one line under the good brief it never replaces
 * (the server 0.6.x: ``failed``, absent from an older one) */
export interface FailedTry { id: number; created_at: string; why: string; fix: string | null }
export interface Latest {
  topics: { topic: { id: number; name: string }; brief: Brief | null; failed?: FailedTry | null }[];
}
/** the failed try's line: "A newer brief could not be written at 14:05: ‹why›" */
export function failedTryLine(f: FailedTry, at: (iso: string) => string): string {
  const why = f.why.replace(/[.\s]+$/, "");
  return `A newer brief could not be written at ${at(f.created_at)}: ${why}.`;
}
/** the words of the failed try's link: the page its fix is on */
export const fixPlace = (fix: string | null | undefined): string => fix === "settings/spend" ? "Settings › Spend ›" : "Settings › Watching ›";

export const ROWS = featurePath("news", "topic_rows");
export const LATEST = featurePath("news", "latest");
export const briefPath = (id: string | number): string => featurePath("news", "briefs.get", { id });
/** the brief as its page and an item's page read it: briefs.get with each item's article (a page read, never the v1 surface) */
export const briefPagePath = (id: string | number): string => featurePath("news", "brief", { id });
export const ACT = (verb: string): string => `/api/f/news/act/${verb}`;
export const SEL = "f";

/** a brief's state as the shell's glyphs say it */
export function briefSt(status: string): [string, string, string] {
  if (status === "ok") return ["check", "green", "ok"];
  if (status === "failed") return ["warn", "red", "failed"];
  return ["dot", "grey", "quiet"];
}

const DAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];
/** "daily at 07:00", "weekdays at 06:00", "Mondays at 07:00" */
export function cadenceWords(s: NewsSetting): string {
  const at = `at ${String(s.hour).padStart(2, "0")}:00`;
  if (s.cadence === "weekly") return `${DAYS[s.weekday] || "weekly"} ${at}`;
  return `${s.cadence} ${at}`;
}

/** where a brief's search came from, in one line, or that there was none */
export function searchLine(b: Brief): string {
  const s = b.search || {};
  if (!s.live) return s.note || "No web search: the brief rests on what was kept alone.";
  // the search backends' own names ("Exa, free mode (rate-limited, no account)") are not a
  // reader's words: a web search, and the day
  const day = s.searched_at ? ` on ${shortDay(s.searched_at)}` : "";
  return `Searched the web${day}.`;
}

/** where a line is from, in words: its outlet, else the address's site, else what kind it is */
export function outletOf(s: Pick<BriefSource, "kind" | "url" | "source">): string {
  let host = "";
  if (s.url) {
    try {
      host = new URL(s.url).hostname.replace(/^www\./, "");
    } catch {
      /* not an address: said by its kind below */
    }
  }
  const known = SITES[host];
  if (known) return known;
  // a watcher's own label ("HN search: coding agent") names a search, not an outlet
  const src = (s.source || "").trim();
  if (/^hn\b|hacker news/i.test(src)) return "Hacker News";
  if (src && !/search|:/i.test(src)) return src;
  if (host) return host;
  return s.kind === "obs" ? "your library" : "a web search";
}
/** the outlets people know by name, by their address's site */
const SITES: Record<string, string> = { "news.ycombinator.com": "Hacker News", "github.com": "GitHub", "arxiv.org": "arXiv", "reddit.com": "Reddit", "old.reddit.com": "Reddit" };
/** a brief's page, an item's page and an article's (things you read are pages) */
export const briefHref = (id: number | string): string => href(`news/b/${id}`);
export const itemHref = (bid: number | string, n: number): string => href(`news/i/${bid}/${n}`);
/** a date as the pages say it: "Thu 23 Oct" */
export const dayWords = (iso: string | null | undefined): string =>
  iso ? new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "";

/** News on or off for a topic, or a new cadence or hour while on: one write (news.toggle), no dialog */
export function newsSet(btn: HTMLElement | null, t: TopicRow, on: boolean, change: Partial<NewsSetting> = {}): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api(ACT("toggle"), { fields: { topic_id: t.id, on, ...change } }), (r) => {
    L.afkDrop();
    const s = { ...t.news, ...change };
    const n = (r as { next_due?: string | null }).next_due;
    L.say(on ? `News is on for ${t.name}: ${cadenceWords(s)}${n ? ", the next at " + n.slice(0, 16).replace("T", " ") : ""}.` : `News is off for ${t.name}.`);
  });
}
/** Brief now: it spends, so it asks first */
export function briefNow(btn: HTMLElement | null, t: TopicRow): void {
  confirmThen(`Write ${t.name}'s brief now?`, "It reads what your watchers kept and searches the web: model calls, counted on Settings › Spend under News briefs. It shows on Today in a minute or so.", "Brief now", () => {
    const L = app();
    void L?.act(btn, () => L.api(ACT("write_now"), { fields: { topic_id: t.id } }), () => {
      L.afkDrop();
      L.say(`Writing ${t.name}'s brief: it shows on Today in a minute or so.`);
    });
  });
}
/** a News topic row's sheet (News › Topics: cadence and hour, Brief now) */
export const TOPIC_SEL = "t";

/** where its cost is: dollars are shown on Settings › Spend only (the owner's rule) */
export const SPEND_LINE = "Counted on Settings › Spend, under News briefs.";
export const ARTICLE_SPEND_LINE = "Counted on Settings › Spend, under News articles.";

/** an article's read, its page, and Earlier's list of them */
export const articlePath = (id: string | number): string => featurePath("news", "articles.get", { id });
export const articlesPath = (topic?: string): string => featurePath("news", "articles.list", topic ? { limit: 40, topic_id: topic } : { limit: 40 });
export const articleHref = (id: number | string): string => href(`news/a/${id}`);
/** an item's article when it has one written (ok), else null */
export function okArticle(b: Pick<Brief, "articles">, n: number): ItemArticle | null {
  const a = b.articles?.[String(n)];
  return a && a.status === "ok" ? a : null;
}
/** where an item's headline goes: its article when it has one, else its own page */
export const itemTarget = (b: Pick<Brief, "id" | "articles">, n: number): string => {
  const a = okArticle(b, n);
  return a ? articleHref(a.id) : itemHref(b.id, n);
};
/** Deep dive now: it reads the pages behind the item and calls the model once, so it asks first */
export function deepDive(btn: HTMLElement | null, bid: number, n: number, headline: string, done?: () => void): void {
  confirmThen("Write the full story now?", [`“${headline}”`, "It reads the pages behind the story, the library's earlier lines and two web searches, then calls the model once (about 10 cents, counted on Settings › Spend under News articles). The full story shows here in a minute or so."], "Write the full story", () => {
    const L = app();
    void L?.act(btn, () => L.api(ACT("article_now"), { fields: { brief_id: bid, n } }), () => {
      L.afkDrop();
      L.say("Writing the full story: it shows here in a minute or so.");
      done?.();
    });
  });
}

// -- News as one line a story -------------------------------------

/** The page's own reading speed: "about a minute" is 240 words */
export const WPM = 240;
/** "about a minute", "about three minutes" (the page's own words for its length) */
export function minutesWords(words: number): string {
  const m = Math.max(1, Math.round(words / WPM));
  const say = ["", "a minute", "two minutes", "three minutes", "four minutes", "five minutes"];
  return `about ${say[m] || m + " minutes"}`;
}
/** the words a story's open block says, for the head's "about a minute" */
export const storyWords = (x: BriefItem): number => `${x.headline} ${x.body} ${x.why}`.split(/\s+/).filter(Boolean).length;
/** "deepmind.google +3": a story's first outlet and how many more */
export function outletsLine(sources: BriefSource[]): string {
  const names = [...new Set(sources.map((s) => outletOf(s)))];
  return names.length ? names[0] + (names.length > 1 ? ` +${names.length - 1}` : "") : "";
}
/** "10 Nov" */
export const shortDay = (iso: string | null | undefined): string =>
  iso ? new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
/** "therobotreport.com · 10 Nov": one line for a story's outlets and days */
export function outletsDays(sources: BriefSource[]): string {
  const names = [...new Set(sources.map((s) => outletOf(s)))].slice(0, 3);
  const days = [...new Set(sources.map((s) => shortDay(s.date)).filter(Boolean))].slice(0, 2);
  return [names.join(", "), days.join(" and ")].filter(Boolean).join(" · ");
}
/** "Wednesday 11 November" */
export const longDay = (iso: string): string =>
  new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
/** "07:46" */
export const clock = (iso: string): string => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
/** the open story's key in the address (?s=<brief>.<n>) */
export const storyKey = (bid: number | string, n: number): string => `${bid}.${n}`;
/** a story's own page (one page a story: its summary, why it matters, its article, its sources) */
export const storyHref = (bid: number | string, n: number): string => itemHref(bid, n);
/** a card's page on Ideas */
export const ideaHref = (id: number): string => href(`ideas/${id}`);

/** Idea from this: theme.card on the story's theme, with the article's idea
 * seed or the headline as a hint; it spends, so it asks first */
export function ideaFromThis(btn: HTMLElement | null, s: StoryIdea, hint: string, done?: () => void): void {
  const theme = s.theme;
  if (!theme) return;
  confirmThen("Write an idea card from this story's theme?", [`Theme: ${theme.name}, ${theme.size} items.`, "One card call and its check, about 6 cents, counted on Settings › Spend. The card shows on Ideas in a minute."], "Write the card", () => {
    const L = app();
    void L?.act(btn, () => L.api(`/api/themes/${encodeURIComponent(theme.lineage_id)}/card`, { hint: hint.slice(0, 600), story: s.story }), () => {
      L.afkDrop();
      L.say("Writing the idea card: it shows on Ideas in a minute.");
      done?.();
    });
  });
}
