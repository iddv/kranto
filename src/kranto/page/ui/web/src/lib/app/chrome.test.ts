// The chrome's facts (chrome.ts): the navigator's tree, the status bar, the header's lanes and its
// update pill, the list's head.
import { afterEach, describe, expect, it } from "vitest";
import { parse } from "../router";
import { NAVOPEN_T } from "../shell.svelte";
import { chromeFacts, navTree } from "./chrome";
import { frame, hostStatus, tick, unframe } from "./testing";

afterEach(() => {
  NAVOPEN_T.clear();
  unframe();
});
const TODAY = { since: null, ingest: { last: { status: "ok", finished_at: "2026-10-16T09:00:00Z" }, judge_calls_24h: 10, judge_errors_24h: 1, sources: 3, topics: 1, observations: 1234 },
  topics: [{ id: 1, name: "Clinics", new_kept: 4, proposed: 2 }, { id: 2, name: "Local-first", new_kept: 0, proposed: 0 }], messages: [] };
const facts = () => chromeFacts(parse())!;

describe("the navigator: one tree of the doors' pages, the cubs in it", () => {
  const SHELL = { layout: "classic", pins: ["toot"], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };
  const cub = (id: string, title: string, enabled: boolean, open: number) => ({ id, title, says: "", version: "1.0.0", trust: "owner", enabled, mode: "dry run", tickets_open: open, manifest: { ui: { nav: [], cards: {} } } });
  const FEATURES = { api: "kranto-mod/1", reads: [], request_kinds: [],
    features: [cub("news", "News", true, 0), cub("digest", "Digest", true, 1), cub("toot", "Toot the pick", true, 2), cub("sleepy", "Sleepy", false, 0)] };
  async function tree(hash: string) {
    await frame({ hash, reads: { "/api/shell": SHELL, "/api/features": FEATURES, "/api/today": TODAY, "/api/topics?kind=project": { topics: [] } } });
    navTree(parse());
    await tick();
    navTree(parse());
    await tick();
    return navTree(parse());
  }
  it("is Home, Needs you, the doors' words, Cubs and Settings, with the entry lit", async () => {
    let t = await tree("#/ideas");
    expect(t.rows.slice(0, 2).map((x) => x.w)).toEqual(["Home", "Needs you"]);
    expect(t.rows.filter((x) => x.head).map((x) => x.head)).toEqual(["Watch", "Ideas", "News", "Features", "Settings"]);
    const under = (head: string) => {
      const i = t.rows.findIndex((x) => x.head === head);
      const j = t.rows.findIndex((x, k) => k > i && x.head);
      return t.rows.slice(i + 1, j < 0 ? undefined : j).filter((x) => !x.sub).map((x) => x.w);
    };
    // Watch is topic-first: Topics, each topic, the scoped one's Sources, Evidence and Map
    // under it (the last topic looked at; with none, the first), then All topics
    expect(under("Watch")).toEqual(["Topics"]);
    expect(t.rows.find((x) => x.head === "Watch")).toMatchObject({ to: "topics", add: "topics/new" });
    const watchRows = t.rows.slice(t.rows.findIndex((x) => x.head === "Watch") + 1, t.rows.findIndex((x) => x.head === "Ideas")).map((x) => [x.to, x.w, !!x.deep]);
    expect(watchRows).toEqual([["watch", "Topics", false], ["watch/topic/1", "Clinics", false], ["watch/topic/1/sources", "Sources", true], ["watch/topic/1/evidence", "Evidence", true],
      ["watch/topic/1/map", "Map", true], ["watch/topic/2", "Local-first", false], ["watch/evidence", "All topics", false]]);
    expect(under("Ideas")).toEqual(["Cards", "Review"]);
    expect(under("News")).toEqual(["Today", "Earlier", "Topics"]);
    expect(t.here).toBe("ideas");
    expect(t.rows.find((x) => x.to === "watch/topic/1")).toMatchObject({ sub: true });
    expect(t.rows.find((x) => x.to === "needs")).toMatchObject({ key: "g t", hot: true });
    t = await tree("#/watch/topic/1");
    expect(t.here).toBe("watch/topic/1");
    t = await tree("#/watch/topic/1/map");
    expect(t.here).toBe("watch/topic/1/map");
    // All topics' pages show under All topics while one is open, and no topic's do
    t = await tree("#/watch/sources");
    expect(t.here).toBe("watch/sources");
    expect(t.rows.filter((x) => x.deep).map((x) => x.to)).toEqual(["watch/sources", "watch/evidence", "watch/map"]);
    expect(t.rows.find((x) => x.w === "All topics")).toMatchObject({ fold: true });
    expect(t.rows.some((x) => /^(build|builds|projects)/.test(x.to || ""))).toBe(false);
  });
  it("has a Cubs row with what they ask you, then each cub that is on, in the home's order", async () => {
    const t = await tree("#/cub/digest");
    expect(t.rows.find((x) => x.head === "Features")).toMatchObject({ to: "cubs", n: 3, tone: "wait" });
    expect(t.rows.filter((x) => x.to.startsWith("cub/")).map((x) => [x.w, x.n])).toEqual([["Toot the pick", 2], ["Digest", 1]]);
    expect(t.rows.some((x) => x.to === "cub/news" || x.to === "cub/sleepy")).toBe(false); // a door, and a cub that is off
    expect(t.rows.find((x) => x.to === "cubs/approvals")).toMatchObject({ w: "Approvals", n: 3 });
    expect(t.here).toBe("cub/digest");
  });
  it("opens Settings' pages under its head while one is open, Advanced last", async () => {
    let t = await tree("#/needs");
    expect(t.rows.some((x) => x.to === "settings/appearance")).toBe(false);
    t = await tree("#/settings/appearance");
    const set = t.rows.slice(t.rows.findIndex((x) => x.head === "Settings") + 1).map((x) => x.to);
    // the seven pages, then Advanced: Prompts
    expect(set.slice(0, 8)).toEqual(["settings/watching", "settings/posting", "settings/assistant", "settings/spend", "settings/privacy", "settings/system", "settings/appearance", "settings/prompts"]);
    // then every feature's and cub's own page, as Settings' Features group lists them
    expect(set.slice(8).every((to) => /^settings\/[a-z][a-z0-9_]+$/.test(to))).toBe(true);
    expect(t.here).toBe("settings/appearance");
  });
  it("has no topics, no Add topic and no cubs without the server", async () => {
    await frame({ host: null });
    const t = navTree(parse());
    expect(t.rows.find((x) => x.head === "Watch")).toMatchObject({ add: null });
    expect(t.rows.some((x) => (x.to || "").startsWith("watch/topic/"))).toBe(false);
    expect(t.rows.some((x) => x.head === "Features" || x.head === "News")).toBe(false);
  });
});

