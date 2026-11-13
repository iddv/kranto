import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { FEATURES_API, type FeatureRow, type Features } from "../../features/index";
import { SHELL_API, type Arrangement } from "../../features/shell";
import { HOME_API, VISIT_API } from "../../features/home";
import { REVIEW_API } from "../review/review";
import { TODAY_API } from "../topics/topics";
import Home from "./Home.svelte";
import { agoWords, awaySpan, coreNeeds, cubRows, everythingLine, nextWords, quietLine, sinceWords, uniqueRows } from "./home";
import { matchRoute, parse } from "../../lib/router";
import { ACT_PATH } from "../../lib/activity";
import { activityOf, incident } from "../../lib/activity.fixtures";

const NOW = new Date().toISOString();
const HOURS = (h: number) => new Date(Date.now() - h * 3600000).toISOString();
afterEach(() => { ui.facts = null; });

const host = { version: "0.6.0", topics: [{ id: 13, name: "Robotics" }], sources: [{ id: 1 }], update: null };
const today = { since: NOW, new_kept: 0, topics: [], messages: [], sources_failing: [], rising: [] };
const newsletter = (): FeatureRow => ({
  id: "newsletter", title: "Newsletter", says: "", version: "1.3.1", trust: "owner", enabled: true, mode: "drafts only", tickets_open: 1,
  manifest: { requests: ["newsletter.send"], ui: { nav: [], cards: {}, kind: "send", glyph: "mail",
    today_rows: [{ kind: "issue", read: "rows", group: "needs_you", primary: "newsletter.send", card: null }] } },
} as unknown as FeatureRow);
const FEATURES = (): Features => ({ api: "kranto-mod/1", reads: [], request_kinds: [], features: [newsletter()] });
const arr = (): Arrangement => ({ layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] });
const card = (id: number, h: number, grade: string | null = null) => ({ id, title: `Card ${id}`, at: HOURS(h), grade });

/** the home's read as the server answers it (core.home.today), with the newsletter's ask in rows */
const HOME = (o: Record<string, unknown> = {}) => ({
  date: NOW.slice(0, 10), now: NOW, sentence: "Today's brief is ready, and one draft waits for you.",
  waiting: { drafts: 1, prepared: 0 },
  briefs: { topics: [{ topic: { id: 13, name: "Robotics" }, brief: 26, at: HOURS(11), more: 2,
    items: [{ n: 0, title: "DeepMind releases Gemini Robotics 2.5", source: "deepmind.google" },
      { n: 1, title: "Fable 5.2 beats most robot models", source: "marblist.ai" },
      { n: 2, title: "Hasbro puts characters into robots", source: "therobotreport.com" }] }], more: 0 },
  ideas: { rows: [card(160, 20), card(159, 44, "useful"), card(158, 45), card(157, 90), card(156, 110)], new: 3, since: HOURS(60), total: 158 },
  quiet: { topics: 5, sources: 153, read_at: HOURS(2), next: null },
  visit: { at: HOURS(20), previous: HOURS(60) }, away_days: 3, away: null,
  slots: {}, budget_s: 2, widgets: [], custom: false, library: [], default: [],
  rows: { needs_you: { newsletter: { state: "ok", data: [{ id: "draft:5", title: "This week: Amazon grasps 66 objects", meta: "ready", at: HOURS(48), ticket: 7,
    ask: { line: "ready", said: null, open: true }, verb: "Open draft" }] } } },
  ...o,
});
const AWAY = {
  since: "2026-11-02T09:00:00Z", days: 9, ideas: 10, briefs: 9,
  sentence: "You were away for 9 days. Kranto wrote 9 briefs and 10 ideas. These five are the best.",
  rows: [{ kind: "card", ...card(155, 120) }, { kind: "card", ...card(153, 190) }, { kind: "card", ...card(151, 210) },
    { kind: "brief", brief: 26, n: 0, title: "DeepMind releases Gemini Robotics 2.5", topic: "Robotics", source: "deepmind.google", at: HOURS(11) },
    { kind: "brief", brief: 25, n: 0, title: "NVIDIA launches GR00T 2", topic: "Robotics", source: "therobotreport.com", at: HOURS(35) }],
};

