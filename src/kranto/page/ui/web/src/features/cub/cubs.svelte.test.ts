import { mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { drop, setFetcher } from "../../lib/reads.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub } from "../../pages/testing.svelte";
import DialogHost from "../../ui/DialogHost.svelte";
import { closeDialog, dlg } from "../../ui/dialog.svelte";
import { FEATURES_API, type Features } from "../index";
import { CUBS_API, type CubJob, type CubsList } from "../cub";
import AddCub from "./AddCub.svelte";
import CubsPage from "./CubsPage.svelte";
import CubsPane from "./CubsPane.svelte";
import AskDialog from "./AskDialog.svelte";

let host: ReturnType<typeof mount> | null = null;
beforeEach(() => { host = mount(DialogHost, { target: document.body }); });
afterEach(() => {
  closeDialog();
  if (host) void unmount(host);
  ui.facts = null;
  ui.headOn = false;
  ui.head = null;
  dlg.now = null;
  document.body.replaceChildren();
});
/** the head as the shell draws it */
const headOf = () => ui.head!;
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
const enabledRow = (sensitive: boolean) => ({ key: "digest.enabled", value: true, type: "bool", default: false, choices: [], lo: null, hi: null, words: "Digest (practice)", sensitive, by_hand: false, per_topic: false });
const F: Features = { api: "cub/1", reads: [], request_kinds: ["book.place"], features: [
  { id: "news", title: "News", says: "Briefs.", version: "1.0.0", trust: "first-party", enabled: true, mode: "live", tickets_open: 0, manifest: { ui: { nav: [], cards: {} } } },
  { id: "digest", title: "Digest", says: "Proposals from the news.", version: "1.0.0", trust: "first-party", enabled: true, mode: "practice", tickets_open: 1,
    settings: [enabledRow(true)], manifest: { ui: { nav: [], cards: {}, glyph: "up" } } },
  { id: "toot", title: "Toot the pick", says: "The editor's pick as a post. You approve it.", version: "1.0.0", trust: "owner", enabled: true, mode: "drafts only", tickets_open: 0,
    manifest: { ui: { nav: [], cards: {}, glyph: "pen" } } }],
  request_schemas: { "book.place": { title: "Book this table", doors: ["ui"], page_only: true, performs: true, expires_hours: 24, per_day: 10, fields: [] } } };
// what the cubs ask (the server's GET /api/asks): one of the toot's, and one of a cub not installed
const ASKS = { asks: [{ id: "draft:5", cub: "toot", title: "A post about the pick", meta: "practice: nothing is sent", at: "2026-10-19T09:00:00Z", ticket: 41, again: null, verb: "Post toot", ask: { line: "practice: nothing is sent", said: null, open: true } },
                      { id: "draft:6", cub: "gone", title: "Something", meta: "ready", at: "2026-10-19T09:00:00Z", ticket: 42, again: null, verb: "Send", ask: { line: "ready", said: null, open: true } }] };
const toot = (o: Record<string, unknown> = {}) => ({ id: "toot", title: "Toot the pick", version: "1.0.0", trust: "owner", state: "installed", enabled: true, mode: "drafts only",
  live: [], source: { kind: "folder", path: "/x/toot" }, installed_at: "2026-10-19T09:00:00Z", pinned: true, tree_ok: true, update: null, paused: null, tickets_open: 0,
  spend: { month_usd: 0, cap_usd: 1, calls_today: 0, calls_per_day: 10000 }, ...o });
const LINES = (o: Partial<CubsList> = {}, line: Record<string, unknown> = {}): CubsList =>
  ({ cubs: [toot(line)] as unknown as CubsList["cubs"], enabled: true, stop_file: false, limits_mode: "scope", sandbox: true, ...o });
const READS = (lines: CubsList | null = LINES()) => ({ [FEATURES_API]: F, "/api/asks": ASKS, ...(lines ? { [CUBS_API]: lines } : {}) });

function at(path: string, sel: string | null = null) {
  return { node: "cubs", list: path.split("/"), id: sel, stage: true, missing: false, object: null, obj: null, sel: false, r: { path: path.split("/"), q: {}, sel } };
}

describe("Features (#/cubs/<tab>)", () => {
  it("says it is reading, never \"0 features installed · None yet\", until the features arrive (QA B14)", async () => {
    stub();
    hosted();
    drop(FEATURES_API);
    let arrive: (v: unknown) => void = () => {};
    setFetcher((path) => (path === FEATURES_API ? new Promise((r) => { arrive = r; }) : Promise.reject(new Error("not found: " + path))));
    ui.headOn = true;
    const { target, done } = await draw(CubsPage, at("cubs"));
    expect(target.textContent).not.toMatch(/0 features installed|None yet/);
    expect(headOf().facts).toBe("reading your features…");
    arrive(structuredClone(F));
    await settle();
    await settle();
    expect(headOf().facts).toContain("2 features installed");
    done();
  });

  it("lists the installed cubs (not the doors) with their tags, a switch behind the house confirm and Staged", async () => {
    const L = stub();
    hosted();
    ui.headOn = true;
    answering(READS());
    const { target, done } = await draw(CubsPage, at("cubs"));
    await settle();
    expect([...target.querySelectorAll("[aria-labelledby=cubs-installed] .r-title")].map((x) => x.textContent)).toEqual(["Digest", "Toot the pick"]);
    expect(target.querySelector("[aria-labelledby=cubs-installed] .c-meta")?.textContent).toContain("built-in");
    // the shell's underlined words, never pills
    expect(headOf().sub!.map((x) => x.w + (x.n ?? ""))).toEqual(["Installed2", "Available", "Made by Kranto", "Approvals1"]);
    (target.querySelector('[data-cub-switch="digest"]') as HTMLButtonElement).click();
    expect(L.api).not.toHaveBeenCalled();
    expect(dlg.now).not.toBeNull();
    expect(headOf().primary).toMatchObject({ id: "cubs-add", href: "#/cubs?sel=add" });
    expect(headOf().flash).toBeNull();
    done();
  });

  it("lists an update staged for an installed cub under Staged, with what it may now do", async () => {
    stub();
    hosted();
    answering(READS(LINES({}, { update: { version: "1.2.0", sha: null, job: "j1", needs: "house", adds: ["requests: post.topic"] } })));
    const { target, done } = await draw(CubsPage, at("cubs"));
    await settle();
    const staged = target.querySelector("[aria-labelledby=cubs-staged]")!;
    expect(staged.querySelector(".r-title")?.textContent).toBe("Toot the pick 1.2.0");
    expect(staged.querySelector(".c-meta")?.textContent).toBe("an update, staged · installed 1.0.0 · it may now: requests: post.topic");
    // its update is on its Settings page
    expect(staged.querySelector('[data-cub-update="toot"]')?.getAttribute("href")).toBe("#/settings/toot");
    done();
    stub();
    answering(READS());
    const none = await draw(CubsPage, at("cubs"));
    await settle();
    expect(none.target.querySelector("[aria-labelledby=cubs-staged] .r-title")).toBeNull();
    none.done();
  });

  it("says when every cub is stopped or off, and tags a stopped cub", async () => {
    stub();
    hosted();
    ui.headOn = true;
    answering(READS(LINES({ stop_file: true }, { state: "paused", paused: { note: "stopped by the owner" } })));
    let v = await draw(CubsPage, at("cubs"));
    await settle();
    expect(headOf().flash).toMatchObject({ kind: "red" });
    expect(headOf().flash?.text).toContain("cubs.STOP exists");
    const metas = [...v.target.querySelectorAll("[aria-labelledby=cubs-installed] .c-meta")].map((x) => x.textContent);
    expect(metas[1]).toContain("stopped");
    v.done();
    answering(READS(LINES({ enabled: false })));
    ui.headOn = true;
    v = await draw(CubsPage, at("cubs"));
    await settle();
    expect(headOf().flash?.text).toContain("cubs.enabled: false");
    v.done();
  });

  it("has one path to add a feature: Add a feature is the head's one primary, Check a manifest a fold in its sheet", async () => {
    stub();
    hosted();
    answering(READS());
    ui.headOn = true;
    let v = await draw(CubsPage, at("cubs"));
    await settle();
    // one primary; Arrange the home under ⋯
    expect(headOf().primary?.label).toBe("Add a feature");
    expect(headOf().more!.map((x) => x.label)).toEqual(["Arrange the home"]);
    v.done();
    v = await draw(CubsPane, at("cubs", "add"));                                    // the shell's one sheet
    await settle();
    const sheets = v.target.ownerDocument.querySelectorAll("#cubs-sheet");
    expect(sheets.length).toBe(1);
    expect(sheets[0]!.querySelector("#cub-source")).not.toBeNull();
    expect((sheets[0]!.querySelector("#cub-check-fold") as HTMLDetailsElement).open).toBe(false);
    expect(sheets[0]!.querySelector("#cub-check-fold summary")?.textContent).toContain("Check a manifest");
    v.done();
  });

  it("offers no Add without the cub runtime (a server that answers /api/cubs with 404)", async () => {
    stub();
    hosted();
    drop(CUBS_API);
    ui.headOn = true;
    answering(READS(null));
    const { done } = await draw(CubsPage, at("cubs"));
    await settle();
    expect(headOf().primary?.id).toBe("cubs-check");
    done();
  });

  it("says there is no index yet, and no building from a sentence yet, never a version it already passed", async () => {
    stub();
    hosted();
    answering(READS());
    let v = await draw(CubsPage, at("cubs/available"));
    await settle();
    expect(v.target.querySelector("#cubs-index")?.textContent).toContain("There is no index of other people's features yet.");
    v.done();
    v = await draw(CubsPage, at("cubs/made"));
    await settle();
    expect(v.target.querySelector("#made-later")?.textContent).toContain("Kranto cannot build a feature from a sentence yet");
    expect(v.target.querySelector(".made .btn.primary")).toBeNull();               // nothing to press that cannot work
    v.done();
  });

  it("lists what every cub asks, one line each with its own button and the one dialog; its old address lands there", async () => {
    stub({ answer: {} });
    hosted();
    answering(READS());
    const { target, done } = await draw(CubsPage, at("cubs/tickets"));
    await settle();
    const rows = [...target.querySelectorAll("[aria-labelledby=cubs-approvals] .ask-row")];
    expect(rows.length).toBe(2);
    expect(rows[0]!.textContent).toContain("A post about the pick · practice: nothing is sent");
    expect(rows[0]!.querySelector("button")?.textContent).toBe("Post toot");
    (rows[0]!.querySelector('[data-act="ask-open"]') as HTMLButtonElement).click();
    expect(dlg.now?.comp).toBe(AskDialog);
    expect((dlg.now?.props as { id: number }).id).toBe(41);
    done();
  });

  it("checks a pasted manifest and draws it in words; a pasted one is never installed", async () => {
    const L = stub({ answer: { ok: true, trust: "unreviewed", installable: false, why: "a pasted cub.yaml is only checked: add the cub from its folder or its git URL to install it",
      manifest: { id: "toot", title: "Mastodon", version: "0.4.2", api: "cub/1", says: "A card as a post you approve.", reads: ["ideas"], requests: ["post.mastodon"] } } });
    hosted();
    answering(READS());
    const { target, done } = await draw(CubsPane, at("cubs", "check"));
    await settle();
    const ta = target.ownerDocument.querySelector("#cub-yaml") as HTMLTextAreaElement;
    ta.value = "id: toot";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.ownerDocument.querySelector("#cub-check") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/cubs/check", { text: "id: toot" });
    const sheet = target.ownerDocument.querySelector("#cubs-sheet")!;
    expect(sheet.textContent).toContain("Nobody at Kranto has read this code.");
    expect(sheet.querySelector("#cub-will")?.textContent).toContain("Asks youpost mastodon");
    expect(sheet.getAttribute("data-title")).toBe("Add a feature");                   // one sheet, one path
    expect((sheet.querySelector("#cub-check-fold") as HTMLDetailsElement).open).toBe(true);
    expect(sheet.querySelector("#cub-check-fold .foot .btn.primary")).toBeNull();
    expect(sheet.querySelector("#cub-install-later")?.textContent).toContain("folder or its git URL");
    done();
  });
});

describe("Add a feature", () => {
  const READY: CubJob = { id: "j1", kind: "add", state: "awaiting_confirm", needs: "house", cub: {
    id: "toot", title: "Toot the pick", version: "1.0.0", trust: "unreviewed", sha: "0123456789abcdef", source: { kind: "git", url: "https://github.com/you/toot" },
    inventory: { files: 4, bytes: 9000, licence: "MIT", findings: [{ level: "warn", text: "imports socket: it has no network, so this does nothing, or hides a try" }] },
    words: [["Cub", "Toot the pick 1.0.0 (toot)"], ["Asks you", "Publish this post (post.mastodon), at most 5 a day"], ["It cannot", "read your files"]] } };
  function server(answers: Record<string, unknown>) {
    const L = stub();
    const calls: [string, unknown][] = [];
    L.api.mockImplementation(async (path: string, body?: unknown) => {
      calls.push([path, body]);
      const a = answers[path];
      return typeof a === "function" ? (a as () => unknown)() : a ?? {};
    });
    return { L, calls };
  }
  async function sheet(every = 0) {
    const done = vi.fn();
    const target = document.createElement("div");
    document.body.append(target);
    const c = mount(AddCub, { target, props: { done, every } });
    await settle();
    return { target, done, end: () => { void unmount(c); target.remove(); } };
  }
  const type = (el: Element | null, v: string) => { (el as HTMLInputElement).value = v; el!.dispatchEvent(new Event("input", { bubbles: true })); };

  it("reads a git URL at a ref, polls the job, and draws it in words with its findings", async () => {
    let n = 0;
    const { calls } = server({ [`${CUBS_API}/fetch`]: { job: { id: "j1", kind: "add", state: "queued" } },
      [`${CUBS_API}/jobs/j1`]: () => (++n < 2 ? { id: "j1", kind: "add", state: "fetching" } : READY) });
    const { target, end } = await sheet();
    type(target.querySelector("#cub-source"), "https://github.com/you/toot");
    await settle();
    type(target.querySelector("#cub-ref"), "v1.0.0");
    await settle();
    (target.querySelector("#cub-fetch") as HTMLButtonElement).click();
    for (let i = 0; i < 6; i++) await settle();
    expect(calls[0]).toEqual([`${CUBS_API}/fetch`, { source: "https://github.com/you/toot", ref: "v1.0.0" }]);
    expect(calls.filter(([p]) => p === `${CUBS_API}/jobs/j1`).length).toBe(2);
    expect(target.textContent).toContain("Nobody at Kranto has read this code.");
    expect(target.querySelector("#cub-words")?.textContent).toContain("Asks youPublish this post (post.mastodon), at most 5 a day");
    expect(target.querySelector("#cub-findings")?.textContent).toContain("imports socket");
    end();
  });

  it("installs (in practice) only after the house confirm, then opens the cub", async () => {
    const { calls } = server({ [`${CUBS_API}/fetch`]: { job: READY }, [`${CUBS_API}/toot/install`]: { cub: { id: "toot" } } });
    const { target, done, end } = await sheet();
    type(target.querySelector("#cub-source"), "/home/user/cubs/toot");
    await settle();
    expect(target.querySelector("#cub-ref")).toBeNull();                       // a folder takes no ref
    (target.querySelector("#cub-fetch") as HTMLButtonElement).click();
    for (let i = 0; i < 3; i++) await settle();
    (target.querySelector("#cub-install") as HTMLButtonElement).click();
    expect(calls.some(([p]) => p.endsWith("/install"))).toBe(false);             // not before the confirm
    expect(document.getElementById("dlg")?.textContent).toContain("Install Toot the pick?");
    (document.getElementById("dlg-ok") as HTMLButtonElement).click();
    for (let i = 0; i < 3; i++) await settle();
    expect(calls).toContainEqual([`${CUBS_API}/toot/install`, { job: "j1", confirm: true }]);
    expect(done).toHaveBeenCalledWith("toot");
    end();
  });

  it("says why a fetch failed and lets you try again", async () => {
    server({ [`${CUBS_API}/fetch`]: { job: { id: "j2", kind: "add", state: "failed", error: "src/fast.so is a native library or program" } } });
    const { target, end } = await sheet();
    type(target.querySelector("#cub-source"), "/home/user/cubs/bad");
    await settle();
    (target.querySelector("#cub-fetch") as HTMLButtonElement).click();
    for (let i = 0; i < 3; i++) await settle();
    expect(target.querySelector("#cub-job-error")?.textContent).toContain("native library");
    (target.querySelector("#cub-again") as HTMLButtonElement).click();
    await settle();
    expect(target.querySelector("#cub-source")).not.toBeNull();
    end();
  });
});