describe("the status bar", () => {
  it("says the service in one word, today's tokens and the server's health", async () => {
    await frame({ reads: { "/api/today": TODAY } });
    chromeFacts(parse());
    await tick();
    const b = facts().bar;
    expect(b.word).toEqual({ icon: "check", colour: "green", text: "Healthy" });
    expect(b.used).toEqual({ text: "150 tokens today", title: "100 in · 50 out" }); // the watcher's
    expect(b.cells).toEqual(["ingest 09:00 ok", "judge errors 1 of 10"]);
    expect(b.size).toBe("3 sources · 1 topic · 1,234 observations");
  });

  it("says Paused, and until when, while the watcher's provider has paused it", async () => {
    const paused = { ...TODAY, ingest: { ...TODAY.ingest, watch_paused: { until: "2026-11-01T00:00:00Z",
      reason: "spend limit set in the Claude Console reached: You have reached your specified API usage limits", provider: "anthropic" } } };
    await frame({ reads: { "/api/today": paused } });
    chromeFacts(parse());
    await tick();
    const b = facts().bar;
    expect(b.word).toEqual({ icon: "paused", colour: "amber", text: "Paused" });
    expect(b.cells[0]).toBe("Watching paused until 2026-11-01 00:00 (spend limit set in the Claude Console reached)");
  });

  it("says Healthy without the server, and that server is not hosting the page; Paused while watching is", async () => {
    await frame({ host: null });
    expect(facts().bar.word.text).toBe("Healthy");
    expect(facts().bar.cells).toEqual(["the server is not answering"]);
    expect(facts().bar.used).toBe(null);
    await frame({ host: hostStatus({ paused: "by hand" }) });
    expect(facts().bar.word).toEqual({ icon: "paused", colour: "amber", text: "Paused" });
  });

  // on live (2026-10-29) the owner saw Degraded and nothing said why; the word and its one
  // line are the server's now (health.py), the same answer the console reads
  const HW = { word: "Degraded", tone: "amber", reason: "The last read of your sources failed at 12:42: a safety filter at OpenRouter declined one item",
    at: "2026-10-29T12:42:41Z", run: "3ad8f80e82ef43f481c2aa8905c68e48", trace: "#/afk/3ad8f80e82ef43f481c2aa8905c68e48/trace" };
  it("says why it is Degraded, in the server's words, and opens that run's trace", async () => {
    // the browser's own rule would say Healthy here (the last ingest ok): the server's word wins
    await frame({ reads: { "/api/today": { ...TODAY, ingest: { ...TODAY.ingest, health: HW } } } });
    chromeFacts(parse());
    await tick();
    const b = facts().bar;
    expect(b.word).toEqual({ icon: "warn", colour: "amber", text: "Degraded" });
    expect(b.why).toEqual({ text: HW.reason, href: HW.trace });
  });

  // a fresh home's bar said "Degraded · Your sources have not been read yet" before
  // Welcome's first step; the server now says "Not set up yet", and the bar draws it grey, never Healthy
  it("says Not set up yet in grey on a home with nothing watched, and links to Welcome", async () => {
    const fresh = { word: "Not set up yet", tone: "grey", reason: "Choose a topic to watch on Welcome", at: null, run: null, trace: null };
    await frame({ reads: { "/api/today": { ...TODAY, ingest: { ...TODAY.ingest, health: fresh } } } });
    chromeFacts(parse());
    await tick();
    const b = facts().bar;
    expect(b.word).toEqual({ icon: "dot", colour: "grey", text: "Not set up yet" });
    expect(b.why).toEqual({ text: fresh.reason, href: "#/hello" });
  });

  // fix 7: watched, not read yet, is the first read: grey, never Degraded
  it("says Reading for the first time in grey during the first read, linking to the home", async () => {
    const reading = { word: "Reading for the first time", tone: "grey", reason: "Kranto is reading your sources for the first time", at: null, run: null, trace: null };
    await frame({ reads: { "/api/today": { ...TODAY, ingest: { ...TODAY.ingest, health: reading } } } });
    chromeFacts(parse());
    await tick();
    const b = facts().bar;
    expect(b.word).toEqual({ icon: "dot", colour: "grey", text: "Reading for the first time" });
    expect(b.why).toEqual({ text: reading.reason, href: "#/home" });
  });

  it("says nothing more when Healthy, and a pause clicked here at once", async () => {
    const ok = { ...TODAY, ingest: { ...TODAY.ingest, health: { ...HW, word: "Healthy", tone: "green", reason: null, run: null, trace: null } } };
    await frame({ reads: { "/api/today": ok } });
    chromeFacts(parse());
    await tick();
    expect(facts().bar.word.text).toBe("Healthy");
    expect(facts().bar.why).toBe(null);
    await frame({ reads: { "/api/today": ok }, host: hostStatus({ paused: "by hand" }) });
    chromeFacts(parse());
    await tick();
    expect(facts().bar.word.text).toBe("Paused");
    expect(facts().bar.why).toEqual({ text: "Watching is paused", href: "#/settings/health" });
  });
});

