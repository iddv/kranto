import { describe, expect, it } from "vitest";
import { href, matchRoute, NODES, parse, selCode, selPath, SELS } from "./router";

describe("the routes", () => {
  it("parses a hash into a path, filters and a selection", () => {
    expect(parse("#/topics/2/evidence?signal=strong&sel=o665")).toEqual({
      path: ["topics", "2", "evidence"], q: { signal: "strong" }, sel: "o665",
    });
    expect(parse("")).toEqual({ path: [], q: {}, sel: null });
    expect(parse("#/ideas/card%3A6").path).toEqual(["ideas", "card:6"]);
  });

  it("writes a route back, dropping empty filters", () => {
    expect(href("ideas", { status: "waiting", q: "", n: 0 })).toBe("#/ideas?status=waiting");
    expect(href("needs")).toBe("#/needs");
  });

  it("matches the first entry, fills the parameters and names the object's home list", () => {
    const b = matchRoute(["library", "o", "665"]);
    expect(b).toMatchObject({ node: "library", object: "observation", list: ["library"], id: "665", base: ["library", "o", "665"] });
    expect(matchRoute(["topics", "2", "ideas"])).toMatchObject({ node: "topics/2/ideas", list: ["topics", "2", "ideas"], id: "2" });
    expect(matchRoute(["ideas", "new"])).toMatchObject({ redirect: "ideas" }); // before ideas/:id
    expect(matchRoute([])).toMatchObject({ redirect: "home" });
    expect(matchRoute(["overview"])).toMatchObject({ redirect: "home" });
    expect(matchRoute(["builds", "receipts", "logs"])).toMatchObject({ redirect: "home", said: "Builds are not part of Kranto any more." });
    expect(matchRoute(["welcome"])).toMatchObject({ stage: true });
    for (const nope of [["nope"], ["builds", "a", "b", "c", "d", "e"],["library", "o"], ["settings", "x", "y"]]) expect(matchRoute(nope)).toBeNull();
    // Settings › <Feature>: any other one word under settings is a feature's page, after Settings' own
    expect(matchRoute(["settings", "news"])).toMatchObject({ node: "settings/feature", id: "news" });
    expect(matchRoute(["settings", "spend"])).toMatchObject({ node: "settings/spend" });
  });

  it("routes every literal #/ link the pages write (Welcome's Your repositories was Not found)", () => {
    const files = import.meta.glob(["../**/*.svelte", "../**/*.ts", "!../**/*.test.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const dead: string[] = [];
    for (const [f, text] of Object.entries(files)) {
      for (const m of text.matchAll(/["'`]#\/([a-z][a-z0-9/_-]*)/g)) {
        if (m[1]!.endsWith("/")) continue; // a prefix the code completes with an id
        if (!matchRoute(m[1]!.split("/"))) dead.push(`${f}: #/${m[1]}`);
      }
    }
    expect(dead).toEqual([]);
    expect(matchRoute(["welcome", "publishing"])).toMatchObject({ redirect: "welcome" });
    expect(matchRoute(["welcome", "repos"])).toMatchObject({ redirect: "welcome" });
  });

  it("has a sel= key for every object shown away from its home, and back", () => {
    const homes = new Set(NODES.filter((n) => n.object && /:(key|id|n)$/.test(n.route)).map((n) => n.route.replace(/\/[^/]+$/, "")));
    expect(new Set(Object.values(SELS))).toEqual(homes);
    expect(selCode(["library", "o", "665"])).toBe("o665");
    expect(selCode(["ideas", "12"])).toBe("i12");
    expect(selCode(["ideas"])).toBeNull();
    expect(selPath("bplots")).toBeNull(); // builds left
    expect(selPath("o665")).toEqual(["library", "o", "665"]);
    expect(selPath("x1")).toBeNull();
    expect(selPath("b")).toBeNull();
  });
});
