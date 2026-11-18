import { afterEach, describe, expect, it, vi } from "vitest";
import { TICKS } from "./proposals";
import type { Cluster, Observation, Observations, Source } from "../../api/afk.gen";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { drop, setFetcher } from "../../lib/reads.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { gradesPath, obsQuery } from "../library/library";
import { cardIdeas, citedBy, IDEAS_API, topicCardsApi } from "../ideas/cards";
import IdeasList from "../ideas/IdeasList.svelte";
import TopicList from "./TopicList.svelte";
import TopicPane from "./TopicPane.svelte";
import { startApi, topicApi, type Topic, type TopicPage, type TopicSource, type TopicTheme } from "./topics";

const NOW = new Date().toISOString();
const traj = [{ at: "2026-10-01T00:00:00Z", share: 0.1, size: 10 }, { at: "2026-10-08T00:00:00Z", share: 0.12, size: 12 }];
// The server's /api/topics (Topics is generated from its web/types.py) and one topic's page
const topic = (id: number, o: Partial<Topic> = {}): Topic => ({
  id, name: `Topic ${id}`, description: `What topic ${id} covers.`, kind: "user", ref: null, status: "active", created_at: NOW, sources: 2, proposed: 0,
  items_per_day: 20, kept_per_day: 5, observations: 120, themes: 1, rising: 1, spend_month_usd: 0.4, tokens_month: { in: 12000, out: 3000 }, ...o,
});
const theme = (cluster: number, o: Partial<Cluster> = {}): TopicTheme => ({
  snapshot_id: 7, cluster, lineage_id: "lin" + cluster, size: 40, share: 0.118, stories: 38, keywords: ["crdt"], name: null, name_call_id: null, label: `Theme ${cluster}`,
  source_mix: {}, topic_mix: {}, origin_mix: {}, max_source_share: 0.6, max_origin_share: null, cross_source: true, representatives: [], trajectory: traj, movement: null,
  rising: false, synthesis: null, grade: null, topic_share: 0.4, ...o,
});
const src = (id: number, o: Partial<TopicSource> = {}): TopicSource => ({
  id, kind: "rss", label: `Source ${id}`, origin: "manual", review: "approved", group: "approved", status: "ok", detail: "", site: "hn", site_name: "Hacker News",
  preset: null, fields: null, topics: [{ id: 1, name: "Topic 1" }], proposed_for: null, why: null, replaces: null, validation: {}, items_7d: 14, items_per_day: 2,
  kept_30d: 4, judged_30d: 10, kept_rate: 0.4, yield_per_day: 0.5, mute: null, last_fetch: NOW, last_error: null, retry_at: null, failing_runs: 0, backoff_until: null,
  needs_fixing: false, connection: null, retention_days: 90, note: null, proposed_topic: null, role: "core", pretick: false, items_per_day_7d: 2, ...o,
} as Source as TopicSource);
const PAGE: TopicPage = { ...topic(1, { proposed: 2 }), themes_list: [theme(5), theme(8, { rising: true, movement: { since: NOW, delta: 0.01, excess: null, points: 2, new_total: null,
  new_in_cluster: 3, expected_new: null, burst: null, entered_burst: false, p_value: null, q_value: null } })], rising_now: [theme(8, { rising: true })],
  snapshot: { id: 7, created_at: "2026-10-15T23:47:32Z" }, prefilter: 0.3, every_hours: 6, budget_usd: null, progress: "",
  grade_labels: { useful: "useful" }, grade_choices: ["useful", "not_useful", "wrong", "missed"], history: [],
  source_rows: [src(1, { yield_per_day: 0.9 }), src(2, { review: "retired", group: "retired", status: "retired" }), src(3, { review: "proposed", group: "proposed", status: "proposed", pretick: true }),
    src(4, { review: "proposed", group: "proposed", status: "proposed", role: "wildcard" })] };
