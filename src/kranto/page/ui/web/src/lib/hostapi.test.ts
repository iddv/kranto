import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import { HOST_API_VERSION } from "../api/afk.gen";
import type { Facts } from "./app";
import ListHead from "../shell/ListHead.svelte";
import { hostApiLine } from "./hostapi";
import { connect, ui } from "./shell.svelte";

afterEach(() => {
  ui.facts = null;
  connect(null);
});

describe("the server's API version", () => {
  it("says nothing when the server answers the version this page expects, or does not host it", () => {
    expect(hostApiLine({ version: "0.3.57", host_api: HOST_API_VERSION })).toBeNull();
    expect(hostApiLine(null)).toBeNull();
    expect(hostApiLine(undefined)).toBeNull();
  });

  it("says one line when the numbers differ, and an older server's none is v0", () => {
    expect(hostApiLine({ version: "0.3.60", host_api: 2 }, 1)).toBe(
      "the server 0.3.60 answers API v2; this page expects v1: update both with kranto update.");
    expect(hostApiLine({ version: "0.3.50", budget_usd: 10 }, 1)).toBe(
      "the server 0.3.50 answers API v0; this page expects v1: update both with kranto update.");
  });

  it("is the list head's first line, and only when they differ", () => {
    let status: Record<string, unknown> = { version: "0.3.50", budget_usd: 10 };
    connect({ host: () => status } as never);
    ui.facts = { head: { paused: null, signin: null, flash: null } } as unknown as Facts;
    const target = document.createElement("div");
    const app = mount(ListHead, { target });
    flushSync();
    const line = target.querySelector("#list-h > #host-api");
    expect(line?.textContent).toBe(`the server 0.3.50 answers API v0; this page expects v${HOST_API_VERSION}: update both with kranto update.`);
    expect(line?.className).toBe("flash amber");
    status = { version: "0.3.58", host_api: HOST_API_VERSION };
    ui.facts = { ...ui.facts } as Facts; // the app drew again after reading /api/status
    flushSync();
    expect(target.querySelector("#host-api")).toBeNull();
    expect(target.querySelector("#list-h")?.matches(":empty")).toBe(true);
    unmount(app);
  });
});
