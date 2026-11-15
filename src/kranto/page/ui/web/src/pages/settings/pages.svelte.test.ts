// Settings' seven pages (before them): every old route lands on its new page with its row,
// the Overview finds a setting by its name or key, and a page made of several lists draws their
// groups under one title.
import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { matchRoute, NODES, redirectOf } from "../../lib/router";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, stub, where } from "../testing.svelte";
import { findSettings } from "./overview";
import { SETTINGS_PAGES } from "./pagedefs";
import { ADVANCED_PAGES, doorsPage, DOORS_PAGES } from "./doorpages";
import WatchingList from "./WatchingList.svelte";
import { SETUP_API } from "./keys.svelte";
import { AFK_MODELS } from "./models.svelte";

const go = (path: string, sel: string | null = null) => {
  const m = matchRoute(path.split("/"));
  return m && m.redirect ? redirectOf(m, sel) : null;
};
afterEach(() => { ui.facts = null; });

describe("Settings' pages", () => {
  it("are seven, then Advanced (Prompts), each a route of its own, with the Overview at #/settings", () => {
    expect([...DOORS_PAGES]).toEqual(["watching", "posting", "assistant", "spend", "privacy", "system", "appearance"]);
    expect(DOORS_PAGES.map((k) => doorsPage(k)?.title)).toEqual(["Watching", "Posting", "Assistant", "Spend", "Privacy & access", "System", "Appearance"]);
    expect([...ADVANCED_PAGES]).toEqual(["prompts"]);
    expect(SETTINGS_PAGES.map((p) => p.title)).toEqual(["Watching", "Posting", "Sources", "Prompts", "Spend", "Privacy & access", "System", "Assistant", "Appearance"]);
    for (const p of SETTINGS_PAGES) expect(matchRoute(["settings", p.key])).toMatchObject({ node: "settings/" + p.key });
    expect(matchRoute(["settings"])).toMatchObject({ node: "settings" });
  });

  it("redirect every old route, the selection kept; the pages of builds land on the Overview", () => {
    expect(go("settings/keys")).toEqual({ path: "settings/watching", sel: "ekey" });
    expect(go("settings/models")).toEqual({ path: "settings/watching", sel: "erole:afk:judge" });
    expect(go("settings/models", "erole:afk:reasoner")).toEqual({ path: "settings/watching", sel: "erole:afk:reasoner" });
    expect(go("settings/connections", "eacct:3")).toEqual({ path: "settings/watching", sel: "eacct:3" }); // the logins sources are read with
    expect(go("settings/accounts")).toEqual({ path: "settings/posting", sel: null });
    expect(go("settings/accounts", "eacct:3")).toEqual({ path: "settings/watching", sel: "eacct:3" });
    expect(go("settings/access", "etok:ui")).toEqual({ path: "settings/privacy", sel: "etok:ui" });
    expect(go("settings/health", "emsg:m1")).toEqual({ path: "settings/system", sel: "emsg:m1" });
    for (const gone of ["building", "publishing", "tools", "rules", "mcp", "capabilities", "plugins", "maintenance", "github", "projects"]) {
      expect(go("settings/" + gone), gone).toEqual({ path: "settings", sel: null });
    }
    // every redirect lands on a route that is a page
    for (const n of NODES.filter((x) => x.redirect && x.route.startsWith("settings/"))) {
      for (const to of [n.redirect!, ...Object.values(n.by_sel || {})]) expect(matchRoute(to!.split("/"))?.node, n.route).toBeTruthy();
    }
    expect(matchRoute(["settings", "connections", "x"])).toMatchObject({ node: "settings/sources", object: "connection" });
  });

  it("the Overview finds a setting by its name, where it is, or its key", () => {
    const month = findSettings("watching a month");
    expect(month.map((f) => [f.w, f.at])).toEqual([["Watching a month", "Spend › Caps"]]);
    expect(month[0]!.href).toBe("#/settings/spend?sel=ecap%3Awatch");
    expect(findSettings("monthly_usd").map((f) => f.w)).toEqual(["Watching a month", "X a month", "Live search a month"]);
    expect(findSettings("telemetry").map((f) => f.at)).toEqual(["Privacy & access"]);
    expect(findSettings("builds a day")).toEqual([]);   // builds left with the factory
    expect(findSettings("")).toEqual([]);
  });

  it("a page made of several lists draws their groups under one title", async () => {
    stub();
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [SETUP_API]: { key: { set: true, env: "ANTHROPIC_API_KEY", provider: "anthropic", choice: "anthropic", test: null }, every_hours: 3 },
      [AFK_MODELS]: { roles: [], routed: false, base_url: "", config: "/h/kranto.yaml" }, "/api/settings/spend": { deep_dive: { enabled: false, daily_usd: null } } });
    const w = await draw(WatchingList, where("settings/watching"));
    expect(w.target.querySelector("h1")?.textContent).toBe("Watching");
    expect(w.target.querySelectorAll("h1").length).toBe(1);
    expect([...w.target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toContain("Provider and key");
    expect([...w.target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toContain("Reading");
    expect(w.target.querySelector('[data-sel="ekey"] .r-title')?.textContent).toBe("Provider and key");
    expect(w.target.querySelector('[data-sel="elogins"]')).toBeNull();          // the logins left with builds
    w.done();
  });
});
