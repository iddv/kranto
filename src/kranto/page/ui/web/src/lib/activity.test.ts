// What Kranto is doing, as data: the indicator's four states, a page's one line by
// subject, Needs you's Fix and waiting rows deduped against the rows that already offer the action.
import { describe, expect, it } from "vitest";
import { about, bandOf, foldedByIncident, foldSame, indicator, isBand, lineOf, needsRows, runMeta, type LaneFacts } from "./activity";
import { activityOf, fail, incident, run } from "./activity.fixtures";

const LANES: LaneFacts = { paused: false, afkRunning: null, reading: null, next: null };
const NOW = new Date("2026-10-23T02:00:00Z");

describe("the indicator", () => {
  it("is Quiet with what comes next, skipping the hourly housekeeping", () => {
    const a = activityOf({ next: [
      { kind: "telemetry", title: "Usage reports", at: "2026-10-23T02:10:00Z", every_words: "hourly", last: null, failing_since: null, failures_in_a_row: 0 },
      { kind: "ingest", title: "Reading your sources", at: "2026-10-23T03:23:00Z", every_words: "every 2 hours", last: null, failing_since: null, failures_in_a_row: 0 },
    ] });
    const i = indicator(a, LANES, "", NOW);
    expect(i.state).toBe("quiet");
    expect(i.word).toBe("Quiet");
    expect(i.detail).toMatch(/^next: reading your sources at (\w{3} )?\d\d:\d\d$/);
  });

  it("spins with the count and the first run's words only while something runs", () => {
    const a = activityOf({ running: [run({ words: "Collecting Robotics' history · source 2 of 5" }), run({ id: "afk:n", title: "Reading your sources" })] });
    const i = indicator(a, LANES, "", NOW);
    expect([i.state, i.word, i.detail]).toEqual(["running", "2 running", "writing the News brief · Collecting Robotics' history · source 2 of 5"]);
  });

  it("says Paused, and a failure once: until Activity is opened", () => {
    expect(indicator(activityOf({ paused: true }), LANES, "", NOW)).toMatchObject({ word: "Paused", detail: null,
      title: "Everything is paused: no source is read and no idea written until you resume" });
    const a = activityOf({ recent: [run({ state: "failed", finished: "2026-10-23T01:00:00Z" })] });
    expect(indicator(a, LANES, "", NOW)).toMatchObject({ state: "failed", word: "Quiet · 1 failed", failed: 1 });
    expect(indicator(a, LANES, "2026-10-23T01:30:00Z", NOW).state).toBe("quiet");
  });

  // live's top bar read "Quiet" once Activity was opened and "1 running" while the
  // key had been refused for two days (failedSince counted only runs since the last look)
  it("stays red while a kind is failing: while something runs and after Activity is opened", () => {
    const a = activityOf({ failing: [fail({ kind: "ingest", title: "Reading your sources" })], running: [run()] });
    expect(indicator(a, LANES, "", NOW)).toMatchObject({ state: "failed", word: "1 failing", detail: "reading your sources" });
    expect(indicator(a, LANES, "2026-10-27T00:00:00Z", NOW).state).toBe("failed");
  });

  it("names a refused key above everything, even paused, running or seen", () => {
    const a = activityOf({ incidents: [incident()], running: [run()], paused: true,
      recent: [run({ state: "failed", finished: "2026-10-23T01:00:00Z" })] });
    const i = indicator(a, { ...LANES, paused: true }, "2026-10-27T00:00:00Z", NOW);
    expect([i.state, i.word, i.detail]).toEqual(["failed", "OpenRouter key refused", "reading your sources stopped"]);
    expect(i.title).toContain("renewed in Settings › Watching");
  });

  it("puts the incident, then the Fix rows, first in Needs you, with Renew the key", () => {
    const rows = needsRows(activityOf({ incidents: [incident()], failing: [fail()], waiting: [run({ id: "w1", state: "waiting" })] }), new Set());
    expect(rows.map((r) => r.kind)).toEqual(["incident", "fix", "waiting"]);
    expect(rows[0]).toMatchObject({ verb: "Renew the key", href: "#/settings/watching?sel=ekey", title: "Your OpenRouter key is refused (expired)" });
  });

  // the owner (2026-10-28): "That level of alert should be limited to issues in Kranto itself"
  it("says a cub's blocked sign-in as one Needs you row in its own words, never the band or the top bar's red", () => {
    const blocked = incident({ id: "cub:newsletter", provider: "newsletter", name: "", tries: 0, band: false,
      title: "Your newsletter platform's sign-in has expired: reconnect", short: "newsletter sign-in expired",
      words: "Your newsletter platform's sign-in has expired: reconnect. Newsletter drafts nothing until you sign in again.",
      verb: "Reconnect", href: "#/settings/posting?sel=enl", kinds: [{ kind: "newsletter", title: "Newsletter", noun: "Newsletter", since: null, tries: 0 }] });
    const a = activityOf({ incidents: [blocked] });
    const i = indicator(a, LANES, "2026-10-27T00:00:00Z", NOW);
    expect(i.state).not.toBe("failed");
    expect(bandOf(a)).toEqual([]);
    const [row] = needsRows(a, new Set());
    expect(row).toMatchObject({ kind: "incident", verb: "Reconnect", href: "#/settings/posting?sel=enl", title: "Your newsletter platform's sign-in has expired: reconnect" });
    expect(row?.meta).not.toContain("failed run");
    // a the server before the field: by the id's class (the server itself sets band from the class)
    expect(isBand({ ...blocked, band: undefined } as never)).toBe(false);
    expect(isBand({ ...incident(), band: undefined } as never)).toBe(true);
    expect(isBand(incident({ id: "core:scheduler" }))).toBe(true);
  });

  it("folds the old per-run failure messages into the incident", () => {
    const a = activityOf({ incidents: [incident()] });
    expect(foldedByIncident(a, "ingest run failed")).toBe(true);
    expect(foldedByIncident(a, "toot.weekly run failed")).toBe(false);
    expect(foldedByIncident(activityOf(), "ingest run failed")).toBe(false);
  });

  it("says what the lanes knew until the read arrives (or an older the server)", () => {
    expect(indicator(null, { ...LANES, afkRunning: "ingest", reading: "source 1 of 8" }, "", NOW).detail).toBe("reading your sources · source 1 of 8");
    expect(indicator(null, { ...LANES, afkRunning: "radar" }, "", NOW).detail).toBe("working");
    expect(indicator(null, LANES, "", NOW)).toMatchObject({ state: "quiet", detail: null });
  });
});

