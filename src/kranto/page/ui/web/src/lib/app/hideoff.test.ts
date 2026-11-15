// What is off is hidden: with cubs_developer false Cubs has Installed and
// Approvals only. A server from before the switches (no keys): everything as before. The pages of
// what left the product (what you read in your browser) are linked nowhere, whatever a host says.
import { afterEach, describe, expect, it } from "vitest";
import { chromeFacts } from "./chrome";
import { shopOff } from "./data";
import { render, routeNow } from "./route";
import { frame, hostStatus, tick, unframe } from "./testing";

afterEach(unframe);
const SHELL = { layout: "classic", pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };
const TODAY = { since: null, ingest: null, topics: [], messages: [], rising: [] };

async function at(hash: string, o: { browser?: boolean; cubs_developer?: boolean } | null): Promise<void> {
  const host = hostStatus(o || {});
  if (o === null) delete (host as { cubs_developer?: boolean }).cubs_developer;
  await frame({ hash, host, reads: { "/api/shell": SHELL, "/api/today": TODAY, "/api/topics?kind=project": { topics: [] } } });
  render();
  await tick();
  history.replaceState(null, "", hash);
  render();
  await tick();
}

describe("the browser pages, gone", () => {
  it.each([{ browser: true }, { browser: false }])("are linked nowhere (%o)", async (o) => {
    await at("#/settings", o);
    const tos = chromeFacts(routeNow()!.r)!.nav.rows.map((r) => r.to);
    expect(tos).not.toContain("settings/browser");
    expect(tos).not.toContain("settings/sources/browser");
    expect(tos).not.toContain("watch/sources/browser");
  });
});

describe("the cub shop", () => {
  it("is off without cubs.developer, and on with it", async () => {
    await at("#/cubs", { cubs_developer: false });
    expect(shopOff()).toBe(true);
    await at("#/cubs", { cubs_developer: true });
    expect(shopOff()).toBe(false);
    await at("#/cubs", null);
    expect(shopOff()).toBe(false);
  });
});
