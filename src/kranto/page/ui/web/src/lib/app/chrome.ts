// What the shell's chrome draws (frame() calls chromeFacts on every frame), worked out from the
// app's data: the header's lanes, the navigator's tree, the status bar, what the key hint needs and
// the list's head (paused, not signed in, the flash). Plain data.
import type { Activity } from "../../api/types.gen";
import type { Route } from "../router";
import { hint as keyHint } from "../keys";
import { stamp, plural, readingWords, tokText, tokTitle, watchPaused } from "../format";
import { tokSum } from "../words";
import { peek, read } from "../reads.svelte";
import { isDark, lookName, lookNow } from "../theme";
import { livePaused } from "../live";
import { TODAY_API, type Today } from "../../pages/topics/topics";
import { needsCount, reviewCount } from "../../pages/front/needs";
import { cardIdeas } from "../../pages/ideas/cards";
import { SETTINGS_PAGES } from "../../pages/settings/pagedefs";
import { tidyError } from "../../pages/settings/checkupdates";
import { ADVANCED_PAGES, doorsPage, DOORS_PAGES } from "../../pages/settings/doorpages";
import { cubsOf, features } from "../../features/index";
import { arrangement, frameNew, shellDoors } from "../../features/shell";
import { afkPaused, host, loaded, PAUSES, signedOut, UPD_BUSY, updBad, updBusy, updNow } from "./data";
import { flashNow, pageHas, routeNow } from "./route";
import { rowsNow, sectionsNow } from "./rows";
import { lastTopic, scopeOf, topicName, WATCH_PAGES, watchPath, type WatchPage } from "./watchscope";
import type { DoorFacts, Facts, NavFacts, NavRow, UpdateFacts } from "./types";

/** the Library's pages, one entry a page */
export const LIB: [string, string][] = [["", "Observations"], ["map", "Map"], ["clusters", "Clusters"], ["rollups", "Rollups"]];
/** Settings' pages, each with its title */
export const SET: [string, string][] = SETTINGS_PAGES.map((p) => [p.key, p.title]);

const todayNow = (): Today | null => (host() ? read<Today>(TODAY_API, 60000).data || null : null);

/** every topic's proposals, your project topics' too: all of them wait on you */
const allProposed = (t: ReturnType<typeof todayNow>): number =>
  t ? [...t.topics, ...(t.project_topics || [])].reduce((a, x) => a + (x.proposed || 0), 0) : 0;
/* the counts beside the doors' words, one function for the subnav and the tree */
function doorCounts(): Record<string, [number | null, string, string?]> {
  const H = host(), t = todayNow();
  const proposed = allProposed(t);
  return {
    // kept observations new since your last visit, not topics: its title says so
    watch: [t && t.new_kept ? t.new_kept : null, "new", t && t.new_kept ? `${plural(t.new_kept, "kept observation")} new since your last visit` : ""],
    "watch/sources": [proposed || null, "wait"],
    ideas: [ideasWaiting() || null, ""],
    "ideas/review": [reviewCount(H) || null, "wait"],
  };
}
/** Ideas' count: its Waiting cards (the server's own state, H1: what the page lists) */
function ideasWaiting(): number {
  const ci = host() ? cardIdeas() : null;
  return ci ? ci.list.filter((x) => (x.state || "waiting") === "waiting").length : 0;
}
/** the cubs the navigator lists: every installed cub that is on, in the home's order (its pins
 * first, then the rest as installed), from the reads the home and Cubs draw from, so a cub
 * installed later is here with no work by its author */
export function cubRows(): { id: string; title: string; open: number }[] {
  const H = !!host(), all = cubsOf(features(H)).filter((x) => x.enabled), pins = arrangement(H)?.pins || [];
  const at = (id: string) => (pins.includes(id) ? pins.indexOf(id) : pins.length + all.findIndex((x) => x.id === id));
  return all.slice().sort((a, b) => at(a.id) - at(b.id)).map((x) => ({ id: x.id, title: x.title, open: x.asks ?? x.tickets_open ?? 0 }));
}
/* the navigator's tree (the owner's choice of 2026-10-21): one tree around the doors' pages. Home
   and Needs you; each door a heading with its subnav's words (Watch's topics under Topics); Cubs
   with what they ask you and each cub's page; Settings, a twisty with its pages and Advanced. The
   entry lit is the longest one the route is under. */
