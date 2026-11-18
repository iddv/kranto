// Ideas: the server's cards alone, grouped by their own state; a card's sheet (the thesis,
// its sources, Write a post, Pass and Later); the verbs ⌘K and a row's menu share; a card's rank.
import { mount, unmount } from "svelte";
import { closeDetails, DETAILS } from "../../ui/details.svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import DialogHost from "../../ui/DialogHost.svelte";
import { closeDialog } from "../../ui/dialog.svelte";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { GRADED } from "../../ui/grades.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import IdeaPane from "./IdeaPane.svelte";
import IdeasList from "./IdeasList.svelte";
import { IDEAS_API } from "./cards";
import { cardIdea, cardNo, firstWords, IDEA_SELECTS, ideaOf, nextAt, priorArtLine, rankLine, rankOrder, rankWhy, type CardX } from "./ideas";
import { ideaItems, passIdea } from "./verbs";

const HOURS = (h: number): string => new Date(Date.now() - h * 3600e3).toISOString();
// The server's /api/ideas, as it answers
const RAW = [{ number: 3, title: "Idea card:3", score: 0.25, grade: null, topics: [{ id: 1, name: "Local-first", share: 0.4 }, { id: 2, name: "AI tooling", share: 1 }],
  citations: [{}, {}], signals: { rising: { agrees: true, line: "up 3 maps" }, watch: { agrees: false } }, theme: { name: "Sync engines" }, origin: "map_theme",
  thesis: "Thesis 3.", evidence: [], state: "waiting", created_at: HOURS(2) }];
const READ_CARDS = { [IDEAS_API]: RAW };
// The server's cards with their own state, as /api/ideas answers them
const STATED = { ideas: [
  { id: 7, title: "Kiosk ledger", state: "waiting", rank: { position: 2, taste: 0, line: "", parts: [] }, created_at: "2026-11-10T08:00:00Z", topics: [] },
  { id: 3, title: "Idea card:3", state: "waiting", rank: { position: 1, taste: 0, line: "", parts: [] }, created_at: "2026-11-09T08:00:00Z", topics: [{ id: 1, name: "Local-first", share: 0.4 }] },
  { id: 8, title: "Choir dues", state: "later", later_until: "2026-11-18T08:00:00Z", created_at: "2026-11-08T08:00:00Z", topics: [] },
  { id: 9, title: "Padel courts", state: "posted", created_at: "2026-11-07T08:00:00Z", topics: [] },
  { id: 10, title: "Old one", state: "passed", grade: "not_useful", created_at: "2026-11-06T08:00:00Z", topics: [] }], count: 5 };
const DISPATCH = { id: 19, title: "The OSS one", state: "waiting", origin: "dispatch", pitch_kind: "oss", pitch_label: "The OSS pitch", pitch_text: "Make the open one.",
  who: "maintainers", thesis: "The argument.", dispatch: { dispatch_id: "d1", title: "Dispatch one", date: "2026-10-01", url: "https://example.org/d1" }, created_at: HOURS(3), topics: [] };
/** a card as the sheet and the verbs read it */
const one = (o: Record<string, unknown> = {}) => cardIdea({ number: 3, title: "Idea card:3", state: "waiting", topics: [], evidence: [], raw: {}, ...o } as unknown as CardX);

const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; location.hash = ""; for (const k of Object.keys(GRADED)) delete GRADED[k]; });
const list = (q: Record<string, string> = {}): Where => ({ ...where("ideas"), r: { path: ["ideas"], q, sel: null } });
const pane = (id: string, node = "ideas"): Where => ({ ...where(node), object: "idea", obj: ["ideas", id], id, sel: node !== "ideas" });

/** the app, stubbed with what Ideas calls of it */
function old() {
  const L = stub({ host: { topics: [{ id: 1, name: "Local-first" }] }, answer: { later_until: "2026-11-19T08:00:00Z" } });
  const fns = {
    openClaude: vi.fn(),
    flash: vi.fn(), toast: vi.fn(), stepping: vi.fn(() => false), menu: vi.fn(), pageKey: vi.fn(), pageKeys: vi.fn(() => ["c"]), runPageKey: vi.fn(),
    sigOf: (n: Element) => n.className + "|" + (n.textContent || ""),
  };
  Object.assign(L, fns);
  hosted();
  return { L, ...fns };
}
const rows = (t: HTMLElement, id: string): HTMLElement[] => [...t.querySelector("#" + id)!.closest("section")!.querySelectorAll("li.row")] as HTMLElement[];

