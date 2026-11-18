// Settings › <Feature> (D-1 to D-3): every feature's and cub's own page, generated
// from its manifest. Moved here from the cub page's Settings and About sheets (cub.svelte.test.ts),
// every claim kept: by hand shown not edited, sensitive behind the house confirm, the topic picker
// for a key of type topics, the manifest in words, a kind live only after the house confirm, an
// update staged from a terminal, Stop and Resume, no controls for a built-in feature.
import { mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import DialogHost from "../../ui/DialogHost.svelte";
import { closeDialog, dlg } from "../../ui/dialog.svelte";
import { FEATURES_API, type FeatureRow, type Features, type SettingRow } from "../../features/index";
import { SHELL_API } from "../../features/shell";
import { cubPath } from "../../features/cub";
import FeaturePage from "./FeaturePage.svelte";
import FeaturePane from "./FeaturePane.svelte";
import { featureLine, groupsOf, stateOf, valueWords } from "./feature";

const NOW = new Date().toISOString();
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
const key = (k: string, o: Partial<SettingRow> = {}): SettingRow => ({ key: k, value: null, type: "int", default: null, choices: [], lo: null, hi: null, words: "", sensitive: false, by_hand: false, per_topic: false, ...o });
const digest = (o: Partial<FeatureRow> = {}): FeatureRow => ({
  id: "digest", title: "Digest", says: "Proposals, in practice.", version: "1.0.0", trust: "first-party",
  enabled: true, mode: "practice", tickets_open: 1, last_run: { kind: "digest.scan", status: "ok", finished_at: NOW },
  spend: { month_usd: 0.42, today_usd: 0, calls: 3 },
  settings: [
    key("digest.enabled", { value: true, type: "bool", default: false, words: "Digest (practice)", sensitive: true }),
    key("digest.max_proposals_day", { value: 3, default: 3, lo: 1, hi: 10, words: "proposals a day at most", group: "Proposals" }),
    key("digest.min_price", { value: 7, type: "float", default: 5, words: "no item under", group: "Items" }),
    key("digest.live.enabled", { value: false, type: "bool", default: false, words: "live sending may be switched on", by_hand: true, advanced: true }),
    key("digest.monthly_usd", { type: "usd", words: "Digest's model calls a month (null: no cap)" }),
  ],
  manifest: { reads: ["topics", "briefs"], requests: ["book.place"], broker: { newsletter: ["emails.get"] }, spend: { caps: { "digest.monthly_usd": "Digest a month" } },
    actions: [], ui: { nav: [], cards: {}, kind: "watch", glyph: "up", lists: [] } },
  ...o,
});
const FEATURES = (...fs: FeatureRow[]): Features => ({ api: "kranto-mod/1", reads: [], request_kinds: ["book.place", "post.mastodon"], features: fs,
  request_schemas: { "post.mastodon": { title: "Publish this post", doors: ["ui"], page_only: true, performs: false, expires_hours: 48, per_day: 5, fields: [] } } });
const shell = { home: true, pins: [], hidden: [], needs_cap: 3, new_cap: 4, pins_max: 6, cubs: [{ id: "toot", trust: "owner", pinned: true, place: 0, hidden: false, needs_you: true, new: false }] };
const toot = digest({ id: "toot", title: "Toot the pick", trust: "owner", mode: "drafts only", version: "1.1.0",
  settings: [key("toot.tone", { type: "enum", value: "plain", default: "plain", choices: ["plain", "warm"], words: "the post's tone", group: "The post" })],
  manifest: { requests: ["post.mastodon"], broker: { mastodon: ["statuses.draft"] }, actions: [], ui: { nav: [], cards: {}, lists: [] } } });
const detail = (o: Record<string, unknown> = {}) => ({ id: "toot", title: "Toot the pick", version: "1.1.0", trust: "owner", state: "installed", enabled: true,
  mode: "drafts only", live: [], tree_ok: true, paused: null, update: null, grants: { requests: ["post.mastodon"] }, words: [], inventory: null,
  spend: { month_usd: 0, cap_usd: null, calls_today: 0, calls_per_day: 200 }, ...o });
const texts = (t: Element, sel: string) => [...t.querySelectorAll(sel)].map((x) => x.textContent?.trim());

let host: ReturnType<typeof mount> | null = null;
beforeEach(() => { host = mount(DialogHost, { target: document.body }); });
afterEach(() => {
  closeDialog();
  if (host) void unmount(host);
  document.body.replaceChildren();
  ui.facts = null;
  dlg.now = null;
});
const dialog = () => document.getElementById("dlg")!;

describe("Settings › <Feature>, generated from its manifest", () => {
  it("is On and off, its groups, Advanced, Accounts it uses, Spend and About, in the eight pages' shape", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePage, where("settings/digest"));
    await settle();
    expect(texts(target, ".grp h2")).toEqual(["On and off", "Proposals", "Items", "Advanced", "Accounts it uses", "Spend", "About"]);
    // a group named by no key is "<Feature>'s settings"; a cap is under Spend, never in a group
    expect(target.querySelector('[data-sel="edigest.monthly_usd"]')?.closest(".grp")?.querySelector("h2")?.textContent).toBe("Spend");
    expect(target.querySelector('[data-sel="edigest.min_price"] .c-meta')?.textContent).toBe("7");
    expect(target.querySelector("[aria-labelledby=fs-accounts] .r-title")?.textContent).toBe("Your newsletter platform");
    expect(target.querySelector("[aria-labelledby=fs-accounts] a")?.getAttribute("href")).toBe("#/settings/accounts");
    done();
  });

  it("shows a key written by hand, never as a field, and asks the house confirm for a sensitive one", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePage, where("settings/digest"));
    await settle();
    const live = target.querySelector('[data-sel="edigest.live.enabled"]');
    expect(live?.querySelector("button, input, select")).toBeNull();
    expect(live?.textContent).toContain("written by hand");
    expect(live?.closest(".grp")?.querySelector("h2")?.textContent).toBe("Advanced");
    (target.querySelector("#k-digest\\.enabled") as HTMLButtonElement).click();
    await settle();
    expect(dialog().textContent).toContain("Change Digest (practice)?");                    // the house confirm first
    done();
    // its form, in the sheet: the field with its range, Save with Undo
    const L = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell });
    const p = await draw(FeaturePane, where("settings/digest", "edigest.max_proposals_day"));
    await settle();
    const input = p.target.querySelector("#fs-k-digest\\.max_proposals_day") as HTMLInputElement;
    expect(input.getAttribute("max")).toBe("10");
    input.value = "5";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (p.target.querySelector("#fs-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/digest/settings", { key: "digest.max_proposals_day", value: 5, confirm: undefined });
    expect(L.toast.mock.calls[0]![0]).toBe("Saved: Proposals a day at most: 5. From the next run.");
    expect(typeof L.toast.mock.calls[0]![1]).toBe("function");                         // Undo
    p.done();
  });

  it("draws the core's topic picker for a key of type topics, never a field of ids (CON L5)", async () => {
    const L = stub({ host: { topics: [{ id: 1, name: "Local-first" }, { id: 2, name: "AI tooling" }, { id: 13, name: "Robotics" }] } });
    hosted();
    const row = key("digest.topics", { value: [], type: "topics", default: [], words: "the topics it reads" });
    answering({ [FEATURES_API]: FEATURES(digest({ settings: [row] })), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePane, where("settings/digest", "edigest.topics"));
    await settle();
    const picker = target.querySelector("#fs-k-digest\\.topics");
    expect(picker?.querySelector(".tp-w")?.textContent).toBe("Every topic (3)");
    expect([...(picker?.querySelectorAll("button.chip") || [])].map((b) => b.textContent)).toEqual(["Local-first", "AI tooling", "Robotics"]);
    expect(target.querySelector("input")).toBeNull();
    (picker?.querySelector('[data-topic="13"]') as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/f/digest/settings", { key: "digest.topics", value: [13], confirm: undefined });
    done();
  });

  it("says the other line's default when a setting's stable default keeps the old behaviour (REL)", async () => {
    stub();
    hosted();
    const row = key("digest.layout", { type: "enum", value: null, default: "classic", choices: ["new", "classic"], words: "the layout", line: "stable", default_other: "new" });
    answering({ [FEATURES_API]: FEATURES(digest({ settings: [row] })), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePane, where("settings/digest", "edigest.layout"));
    expect(target.querySelector("#fs-other-line")?.textContent).toBe("Nightly's default is new: stable keeps classic until it is turned on for stable.");
    done();
    answering({ [FEATURES_API]: FEATURES(digest({ settings: [{ ...row, line: "nightly", default: "new", default_other: "classic" }] })), [SHELL_API]: shell });
    const n = await draw(FeaturePane, where("settings/digest", "edigest.layout"));
    expect(n.target.querySelector("#fs-other-line")?.textContent).toBe("Stable's default is classic: stable installs keep it until it is turned on for stable.");
    n.done();
    answering({ [FEATURES_API]: FEATURES(digest({ settings: [key("digest.layout", { type: "enum", default: "new", choices: ["new"] })] })), [SHELL_API]: shell });
    const none = await draw(FeaturePane, where("settings/digest", "edigest.layout"));
    expect(none.target.querySelector("#fs-other-line")).toBeNull();          // one default on both lines
    none.done();
  });

  it("says the manifest in words under About", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePane, where("settings/digest", "eabout"));
    await settle();
    expect(target.querySelector("#fs-perms")?.textContent).toContain("Asks youbook place"); // the kind in words, not its id (QA B10)
    expect(target.textContent).toContain("It cannot pay, post, trade or send by itself");
    done();
  });
});

