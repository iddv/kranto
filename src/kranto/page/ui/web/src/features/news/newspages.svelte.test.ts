// News: Today as one line a story with one open in place, a story's
// own page (the item's page and the article's as one; #/news/a/<id> lands on it), a brief's day in
// Today's layout, Earlier as one row a day; no line says "[obs N]", "Kranto on" or an ISO date.
// News › Topics' rows are the one row with News's switch, how often and the hour in the sheet.
import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../../pages/testing.svelte";
import BriefPage from "./BriefPage.svelte";
import StoryPage from "./StoryPage.svelte";
import NewsToday from "./NewsToday.svelte";
import NewsTopics from "./NewsTopics.svelte";
import NewsTopicPane from "./NewsTopicPane.svelte";
import NewsEarlier from "./NewsEarlier.svelte";
import { LATEST, ROWS, articlePath, articlesPath, briefPagePath, minutesWords, outletOf, outletsLine, type Article, type Brief, type StoryIdea, type TopicRows } from "./news";
import { featurePath } from "../index";
import { closeDialog, dlg } from "../../ui/dialog.svelte";

const NOW = new Date().toISOString();
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const theme = { lineage_id: "L7", name: "Humanoids leave the lab", size: 865 };
const stories = (o: Record<string, Partial<StoryIdea>> = {}): Record<string, StoryIdea> => ({
  "0": { idea: null, theme, no_theme: null, story: "brief:12:1", ...o["0"] },
  "1": { idea: null, theme: null, no_theme: "An idea needs this story on the map: after tonight's map.", story: "brief:12:2", ...o["1"] },
  "2": { idea: null, theme: null, no_theme: null, story: "brief:12:3", ...o["2"] },
});
const brief = (o: Partial<Brief> = {}): Brief => ({
  id: 12, topic_id: 3, status: "ok", period_start: "2026-10-17T07:00:00Z", period_end: "2026-10-18T07:00:00Z",
  items: [
    { headline: "A humanoid ships", body: "A company shipped a humanoid, it says.", why: "Robots leave the lab.", cites: ["obs 5", "exa 1"], date: "2026-10-18",
      background: false, observation_ids: [5], urls: ["https://ex.com/a"],
      sources: [{ label: "obs 5", kind: "obs", id: 5, title: "Humanoid ships", url: "https://www.ex.com/a", date: "2026-10-18" },
                { label: "exa 1", kind: "web", id: null, title: "Launch post", url: "https://news.example.com/b", date: "2026-10-17", source: "Example News" }] },
    { headline: "A second story", body: "Something else happened.", why: "It changes the price of arms.", cites: ["obs 6"], date: "2026-10-18",
      background: false, observation_ids: [6], urls: [], sources: [{ label: "obs 6", kind: "obs", id: 6, title: "Arms", url: "https://arms.example.org/x", date: "2026-10-18" }] },
    { headline: "An old result", body: "An earlier study.", why: "Context.", cites: ["obs 2"], date: "2026-09-01", background: true,
      observation_ids: [2], urls: [], sources: [{ label: "obs 2", kind: "obs", id: 2, title: "Study", url: null, date: "2026-09-01" }] },
  ],
  quiet: null, error: null, search: { live: true, labels: ["Exa"], searched_at: NOW }, checks: { dropped_uncited: 1, repeats: 0, cut: 0 },
  cost_usd: 0.08, equiv_usd: null, model: "claude-sonnet-5-5", trigger: "schedule", created_at: NOW, stories: stories(), ...o,
});
const rows = (on: boolean): TopicRows => ({
  enabled: true, search_off: null, spend: null,
  topics: [{ id: 3, name: "Robotics", status: "active", running: false, next_due: on ? "2026-10-19T07:00:00+00:00" : null, last: { id: 12, status: "ok", created_at: NOW, items: 2 },
             news: { topic_id: 3, enabled: on, cadence: "daily", hour: 7, weekday: 0 } }],
});
const ok = { id: 7, status: "ok" as const, kind: "paper", headline: "Six models", minutes: 3, words: 522, diagram: "timeline", timeline: [], quiet: null, error: null, created_at: NOW, image: null };
const IDEAS = "/api/ideas?embedding=ref";

