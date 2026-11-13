// Settings › System › Your grades (#/settings/grades): what the owner's grades changed, read
// from the server's /api/grades/summary: ratings steer gathering, and the page says how.
import { afterEach, describe, expect, it } from "vitest";
import type { GradesSummary } from "../../api/afk.gen";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, stub, where } from "../testing.svelte";
import GradesList from "./GradesList.svelte";
import GradesPane from "./GradesPane.svelte";
import { GRADES_API } from "./grades";

const D: GradesSummary = {
  window_days: 90,
  counts: { grades: 14, cards: 6, evidence: 8, cleared: 4 },
  ideas: { shown: 143, moved: 39, graded: 6, still: 98, top: [{ id: 109, title: "A loop-governance product", taste: 1.824, line: "ranked up: like 2 cards you upvoted", position: 4 }] },
  themes: [
    { lineage_id: "L5", name: "agent memory failures and benchmarks", taste: 2.391, skip: false, line: "ranked up: like 2 cards you upvoted", parts: [] },
    { lineage_id: "L0", name: "Model Context Protocol server projects", taste: -1.421, skip: true, line: "ranked down: like 2 cards you downvoted", parts: [] }],
  sources: { window_days: 90, remove_after: 3, recommended: [], closest: { id: 4, label: "HN search: local-first", down: 1, up: 2 }, kept: [{ id: 7, label: "HN front page", at: "2026-10-28T08:00:00Z", down: 4, up: 1 }] },
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.area = ""; ui.facts = null; });

const titles = (t: HTMLElement) => [...t.querySelectorAll(".grp h2")].map((h) => h.textContent);
const meta = (t: HTMLElement, sel: string) => t.querySelector(`[data-sel="${sel}"] .c-meta`)?.textContent;
const foot = (t: HTMLElement, g: string) => t.querySelector(`[aria-labelledby="${g}"] .more`)?.textContent;

describe("Settings › System › Your grades", () => {
  it("without the server says it needs the server", async () => {
    stub();
    answering({});
    const { target, done } = await draw(GradesList, where("settings/grades"));
    expect(target.querySelector(".box strong")?.textContent).toBe("Your grades need the server. ");
    expect(titles(target)).toEqual([]);
    done();
  });

  it("says what the grades changed in four sections, and nothing of the factory's", async () => {
    stub();
    hosted();
    answering({ [GRADES_API]: D });
    const { target, done } = await draw(GradesList, where("settings/grades"));
    expect(titles(target)).toEqual(["Your grades", "Ideas", "The next ideas run", "Sources"]);
    expect(target.querySelector("#grades-counts")?.textContent).toBe("14 in 90 days: 6 on cards, 8 on evidence; 4 cleared.");
    expect(target.querySelector("#grades-ideas")?.textContent).toBe("39 cards rank higher or lower because of them; 98 are where they would be anyway.");
    expect(target.querySelector('[data-sel="gidea:109"] a.r-title')?.getAttribute("href")).toBe("#/ideas/109");
    expect(meta(target, "gidea:109")).toBe("#109 · ranked up: like 2 cards you upvoted · now 4 of 143");
    expect(meta(target, "gtheme:L0")).toContain("skipped this run: ranked down: like 2 cards you downvoted");
    expect(target.querySelector("#grades-sources")?.textContent).toContain("None recommended for removal. Closest: HN search: local-first, 1 of 3 graded posts not useful.");
    expect(meta(target, "gkept:7")).toContain("kept on 28 Oct, after 4 of 5 graded posts were not useful");
    expect(target.querySelector('[data-sel="egrades"]')).not.toBeNull();
    expect(target.textContent).not.toMatch(/[Ll]esson|Maintenance|Build tools|capabilit/);
    done();
  });

  it("keeps the next run's themes short: the first five and every skipped one, in the run's order", async () => {
    stub();
    hosted();
    const th = (n: number, skip: boolean) => ({ lineage_id: "T" + n, name: "theme " + n, taste: skip ? -1 : 2 - n / 10, skip, line: "", parts: [] });
    answering({ [GRADES_API]: { ...D, themes: [...Array.from({ length: 9 }, (_, n) => th(n, false)), th(9, true), th(10, true)] } });
    const { target, done } = await draw(GradesList, where("settings/grades"));
    const rows = [...target.querySelectorAll('[data-sel^="gtheme:"]')].map((r) => r.getAttribute("data-sel"));
    expect(rows).toEqual(["gtheme:T0", "gtheme:T1", "gtheme:T2", "gtheme:T3", "gtheme:T4", "gtheme:T9", "gtheme:T10"]);
    expect(foot(target, "g-themes")).toContain("(the first 5 and every one it skips; 4 more after them)");
    done();
  });

  it("says when nothing was graded", async () => {
    stub();
    hosted();
    answering({ [GRADES_API]: { ...D, counts: { grades: 0, cards: 0, evidence: 0, cleared: 0 }, ideas: { shown: 10, moved: 0, graded: 0, still: 10, top: [] }, themes: [],
      sources: { ...D.sources, closest: null, kept: [] } } });
    const { target, done } = await draw(GradesList, where("settings/grades"));
    expect(target.querySelector("#grades-counts")?.textContent).toBe("None in 90 days. A ▲ or ▼ on a card or a piece of evidence is a grade.");
    expect(target.querySelector("#grades-ideas")?.textContent).toBe("No card has moved yet: an upvote lifts the cards like it, a downvote sinks them.");
    expect(foot(target, "g-themes")).toBe("Your grades reach no theme of the latest map: the next ideas run cards in its usual order.");
    done();
  });

  it("explains how grades are used, and without the server says so", async () => {
    stub();
    hosted();
    const a = await draw(GradesPane, where("settings/grades"));
    expect(a.target.querySelector(".dt")?.textContent).toBe("How your grades are used");
    expect(a.target.querySelector("#s-cards")?.textContent).toContain("No model decides any of it");
    a.done();
    ui.facts = null;
    stub();
    const b = await draw(GradesPane, where("settings/grades"));
    expect(b.target.querySelector(".pane-empty")?.textContent).toBe("Your grades need the server, which is not hosting this page.");
    b.done();
  });
});
