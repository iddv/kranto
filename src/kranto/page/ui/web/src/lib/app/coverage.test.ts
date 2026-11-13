// the coverage matrix, walked (coverage/uxa.json; INVENTORY.md) in the one
// layout (New; Classic was cut in open-source wave 1, and a file that says classic draws New too):
// every old route lands where the row says, every row's route draws a page (not Not found), a page
// row's words are on it, and a sheet row's object opens in the sheet. The cubs installed are in the
// reads, so a cub's page is walked the same way, and the drawer's tree lists them. The words of
// an action inside a sheet are checked in its component by tests/page/test_uxa_coverage.py.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import MATRIX from "../../../coverage/uxa.json";
import "../../pages";
import { onPageLoaded } from "../pages.svelte";
import { parse } from "../router";
import { navTree } from "./chrome";
import { render, routeNow } from "./route";
import { frame, unframe } from "./testing";

interface Row { id: string; inv: string; what: string; kind: string; at: string; old?: string; find?: string[]; object?: string; fate: string }
const ROWS = (MATRIX as { rows: Row[] }).rows;
const LAYOUTS = ["new", "classic"] as const; // the stored value; both draw New
const SHELL = { pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };
const TODAY = { since: null, seen_at: null, new_kept: 0, topics: [{ id: 1, name: "Clinics", status: "active", kind: "user", ref: null, new_kept: 2, top: [], proposed: 0, proposed_ticked: [], proposed_items_per_day: 0 }],
  messages: [], rising: [], sources_failing: [], ingest: null };
const TOPIC = { id: 1, name: "Clinics", description: "care", status: "active", sources: 1, proposed: 0, observations: 3, themes: 0, rising: 0, kept_per_day: 1, items_per_day: 2,
  themes_list: [], rising_now: [], source_rows: [], snapshot: null, progress: "", tokens_month: null };
const TOPICS = { topics: [{ ...TOPIC, kind: "user", ref: null, created_at: "2026-10-01", spend_month_usd: 0 }], broad: [], progress: "", every_hours: 6, theme_min_share: 0.5,
  all: { observations: 3, sources: 1, themes: 0, items_per_day: 2, map: null } };
// the cubs the server lists: one of Kranto's own (Digest), and one of the owner's installed later (no work by its author)
const cub = (id: string, title: string, trust: string, open: number) => ({ id, title, says: `${title} says`, version: "1.0.0", trust, enabled: true, mode: "dry run", tickets_open: open,
  manifest: { ui: { nav: [], cards: {} } } });
const FEATURES = { api: "kranto-mod/1", reads: [], request_kinds: [], features: [cub("digest", "Digest", "first-party", 0), cub("toot", "Toot the pick", "owner", 1)] };
const READS = { "/api/topics": TOPICS, "/api/today": TODAY, "/api/topics/1": TOPIC, "/api/topics?kind=project": { topics: [] }, "/api/features": FEATURES };

/** a hash as its parts: the path, and the filters with the selection, in any order */
const norm = (h: string) => {
  const r = parse(h.startsWith("#") ? h : "#/" + h);
  return { path: r.path.join("/"), q: { ...r.q, ...(r.sel ? { sel: r.sel } : {}) } };
};
async function open(hash: string): Promise<void> {
  history.replaceState(null, "", hash);
  render();
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 5));
  render();
  for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 5));
  // a page's first open loads its part; on a busy machine that outlasts the waits above
  // (the page's part stands alone in its pane until it arrives; the head may be drawn above it)
  for (let i = 0; i < 100 && [...document.querySelectorAll("#rows > p.empty, #dscroll > p.empty")].some((b) => b.textContent === "Loading…"); i++) {
    await new Promise((r) => setTimeout(r, 20));
    render();
  }
}

describe("UXA's coverage matrix", () => {
  it("names every part of the inventory, each row once", () => {
    const ids = ROWS.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const inv of ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2", "B3", "B4", "B5", "B6", "C", "D", "E", "F"]) expect(ROWS.some((r) => r.inv === inv), inv).toBe(true);
    // what proposed to drop the owner has decided: the bulk bar and its keys removed;
    // D-4's tree is the drawer now (kept)
    expect(ROWS.filter((r) => r.fate === "kept-not-dropped").map((r) => r.id)).toEqual([]);
    expect(ROWS.filter((r) => r.fate === "removed" && ["B3-bulk", "D-ticks"].includes(r.id)).length).toBe(2);
  });
});

for (const layout of LAYOUTS) {
  describe(`UXA's coverage matrix in the ${layout} layout`, () => {
    beforeAll(async () => {
      localStorage.removeItem("kranto.watch.topic"); // #/topics lands on Watch's Topics until a topic is opened (WT)
      await frame({ hash: "#/needs", reads: { ...READS, "/api/shell": { ...SHELL, layout } } });
      onPageLoaded(() => { if (typeof document !== "undefined" && document.getElementById("rows")) render(); }); // a part that arrives after the frame is gone draws nothing
      await open("#/needs"); // the shell's read has arrived: the layout is drawn
      expect(document.body.classList.contains("classic")).toBe(false);
    });
    afterAll(unframe);

    for (const r of ROWS.filter((x) => x.old)) {
      it(`${r.id}: #/${r.old} lands on #/${r.at}`, async () => {
        await open("#/" + r.old);
        expect(norm(location.hash)).toEqual(norm(r.at));
      });
    }

    for (const r of ROWS) {
      it(`${r.id}: #/${r.at} draws (${r.what})`, async () => {
        await open("#/" + r.at);
        expect(routeNow()?.missing, r.at).toBe(false);
        const text = (document.getElementById("rows")!.textContent || "") + (document.getElementById("dscroll")!.textContent || "");
        expect(text).not.toContain("Not found");
        for (const w of r.find || []) expect(text, `${r.id}: "${w}"`).toContain(w);
        // one head a page: the shell's, never a page's own beside it
        expect(document.querySelectorAll("#page-head").length, `${r.id}: one #page-head`).toBeLessThanOrEqual(1);
        if (/^(watch|ideas|build|news|needs|activity|settings)(\/|$)/.test(r.at) && r.kind === "page") {
          expect(document.querySelectorAll("#rows #page-head").length, `${r.id}: the head`).toBe(1);
          expect(document.querySelectorAll("#rows .wl > .lh").length, `${r.id}: no title of the page's own`).toBe(0);
        }
        if (r.kind === "sheet") {
          expect(routeNow()?.object, r.id).toBe(r.object);
          expect(document.getElementById("dscroll")!.childElementCount, `${r.id}: the object draws`).toBeGreaterThan(0);
        }
      });
    }

    if (layout === "new") {
      it("lists every cub that is on under Cubs, with the tickets waiting, so a cub installed later needs no work", async () => {
        await open("#/needs");
        const t = navTree(parse());
        expect(t.rows.find((x) => x.head === "Cubs")).toMatchObject({ to: "cubs", n: 1 });
        expect(t.rows.filter((x) => x.to.startsWith("cub/")).map((x) => x.w)).toEqual(["Digest", "Toot the pick"]);
      });
    }
  });
}