describe("News › Today: one line a story", () => {
  it("keeps the good brief when a newer try failed, with one line under it saying why and where to fix it", async () => {
    stub();
    hosted();
    const why = "Claude Code is not installed on this machine. Install it, or choose another provider on Settings › Watching.";
    answering({ [LATEST]: { topics: [{ topic: { id: 3, name: "Robotics" }, brief: brief(), failed: { id: 13, created_at: NOW, why, fix: "settings/watching" } }] },
      [ROWS]: rows(true), [IDEAS]: { ideas: [] } });
    const { target, done } = await draw(NewsToday, where("news"));
    await settle();
    // the good brief's stories are still there
    expect(target.querySelectorAll("section.brief li.story").length).toBeGreaterThan(0);
    const line = target.querySelector("p.failed-try")!;
    expect(line.textContent).toContain("A newer brief could not be written at");
    expect(line.textContent).toContain("Claude Code is not installed on this machine");
    expect(line.querySelector("a")?.getAttribute("href")).toBe("#/settings/watching");
    expect(target.querySelector(".quiet-topic")).toBeNull();
    done();
  });

  it("says how much there is, opens the first story, and draws the others as one line each", async () => {
    stub();
    hosted();
    answering({ [LATEST]: { topics: [{ topic: { id: 3, name: "Robotics" }, brief: brief({ articles: { "0": ok } }) }] }, [ROWS]: rows(true),
      [IDEAS]: { ideas: [{ id: 133, state: "waiting", topic: { id: 3 } }] } });
    const { target, done } = await draw(NewsToday, where("news"));
    await settle();
    expect(target.querySelector(".ph .muted.small, .lsub, .facts")?.textContent || target.textContent).toMatch(/2 stories in Robotics · about a minute/);
    const open = target.querySelector("li.story.open")!;
    expect(open.getAttribute("data-story")).toBe("12.0");
    expect(open.querySelector("h3 a")?.getAttribute("href")).toBe("#/news/i/12/0");
    expect(open.querySelector(".why")?.textContent).toBe("Why it matters · Robots leave the lab.");
    expect(open.querySelector(".st-src")?.textContent).toContain("ex.com, Example News");
    expect([...open.querySelectorAll(".st-verbs .btn")].map((b) => b.textContent)).toEqual(["Read the story · 3 min", "Write a post", "Idea from this"]);
    expect(target.querySelector(".btn.primary")).toBeNull();                        // News has no primary
    const row = target.querySelector("li.story:not(.open) .story-row")!;
    expect(row.textContent).toContain("A second story");
    expect(row.textContent).toContain("arms.example.org");
    expect(target.querySelector(".earlier-stories summary")?.textContent).toBe("1 from earlier ▾");
    expect(target.querySelector(".day-ideas")?.textContent).toBe("1 idea from Robotics waits ›");
    expect(target.textContent).not.toMatch(/\[obs \d+\]|Kranto on|\d{4}-\d{2}-\d{2}/);
    // a click opens another in place and closes the first; the address keeps it
    (row as HTMLButtonElement).click();
    await settle();
    expect(target.querySelector("li.story.open")?.getAttribute("data-story")).toBe("12.1");
    expect(location.hash).toContain("s=12.1");
    // j and k move the open story
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k" }));
    await settle();
    expect(target.querySelector("li.story.open")?.getAttribute("data-story")).toBe("12.0");
    done();
  });

  it("offers Write the full story when a story has none, and Idea from this as theme.card with a hint, which asks first", async () => {
    const L = stub({ answer: { started: true } });
    hosted();
    answering({ [LATEST]: { topics: [{ topic: { id: 3, name: "Robotics" }, brief: brief() }] }, [ROWS]: rows(true), [IDEAS]: { ideas: [] } });
    const { target, done } = await draw(NewsToday, where("news"));
    await settle();
    const verbs = [...target.querySelectorAll("li.story.open .st-verbs .btn")];
    expect(verbs.map((b) => b.textContent)).toEqual(["Write the full story", "Write a post", "Idea from this"]);
    (verbs[2] as HTMLButtonElement).click();
    await settle();
    const shown = JSON.stringify(dlg.now?.props, (_k, v) => (v instanceof HTMLElement ? v.textContent : v));
    expect(shown).toContain("Write an idea card from this story's theme?");
    expect(shown).toContain("Humanoids leave the lab, 865 items");
    closeDialog();
    (verbs[1] as HTMLButtonElement).click();
    await settle();
    expect(dlg.now?.props.about).toEqual({ brief: 12, n: 0, title: "A humanoid ships", sources: 2 });
    closeDialog();
    void L;
    done();
  });

  it("names a story's idea when the rules found one, with no Idea from this", async () => {
    stub();
    hosted();
    const idea = { id: 133, title: "Failure-targeted data collection", state: "waiting", rule: 3, more: 2 };
    answering({ [LATEST]: { topics: [{ topic: { id: 3, name: "Robotics" }, brief: brief({ stories: stories({ "0": { idea } }) }) }] }, [ROWS]: rows(true), [IDEAS]: { ideas: [] } });
    const { target, done } = await draw(NewsToday, where("news"));
    await settle();
    const open = target.querySelector("li.story.open")!;
    expect(open.querySelector(".st-idea")?.textContent).toBe("Idea · #133 Failure-targeted data collection · waiting · and 2 more ›");
    expect(open.querySelector(".st-idea a")?.getAttribute("href")).toBe("#/ideas/133");
    expect([...open.querySelectorAll(".st-verbs .btn")].map((b) => b.textContent)).not.toContain("Idea from this");
    done();
  });

  it("says when a new topic's first brief comes, and marks the first read's", async () => {
    stub();
    hosted();
    const padel = { ...rows(true).topics[0]!, id: 5, name: "Padel", last: null };
    answering({ [LATEST]: { topics: [{ topic: { id: 3, name: "Robotics" }, brief: brief({ trigger: "first_read" }) }, { topic: { id: 5, name: "Padel" }, brief: null }] },
      [ROWS]: { ...rows(true), topics: [...rows(true).topics, padel] }, [IDEAS]: { ideas: [] } });
    const { target, done } = await draw(NewsToday, where("news"));
    await settle();
    expect([...target.querySelectorAll("p.first-brief")].map((p) => p.textContent)).toEqual(["The first brief for Padel is written as soon as 8 items are kept in its first read."]);
    expect(target.querySelector(".brief .first-read")?.textContent).toBe("From the first read. Tomorrow's covers a day.");
    done();
  });

  it("words its helpers plainly", () => {
    expect(minutesWords(197)).toBe("about a minute");
    expect(minutesWords(700)).toBe("about three minutes");
    expect(outletsLine(brief().items[0]!.sources)).toBe("ex.com +1");
    expect(outletOf({ kind: "web", url: "https://www.arxiv.org/x", source: null })).toBe("arXiv");
    expect(outletOf({ kind: "web", url: null, source: "Reuters" })).toBe("Reuters");
    expect(outletOf({ kind: "web", url: "https://hn.algolia.com/x", source: "HN search: coding agent" })).toBe("Hacker News");
    expect(outletOf({ kind: "obs", url: null, source: null })).toBe("your library");
  });
});