const CLASSIC_HOME: Record<string, string> = { topics: "watch", library: "watch/evidence", review: "ideas/review" };
function classicTree(r: Route): NavFacts {
  const out: NavRow[] = [], H = host(), n = doorCounts();
  const item = (to: string, w: string, o?: Partial<NavRow>) => out.push({ to, w, ...(o || {}) });
  const path = r.path.join("/"), seen = PLACED[path]?.[1] || CLASSIC_HOME[r.path[0] || ""] || path;
  const cubs = H ? cubRows() : [], open = cubs.reduce((a, c) => a + c.open, 0);
  item("home", "Home", { key: "g h" });
  item("needs", "Needs you", { key: keyHint("needs"), n: needsCount(H, open) || null, hot: true });
  // what Kranto is doing: the runs going now, the ring while one does
  const running = peek<Activity>("api/activity")?.data?.counts.running || 0;
  item("activity", "Activity", { key: keyHint("activity"), n: running || null, tone: "", live: running > 0 });
  for (const id of ["watch", "ideas", "news"]) {
    const d = doorNav(id);
    if (id === "news" && !H) continue;
    if (!d.items.length) continue;
    if (id === "watch") {
      classicWatch(r, item, n);
      continue;
    }
    out.push({ head: d.word, to: d.items[0]![0] } as NavRow);
    for (const [to, w] of d.items) item(to, w, { n: n[to]?.[0] ?? null, tone: n[to]?.[1] || "" });
  }
  if (H) {
    // the Cubs row with what they ask you, then each cub's page (the owner's note)
    out.push({ head: "Features", to: "cubs", n: open || null, tone: "wait" } as NavRow);
    for (const c of cubs) item("cub/" + c.id, c.title, { n: c.open || null, tone: "wait" });
    item("cubs/approvals", "Approvals", { n: open || null, tone: "wait" });
  }
  // Settings: its head opens the Overview; its pages show while one of them is open
  out.push({ head: "Settings", to: "settings" } as NavRow);
  if (path.startsWith("settings")) {
    for (const [to, w] of doorNav("settings").items.slice(1)) item(to, w);
    for (const k of ADVANCED_PAGES) item("settings/" + k, "Advanced › " + (doorsPage(k)?.title || k));
    // every feature's and cub's own page, as Settings' Features group lists them
    for (const x of features(!!H)?.features || []) item("settings/" + x.id, x.title, { sub: true });
  }
  const tos = out.filter((x) => !x.head).map((x) => x.to);
  const here = tos.filter((to) => seen === to || seen.startsWith(to + "/")).sort((a, b) => b.length - a.length)[0] || seen;
  return { here, rows: out, topic: null };
}

/* Watch in the classic tree: its head opens the last topic you looked at (#/topics); then
   Topics, each of your topics, and the one Watch is scoped to (the address's, else the last one)
   with its Sources, Evidence and Map under it; then All topics, whose pages show while you are on
   one of them. A topic you are on that is not one of yours (paused, a project's) has its row too. */
function classicWatch(r: Route, item: (to: string, w: string, o?: Partial<NavRow>) => void, n: ReturnType<typeof doorCounts>): void {
  const H = host(), t = todayNow(), s = watchScope(r);
  item("topics", "", { head: "Watch", add: H ? "topics/new" : null } as Partial<NavRow>);
  item("watch", "Topics", { n: n.watch?.[0] ?? null, tone: n.watch?.[1] || "" });
  const mine = (H ? H.topics : []).map((x) => ({ id: String(x.id), name: x.name }));
  if (s.topic && !mine.some((x) => x.id === s.topic)) mine.push({ id: s.topic, name: s.name });
  for (const tp of mine) {
    const nw = t && t.topics.find((x) => String(x.id) === tp.id);
    item(watchPath(tp.id, ""), tp.name, { sub: true, n: nw && nw.new_kept ? nw.new_kept : null, tone: "new" });
    if (tp.id === s.topic) for (const [k, w] of WATCH_PAGES) item(watchPath(tp.id, k), w, { sub: true, deep: true, n: k === "sources" ? sourcesCount(tp.id) : null, tone: "wait" });
  }
  // All topics: a choice, never the default; its row is a heading while one of its pages is open
  item(s.all ? "watch/sources" : "watch/evidence", "All topics", { sub: true, fold: s.all });
  if (s.all) for (const [k, w] of WATCH_PAGES) item(watchPath(null, k), w, { sub: true, deep: true, n: k === "sources" ? sourcesCount(null) : null, tone: "wait" });
}
/** the proposals waiting under a topic's Sources, or every topic's for All topics */
function sourcesCount(topic: string | null): number | null {
  const t = todayNow();
  if (!topic) return allProposed(t) || null;
  return (t ? [...t.topics, ...(t.project_topics || [])].find((x) => String(x.id) === topic)?.proposed : 0) || null;
}
/** the topic Watch's pages are for: the address's, All topics on its pages, else the last
 * topic you looked at (the first with none yet); null topic and all false: no topics at all */
