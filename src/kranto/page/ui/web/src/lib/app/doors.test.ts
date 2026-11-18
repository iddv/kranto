// the doors (shell.doors): every old route lands in its door while they
// are on, and nowhere else while they are off; the door's crumb and subnav; the one sheet, open
// only while an object is chosen, closed back to its list.
import { afterEach, describe, expect, it } from "vitest";
import { doorsOf, matchRoute, NODES, parse } from "../router";
import { ui } from "../shell.svelte";
import { chromeFacts } from "./chrome";
import { closeSheet, inlineOf, render, routeNow } from "./route";
import { rowKey } from "./rows";
import { frame, tick, unframe } from "./testing";

afterEach(unframe);
const SHELL = { layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };
const TODAY = { since: null, ingest: null, topics: [{ id: 1, name: "Clinics", new_kept: 4, proposed: 2 }], messages: [], rising: [] };

/** the frame in a layout (or without the server's shell: no doors), the shell's read arrived, then
 * the route drawn */
async function at(hash: string, mode: "new" | "classic" | "alone" = "new"): Promise<string> {
  await frame({ hash, reads: { ...(mode === "alone" ? {} : { "/api/shell": { ...SHELL, layout: mode } }), "/api/today": TODAY, "/api/topics?kind=project": { topics: [] } } });
  render();
  await tick();
  history.replaceState(null, "", hash);
  render();
  await tick();
  return location.hash;
}

describe("where an old route goes in the doors", () => {
  it("fills the target's parameters by name, merges its filters and keeps the selection", () => {
    const n = (route: string) => NODES.find((x) => x.route === route)!;
    expect(doorsOf(n("ideas/:id"), ["ideas", "3"], {}, null)).toEqual({ path: "ideas", q: {}, sel: "i3" });
    expect(doorsOf(n("topics/:id"), ["topics", "7"], {}, null)).toEqual({ path: "watch/topic/7", q: {}, sel: null });
    expect(doorsOf(n("library/o/:id"), ["library", "o", "665"], { topic: "1" }, null)).toEqual({ path: "watch/evidence", q: { topic: "1" }, sel: "o665" });
    expect(doorsOf(n("ideas"), ["ideas"], {}, null)).toBeNull(); // Ideas keeps its address
  });

  it("is a route that draws, for every old route the doors move", () => {
    for (const n of NODES.filter((x) => x.doors)) {
      const path = n.route.split("/").map((p) => (p[0] === ":" ? "5" : p));
      const to = doorsOf(n, path, {}, null)!;
      const m = matchRoute(to.path.split("/").filter(Boolean));
      expect(m, n.route).not.toBeNull();
      expect(m!.redirect || m!.doors, n.route).toBeFalsy();
    }
  });

  it("redirects while the doors are on, the selection kept, and never while they are off", async () => {
    expect(await at("#/today")).toBe("#/needs");
    expect(await at("#/builds/plots")).toBe("#/home"); // builds left: the home
    expect(await at("#/review")).toBe("#/ideas/review");
    expect(await at("#/settings/sources/4")).toBe("#/watch/sources?sel=s4");
    // watches are retired: their old pages open Watch, a topic's its page
    expect(await at("#/settings/watches")).toBe("#/watch");
    expect(await at("#/library/watches/new")).toBe("#/watch");
    expect(await at("#/topics/1/watches")).toBe("#/watch/topic/1");
    expect(await at("#/watch/watches?topic=1")).toBe("#/watch/topic/1");
    // Watch is topic-first: a topic's Sources, Evidence and Map are its pages, and the old
    // ?topic= forms land there; Clusters is the Map, Rollups a group of Evidence
    expect(await at("#/topics/1/evidence")).toBe("#/watch/topic/1/evidence");
    expect(await at("#/topics/1/themes")).toBe("#/watch/topic/1/map");
    expect(await at("#/topics/1/sources")).toBe("#/watch/topic/1/sources");
    expect(await at("#/watch/sources?topic=1&status=proposed")).toBe("#/watch/topic/1/sources?status=proposed");
    expect(await at("#/watch/evidence?topic=1&sel=o9")).toBe("#/watch/topic/1/evidence?sel=o9");
    expect(await at("#/watch/map?topic=1")).toBe("#/watch/topic/1/map");
    // the Watch door (#/topics: g w, the tab bar) lands on the last topic looked at, kept in this
    // browser; with none, Watch's Topics
    localStorage.removeItem("kranto.watch.topic");
    expect(await at("#/topics")).toBe("#/watch");
    await at("#/watch/topic/1/evidence");
    expect(localStorage.getItem("kranto.watch.topic")).toBe("1");
    expect(await at("#/topics")).toBe("#/watch/topic/1");
    localStorage.setItem("kranto.watch.topic", "99"); // a topic that is gone: Watch's Topics
    expect(await at("#/topics")).toBe("#/watch");
    expect(await at("#/topics/1/ideas")).toBe("#/ideas?topic=1");
    expect(await at("#/topics/1/builds")).toBe("#/ideas");
    expect(await at("#/library/clusters/3")).toBe("#/watch/map?sel=c3");
    expect(await at("#/library/rollups")).toBe("#/watch/evidence?group=rollups");
    // the pages that left land on the Overview, the selection kept
    expect(await at("#/settings/maintenance?sel=eadopt:o/r")).toBe("#/settings?sel=eadopt%3Ao%2Fr");
    expect(await at("#/news?sel=f4")).toBe("#/news/earlier?sel=f4");
    // a file that says classic (one layout since open-source wave 1) lands the same
    expect(await at("#/today", "classic")).toBe("#/needs");
    expect(await at("#/topics/1/evidence", "classic")).toBe("#/watch/topic/1/evidence");
    expect(await at("#/settings/home", "classic")).toBe("#/settings"); // the home is not arranged
    // without the server's shell there are no doors: an old address keeps its page
    expect(await at("#/topics/1/evidence", "alone")).toBe("#/topics/1/evidence");
  });
});

