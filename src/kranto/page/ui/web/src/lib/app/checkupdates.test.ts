// Check for updates (the owner, 2026-10-22: "we should add the check for updates button as well"),
// a test per door: ⌘K, the version in the status bar (both layouts: the bar is the same in both
// frames), Settings' Overview, and the header's pill once the check has failed for two days.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import StatusBar from "../../shell/StatusBar.svelte";
import Header from "../../shell/Header.svelte";
import { answerOf, tidyError } from "../../pages/settings/checkupdates";
import type { UpdateState } from "../../pages/settings/updates";
import { ui } from "../shell.svelte";
import { chromeFacts } from "./chrome";
import { palItems } from "./commands";
import { flashNow, render } from "./route";
import { parse } from "../router";
import { frame, hostStatus, tick, unframe } from "./testing";
import "../../pages";
import { onPageLoaded } from "../pages.svelte";

const VIEW: UpdateState = {
  ok: true, checked_at: "2026-10-22T18:00:00Z", available: null, staged: null, can_apply: true,
  installed: { version: "0.3.74", channel: "stable" }, settings: { auto: "off", quiet_window: "03:00-06:00", channel: "stable" },
};
const PRIVATE = "GitHub answered 404 for iddv/kranto's releases (a private repo needs a GitHub login)";
const SHELL = { pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [] };

// a page part that finishes loading after its test (Settings' System row, loaded on demand) must
// not draw into a document that is gone: the hook is dropped after each test, and the hook itself
// checks for a document (the FACT of 13 November: "document is not defined … originated in
// checkupdates.test.ts" on a head that did not touch it)
afterEach(() => {
  onPageLoaded(() => {});
  unframe();
});
const framed = (o: Parameters<typeof frame>[0] = {}) => frame(o);

function drawn<T>(C: T) {
  const target = document.createElement("div");
  document.body.append(target);
  const app = mount(C as never, { target });
  flushSync();
  return { target, done: () => unmount(app) };
}
const posted = (net: { calls: [string, RequestInit | undefined][] }) =>
  net.calls.filter(([u, i]) => u === "/api/update/check" && i?.method === "POST").length;

describe("the answer, in words", () => {
  it("says the latest, a release ready, or why the check failed and what to do", () => {
    expect(answerOf(VIEW).text).toBe("You're on the latest, 0.3.74 (checked just now)");
    const ready = answerOf({ ...VIEW, available: "0.3.75", staged: { version: "0.3.75" } });
    expect(ready.text).toBe("0.3.75 is ready · Restart to update");
    expect(ready.next?.restart).toBe(true);
    expect(answerOf({ ...VIEW, available: "0.3.75", staged: { version: "0.3.75" }, can_apply: false }).text)
      .toBe("0.3.75 is ready · this Kranto updates from the command line: kranto update");
    const bad = answerOf({ ...VIEW, ok: false, error: PRIVATE });
    expect(bad.text).toBe("Can't check for updates: GitHub answered 404 (a private repo needs a GitHub login)");
    expect(bad.next).toEqual({ word: "Run gh auth login on the machine Kranto runs on, then check again", href: "#/settings/updates" });
    expect(answerOf({ ...VIEW, ok: false, error: "ConnectError: no route to host" }).next?.href).toBe("#/settings/updates");
    expect(tidyError(PRIVATE)).toBe("GitHub answered 404 (a private repo needs a GitHub login)");
  });
});

describe("⌘K", () => {
  it("has Check for updates, which asks the server and says the answer", async () => {
    const net = await framed({ hash: "#/settings" });
    net.answer["/api/update/check"] = VIEW;
    const item = palItems("", null).find((x) => x.title === "Check for updates");
    expect(item?.detail).toBe("Kranto 0.3.74; the answer shows at the top of the page");
    expect(palItems("", null).some((x) => x.title === "Update Kranto")).toBe(false);
    (item as { run: () => void }).run();
    for (let i = 0; i < 6; i++) await tick();
    expect(posted(net)).toBe(1);
    expect(flashNow()?.text).toBe("You're on the latest, 0.3.74 (checked just now)");
  });

  it("has Update Kranto when a release is on offer, and finds Check for updates by typing", async () => {
    const H = hostStatus();
    await framed({ hash: "#/settings", host: { ...H, update: { ...H.update, available: "0.3.75" } } });
    expect(palItems("", null).find((x) => x.title === "Update Kranto")?.detail).toBe("0.3.74 → 0.3.75; restarts Kranto");
    expect(palItems("check for upd", null)[0]?.title).toBe("Check for updates");
  });
});