describe("the header and the list's head", () => {
  it("says what Kranto is doing and what Pause stops", async () => {
    const progress = { run_uuid: "r", started_at: "2026-10-17T03:00:00Z", sources: 8, source_index: 2, source: "Lobsters", items: 10, item: 4, done_items: 14, kept: 3 };
    await frame({ host: hostStatus({ running: "ingest", ingest_progress: progress, next_run: { ingest: "2026-10-17T06:00:00Z" } }) });
    const h = facts().header;
    expect(h.host).toEqual({ paused: false, running: "ingest", next: "2026-10-17T06:00:00Z", reading: "source 2 of 8, Lobsters · 4 of 10 items · 3 kept so far" });
    expect(h.pauses).toBe("reading sources and writing ideas");
    await frame({ host: null });
    expect(facts().header.host).toBe(null);
  });

  it("offers an update, says its step while it runs, and a rollback", async () => {
    const upd = (o: object) => hostStatus({ update: { ...hostStatus().update, ...o } });
    await frame({ host: upd({ available: "0.3.75", notes: ["Faster"] }) });
    expect(facts().header.update).toEqual({ icon: "dot", colour: "blue", word: "Update", detail: "0.3.74 → 0.3.75", title: "What's new in 0.3.75:\nFaster" });
    await frame({ host: upd({ state: "draining", to: "0.3.75" }) });
    expect(facts().header.update).toMatchObject({ icon: "running", word: "Updating", detail: "waiting for a job to finish", title: "Updating to 0.3.75" });
    await frame({ host: upd({ state: "rolled_back", reason: "the new version did not answer" }) });
    expect(facts().header.update).toEqual({ icon: "warn", colour: "red", word: "Update rolled back", detail: null, title: "the new version did not answer" });
    await frame({ host: upd({}) });
    expect(facts().header.update).toBe(null);
  });

  it("says what is paused and that this browser is not signed in", async () => {
    await frame({ host: hostStatus({ paused: "by hand" }), who: { origin: null, require_token: true } });
    expect(facts().head).toMatchObject({ paused: { afk: true, host: true }, signin: true });
    await frame({ who: { origin: "ann", require_token: true } });
    expect(facts().head).toMatchObject({ paused: null, signin: false });
  });
});

it("says what Watch's count counts: kept observations new since your visit, not topics", async () => {
  await frame({ hash: "#/watch", reads: { "/api/shell": { layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] }, "/api/today": { ...TODAY, new_kept: 4 },
    "/api/topics?kind=project": { topics: [] } } });
  facts();
  await tick();
  facts();
  await tick();
  const watch = facts().door?.items.find((x) => x.to === "watch");
  expect(watch).toMatchObject({ w: "Topics", n: 4, title: "4 kept observations new since your last visit" });
});