const TODAY = { topics: [{ id: 1, name: "Topic 1", new_kept: 4 }] };
const obs = (id: number, o: Partial<Observation> = {}): Observation => ({
  id, kind: "beat", title: null, summary: `Observation ${id} says a thing.`, why_it_matters: "", content_quality: 0.5, durability: 0.5, opportunity: 0.5, signal: 0.31,
  override: false, override_reason: null, tags: [], source_url: null, source_excerpt: null, item_published_at: null, source_id: 1, source_label: "Source 1",
  admitted_by: "topic", created_at: NOW, llm_call_id: null, prompt_version: null, grade: null, ...o,
});
const EV: Observations = { total: 2, offset: 0, cluster_label: null, seen_at: null, marker: "", since: null, new_total: 1, results: [obs(7, { new: true }), obs(6)] };
const EV_TOP = "/api/observations?topic=1&since=last&sort=signal&limit=5";

const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
// The server's cards (/api/ideas): three from Topic 1, each with its own state: 4 passed
const card = (n: number, state = "waiting") => ({ number: n, title: "Card " + n, status: "shown", score: 0.5, topics: [{ id: 1, name: "Topic 1", share: 0.5 }], citations: [], state });
const CARDS = { "/api/ideas?embedding=ref": [card(3), card(9), card(4, "passed")] };
// a new topic's first hour (the server's /api/topics/1/start,)
const START = { topic_id: 1, done: false, observations: 4, needed: 30, quiet: "A quiet topic takes longer. One item in the first read is few. Scout more sources or widen the sentence, and ideas come sooner.",
  rows: [{ key: "sources", title: "Sources", state: "done", words: "2 sources watched", at: "2026-11-11T09:00:00Z" },
    { key: "read", title: "First read", state: "done", words: "Kept 1 of 6 items read", at: "2026-11-11T09:20:00Z" },
    { key: "brief", title: "First brief", state: "done", words: "1 item", at: "2026-11-11T09:30:00Z", brief_id: 12 },
    { key: "ideas", title: "First ideas", state: "waiting", words: "After the map, once 30 items are kept. So far: 4.", at: null }] };
const at = (path: string, q: Record<string, string> = {}, sel: string | null = null): Where => ({ ...where(path, sel), r: { path: path.split("/"), q, sel } });
/** a list's group by its heading's id */
const grp = (t: HTMLElement, id: string): HTMLElement => t.querySelector("#" + id)!.closest("section")!;

/** the old module, stubbed with what the topics' pages place of it */
function old(o: Parameters<typeof stub>[0] = {}) {
  const L = stub({ host: { topics: [{ id: 1, name: "Topic 1" }], sources: [{ id: 1, kind: "rss", label: "Source 1", status: "approved" }, { id: 9, kind: "rss", label: "Elsewhere", status: "approved" }] }, ...o });
  const fns = {
    sigOf: (n: Element) => n.className + "|" + (n.textContent || ""),
    pageKey: vi.fn(), menu: vi.fn(), loadHost: vi.fn(async () => {}), afkDrop: vi.fn(), tip: () => null,
  };
  Object.assign(L, fns);
  hosted();
  return { L, ...fns };
}