function answers(home: unknown, extra: Record<string, unknown> = {}) {
  answering({ [FEATURES_API]: FEATURES(), [SHELL_API]: arr(), [TODAY_API]: today, [REVIEW_API]: { items: [] },
    [ACT_PATH]: activityOf(), [HOME_API]: home, ...extra });
}
const facts = () => {
  ui.facts = { header: { host: { paused: false, running: null, next: null }, run: [] }, bar: { word: { icon: "check", colour: "green", text: "Quiet" }, cells: [], size: null } } as unknown as Facts;
};
async function home(read: unknown, extra: Record<string, unknown> = {}) {
  answers(read, extra);
  const L = stub({ host });
  facts();
  const { target, done } = await draw(Home, where("home"));
  await settle();
  await settle();
  return { L, target, done };
}
const titles = (el: Element, sel: string) => [...el.querySelectorAll(`${sel} .r-title`)].map((x) => x.textContent);

describe("the home", () => {
  it("draws the date and sentence, the one thing, today's brief, five new ideas and the quiet line, and nothing else", async () => {
    const { L, target, done } = await home(HOME());
    expect(target.querySelector("h1")?.textContent).toMatch(/^[A-Z][a-z]+day \d+ [A-Z][a-z]+$/);
    expect(target.querySelector("#home-sentence")?.textContent).toBe("Today's brief is ready, and one draft waits for you.");
    // the one thing: the draft that waits, the page's one primary
    expect(target.querySelector("#next h2")?.textContent).toBe("This week: Amazon grasps 66 objects");
    expect(target.querySelector("#next .nk")?.textContent).toMatch(/^Next · Newsletter asks/);
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    const brief = target.querySelector("[aria-labelledby=home-brief-26]")!;
    expect(brief.querySelector("h2")?.textContent).toBe("Today's brief");
    expect(brief.querySelector(".n")?.textContent).toMatch(/^Robotics, written at \d\d:\d\d$/);
    expect(titles(brief, "")).toEqual(["DeepMind releases Gemini Robotics 2.5", "Fable 5.2 beats most robot models", "Hasbro puts characters into robots"]);
    expect(brief.querySelector(".r-title")?.getAttribute("href")).toBe("#/news/i/26/0");
    expect(brief.querySelector(".c-meta")?.textContent).toBe("deepmind.google");
    expect(brief.querySelector(".g-foot")?.textContent).toBe("2 more in this brief.");
    expect(brief.querySelector(".g-link")?.getAttribute("href")).toBe("#/news/b/26");
    const ideas = target.querySelector("[aria-labelledby=home-ideas]")!;
    expect(titles(ideas, "")).toEqual(["Card 160", "Card 159", "Card 158", "Card 157", "Card 156"]);
    expect(ideas.querySelector(".r-title")?.getAttribute("href")).toBe("#/ideas/card:160");
    expect(ideas.querySelector("#home-all-ideas")?.textContent).toBe("All 158");
    expect(ideas.querySelector(".n")?.textContent).toMatch(/^3 since [A-Z]/);
    expect(ideas.querySelectorAll(".grade").length).toBe(5);                                 // ▲ ▼ on each
    expect(ideas.querySelectorAll('.grade button[aria-pressed="true"]').length).toBe(1);   // #159's own ▲
    expect(target.querySelector("#home-quiet")?.textContent).toBe("5 topics and 153 sources, read 2 hours ago. Activity");
    // no tiles, no doors on the home, no cubs, no Arrange, no New today, no Needs you list
    for (const id of ["home-doors", "home-cubs", "home-arrange", "home-arrange-head", "home-new", "home-needs", "home-facts"]) expect(target.querySelector("#" + id), id).toBeNull();
    expect(target.textContent).not.toMatch(/\bCubs?\b|\bBuild\b|Arrange/);
    // the ordinary home marks the visit as it draws, once
    expect(L.api.mock.calls.filter((c) => c[0] === VISIT_API)).toEqual([[VISIT_API, {}]]);
    done();
  });

  it("gives way to While you were away after an absence, and marks the visit only on Show today", async () => {
    const { L, target, done } = await home(HOME({ away: AWAY, sentence: AWAY.sentence }));
    expect(target.querySelector("#home-sentence")?.textContent).toBe(AWAY.sentence);
    const away = target.querySelector("[aria-labelledby=home-away]")!;
    expect(away.querySelector("h2")?.textContent).toBe("While you were away");
    expect(away.querySelector(".n")?.textContent).toMatch(/^2 (to|November to) /);
    expect(titles(away, "")).toEqual(["Card 155", "Card 153", "Card 151", "DeepMind releases Gemini Robotics 2.5", "NVIDIA launches GR00T 2"]);
    expect(away.querySelectorAll(".r-title")[3]?.getAttribute("href")).toBe("#/news/i/26/0");
    // 12 (Codex 16, Gemini 9): one link said both and opened Ideas alone; now each its own
    expect(away.querySelector(".g-foot")?.textContent).toBe("Everything since 2 November: 10 ideas and 9 briefs");
    expect(away.querySelector("#home-everything")?.textContent).toBe("10 ideas");
    expect(away.querySelector("#home-everything")?.getAttribute("href")).toMatch(/^#\/ideas\?since=/);
    expect(away.querySelector("#home-everything-briefs")?.getAttribute("href")).toBe("#/news/earlier");
    expect(target.querySelector("[aria-labelledby=home-ideas]")).toBeNull();               // the brief and the cards give way
    expect(target.querySelector("[aria-labelledby=home-brief-26]")).toBeNull();
    expect(target.querySelector("#next")).not.toBeNull();                                    // the one thing still stands
    expect(L.api.mock.calls.some((c) => c[0] === VISIT_API)).toBe(false);                   // a reload shows it again
    (target.querySelector("#home-show-today") as HTMLButtonElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === VISIT_API).length).toBe(1);
    expect(target.querySelector("[aria-labelledby=home-away]")).toBeNull();
    expect(titles(target, "[aria-labelledby=home-ideas]")[0]).toBe("Card 160");
    done();
  });

  it("marks the visit when one of the five is opened", async () => {
    const { L, target, done } = await home(HOME({ away: AWAY }));
    const row = target.querySelector("[aria-labelledby=home-away] li") as HTMLElement;
    row.querySelector("a")!.addEventListener("click", (e) => e.preventDefault());
    (row.querySelector("a") as HTMLAnchorElement).click();
    await settle();
    expect(L.api.mock.calls.filter((c) => c[0] === VISIT_API).length).toBe(1);
    done();
  });

  it("draws Kranto's own trouble as the band above everything, and leaves out a block with nothing to say", async () => {
    const { target, done } = await home(HOME({ briefs: { topics: [], more: 0 }, ideas: { rows: [], new: 0, since: null, total: 0 }, quiet: { error: "no", error_id: "x" } }),
      { [ACT_PATH]: activityOf({ incidents: [incident()] }) });
    expect(target.querySelector("#home")!.firstElementChild?.id).toBe("incident-band");
    expect(target.querySelector("[aria-labelledby=home-ideas]")).toBeNull();
    expect(target.querySelector(".grp")).toBeNull();
    expect(target.querySelector("#home-quiet")).toBeNull();
    done();
  });

  // (mock `first`): until the newest topic's first brief, the home shows the
  // first hour: the read as it goes, the topic's four rows, and that the page may be closed
  it("shows the first hour while the first read runs", async () => {
    const first = { topic: { id: 13, name: "Robotics" }, quiet: null, news_on: true, no_key: false, brief_minutes: 3, early_kept: 8,
      read: { source_index: 2, sources: 5, kept: 4, judged: 19, started_at: HOURS(0) },
      rows: [{ key: "sources", title: "Sources", state: "done", words: "5 sources watched", at: HOURS(0) },
        { key: "read", title: "First read", state: "running", words: "Reading now: source 2 of 5 · 4 kept of 19 read", at: HOURS(0) },
        { key: "brief", title: "First brief", state: "waiting", words: "As soon as 8 items are kept", at: null },
        { key: "ideas", title: "First ideas", state: "waiting", words: "After the map, once 30 items are kept. So far: 4.", at: null }] };
    const { target, done } = await home(HOME({ first, briefs: { topics: [], more: 0 }, ideas: { rows: [], new: 0, since: null, total: 0 } }));
    expect(target.querySelector("#home-sentence")?.textContent).toBe("Kranto is reading Robotics for the first time.");
    const g = target.querySelector("[aria-labelledby=home-first]")!;
    expect(g.querySelector("h2")?.textContent).toBe("The first hour");
    expect(g.querySelector("#home-first-read")?.textContent).toBe("Kranto is reading · source 2 of 5 · 4 kept of 19 read · the first brief in about 3 minutes");
    expect(titles(g, "")).toEqual(["Sources", "First read", "First brief", "First ideas"]);
    expect(g.querySelector("#home-first-foot")?.textContent).toBe("You can close this page; Kranto keeps reading.");
    expect(g.querySelector("#home-first-topic")?.getAttribute("href")).toBe("#/topics/13");
    done();
  });
});