describe("a page's line", () => {
  const brief = run({ subject: { kind: "topic", id: "12", name: "Robotics" }, words: "Reading what Robotics kept" });
  it("is the running run of its subject first, with Watch and Stop", () => {
    const l = lineOf(activityOf({ running: [brief] }), "kind:news.brief");
    expect(l).toMatchObject({ state: "running", watch: "#/afk/0f9e8d7c6b5a49382716a5b4c3d2e1f0/trace?follow=1", stop: "afk:0f9e8d7c6b5a49382716a5b4c3d2e1f0" });
    expect(l?.words).toBe("Writing the News brief · Reading what Robotics kept · 1 min");
    expect(lineOf(activityOf({ running: [brief] }), "topic:12")?.state).toBe("running");
    expect(lineOf(activityOf({ running: [brief] }), "topic:13")).toBeNull();
  });

  it("then what stopped for you, with the one verb to its action (B28)", () => {
    const w = run({ state: "waiting", words: "The brief for Robotics waits for you", needs: { verb: "Review", href: "news/topics" } });
    expect(lineOf(activityOf({ waiting: [w] }), "kind:news.brief")).toMatchObject({ state: "waiting", verb: { word: "Review", href: "#/news/topics" } });
  });

  it("on a cub's page, its update that waits for one click", () => {
    const w = run({ kind: "cub.update", feature: "cub", state: "waiting", words: "Newsletter 1.2.0 asks for one more permission",
      subject: { kind: "cub", id: "newsletter", name: "Newsletter" }, needs: { verb: "Review", href: "cub/newsletter?sel=settings" } });
    expect(lineOf(activityOf({ waiting: [w] }), "feature:newsletter")).toMatchObject({ state: "waiting", words: "Newsletter 1.2.0 asks for one more permission",
      verb: { word: "Review", href: "#/cub/newsletter?sel=settings" } });
    expect(lineOf(activityOf({ waiting: [w] }), "feature:toot")).toBeNull();
  });

  it("then a failing kind or the last failure, else the quiet words or nothing", () => {
    expect(lineOf(activityOf({ failing: [fail()] }), "kind:update")).toMatchObject({ state: "failed", words: "The update check: GitHub answered 401 · 3 tries", verb: { word: "Try again", href: "#/activity?fix=update" } });  // Activity at its row, as Needs you does
    const toot = run({ kind: "toot.weekly", feature: "toot", state: "failed", error: "crashed before hello (exit 137, memory)", verb: "Run again", title: "Toot's weekly run" });
    expect(lineOf(activityOf({ recent: [toot] }), "feature:toot")?.words).toBe("Toot's weekly run failed: crashed before hello (exit 137, memory)");
    expect(lineOf(activityOf(), "feature:toot", "Weekly post: next Tuesday 05:40")?.state).toBe("quiet");
    expect(lineOf(activityOf(), "feature:toot")).toBeNull();
    expect(about(activityOf({ running: [run({ kind: "ingest" })] }), "topic:12").running).toHaveLength(1); // a topic's sources
  });

  it("says a run's meta in one fact: its stage, how long, which assistant; no calls or dollars", () => {
    expect(runMeta(run({ subject: { kind: "topic", id: "12", name: "Robotics" }, words: "source 2 of 5", calls: 1, usd: 0.03, trigger: { origin: "press", by: "ui", at: null } })))
      .toBe("source 2 of 5 · 1 min");
  });
});

