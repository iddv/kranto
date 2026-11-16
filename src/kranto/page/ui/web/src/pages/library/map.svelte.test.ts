import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { drop, setFetcher } from "../../lib/reads.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import MapList from "./MapList.svelte";
import MapPane from "./MapPane.svelte";
import { MAP, mapTheme, moveText, sparkLine, type Map, type ObservationPage } from "./map.svelte";

const NOW = new Date().toISOString();
// The server's /api/map (Map is generated from its web/types.py): three points in two clusters
const MAPD: Map = {
  snapshot: { id: 7, created_at: "2026-10-14T23:45:35Z", n: 3, k: 2, quality: {
    silhouette_umap: 0.41, silhouette_native: 0.05, stories: { observations: 3, distinct: 2 },
    structure_null: { reps: 5, null_mean: 0.01, null_sd: 0.002, real: 0.05, z: 20, covariance_null_mean: 0.04, covariance_null_sd: 0.004, covariance_z: 2.5, clustered: true } } },
  density: [], sources: ["HN", "Lobsters"],
  clusters: [{ cluster: 4, label: "Sync engines", name: null, keywords: [], size: 2, share: 0.66, centroid_2d: [0, 0], cross_source: true, max_source_share: 0.5 },
    { cluster: 1, label: "Local models", name: null, keywords: [], size: 1, share: 0.33, centroid_2d: [1, 1], cross_source: false, max_source_share: 1 }],
  points: { id: [10, 11, 12], x: [0, 0.5, 1], y: [0, 0.5, 1], c: [4, 4, 1], s: [0.2, 0.45, 0.31], t: ["CRDT sync for SQLite", "Automerge 3 ships", "Llama on a laptop"], src: [0, 1, 0] },
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; MAP.words = ""; });
/** the old module, stubbed with what the map calls of it; with the server hosting, or without */
const lib = (host = true) => {
  const L = stub();
  if (host) hosted();
  else ui.facts = null;
  return L;
};
const at = (q: Record<string, string> = {}): Where => ({ ...where("library/map"), r: { path: ["library", "map"], q, sel: null } });
const page = (id: number, near: number[]): Partial<ObservationPage> => ({ id, similar: near.map((n) => ({ id: n, score: 0.9, weak: false })),
  neighbours: near.map((n) => ({ id: n, summary: `Neighbour ${n} in a long sentence.`, score: 0.87, weak: false })) as ObservationPage["neighbours"] });

