// Needs you (#/needs, where #/today and g t land): the one inbox, its helpers, its rows grouped by
// the verb you will use, its pane, and Promote to stable. Builds, projects and maintenance left with
// the factory: what waits is the server's (/api/today, the cards, the review queue, an update).
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import type { Facts } from "../../lib/app";
import { card } from "../../lib/app/testing";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { ACT_PATH } from "../../lib/activity";
import { activityOf, fail, incident, run } from "../../lib/activity.fixtures";
import { PREPARED_API } from "../../lib/prepared";
import { GRADED } from "../../ui/grades.svelte";
import { closeDialog } from "../../ui/dialog.svelte";
import DialogHost from "../../ui/DialogHost.svelte";
import { answerDialog, dialogShown } from "../../ui/testing";
import { IDEAS_API } from "../ideas/cards";
import { REVIEW_API } from "../review/review";
import HealthPane from "../settings/HealthPane.svelte";
import { HEALTH_API } from "../settings/health";
import { muteMenu } from "../settings/sourceverbs";
import { UPD_API } from "../settings/updates";
import { TICKS } from "../topics/proposals";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import NeedsPage from "./NeedsPage.svelte";
import NeedsPane from "./NeedsPane.svelte";
import { confirmWords, promoteRow } from "./promote";
import { DISPATCH_API, msgMark, needsCount, newHref, nextOf, termWaits, todayCount, updateOffer, waitingCards, type Host, type Want } from "./needs";

const NOW = Date.now() / 1000;
const iso = (s: number): string => new Date(s * 1000).toISOString();
/** api/term: one session about a card, with a proposal waiting and one already answered */
const PROP = (n: number, status: string, title: string) => ({ n, kind: "edit", title, confirm_class: false, subject: { kind: "idea", id: "1" }, fields: {}, why: "", status, result: null });
const TERM = { enabled: true, available: true, why: null, sandboxed: true, max_sessions: 3, running: 1, socket: true,
  sessions: [{ tid: "t1", subject: { kind: "idea", id: "1" }, title: "Card 1", state: "running", reason: null, words: "Running", created: NOW - 900, updated: NOW - 300,
    usd: 0, tokens: null, sandboxed: true, cwd: "/w", branch: "term/t1", session: "s", net: { allowed: [], asked: [] },
    proposals: [PROP(1, "done", "Fix the typo"), PROP(2, "proposed", "Tighten the pitch")] }] };
const TODAY = {
  since: iso(NOW - 86400), seen_at: null, now: iso(NOW), default_window_hours: 24, new_kept: 30, proposed: 3, project_topics: [] as unknown[],
  topics: [{ id: 1, name: "Local-first", status: "active", kind: "user", ref: null, new_kept: 0, top: [], proposed: 3, proposed_ticked: [31, 32], proposed_items_per_day: 12.4 },
    { id: 2, name: "AI tooling", status: "active", kind: "user", ref: null, new_kept: 25, top: [], proposed: 0, proposed_ticked: [], proposed_items_per_day: 0 }],
  rising: [],
  messages: [{ id: 5, kind: "strike", dedup_key: "k", origin: "card", title: "A strike on sync", body: "Sync engines moved a lot this week. More follows.", links: [], evidence_ids: [71, 72],
    created_at: iso(NOW - 1800), grade: null }] as Record<string, unknown>[],
  sources_failing: [{ id: 8, label: "Old feed", kind: "rss", failing_runs: 4, backoff_until: "2026-10-20T00:00:00Z", error: "404 Not Found" }],
  ingest: { last: null, judge_calls_24h: 0, judge_errors_24h: 0, observations: 0, sources: 0, topics: 0, paused: null },
};
const QUEUE = { items: [{ target: "idea", id: 1 }, { target: "idea", id: 2 }, { target: "observation", id: 71 }], week: "2026-W42" };
const UPDATE = { available: "0.3.64", installed: "0.3.63", channel: "stable", state: "idle", detail: null, reason: null, to: null, notes: ["- Faster."], notes_url: "https://example.org/n", can_apply: true };
const HOST = { topics: [{ id: 1, name: "Local-first" }, { id: 2, name: "AI tooling" }], sources: [{ status: "approved" }], observations: 9000, runs: [],
  update: UPDATE } as unknown as Host;
/** six cards waiting and one put off */
const CARDS = { ideas: [...[1, 2, 3, 4, 5, 6].map((n) => card(n)), card(7, "later")] };
const TOPIC1 = { id: 1, name: "Local-first", source_rows: [{ id: 31, label: "A feed", review: "proposed", pretick: true }, { id: 32, label: "B feed", review: "proposed", pretick: true },
  { id: 33, label: "C feed", review: "proposed", pretick: false }, { id: 34, label: "Watched", review: "approved", pretick: false }] };
const SHELL = { home: true, doors: true, pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };

const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; for (const k of Object.keys(GRADED)) delete GRADED[k]; document.body.replaceChildren(); });

