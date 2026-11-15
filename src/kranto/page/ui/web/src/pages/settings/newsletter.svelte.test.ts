import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import PostingList from "./PostingList.svelte";
import AccountsPane from "./AccountsPane.svelte";
import ConnectionsList from "./ConnectionsList.svelte";
import NewsletterPane from "./NewsletterPane.svelte";
import { CONNECTIONS_API, type Connections } from "./connections";
import { NEWSLETTER_API, nlLine, nlSt, type Newsletter } from "./newsletter";

// the server's /api/newsletter (generated from its web/types.py). The platforms are made up: the page
// names whatever the server lists, and never one of its own.
const ALPHA = { id: "alpha", name: "Alpha", about: "An email platform.", docs: "docs/newsletter.md#alpha", can_schedule: true };
const BETA = { id: "beta", name: "Beta", about: "A newsletter service.", docs: "docs/newsletter.md#beta", can_schedule: false };
const NONE: Newsletter = { platform: null, name: null, unnamed: "your newsletter platform", platforms: [ALPHA, BETA], connection: null, from_address: null, audience: null,
  audiences: false, ready: false, missing: ["No newsletter platform is connected: Connect a provider"] };
const READY: Newsletter = { ...NONE, platform: ALPHA, name: "Alpha", connection: { id: 7, account: "Kranto <news@example.org>", state: "connected" },
  from_address: "Kranto <news@example.org>", audience: "the audience Readers", audiences: true, ready: true, missing: [] };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const at = (sel: string | null = "enl"): Where => ({ ...where("settings/posting", sel), r: { path: ["settings", "posting"], q: {}, sel } });

describe("Settings › Posting › Newsletter", () => {
  it("words the platform's state, and names none until one is connected", () => {
    expect(nlSt(NONE)[2]).toBe("Not connected");
    expect(nlLine(NONE)).toBe("No platform connected · Connect a provider");
    expect(nlSt(READY)[2]).toBe("Ready");
    expect(nlLine(READY)).toBe("Alpha · the audience Readers · ready");
    const missing = { ...READY, ready: false, missing: ["Your domain isn't verified yet."] };
    expect(nlSt(missing)[2]).toBe("Missing something");
    expect(nlLine(missing)).toBe("Alpha · the audience Readers · Your domain isn't verified yet.");
  });

  it("offers every platform under Connect a provider, the first as the default", async () => {
    stub();
    hosted();
    answering({ [NEWSLETTER_API]: NONE });
    const { target, done } = await draw(NewsletterPane, at(), "#/settings/accounts");
    expect(target.querySelector(".dk")?.textContent).toBe(" newsletter · your newsletter platform");
    expect(target.querySelector("#s-use p")?.textContent).toContain("No newsletter platform is connected.");
    const a = target.querySelector("#nl-connect-alpha") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("#/settings/connections/alpha");
    expect(a.className).toBe("btn sm primary");
    expect(target.querySelector("#nl-connect-beta")?.textContent).toBe("Connect Beta");
    expect(target.querySelector("#nl-check")).toBeNull();
    done();
  });

  it("says what is missing, checks again, and creates the audience after a confirm", async () => {
    const L = stub({ answer: { message: "Made the audience Readers at Alpha.", ok: true } });
    const dialog = vi.fn(), afkDrop = vi.fn();
    Object.assign(L, { dialog, afkDrop });
    hosted();
    answering({ [NEWSLETTER_API]: { ...READY, ready: false, audience: "no audience chosen yet", missing: ["There is no audience named “Readers”."] } });
    const { target, done } = await draw(NewsletterPane, at(), "#/settings/accounts");
    expect(target.querySelector("#nl-missing li")?.textContent).toContain("There is no audience named “Readers”.");
    (target.querySelector("#nl-check") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/newsletter/check", {});
    expect(afkDrop).toHaveBeenCalled();
    const name = target.querySelector("#nl-audience") as HTMLInputElement;
    name.value = "Readers";
    name.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.querySelector("#nl-create") as HTMLButtonElement).click();
    expect(dialog).toHaveBeenCalledWith("Create the audience?", [expect.any(HTMLElement)], "Create", expect.any(Function), "");
    expect(L.api).not.toHaveBeenCalledWith("/api/newsletter/audience", expect.anything());
    const close = vi.fn();
    dialog.mock.calls[0]![3](document.createElement("button"), close);
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/newsletter/audience", { confirm: true, name: "Readers" });
    expect(close).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Made the audience Readers at Alpha.", "blue");
    done();
  });

  it("puts the newsletter on Posting, and leaves its platforms out of the sites list", async () => {
    stub();
    hosted();
    const conns: Connections = { accounts: [], unavailable: null, storage: {}, callback: {}, providers: [
      { key: "mastodon", name: "Mastodon", state: "available", flow: "browser" },
      { key: "alpha", name: "Alpha", state: "available", flow: "paste", writes: true, group: "newsletter" }] };
    answering({ [NEWSLETTER_API]: READY, [CONNECTIONS_API]: conns });
    const list = await draw(ConnectionsList, at(null));
    expect(list.target.querySelector("#connect-mastodon")).not.toBeNull();
    expect(list.target.querySelector("#connect-alpha")).toBeNull();
    list.done();
    const acc = await draw(PostingList, at(null));
    const row = acc.target.querySelector('[data-sel="enl"]') as HTMLElement;
    expect(row.querySelector(".r-title")?.textContent).toBe("Newsletter");
    expect(row.querySelector(".c-meta")?.textContent).toBe("Alpha · the audience Readers · ready");
    acc.done();
    // the row's selection opens the newsletter's sheet through the accounts' pane
    const sheet = await draw(AccountsPane, at(), "#/settings/posting");
    expect(sheet.target.querySelector(".dt")?.textContent).toBe("Newsletter");
    expect(sheet.target.querySelector("#nl-check")).not.toBeNull();
    sheet.done();
  });
});
