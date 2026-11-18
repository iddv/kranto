import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, stub, where } from "../testing.svelte";
import ObsPane from "./ObsPane.svelte";
import RollupPane from "./RollupPane.svelte";
import RollupsList from "./RollupsList.svelte";
import { obsQuery, rollupsPath, type Rollup, type Rollups } from "./library";

const NOW = new Date().toISOString();
const roll = (id: number, o: Partial<Rollup> = {}): Rollup => ({
  id, period_start: "2026-06-01T00:00:00Z", period_end: "2026-06-08T00:00:00Z", first_at: NOW, last_at: NOW, size: 12, source_mix: { HN: 8, Lobsters: 4, arXiv: 1 },
  platform_mix: {}, topic_mix: {}, mean_signal: 0.3, kind_counts: {}, keywords: ["crdt", "sync"], name: null, summary: "CRDTs everywhere", summary_call_id: null,
  urls: ["https://example.org/a", "ftp://example.org/b"], embedding_model: "e", replaced_count: 12, replaced_fingerprint: "f", run_uuid: null, created_at: NOW,
  label: "Sync week " + id, ...o,
});
// The server's /api/rollups (Rollups is generated from its web/types.py)
const list = (results: Rollup[], o: Partial<Rollups> = {}): Rollups => ({ rollups: 60, replaced: 700, retention_line: "90 days", results, total: 60, offset: 0, ...o });
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const at = (node: string, q: Record<string, string> = {}, sel: string | null = null): Where => ({ ...where(node, sel), r: { path: node.split("/"), q, sel } });
function lib() {
  const L = stub();
  hosted();
  return L;
}

describe("Library › Rollups", () => {
  it("reads 50 a page, or the 100 best matches", () => {
    expect(rollupsPath({ page: "2" })).toBe("/api/rollups?k=50&offset=50");
    expect(rollupsPath({ q: "sync engines" })).toBe("/api/rollups?k=100&q=sync%20engines");
  });

  it("lists the compacted weeks with the search and the pager", async () => {
    const L = lib();
    answering({ [rollupsPath({})]: list([roll(2, { mean_signal: 0.45 }), roll(1)]) });
    const { target, done } = await draw(RollupsList, where("library/rollups"));
    expect(target.querySelector(".wl")?.getAttribute("data-title")).toBe("Rollups");
    expect(target.querySelector(".tb > .tbn.filters > #search")).not.toBeNull();
    expect((target.querySelector("#search") as HTMLInputElement).placeholder).toBe("Search the compacted weeks  ( / )");
    void L;
    expect(target.querySelector("p.quiet-topics")?.textContent).toBe("60 rollups stand in for 700 observations.");
    expect(target.querySelector("p.quiet-topics")?.getAttribute("title")).toBe("Kept for 90 days, then compacted.");
    expect(target.querySelector(".grp h2")?.textContent).toBe("Compacted weeks");
    expect(target.querySelector(".grp .n")?.textContent).toBe("60");
    const r = target.querySelector('[data-sel="u2"]')!;
    expect(r.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library/rollups?sel=u2");
    expect(r.querySelector(".gl")?.className).toBe("gl c-blue");
    expect(r.querySelector(".c-aside")?.textContent).toBe("HN 8, Lobsters 4 and 1 more");
    expect(target.querySelector('[data-sel="u1"] .gl')?.getAttribute("title")).toBe("mean signal 0.30");
    expect(target.querySelector(".pager")?.textContent).toBe("page 1 of 2Next");
    done();
  });

  it("pages a search's matches here, and says when none match", async () => {
    lib();
    const many = Array.from({ length: 60 }, (_, i) => roll(i + 1));
    answering({ [rollupsPath({ q: "sync" })]: list(many, { total: undefined }), [rollupsPath({ q: "none" })]: list([], { total: undefined }) });
    const two = await draw(RollupsList, at("library/rollups", { q: "sync", page: "2" }));
    expect(two.target.querySelector(".grp h2")?.textContent).toBe("Matching rollups");
    expect(two.target.querySelectorAll("li.row").length).toBe(10);
    expect(two.target.querySelector("li.row a")?.getAttribute("href")).toBe("#/library/rollups?q=sync&page=2&sel=u51");
    two.done();
    lib();
    const none = await draw(RollupsList, at("library/rollups", { q: "none" }));
    expect(none.target.querySelector("p.empty")?.textContent).toBe('No rollup matches "none".');
    none.done();
  });

  it("without the server says the library needs it", async () => {
    stub();
    answering({});
    const { target, done } = await draw(RollupsList, where("library/rollups"));
    expect(target.querySelector("[data-title=Library] strong")?.textContent).toBe("The library needs Kranto's server, which is not answering. ");
    done();
  });

  it("opens a week from the list it was read in: its facts and its web links", async () => {
    lib();
    answering({ [rollupsPath({})]: list([roll(2, { score: 0.71 })]) });
    const { target, done } = await draw(RollupPane, where("library/rollups", "u2"), "#/library/rollups");
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/library/rollups");
    expect(target.querySelector(".dk")?.textContent).toBe(" rollup · week of 2026-06-01");
    expect(target.querySelector(".dt")?.textContent).toBe("Sync week 2");
    expect(target.querySelector(".lede")?.textContent).toBe("CRDTs everywhere");
    expect(target.querySelector(".acts .mono")?.textContent).toBe("signal 0.30");
    expect([...target.querySelectorAll("#s-facts dd")].map((x) => x.textContent)).toEqual(["2026-06-01", "12", "HN 8, Lobsters 4, arXiv 1", "crdt, sync", "0.71", "just now"]);
    expect([...target.querySelectorAll("#s-links a")].map((a) => a.getAttribute("href"))).toEqual(["https://example.org/a"]);
    expect(target.querySelector("#s-links h3 .n")?.textContent).toBe("1");
    done();
  });

  it("opens a search's compacted week from Observations, and says when it is gone", async () => {
    lib();
    const d = { total: 0, offset: 0, cluster_label: null, seen_at: null, marker: "", since: null, new_total: 0, results: [], query: "sync", rollups: [roll(7)] };
    answering({ [obsQuery({ q: "sync" }).path]: d, [rollupsPath({})]: list([]) });
    const found = await draw(ObsPane, at("library", { q: "sync" }, "u7"));
    expect(found.target.querySelector(".dt")?.textContent).toBe("Sync week 7");
    found.done();
    lib();
    const gone = await draw(RollupPane, where("library/rollups", "u9"));
    expect(gone.target.querySelector(".pane-empty")?.textContent).toBe("This rollup is not on the list any more. Search the compacted weeks again.");
    gone.done();
    lib();
    const none = await draw(RollupPane, where("library/rollups"));
    expect(none.target.querySelector(".pane-empty")?.textContent).toBe("Nothing selected.");
    none.done();
  });
});