describe("the home's words", () => {
  const at = new Date(2026, 10, 11, 19, 0); // Wednesday 11 November, 19:00 local
  it("words the quiet line, the next run and the time since", () => {
    expect(agoWords(new Date(at.getTime() - 2 * 3600000).toISOString(), at.getTime())).toBe("2 hours ago");
    expect(agoWords(new Date(at.getTime() - 60000).toISOString(), at.getTime())).toBe("1 minute ago");
    expect(nextWords(new Date(2026, 10, 11, 22, 0).toISOString(), at)).toBe("tonight at 22:00");
    expect(nextWords(new Date(2026, 10, 12, 7, 0).toISOString(), at)).toBe("tomorrow at 07:00");
    expect(nextWords(new Date(2026, 10, 14, 7, 0).toISOString(), at)).toBe("on Saturday at 07:00");
    expect(quietLine({ topics: 5, sources: 153, read_at: new Date(at.getTime() - 2 * 3600000).toISOString(), next: { words: "ideas", at: new Date(2026, 10, 11, 22, 0).toISOString() } }, at))
      .toBe("5 topics and 153 sources, read 2 hours ago. Next: ideas tonight at 22:00.");
    expect(quietLine({ topics: 1, sources: 0, read_at: null, next: null }, at)).toBe("1 topic and 0 sources, not read yet.");
    expect(quietLine({}, at)).toBe("");
  });

  it("words where new counts from and the absence", () => {
    expect(sinceWords(null, at)).toBe("in the last day");
    expect(sinceWords(new Date(2026, 10, 9, 8, 0).toISOString(), at)).toBe("since Monday");
    expect(sinceWords(new Date(2026, 10, 2, 8, 0).toISOString(), at)).toBe("since 2 November");
    expect(awaySpan(new Date(2026, 10, 2, 9, 0).toISOString(), at)).toBe("2 to 11 November");
    expect(awaySpan(new Date(2026, 9, 28, 9, 0).toISOString(), at)).toBe("28 October to 11 November");
    expect(everythingLine({ since: new Date(2026, 10, 2, 9, 0).toISOString(), ideas: 10, briefs: 9 })).toBe("Everything since 2 November: 10 ideas and 9 briefs");
    expect(everythingLine({ since: new Date(2026, 10, 2, 9, 0).toISOString(), ideas: 1, briefs: 0 })).toBe("Everything since 2 November: 1 idea");
  });
});

