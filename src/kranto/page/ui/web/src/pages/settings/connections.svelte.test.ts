import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, ownerText, SETTING_KEY, settle, stub, where } from "../testing.svelte";
import ConnectionsList from "./ConnectionsList.svelte";
import ConnectionsPane from "./ConnectionsPane.svelte";
import { acctWords, CONNECTIONS_API, DEVICE, devicePoll, INSTANCE, provSt, type Connections, type Provider } from "./connections";

const NOW = new Date().toISOString();
const prov = (key: string, o: Partial<Provider> = {}): Provider => ({
  key, name: key[0]!.toUpperCase() + key.slice(1), state: "available", flow: "browser", blurb: `Reads ${key}.`, steps: ["One", "Two"], scopes: ["read"],
  reads: "your feed", sources: ["Home"], never: "Never posts.", revoke_at: "the site's settings", expiry: "until revoked", ...o,
});
// The server's /api/connections (Connections is generated from its web/types.py)
const D: Connections = {
  accounts: [{ id: 4, provider: "mastodon", provider_name: "Mastodon", instance: "example.social", account: "@me@example.social", state: "connected", note: null, scopes: ["read"],
    sources: [{ id: 9, label: "Home timeline" }], connected_at: "2026-09-01T10:00:00Z", state_at: "2026-09-01T10:00:00Z", last_used_at: NOW, last_test: null },
  { id: 5, provider: "bluesky", provider_name: "Bluesky", instance: "bluesky", account: "me.example", state: "needs_login", note: "Refused.", scopes: ["read"], sources: [],
    connected_at: "2026-09-01T10:00:00Z", state_at: "2026-09-02T10:00:00Z", last_used_at: null, last_test: null }],
  providers: [prov("mastodon"), prov("bluesky", { flow: "both", redirect_host: "127.0.0.1", alt_steps: ["Make one"], fields: [{ key: "password", label: "App password", secret: true }] }),
    prov("github", { flow: "paste", device: true, fields: [{ key: "token", label: "Token", secret: true }] }),
    prov("x", { name: "X / Twitter", flow: "client", redirect_host: "127.0.0.1", client_set: false, client_section: "1. Your X developer app", client_ready: "Save the client id first.",
      client_removed: "Removed the client id.", cost: "About $46 a month at the defaults.", steps: ["Console", "Credits", "App", "Native App", "Client id", "Connect", "Add sources"],
      fields: [{ key: "client_id", label: "Client ID", placeholder: "the OAuth 2.0 Client ID" }] }),
    { key: "linkedin", name: "LinkedIn", state: "not_offered", reason: "No API." }],
  unavailable: null, storage: { cipher: "AES-GCM", key: "in the OS keyring" }, callback: { mastodon: "/connections/mastodon/callback" },
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; DEVICE.d = null; });
const at = (q: Record<string, string> = {}, sel: string | null = null): Where => ({ ...where("settings/connections", sel), r: { path: ["settings", "connections"], q, sel } });
const provider = (key: string): Where => ({ ...where("settings/connections"), r: { path: ["settings", "connections", key], q: {}, sel: null }, list: ["settings", "connections"],
  object: "connection", obj: ["settings", "connections", key], id: key });