export function watchScope(r: Route): { topic: string | null; name: string; page: WatchPage | null; all: boolean } {
  const path = r.path.join("/"), s = scopeOf(r.path);
  // Add source from a topic is that topic's Sources; from All topics', theirs
  if (path === "settings/sources/new") return r.q.topic ? { topic: r.q.topic, name: topicName(r.q.topic), page: "sources", all: false } : { topic: null, name: "All topics", page: "sources", all: true };
  if (s?.topic) return { topic: s.topic, name: topicName(s.topic), page: s.page, all: false };
  if (s?.page) return { topic: null, name: "All topics", page: s.page, all: true };
  const last = lastTopic();
  return last ? { topic: String(last.id), name: last.name, page: null, all: false } : { topic: null, name: "All topics", page: null, all: false };
}

/* the doors: each door's subnav, three to five words, by route; the crumb is
   Home › the door's word. A topic's old pages are in their door too. */
export const DOOR_NAV: Record<string, { word: string; items: [string, string][] }> = {
  needs: { word: "Needs you", items: [] },
  activity: { word: "Activity", items: [] },
  // Watch's Sources, Evidence and Map are a topic's: doorFacts scopes them (watchScope)
  watch: { word: "Watch", items: [["watch", "Topics"], ["watch/sources", "Sources"], ["watch/evidence", "Evidence"], ["watch/map", "Map"]] },
  ideas: { word: "Ideas", items: [["ideas", "Cards"], ["ideas/review", "Review"]] },
  news: { word: "News", items: [["news", "Today"], ["news/earlier", "Earlier"], ["news/topics", "Topics"]] },
  // Post: the drafts that wait, what was sent, the accounts; one page
  post: { word: "Post", items: [] },
  settings: { word: "Settings", items: [["settings", "Overview"], ...DOORS_PAGES.map((k): [string, string] => ["settings/" + k, doorsPage(k)?.title || k])] },
};
/** a door's words and its subnav */
export function doorNav(id: string): { word: string; items: [string, string][] } {
  const d = DOOR_NAV[id]!;
  return { word: d.word, items: d.items.slice() };
}
// the posting cubs' pages are Post's ("the posting cubs are drawn as Post")
const DOOR_OF: Record<string, string> = { topics: "watch", library: "watch", review: "ideas", cubs: "post", cub: "post" };
/* pages kept on an old route that belong to another door's subnav word
   (Add topic and Add source stay pages this release, drawn under Watch): [door, subnav route] */