describe("the one thing's candidates", () => {
  it("keeps every row's key unique whatever the reads hold", () => {
    const r = (key: string) => ({ key, title: key, meta: "", href: "#/", verb: "Open", age: null, from: "core", tags: [], glyph: "", tone: "" });
    expect(uniqueRows([r("a"), r("a"), r("b")]).map((x) => x.key)).toEqual(["a", "a~1", "b"]);
  });

  it("opens a cub's row on the cub's page with its object's sheet (QA B3: #/newsletter was no page)", () => {
    const mail = newsletter();
    const [r] = cubRows(mail, [{ id: "2026-10-20", title: "This week: Kodama raises $7M", ticket: 9 }], "needs_you");
    expect(r!.href).toBe("#/cub/newsletter?sel=o2026-10-20");
    expect(r!.verb).toBe("Confirm");
    expect(cubRows(mail, [{ id: 1, title: "x", open: "news?sel=f1" }], "needs_you")[0]!.href).toBe("#/news?sel=f1");
  });

  // the one thing and Needs you offered Send for a draft whose page said "Connect an
  // account to send"; with its account not connected the row opens the draft's page instead
  it("says Open, to the draft's page, for a draft whose account is not connected", async () => {
    stub({ host: {} });
    const post = (account: boolean) => ({ line: "", drafts: [{ id: 5, ticket: 8, account, kind: "newsletter", word: "newsletter", title: "x" }], sent: [], earlier: [], accounts: [] });
    answering({ "/api/post": post(false) });
    const ask = [{ id: "2026-11-09", title: "This week", ticket: 8, ask: true, verb: "Send" }];
    cubRows(newsletter(), ask as never, "needs_you");          // the read starts
    await settle();
    const [r] = cubRows(newsletter(), ask as never, "needs_you");
    expect([r!.verb, r!.href, "ask" in r!]).toEqual(["Open", "#/post/d/5", false]);
  });

  it("links every row the one thing may be to a route the app has", () => {
    const t = { ...today, topics: [{ id: 3, name: "Robotics", new_kept: 1, proposed: 2 }], sources_failing: [{}], messages: [{}] };
    const h = { ...host, update: { installed: "0.4.8", available: "0.4.9", to: "0.4.9", state: "available" } };
    const rows = [...coreNeeds(t as never, h as never, 3), ...cubRows(newsletter(), [{ id: 4, title: "A draft" }], "needs_you")];
    expect(rows.length).toBeGreaterThan(4);
    for (const r of rows) expect([r.href, matchRoute(parse(r.href).path)]).not.toEqual([r.href, null]);
    for (const r of rows) expect([r.href, ["today", "library", "desk"].includes(parse(r.href).path[0] || "")]).toEqual([r.href, false]);
  });
});