describe("a card's prior art (live search,)", () => {
  it("says when and where it searched, or that it did not", () => {
    expect(priorArtLine({ live: true, searched_at: "2026-10-17T12:00:00Z", backends: ["Exa, free mode (rate-limited, no account)", "GitHub"], results: 10 }))
      .toBe("searched 2026-10-17 with Exa, free mode (rate-limited, no account), GitHub · 10 results");
    expect(priorArtLine({ live: false, note: "no live search: results are from model memory and may be stale" })).toBe("no live search: results are from model memory and may be stale");
    expect(priorArtLine(null)).toBeNull();
  });
});

describe("Ideas", () => {
  it("finds a card by its number or card:N once the cards are read; filters by a card's own state", async () => {
    old();
    answering({ [IDEAS_API]: STATED });
    expect(ideaOf("3")).toBeNull(); // not read yet: the call reads
    await settle();
    expect(ideaOf("3")).toMatchObject({ id: "3", status: "open", state: "waiting", title: "Idea card:3" });
    expect(ideaOf("card:9")).toMatchObject({ id: "9", status: "posted" });
    expect(ideaOf("i1a1b2c3d")).toBeNull(); // an old link no card names
    expect(cardNo("card:143")).toBe(143);
    expect(cardNo("x")).toBeNull();
    expect(IDEA_SELECTS.map((s) => s[0])).toEqual(["status", "source", "kind"]);
    expect(IDEA_SELECTS[0]![2].map((o) => o[0])).toEqual(["", "waiting", "later", "posted", "passed"]);
  });

  it("lists the server's cards alone, grouped Waiting · Later · Posted · Passed by their own state", async () => {
    const { L } = old();
    answering({ [IDEAS_API]: STATED });
    const { target, done } = await draw(IdeasList, list());
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Ideas");
    expect(target.querySelector(".lh .muted")?.textContent).toBe("5 ideas · 2 waiting");
    expect((target.querySelector("#search") as HTMLInputElement).placeholder).toBe("Search ideas  ( / )");
    expect(target.querySelector("section.pin, #new-idea-head, #changes-chip, #bulk, #select-rows, input.tick")).toBeNull();
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Waiting", "Later", "Posted", "Passed"]);
    expect([...target.querySelectorAll(".grp .ghd .n")].map((h) => h.textContent)).toEqual(["2", "1", "1", "1"]);
    // Waiting in the server's rank order; a row links the card by its number
    const [a, b] = rows(target, "id-waiting");
    expect([a, b].map((r) => r!.querySelector(".c-num")?.textContent)).toEqual(["#3", "#7"]);
    expect(a!.className).toBe("row lr");
    expect(a!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/ideas/3");
    expect(a!.querySelector(".c-meta")?.textContent).toBe("Local-first");
    const g = a!.querySelector('.c-end .grade[data-grade="idea:3"]')!;
    expect(g.getAttribute("aria-label")).toBe("Grade card #3");
    const later = rows(target, "id-later")[0]!;
    expect(later.querySelector(".c-meta")?.textContent).toMatch(/^later: until \d+ \w+$/);
    expect(rows(target, "id-posted")[0]!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Posted");
    expect(a!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Waiting");
    expect(later.querySelector(".gl")?.getAttribute("aria-label")).toBe("Later");
    expect(rows(target, "id-passed")[0]!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Passed");
    expect(target.textContent).not.toMatch(/\bBuild\b/);
    (g.querySelector("button[data-v=useful]") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/feedback", expect.objectContaining({ target: "idea", target_id: "3", value: "useful", context: expect.objectContaining({ position: 1 }) }));
    expect(L.api.mock.calls.some((c) => String(c[0]).startsWith("api/loop"))).toBe(false);
    done();
  });

  it("makes a filter or a search one group, reads the dispatch cards on their own, says when nothing matches", async () => {
    old();
    answering({ [IDEAS_API]: STATED, "/api/ideas?origin=dispatch&embedding=ref": { ideas: [{ id: 9, title: "The OSS one", state: "waiting", origin: "dispatch", pitch_kind: "oss" }] } });
    const m = await draw(IdeasList, list({ q: "ledger" }));
    expect([...m.target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Matching"]);
    expect(rows(m.target, "id-match").map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Kiosk ledger"]);
    m.done();
    old();
    const st = await draw(IdeasList, list({ status: "later" }));
    expect(rows(st.target, "id-match").map((r) => r.querySelector(".c-num")?.textContent)).toEqual(["#8"]);
    st.done();
    old();
    const k = await draw(IdeasList, list({ source: "dispatch", kind: "oss" }));
    await settle();
    expect(rows(k.target, "id-match").map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["The OSS one"]);
    k.done();
    old();
    const n = await draw(IdeasList, list({ q: "nothing like this" }));
    expect(n.target.querySelector("p.empty")?.textContent).toBe("No ideas match.");
    n.done();
  });

  // (decision D4): the sheet is the title, the facts line, the thesis, its sources and
  // the verbs; every other field is Details'
  it("draws a card's sheet as its thesis and its sources, within 128 words and 6 controls", async () => {
    old();
    const long = (w: string, n: number) => Array.from({ length: n }, (_, k) => `${w}${k}`).join(" ");
    const big = { id: 143, title: "Padel court finder for clubs that book by phone", state: "waiting", grade: "useful", created_at: "2026-11-10T08:00:00Z",
      topics: [{ id: 5, name: "Padel", share: 1 }], thesis: long("thesis", 60), insight: long("insight", 40), pattern: long("pattern", 30),
      where_now: long("where", 30), cheapest_test: long("cheap", 30), risks: long("risk", 30), moment: long("moment", 20), mechanism: long("mech", 20),
      gap: long("gap", 20), evidence: [{ observation_id: 1, claim: "a", url: "https://www.padelfip.com/a" }, { observation_id: 2, claim: "b", url: "https://padelfip.com/b" },
        { observation_id: 3, claim: "c", url: "https://reuters.com/c" }],
      prior_art: { live: true, searched_at: "2026-11-10T00:00:00Z", backends: ["Exa"], results: 3, existing: [{ title: "Playtomic", url: "https://playtomic.io" }] } };
    const vocab = { chips: { idea: [{ id: "too_broad", label: "too broad", key: "a" }] } };
    answering({ [IDEAS_API]: { ideas: [big], count: 1 }, "/api/ideas/143?embedding=ref": big, "/api/feedback/vocabulary": vocab });
    const { target, done } = await draw(IdeaPane, pane("143"));
    await settle();
    await settle();
    const text = target.textContent || "";
    expect(target.querySelector("#idea-sources")?.textContent).toBe("Sources: padelfip.com · reuters.com");
    for (const gone of ["Pattern", "Where now", "Cheapest test", "Risks", "Prior art", "Research this card", "Painful moment", "Build"]) expect(text, gone).not.toContain(gone);
    expect(text).toContain("thesis59");
    expect([...target.querySelectorAll(".dh .acts > .btn")].map((x) => x.textContent)).toEqual(["Write a post", "Passp", "Laterl"]); // each with its key
    expect(target.querySelector(".dh .acts .btn.more, .dh .acts [aria-haspopup=menu]")).toBeNull();
    expect(target.querySelector(".dk")?.textContent).toContain("card #143 · waiting");
    expect(target.querySelector(".whyb")).toBeNull();
    const words = (target as HTMLElement).innerText?.split(/\s+/).filter((w) => /\w/.test(w)).length ?? text.split(/\s+/).filter((w) => /\w/.test(w)).length;
    expect(words).toBeLessThanOrEqual(128);
    const controls = target.querySelectorAll("a[href], button, input, select, textarea, summary").length;
    expect(controls, [...target.querySelectorAll("a[href], button, input, select, textarea, summary")].map((e) => (e.textContent || e.getAttribute("aria-label") || "").trim()).join(" | ")).toBeLessThanOrEqual(6);
    done();
  });

  // card → Write a post → the question → Write draft
  it("a card's Write a post asks the question and Write draft asks the server for the draft", async () => {
    const { L } = old();
    const card143 = { id: 143, title: "Padel court finder", state: "waiting", created_at: "2026-11-10T08:00:00Z", topics: [], thesis: "Clubs book by phone.",
      evidence: [{ observation_id: 1, claim: "a", url: "https://padelfip.com/a" }, { observation_id: 2, claim: "b", url: "https://reuters.com/b" }] };
    answering({ [IDEAS_API]: { ideas: [card143], count: 1 }, "/api/ideas/143?embedding=ref": card143 });
    const host = document.createElement("div");
    document.body.append(host);
    const dh = mount(DialogHost, { target: host });
    const { target, done } = await draw(IdeaPane, pane("143"));
    await settle();
    const write = target.querySelector("#idea-write") as HTMLButtonElement;
    expect(write.className).toContain("primary");
    write.click();
    await settle();
    expect(document.querySelector("#dlg-t")?.textContent).toBe("Write a post about this idea?");
    expect(document.querySelector("#write-post-about")?.textContent).toBe("card #143, with its 2 sources linked");
    (document.querySelector("#dlg-ok") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "card:143", as: "blog" });
    expect(L.say).toHaveBeenCalledWith("Writing the draft. It will be on Post in about a minute.");
    done();
    closeDialog();
    unmount(dh);
    host.remove();
  });

  it("at ?since= lists only the cards written after it, in one group named for the day", async () => {
    old();
    answering({ [IDEAS_API]: STATED });
    const s = await draw(IdeasList, list({ since: "2026-11-08T12:00:00Z" }));
    expect([...s.target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Since 8 November"]);
    expect(rows(s.target, "id-since").map((r) => r.querySelector(".c-num")?.textContent)).toEqual(["#7", "#3"]);
    expect(s.target.querySelector(".lh .muted")?.textContent).toBe("2 of 5");
    expect(s.target.querySelector("#ideas-since a")?.getAttribute("href")).toBe("#/ideas");
    s.done();
    old();
    const none = await draw(IdeasList, list({ since: "2026-11-11T00:00:00Z" }));
    expect(none.target.querySelector("p.empty")?.textContent).toBe("No idea was written since then.");
    none.done();
  });

  it("with no card yet, says when the first come: after the map, once 30 items are kept", async () => {
    old();
    answering({ [IDEAS_API]: { ideas: [], count: 0, first: { words: "x", at: null, observations: 12, needed: 30 } } });
    const e = await draw(IdeasList, list());
    await settle();
    expect(e.target.querySelector("p.empty")?.textContent).toBe("No ideas yet. The first come after the map, once 30 items are kept. So far: 12.");
    e.done();
    const at = new Date(2026, 10, 11, 22, 0), now = new Date(2026, 10, 11, 15, 0);
    expect(firstWords({ words: "", at: at.toISOString(), observations: 31, needed: 30 }, now)).toBe("No ideas yet. The first come after tonight's map at 22:00.");
    expect(firstWords({ words: "", at: new Date(2026, 10, 12, 7, 0).toISOString(), observations: 31, needed: 30 }, now)).toBe("No ideas yet. The first come after the next map, tomorrow at 07:00.");
    expect(nextAt(new Date(2026, 10, 11, 14, 30).toISOString(), new Date(2026, 10, 11, 9, 0))).toBe("at 14:30");
    expect(firstWords({ words: "", at: at.toISOString(), observations: 12, needed: 30 }, now))
      .toBe("No ideas yet. The first come after tonight's map at 22:00, once 30 items are kept. So far: 12.");
  });

  it("draws an open card in the pane: Write a post, Pass and Later with their keys, the grade bar and the card", async () => {
    const { L, pageKey } = old();
    answering({ ...READ_CARDS });
    const { target, done } = await draw(IdeaPane, pane("3", "topics/1/ideas"), "#/topics/1/ideas");
    await settle();
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/topics/1/ideas");
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("Idea card:3");
    expect(target.querySelector(".dk")?.textContent).toBe(" card #3 · waiting");
    expect(target.querySelector(".lede")?.textContent).toBe("Local-first 40% · AI tooling · theme Sync engines · written 2 h ago");
    expect(target.querySelector(".acts .mono")).toBeNull(); // no score at the head
    const acts = [...target.querySelectorAll(".dh .acts > .btn")] as HTMLElement[];
    expect(acts.map((b) => b.textContent)).toEqual(["Write a post", "Passp", "Laterl"]);
    // Pass asks why: the chips a person reads ("not doable", kept as not_buildable)
    acts[1]!.click();
    expect(L.popover).toHaveBeenCalledWith(acts[1], "Why pass?", [], expect.anything());
    expect([...document.querySelectorAll(".pop button.chip")].map((b) => b.getAttribute("data-chip"))).toEqual(["not my topic", "already exists", "thin evidence", "not doable", "wrong user"]);
    for (const x of document.querySelectorAll(".pop")) x.remove();
    // Later: the server's idea.later, a week
    acts[2]!.click();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === "/api/ideas/3/later")).toEqual([["/api/ideas/3/later", { days: 7 }]]);
    // the keys p l
    expect(pageKey.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(["p", "l"]));
    (pageKey.mock.calls.find((c) => c[0] === "l")![1] as () => void)();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === "/api/ideas/3/later").length).toBe(2);
    expect(target.querySelector(".toc")).toBeNull(); // one section: no outline
    expect(target.querySelector("#s-card h3")?.textContent).toBe("Card");
    expect(target.querySelector("#idea-details")?.textContent).toBe("Details ›");
    expect(target.querySelector("#s-card .grade")?.getAttribute("aria-label")).toBe("Grade card #3");
    expect(target.querySelector("#s-card dl.kv dd")?.textContent).toBe("Thesis 3.");
    expect(target.querySelector("#s-pitch, #s-build, #s-evidence, #s-signals, #s-why, #cap-with")).toBeNull();
    done();
  });

  it("says what cubs asked on the card in its Details, not as a section (CON L4,)", async () => {
    old();
    answering({ ...READ_CARDS, "/api/ideas/3?embedding=ref": { id: 3, tickets: [{ id: 7, cub: "toot", kind: "post.mastodon", title: "Publish this post", state: "needs_confirm", created_at: HOURS(1) }] } });
    const { target, done } = await draw(IdeaPane, pane("3", "topics/1/ideas"), "#/topics/1/ideas");
    await settle();
    expect(target.querySelector("#idea-tickets")).toBeNull();
    (target.querySelector("#idea-details") as HTMLButtonElement).click();
    expect(DETAILS.sel).toBe("card:3");
    closeDetails();
    done();
  });

  it("leaves out a theme that lost its name, never \"theme null\"", async () => {
    old();
    answering({ [IDEAS_API]: [{ ...RAW[0], theme: { name: null } }] });
    const { target, done } = await draw(IdeaPane, pane("3", "topics/1/ideas"), "#/topics/1/ideas");
    await settle();
    expect(target.querySelector(".lede")?.textContent).toBe("Local-first 40% · AI tooling · written 2 h ago");
    expect(target.textContent).not.toMatch(/\bnull\b|\bundefined\b/);
    done();
  });

  it("draws a dispatch card's pitch, read alone (it is not in the default list)", async () => {
    old();
    answering({ ...READ_CARDS, "/api/ideas/19?embedding=ref": DISPATCH });
    const d = await draw(IdeaPane, pane("19"));
    // two reads in turn (the cards, then the dispatch card alone): on a busy run the second is later
    for (let k = 0; k < 50 && !d.target.querySelector("#s-card"); k++) await settle();
    expect(d.target.querySelector("#s-card h3")?.textContent).toBe("From the dispatch");
    expect(d.target.querySelector("#s-card section.box#pitch h2")?.textContent).toBe("The OSS pitch");
    expect(d.target.querySelector("#s-card .box-b .prose")?.textContent).toBe("Make the open one.");
    expect([...d.target.querySelectorAll("#s-card dl.kv dt")].map((x) => x.textContent)).toEqual(["For", "The dispatch's argument"]);
    d.done();
  });

  it("gives ⌘K and a row's menu an open card's verbs: Pass, Later, Open in Claude Code; a decided one only the last", async () => {
    const { L, openClaude } = old();
    const open = one();
    const items = ideaItems(open);
    expect(items.map((x) => [x.label, x.key])).toEqual([["Pass", "p"], ["Later", "l"], ["Open in Claude Code", "c"]]);
    items[1]!.run(null as never);
    await settle();
    expect(L.api).toHaveBeenLastCalledWith("/api/ideas/3/later", { days: 7 });
    expect(L.flash.mock.calls.at(-1)![0]).toMatch(/^"Idea card:3" moves to Later until .+, then comes back by itself\.$/);
    items[2]!.run(null as never);
    expect(openClaude).toHaveBeenCalledWith("idea", "3", "Idea card:3");
    expect(ideaItems(one({ state: "passed" })).map((x) => x.label)).toEqual(["Open in Claude Code"]);
    expect(ideaItems(one({ state: "posted" })).map((x) => x.label)).toEqual(["Open in Claude Code"]);
  });

  it("Pass asks why and grades the card not useful with the chip as its reason, the server's alone", async () => {
    const { L } = old();
    const btn = document.createElement("button");
    document.body.append(btn);
    const pick = async (chip: string) => {
      passIdea(btn, one());
      ([...document.querySelectorAll(".pop button.chip")].find((b) => b.getAttribute("data-chip") === chip) as HTMLButtonElement).click();
      await settle();
    };
    await pick("thin evidence");
    expect(L.api.mock.calls).toEqual([["/api/feedback", expect.objectContaining({ target: "idea", target_id: "3", value: "not_useful", reasons: ["thin_evidence"], origin: "ui", context: expect.objectContaining({ via: "pass" }) })]]);
    expect(GRADED["idea:3"]).toEqual({ value: "not_useful", reasons: ["thin_evidence"] });
    expect(L.afkStale).toHaveBeenCalledWith("/api/ideas");
    expect(L.say).toHaveBeenLastCalledWith('Passed on "Idea card:3" (thin evidence). It moves to Passed, kept with your reason.');
    L.api.mockClear();
    await pick("not doable");
    expect(L.api).toHaveBeenLastCalledWith("/api/feedback", expect.objectContaining({ reasons: ["not_buildable"] }));
    expect(L.api.mock.calls.some((c) => String(c[0]).startsWith("api/loop"))).toBe(false);
    btn.remove();
  });

  it("says when nothing is selected and when the card is gone", async () => {
    old();
    const none = await draw(IdeaPane, where("ideas"));
    expect(none.target.querySelector(".pane > .pane-empty p.empty")?.textContent).toBe("Nothing selected.");
    none.done();
    old();
    answering({ ...READ_CARDS });
    const gone = await draw(IdeaPane, pane("999"), "#/ideas");
    await settle();
    expect(gone.target.querySelector(".pane-empty p.empty")?.textContent).toBe("No such idea.");
    gone.done();
  });
});

describe("a card's rank (the server's taste, no model)", () => {
  const part = (w: number, id: string, o: Record<string, unknown> = {}) => ({ weight: w, why: "reads alike (0.77)", target: "idea" as const, target_id: id, value: w > 0 ? "useful" : "not_useful", graded_at: "2026-10-11T09:00:00Z", title: "Persistent project memory", ...o });
  it("says the line on the row, never the owner's own grade (the ▲ ▼ show that)", () => {
    expect(rankLine({ rank: { position: 4, taste: 1.8, line: "ranked up: like 2 cards you upvoted", parts: [] } })).toBe("ranked up: like 2 cards you upvoted");
    expect(rankLine({ rank: { position: 1, taste: 0, line: "you graded it useful", parts: [] } })).toBeNull();
    expect(rankLine({ rank: { position: 9, taste: 0, line: "", parts: [] } })).toBeNull();
    expect(rankLine({ rank: null })).toBeNull();
  });
  it("names the parts on the sheet: like #111 … and #112, which you upvoted on 11 Oct", () => {
    expect(rankWhy({ number: 109, rank: { position: 4, taste: 1.8, line: "ranked up: like 2 cards you upvoted", parts: [part(0.88, "111"), part(0.88, "112", { title: "The gap" })] } }))
      .toBe("Ranked up: like #111 Persistent project memory and #112, which you upvoted on 11 Oct.");
    expect(rankWhy({ number: 143, rank: { position: 25, taste: 0.24, line: "ranked up: like 1 card you upvoted and 1 you downvoted", parts: [part(-0.918, "123", { title: "A JSON API" }), part(0.859, "3", { title: "Audit logs", graded_at: "2026-10-17T00:00:00Z" })] } }))
      .toBe("Ranked up: like #3 Audit logs, which you upvoted on 17 Oct; like #123 A JSON API, which you downvoted on 11 Oct.");
    expect(rankWhy({ number: 112, rank: { position: 1, taste: 0.9, line: "you graded it useful", parts: [] } })).toBe("You graded it useful.");
    expect(rankWhy({ number: 50, rank: { position: 50, taste: 0, line: "", parts: [] } })).toBeNull();
  });
  it("orders Waiting's cards by their rank, the rest after as they came", () => {
    const xs = [{ id: "a", p: null }, { id: "b", p: 3 }, { id: "c", p: 1 }, { id: "d", p: null }];
    expect(rankOrder(xs, (x) => x.p).map((x) => x.id)).toEqual(["c", "b", "a", "d"]);
  });
});
