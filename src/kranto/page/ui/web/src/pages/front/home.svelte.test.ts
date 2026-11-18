import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { FEATURES_API, type FeatureRow, type Features } from "../../features/index";
import { SHELL_API, type Arrangement } from "../../features/shell";
import { HOME_API, VISIT_API } from "../../features/home";
import { REVIEW_API } from "../review/review";
import { TODAY_API } from "../topics/topics";
import Home from "./Home.svelte";
import NeedsPage from "./NeedsPage.svelte";
import { featurePath } from "../../features/index";
import { PREPARED_API } from "../../lib/prepared";
import { IDEAS_API } from "../ideas/cards";
import { UPD_API } from "../settings/updates";
import { DISPATCH_API } from "./needs";
import { agoWords, awaySpan, coreNeeds, cubRows, everythingLine, nextLine, nextWords, quietLine, setupRow, sinceWords, uniqueRows, type HomeRow } from "./home";
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

describe("the one thing's line", () => {
  it("says who asks in a shape that fits a plural name: never \"Blog posts asks\"", () => {
    const r = { key: "blog:d1", title: "A post", meta: "", href: "#/post", from: "blog", age: "3 min", tags: [{ word: "Blog posts", tone: "owner" }] } as unknown as HomeRow;
    expect(nextLine(r)).toBe("asked by Blog posts, 3 min ago");
    expect(nextLine({ ...r, age: "now" })).toBe("asked by Blog posts, just now");
    expect(nextLine(r)).not.toMatch(/\basks\b/);
  });
});

describe("the home", () => {
  it("draws the date and sentence, the one thing, today's brief, five new ideas and the quiet line, and nothing else", async () => {
    const { L, target, done } = await home(HOME());
    expect(target.querySelector("h1")?.textContent).toMatch(/^[A-Z][a-z]+day \d+ [A-Z][a-z]+$/);
    expect(target.querySelector("#home-sentence")?.textContent).toBe("Today's brief is ready, and one draft waits for you.");
    // the one thing: the draft that waits, the page's one primary
    expect(target.querySelector("#next h2")?.textContent).toBe("This week: Amazon grasps 66 objects");
    expect(target.querySelector("#next .nk")?.textContent).toMatch(/^Next · asked by Newsletter, /);
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
    const quiet = { topics: 1, sources: 5, read_at: null, next: null };
    const { target, done } = await home(HOME({ first, quiet, briefs: { topics: [], more: 0 }, ideas: { rows: [], new: 0, since: null, total: 0 } }));
    expect(target.querySelector("#home-sentence")?.textContent).toBe("Kranto is reading Robotics for the first time.");
    const g = target.querySelector("[aria-labelledby=home-first]")!;
    expect(g.querySelector("h2")?.textContent).toBe("The first hour");
    // the topic page's first-hour rows (.grp.start): the time keeps its width, the words go under
    expect(g.classList.contains("start")).toBe(true);
    // a first run: the foot line said "not read yet" while the first read ran
    expect(target.querySelector("#home-quiet")?.textContent).toBe("1 topic and 5 sources, reading now. Activity");
    expect(g.querySelector("#home-first-read")?.textContent).toBe("Kranto is reading · source 2 of 5 · 4 kept of 19 read · the first brief in about 3 minutes");
    expect(titles(g, "")).toEqual(["Sources", "First read", "First brief", "First ideas"]);
    expect(g.querySelector("#home-first-foot")?.textContent).toBe("You can close this page; Kranto keeps reading.");
    expect(g.querySelector("#home-first-topic")?.getAttribute("href")).toBe("#/topics/13");
    done();
  });
});