describe("an installed cub's Settings page", () => {
  it("has the cub's switch, its kinds dry or live, the core's keys and its caps", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail() });
    const { target, done } = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(texts(target, ".grp h2")).toEqual(["On and off", "The post", "The core's keys", "Accounts it uses", "Spend", "About"]);
    expect(target.querySelector("#fs-enabled")?.getAttribute("aria-checked")).toBe("true");
    expect(target.querySelector("#k-needs")?.getAttribute("aria-checked")).toBe("true");
    expect(target.querySelector("#k-new")?.getAttribute("aria-checked")).toBe("false");
    expect(target.querySelector('[data-sel="ecap:monthly_usd"] .c-meta')?.textContent).toBe("no cap");
    expect(target.querySelector("[aria-labelledby=fs-accounts] .r-title")?.textContent).toBe("Mastodon (posting)");
    done();
  });

  it("turns a kind live only after the house confirm, and dry at once", async () => {
    const L = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail() });
    let v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    const sw = v.target.querySelector("#live-post\\.mastodon") as HTMLButtonElement;
    expect(sw.textContent).toBe("Practice");
    sw.click();
    expect(L.api).not.toHaveBeenCalled();
    expect(dialog().textContent).toContain("Send for real from Toot the pick?");
    (dialog().querySelector("#dlg-ok") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/cubs/toot/live", { kind: "post.mastodon", confirm: true });
    v.done();
    const L2 = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail({ live: ["post.mastodon"] }) });
    v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(v.target.querySelector("#live-post\\.mastodon")?.textContent).toBe("For real");
    (v.target.querySelector("#live-post\\.mastodon") as HTMLButtonElement).click();
    await settle();
    expect(L2.api).toHaveBeenCalledWith("/api/cubs/toot/dry", { kind: "post.mastodon" });
    v.done();
  });

  it("offers an update staged from a terminal under About, without an action", async () => {
    const job = { id: "j1", kind: "update", state: "awaiting_confirm", needs: "house",
      cub: { id: "toot", title: "Toot the pick", version: "1.2.0", trust: "owner", sha: null, source: { kind: "folder" },
        inventory: { files: 1, bytes: 1, licence: "MIT", findings: [] }, words: [],
        delta: { added: { requests: ["post.topic"] }, removed: {}, grown: true }, diff: { counts: { changed: 1, added: 0, removed: 0 } } } };
    const up = { version: "1.2.0", sha: null, job: "j1", needs: "house", adds: ["requests: post.topic"] };
    const L = stub({ answer: job });
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail({ update: up }) });
    let v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/cubs/jobs/j1");
    expect(v.target.querySelector("#cub-apply")?.textContent).toBe("Update to 1.2.0");
    expect(v.target.querySelector("#cub-update")).toBeNull();
    (v.target.querySelector("#cub-apply") as HTMLButtonElement).click();
    expect(dialog().textContent).toContain("It may now: requests: post.topic.");
    v.done();
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail() });
    v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(v.target.querySelector("#cub-update")?.textContent).toBe("Look for an update");
    v.done();
  });

  // an installed feature recorded a folder that no longer exists and said nothing
  it("says a feature's source is gone, with the command that points it elsewhere", async () => {
    stub();
    hosted();
    // Kranto's own words for a feature it ships (core/cubs/updates.py's gone_words)
    const fix = 'kranto cub source toot "$(kranto paths examples)/toot"';
    const gone = { path: "/x/old-install/cubs/examples/toot", fix,
      words: `Its source folder is gone (/x/old-install/cubs/examples/toot); it gets no updates. Point it at this Kranto's own copy: ${fix}` };
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail({ source_gone: gone }) });
    let v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(v.target.querySelector("#cub-source-gone")?.textContent).toBe(gone.words);
    v.done();
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail() });
    v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(v.target.querySelector("#cub-source-gone")).toBeNull();          // an older server: none
    v.done();
  });

  it("stops behind a confirm, resumes at once, and has no controls for a built-in feature", async () => {
    const L = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail() });
    let v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    (v.target.querySelector("#fs-stop") as HTMLButtonElement).click();
    expect(L.api).not.toHaveBeenCalled();
    (dialog().querySelector("#dlg-ok") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/cubs/toot/stop", {});
    v.done();
    const L2 = stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell, [cubPath("toot")]: detail({ state: "paused", paused: { note: "stopped by the owner" } }) });
    v = await draw(FeaturePage, where("settings/toot"));
    await settle();
    expect(v.target.querySelector("#cub-state")?.textContent).toContain("stopped by the owner");
    (v.target.querySelector("#fs-resume") as HTMLButtonElement).click();
    await settle();
    expect(L2.api).toHaveBeenCalledWith("/api/cubs/toot/resume", {});
    v.done();
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(digest()), [SHELL_API]: shell });
    v = await draw(FeaturePage, where("settings/digest"));
    await settle();
    expect(v.target.querySelector("#cub-controls")).toBeNull();
    expect(v.target.querySelector("#k-needs")).toBeNull(); // the core's keys are a cub's
    v.done();
  });

  it("says a feature that is not here, in words", async () => {
    stub();
    hosted();
    answering({ [FEATURES_API]: FEATURES(toot), [SHELL_API]: shell });
    const { target, done } = await draw(FeaturePage, where("settings/nope"));
    await settle();
    expect(target.textContent).toContain("There is no feature called nope on this Kranto.");
    done();
  });
});