/** the app, stubbed with what Needs you calls of it */
function old(o: { host?: Host | null } = {}) {
  const L = stub({ host: o.host === undefined ? (HOST as never) : (o.host as never) });
  const keys: Record<string, () => void> = {};
  const fns = {
    pageKey: vi.fn((k: string, f: () => void) => { keys[k] = f; }),
    updApply: vi.fn(async () => {}), dialog: vi.fn(), openClaude: vi.fn(),
    sigOf: (n: Element) => n.className + "|" + (n.textContent || ""),
  };
  Object.assign(L, fns);
  if (o.host !== null) hosted();
  return { L, keys, ...fns };
}
const READS = () => ({ "/api/today": structuredClone(TODAY), [IDEAS_API]: structuredClone(CARDS), [REVIEW_API]: QUEUE, "/api/topics/1": TOPIC1,
  "/api/features": { features: [] }, "/api/shell": SHELL,
  // the reads a test may change, answered quiet so no test sees the last one's
  "api/term": { ...TERM, sessions: [] }, [ACT_PATH]: activityOf(), [PREPARED_API]: { prepared: [] }, [UPD_API]: { candidate: null }, [DISPATCH_API]: { ideas: [] } });
/** a row's state in a word (the word, never the kind tag) */
const word = (r: Element): string => r.querySelector(".c-st .gl")?.getAttribute("aria-label") || "";
const titled = (t: Element, text: string): Element | undefined =>
  [...t.querySelectorAll("li.row")].find((r) => (r.querySelector(".r-title")?.textContent || "").includes(text));
/** every row: Show all on each long group, and the folded groups opened */
async function showAll(t: Element): Promise<void> {
  for (const b of [...t.querySelectorAll<HTMLButtonElement>("[data-show-all]")]) b.click();
  for (const b of [...t.querySelectorAll<HTMLButtonElement>("section.grp.folded .twisty")]) b.click();
  await settle();
}
/** what waits, as Needs you counts it: its groups' counts and the one thing */
const waits = (t: Element): number =>
  [...t.querySelectorAll("section.grp.needs .ghd .n")].reduce((a, n) => a + Number(n.textContent), 0) + (t.querySelector("#next") ? 1 : 0);
const pane = (sel: string): Where => where("needs", sel);

describe("Needs you's helpers", () => {
  it("lists the cards waiting, words the update and a message, and counts the rows", async () => {
    old();
    answering(READS());
    waitingCards(); // the first call reads
    await settle();
    expect(waitingCards().map((i) => i.id)).toEqual(["1", "2", "3", "4", "5", "6"]); // Later's is not waiting
    expect(updateOffer(UPDATE as never)).toBe("offer");
    expect(updateOffer({ ...UPDATE, state: "installing" } as never)).toBeNull();
    expect(updateOffer({ ...UPDATE, available: null, state: "rolled_back" } as never)).toBe("bad");
    expect(updateOffer({ ...UPDATE, available: null } as never)).toBeNull();
    for (const state of ["requested", "draining", "backing_up", "stopping", "installing", "starting", "verifying", "rolling_back"]) {
      expect(updateOffer({ ...UPDATE, state } as never)).toBeNull();
    }
    expect(msgMark({ kind: "alarm" })).toEqual(["warn", "red", "Alarm"]);
    expect(msgMark({ kind: "strike" })).toEqual(["check", "blue", "Strike"]);
    expect(msgMark({ kind: "heartbeat" })).toEqual(["dot", "grey", "Heartbeat"]);
    expect(newHref({ id: 2 }, { top: 20 })).toBe("#/topics/2/evidence?since=last&sort=signal&top=20");
    expect(termWaits(TERM as never).map((w) => [w.s.tid, w.n, w.first])).toEqual([["t1", 1, "Tighten the pitch"]]);
    expect(termWaits({ ...TERM, sessions: [{ ...TERM.sessions[0]!, proposals: [PROP(1, "dismissed", "x")] }] } as never)).toEqual([]);
    // without the server nothing counts (the cards are the server's: none is read); with it the cards
    // (each one), the update, the proposals, the message, the failing source and the queue
    expect(todayCount(null)).toBe(0);
    todayCount(HOST);
    await settle();
    expect(todayCount(HOST)).toBe(6 + 1 + 1 + 1 + 1 + 1);
    expect(needsCount(HOST, 0)).toBe(6); // the cards are one row
  });
});