describe("a brief's own day", () => {
  it("is Today's layout for that day, with About this brief under Details", async () => {
    stub();
    hosted();
    answering({ [briefPagePath(12)]: brief(), [ROWS]: rows(true), [IDEAS]: { ideas: [] } });
    const { target, done } = await draw(BriefPage, where("news/b/12"));
    await settle();
    expect(target.querySelector("h1")?.textContent).toBe("Robotics");
    expect(target.querySelector("li.story.open")?.getAttribute("data-story")).toBe("12.0");
    const about = target.querySelector("#brief-about")!;
    expect(about.tagName).toBe("DETAILS");
    expect(about.textContent).toContain("1 story dropped for citing nothing");
    expect(about.textContent).toContain("Searched the web on");
    expect(target.textContent).not.toMatch(/\bok\b|\bExa\b|\d{4}-\d{2}-\d{2}/);
    done();
  });
});

const article = (o: Partial<Article> = {}): Article => ({
  id: 7, topic_id: 3, topic: "Robotics", brief_id: 12, item_n: 0, status: "ok", kind: "paper",
  headline: "Six frontier models run LIBERO-10 as robot controllers, best at 44%",
  standfirst: "A paper tests six frontier models as closed-loop controllers; the best reaches 44%.",
  words: 522, minutes: 3, diagram: "timeline", quiet: null, error: null, trigger: "schedule", created_at: NOW,
  timeline: [{ date: "2026-10-19" }], image: null,
  body: {
    sections: [
      { id: "what", title: "What happened", paragraphs: [{ text: "The paper runs 1,800 episodes over 18 configurations.", cites: ["obs 5", "page 1"] }] },
      { id: "before", title: "What came before", paragraphs: [{ text: "Earlier, a coding agent learned control.", cites: ["obs 5"] }] },
      { id: "who", title: "Who is involved", paragraphs: [{ text: "Three labs and one benchmark.", cites: ["obs 5"] }] },
    ],
    numbers: [{ label: "best success rate", value: "44", unit: "%", cites: ["obs 5"] }],
    timeline: [], series: null, entities: [], relations: [], themes: [], idea_seed: "Test a small open model on the same harness.",
    standfirst_cites: ["obs 5"], evidence_timeline: [], image: null,
  },
  sources: [{ label: "obs 5", kind: "obs", id: 5, title: "Humanoid ships", url: "https://www.ex.com/a", date: "2026-10-22" },
            { label: "page 1", kind: "page", id: null, title: "Humanoid ships", url: "https://www.ex.com/a", date: "2026-10-23", source: "the page behind it" },
            { label: "s3", kind: "web", id: null, title: "Three", url: "https://c.example/3", date: "2026-10-23" },
            { label: "s4", kind: "web", id: null, title: "Four", url: "https://d.example/4", date: "2026-10-23" },
            { label: "s5", kind: "web", id: null, title: "Five", url: "https://e.example/5", date: "2026-10-23" }],
  checks: {}, material: { counts: {}, earlier: 0, pages: [], search: null },
  model: "claude-sonnet-5-5", prompt_version: "news_article-x", brief_at: NOW, newest_id: 7, ...o,
});

