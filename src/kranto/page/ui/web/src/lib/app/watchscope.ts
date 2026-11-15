// Watch is topic-first (WT; the owner, 2026-10-23: "By default you see sources/evidence for a
// specific topic, and maybe you can see them in aggregate"). A topic's pages are
// #/watch/topic/<id> and its Sources, Evidence and Map under it; #/watch/sources, /evidence and
// /map are All topics, a choice made in the topic switcher. When the address names no topic, Watch
// is scoped to the last topic you looked at, kept in this browser (per viewer); with none yet, the
// first. Plain data and the browser's storage; the shell's chrome and render() read it.
import type { Route } from "../router";
import { peek } from "../reads.svelte";
import { host } from "./data";

/** a topic's page in Watch: "" is the topic itself */
export type WatchPage = "" | "sources" | "evidence" | "map";
/** the pages a topic has under it, in the subnav's order */
export const WATCH_PAGES: [Exclude<WatchPage, "">, string][] = [["sources", "Sources"], ["evidence", "Evidence"], ["map", "Map"]];
const PAGES = new Set<string>(WATCH_PAGES.map(([k]) => k));
const WATCH_KEY = "kranto.watch.topic";

/** where a path is in Watch: the topic it names (null: All topics, or the Topics list) and the
 * page (null: the Topics list or a page that is not a topic's); null outside Watch */
export function scopeOf(path: string[]): { topic: string | null; page: WatchPage | null } | null {
  if (path[0] !== "watch") return null;
  if (path[1] === "topic" && path[2]) return { topic: path[2], page: PAGES.has(path[3] || "") ? (path[3] as WatchPage) : "" };
  return { topic: null, page: PAGES.has(path[1] || "") ? (path[1] as WatchPage) : null };
}
/** a page of a topic, or of All topics (topic null), as a route without "#/" */
export const watchPath = (topic: string | number | null, page: WatchPage): string =>
  topic != null ? `watch/topic/${encodeURIComponent(String(topic))}${page ? "/" + page : ""}` : page ? "watch/" + page : "watch";

/** remember the topic you looked at (render() calls it on every topic page) */
export function rememberTopic(id: string | number): void {
  try {
    localStorage.setItem(WATCH_KEY, String(id));
  } catch {
    /* storage refused (a private window): the first topic stands in */
  }
}
function stored(): string | null {
  try {
    return localStorage.getItem(WATCH_KEY);
  } catch {
    return null;
  }
}
/** the topic remembered here, while it is still one of your topics; else null */
export function rememberedTopic(): { id: number; name: string } | null {
  const k = stored();
  return (k && (host()?.topics || []).find((t) => String(t.id) === k)) || null;
}
/** the topic Watch is scoped to when the address names none: the remembered one, else the first;
 * null without topics (a new install says so, with Add topic) */
export function lastTopic(): { id: number; name: string } | null {
  return rememberedTopic() || host()?.topics[0] || null;
}
/** a topic's name: yours (the header's read), else its page's read (a paused or project topic) */
export function topicName(id: string): string {
  const mine = (host()?.topics || []).find((t) => String(t.id) === id);
  return mine?.name || peek<{ name: string }>("/api/topics/" + encodeURIComponent(id))?.data?.name || "topic " + id;
}

/** where an address goes in topic-first Watch, or null: the old ?topic= forms of the All topics
 * pages and of Watch itself become the topic's page (#/watch/sources?topic=13 →
 * #/watch/topic/13/sources), and #/topics (the Watch door: g w, the home's tile, the tab bar)
 * lands on the last topic you looked at, or the Topics list when there is none */
export function watchRedirect(r: Route): { path: string; q: Record<string, string> } | null {
  const p = r.path.join("/");
  if (p === "topics") {
    const t = rememberedTopic();
    return t ? { path: watchPath(t.id, ""), q: r.q } : null;
  }
  const s = scopeOf(r.path);
  if (s && s.topic == null && r.q.topic && (s.page || r.path.length === 1)) {
    const q = { ...r.q };
    delete q.topic;
    return { path: watchPath(r.q.topic, s.page || ""), q };
  }
  return null;
}