describe("the door's head", () => {
  it("is Home › the door, with its subnav and the page drawn current", async () => {
    await at("#/ideas/review");
    const d = chromeFacts(parse())!.door!;
    expect(d.word).toBe("Ideas");
    expect(d.items.map((x) => [x.w, x.on])).toEqual([["Cards", false], ["Review", true]]);
    // Watch is topic-first: Topics, then the topic's own Sources, Evidence and Map
    await at("#/watch/topic/1");
    let w = chromeFacts(parse())!.door!;
    expect(w.items.map((x) => [x.w, x.to, x.on])).toEqual([["Topics", "watch", false], ["Sources", "watch/topic/1/sources", false], ["Evidence", "watch/topic/1/evidence", false], ["Map", "watch/topic/1/map", false]]);
    expect(w.scope).toMatchObject({ topic: "1", name: "Clinics", all: false, page: "", to: "watch/topic/1", on: true });
    await at("#/watch/topic/1/sources");
    expect(chromeFacts(parse())!.door!.items.find((x) => x.on)!.w).toBe("Sources");
    // All topics: a choice, its pages All topics'
    await at("#/watch/evidence");
    w = chromeFacts(parse())!.door!;
    expect(w.items.map((x) => [x.to, x.on])).toEqual([["watch", false], ["watch/sources", false], ["watch/evidence", true], ["watch/map", false]]);
    expect(w.scope).toMatchObject({ topic: null, name: "All topics", all: true, page: "evidence", to: null });
    // Watch's Topics: the subnav is the last topic's (topic 1 was just opened)
    await at("#/watch");
    w = chromeFacts(parse())!.door!;
    expect(w.items.find((x) => x.on)!.w).toBe("Topics");
    expect(w.scope).toMatchObject({ topic: "1", page: null });
    expect(w.items[1]!.to).toBe("watch/topic/1/sources");
    // Add source and Add topic stay pages, drawn under Watch, not Settings
    await at("#/settings/sources/new");
    expect(chromeFacts(parse())!.door!.word).toBe("Watch");
    expect(chromeFacts(parse())!.door!.items.find((x) => x.on)!.w).toBe("Sources");
    await at("#/topics/new");
    expect(chromeFacts(parse())!.door!.items.find((x) => x.on)!.w).toBe("Topics");
    await at("#/home");
    expect(chromeFacts(parse())!.door).toBeNull();
    await at("#/ideas", "classic"); // a file that says classic draws the door's head too
    expect(chromeFacts(parse())!.door!.word).toBe("Ideas");
  });
});

describe("a page's pane in the column", () => {
  it("is the map over Watch's map, Health under System; no other (a topic's head is the page's one head:)", () => {
    expect(inlineOf("watch/map")).toBe("top");
    expect(inlineOf("topics/7")).toBeNull();
    expect(inlineOf("topics/7/evidence")).toBeNull();
    expect(inlineOf("settings/system")).toBe("bottom");
    expect(inlineOf("ideas")).toBeNull();
    expect(inlineOf(null)).toBeNull();
  });
});

describe("the one sheet", () => {
  it("is open only while an object is chosen, a dialog over the column; Close goes back to the list", async () => {
    await at("#/ideas");
    expect(document.body.classList.contains("doors")).toBe(true);
    expect(ui.sheet).toBe(false);
    expect(document.getElementById("dscroll")!.childElementCount).toBe(0); // no pane says "Nothing selected"
    await at("#/ideas?sel=i3");
    expect(ui.sheet).toBe(true);
    expect(routeNow()!.object).toBe("idea");
    closeSheet();
    expect(location.hash).toBe("#/ideas");
  });

  it("takes o from a sheet to the cursor in it: no object has a full page", async () => {
    await at("#/ideas?sel=i3");
    expect(rowKey("open")).toBe(true);
    expect(location.hash).toBe("#/ideas?sel=i3");
    expect(document.activeElement?.id).toBe("dscroll");
  });

  it("opens no settings group by itself", async () => {
    expect(await at("#/settings/prompts")).toBe("#/settings/prompts");
    expect(routeNow()!.r.sel).toBeNull();
    await at("#/settings/prompts", "classic"); // a file that says classic: the same
    expect(routeNow()!.r.sel).toBeNull();
  });
});

describe("one layout (open-source wave 1, D-2: Classic cut)", () => {
  it("draws New for a file that says classic: the sheet, the home at #/", async () => {
    expect(await at("#/ideas?sel=i3", "classic")).toBe("#/ideas?sel=i3");
    expect(document.body.classList.contains("classic")).toBe(false);
    expect(document.body.classList.contains("doors")).toBe(true);
    expect(ui.sheet).toBe(true);
    expect(routeNow()!.object).toBe("idea");
    expect(await at("#/", "classic")).toBe("#/home");
  });
});