// the one thing (the owner's D-1): by rule, never by a model
describe("nextOf", () => {
  const c = (key: string, want: Want, at: number | null) => ({ key, want, at });
  it("is the newest Approve, whatever waits to be fixed or decided", () => {
    expect(nextOf([c("held", "fix", 1), c("old-ready", "approve", 10), c("prep", "approve", 20), c("ask", "decision", 30)])?.key).toBe("prep");
    expect(nextOf([c("cub", "approve", null), c("ready", "approve", 5)])?.key).toBe("ready");
  });
  it("is the oldest Fix when nothing waits to go out, then the first Decide, else nothing", () => {
    expect(nextOf([c("new-held", "fix", 20), c("old-held", "fix", 10), c("failing", "fix", null), c("ask", "decision", 1)])?.key).toBe("old-held");
    expect(nextOf([c("a", "fix", 10), c("b", "fix", 10)])?.key).toBe("a");
    expect(nextOf([c("first", "decision", 99), c("second", "decision", 1)])?.key).toBe("first");
    expect(nextOf([])).toBeNull();
  });
  it("is never Kranto's own trouble: the band says it, and Needs you draws no one thing for it", async () => {
    old({ host: { ...HOST, update: null } as never });
    answering({ "/api/today": { ...TODAY, topics: [], messages: [], sources_failing: [] }, [ACT_PATH]: activityOf({ incidents: [incident()] }), "/api/features": { features: [] },
      [REVIEW_API]: { items: [] }, [IDEAS_API]: { ideas: [] } });
    const { target, done } = await draw(NeedsPage, where("needs"));
    await settle();
    expect(target.querySelector("#incident-band")).not.toBeNull();
    expect(target.querySelector("#next")).toBeNull();
    done();
    answering({ [ACT_PATH]: activityOf() });
  });
});