describe("Library › Map", () => {
  it("lists the clusters' legend, then each cluster's points by signal, a point's row selecting it", async () => {
    stub();
    hosted();
    answering({ "/api/map": MAPD });
    const { target, done } = await draw(MapList, at({ p: "11" }));
    expect(target.querySelector(".quiet-topics")?.textContent).toBe("3 observations · 2 clusters · mapped 2026-10-14");
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Clusters", "Sync engines", "Local models"]);
    const legend = target.querySelector("#legend")!.closest("section")!;
    expect(legend.querySelector(".swatch.k1")).not.toBeNull();
    expect(legend.querySelector("li .c-meta")?.textContent).toBe("cross-source");
    expect(legend.querySelector("a.r-title")?.getAttribute("href")).toBe("#/library/map?c=4");
    expect(legend.querySelector(".r-act a")?.getAttribute("href")).toBe("#/library/clusters/4");
    const rows = [...target.querySelector("#pts-4")!.closest("section")!.querySelectorAll("li")];
    expect(rows.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Automerge 3 ships", "CRDT sync for SQLite"]);
    expect(rows[0]!.dataset.go).toBe("#/library/map?p=11");
    expect(rows[0]!.hasAttribute("data-cur")).toBe(true);
    expect(rows[0]!.querySelector(".c-num.hot")?.textContent).toBe("0.45");
    expect(rows[0]!.querySelector(".c-aside")?.textContent).toBe("Lobsters");
    expect(rows[1]!.hasAttribute("data-cur")).toBe(false);
    done();
  });

  it("shows one cluster alone, and counts what the highlight leaves lit", async () => {
    stub();
    hosted();
    answering({ "/api/map": MAPD });
    const { target, done } = await draw(MapList, at({ c: "4" }));
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Clusters", "Sync engines"]);
    expect(target.querySelector("#legend")?.parentElement?.querySelector("a")?.getAttribute("href")).toBe("#/library/map");
    expect(target.querySelector("#legend")!.closest("section")!.querySelector(".c-meta")?.textContent).toBe("shown alone · cross-source");
    const input = target.querySelector("#map-filter") as HTMLInputElement;
    input.value = "sync";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    expect(MAP.words).toBe("sync");
    expect(target.querySelector("#map-count")?.textContent).toBe("1 highlighted");
    done();
  });

  it("before the first map says what it needs, and builds it", async () => {
    const L = stub();
    const hostForm = vi.fn(async () => null), afkDrop = vi.fn();
    Object.assign(L, { hostForm, afkDrop });
    hosted();
    drop("/api/map");
    drop("/api/clusters");
    const asked: string[] = [];
    setFetcher(async (p) => {
      asked.push(p);
      if (p === "/api/clusters") return { snapshot: null, clusters: [], progress: "12 of 30 observations so far." };
      throw new Error("not found: " + p);
    });
    const { target, done } = await draw(MapList, at());
    await settle();
    expect(target.querySelector(".box p")?.textContent).toMatch(/^No map yet\. A map needs at least 30 observations/);
    // the clusters say there is no map: /api/map is never asked for its 404 (QA B20)
    expect(asked).toContain("/api/clusters");
    expect(asked).not.toContain("/api/map");
    expect(target.querySelector(".box p.muted")?.textContent).toBe("12 of 30 observations so far.");
    (target.querySelector(".box button") as HTMLButtonElement).click();
    await settle();
    expect(hostForm).toHaveBeenCalledWith("/run/snapshot");
    expect(afkDrop).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Started building the map. It shows here when it is done.");
    done();
    drop("/api/clusters"); // the next tests read a map
  });

  it("without the server says the library needs it", async () => {
    stub();
    answering({});
    const { target, done } = await draw(MapList, at());
    expect(target.querySelector("[data-title=Library] strong")?.textContent).toBe("The library needs the server. ");
    done();
  });

  it("draws the map in the pane, the selected point and its nearest, and how to read it", async () => {
    lib();
    answering({ "/api/map": MAPD, "/api/observations/10?k=12": page(10, [11, 99]) });
    const { target, done } = await draw(MapPane, at({ p: "10", c: "4" }));
    await settle();
    const svg = target.querySelector(".viz-box svg.viz")!;
    expect(svg.getAttribute("aria-label")).toBe("Map of 3 observations in 2 clusters. The list below the map has the same points.");
    expect([...svg.querySelectorAll("circle.pt")].map((c) => c.getAttribute("class"))).toEqual(["pt k1", "pt k1", "pt k2 dim"]);
    expect(svg.querySelectorAll("line.nb-line").length).toBe(1);
    expect(svg.querySelector("circle.sel")).not.toBeNull();
    expect(target.querySelector(".dk")?.textContent).toBe("map · 2 clusters");
    expect(target.querySelector(".dt")?.textContent).toBe("#10");
    expect(target.querySelector(".acts .mono")?.textContent).toBe("signal 0.20");
    expect(target.querySelector("#s-point .inline")?.textContent).toBe("0.20HN");
    expect(target.querySelector("#s-point p.small a")?.getAttribute("href")).toBe("#/library/o/10");
    const near = [...target.querySelectorAll("#s-point ul.ctx a")].map((a) => a.getAttribute("href"));
    expect(near).toEqual(["#/library/map?p=11&c=4", "#/library/o/99"]);
    expect(target.querySelector("details.fold")?.id).toBe("map-how");          // kept open across draws
    expect([...target.querySelectorAll("details .mono")].map((p) => p.textContent)[0]).toBe(
      "Cluster separation (silhouette): 0.410 in the 10-d projection, 0.050 in the original embedding space. Structure-free null (5 column permutations): 0.0100 ± 0.0020 vs 0.0500 real (z = 20).");
    expect(target.textContent).toContain("Stories: 3 observations tell 2 distinct stories");
    // the list's highlight reaches the map
    MAP.words = "automerge";
    await settle();
    expect([...svg.querySelectorAll("circle.pt")].map((c) => c.classList.contains("dim"))).toEqual([true, false, true]);
    // a click on a point selects it
    location.hash = "#/library/map?c=4";
    svg.querySelector("circle[data-id='11']")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(location.hash).toBe("#/library/map?c=4&p=11");
    done();
  });

  it("says Pick a point, No map yet, and Nothing selected without the server", async () => {
    lib();
    answering({ "/api/map": MAPD });
    const one = await draw(MapPane, at());
    expect(one.target.querySelector(".dt")?.textContent).toBe("3 observations");
    expect(one.target.querySelector("#s-point")?.textContent).toBe("Pick a point.");
    one.done();
    lib();
    drop("/api/map");
    answering({});
    const none = await draw(MapPane, at());
    await settle();
    expect(none.target.querySelector(".pane-in p.empty")?.textContent).toBe("No map yet.");
    none.done();
    lib(false);
    const alone = await draw(MapPane, at());
    expect(alone.target.querySelector(".pane-empty")?.textContent).toBe("Nothing selected.");
    alone.done();
  });

  it("names an observation's theme from the map once it is read, its movement and its spark", async () => {
    lib();
    drop("/api/map");
    answering({ "/api/map": MAPD });
    expect(mapTheme(12)).toBeNull();
    await settle();
    expect(mapTheme(12)).toBeNull(); // never a read of its own: what Library › Map read
    const { done } = await draw(MapList, at());
    expect(mapTheme(12)).toEqual({ cluster: 1, label: "Local models" });
    expect(mapTheme(404)).toBeNull();
    done();
    expect(moveText({ movement: null })).toBeNull();
    expect(moveText({ movement: { since: NOW, delta: 0.012, excess: -0.003, points: 3, new_total: 40, new_in_cluster: 9, expected_new: 4.25, burst: null, entered_burst: false, p_value: 0.01, q_value: 0.0123456 } }))
      .toBe("+1.20 pts, excess -0.30 · new 9/40 vs 4.3 expected, q 0.0123");
    expect(sparkLine([{ at: NOW, share: 0.1, size: 1 }])).toBeNull();
    expect(sparkLine([{ at: NOW, share: 0.1, size: 1 }, { at: NOW, share: null, size: 2 }, { at: NOW, share: 0.2, size: 3 }]))
      .toEqual({ points: "0.0,12.0 50.0,22.0 100.0,2.0", label: "share over 3 maps: 10.0% to 20.0%" });
  });
});
