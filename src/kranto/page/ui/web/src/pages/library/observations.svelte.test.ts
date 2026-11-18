import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import ObsList from "./ObsList.svelte";
import ObsPane from "./ObsPane.svelte";
import { put } from "../../lib/reads.svelte";
import { gradesPath, obsQuery, obsSelects, type ObservationPage, type Observation, type Observations } from "./library";

const NOW = new Date().toISOString();
const obs = (id: number, o: Partial<Observation> = {}): Observation => ({
  id, kind: "mild_signal", title: null, summary: `Observation ${id} says something about local-first sync. More follows.`, why_it_matters: "", content_quality: 0.8,
  durability: 0.5, opportunity: 0.5, signal: 0.2, override: false, override_reason: null, tags: [], source_url: null, source_excerpt: null, item_published_at: null,
  source_id: 14, source_label: "HN", admitted_by: "topic", created_at: NOW, llm_call_id: null, prompt_version: null, grade: null, ...o,
});
// The server's /api/observations (Observations is generated from its web/types.py)
const page = (results: Observation[], o: Partial<Observations> = {}): Observations => ({
  total: results.length, offset: 0, cluster_label: null, seen_at: null, marker: "", since: null, new_total: results.filter((x) => x.new).length, results, ...o,
});
const HOST = { topics: [{ id: 1, name: "Local-first" }], sources: [{ id: 14, kind: "hn", label: "HN", status: "approved" }, { id: 20, kind: "parallax", label: "PX", status: "imported" }, { id: 21, kind: "rss", label: "Gone", status: "proposed" }] };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const at = (path: string[], q: Record<string, string> = {}, object: string | null = null): Where =>
  ({ ...where("library"), r: { path, q, sel: null }, object, obj: object ? path : null, id: object ? path[2] ?? null : null });

/** the old module, stubbed with what the Library calls of it */
function lib() {
  const L = stub({ host: HOST });
  Object.assign(L, { pageKey: vi.fn(), sigOf: (n: Element) => n.className + "|" + (n.textContent || "") });
  hosted();
  return L as typeof L & { pageKey: ReturnType<typeof vi.fn> };
}