describe("Needs you's rows", () => {
  it("are one Fix row a failing kind, and a waiting run no other row offers", () => {
    const w = run({ id: "afk:w1", state: "waiting", words: "The brief for Robotics waits for you", needs: { verb: "Review", href: "news/topics" } });
    const other = run({ id: "afk:w2", kind: "toot.weekly", state: "waiting", words: "A ticket waits for your confirm", needs: { verb: "Confirm", href: "cub/toot?sel=o4" } });
    const a = activityOf({ failing: [fail()], waiting: [w, other] });
    const rows = needsRows(a, new Set(["#/news/topics"]));
    expect(rows.map((r) => [r.key, r.verb, r.href])).toEqual([
      ["fix:update", "Try again", "#/activity?fix=update"],
      ["wait:afk:w2", "Confirm", "#/cub/toot?sel=o4"],
    ]);
    expect(rows[0]!.title).toBe("The update check is failing");
    expect(rows[0]!.meta).toBe("GitHub answered 401");   // its one fact
    expect(needsRows(null, new Set())).toEqual([]);
  });
});

// (R6): four runs that failed the same way are one row
describe("foldSame", () => {
  it("folds the runs of a kind that failed with the same error into the first, in order", () => {
    const bad = (id: string, error = "HTTP 401") => run({ id, kind: "ingest", state: "failed", error });
    const ok = run({ id: "ok1", kind: "ingest", state: "ok" });
    const got = foldSame([bad("a"), ok, bad("b"), bad("c", "HTTP 500"), bad("d")]);
    expect(got.map((f) => [f.x.id, f.n])).toEqual([["a", 3], ["ok1", 1], ["c", 1]]);
    expect(foldSame([])).toEqual([]);
  });
});