describe("a story's page", () => {
  it("is the summary, Why it matters with its idea seed, the article in its own order, four sources and Next", async () => {
    stub();
    hosted();
    answering({ [briefPagePath(12)]: brief({ articles: { "0": ok } }), [articlePath(7)]: article(), [ROWS]: rows(true) });
    const { target, done } = await draw(StoryPage, where("news/i/12/0"));
    await settle();
    expect(target.querySelector("h1")?.textContent).toBe("A humanoid ships");
    expect(target.querySelector(".lsub")?.textContent).toContain("closed-loop controllers");
    expect(target.textContent).toMatch(/Story 1 of 2 · 5 sources · 3 min read · written/);
    expect(target.querySelector("#story-write")?.textContent).toContain("Write a post");
    expect(target.querySelectorAll(".btn.primary").length).toBeLessThanOrEqual(1);
    expect(target.querySelector("#story-why")?.textContent).toContain("Robots leave the lab.");
    expect(target.querySelector("#story-why")?.textContent).toContain("An idea in it · Test a small open model");
    expect(target.querySelector("#story-idea-from")?.textContent).toBe("Idea from this");
    expect(target.querySelector("#story-read-on summary")?.textContent).toMatch(/^Read on: What came before · Who is involved \(\d+ words\)$/);
    expect(target.querySelectorAll("#s-evidence > ol .ns-d").length).toBe(4);
    expect(target.querySelector("#story-all-sources summary")?.textContent).toBe("All 5 sources");
    expect(target.querySelector("#story-next")?.textContent).toBe("Next: A second story ›");
    expect(target.textContent).not.toMatch(/There is no page|\[obs \d+\]|\d{4}-\d{2}-\d{2}/);
    done();
  });

  it("without an article offers Write the full story; a story on no theme says why there is no idea", async () => {
    stub();
    hosted();
    answering({ [briefPagePath(12)]: brief(), [ROWS]: rows(true) });
    const { target, done } = await draw(StoryPage, where("news/i/12/1"));
    await settle();
    expect(target.querySelector("#story-full")?.textContent).toBe("Write the full story");
    expect(target.querySelector("#story-idea-from")).toBeNull();
    expect(target.querySelector("#story-no-idea")?.textContent).toBe("An idea needs this story on the map: after tonight's map.");
    done();
    const gone = await draw(StoryPage, where("news/i/12/9"));
    await settle();
    expect(gone.target.textContent).toContain("has no story 10");
    gone.done();
  });

  it("#/news/a/<id> lands on its story's page", async () => {
    stub();
    hosted();
    answering({ [articlePath(16)]: article({ id: 16, brief_id: 26, item_n: 0 }) });
    const { done } = await draw(StoryPage, where("news/a/16"));
    await settle();
    expect(location.hash).toBe("#/news/i/26/0");
    done();
  });
});