describe("Settings › Sources › Accounts", () => {
  it("words an account and a provider", () => {
    expect(acctWords(D.accounts[1]!).meta).toBe("Refused. Connect again to resume 0 sources.");
    expect(acctWords(D.accounts[0]!).meta).toBe("@me@example.social · 1 source · last used just now");
    expect(provSt(prov("youtube", { flow: "client", client_set: true }), 0)[2]).toBe("Client saved");
    expect(provSt(prov("x", { flow: "client", client_set: false }), 0)[2]).toBe("Not connected");
    expect(provSt(prov("mastodon"), 2)[2]).toBe("2 connected");
  });

  it("lists your accounts and the providers by state", async () => {
    stub();
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const { target, done } = await draw(ConnectionsList, at());
    expect([...target.querySelectorAll(".grp h2")].map((h) => h.textContent)).toEqual(["Accounts", "Accounts you can connect", "Not offered"]);
    expect(target.querySelector('[data-sel="eacct:5"] .r-act a')?.getAttribute("href")).toBe("#/settings/connections/bluesky");
    expect(target.querySelector('[data-sel="eacct:4"] .r-act')).toBeNull();
    expect(target.querySelector("#connect-mastodon")?.textContent).toBe("Connect another");
    expect(target.querySelector("#connect-github")?.className).toBe("btn sm");       // plain: Settings keeps one primary
    expect(target.querySelector("#connect-bluesky")?.textContent).toBe("Details");
    const no = [...target.querySelectorAll("li.row")].find((x) => x.querySelector(".r-title")?.textContent === "LinkedIn") as HTMLElement;
    expect(no.querySelector(".c-meta")?.textContent).toBe("not offered · No API.");
    done();
  });

  it("says how a sign-in went, once, when it comes back", async () => {
    const L = stub();
    const afkDrop = vi.fn();
    Object.assign(L, { afkDrop });
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const { done } = await draw(ConnectionsList, at({ connected: "Mastodon" }));
    expect(L.say).toHaveBeenCalledWith("Connected Mastodon. Its sources are read with it from the next ingest run.", undefined);
    expect(afkDrop).toHaveBeenCalled();
    expect(location.hash).toBe("#/settings/watching"); // a site's sign-in comes back to Watching's logins
    history.replaceState(null, "", "#/");
    done();
    stub();
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const post = await draw(ConnectionsList, at({ connected: "Mastodon" }), null, { part: "posting" });
    expect(location.hash).toBe("#/settings/posting"); // a posting account's comes back to Posting
    history.replaceState(null, "", "#/");
    post.done();
  });

  it("says GitHub's device flow needs a client id without a setting key in the words", async () => {
    stub();
    hosted();
    const gh = D.providers.map((p) => (p.key === "github" ? { ...p, device: false, device_steps: ["Register an OAuth app"] } : p));
    answering({ [CONNECTIONS_API]: { ...D, providers: gh } });
    const { target, done } = await draw(ConnectionsPane, provider("github"));
    expect(target.textContent).toContain("Once its client id is in your settings (written by hand; the setting is under Advanced below)");
    expect(ownerText(target).match(SETTING_KEY)).toBeNull();
    expect(target.querySelector("details.advanced code")?.textContent).toBe("connections.github_client_id");
    done();
  });

  it("says how tokens are kept, and that Connections need the server", async () => {
    stub();
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const home = await draw(ConnectionsPane, at());
    expect(home.target.querySelector(".dt")?.textContent).toBe("Accounts Kranto may read with");
    expect([...home.target.querySelectorAll("#s-storage dt")].map((x) => x.textContent)).toEqual(["Cipher", "Key"]);
    home.done();
    stub();
    ui.facts = null;
    const none = await draw(ConnectionsList, at());
    expect(none.target.querySelector("strong")?.textContent).toBe("Connections need the server. ");
    none.done();
  });

  it("tests an account and disconnects it after a confirm", async () => {
    const L = stub({ answer: { message: "Works.", ok: true } });
    const dialog = vi.fn(), afkDrop = vi.fn();
    Object.assign(L, { dialog, afkDrop });
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const { target, done } = await draw(ConnectionsPane, at({}, "eacct:4"), "#/settings/connections");
    expect(target.querySelector(".dk")?.textContent).toBe(" account · Mastodon");
    expect(target.querySelector("#s-sources a")?.getAttribute("href")).toBe("#/settings/sources/9");
    (target.querySelector("#test-account") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/connections/4/test", {});
    expect(L.say).toHaveBeenCalledWith("Works.", "blue");
    ([...target.querySelectorAll(".dh .acts button")].find((b) => b.textContent === "Disconnect") as HTMLButtonElement).click();
    expect(dialog).toHaveBeenCalledWith("Disconnect Mastodon?", [expect.any(HTMLElement)], "Disconnect", expect.any(Function), "");
    const close = vi.fn();
    dialog.mock.calls[0]![3](document.createElement("button"), close);
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/connections/4/disconnect", {});
    expect(close).toHaveBeenCalled();
    done();
  });

  it("saves a pasted token once and clears it, and starts GitHub's device flow", async () => {
    const L = stub({ answer: { message: "Saved and tested." } });
    const afkDrop = vi.fn();
    Object.assign(L, { afkDrop });
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const { target, done } = await draw(ConnectionsPane, provider("github"), "#/settings/connections");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    expect(target.querySelector("#s-token h3")?.textContent).toBe("Paste a fine-grained token");
    const tok = target.querySelector("#f-github-token") as HTMLInputElement;
    expect(tok.type).toBe("password");
    (target.querySelector("#save-github") as HTMLButtonElement).click();
    expect(L.api).not.toHaveBeenCalled();
    tok.value = "  pasted  ";
    (target.querySelector("#save-github") as HTMLButtonElement).click();
    await vi.advanceTimersByTimeAsync(0);
    expect(L.api).toHaveBeenCalledWith("/api/connections/github/credentials", { token: "pasted" });
    expect(tok.value).toBe("");
    expect(L.say).toHaveBeenCalledWith("Saved and tested.");
    L.api.mockResolvedValueOnce({ verification_uri: "https://github.com/login/device", user_code: "ABCD-1234", interval: 5 });
    (target.querySelector("#device") as HTMLButtonElement).click();
    await vi.advanceTimersByTimeAsync(0);
    expect(L.api).toHaveBeenCalledWith("/connections/github/device", {});
    expect(DEVICE.d?.user_code).toBe("ABCD-1234");
    expect(L.render).toHaveBeenCalled();
    clearTimeout(DEVICE.d?.timer);
    done();
    vi.useRealTimers();
  });

  it("polls the device flow no faster than GitHub's interval", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const L = stub();
    Object.assign(L, { afkDrop: vi.fn() });
    history.replaceState(null, "", "#/settings/connections/github");
    L.api.mockResolvedValueOnce({ state: "pending", interval: 10 }).mockResolvedValueOnce({ state: "connected", account: "me" });
    DEVICE.d = { key: "github", verification_uri: "https://github.com/login/device", user_code: "X", interval: 5 };
    devicePoll("github");
    await vi.advanceTimersByTimeAsync(5000);
    expect(L.api).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(250);
    expect(L.api).toHaveBeenCalledTimes(1);
    expect(DEVICE.d?.interval).toBe(10);
    await vi.advanceTimersByTimeAsync(10250);
    expect(L.api).toHaveBeenCalledTimes(2);
    expect(DEVICE.d).toBeNull();
    expect(L.say).toHaveBeenCalledWith("Connected GitHub me.", "blue");
    history.replaceState(null, "", "#/");
    vi.useRealTimers();
  });

  it("asks a sign-in's first field before it leaves for the provider, and keeps it across draws", async () => {
    const L = stub();
    L.api.mockResolvedValueOnce({ authorize_url: "#/signed-in-elsewhere" });
    hosted();
    answering({ [CONNECTIONS_API]: { ...D, accounts: [] } });
    const { target, done } = await draw(ConnectionsPane, provider("mastodon"), "#/settings/connections");
    expect(target.querySelector(".dt")?.textContent).toBe("Connect Mastodon");
    expect(target.querySelector("#s-signin .mono")?.textContent).toBe(`Callback: http://localhost:${location.port || "80"}/connections/mastodon/callback`);
    const go = target.querySelector("#connect") as HTMLButtonElement;
    expect(go.textContent).toBe("Connect");
    go.click();
    expect(L.api).not.toHaveBeenCalled();
    const inst = target.querySelector("#instance") as HTMLInputElement;
    inst.value = "example.social";
    inst.dispatchEvent(new Event("input", { bubbles: true }));
    expect(INSTANCE.mastodon).toBe("example.social");
    go.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/connections/mastodon/start", { instance: "example.social" });
    expect(location.hash).toBe("#/signed-in-elsewhere");
    expect(INSTANCE.mastodon).toBeUndefined();
    history.replaceState(null, "", "#/");
    done();
  });

  it("draws Bluesky's sign-in off away from 127.0.0.1, and a provider not offered", async () => {
    stub();
    hosted();
    answering({ [CONNECTIONS_API]: D });
    const sky = await draw(ConnectionsPane, provider("bluesky"), "#/settings/connections");
    expect((sky.target.querySelector("#connect") as HTMLButtonElement).disabled).toBe(true);
    expect(sky.target.querySelector(".note")?.textContent).toContain("Bluesky only sends your browser back to 127.0.0.1. Open Kranto as ");
    expect(sky.target.querySelector("#s-connected strong")?.textContent).toBe("me.example");
    expect(sky.target.querySelector("#f-bluesky-password")?.getAttribute("type")).toBe("password");
    sky.done();
    stub();
    hosted();
    const li = await draw(ConnectionsPane, provider("linkedin"), "#/settings/connections");
    expect(li.target.querySelector(".dk")?.textContent).toBe(" connection · not offered");
    expect(li.target.querySelector("#s-about p")?.textContent).toBe("No API.");
    li.done();
  });

  it("draws X's own app first, its cost, and Connect only once the client id is saved", async () => {
    const L = stub({ answer: { message: "Saved. Now click Connect." } });
    Object.assign(L, { afkDrop: vi.fn() });
    hosted();
    answering({ [CONNECTIONS_API]: { ...D, accounts: [] } });
    const x = await draw(ConnectionsPane, provider("x"), "#/settings/connections");
    expect(x.target.querySelector(".dk")?.textContent).toBe(" connection · your own app");
    expect(x.target.querySelector("#s-project h3")?.textContent).toBe("1. Your X developer app");
    expect(x.target.querySelector("#s-signin h3")?.textContent).toBe("2. Connect");
    expect(x.target.querySelector("#cost")?.textContent).toBe("About $46 a month at the defaults.");
    expect([...x.target.querySelectorAll("#s-project li")].map((li) => li.textContent)).toEqual(["Console", "Credits", "App", "Native App", "Client id"]);
    expect([...x.target.querySelectorAll("#s-signin li")].map((li) => li.textContent)).toEqual(["Connect", "Add sources"]);
    expect((x.target.querySelector("#connect") as HTMLButtonElement).disabled).toBe(true);
    expect(x.target.querySelector("#s-signin .mono")?.textContent).toContain("Save the client id first. Callback: http://127.0.0.1:");
    const id = x.target.querySelector("#f-x-client_id") as HTMLInputElement;
    expect(id.type).toBe("text");
    id.value = " abc123 ";
    (x.target.querySelector("#save-x") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/connections/x/credentials", { client_id: "abc123" });
    x.done();
    stub();
    hosted();
    answering({ [CONNECTIONS_API]: { ...D, accounts: [], providers: D.providers.map((p) => (p.key === "x" ? { ...p, client_set: true } : p)) } });
    const saved = await draw(ConnectionsPane, provider("x"), "#/settings/connections");
    expect([...saved.target.querySelectorAll("#s-project p")].map((p) => p.textContent).join(" ")).toContain("Client id saved, encrypted.");
    expect(saved.target.querySelector("#clear-client")?.textContent).toBe("Remove it");
    saved.done();
  });
});