const PLACED: Record<string, [string, string]> = { "settings/sources/new": ["watch", "watch/sources"], "topics/new": ["watch", "watch"] };
/** the door a route is in, with the doors on */
export function doorId(path: string[]): string | null {
  const p0 = path[0] || "", placed = PLACED[path.join("/")];
  if (placed) return placed[0];
  return DOOR_NAV[p0] ? p0 : DOOR_OF[p0] || null;
}
function doorFacts(r: Route): DoorFacts | null {
  const id = doorId(r.path);
  if (!id) return null;
  // without the doors' frame (no server) Watch's pages still have the crumb, for the topic
  // switcher (the classic tree and the phone draw it the same)
  if (!frameNew(!!host())) return id === "watch" && shellDoors(!!host()) ? { ...watchFacts(r, DOOR_NAV.watch!.word, doorCounts()), crumbOnly: true } : null;
  const d = doorNav(id), here = r.path.join("/"), counts = doorCounts();
  if (id === "watch") return watchFacts(r, d.word, counts);
  const at = PLACED[here]?.[1] || d.items.map(([to]) => to).filter((to) => here === to || here.startsWith(to + "/")).sort((a, b) => b.length - a.length)[0] || null;
  return { id, word: d.word, items: d.items.map(([to, w]) => ({ to, w, n: counts[to]?.[0] ?? null, tone: counts[to]?.[1] || "", title: counts[to]?.[2] || null, on: to === at })) };
}
/** the door for the page's head */
function placeFacts(r: Route, door: DoorFacts | null): DoorFacts | null {
  if (!shellDoors(!!host())) return null;
  if (frameNew(!!host())) return door;
  const id = doorId(r.path);
  if (!id) return null;
  if (id === "watch") return { ...watchFacts(r, DOOR_NAV.watch!.word, doorCounts()), classic: true };
  const d = doorNav(id), here = r.path.join("/"), counts = doorCounts();
  const at = PLACED[here]?.[1] || d.items.map(([to]) => to).filter((to) => here === to || here.startsWith(to + "/")).sort((a, b) => b.length - a.length)[0] || null;
  return { id, word: d.word, classic: true, items: d.items.map(([to, w]) => ({ to, w, n: counts[to]?.[0] ?? null, tone: counts[to]?.[1] || "", title: counts[to]?.[2] || null, on: to === at })) };
}
/* Watch's subnav (WT, the owner's words): Topics · Sources · Evidence · Map, the last three the
   scoped topic's ("Topics · Robotics › Sources Evidence Map"), or All topics' on their pages; the
   crumb says "Watch › Robotics › Sources", its topic a switcher that keeps the page */
function watchFacts(r: Route, word: string, counts: ReturnType<typeof doorCounts>): DoorFacts {
  const s = watchScope(r), here = r.path.join("/"), on = s.topic != null || s.all ? s.page : null;
  const topics = (host()?.topics || []).map((x) => ({ id: String(x.id), name: x.name }));
  const items: DoorFacts["items"] = [{ to: "watch", w: "Topics", n: counts.watch?.[0] ?? null, tone: counts.watch?.[1] || "", title: counts.watch?.[2] || null, on: here === "watch" || here === "topics/new" }];
  for (const [k, w] of WATCH_PAGES) items.push({ to: watchPath(s.all ? null : s.topic, k), w, n: k === "sources" ? sourcesCount(s.all ? null : s.topic) : null, tone: "wait", title: null, on: on === k, sub: true });
  return { id: "watch", word, items, scope: { topic: s.topic, name: s.name, all: s.all, page: s.page, to: s.topic ? watchPath(s.topic, "") : null, on: !!s.topic && s.page === "", topics } };
}

/** the navigator's tree: the doors' (Nav.svelte draws it where the frame has a navigator) */
export function navTree(r: Route): NavFacts {
  return classicTree(r);
}

/* The status bar's service line (StatusBar.svelte draws it): the service in one
   word and a few cells. The word and why are the server's (health.py: `ingest.health` on
   /api/today), worked out once on the server so the page, the phone and the console say the same:
   Paused (watching paused, or the watcher's provider paused until a time), Degraded (no ingest
   yet, the last failed or had problems, more than one judge call in five failed) or Healthy. A
   pause clicked here shows at once, before the next read. With a server older than the health read the rule
   is worked out here, as before. */
const PAUSED = { icon: "paused", colour: "amber", text: "Paused" }, DEGRADED = { icon: "warn", colour: "amber", text: "Degraded" },
  HEALTHY = { icon: "check", colour: "green", text: "Healthy" },
  // a home with nothing watched yet: new, not broken (the server's health.py)
  NOT_SET_UP = { icon: "dot", colour: "grey", text: "Not set up yet" },
  // sources watched, no read ended yet: the first read, never Degraded (fix 7)
  FIRST_READ = { icon: "dot", colour: "grey", text: "Reading for the first time" };
