import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../lib/app";
import { ui } from "../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../pages/testing.svelte";
import Card from "../ui/Card.svelte";
import { FEATURES_API, featureNav, featurePath, type Features } from "./index";
import NewsList from "./news/NewsList.svelte";
import NewsPane from "./news/NewsPane.svelte";
import { LATEST, ROWS, briefPath, cadenceWords, type Brief, type TopicRows } from "./news/news";

const NOW = new Date().toISOString();
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });

const card = { title: "headline", lines: ["body", "why"], fields: [{ key: "date", label: "Date", kind: "date" }], actions: [] };
const FEATURES: Features = {
  api: "kranto-mod/1", reads: [], request_kinds: ["toot.post"],
  features: [
    { id: "news", title: "News", says: "", version: "1.0.0", trust: "first-party", enabled: true, mode: "live", tickets_open: 0,
      manifest: { ui: { nav: [{ route: "news", word: "News", under: "Desk", count: "count" }], cards: { brief: card } } } },
    { id: "toot", title: "Toot", says: "", version: "1.0.0", trust: "first-party", enabled: false, mode: "practice", tickets_open: 0,
      manifest: { ui: { nav: [{ route: "cub/toot", word: "Toot", under: "Work", count: null }], cards: {} } } },
  ],
};
const brief = (o: Partial<Brief> = {}): Brief => ({
  id: 12, topic_id: 3, status: "ok", period_start: "2026-10-17T07:00:00Z", period_end: "2026-10-18T07:00:00Z",
  items: [
    { headline: "A humanoid ships", body: "A company shipped a humanoid, it says.", why: "Robots leave the lab.", cites: ["obs 5", "exa 1"], date: "2026-10-18",
      background: false, observation_ids: [5], urls: ["https://ex.com/a"],
      sources: [{ label: "obs 5", kind: "obs", id: 5, title: "Humanoid ships", url: "https://ex.com/a", date: "2026-10-18" },
                { label: "exa 1", kind: "web", id: null, title: "Launch post", url: "https://news.example.com/b", date: "2026-10-17" }] },
    { headline: "An old result", body: "An earlier study.", why: "Context.", cites: ["obs 2"], date: "2026-09-01", background: true,
      observation_ids: [2], urls: [], sources: [{ label: "obs 2", kind: "obs", id: 2, title: "Study", url: null, date: "2026-09-01" }] },
  ],
  quiet: null, error: null, search: { live: true, labels: ["Exa"], searched_at: NOW }, checks: { dropped_uncited: 1, repeats: 0, cut: 0 },
  cost_usd: 0.08, equiv_usd: null, model: "claude-sonnet-5-5", trigger: "schedule", created_at: NOW, ...o,
});
const rows = (on: boolean): TopicRows => ({
  enabled: true, search_off: null, spend: { month_usd: 0.42, today_usd: 0.08, calls: 5, equiv_usd: 0 },
  topics: [{ id: 3, name: "Robotics", status: "active", running: false, next_due: on ? "2026-10-19T07:00:00+00:00" : null, last: null,
             news: { topic_id: 3, enabled: on, cadence: "daily", hour: 7, weekday: 0 } }],
});

describe("the features' slots", () => {
  it("draws a navigator entry under its heading only while the feature is on", async () => {
    hosted();
    answering({ [FEATURES_API]: FEATURES, [featurePath("news", "count")]: { count: 2 } });
    featureNav("Desk", true); // the features' read goes out
    await settle();
    featureNav("Desk", true); // then News's count's
    await settle();
    expect(featureNav("Desk", true)).toEqual([{ to: "news", w: "News", n: 2 }]);
    expect(featureNav("Work", true)).toEqual([]);             // Toot is off: no entry
    expect(featureNav("Desk", false)).toEqual([]);            // no server, no feature
  });

  it("renders a declarative card as text", () => {
    const target = document.createElement("div");
    const c = mount(Card, { target, props: { schema: card, object: { headline: "<b>H</b>", body: "B", why: "W", date: "2026-10-18T07:00:00Z" } } });
    expect(target.querySelector(".card-t")?.textContent).toBe("<b>H</b>");
    expect([...target.querySelectorAll(".card-l")].map((p) => p.textContent)).toEqual(["B", "W"]);
    expect(target.querySelector("dd")?.textContent).toBe("2026-10-18");
    void unmount(c);
  });
});

describe("Desk › News", () => {
  it("lists the topics with News off and turns one on with one click", async () => {
    const L = stub({ answer: { next_due: "2026-10-19T07:00:00+00:00" } });
    hosted();
    answering({ [ROWS]: rows(false), [LATEST]: { topics: [] } });
    const { target, done } = await draw(NewsList, where("news"));
    expect(target.querySelector(".grp .empty")?.textContent).toBe("No brief yet. A new topic's first brief is written right after its first read."); // 
    const b = target.querySelector('[data-act="news-toggle"]') as HTMLButtonElement;
    expect(b.textContent).toBe("Turn on");
    b.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/news/act/toggle", { fields: { topic_id: 3, on: true } });
    expect(L.say).toHaveBeenCalledWith("News is on for Robotics: daily at 07:00, the first at 2026-10-19 07:00.");
    done();
  });

  it("shows a brief's items, their sources, Earlier, the search and the cost", async () => {
    stub();
    hosted();
    answering({ [briefPath(12)]: brief(), [ROWS]: rows(true), [FEATURES_API]: FEATURES });
    const { target, done } = await draw(NewsPane, where("news", "f12"), "#/news");
    await settle();
    expect(target.querySelector(".dt")?.textContent).toBe("Robotics");
    expect(target.querySelector("#s-items .card-t")?.textContent).toBe("A humanoid ships");
    expect([...target.querySelectorAll("#s-items .ctx a")].map((a) => a.getAttribute("href"))).toEqual(["#/library/o/5", "https://news.example.com/b"]);
    expect(target.querySelector("#s-earlier .card-t")?.textContent).toBe("An old result");
    expect(target.querySelector("#s-about")?.textContent).toContain("Searched");
    expect(target.querySelector(".acts .mono")?.textContent).toBe("2 items");
    expect(target.querySelector("#s-about")?.textContent).toContain("Settings › Spend");
    done();
  });

  it("offers no New idea from an item: typed ideas left with the factory", async () => {
    stub();
    hosted();
    answering({ [briefPath(12)]: brief(), [ROWS]: rows(true), [FEATURES_API]: FEATURES });
    const { target, done } = await draw(NewsPane, where("news", "f12"), "#/news");
    await settle();
    expect(target.querySelector('a[href^="#/ideas/new"]')).toBeNull();
    expect(target.querySelector("#brief-ideas")).toBeNull();
    done();
  });
  it("words a cadence", () => {
    expect(cadenceWords({ topic_id: 1, enabled: true, cadence: "weekly", hour: 6, weekday: 0 })).toBe("Mondays at 06:00");
  });
});
