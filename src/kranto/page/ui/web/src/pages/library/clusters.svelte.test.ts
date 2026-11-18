import { afterEach, describe, expect, it, vi } from "vitest";
import type { ArchiveTheme, Cluster, Clusters, Observations } from "../../api/afk.gen";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { closeDialog, dlg } from "../../ui/dialog.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import ClustersList from "./ClustersList.svelte";
import ObsList from "./ObsList.svelte";
import ThemePane from "./ThemePane.svelte";
import { obsQuery } from "./library";

const NOW = new Date().toISOString();
const traj = [{ at: "2026-10-01T00:00:00Z", share: 0.1, size: 10 }, { at: "2026-10-08T00:00:00Z", share: 0.12, size: 12 }];
// The server's /api/clusters (Cluster is generated from its web/types.py)
const cl = (cluster: number, o: Partial<Cluster> = {}): Cluster => ({
  snapshot_id: 7, cluster, lineage_id: "lin" + cluster, size: 40, share: 0.118, stories: 38, centroid_2d: [0, 0], keywords: ["crdt", "sync"], name: null, name_call_id: null,
  label: `Theme ${cluster}`, source_mix: { HN: 20, Lobsters: 18 }, topic_mix: { "AI tooling": 3, "Local-first": 30 }, origin_mix: {}, max_source_share: 0.63, max_origin_share: null,
  cross_source: false, representatives: [], trajectory: traj, movement: null, rising: false, synthesis: null, grade: null, examples: [], ...o,
});
const MV = { since: "2026-10-08T00:00:00Z", delta: 0.02, excess: null, points: 2, new_total: null, new_in_cluster: 10, expected_new: null, burst: null, entered_burst: false, p_value: null, q_value: null };
const D: Clusters = { snapshot: { id: 7, created_at: "2026-10-14T23:45:35Z", n: 300, k: 2 }, clusters: [cl(12, { rising: true, movement: MV, cross_source: true }), cl(3, { movement: { ...MV, burst: 1, new_in_cluster: null } })] };
const theme = (lineage_id: string, o: Partial<ArchiveTheme> = {}): ArchiveTheme => ({
  lineage_id, name: null, named: false, names: [], name_count: 0, keywords: ["nas", "mirror"], alive: false, size: 9, first_at: "2026-04-01T00:00:00Z", last_at: "2026-06-30T00:00:00Z",
  epochs: 3, members: 0, trajectory: [], dispatches: [], bundle: "b", ...o,
});
const ARCHIVE = { archive: "parallax", count: 3, themes: [theme("L1", { name: "The server storage", alive: true, members: 4, epochs: 12 }), theme("L2", { epochs: 9 }), theme("L3")] };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const at = (path: string[], q: Record<string, string> = {}, object: string | null = null): Where =>
  ({ ...where("library/clusters"), r: { path, q, sel: null }, object, obj: object ? path : null, id: object ? path[2] ?? null : null });

/** the old module, stubbed with what Clusters calls of it */
function lib() {
  const L = stub();
  hosted();
  return L;
}
/** Watch this theme's popover: its question as drawn */