for (const layout of ["new", "classic"] as const) {
  describe(`the version in the status bar, ${layout} layout`, () => {
    it("is pressable, and says the answer where it was pressed", async () => {
      const net = await framed({ hash: "#/needs", reads: { "/api/shell": { ...SHELL, layout } } });
      net.answer["/api/update/check"] = { ...VIEW, ok: false, error: PRIVATE };
      render();
      await tick();
      ui.facts = chromeFacts(parse());
      const { target, done } = drawn(StatusBar);
      const btn = target.querySelector("#bar-version-press") as HTMLButtonElement;
      expect(btn.textContent).toBe("Kranto 0.3.74 · Check for updates");
      btn.click();
      for (let i = 0; i < 6; i++) await tick();
      flushSync();
      expect(posted(net)).toBe(1);
      expect(target.querySelector("#bar-version-said")?.textContent).toBe("Can't check for updates: GitHub answered 404 (a private repo needs a GitHub login)");
      expect(target.querySelector("#bar-version a")?.getAttribute("href")).toBe("#/settings/updates");
      expect(btn.textContent).toBe("Kranto 0.3.74 · Check again");
      done();
    });
  });
}

describe("Settings' Overview", () => {
  it("draws the version on the System row, and Restart to update when one is ready", async () => {
    const net = await framed({ hash: "#/settings" });
    net.answer["/api/update/check"] = { ...VIEW, available: "0.3.75", staged: { version: "0.3.75" } };
    onPageLoaded(() => { if (typeof document !== "undefined" && document.getElementById("rows")) render(); }); // a part that arrives after the frame is gone draws nothing
    render();
    // the System row is a page part loaded on demand: wait for it (a loaded runner took longer
    // than the 80 ms this once allowed), redrawing as the part's own load would
    for (let i = 0; i < 400 && !document.getElementById("set-version-press"); i++) {
      await new Promise((r) => setTimeout(r, 5));
      if (i % 10 === 9) render();
    }
    const btn = document.getElementById("set-version-press") as HTMLButtonElement;
    expect(btn.textContent).toBe("Kranto 0.3.74 · Check for updates");
    btn.click();
    for (let i = 0; i < 6; i++) await tick();
    flushSync();
    expect(document.getElementById("set-version-said")?.textContent).toBe("0.3.75 is ready · Restart to update");
    expect(document.getElementById("set-version-restart")?.textContent).toBe("Restart to update");
  });
});

describe("the header's pill", () => {
  it("says it cannot check once the check has failed for more than two days, and is silent before", async () => {
    const H = hostStatus();
    await framed({ hash: "#/needs", host: { ...H, update: { ...H.update, check_failing: PRIVATE, failing_since: "2026-10-19T06:00:00Z" } as never } });
    ui.facts = chromeFacts(parse());
    const { target, done } = drawn(Header);
    const pill = target.querySelector("#hd-update") as HTMLAnchorElement;
    expect(pill.textContent).toBe("Can't check for updates");                    // the why is its tooltip
    expect(pill.getAttribute("title")).toContain("GitHub answered 404");
    expect(pill.getAttribute("href")).toBe("#/settings/updates");
    expect(pill.getAttribute("title")).toContain("since 2026-10-19");
    done();
    unframe();
    await framed({ hash: "#/needs" });
    ui.facts = chromeFacts(parse());
    const quiet = drawn(Header);
    expect(quiet.target.querySelector("#hd-update")).toBeNull();
    quiet.done();
  });
});