describe("Library › Observations", () => {
  it("reads a page of the library, a search by meaning, or the first 20", () => {
    expect(obsQuery({}).path).toBe("/api/observations?sort=new&limit=100&offset=0");
    expect(obsQuery({ q: "sync", page: "2" }).path).toBe("/api/observations?q=sync&cutoff=1&limit=20&offset=20");
    expect(obsQuery({ q: "sync", by: "words", sort: "signal", top: "20" })).toMatchObject({ path: "/api/observations?contains=sync&sort=signal&limit=20&offset=0", at: 1, top: 20 });
    expect(obsQuery({ since: "24h" }, Date.parse("2026-10-15T12:00:00Z")).path).toBe("/api/observations?since=2026-10-14T12%3A00%3A00Z&sort=new&limit=100&offset=0");
    // the same read for the whole minute: a draw is not a new read
    expect(obsQuery({ since: "7d" }, Date.parse("2026-10-15T12:00:59Z")).path).toBe(obsQuery({ since: "7d" }, Date.parse("2026-10-15T12:00:01Z")).path);
    const s = obsSelects(HOST, false);
    expect(s.map((x) => x[0])).toEqual(["by", "since", "topic", "source", "kind", "min_signal", "sort"]);
    expect(s[3]?.[2]).toEqual([["", ""], ["parallax", "Parallax archive (all)"], ["14", "HN"], ["20", "PX"]]);
    expect(obsSelects(HOST, true).map((x) => x[0])).not.toContain("sort");
  });

  it("without the server says the library needs it", async () => {
    stub();
    answering({});
    const { target, done } = await draw(ObsList, where("library"));
    expect(target.querySelector("[data-title=Library] strong")?.textContent).toBe("The library needs Kranto's server, which is not answering. ");
    done();
  });

  it("groups the rows by their new flag, each with its mute and grade, no tick", async () => {
    const L = lib();
    const d = page([obs(3, { new: true, signal: 0.42 }), obs(2), obs(1, { source_id: null, source_label: null })], { total: 3, new_total: 1 });
    answering({ [obsQuery({}).path]: d, [gradesPath([3, 2, 1])]: { grades: { "2": { value: "useful" } } } });
    const { target, done } = await draw(ObsList, where("library"));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["New since your last visit", "Seen before"]);
    expect([...target.querySelectorAll(".grp .ghd .n")].map((h) => h.textContent)).toEqual(["1", "2"]);
    expect(target.querySelector("#ev-new")?.parentElement?.querySelector(".muted")?.textContent).toBe("in the last 24 hours");
    const row = target.querySelector("#ev-new")!.closest("section")!.querySelector("li.row")!;
    expect(row.classList.contains("new")).toBe(true);
    expect(row.querySelector(".c-num.hot .hotmark")?.getAttribute("aria-label")).toBe("signal 0.42");   // the mark, its number on the sheet
    expect(row.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library/o/3");
    expect(row.querySelector(".c-meta")?.textContent).toBe("#3 mild signal");
    expect(row.querySelector(".c-aside a.src")?.getAttribute("href")).toBe("#/settings/sources/14");
    expect(row.querySelector("input.tick")).toBeNull(); // no tick, no Select
    // the grade cluster: the second row's, pressed with its grade from the server's feedback read
    const two = target.querySelector('.grade[data-grade="observation:2"]')!;
    expect(two.getAttribute("aria-label")).toBe("Grade #2");
    expect(two.querySelector("button[aria-pressed=true]")?.getAttribute("data-v")).toBe("useful");
    // no mute on the row: Mute is on the observation's sheet and the source's
    expect(row.querySelector(".c-aside")?.children.length).toBe(1);
    expect(target.querySelector("button.mute")).toBeNull();
    void L;
    expect(target.querySelectorAll("li.row")[2]?.querySelector(".c-aside")?.textContent).toBe("imported");
    // the toolbar: the old module's filters, Mark all seen (⇧a) and the bulk bar
    expect(target.querySelector(".tb > .tbn.filters > #search")).not.toBeNull();
    expect(target.querySelector("#bulk, #select-rows")).toBeNull();
    expect((target.querySelector("#search") as HTMLInputElement).placeholder).toBe("Ask the library  ( / )");
    expect(L.pageKey).toHaveBeenCalledWith("⇧a", expect.any(Function));
    (target.querySelector("#mark-seen") as HTMLButtonElement).click();
    expect(L.api).toHaveBeenCalledWith("/api/seen", {});
    done();
  });

  it("cuts a page at the top 20 with Show all, and pages the rest", async () => {
    lib();
    const top = { top: "2", sort: "signal" };
    answering({ [obsQuery(top).path]: page([obs(5), obs(4)], { total: 9 }), [gradesPath([5, 4])]: { grades: {} },
      [obsQuery({ page: "2" }).path]: page([obs(1)], { total: 250 }), [gradesPath([1])]: { grades: {} } });
    const cut = await draw(ObsList, at(["library"], top));
    expect(cut.target.querySelector(".more.cut")?.textContent).toBe("The top 2 of 9, by signal. Show all 9");
    expect(cut.target.querySelector("#show-all")?.getAttribute("href")).toBe("#/library?sort=signal");
    expect(cut.target.querySelector("#ev-seen")?.parentElement?.querySelector(".muted")?.textContent).toBe("the top 2, by signal");
    expect(cut.target.querySelector(".pager")).toBeNull();
    cut.done();
    lib();
    const paged = await draw(ObsList, at(["library"], { page: "2" }));
    expect(paged.target.querySelector(".pager")?.textContent).toBe("Previouspage 2 of 3Next");
    expect(paged.target.querySelector(".pager a")?.getAttribute("href")).toBe("#/library?page=1");
    paged.done();
  });

  it("finds by meaning: one group, and the compacted weeks that match", async () => {
    lib();
    const q = { q: "sync" };
    const roll = { id: 7, period_start: "2026-06-01T00:00:00Z", label: "Sync week", summary: "CRDTs", size: 12, source_mix: { HN: 8, Lobsters: 4 }, mean_signal: 0.5, created_at: NOW };
    answering({ [obsQuery(q).path]: page([obs(9, { new: true })], { total: 1, query: "sync", cutoff: 0.05, closest: 0.2, off_topic_below: 0.3,
      rollups: [roll as never] }), [gradesPath([9])]: { grades: {} } });
    const { target, done } = await draw(ObsList, at(["library"], q));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Best matches", "Compacted weeks"]);
    expect(target.querySelector(".flash.amber")?.textContent).toContain("the closest observation scores 0.20, below 0.30");
    expect(target.querySelector("#watch-this")).toBeNull(); // watches are retired
    expect(target.querySelector("p.quiet-topics")?.textContent).toBe('The 1 observation that best match "sync". Observations more than 0.05 less similar than the closest are left out.');
    const r = target.querySelector('[data-sel="u7"]')!;
    expect(r.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library?q=sync&sel=u7");
    expect(r.querySelector(".c-num")?.textContent).toBe("06-01");
    expect(r.querySelector(".c-meta")?.textContent).toBe("CRDTs · 12 observations");
    expect(r.querySelector(".c-aside")?.textContent).toBe("HN 8, Lobsters 4");
    done();
  });

  it("pins the observation open in the pane when it is not on the page, and says a cluster's name", async () => {
    lib();
    answering({ [obsQuery({ cluster: "3" }).path]: page([obs(2)], { cluster_label: "Sync engines" }), [gradesPath([2])]: { grades: {} },
      "/api/observations/40?k=12": obs(40) });
    const w = at(["library", "o", "40"], {}, "observation");
    const { target, done } = await draw(ObsList, { ...w, r: { ...w.r, q: { cluster: "3" } } });
    expect(target.querySelector("#ev-pin")?.textContent).toBe("Open in the pane");
    expect(target.querySelector("#ev-pin")?.closest("section")?.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library/o/40");
    done();
  });

  it("says when nothing matches the filters", async () => {
    lib();
    answering({ [obsQuery({ kind: "beat" }).path]: page([]) });
    const { target, done } = await draw(ObsList, at(["library"], { kind: "beat" }));
    expect(target.querySelector("p.empty")?.textContent).toBe("Nothing matches.");
    done();
  });
});

describe("Library › an observation", () => {
  // The server's /api/observations/<id> (ObservationPage is generated from its web/types.py)
  const O: ObservationPage = {
    ...obs(5, { title: "Sync engines compared", source_url: "https://example.org/a", source_excerpt: "an excerpt", why_it_matters: "It moves.", tags: ["crdt"],
      override: true, override_reason: "the judge was too strict", signal: 0.2 }),
    grade: null, grade_choices: ["useful"], grade_labels: { useful: "useful" }, source_kind: "hn", similar: [{ id: 8, score: 0.8, weak: false }], topics: [{ id: 1, name: "Topic 1", kind: "user" }],
    call: { id: 77, model: "m-1", prompt_version: "v", cost_usd: null, created_at: NOW, response: "{}", prompt_tokens: 1200, completion_tokens: 300 },
    dive_parent: { id: 4, relation: "link", title: "The parent", summary: "" },
    dive_children: [{ id: 6, title: null, summary: "Observation 6 says something about local-first sync.", signal: 0.2, source_url: null, relation: "discussion" }],
    neighbours: [{ ...obs(8), score: 0.8, weak: false }], synthesis: { text: "They agree.", input_ids: [5, 8] }, topic_similarity: 0.61,
    cited_by: { ideas: [], briefs: [] },
  };
  // the map, as Library › Map read it: #5 is in cluster 3
  const MAPD = { snapshot: { id: 1, created_at: NOW, n: 2, k: 1, quality: {} }, density: [], sources: ["HN"],
    clusters: [{ cluster: 3, label: "Local-first", name: null, keywords: [], size: 2, share: 1, centroid_2d: [0, 0], cross_source: false, max_source_share: 1 }],
    points: { id: [5, 8], x: [0, 1], y: [0, 1], c: [3, 3], s: [0.2, 0.3], t: ["a", "b"], src: [0, 0] } };

  it("draws its head, its sections and its judgment", async () => {
    const L = lib();
    put("/api/map", MAPD);
    answering({ "/api/observations/5?k=12": O });
    const { target, done } = await draw(ObsPane, at(["library", "o", "5"], {}, "observation"), "#/library");
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/library");
    expect(target.querySelector(".pane-in")?.getAttribute("data-title")).toBe("Observation #5");
    // it names the topic its source feeds, and why it is there
    expect(target.querySelector(".dk")?.textContent).toBe(" observation #5 · mild signal · Topic 1");
    expect(target.querySelector("#obs-feeds")?.textContent).toBe(" · feeds Topic 1 (its only topic)");
    expect(target.querySelector("#obs-why-here")?.textContent).toMatch(/^its source feeds Topic 1/);
    expect(target.querySelector(".dt")?.textContent).toBe("Observation 5 says something about local-first sync.");
    expect(target.querySelector(".lede")?.textContent).toBe("Sync engines compared");
    // the cards are not read here: no Cited by until they are (the build loop's snapshot, which
    // stood in for them, left with the factory)
    expect([...target.querySelectorAll(".toc li a")].map((a) => a.textContent)).toEqual(["Summary", "Source", "One step away1", "Neighbourhood", "Nearby1", "Judgment"]);
    expect(target.querySelector(".note.c-amber")?.textContent).toBe("Override. the judge was too strict");
    // the grade is a line under the title, not a section
    expect(target.querySelector('.gh[data-why-id="5"] .grade')?.getAttribute("aria-label")).toBe("Grade this observation");
    expect(target.querySelector("#s-grade")).toBeNull();
    expect(target.querySelector("#s-summary .muted")?.textContent).toBe("Why kept: It moves.");
    expect([...target.querySelectorAll("#s-source dd")].map((x) => x.textContent)).toEqual(["HN · feeds Topic 1 (its only topic)", (target.querySelector("#obs-why-here")?.textContent || ""), "mild signal", "just now", "Local-first"]);
    expect(target.querySelector("#s-source dd a[href='#/library/clusters/3']")).not.toBeNull();
    expect(target.querySelector("#s-source p.muted.mt")?.textContent).toBe("Read one step from another item (link): #4 The parent.");
    expect(target.querySelector("#s-step .c-meta")?.textContent).toBe("#6 discussion");
    expect(target.querySelector("#s-step .c-aside")?.textContent).toBe("linked");
    expect(target.querySelector("#s-hood .small")?.textContent).toBe("Written by a model from this observation and its nearest neighbours; numbers refer to [1] [2].");
    expect(target.querySelector("#s-nearby a.r-title")?.getAttribute("href")).toBe("#/library/o/8");
    expect(target.querySelector("#s-judgment p.mono")?.textContent).toBe("signal = 0.80 × 0.50 × 0.50 = 0.200");
    // the three numbers and the meter; the run's trace (model, tokens, raw response) is Activity's
    expect([...target.querySelectorAll("#s-judgment dl.mt dd")].map((x) => x.textContent)).toEqual(["topic (0.61)"]);
    expect(target.querySelector("#s-judgment details")).toBeNull();
    expect(target.querySelector("#watch-obs")).toBeNull(); // watches are retired
    (target.querySelector("#mute-obs") as HTMLButtonElement).click();
    expect(L.popover).toHaveBeenCalledWith(expect.any(HTMLElement), "Mute HN", [], expect.anything());
    expect([...document.querySelectorAll(".pop.menu button[role=menuitem]")].map((b) => b.textContent)).toEqual(["Mute for 7 days", "Mute for 30 days", "Read less", "Retire"]);
    expect(target.querySelector("#remove-post")).toBeNull();          // not an X post
    done();
  });

  it("removes an X post after a confirm (a deletion request)", async () => {
    const L = lib();
    const dialog = vi.fn();
    Object.assign(L, { dialog, afkDrop: vi.fn() });
    L.api.mockResolvedValue({ ok: true, removed: 1, message: "Removed from the library at your request; the purge record says so." });
    answering({ "/api/observations/5?k=12": { ...O, source_kind: "x", source_url: "https://x.com/i/status/5" } });
    const { target, done } = await draw(ObsPane, at(["library", "o", "5"], {}, "observation"), "#/library/o/5");
    (target.querySelector("#remove-post") as HTMLButtonElement).click();
    expect(dialog).toHaveBeenCalledWith("Remove this post?", [expect.any(HTMLElement)], "Remove", expect.any(Function), "");
    const close = vi.fn();
    dialog.mock.calls[0]![3](document.createElement("button"), close);
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/observations/5/remove", {});
    expect(close).toHaveBeenCalled();
    expect(location.hash).toBe("#/library");
    history.replaceState(null, "", "#/");
    done();
  });

  it("lists the cards that cite it, and Explain without a synthesis", async () => {
    const L = lib();
    void L;
    // The server's cards: #9 cites this observation, #10 another (an older server: no cited_by,
    // so the cards' citations are read)
    const { cited_by: _, ...older } = O;
    void _;
    answering({ "/api/observations/5?k=12": { ...older, synthesis: null, dive_children: [], dive_parent: null },
      "/api/ideas?embedding=ref": [{ number: 9, title: "Card 9", status: "shown", score: 0.2, citations: [{ observation_id: 5 }], topics: [{ id: 1, name: "Local-first" }] },
        { number: 10, title: "Card 10", status: "shown", citations: [{ observation_id: 6 }], topics: [] }] });
    const { target, done } = await draw(ObsPane, at(["library", "o", "5"], {}, "observation"));
    await settle();
    const rows = [...target.querySelectorAll("#s-cited ul.lst.pl li.row")];
    expect(rows.map((r) => [r.querySelector(".c-num")?.textContent, r.querySelector(".r-title")?.textContent, r.querySelector(".c-meta")?.textContent]))
      .toEqual([["#9", "Card 9", "waiting · score 0.200 · Local-first"]]);
    expect(target.querySelector("#s-cited")?.querySelector("h3")?.querySelector(".n")?.textContent).toBe("1");
    expect(target.querySelector("#s-hood .inline button")?.textContent).toBe("Explain this neighbourhood");
    done();
  });

  it("lists what the server says cites it: its cards and its News briefs (CON L2)", async () => {
    lib();
    // #10's citation was compacted out of its JSON; the server's idea_citations still name it
    answering({ "/api/observations/5?k=12": { ...O, synthesis: null, dive_children: [], dive_parent: null, cited_by: { ideas: [10], briefs: [3] } },
      "/api/ideas?embedding=ref": [{ number: 9, title: "Card 9", status: "shown", citations: [{ observation_id: 5 }], topics: [] },
        { number: 10, title: "Card 10", status: "shown", citations: [], topics: [] }] });
    const { target, done } = await draw(ObsPane, at(["library", "o", "5"], {}, "observation"));
    await settle();
    const sec = target.querySelector("#s-cited")!;
    expect([...sec.querySelectorAll("ul.lst.pl li.row .r-title")].map((r) => r.textContent)).toEqual(["Card 10"]);
    expect(sec.querySelector("h3 .n")?.textContent).toBe("2");
    const brief = sec.querySelector("p.small a") as HTMLAnchorElement;
    expect(brief.textContent).toBe("brief #3");
    expect(brief.getAttribute("href")).toContain("news/earlier");
    expect(brief.getAttribute("href")).toContain("sel=f3");
    done();
  });

  it("says when an observation is gone, and with nothing selected", async () => {
    lib();
    answering({});
    const gone = await draw(ObsPane, at(["library", "o", "41"], {}, "observation"));
    await settle();
    expect(gone.target.querySelector("p.empty")?.textContent).toBe("No observation 41. It may have been compacted into a weekly rollup.");
    gone.done();
    lib();
    const none = await draw(ObsPane, where("library"));
    expect(none.target.querySelector(".pane-empty")?.textContent).toBe("Nothing selected.");
    none.done();
  });
});
