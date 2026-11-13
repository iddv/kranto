// Where a posting cub's addresses land once a draft has its own page (#/post/d/<id>;):
// the cub's bare page is Post; a selection on it, or one of its own lists (its issues, its run
// log), still opens the cub's page.
import { afterEach, describe, expect, it } from "vitest";
import { landOf, render } from "../../lib/app/route";
import { frame, hostStatus, tick, unframe } from "../../lib/app/testing";

afterEach(unframe);
const SHELL = { layout: "new", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };

describe("a posting cub's addresses", () => {
  it("land on Post bare, and stay on the cub with a selection or a list", async () => {
    await frame({ hash: "#/home", host: hostStatus(),
      reads: { "/api/shell": SHELL, "/api/today": { since: null, ingest: null, topics: [], messages: [], rising: [] } } });
    render();
    await tick();
    expect(landOf("#/cub/newsletter")).toBe("#/post");
    expect(landOf("#/cub/toot")).toBe("#/post");
    expect(landOf("#/cub/newsletter?list=issues")).toBe("#/cub/newsletter?list=issues");
    expect(landOf("#/cub/newsletter?list=log")).toBe("#/cub/newsletter?list=log");
    expect(landOf("#/cub/toot?sel=draft%3A1")).toContain("#/cub/toot");
    expect(landOf("#/post/d/5")).toBe("#/post/d/5");
  });
});
