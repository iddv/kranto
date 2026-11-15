// Every address that redirects (lib/nodes.json), Settings' aside (settingsRedirects.test.ts): where
// it lands, and what a page that left says where it lands. Builds, projects and
// repositories left with the factory: their old bookmarks land on the home, a topic's builds on Ideas,
// each with one sentence. A new redirect route fails this test until it has its row.
import { afterEach, describe, expect, it } from "vitest";
import { matchRoute, NODES } from "../router";
import { TOAST } from "../../ui/toast.svelte";
import { landOf, render } from "./route";
import { frame, tick, unframe } from "./testing";

afterEach(unframe);

const BUILDS = "Builds are not part of Kranto any more.";
const PROJECTS = "Projects are not part of Kranto any more.";
const REPOS = "Repositories are not part of Kranto any more.";
const SAID = new Set([BUILDS, PROJECTS, REPOS]);

/** every redirect route but Settings' → [where nodes.json sends it, the sentence it says or null] */
const TABLE: Record<string, [string, string | null]> = {
  "": ["home", null],
  "today": ["needs", null],
  "overview": ["home", null],
  "chat": ["home", null],
  "chat/new": ["home", null],
  "chat/:id": ["home", null],
  "cubs": ["post", null],
  "cubs/tickets": ["post", null],
  "cubs/approvals": ["post", null],
  // what left the product (A2: Invest, the radar, the browser pages), without their selection
  "invest": ["home", null],
  "cub/invest": ["home", null],
  "cub/radar": ["home", null],
  "cub/invest/o/:oid": ["home", null],
  "cub/radar/o/:oid": ["home", null],
  "watch/sources/browser": ["watch/sources", null],
  "watch/watches": ["watch", null],
  "library/watches": ["watch", null],
  "library/watches/new": ["watch", null],
  "ideas/new": ["ideas", null],
  "ideas/editor": ["ideas", null],
  "welcome/building": ["welcome", null],
  "welcome/publishing": ["welcome", null],
  "welcome/repos": ["welcome", null],
  // what left with the factory
  "build": ["home", BUILDS],
  "build/projects": ["home", PROJECTS],
  "build/repos": ["home", REPOS],
  "projects": ["home", PROJECTS],
  "projects/:id": ["home", PROJECTS],
  "projects/:id/:section": ["home", PROJECTS],
  "builds": ["home", BUILDS],
  "builds/:key": ["home", BUILDS],
  "builds/:key/trace": ["home", BUILDS],
  "builds/:key/compare": ["home", BUILDS],
  "builds/:key/trace/:n": ["home", BUILDS],
  "builds/:key/:section": ["home", BUILDS],
  "builds/:key/build/:run": ["home", BUILDS],
  "builds/:key/build/:run/logs": ["home", BUILDS],
  "loop/:id/trace": ["home", BUILDS],
  "topics/:id/builds": ["ideas", BUILDS],
};
const fill = (route: string): string =>
  route.replace(":key", "plots").replace(":oid", "5").replace(":id", "1").replace(":section", "logs").replace(":n", "2").replace(":run", "3");

describe("every redirect lands where nodes.json says", () => {
  it("has a row for every redirect route of nodes.json outside Settings", () => {
    const routes = NODES.filter((n) => n.redirect && n.route !== "settings" && !n.route.startsWith("settings/")).map((n) => n.route);
    expect(routes.filter((r) => !(r in TABLE))).toEqual([]);
    expect(Object.keys(TABLE).filter((r) => !routes.includes(r))).toEqual([]);
  });

  it("sends each where the table says, and only a page that left says so, in one of three sentences", () => {
    for (const [route, [to, said]] of Object.entries(TABLE)) {
      const m = matchRoute(route ? fill(route).split("/") : []);
      expect([route, m?.redirect, m?.said ?? null]).toEqual([route, to, said]);
      if (said) expect(SAID.has(said)).toBe(true);
    }
  });

  it("lands an old build, project or repository bookmark on the home, a topic's builds on Ideas", () => {
    for (const [route, [to, said]] of Object.entries(TABLE)) {
      if (!said) continue;
      expect([route, landOf("#/" + fill(route), false)]).toEqual([route, "#/" + to]);
    }
    expect(landOf("#/builds/plots?sel=x", false)).toBe("#/home?sel=x"); // a selection is kept
  });
});

describe("a page that left, opened by its old address", () => {
  it("lands on the home and says it left", async () => {
    await frame({ hash: "#/needs" });
    render();
    await tick();
    for (const [old, to, said] of [
      ["#/builds/plots/build/3/logs", "#/home", BUILDS],
      ["#/projects/1", "#/home", PROJECTS],
      ["#/build/repos", "#/home", REPOS],
      ["#/topics/1/builds", "#/ideas", BUILDS],
    ] as const) {
      TOAST.text = "";
      history.replaceState(null, "", old);
      render();
      expect([old, location.hash, TOAST.text]).toEqual([old, to, said]);
    }
    TOAST.text = "";
    history.replaceState(null, "", "#/today");
    render();
    expect(location.hash).toBe("#/needs");
    expect(TOAST.text).toBe(""); // a page that moved says nothing
  });
});