// a tester found the home and Needs you naming different drafts: the chip, the home's
// one thing and Needs you's Next read the same list in the same order
describe("the one thing, on the home and on Needs you", () => {
  const prep = (uuid: string, h: number, subject: string) => ({ uuid, verb: "topic.archive", title: "Archive topic", by_words: "by Claude Code",
    page: "#/watch/topics", words: null, fields: {}, subject_kind: "topic", subject_id: "15", subject_name: subject, state: "open",
    button: "Archive", available: true, created_at: HOURS(h) });
  const READS = (prepared: unknown[]) => ({
    [PREPARED_API]: { prepared }, [featurePath("newsletter", "rows")]: { rows: HOME().rows.needs_you.newsletter.data },
    [IDEAS_API]: { ideas: [] }, "api/term": { enabled: false, sessions: [] }, [UPD_API]: { candidate: null }, [DISPATCH_API]: { ideas: [] },
  });
  /** the app, stubbed with what Needs you calls of it too (its keys, its signature) */
  function needsApp() {
    const L = stub({ host });
    Object.assign(L, { pageKey: vi.fn(), sigOf: (n: Element) => n.className + "|" + (n.textContent || "") });
    facts();
    return L;
  }
  async function both(prepared: unknown[]): Promise<[string | null, string | null]> {
    const a = await home(HOME(), READS(prepared));
    const onHome = a.target.querySelector("#next h2")?.textContent ?? null;
    a.done();
    answers(HOME(), READS(prepared));
    needsApp();
    const b = await draw(NeedsPage, where("needs"));
    await settle();
    await settle();
    const onNeeds = b.target.querySelector("#next h2")?.textContent ?? null;
    b.done();
    return [onHome, onNeeds];
  }

  it("names the same draft: the newsletter's draft, then the newest prepared item", async () => {
    expect(await both([])).toEqual(["This week: Amazon grasps 66 objects", "This week: Amazon grasps 66 objects"]);
    const [h, n] = await both([prep("p-old", 30, "Lab tools"), prep("p-new", 1, "Padel")]);
    expect(h).toBe("Archive topic: Padel");
    expect(n).toBe(h);
  });

  it("gives a prepared item Dismiss beside its yes on Needs you, named by its subject, and Dismiss puts it away", async () => {
    answers(HOME(), READS([prep("p-new", 1, "Padel"), prep("p-old", 30, "Lab tools")]));
    const L = needsApp();
    const page = await draw(NeedsPage, where("needs"));
    await settle();
    await settle();
    const t = page.target;
    const yes = t.querySelector("[data-prepared-act='p-old']") as HTMLButtonElement;
    expect(yes.textContent).toBe("Archive");
    const no = t.querySelector("[data-prepared-dismiss='p-old']") as HTMLButtonElement;
    expect(no.textContent).toBe("Dismiss");
    expect(no.getAttribute("aria-label")).toBe("Dismiss Archive topic: Lab tools");
    expect(no.parentElement).toBe(yes.parentElement);                       // beside its yes
    expect(t.querySelector("[data-prepared-dismiss='p-new']")?.getAttribute("aria-label")).toBe("Dismiss Archive topic: Padel");
    expect(t.textContent).not.toContain("topic #15");
    // Dismiss is the item's own (POST /api/prepared/<uuid>/dismiss), as on its page's line
    const posted: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") posted.push(url);
      return new Response(JSON.stringify({ state: "dismissed" }), { status: 200 });
    }));
    no.click();
    await settle();
    vi.unstubAllGlobals();
    expect(posted).toEqual(["/api/prepared/p-old/dismiss"]);
    expect(L.api).not.toHaveBeenCalledWith("/api/prepared/p-old/press", expect.anything());
    page.done();
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
    // a first read that runs now, said by the server or by the first hour's read row
    expect(quietLine({ topics: 1, sources: 5, read_at: null, reading: true, next: null }, at)).toBe("1 topic and 5 sources, reading now.");
    expect(quietLine({ topics: 1, sources: 5, read_at: null, next: null }, at, true)).toBe("1 topic and 5 sources, reading now.");
    const read = new Date(at.getTime() - 3600000).toISOString();
    expect(quietLine({ topics: 1, sources: 5, read_at: read, reading: true, next: null }, at)).toBe("1 topic and 5 sources, read 1 hour ago.");
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

  it("opens a cub's row on the cub's page with its object's sheet (#/newsletter was no page)", () => {
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

// An unfinished install: the home said "No brief yet today, and nothing waits for you." with no
// way to Welcome; on a phone the status bar that says "Choose a topic to watch on Welcome" is not
// drawn. The home's one thing leads there now, at the step still missing.
describe("an unfinished install's home", () => {
  it("names what is missing and where Set up goes", () => {
    const none = setupRow({ key: { set: false }, topics: 0 }, "Not set up yet")!;
    expect([none.title, none.meta, none.href, none.verb, none.want]).toEqual(
      ["Kranto is not set up yet", "Still missing: a model (step 1), and a topic to watch (step 2).", "#/welcome", "Set up", "decision"]);
    expect(nextLine(none)).toBe("to start");
    expect(setupRow({ key: { set: true }, topics: 0 }, "Not set up yet")!.href).toBe("#/welcome/topics");
    const unwatched = setupRow({ key: { set: true }, topics: 1 }, "Not set up yet")!;
    expect([unwatched.meta, unwatched.href]).toEqual(["Still missing: a place to read for your topic (step 2).", "#/welcome/topics"]);
    expect(setupRow({ key: { set: false }, topics: 2 }, "Reading for the first time")!.meta).toBe("Still missing: a model (step 1).");
    // a finished one, or a server too old to say: nothing
    expect(setupRow({ key: { set: true }, topics: 1 }, "Healthy")).toBeNull();
    expect(setupRow({ key: { set: true }, topics: 1 }, "Reading for the first time")).toBeNull();
    expect(setupRow(null, "Not set up yet")).toBeNull();
  });

  it("draws Set up as the one thing and says no brief comes until setup is finished", async () => {
    const bare = HOME({ sentence: "No brief yet today, and nothing waits for you.", waiting: { drafts: 0, prepared: 0 }, briefs: { topics: [], more: 0 },
      ideas: { rows: [], new: 0, since: null, total: 0 }, rows: { needs_you: {} } });
    const { target, done } = await home(bare, { "/api/setup": { needs_setup: false, done: true, key: { set: false }, topics: 0 },
      [PREPARED_API]: { prepared: [] }, [featurePath("newsletter", "rows")]: { rows: [] } });
    expect(target.querySelector("#home-sentence")?.textContent).toBe("No brief yet, and none comes until setup is finished.");
    expect(target.querySelector("#next h2")?.textContent).toBe("Kranto is not set up yet");
    expect(target.querySelector("#next .nk")?.textContent).toBe("Next · to start");
    const primary = target.querySelectorAll<HTMLAnchorElement>(".btn.primary");
    expect(primary.length).toBe(1);
    expect([primary[0]!.textContent, primary[0]!.getAttribute("href")]).toEqual(["Set up", "#/welcome"]);
    done();
  });

  it("is not drawn on a home that is set up", async () => {
    const { target, done } = await home(HOME(), { "/api/setup": { needs_setup: false, done: true, key: { set: true }, topics: 1 },
      [PREPARED_API]: { prepared: [] }, [featurePath("newsletter", "rows")]: { rows: HOME().rows.needs_you.newsletter.data } });
    expect(target.querySelector("#next h2")?.textContent).toBe("This week: Amazon grasps 66 objects");
    done();
  });
});