function serviceWord(): Pick<Facts["bar"], "word" | "why"> {
  const t = todayNow(), svc = t ? t.ingest : null, hw = svc ? svc.health : null;
  const why = (text: string | null | undefined, href?: string | null) => (text ? { text, href: href || "#/settings/health" } : null);
  if (hw && hw.word) {
    if (hw.word !== "Paused" && afkPaused()) return { word: PAUSED, why: why("Watching is paused") };
    if (hw.word === "Not set up yet") return { word: NOT_SET_UP, why: why(hw.reason, "#/hello") };
    if (hw.word === "Reading for the first time") return { word: FIRST_READ, why: why(hw.reason, "#/home") };
    return { word: hw.word === "Paused" ? PAUSED : hw.word === "Degraded" ? DEGRADED : HEALTHY, why: hw.word === "Healthy" ? null : why(hw.reason, hw.trace) };
  }
  if (afkPaused() || (svc && svc.watch_paused)) return { word: PAUSED, why: null };
  if (svc && (!svc.last || ["failed", "degraded"].includes(svc.last.status) || (svc.judge_calls_24h && svc.judge_errors_24h / svc.judge_calls_24h > 0.2))) return { word: DEGRADED, why: null };
  return { word: HEALTHY, why: null };
}
function serviceLine(): Facts["bar"] {
  const H = host(), t = todayNow(), svc = t ? t.ingest : null;
  const wp = svc ? svc.watch_paused : null;
  const { word, why } = serviceWord();
  // the tokens the watcher used today (HOST.tokens_today): never dollars outside Settings › Spend
  const used = tokSum([H?.tokens_today]);
  const cells = svc ? [wp ? watchPaused(wp) : null, svc.last ? `ingest ${stamp(svc.last.finished_at).slice(11)} ${svc.last.status}` : "no ingest yet",
    svc.judge_calls_24h ? `judge errors ${svc.judge_errors_24h} of ${svc.judge_calls_24h}` : null]
    : [H ? "reading the server's health…" : "the server is not answering"];
  const size = svc ? `${plural(svc.sources, "source")} · ${plural(svc.topics, "topic")} · ${svc.observations.toLocaleString("en-GB")} observations` : null;
  // the live feed's places all taken: the page polls and says so
  const all = [...cells, livePaused() ? "live updates paused" : null];
  // the preview: a second Kranto on a copy of the owner's data says so on every page
  const preview = H?.preview?.line || null;
  return { word, why, used: used ? { text: tokText(used) + " today", title: tokTitle(used) || "" } : null, cells: all.filter((c): c is string => !!c), size, preview };
}
/** what the status bar's key hint says on this page (the shell's StatusBar.svelte words it) */
function hintFacts(): Facts["hint"] {
  const R = routeNow();
  return { rows: rowsNow().length > 0, grade: !!pageHas("1"), tick: !!document.querySelector("#rows input.tick"), term: !!pageHas("c"),
    review: !!(R && R.node === "review" && pageHas("0")), sections: sectionsNow() > 1 };
}
/** the header's update pill: "Update 0.1.0 → 0.2.0" (what's new in the tooltip), the step while
 * it runs, or the rollback */
function updatePill(): UpdateFacts | null {
  const u = updNow();
  if (!u) return null;
  if (updBusy(u)) return { icon: "running", colour: "blue", word: "Updating", detail: UPD_BUSY[u.state] || null, title: u.detail || `Updating to ${u.to}` };
  if (updBad(u)) return { icon: "warn", colour: "red", word: u.state === "failed" ? "Update failed" : "Update rolled back", detail: null, title: u.reason || "" };
  // the check has failed for more than two days (the server's check_failing): said, not silent
  if (u.check_failing && !u.available) return { icon: "warn", colour: "amber", word: "Can't check for updates", detail: tidyError(u.check_failing),
    title: `Can't check for updates since ${(u.failing_since || "").slice(0, 10)}: ${tidyError(u.check_failing)}. Click to see why and what to do.` };
  if (!u.available) return null;
  return { icon: "dot", colour: "blue", word: "Update", detail: `${u.installed} → ${u.available}`, title: ["What's new in " + u.available + ":", ...(u.notes || [])].join("\n") };
}
export function chromeFacts(r: Route): Facts | null {
  const H = host();
  if (!loaded()) return null;
  const paused = afkPaused() ? { afk: true, host: !!H } : null;
  const door = doorFacts(r);
  return {
    header: { host: H ? { paused: afkPaused(), running: H.running || null, next: (H.next_run || {}).ingest || null, reading: H.ingest_progress ? readingWords(H.ingest_progress) : null } : null,
      update: updatePill(), pauses: PAUSES, theme: { name: lookName(lookNow()), dark: isDark() } },
    nav: navTree(r), bar: serviceLine(), hint: hintFacts(), head: { paused, signin: signedOut(), flash: flashNow() }, door, place: placeFacts(r, door),
  };
}
