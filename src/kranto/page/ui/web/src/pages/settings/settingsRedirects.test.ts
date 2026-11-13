// Settings' seven pages: every Settings address in lib/nodes.json has a row
// here, and each lands where the table says, with the cub shop off (a fresh install): on one of
// the seven pages, the Overview, Advanced's Prompts, a feature's
// own page, or Watch (Sources moved there before). A new Settings route fails this test until it
// has its row.
import { afterEach, describe, expect, it } from "vitest";
import { NODES, parse } from "../../lib/router";
import { landOf, render } from "../../lib/app/route";
import { frame, hostStatus, tick, unframe } from "../../lib/app/testing";
import { DOORS_PAGES } from "./doorpages";

afterEach(unframe);
const SHELL = { layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };

/** every Settings address of today's nodes.json, with ":id"-like parts filled in → where it lands */
const TABLE: Record<string, string> = {
  "settings": "settings",
  "settings/watching": "settings/watching",
  "settings/posting": "settings/posting",
  "settings/assistant": "settings/assistant",
  "settings/spend": "settings/spend",
  "settings/privacy": "settings/privacy",
  "settings/system": "settings/system",
  "settings/appearance": "settings/appearance",
  "settings/prompts": "settings/prompts",
  // Accounts was split: the sites are Watching's, the rest Posting's
  "settings/accounts": "settings/posting",
  // How you write: its own page under Posting
  "settings/posting/voice": "settings/posting/voice",
  "settings/connections": "settings/watching",
  "settings/connections/:key": "settings/watching",
  "settings/keys": "settings/watching",
  "settings/models": "settings/watching",
  // the pages of builds, which left with the factory: the Overview
  "settings/building": "settings",
  "settings/publishing": "settings",
  "settings/tools": "settings",
  "settings/rules": "settings",
  "settings/mcp": "settings",
  "settings/capabilities": "settings",
  "settings/plugins": "settings",
  "settings/maintenance": "settings",
  "settings/github": "settings",
  "settings/projects": "settings",
  // the home is not arranged
  "settings/home": "settings",
  "settings/updates": "settings/system",
  "settings/health": "settings/system",
  // Your grades (System's group) has its own address; Learning's lands there
  "settings/grades": "settings/grades",
  "settings/learning": "settings/grades",
  "settings/access": "settings/privacy",
  // what left the product (the browser pages, Invest, the radar): the Overview
  "settings/browser": "settings",
  "settings/sources/browser": "settings",
  "settings/invest": "settings",
  "settings/radar": "settings",
  // Sources is Watch's
  "settings/sources": "watch/sources",
  "settings/sources/:id": "watch/sources",
  "settings/topics": "watch/sources",
  "settings/sources/new": "settings/sources/new",
  "settings/watches": "watch",
  "settings/watches/new": "watch",
  // a feature's or a posting cub's own page (listed under Posting)
  "settings/:fid": "settings/:fid",
};
const fill = (route: string): string => route.replace(":key", "github").replace(":id", "4").replace(":fid", "newsletter");

describe("every Settings address lands on its page", () => {
  it("has a row for every Settings route of nodes.json", () => {
    const routes = NODES.map((n) => n.route).filter((r) => r === "settings" || r.startsWith("settings/"));
    expect(routes.filter((r) => !(r in TABLE))).toEqual([]);
    expect(Object.keys(TABLE).filter((r) => !routes.includes(r))).toEqual([]);
  });

  it("lands each where the table says, on a fresh install (the shop off)", async () => {
    await frame({ hash: "#/settings", host: hostStatus({ cubs_developer: false }),
      reads: { "/api/shell": SHELL, "/api/today": { since: null, ingest: null, topics: [], messages: [], rising: [] } } });
    render();
    await tick();
    const seven = new Set(["settings", ...DOORS_PAGES.map((k) => "settings/" + k)]);
    for (const [route, to] of Object.entries(TABLE)) {
      const landed = parse(landOf("#/" + fill(route))).path.join("/");
      expect([route, landed]).toEqual([route, fill(to)]);
    }
    // the owner's line: "my old bookmark to Settings › Accounts lands on Posting"
    expect(landOf("#/settings/accounts")).toBe("#/settings/posting");
    expect(seven.size).toBe(8);
    // the Settings of what left lands on the Overview, never on "There is no feature
    // or cub called cubs"; and the shop's own tabs of Cubs land on Post
    for (const gone of ["cubs", "invest", "radar", "layout"]) expect(landOf("#/settings/" + gone), gone).toBe("#/settings");
    expect(landOf("#/settings/newsletter")).toBe("#/settings/newsletter");
    for (const tab of ["available", "made"]) expect(landOf("#/cubs/" + tab), tab).toBe("#/post");
    // Invest, the radar and the browser pages left: their old addresses land on a page that is,
    // without the selection, which named one of their objects
    expect(landOf("#/invest")).toBe("#/home");
    expect(landOf("#/cub/invest?sel=o5")).toBe("#/home");
    expect(landOf("#/settings/browser?sel=epair")).toBe("#/settings");
    expect(landOf("#/cub/radar")).toBe("#/home");
    expect(landOf("#/watch/sources/browser")).toBe("#/watch/sources");
  });
});
