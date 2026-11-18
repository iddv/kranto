import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import UpdatesList from "./UpdatesList.svelte";
import UpdatesPane from "./UpdatesPane.svelte";
import { buildLine, CHANNEL_HINT, CHANNEL_WORDS, channelReadback, latestLine, tagOf, UPD_API, type UpdateState } from "./updates";

const NOW = Date.now();
const iso = (minutesAgo: number) => new Date(NOW - minutesAgo * 60000).toISOString();
const D: UpdateState = {
  ok: true, checked_at: iso(3), available: "0.3.58", staged: { version: "0.3.58" }, can_apply: true,
  installed: { version: "0.3.57", channel: "stable" }, settings: { auto: "off", quiet_window: "03:00-06:00", channel: "stable" },
  apply: { state: "done", to: "0.3.57", finished: iso(60) }, previous: { version: "0.3.56" },
  history: [{ from: "0.3.56", to: "0.3.57", state: "done", finished: iso(60) }, { from: "0.3.55", to: "0.3.56", state: "rolled_back", reason: "it did not answer" }],
  latest: { version: "0.3.58", notes: ["- the page seam", "- Settings moved"], notes_url: "https://example.invalid/notes" },
};
const hosted = () => { ui.facts = { header: { host: { paused: false, running: null, next: null } } } as unknown as Facts; };
afterEach(() => {
  ui.facts = null;
});