describe("Library › Clusters", () => {
  it("lists the themes with their state, movement and spark, no grade, then the archive's", async () => {
    const L = lib();
    answering({ "/api/clusters": D, "/api/archive/themes": ARCHIVE });
    const { target, done } = await draw(ClustersList, at(["library", "clusters"]));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Themes", "Parallax themes"]);
    expect(target.querySelector("#cl")?.parentElement?.querySelector(".muted")?.textContent).toBe("the map of 2026-10-14");
    const [a, b] = [...target.querySelector("#cl")!.closest("section")!.querySelectorAll("li")];
    expect(a!.dataset.sel).toBe("c12");
    expect(a!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Rising");
    expect(a!.querySelector(".c-num")?.textContent).toBe("38");
    expect(a!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library/clusters/12");
    expect(a!.querySelector(".c-meta")?.textContent).toBe("rising · cross-source · 11.8% of the map · +2.00 pts");
    expect(a!.querySelector(".c-aside svg.spark")?.getAttribute("aria-label")).toBe("share over 2 maps: 10.0% to 12.0%");
    expect(a!.querySelector(".c-age")?.textContent).toBe("+10");
    expect(a!.querySelector(".grade")).toBeNull(); // a theme has no grade: Card it now is its action
    expect(a!.querySelector(".r-act button")).toBeNull(); // watches are retired (WT): no Watch on a theme
    expect(b!.querySelector(".gl")?.getAttribute("aria-label")).toBe("Burst");
    expect(b!.querySelector(".c-age")?.textContent).toBe("");
    // the archive: alive or long-lived only, each listing its members in Observations
    const px = [...target.querySelectorAll("#parallax-themes li")];
    expect(px.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["The server storage", "L2"]);
    expect(px[0]!.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library?theme=L1");
    expect(px[1]!.querySelector("a.r-title")).toBeNull();
    expect(px[0]!.querySelector(".c-meta")?.textContent).toBe("alive · 2026-04-01 to 2026-06-30 · 12 snapshots · nas, mirror");
    expect(target.querySelector("#px")?.parentElement?.querySelector("a")?.getAttribute("href")).toBe("#/library?source=parallax");
    done();
  });

  it("sorts by the select, and says when there is no map yet", async () => {
    lib();
    answering({ "/api/clusters?sort=moving": { ...D, sort: "moving" }, "/api/clusters": { snapshot: null, clusters: [], progress: "Maps start at 30." } });
    const moving = await draw(ClustersList, at(["library", "clusters"], { sort: "moving" }));
    const sel = moving.target.querySelector("select.tb-f") as HTMLSelectElement;
    expect(sel.value).toBe("moving");
    sel.value = "cross";
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    expect(location.hash).toBe("#/library/clusters?sort=cross");
    moving.done();
    lib();
    const none = await draw(ClustersList, at(["library", "clusters"]));
    expect(none.target.querySelector("p.empty")?.textContent).toBe("No map yet, so no clusters. Maps start at 30.");
    none.done();
  });

  it("without the server says the library needs it", async () => {
    stub();
    answering({});
    const { target, done } = await draw(ClustersList, at(["library", "clusters"]));
    expect(target.querySelector("[data-title=Library] strong")?.textContent).toBe("The library needs Kranto's server, which is not answering. ");
    done();
  });

  it("draws a theme in the pane: its head, members, movement and mix, no grade", async () => {
    const L = lib();
    const members: Observations = { total: 1, offset: 0, cluster_label: "Theme 12", seen_at: null, marker: "", since: null, new_total: 0, results: [{
      id: 5, kind: "beat", title: null, summary: "A member of the theme, at length.", why_it_matters: "", content_quality: 1, durability: 1, opportunity: 0.5, signal: 0.5, override: false,
      override_reason: null, tags: [], source_url: null, source_excerpt: null, item_published_at: null, source_id: null, source_label: null, admitted_by: null, created_at: NOW,
      llm_call_id: null, prompt_version: null, grade: null }] };
    answering({ "/api/clusters": { ...D, clusters: [cl(12, { movement: MV, synthesis: { text: "They converge.", input_ids: [5, 6] } })] }, "/api/observations?cluster=12&sort=signal&limit=20": members });
    const { target, done } = await draw(ThemePane, at(["library", "clusters", "12"], {}, "theme"), "#/library/clusters");
    await settle();
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/library/clusters");
    expect(target.querySelector(".dk")?.textContent).toBe(" theme · Local-first · steady");
    expect(target.querySelector(".dt")?.textContent).toBe("Theme 12");
    expect(target.querySelector(".lede")?.textContent).toBe("38 stories, +10 since the last map · 11.8% of the map of 2026-10-14 · one source supplies 63%");
    expect([...target.querySelectorAll(".acts a")].map((a) => a.getAttribute("href"))).toEqual(["#/library/map?c=12", "#/library?cluster=12"]);
    expect(target.querySelector(".acts .mono")?.textContent).toBe("cluster 12 · lin12");
    expect([...target.querySelectorAll(".toc li a")].map((a) => a.textContent)).toEqual(["About", "Highest signal1", "Movement", "Mix"]);
    expect(target.querySelector(".grade, .gh")).toBeNull();
    expect(target.querySelector("#s-about .small")?.textContent).toBe("Numbers refer to [1] [2].");
    expect(target.querySelector("#s-members a.r-title")?.getAttribute("href")).toBe("#/library/o/5");
    expect(target.querySelector("#s-movement svg.spark")?.getAttribute("style")).toBe("width: 100%; height: 40px;");
    expect([...target.querySelectorAll("#s-movement dd")].map((x) => x.textContent)).toEqual(["11.8%", "+2.00 pts", "2"]);
    expect([...target.querySelectorAll("#s-mix dt")].map((x) => x.textContent)).toEqual(["stories", "sources", "topics", "keywords"]);
    expect(target.querySelector("#s-mix dd:nth-of-type(3)")?.textContent).toBe("AI tooling 3, Local-first 30");
    expect([...target.querySelectorAll(".acts button")].map((b) => b.textContent)).not.toContain("Watch"); // retired (WT)
    done();
  });

  it("cards a theme on request, after a confirm that says the cost (CON D-1)", async () => {
    const L = lib();
    answering({ "/api/clusters": { ...D, clusters: [cl(12)] }, "/api/observations?cluster=12&sort=signal&limit=20": { total: 0, offset: 0, cluster_label: null, seen_at: null, marker: "", since: null, new_total: 0, results: [] } });
    const { target, done } = await draw(ThemePane, at(["library", "clusters", "12"], {}, "theme"), "#/library/clusters");
    await settle();
    (target.querySelector("#card-theme") as HTMLButtonElement).click();
    const shown = dlg.now?.props as { title: string; body: Node[]; okText: string; onOk: (ok: HTMLElement, close: () => void) => unknown };
    expect(shown.title).toBe('Card "Theme 12" now?');
    expect(shown.body.map((n) => n.textContent).join(" ")).toContain("one card call and its check, counted under Settings › Spend");
    expect(shown.okText).toBe("Card it");
    expect(L.api).not.toHaveBeenCalledWith("/api/themes/lin12/card", {});
    await shown.onOk(document.createElement("button"), () => closeDialog());
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/themes/lin12/card", {});
    done();
  });

  it("lists a theme's ideas by its lineage, never by its cluster number (snapshot 17's replay)", async () => {
    // live's map of 2026-10-18: cluster 18 is a new robotics lineage, and no card is on it; earlier
    // maps gave the number 18 to other themes, which have cards
    const withHost = () => { stub({ host: { topics: [], sources: [] } }); hosted(); };
    withHost();
    const card = (number: number, lineage_id: string, theme: string) => ({ number, title: `Card ${number}`, status: "shown", score: 0.5, lineage_id,
      theme: { lineage_id, name: theme }, topics: [{ id: 2, name: "AI developer tooling", share: 1 }], citations: [{ observation_id: 1 }], evidence: [] });
    answering({
      "/api/clusters": { ...D, clusters: [cl(18, { lineage_id: "7c19c0d957ce", label: "Weekly robotics newsletter digests", topic_mix: { Robotics: 43, "AI developer tooling": 2 } }),
        cl(5, { lineage_id: "0d6862374eab", label: "AI data center power demands" })] },
      "/api/ideas?embedding=ref": { ideas: [card(116, "687cdcee3043", "LLM inference serving"), card(41, "0d6862374eab", "AI data center power demands"), card(52, "1288bf438642", "Self-hosted the server tools")] },
      "/api/observations?cluster=18&sort=signal&limit=20": { total: 0, offset: 0, results: [] },
      "/api/observations?cluster=5&sort=signal&limit=20": { total: 0, offset: 0, results: [] },
    });
    const robots = await draw(ThemePane, at(["library", "clusters", "18"], {}, "theme"));
    await settle();
    expect([...robots.target.querySelectorAll(".toc li a")].map((a) => a.textContent)).toEqual(["About", "Ideas0", "Highest signal0", "Movement", "Mix"]);
    expect(robots.target.querySelector("#s-ideas p.muted")?.textContent).toBe("No ideas from this theme yet.");
    expect(robots.target.querySelectorAll("#s-ideas li.row").length).toBe(0);
    robots.done();
    withHost();
    const power = await draw(ThemePane, at(["library", "clusters", "5"], {}, "theme"));
    await settle();
    expect([...power.target.querySelectorAll("#s-ideas li.row .r-title")].map((x) => x.textContent)).toEqual(["Card 41"]);
    power.done();
  });

  it("offers Explain without a synthesis, says a missing cluster, and nothing selected", async () => {
    const L = lib();
    answering({ "/api/clusters": { ...D, clusters: [cl(3, { cross_source: true })] }, "/api/observations?cluster=3&sort=signal&limit=20": { total: 0, offset: 0, results: [] } });
    const one = await draw(ThemePane, at(["library", "clusters", "3"], {}, "theme"));
    await settle();
    expect(one.target.querySelector("#s-about .inline button")?.textContent).toBe("Explain this cluster");
    expect(one.target.querySelector(".lede")?.textContent).toBe("38 stories · 11.8% of the map of 2026-10-14 · cross-source");
    expect(one.target.querySelector("#s-movement p.muted")?.textContent).toBe("Only one map so far: no movement yet.");
    one.done();
    lib();
    const gone = await draw(ThemePane, at(["library", "clusters", "40"], {}, "theme"));
    expect(gone.target.querySelector(".pane-empty")?.textContent).toBe("No cluster 40 in the latest map. Cluster numbers change with each map.");
    gone.done();
    lib();
    const none = await draw(ThemePane, where("library/clusters"));
    expect(none.target.querySelector(".pane-empty")?.textContent).toBe("Nothing selected.");
    none.done();
  });

  it("names a Parallax theme on Observations from the archive's themes", async () => {
    Object.assign(stub(), { filterBar: vi.fn(() => []), pageKey: vi.fn(),
      host: () => ({ topics: [], sources: [] }) });
    hosted();
    const q = { theme: "L1" };
    answering({ [obsQuery(q).path]: { total: 0, offset: 0, cluster_label: null, seen_at: null, marker: "", since: null, new_total: 0, results: [] }, "/api/archive/themes": ARCHIVE });
    const { target, done } = await draw(ObsList, { ...where("library"), r: { path: ["library"], q, sel: null } });
    await settle();
    expect(target.querySelector(".flash.blue strong")?.textContent).toBe("The server storage");
    done();
  });
});