describe("the page as data", () => {
  it("groups the keys, words the values and the states, and says a feature's state in one line", () => {
    const g = groupsOf(digest());
    expect(g.on?.key).toBe("digest.enabled");
    expect(g.groups.map((x) => [x.word, x.rows.map((r) => r.key)])).toEqual([["Proposals", ["digest.max_proposals_day"]], ["Items", ["digest.min_price"]]]);
    expect(g.advanced.map((r) => r.key)).toEqual(["digest.live.enabled"]);
    expect(g.caps.map((r) => r.key)).toEqual(["digest.monthly_usd"]);
    expect(groupsOf(digest({ settings: [key("digest.x", { words: "x" })] })).groups[0]!.word).toBe("Digest's settings");
    expect(valueWords(key("a.b", { type: "usd" }))).toBe("no cap");
    expect(valueWords(key("a.b", { type: "topics", value: [13] }), [{ id: 13, name: "Robotics" }])).toBe("Robotics");
    expect(valueWords(key("a.b", { type: "list", value: [] }))).toBe("none");
    expect(stateOf(key("a.b", { value: 3, default: 3 }))[2]).toBe("Default");
    expect(stateOf(key("a.b", { value: 4, default: 3 }))[2]).toBe("Set");
    expect(stateOf(key("a.b", { by_hand: true }))[2]).toBe("By hand");
    expect(featureLine(digest())).toMatch(/^on · practice · ran .* ok · \$0\.42 this month$/);
    expect(featureLine(toot)).toMatch(/^on · drafts only · 1\.1\.0/);
  });
});