describe("Needs you (the one inbox)", () => {
  it("groups every row by the verb you will use under the one thing, with the count and Mark all seen", async () => {
    const { L, keys, updApply } = old();
    answering(READS());
    const { target, done } = await draw(NeedsPage, where("needs"));
    await settle();
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Needs you");
    expect(target.querySelector("#bulk, #select-rows")).toBeNull(); // no bulk grading
    // the one thing: the failing source (nothing waits to go out); the page's only primary
    const next = target.querySelector("#next")!;
    expect(next.getAttribute("data-sel")).toBe("s8");
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    await showAll(target);
    const groups = [...target.querySelectorAll("section.grp.needs")];
    expect(groups.map((g) => g.querySelector("h2")?.textContent)).toEqual(["Approve", "Review", "Update"]);
    const words = (g: Element) => [...g.querySelectorAll("li.row")].map(word);
    expect(groups.map(words)).toEqual([["Proposed"], ["Review", "Ideas", "Strike"], ["Update"]]);
    expect(groups.map((g) => g.querySelector(".ghd .n")?.textContent)).toEqual(["1", "3", "1"]);
    const rows = [...target.querySelectorAll("section.grp.needs li.row")];
    expect(rows.map((r) => r.getAttribute("data-sel"))).toEqual(["p1", "r", "cards", "m5", null]);
    expect(rows.every((r) => r.querySelectorAll(".r-act").length === 1 && !r.querySelector(".grade") && !r.querySelector(".primary"))).toBe(true);
    // the cards waiting are one row; their Later and Pass are on Ideas
    const cards = rows[2]!;
    expect(cards.querySelector(".r-title")?.textContent).toBe("6 idea cards wait for Later or Pass");
    expect(cards.querySelector(".r-act a")?.getAttribute("href")).toBe("#/ideas?status=waiting");
    expect(rows[1]!.querySelector(".r-title")?.textContent).toBe("3 waiting for a grade, a few seconds each");
    expect(rows[1]!.querySelector(".r-act a")?.getAttribute("href")).toBe("#/review");
    expect(rows[0]!.querySelector(".r-act button")?.textContent).toBe("Watch the 2 ticked");
    expect(rows[0]!.querySelector(".c-meta")?.textContent).toBe("2 close matches");
    expect(rows[3]!.querySelector(".c-meta")).toBeNull(); // the message is its pane's
    // the update: the version, Restart to update
    const upd = rows[4]!;
    expect(upd.querySelector(".r-title")?.textContent).toBe("Kranto 0.3.64 is ready");
    expect(upd.querySelector(".c-meta")?.textContent).toBe("installs when you restart");
    (upd.querySelector("#upd-apply") as HTMLButtonElement).click();
    expect(updApply).toHaveBeenCalled();
    // the head says the count the home says (one inbox, one number)
    expect(target.querySelector(".ph .muted")?.textContent).toBe(`${waits(target)} things wait for you`);
    expect(needsCount(HOST, 0)).toBe(waits(target));
    expect(target.textContent).not.toMatch(/\b[Bb]uilds?\b|[Pp]rojects?\b/);
    // Mark all seen, by its button and by ⇧a
    (target.querySelector("#mark-seen") as HTMLButtonElement).click();
    keys["⇧a"]!();
    expect(L.api.mock.calls.filter((c) => c[0] === "/api/seen")).toEqual([["/api/seen", {}], ["/api/seen", {}]]);
    done();
  });

  it("has one row for the project topics' proposed sources, to Watch › Sources' Proposed", async () => {
    old();
    const t = { ...structuredClone(TODAY), project_topics: [{ id: 40, name: "A (project)", status: "active", kind: "project", ref: "project:a", new_kept: 0, top: [], proposed: 9,
      proposed_ticked: [], proposed_items_per_day: 0 }, { id: 41, name: "B (project)", status: "active", kind: "project", ref: "project:b", new_kept: 0, top: [], proposed: 6, proposed_ticked: [], proposed_items_per_day: 0 }] };
    answering({ ...READS(), "/api/today": t });
    const { target, done } = await draw(NeedsPage, where("needs"));
    await showAll(target);
    const row = target.querySelector('li.row[data-sel="pproj"]')!;
    expect(row.querySelector(".r-title")?.textContent).toBe("15 proposed sources for 2 project topics");
    expect(row.querySelector(".r-act a")?.getAttribute("href")).toBe("#/watch/sources?status=proposed");
    done();
  });

  it("a session whose proposals wait is one row under Approve, and Open opens it in Claude Code", async () => {
    const { openClaude } = old();
    answering({ ...READS(), "api/term": TERM });
    const { target, done } = await draw(NeedsPage, where("needs"));
    await settle();
    await showAll(target);
    const row = target.querySelector('li.row[data-sel="i1"]')!;
    expect(row.querySelector(".r-title")?.textContent).toBe("Claude Code proposes: Tighten the pitch");
    expect(row.querySelector(".r-title")?.getAttribute("href")).toBe("#/ideas/1");
    expect(row.querySelector(".c-meta")?.textContent).toBe("Card 1");
    (row.querySelector(".r-act button") as HTMLButtonElement).click();
    expect(openClaude).toHaveBeenCalledWith("idea", "1", "Card 1");
    done();
  });

  it("watches a topic's ticked proposals from its row, with a toast", async () => {
    const { L } = old();
    answering(READS());
    const { target, done } = await draw(NeedsPage, where("needs"));
    await showAll(target);
    (target.querySelector('[data-sel="p1"] .r-act button') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/approve", { ids: [31, 32], topic: 1 });
    expect(L.afkStale).toHaveBeenCalledWith("/api/today", "/api/sources", "/api/topics");
    expect(L.toast).toHaveBeenCalledWith("Watching 2 more sources for Local-first. Their first fetch is the next ingest run.");
    done();
  });

  it("says a version that broke on your data was rolled back, with Send this error (RCA D1)", async () => {
    const dialog = await import("../../ui/dialog.svelte");
    const open = vi.spyOn(dialog, "openDialog").mockImplementation(() => {});
    const back = { ...UPDATE, available: null, state: "rolled_back", to: "0.5.23", reason: "0.5.23 broke on your data: GET /api/topics/7 answered 500 (error 1a2b3c4d); 1 more",
      broke: { pages: 2, error_id: "1a2b3c4d" } };
    old({ host: { ...HOST, update: back } as unknown as Host });
    answering(READS());
    const one = await draw(NeedsPage, where("needs"));
    await showAll(one.target);
    const upd = titled(one.target, "broke on your data")!;
    expect(upd.querySelector(".r-title")?.textContent).toBe("0.5.23 broke on your data and was rolled back");
    expect(upd.querySelector(".c-meta")?.textContent).toBe("nothing in your data was undone");
    const send = upd.querySelector("#upd-send-error") as HTMLButtonElement;
    expect(send.textContent).toBe("Send this error");
    send.click();
    const props = open.mock.calls[0]![1] as { report: string; error: string };
    expect(props.report).toBe("1a2b3c4d");
    expect(props.error).toBe("0.5.23 broke on my data and was rolled back (error 1a2b3c4d)");
    one.done();
    open.mockRestore();
  });

  it("says an update rolled back with Try again, not finished with nothing to try, and How to update from the command line", async () => {
    const back = { ...UPDATE, available: null, state: "rolled_back", to: "0.3.64rc1", reason: "the new version did not answer" };
    const a = old({ host: { ...HOST, update: back } as unknown as Host });
    answering(READS());
    const one = await draw(NeedsPage, where("needs"));
    await showAll(one.target);
    const upd = titled(one.target, "was rolled back")!;
    expect(upd.querySelector(".r-title")?.textContent).toBe("Update to 0.3.64rc1 was rolled back");
    expect(upd.querySelector(".c-meta")?.textContent).toBe("the new version did not answer");
    expect(upd.querySelector("a.r-title")?.getAttribute("href")).toBe("#/settings/updates");
    (upd.querySelector(".r-act button") as HTMLButtonElement).click();
    expect(a.updApply).toHaveBeenCalledWith(expect.any(HTMLButtonElement), { to: "v0.3.64-rc1" });
    one.done();
    old({ host: { ...HOST, update: { ...back, state: "failed" } } as unknown as Host });
    answering(READS());
    const failed = await draw(NeedsPage, where("needs"));
    await showAll(failed.target);
    const f = titled(failed.target, "was not finished")!;
    expect(f.querySelector(".r-title")?.textContent).toBe("Update to 0.3.64rc1 was not finished");
    expect(f.querySelector(".r-act")).toBeNull();
    failed.done();
    old({ host: { ...HOST, update: { ...UPDATE, can_apply: false } } as unknown as Host });
    answering({ ...READS(), "/api/today": { ...structuredClone(TODAY), topics: TODAY.topics.map((x) => ({ ...x, proposed_ticked: [] })) } });
    const cli = await draw(NeedsPage, where("needs"));
    await showAll(cli.target);
    const u = titled(cli.target, "is ready")!;
    expect(u.querySelector("#upd-apply")).toBeNull();
    expect(u.querySelector(".r-act a")?.textContent).toBe("How to update");
    expect(u.querySelector(".r-act a")?.getAttribute("href")).toBe("#/settings/updates");
    const p = cli.target.querySelector('[data-sel="p1"]')!;
    expect(p.querySelector(".r-act a")?.textContent).toBe("Review all 3");
    expect(p.querySelector(".r-act a")?.getAttribute("href")).toBe("#/needs?sel=p1");
    expect(p.querySelector(".c-meta")?.textContent).toBe("none is a close match");
    cli.done();
  });

  it("asks under Decide whether to remove a source your downvotes recommend removing: Remove (the house confirm) or Keep", async () => {
    const { L } = old();
    const rm = { id: 9, label: "HN search: local-first", kind: "hackernews", down: 3, up: 0, window_days: 90, topics: [{ id: 1, name: "Local-first" }], items_per_day: 1.3 };
    answering({ ...READS(), "/api/today": { ...structuredClone(TODAY), sources_to_remove: [rm] } });
    const { target, done } = await draw(NeedsPage, where("needs"));
    await showAll(target);
    const decide = [...target.querySelectorAll("section.grp.needs")].find((g) => g.querySelector("h2")?.textContent === "Decide")!;
    const row = decide.querySelector('li.row[data-sel="sr9"]')!;
    expect(row.querySelector(".r-title")?.textContent).toBe("Remove HN search: local-first?");
    expect(row.querySelector(".c-meta")?.textContent).toBe("3 of its 3 graded posts were not useful");
    expect([...row.querySelectorAll(".r-act button")].map((b) => [b.textContent, (b as HTMLElement).dataset.verb])).toEqual([["Remove", "source.retire"], ["Keep", "source.keep"]]);
    (row.querySelector("[data-act=remove-source]") as HTMLButtonElement).click();
    const d = dialogShown()!;
    expect(d.title).toBe("Remove HN search: local-first?");
    expect(d.text).toContain("Stop watching HN search: local-first. Its observations stay; the next ingest run does not read it.");
    expect(L.api).not.toHaveBeenCalledWith("/api/sources/9/status", expect.anything());
    answerDialog(true);
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/9/status", { status: "retired" });
    (row.querySelector("[data-act=keep-source]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/sources/9/keep", {});
    done();
  });

  // the home, Needs you and the nav said three counts in the same minute
  it("says one count with a refused key, the band above everything; its per-run messages fold", async () => {
    const today = structuredClone(TODAY);
    today.messages = [...today.messages,
      ...[1, 2, 3].map((i) => ({ id: 900 + i, kind: "alarm", title: "ingest run failed", body: "HTTP 401", created_at: iso(NOW - i * 3600), links: [], evidence_ids: [] as number[], dedup_key: "x" + i, origin: "ingest", grade: null }))];
    old();
    answering({ ...READS(), "/api/today": today, [ACT_PATH]: activityOf({ incidents: [incident()], failing: [fail()] }) });
    const page = await draw(NeedsPage, where("needs"));
    await settle();
    const rows = waits(page.target);
    const head = page.target.querySelector(".ph .muted")?.textContent;
    expect(page.target.querySelector(".wl")?.firstElementChild?.nextElementSibling?.id).toBe("incident-band");
    expect(page.target.textContent).toContain("The update check is failing");
    expect(page.target.textContent).not.toContain("ingest run failed");
    page.done();
    expect(rows).toBe(7); // six and the Fix row (the band says the incident); no message added
    expect(head).toBe(`${rows} things wait for you`);
    expect(needsCount(HOST, 0)).toBe(rows);
    answering({ [ACT_PATH]: activityOf() });
  });

  // the owner on 2026-10-29: nothing is said twice on Needs you
  it("says every incident and every row once; a prepared item is one line and its dialog the body once", async () => {
    const BODY = "## What happened\n" + "The item lands in Needs you and the open page does not show it. ".repeat(12) + "\n\n- one\n- two";
    const item = { uuid: "f1", verb: "b.factory_issue", title: "File a Kranto issue", by_words: "by Claude Code", page: "#/needs", words: null,
      fields: { issue: "Needs you doesn't update live", text: BODY, labels: ["feature"], area: "ui" }, state: "open", button: "File issue", created_at: iso(NOW - 600) };
    const waitingRun = run({ id: "afk:w1", kind: "verb", state: "waiting", title: "Prepared: File a Kranto issue", words: "File a Kranto issue: prepared by Claude Code; waits for your approval on #/needs",
      needs: { verb: "File a Kranto issue", href: "#/needs", words: "" } });
    const act = activityOf({ incidents: [incident({ dismiss: true })], failing: [fail()], waiting: [waitingRun] });
    const today = structuredClone(TODAY);
    today.messages = [...today.messages, { id: 990, kind: "alarm", title: "Your OpenRouter key is refused (no credit)", body: "HTTP 402",
      created_at: iso(NOW - 60), links: [], evidence_ids: [] as number[], dedup_key: "auth:openrouter:r1", origin: "ideas", grade: null }];
    old();
    answering({ ...READS(), "/api/today": today, [ACT_PATH]: act, [PREPARED_API]: { prepared: [item] } });
    const page = await draw(NeedsPage, where("needs"));
    await settle();
    const t = page.target;
    expect(t.querySelectorAll("#incident-band .inc").length).toBe(1);
    const titles = [...t.querySelectorAll("li.row .r-title, #next h2")].map((x) => x.textContent || "");
    expect(titles.filter((x, i) => titles.indexOf(x) !== i)).toEqual([]);
    expect(titles.filter((x) => /OpenRouter/.test(x))).toEqual([]);
    expect(titles.filter((x) => /File a Kranto issue/.test(x))).toEqual(["File a Kranto issue: Needs you doesn't update live"]);
    expect(t.textContent).not.toContain("What happened");
    expect(t.textContent).not.toMatch(/\bpress(es|ed|ing)?\b/i);
    expect(t.querySelector("[data-dismiss='auth:openrouter']")?.textContent).toBe("Dismiss");
    const btn = t.querySelector("[data-prepared-act='f1']") as HTMLButtonElement;
    expect(btn.textContent).toBe("File issue");
    const dh = mount(DialogHost, { target: document.body });
    btn.click();
    flushSync();
    const d = document.getElementById("dlg")!;
    expect(d.textContent).toContain("a new issue on iddv/kranto");
    expect(d.textContent!.split("The item lands in Needs you").length - 1).toBe(12); // the body, once
    closeDialog();
    void unmount(dh);
    page.done();
    answering({ [ACT_PATH]: activityOf(), [PREPARED_API]: { prepared: [] } });
  });

  it("mutes a source for 7 days or retires it, each with Undo (from a sheet: no mute on the rows)", async () => {
    const { L } = old();
    answering(READS());
    const { target, done } = await draw(NeedsPage, where("needs"));
    expect(target.querySelector("li.row button.mute")).toBeNull();
    L.api.mockResolvedValue({ muted_until: "2026-10-23T12:00:00Z" });
    const anchor = document.createElement("button");
    document.body.append(anchor);
    const pick = async (w: string) => {
      muteMenu(anchor, { id: 4, label: "HN" });
      ([...document.querySelectorAll(".pop.menu button[role=menuitem]")].find((b) => b.textContent === w) as HTMLButtonElement).click();
      await settle();
    };
    await pick("Mute for 7 days");
    expect(L.api).toHaveBeenLastCalledWith("/api/sources/4/mute", { days: 7 });
    expect(L.toast).toHaveBeenLastCalledWith("Muted HN until 23 Oct: it is not read until then.", expect.any(Function));
    await pick("Retire");
    expect(L.api).toHaveBeenLastCalledWith("/api/sources/4/status", { status: "retired" });
    (L.toast.mock.lastCall![1] as () => void)();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/sources/4/status", { status: "approved" });
    done();
  });

  it("marks everything seen with Undo back to where the marker was; opening it moves nothing", async () => {
    const { L } = old();
    answering(READS());
    const { target, done } = await draw(NeedsPage, where("needs"));
    expect(L.api).not.toHaveBeenCalled();
    L.api.mockResolvedValue({ previous: "2026-10-14T08:00:00Z" });
    (target.querySelector("#mark-seen") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/seen", {});
    expect(L.toast).toHaveBeenLastCalledWith("Marked everything seen: new counts from now.", expect.any(Function));
    (L.toast.mock.lastCall![1] as () => void)();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/seen", { at: "2026-10-14T08:00:00Z" });
    done();
  });

  it("says nothing needs you with the mark when nothing does, and what comes from the server without it", async () => {
    old({ host: { ...HOST, update: null } as never });
    answering({ "/api/today": { ...TODAY, topics: [], messages: [], sources_failing: [] }, "api/term": { ...TERM, sessions: [] }, "/api/features": { features: [] },
      [REVIEW_API]: { items: [] }, [IDEAS_API]: { ideas: [] } });
    const a = await draw(NeedsPage, where("needs"));
    expect(a.target.querySelectorAll("section.grp").length).toBe(0);
    expect(a.target.textContent).toContain("Nothing needs you. Kranto keeps watching.");
    a.done();
    old({ host: null });
    answering({ [IDEAS_API]: { ideas: [] } });
    const b = await draw(NeedsPage, where("needs"));
    expect(b.target.querySelector("#mark-seen")).toBeNull();
    expect(b.target.querySelector("p.quiet-topics")?.textContent).toBe("Proposed sources, messages and the cubs' asks come from the server, which is not hosting this page.");
    b.done();
  });
});

describe("Needs you's pane", () => {
  it("with nothing selected: what the kranto read while the library is small, and the recent Claude Code sessions", async () => {
    const { openClaude } = old({ host: { ...HOST, observations: 12, runs: [{ kind: "ingest", finished_at: "2026-10-15T06:26:00Z", status: "ok" }] } as unknown as Host });
    answering({ ...READS(), "/api/setup": { done: true }, "api/term": TERM });
    const { target, done } = await draw(NeedsPane, where("needs"));
    expect(target.querySelector(".pane-empty > p.empty")?.textContent).toBe("Nothing selected.");
    expect(target.querySelector(".hero p")?.textContent).toBe("Kranto is reading 1 source for 2 topics. Last ingest 2026-10-15 06:26, ok. Themes appear after about 30 observations (12 so far); ideas after the first map.");
    const a = target.querySelector(".box-b.ctx a") as HTMLAnchorElement;
    expect(a.textContent).toBe("Card 1");
    expect(target.querySelector(".box-b.ctx time")?.textContent).toBe("5 min ago");
    a.click();
    expect(openClaude).toHaveBeenCalledWith("idea", "1", "Card 1");
    done();
  });

  it("the queue: what is in it by kind, and Start", async () => {
    old();
    answering(READS());
    const { target, done } = await draw(NeedsPane, pane("r"));
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("Review");
    expect(target.querySelector(".dt")?.textContent).toBe("3 items waiting for a grade");
    expect(target.querySelector("#s-in p")?.textContent).toBe("2 cards · 1 observation");
    expect(target.querySelector(".acts a.btn.primary")?.getAttribute("href")).toBe("#/review");
    done();
  });

  it("a message: its evidence and where every message is kept, no grade; gone once seen", async () => {
    old();
    answering(READS());
    const { target, done } = await draw(NeedsPane, pane("m5"));
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("A strike on sync");
    expect(target.querySelector(".dk")?.textContent).toBe(" message · strike");
    expect(target.querySelector(".gh, .grade")).toBeNull();
    expect(target.querySelector("#s-body p.prose")?.textContent).toBe("Sync engines moved a lot this week. More follows.");
    expect([...target.querySelectorAll("#s-evidence a")].map((a) => a.getAttribute("href"))).toEqual(["#/library/o/71", "#/library/o/72"]);
    expect(target.querySelector("p.mt a")?.getAttribute("href")).toBe("#/settings/health?message=5");
    done();
    old();
    answering(READS());
    const gone = await draw(NeedsPane, pane("m9"));
    expect(gone.target.querySelector(".pane-empty p")?.textContent).toBe("This message is no longer new. Every message is kept under Settings › System › Health.");
    gone.done();
  });

  it("a topic's proposals: ticked as its Sources ticks them, and Watch these", async () => {
    const { L } = old();
    answering(READS());
    const { target, done } = await draw(NeedsPane, pane("p1"));
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("Proposed sources");
    expect(target.querySelector(".dt")?.textContent).toBe("3 proposed sources for Local-first");
    const box = target.querySelector("section.grp.props")!;
    expect([...box.querySelectorAll("li.row .r-title")].map((x) => x.textContent)).toEqual(["A feed", "B feed", "C feed"]);
    expect([...box.querySelectorAll("li.row input.ptick")].map((x) => (x as HTMLInputElement).checked)).toEqual([true, true, false]);
    expect([...TICKS[1]!]).toEqual([31, 32]);
    (target.querySelector("#watch-these") as HTMLButtonElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => String(c[0]).startsWith("/api/sources"))).toEqual([["/api/sources/approve", { ids: [31, 32], topic: 1 }]]);
    expect(TICKS[1]).toBeUndefined();
    expect(L.afkDrop).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Watching 2 more sources for Local-first. Their first fetch is the next ingest run.");
    done();
    old();
    answering(READS());
    const gone = await draw(NeedsPane, pane("p2"));
    expect(gone.target.querySelector(".pane-empty p")?.textContent).toBe("Nothing waits for you here now: the proposals were watched or retired.");
    gone.done();
  });

  it("without the server a message says so", async () => {
    old({ host: null });
    answering({});
    const { target, done } = await draw(NeedsPane, pane("m5"));
    expect(target.querySelector(".pane-empty p")?.textContent).toBe("This comes from the server, which is not hosting this page.");
    done();
  });

  it("Settings › System › Health draws a message with its delivery", async () => {
    old();
    const D = { messages: [{ ...TODAY.messages[0], id: 7 }], message_grades: { 7: { grade: "useful" } }, deliveries: { 7: { sent: ["ntfy"], failed: 1, last_error: "timeout" } }, delivery_status: "on: ntfy" };
    answering({ [HEALTH_API]: D });
    const { target, done } = await draw(HealthPane, where("settings/health", "emsg:7"));
    expect(target.querySelector("#s-delivery p")?.textContent).toBe("sent to ntfy; 1 failed attempt, last: timeout");
    expect(target.querySelector(".grade")).toBeNull();
    expect(target.querySelector("p.mt")).toBeNull();
    done();
  });
});

// Promote to stable (REL; the owner, 2026-10-24: stable is always a choice, never time)
const CAND = {
  state: "candidate", stable: "v0.5.27", tag: "v0.6.0-dev3", version: "0.6.0.dev3", to: "v0.6.0", installed: "0.6.0.dev3",
  prs: { kranto: [{ number: 360, title: "A calmer home" }], "kranto.page": [] }, count: 12,
  big: [{ repo: "kranto", number: 360, title: "A calmer home" }],
  off_on_stable: [{ key: "shell.layout", default: "new", default_stable: "classic" }],
  checks: [{ name: "rollback", ok: true, said: "no rollback of it on your install or another" }, { name: "pages", ok: true, said: "kranto doctor --routes passed: 411 of 411" }],
  blocking: [], blind: ["error reports: not on the server yet"], nightly_since: "2026-10-24T05:35:04Z",
};
const withCand = (c: unknown) => ({ ...READS(), [UPD_API]: { candidate: c } });

describe("Promote to stable", () => {
  it("words each state from the facts, never a countdown", () => {
    const r = promoteRow(CAND as never)!;
    expect(r.title).toBe("Nightly 0.6.0-dev3 can become stable 0.6.0");
    expect(r.press && r.counts).toBe(true);
    expect(r.detail).toEqual(["12 pull requests since 0.5.27", "1 big change", "shell.layout stays classic on stable",
      "no rollback of it on your install or another", "kranto doctor --routes passed: 411 of 411", "error reports: not on the server yet", "on nightly since 2026-10-24 05:35 UTC"]);
    expect(r.detail.join(" ")).not.toMatch(/\b\d+(\.\d+)? (days?|hours?)\b|has run|until it|left to/);
    const b = promoteRow({ ...CAND, state: "blocked", blocking: ["1 new error still occurring: brief (first seen on 0.6.0.dev2, your install)"] } as never)!;
    expect(b.title).toBe("Nightly 0.6.0-dev3 is not promoted: 1 new error still occurring: brief (first seen on 0.6.0.dev2, your install)");
    expect(b.press).toBe(false);
    expect(promoteRow({ ...CAND, state: "promoting", step: "rc_check" } as never)!.detail[0]).toBe("rc_check against 0.5.27");
    const f = promoteRow({ ...CAND, state: "failed", step: "rc_check", reason: "FAIL 3. roll back", log: "/x/rc_check.log" } as never)!;
    expect([f.title, f.detail[0], f.press]).toEqual(["0.6.0's promotion stopped at rc_check", "FAIL 3. roll back", false]);
    expect(promoteRow({ ...CAND, state: "promoted", promoted: { tag: "v0.6.0", at: "2026-10-24T13:00:00Z" } } as never)!.title).toBe("0.6.0 is stable");
    expect(promoteRow({ state: "none", said: "nightly is not ahead" } as never)).toBeNull();
    expect(promoteRow(null)).toBeNull();
    expect(promoteRow({ ...CAND, state: "rethinking" } as never)).toBeNull();
  });

  it("offers the action in Needs you, and nothing is written until the confirm's Promote", async () => {
    const a = old();
    answering(withCand(CAND));
    const one = await draw(NeedsPage, where("needs"));
    await showAll(one.target);
    const row = [...one.target.querySelectorAll("section.grp.needs li.row")].find((r) => r.querySelector("#promote-stable"))!;
    expect(row.querySelector(".r-title")?.textContent).toBe("Nightly 0.6.0-dev3 can become stable 0.6.0");
    expect(word(row)).toBe("Stable?");
    (row.querySelector("#promote-stable") as HTMLButtonElement).click();
    const d = dialogShown()!;
    expect(d.title).toBe("Promote 0.6.0-dev3 to stable as 0.6.0?");
    expect(d.text).toContain("including 1 big change: A calmer home");
    expect(confirmWords({ ...CAND, big: [] } as never).body[0]).toContain("12 pull requests since 0.5.27; none is labelled big.");
    expect(d.text).toContain("Off on stable until you change their default: shell.layout stays classic on stable");
    answerDialog(false);
    expect(a.L.api).not.toHaveBeenCalledWith("/api/update/promote", expect.anything());
    (row.querySelector("#promote-stable") as HTMLButtonElement).click();
    answerDialog(true);
    await settle();
    expect(a.L.api).toHaveBeenCalledWith("/api/update/promote", { tag: "v0.6.0-dev3" });
    one.done();
  });

  it("shows a blocked candidate with no approval, and no row off the maintainer's install", async () => {
    old();
    answering(withCand({ ...CAND, state: "blocked", blocking: ["0.6.0.dev3 was rolled back on your install"] }));
    const one = await draw(NeedsPage, where("needs"));
    await showAll(one.target);
    const titles = [...one.target.querySelectorAll("section.grp.needs li.row .r-title")].map((t) => t.textContent);
    expect(titles).toContain("Nightly 0.6.0-dev3 is not promoted: 0.6.0.dev3 was rolled back on your install");
    expect(one.target.querySelector("#promote-stable")).toBeNull();
    one.done();
    old();
    answering(withCand(null));
    const two = await draw(NeedsPage, where("needs"));
    expect(two.target.textContent).not.toContain("can become stable");
    two.done();
  });
});