describe("Settings › System › Updates", () => {
  it("says what was checked", () => {
    expect(latestLine(D, NOW)).toBe("0.3.58 available, staged");
    expect(latestLine({ ...D, available: null }, NOW)).toBe("up to date, checked 3 min ago");
    expect(latestLine({ ...D, ok: false, error: "offline" }, NOW)).toBe("check failed 3 min ago: offline");
    expect(latestLine({ ...D, checked_at: null }, NOW)).toBe("not checked yet");
  });

  it("names the two lines, and never by time", () => {
    expect(Object.keys(CHANNEL_WORDS)).toEqual(["stable", "nightly", "main"]);
    expect(CHANNEL_WORDS.nightly).toBe("nightly: a new version from main, several a day"); // 
    expect(CHANNEL_HINT).toContain("you click to update (nothing installs by itself)");
    expect(CHANNEL_HINT).toContain("never downgrades");
    expect(`${CHANNEL_WORDS.stable} ${CHANNEL_HINT}`).not.toMatch(/\b(\d+ days|\d+ hours|after it has run)\b/);
    expect(buildLine("0.7.0.dev12")).toBe("nightly 12 toward 0.7.0");
    expect(["0.6.2", "0.7.0.dev12", "0.5.27rc1", "v0.6.2"].map(tagOf)).toEqual(["v0.6.2", "v0.7.0-dev12", "v0.5.27-rc1", "v0.6.2"]);
    expect(buildLine("0.6.2")).toBeNull();
    expect(channelReadback("nightly", { version: "0.6.2", channel: "stable" })).toBe("channel nightly: the next check offers the newest version");
    expect(channelReadback("stable", { version: "0.7.0.dev14", channel: "nightly" })).toBe(
      "channel stable: you stay on 0.7.0.dev14 until a newer stable is released; nothing is downgraded",
    );
    expect(channelReadback("stable", { version: "0.6.2", channel: "stable" })).toBe("channel stable");
  });

  it("heads a nightly install with its build", async () => {
    stub();
    hosted();
    answering({ [UPD_API]: { ...D, available: null, installed: { version: "0.7.0.dev12", channel: "nightly" } } });
    const { target, done } = await draw(UpdatesPane, where("settings/updates"));
    expect(target.textContent).toContain("Kranto 0.7.0.dev12");
    expect(target.textContent).toContain("nightly 12 toward 0.7.0 · up to date");
    done();
  });

  it("lists the version, automatic updates, the channel and the recent updates", async () => {
    stub();
    hosted();
    answering({ [UPD_API]: D });
    const { target, done } = await draw(UpdatesList, where("settings/updates"));
    const rows = [...target.querySelectorAll("li.row")];
    expect(rows.map((r) => r.getAttribute("data-sel"))).toEqual(["eversion", "eauto", "echannel", "ehist:0", "ehist:1"]);
    expect(rows[0]?.querySelector(".gl")?.getAttribute("title")).toBe("Needs you");
    expect(rows[0]?.querySelector(".c-meta")?.textContent).toBe("0.3.57 (stable) · 0.3.58 available, staged");
    expect(rows[4]?.querySelector(".r-title")?.textContent).toBe("0.3.55 → 0.3.56: rolled back");
    expect(target.querySelector(".tbn")?.textContent).toBe("0.3.58 available, stagedCheck for updates");
    ui.facts = null;
    done();
  });

  it("says Updates need the server on brb ui alone", async () => {
    stub();
    ui.facts = { header: { host: null } } as unknown as Facts;
    const { target, done } = await draw(UpdatesList, where("settings/updates"));
    expect(target.querySelector("strong")?.textContent).toBe("Updates need Kranto's server, which is not answering. ");
    ui.facts = null;
    done();
  });

  it("checks now, and what the check answered is the page", async () => {
    const L = stub({ answer: { ...D, available: null } }) as ReturnType<typeof stub> & { loadHost: () => Promise<void> };
    (L as unknown as { loadHost: () => Promise<void> }).loadHost = vi.fn(async () => {});
    hosted();
    answering({ [UPD_API]: D });
    const { target, done } = await draw(UpdatesList, where("settings/updates"));
    (target.querySelector("#upd-check") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(UPD_API + "/check", {});
    expect(L.say).toHaveBeenCalledWith("You're on the latest, 0.3.57 (checked just now)", undefined);
    expect(target.querySelector(".tbn span")?.textContent).toMatch(/^up to date/);
    ui.facts = null;
    done();
  });

  it("offers Restart to update and Roll back; no Update now (no build to stop)", async () => {
    const L = stub() as ReturnType<typeof stub> & Record<string, ReturnType<typeof vi.fn>>;
    Object.assign(L, { updApply: vi.fn(), updRollback: vi.fn(), updCancel: vi.fn() });
    hosted();
    answering({ [UPD_API]: D });
    const { target, done } = await draw(UpdatesPane, where("settings/updates"));
    expect(target.querySelector(".dt")?.textContent).toBe("Update 0.3.57 → 0.3.58");
    (target.querySelector("#upd-apply") as HTMLButtonElement).click();
    expect(L.updApply).toHaveBeenCalled();
    expect(target.querySelector("#upd-now")).toBeNull();
    (target.querySelector("#upd-rollback") as HTMLButtonElement).click();
    expect(L.updRollback).toHaveBeenCalledWith(expect.anything(), "0.3.56");
    expect([...target.querySelectorAll(".notes li")].map((li) => li.textContent)).toEqual(["the page seam", "Settings moved"]);
    done();
  });

  it("says How to update where this Kranto cannot apply one, and offers Cancel while it waits for a job", async () => {
    const L = stub() as ReturnType<typeof stub> & Record<string, ReturnType<typeof vi.fn>>;
    Object.assign(L, { updApply: vi.fn(), updRollback: vi.fn(), updCancel: vi.fn() });
    hosted();
    answering({ [UPD_API]: { ...D, can_apply: false } });
    const cli = await draw(UpdatesPane, where("settings/updates"));
    expect(cli.target.querySelector("#upd-apply")).toBeNull();
    expect(cli.target.querySelector("#upd-rollback")).toBeNull();
    expect(cli.target.querySelector(".acts a.btn.primary")?.textContent).toBe("How to update");
    expect(cli.target.querySelector("#s-state code")?.textContent).toBe("kranto update");
    cli.done();
    const M = stub() as ReturnType<typeof stub> & Record<string, ReturnType<typeof vi.fn>>;
    Object.assign(M, { updApply: vi.fn(), updRollback: vi.fn(), updCancel: vi.fn() });
    hosted();
    answering({ [UPD_API]: { ...D, apply: { state: "draining", to: "0.3.58" } } });
    const wait = await draw(UpdatesPane, where("settings/updates"));
    expect(wait.target.querySelector("#s-state p")?.textContent).toBe("Updating to 0.3.58: waiting for a job to finish.");
    expect(wait.target.querySelector("#upd-apply")).toBeNull();
    (wait.target.querySelector("#upd-cancel") as HTMLButtonElement).click();
    expect(M.updCancel).toHaveBeenCalled();
    wait.done();
  });

  it("saves automatic updates from what is typed, and only on Save", async () => {
    const saved = { ...D, settings: { auto: "idle", quiet_window: "02:00-05:00", channel: "stable" } };
    const L = stub({ answer: saved }) as ReturnType<typeof stub> & { loadHost: ReturnType<typeof vi.fn> };
    Object.assign(L, { loadHost: vi.fn(async () => {}) });
    hosted();
    answering({ [UPD_API]: D });
    const { target, done } = await draw(UpdatesPane, where("settings/updates", "eauto"));
    (target.querySelector("#upd-auto-idle") as HTMLInputElement).click();
    const win = target.querySelector("#upd-window") as HTMLInputElement;
    win.value = "02:00-05:00";
    win.dispatchEvent(new Event("input", { bubbles: true })); // as a browser's does (Svelte listens at the root)
    expect(L.api).not.toHaveBeenCalled();
    (target.querySelector("#save-update") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(UPD_API + "/settings", { auto: "idle", quiet_window: "02:00-05:00" });
    expect(L.toast).toHaveBeenCalledWith("Saved: automatic updates when idle, 02:00-05:00; channel stable. From the next check.", expect.any(Function));
    done();
  });

  it("offers Check for updates on the version's sheet when up to date (the New layout's System page opens it)", async () => {
    const L = stub({ host: { version: "0.3.57", update: { installed: "0.3.57" } }, answer: { ...D, available: null, staged: null } });
    Object.assign(L, { loadHost: vi.fn(async () => {}) });
    hosted();
    answering({ [UPD_API]: { ...D, available: null, staged: null } });
    const { target, done } = await draw(UpdatesPane, where("settings/updates"));
    const press = target.querySelector("#upd-pane-version-press") as HTMLButtonElement;
    expect(press.textContent).toBe("Kranto 0.3.57 · Check for updates");
    press.click();
    await settle();
    await settle();
    expect(L.api).toHaveBeenCalledWith(UPD_API + "/check", {});
    expect(target.querySelector("#upd-pane-version-said")?.textContent).toBe("You're on the latest, 0.3.57 (checked just now)");
    done();
  });

  it("reads nothing without the server: updates are its alone", async () => {
    stub();
    answering({});
    const { target, done } = await draw(UpdatesPane, where("settings/updates"));
    expect(target.querySelector(".empty")?.textContent).toBe("Loading…");
    done();
  });
});