describe("Topics", () => {
  // the list of every topic is Watch › Topics (watch/Topics.svelte) in either layout: the old
  // Topics page went with the layouts' one set of pages (track)
  it("says a topic it does not have", async () => {
    old();
    answering({});
    const gone = await draw(TopicList, at("topics/77/themes"));
    expect(gone.target.querySelector(".wl")?.getAttribute("data-title")).toBe("Topic");
    expect(gone.target.querySelector("h1")?.textContent).toBe("Themes");
    expect(gone.target.querySelector("p.empty")?.textContent).toBe("No topic 77."); // the server's 404 says not found
    gone.done();
    // any other failure says what it was
    old();
    drop(topicApi(1));
    setFetcher(async () => { throw new Error("the server is restarting"); });
    const down = await draw(TopicList, at("topics/1"));
    expect(down.target.querySelector(".failed .why")?.textContent).toBe("Could not read Kranto: the server is restarting");
    down.done();
  });

  it("draws a topic's Overview: sources, themes, ideas waiting and top evidence", async () => {
    old();
    answering({ ...CARDS, [topicApi(1)]: PAGE, "/api/today": TODAY, [EV_TOP]: EV, [gradesPath([7, 6])]: { grades: {} } });
    const { target, done } = await draw(TopicList, at("topics/1"));
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Topic 1");
    expect(target.querySelector("h1")?.textContent).toBe("Overview");
    expect(target.querySelector(".tbn > span")?.textContent).toBe("4 new since your visit · 2 sources · 5 kept a day");
    expect(target.querySelector("#proposed-link")?.getAttribute("href")).toBe("#/topics/1/sources");
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Sources", "Rising themes", "Ideas waiting", "Top evidence, new since your visit"]);
    // its sources first: the proposals, Approve on each (the first the one primary) and
    // Dismiss, then the watched ones that keep the most; All N › is the topic's Sources
    const so = grp(target, "ov-sources");
    expect(so.querySelector(".g-says")?.textContent).toBe("2 watched · 2 proposed");
    expect([...so.querySelectorAll("li.row")].map((r) => (r as HTMLElement).dataset.sel)).toEqual(["s3", "s4", "s1"]);
    expect([...so.querySelectorAll("li.row .r-act button")].map((b) => b.textContent + (b.classList.contains("primary") ? "*" : ""))).toEqual(["Approve*", "✕", "Approve", "✕", "⋯"]);   // Dismiss is a quiet ✕ (D-4)
    expect(so.querySelector("#ov-sources-all")?.getAttribute("href")).toBe("#/topics/1/sources");
    expect(so.querySelector("#ov-sources-all")?.textContent).toBe("All 2 ›");
    // the themes: rising first, the topic's share
    const th = [...grp(target, "ov-themes").querySelectorAll("li.row")] as HTMLElement[];
    expect(th.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Theme 8", "Theme 5"]);
    expect(th[0]!.querySelector(".c-meta")?.textContent).toBe("rising · cross-source · 40% from this topic · +1.00 pts");
    // the ideas waiting are Ideas' card rows; Pass and Later are on the card's sheet
    const id = [...grp(target, "ov-ideas").querySelectorAll("li.row")] as HTMLElement[];
    expect(id.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Card 3", "Card 9"]);
    // a card's row links the card by its number and says its own state
    expect(id[0]!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/ideas/3");
    expect(id[0]!.querySelector(".c-num")?.textContent).toBe("#3");
    expect(id[0]!.querySelector(".c-meta")?.textContent).toBe("waiting · 50% from this topic");
    expect(id[0]!.querySelector('.grade[data-grade="idea:3"]')?.getAttribute("aria-label")).toBe("Grade card #3");
    expect(id.map((r) => r.querySelector(".r-act"))).toEqual([null, null]);
    expect(id[1]!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/ideas/9");
    expect(grp(target, "ov-ideas").querySelector(".ghd a")?.textContent).toBe("All 3");
    expect(target.querySelector("#ov-builds")).toBeNull();
    // the evidence: new since your visit, by signal, each with its grade
    const ev = [...grp(target, "ov-ev").querySelectorAll("li.row")] as HTMLElement[];
    expect(ev.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Observation 7 says a thing.", "Observation 6 says a thing."]);
    expect(grp(target, "ov-ev").querySelector(".ghd .n")?.textContent).toBe("4");
    expect(grp(target, "ov-ev").querySelector(".ghd a")?.getAttribute("href")).toBe("#/topics/1/evidence?since=last&sort=signal");
    expect(ev[1]!.querySelector('.grade[data-grade="observation:6"]')?.getAttribute("aria-label")).toBe("Grade #6");
    done();
  });

  it("a watched row's ⋯: Remove from <topic> first (this topic only), then the verbs that act everywhere (the owner's O-1)", async () => {
    const { L, menu } = old({ answer: { id: 1, added: [], removed: [1], retired: [], approved: [], remaining: { 1: [{ id: 2, name: "Storage", kind: "user" }] } } });
    const shared = { ...PAGE, source_rows: [src(1, { yield_per_day: 0.9, topics: [{ id: 1, name: "Topic 1", kind: "user" }, { id: 2, name: "Storage", kind: "user" }] }), src(5, { yield_per_day: 0.2 })] };
    answering({ ...CARDS, [topicApi(1)]: shared, "/api/today": TODAY, [EV_TOP]: EV, [gradesPath([7, 6])]: { grades: {} } });
    const { target, done } = await draw(TopicList, at("topics/1"));
    const rows = [...grp(target, "ov-sources").querySelectorAll("li.row")] as HTMLElement[];
    expect(rows[0]!.querySelector(".c-meta")?.textContent).toBe("also feeds Storage");   // its one fact
    (rows[0]!.querySelector(".row-more") as HTMLButtonElement).click();
    const items = (menu.mock.calls.at(-1) as unknown as [unknown, { label: string; note?: string | null; run: () => void }[]])[1];
    expect(items.map((x) => [x.label, x.note])).toEqual([["Remove from Topic 1", "It keeps feeding Storage"], ["Mute for 7 days", "everywhere: all 2 topics"],
      ["Read less", "everywhere: all 2 topics"], ["Retire", "everywhere: all 2 topics"]]);
    items[0]!.run();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/1/sources", { remove: [1], origin: "ui" });
    expect((L.toast.mock.calls.at(-1) as [string])[0]).toBe("Removed Source 1 from Topic 1. It still feeds Storage.");
    // its only topic: Remove says Kranto stops reading it, and no reach on the rest
    (rows[1]!.querySelector(".row-more") as HTMLButtonElement).click();
    const solo = (menu.mock.calls.at(-1) as unknown as [unknown, { label: string; note?: string | null }[]])[1];
    expect(solo.map((x) => x.note)).toEqual(["It has no other topic: Kranto stops reading it (as Retire)", null, null, null]);
    done();
  });

  it("says when a topic is paused, has no map, no open idea and nothing kept", async () => {
    old();
    const quiet = { ...PAGE, status: "paused" as const, themes: 0, rising: 0, themes_list: [], snapshot: null, progress: "The first map is drawn at 300 observations.", sources: 0, source_rows: [] };
    answering({ [IDEAS_API]: [], [topicApi(1)]: quiet, "/api/today": { topics: [] }, "/api/observations?topic=1&sort=signal&limit=5": { ...EV, results: [], total: 0 }, [startApi(1)]: START });
    const { target, done } = await draw(TopicList, at("topics/1"));
    await settle();
    expect(target.querySelector(".flash.amber")?.textContent).toBe("Paused: this topic's sources are not read. Its evidence, themes and ideas stay. Resume it from the topic's pane.");
    expect(target.querySelector(".flash.blue")).toBeNull();      // the first hour's rows say it now
    const start = [...grp(target, "topic-start").querySelectorAll("li.row")] as HTMLElement[];
    expect(start.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Sources", "First read", "First brief", "First ideas"]);
    expect(start.map((r) => r.querySelector(".gl")?.getAttribute("aria-label"))).toEqual(["Done", "Done", "Done", "Next"]);
    expect(start[2]!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/news/b/12");
    expect(start[3]!.querySelector(".c-meta")?.textContent).toBe("After the map, once 30 items are kept. So far: 4.");
    expect(grp(target, "topic-start").querySelector(".ghd .n")?.textContent).toBe("3 of 4");
    expect([...target.querySelectorAll(".grp p.more")].map((p) => p.textContent)).toEqual([START.quiet, "No source yet: Add source, or Scout more.", "No map yet, so no themes.", "No open ideas from this topic.", "Nothing kept from this topic yet."]);
    done();
  });

  it("lists a topic's Themes, Map and Ideas", async () => {
    old();
    answering({ [topicApi(1)]: PAGE });
    const th = await draw(TopicList, at("topics/1/themes"));
    expect(th.target.querySelector(".wl")?.getAttribute("data-title")).toBe("Topic 1 · Themes");
    expect(th.target.querySelector(".ghd .muted")?.textContent).toBe("mapped 2026-10-15 · ");
    expect([...th.target.querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["Theme 8", "Theme 5"]);
    // watches are retired (WT): a theme's row has no Watch
    expect(th.target.querySelector("li.row .r-act button")).toBeNull();
    th.done();
    // the topic's Map (#/watch/topic/1/map): its themes, titled by the topic, the map above them
    old();
    answering({ [topicApi(1)]: PAGE });
    const map = await draw(TopicList, at("topics/1/map"));
    expect(map.target.querySelector("h1")?.textContent).toBe("Topic 1 › Map");
    expect(map.target.querySelector(".wl")?.getAttribute("data-title")).toBe("Topic 1 › Map");
    expect([...map.target.querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["Theme 8", "Theme 5"]);
    expect(map.target.querySelector(".ghd a")?.getAttribute("href")).toBe("#/watch/map");
    map.done();
    old();
    answering({ ...CARDS, [topicApi(1)]: PAGE });
    const ideas = await draw(TopicList, at("topics/1/ideas"));
    expect(ideas.target.querySelector(".tbn > span")?.textContent).toBe("3 ideas");
    expect([...ideas.target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Waiting", "Passed"]);
    expect([...ideas.target.querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["Card 9", "Card 3", "Card 4"]);
    expect([...ideas.target.querySelectorAll("li.row .gl")].map((x) => x.getAttribute("aria-label"))).toEqual(["Waiting", "Waiting", "Passed"]);
    expect(ideas.target.querySelectorAll("li.row .r-act button").length).toBe(0); // the verbs are the card's sheet's
    ideas.done();
  });

  it("lists a topic's Sources: the proposals with Watch these, then its sources by group", async () => {
    const { L } = old();
    answering({ [topicApi(1)]: PAGE, [`/api/feedback?target=source&ids=1,2,3,4`]: { grades: {} } });
    const { target, done } = await draw(TopicList, at("topics/1/sources"));
    // "<topic> › Sources" (WT), the topic's own numbers in one line, Add source to it
    expect(target.querySelector("h1")?.textContent).toBe("Topic 1 › Sources");
    expect(target.querySelector("#topic-sources-facts")?.textContent).toBe("2 watched · 20 items a day, 25% kept · 15k tokens this month · 2 proposed");
    expect(target.querySelector(".tbn a.btn")?.getAttribute("href")).toBe("#/settings/sources/new?topic=1");
    expect(target.querySelector(".tbn a.btn")?.textContent).toBe("Add source to Topic 1");
    expect(target.querySelector("#topic-sources-edit")?.textContent).toBe("Edit the topic");
    // the proposals: the close match first and ticked for you, the wildcard last; Approve on each
    const props = target.querySelector("section.grp.props.approve")!;
    expect([...props.querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["Source 3", "Source 4"]);
    expect([...props.querySelectorAll("li.row .gl")].map((x) => x.getAttribute("aria-label"))).toEqual(["Fits well", "Further afield"]);
    expect([...props.querySelectorAll("li.row .r-act button")].map((x) => x.textContent + (x.classList.contains("primary") ? "*" : ""))).toEqual(["Approve*", "Approve"]);
    expect(TICKS[1]).toEqual(new Set([3]));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Proposed", "Watched", "Retired"]);
    // each group says what it means beside its heading, not behind a ?
    expect(grp(target, "src-approved").querySelector(".g-says")?.textContent).toBe("read every run for Topic 1; its items are compared with Topic 1 before any model call");
    expect([...target.querySelectorAll("li.row")].map((r) => (r as HTMLElement).dataset.sel)).toEqual(["s3", "s4", "s1", "s2"]);
    (target.querySelector("#watch-these") as HTMLButtonElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => String(c[0]).startsWith("/api/sources"))).toEqual([["/api/sources/approve", { ids: [3], topic: 1 }]]);
    expect(L.say).toHaveBeenCalledWith("Watching 1 more source for Topic 1. Their first fetch is the next ingest run.");
    expect(TICKS[1]).toBeUndefined();
    done();
  });

  it("approves a proposal from its row for the topic, a wildcard with no topic", async () => {
    const { L } = old();
    answering({ [topicApi(1)]: PAGE, [`/api/feedback?target=source&ids=1,2,3,4`]: { grades: {} } });
    const { target, done } = await draw(TopicList, at("topics/1/sources"));
    const approve = [...target.querySelectorAll("section.grp.props li.row .r-act button")] as HTMLButtonElement[];
    approve[0]!.click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/sources", { id: 3, status: "approved", topic: 1 });
    expect(L.toast).toHaveBeenLastCalledWith("Watching Source 3 for Topic 1. Its first fetch is the next ingest run.");
    approve[1]!.click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/sources", { id: 4, status: "approved", topic: null });
    expect(L.toast).toHaveBeenLastCalledWith("Watching Source 4 with no topic (a wildcard: every item is judged). Its first fetch is the next ingest run.");
    expect(L.afkStale).toHaveBeenCalledWith("/api/today", "/api/sources", "/api/topics");
    delete TICKS[1]; // the close match ticked for you, left for the next test
    done();
  });

  it("is the library's list with the topic fixed on its Evidence", async () => {
    old();
    const qq = obsQuery({ topic: "1" });
    answering({ [topicApi(1)]: PAGE, [qq.path]: EV, [gradesPath([7, 6])]: { grades: {} } });
    const { target, done } = await draw(TopicList, at("topics/1/evidence"));
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Topic 1 · Evidence");
    expect(target.querySelector("h1")?.textContent).toBe("Evidence");
    expect(target.querySelector(".lh .muted")?.textContent).toBe("Topic 1");
    expect((target.querySelector("#search") as HTMLInputElement).placeholder).toBe("Ask this topic's evidence  ( / )");
    (target.querySelector("#filter") as HTMLButtonElement).click();
    expect([...document.querySelectorAll(".pop.filters select")].map((x) => x.id)).toEqual(["fpop-by", "fpop-since", "fpop-source", "fpop-kind", "fpop-min_signal"]);
    expect([...document.querySelectorAll("#fpop-source option")].map((x) => x.textContent)).toEqual(["all", "Source 1"]);
    expect(target.querySelectorAll(".tbn select.tb-f").length).toBe(1); // the sort stays inline
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["New since your last visit", "Seen before"]);
    done();
  });
});

describe("Topics, the pane", () => {
  it("shows the topic on its pages: facts (the sources' number a link), rising now, and its verbs", async () => {
    old();
    answering({ [topicApi(1)]: PAGE, "/api/today": TODAY });
    const { target, done } = await draw(TopicPane, at("topics/1/themes"));
    expect(target.querySelector(".dk")?.textContent).toBe(" topic · active");
    expect(target.querySelector(".dt")?.textContent).toBe("Topic 1");
    expect(target.querySelector(".lede")?.textContent).toBe("What topic 1 covers.");
    expect([...target.querySelectorAll(".acts .btn")].map((b) => b.textContent)).toEqual(["Edit", "Add source", "Scout more", "⋯"]);
    expect([...target.querySelectorAll(".fact dd")].map((x) => x.textContent)).toEqual(["4", "2", "5", "15k tokens"]);
    expect([...target.querySelectorAll(".fact small")].map((x) => x.textContent)).toEqual(["kept · 1 rising theme", "2 proposed, waiting for you", "of 20 fetched · 25% kept", "judging this topic's items"]);
    expect(target.querySelector(".fact small a")?.getAttribute("href")).toBe("#/topics/1/evidence?since=last");
    expect([...target.querySelectorAll("#s-rising li.row .r-title")].map((x) => x.textContent)).toEqual(["Theme 8"]);
    // the sources' number is the way to the topic's Sources; Best sources is retired (the owner's O-2)
    expect(target.querySelector("#topic-sources-link")?.getAttribute("href")).toBe("#/topics/1/sources");
    expect(target.querySelector("#s-best")).toBeNull();
    expect([...target.querySelectorAll(".toc a")].map((a) => a.firstChild?.textContent)).toEqual(["Facts", "Rising now"]);
    done();
  });

  it("jumps to a section from the outline without changing the route", async () => {
    const { L } = old();
    const spyJump = vi.fn();
    Object.assign(L, { spyJump });
    answering({ [topicApi(1)]: PAGE, "/api/today": TODAY });
    history.replaceState(null, "", "#/topics/1/themes");
    const { target, done } = await draw(TopicPane, at("topics/1/themes"));
    expect(target.querySelector("nav.toc")?.getAttribute("aria-label")).toBe("On this page");
    const link = [...target.querySelectorAll(".toc a")].find((a) => a.getAttribute("href") === "#s-rising")!;
    const e = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
    expect(location.hash).toBe("#/topics/1/themes");
    expect(spyJump).toHaveBeenCalledWith(target.querySelector("#s-rising"));
    done();
  });

  it("Scout more ticks the close matches and opens the topic's Sources; Pause pauses it", async () => {
    const { L, loadHost, menu } = old({ answer: { proposals: [{ id: 9, label: "New", pretick: true }, { id: 10, label: "Far", pretick: false }], message: "Proposed 2." } });
    answering({ [topicApi(1)]: PAGE, "/api/today": TODAY });
    const { target, done } = await draw(TopicPane, at("topics/1"));
    // its own page: Edit, Add source and Scout more; Pause, Archive under ⋯
    expect([...target.querySelectorAll(".acts .btn")].map((b) => b.textContent)).toEqual(["Edit", "Add source", "Scout more", "⋯"]);
    (target.querySelector("#scout-more") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/topics/1/scout", {});
    expect(TICKS[1]).toEqual(new Set([9]));
    expect(location.hash).toBe("#/topics/1/sources");
    expect(L.say).toHaveBeenCalledWith("Proposed 2. Tick what to watch under Proposed.");
    (target.querySelector(".acts .more") as HTMLButtonElement).click();
    const items = (menu.mock.calls[0] as unknown as [unknown, { label: string; id: string; run: () => void }[]])[1];
    expect(items.map((x) => x.label)).toEqual(["Pause topic", "Archive"]);
    items.find((x) => x.id === "pause-topic")!.run();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/topics/1/status", { status: "paused" });
    expect(loadHost).toHaveBeenCalled();
    expect(L.say).toHaveBeenLastCalledWith("Topic 1 is paused: its sources are not read until you resume it. Nothing is removed.");
    done();
  });

  it("a Topics row is its topic, with Open the topic and the rest under ⋯", async () => {
    const { menu } = old();
    answering({ [topicApi(2)]: { ...PAGE, ...topic(2, { status: "paused" }) }, "/api/today": TODAY });
    const { target, done } = await draw(TopicPane, at("topics", {}, "t2"), "#/topics");
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/topics");
    expect([...target.querySelectorAll(".acts .btn")].map((b) => b.textContent)).toEqual(["Open the topic", "Edit", "⋯"]);
    expect(target.querySelector(".note.c-amber")?.textContent).toBe("Paused: this topic's sources are not read. Its evidence, themes and ideas stay. Click Resume topic to read again.");
    expect(target.querySelector(".fact small")?.textContent).toBe("reading…");
    (target.querySelector(".acts .more") as HTMLButtonElement).click();
    expect((menu.mock.calls[0] as unknown as [unknown, { label: string }[]])[1].map((x) => x.label)).toEqual(["Add source", "Scout more", "Resume topic", "Archive"]);
    done();
  });

  it("says Nothing selected on the Topics node, a topic it does not have, and needs the server", async () => {
    old();
    answering({});
    const none = await draw(TopicPane, at("topics"));
    expect(none.target.querySelector(".pane-empty")?.textContent).toBe("Nothing selected.");
    none.done();
    old();
    answering({ "/api/today": TODAY });
    const gone = await draw(TopicPane, at("topics", {}, "t77"));
    expect(gone.target.querySelector(".pane-in")?.textContent).toBe("No topic 77.");
    gone.done();
    stub();
    ui.facts = null;
    answering({});
    const off = await draw(TopicPane, at("topics", {}, "t1"));
    expect(off.target.querySelector(".pane-empty")?.textContent).toBe("This comes from the server, which is not answering.");
    off.done();
  });
});

describe("a topic's cards", () => {
  it("come through the server's ideas API alone; a card cites by its citations or its evidence", async () => {
    old();
    answering({ [IDEAS_API]: [
      { number: 3, title: "Card 3", status: "waiting", score: 0.5, topics: [{ id: "1", name: "Topic 1", share: 0.5 }], output_kind: "app", citations: [{ observation_id: 7 }] },
      { id: 9, title: "Card 9", status: "shown", output_kind: "dataset", evidence: [{ observation_id: 8, source: "Source 1" }] }] });
    cardIdeas();
    await settle();
    const api = cardIdeas()!;
    expect(api.from).toBe("api");
    // card 9 numbered by its id
    expect(api.list.map((x) => [x.number, x.cited, x.waiting])).toEqual([[3, 1, true], [9, 1, false]]);
    expect(api.list[0]!.topics).toEqual([{ id: 1, name: "Topic 1", share: 0.5 }]);
    expect(citedBy(7)?.map((x) => x.number)).toEqual([3]);
    expect(citedBy("8")?.map((x) => x.number)).toEqual([9]);
    expect(citedBy(1)).toEqual([]);
    // no ideas API: no cards, never another source of them
    drop(IDEAS_API);
    answering({});
    cardIdeas();
    await settle();
    expect(cardIdeas()).toBeNull();
  });

  it("are read from the server's own filter on the topic's pages and Ideas with ?topic=, never every card", async () => {
    old();
    const asked: string[] = [];
    const answers: Record<string, unknown> = { [topicCardsApi(1)]: [card(3), card(9)], [topicApi(1)]: PAGE, "/api/today": TODAY, [EV_TOP]: EV, [gradesPath([7, 6])]: { grades: {} } };
    for (const k of [IDEAS_API, ...Object.keys(answers)]) drop(k);
    setFetcher(async (p) => {
      asked.push(p);
      if (!(p in answers)) throw new Error("not found: " + p);
      return structuredClone(answers[p]);
    });
    const page = await draw(TopicList, at("topics/1"));
    await settle();
    expect(asked).toContain("/api/ideas?topic=1&embedding=ref");
    expect(asked).not.toContain(IDEAS_API);
    expect([...grp(page.target, "ov-ideas").querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["Card 3", "Card 9"]);
    page.done();
    old();
    asked.length = 0;
    drop(topicCardsApi(1));
    const list = await draw(IdeasList, at("ideas", { topic: "1" }));
    await settle();
    expect(asked).toEqual(expect.arrayContaining(["/api/ideas?topic=1&embedding=ref"]));
    expect(asked).not.toContain(IDEAS_API);
    // Ideas with ?topic= is the topic's cards, one group
    expect([...list.target.querySelectorAll("[aria-labelledby=id-match] li.row .r-title")].map((x) => x.textContent)).toEqual(["Card 3", "Card 9"]);
    list.done();
  });
});
