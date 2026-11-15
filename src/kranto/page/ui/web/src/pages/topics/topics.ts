// Topics (PLAN.md sections 2.2 and 2.3; WORKSPACE.md 2.7, 2.13): the server's /api/topics (every
// topic with its facts, the broad lane, the library as a whole) and one topic's page,
// /api/topics/<id>: its facts, its themes (the latest map's clusters whose stories come mostly
// from it), the ones rising now, its sources with the scout's proposals. Both are generated from
// the server's web/types.py (api/afk.gen.ts).
import type { TopicPage, TopicSource, TopicTheme } from "../../api/afk.gen";
export type { Today, TodayTopic, Topic, TopicPage, Topics, TopicSource, TopicTheme } from "../../api/afk.gen";

export const TOPICS_API = "/api/topics";
export const topicApi = (id: number | string): string => "/api/topics/" + encodeURIComponent(id);
export const TODAY_API = "/api/today";
/** a new topic's first hour: its four rows (the server progress.topic_start,) */
export const startApi = (id: number | string): string => "/api/topics/" + encodeURIComponent(id) + "/start";
export type { TopicStart, TopicStartRow } from "../../api/afk.gen";

/** a topic's state: [icon, colour, word] */
export const TOPIC_ST: Record<string, [string, string, string]> = { active: ["public", "green", "Active"], paused: ["paused", "grey", "Paused"], archived: ["closed", "grey", "Archived"] };
export const topicSt = (s: string | null | undefined): [string, string, string] => TOPIC_ST[s || ""] || (TOPIC_ST.active as [string, string, string]);

/** a topic's pages by their node (topics/<id>/<page>): [the page's part, its name]. Under the
 * doors a topic's pages are Watch's (#/watch/topic/<id>, …/sources, …/evidence, …/map: WT); the
 * old tree (a the server with no doors) lists them as the topic's children, Map aside */
export const TPAGES: [string, string][] = [["", "Overview"], ["evidence", "Evidence"], ["themes", "Themes"], ["ideas", "Ideas"], ["sources", "Sources"], ["map", "Map"]];
/** the page a route opens (Overview for one it does not know, as the old page did) */
export const subOf = (part: string | undefined): string => (TPAGES.some((p) => p[0] === (part || "")) ? part || "" : "");
export const pageName = (sub: string): string => (TPAGES.find((p) => p[0] === sub) || TPAGES[0] as [string, string])[1];
/** the server's answer for a topic it does not have */
export const noTopic = (error: string | null | undefined): boolean => !!error && /no such topic|not found/i.test(error);

/** the Overview's themes: rising first, then the most new arrivals; three */
export const topThemes = (xs: TopicTheme[]): TopicTheme[] =>
  xs.slice().sort((a, b) => Number(b.rising) - Number(a.rising) || (b.movement?.new_in_cluster || 0) - (a.movement?.new_in_cluster || 0)).slice(0, 3);
/** Themes' list: rising first, then the most stories */
export const themeOrder = (xs: TopicTheme[]): TopicTheme[] =>
  xs.slice().sort((a, b) => Number(b.rising) - Number(a.rising) || (b.stories || b.size) - (a.stories || a.size));
/** a source this topic reads every run: watched and linked to it (what the topic's "N watched" counts) */
export const watchedHere = (s: TopicSource, tid: number | string): boolean => s.review === "approved" && s.topics.some((x) => String(x.id) === String(tid));
/** the topic page's Sources section: its watched sources that keep the most, best first; five */
export const topSources = (rows: TopicSource[], tid: number | string, n = 5): TopicSource[] =>
  rows.filter((s) => watchedHere(s, tid)).sort((a, b) => (b.yield_per_day || 0) - (a.yield_per_day || 0) || (b.items_per_day || 0) - (a.items_per_day || 0)).slice(0, n);

/** a topic's rows by group: its proposals; Watched (linked to it, read every run: the topic's
 * count); Wildcards (proposed for it, watched with no topic); then the rest as Watch › Sources
 * groups them. [key, heading, what it means, rows] */
export function topicGroups(t: Pick<TopicPage, "id" | "name" | "source_rows">, groups: [string, string, string][]): [string, string, string, TopicSource[]][] {
  const taken = new Set<number>(), out: [string, string, string, TopicSource[]][] = [];
  const take = (key: string, title: string, blurb: string, f: (s: TopicSource) => boolean): void => {
    const xs = t.source_rows.filter((s) => !taken.has(s.id) && f(s));
    for (const s of xs) taken.add(s.id);
    if (xs.length) out.push([key, title, blurb, xs]);
  };
  const g = (k: string): [string, string] => { const x = groups.find((y) => y[0] === k); return [x?.[1] || k, x?.[2] || ""]; };
  take("proposed", ...g("proposed"), (s) => s.review === "proposed");
  take("approved", g("approved")[0], `read every run for ${t.name}; its items are compared with ${t.name} before any model call`, (s) => watchedHere(s, t.id));
  take("wildcard", g("wildcard")[0], `unrelated to ${t.name}, watched for the patterns it may share`, (s) => s.group === "wildcard");
  for (const [k, w, b] of groups) take(k, w, b, (s) => s.group === k);
  take("other", "Other", "", () => true);
  return out;
}