describe("News › Earlier: one row a day", () => {
  it("is the day, its lead headline, full story, and how many stories; a row opens the day", async () => {
    stub();
    hosted();
    answering({ [featurePath("news", "briefs.list", { limit: 50 })]: { briefs: [brief()] }, [ROWS]: rows(true),
      [articlesPath("")]: { articles: [{ ...ok, brief_id: 12, topic_id: 3 }] } });
    const e = await draw(NewsEarlier, where("news/earlier"));
    await settle();
    const row = e.target.querySelector("li.row")!;
    expect(row.querySelector("a.r-title")?.getAttribute("href")).toBe("#/news/b/12");
    expect(row.textContent).toContain("A humanoid ships");
    expect(row.textContent).toContain("full story");
    expect(row.textContent).toContain("2 stories");
    e.done();
  });
});

describe("News › Topics", () => {
  it("is a row a topic with News's switch, its cadence and hour in the meta; its sheet changes them", async () => {
    const L = stub({ answer: { next_due: "2026-10-19T06:00:00+00:00" } });
    hosted();
    answering({ [ROWS]: rows(true) });
    const { target, done } = await draw(NewsTopics, where("news/topics"));
    await settle();
    const row = target.querySelector("li.row")!;
    expect(row.querySelector(".c-meta")?.textContent).toBe("daily at 07:00 · next 2026-10-19 07:00");
    expect(row.querySelector("select")).toBeNull();                                  // no select on a row
    (row.querySelector('[role="switch"]') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/news/act/toggle", { fields: { topic_id: 3, on: false } });
    done();
    const L2 = stub({ answer: {} });
    hosted();
    answering({ [ROWS]: rows(true) });
    const p = await draw(NewsTopicPane, where("news/topics", "t3"));
    await settle();
    const hour = p.target.querySelector("#nt-hour") as HTMLSelectElement;
    hour.value = "6";
    hour.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(L2.api).toHaveBeenCalledWith("/api/f/news/act/toggle", { fields: { topic_id: 3, on: true, hour: 6 } });
    expect(p.target.querySelector("#nt-brief-now")?.textContent).toBe("Brief now");
    p.done();
  });
});
