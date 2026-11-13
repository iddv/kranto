import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../lib/app";
import { connect, ui } from "../lib/shell.svelte";
import Header from "./Header.svelte";
import ListHead from "./ListHead.svelte";
import Nav from "./Nav.svelte";
import Palette from "./Palette.svelte";
import StatusBar from "./StatusBar.svelte";
import PreviewStrip from "./PreviewStrip.svelte";
import { ACT_PATH, SEEN_KEY } from "../lib/activity";
import { activityOf, run } from "../lib/activity.fixtures";
import { drop, put } from "../lib/reads.svelte";

function facts(o: { header?: Partial<Facts["header"]>; head?: Partial<Facts["head"]>; hint?: Partial<Facts["hint"]>; door?: Facts["door"] } = {}): Facts {
  return {
    header: { host: { paused: false, running: null, next: null }, update: null, pauses: "reading sources and writing ideas",
              theme: { name: "Kranto", dark: false }, ...o.header },
    nav: { here: "ideas", topic: null, rows: [
      { head: "Desk", to: "", w: "" },
      { to: "needs", w: "Needs you", key: "g t", n: 3, hot: true },
      { head: "Topics", to: "topics", w: "", add: "topics/new" },
      { to: "topics/2", w: "local-first", twist: "t2", open: true, n: 4, tone: "new" },
      { to: "topics/2/evidence", w: "Evidence", sub: true },
      { head: "Cards", to: "", w: "" },
      { to: "ideas", w: "Ideas", key: "g i", n: 2, tone: "wait" },
      { head: "Settings", to: "settings", w: "" },
      { to: "settings", w: "Sources", key: "g s" },
    ] },
    bar: { word: { icon: "check", colour: "green", text: "Healthy" }, why: null, used: { text: "1.2M tokens today", title: "1 in · 2 out" },
           cells: ["ingest 09:00 ok"], size: "3 sources · 1 topic · 10 observations", preview: null },
    hint: { rows: true, grade: true, tick: false, term: false, review: false, sections: true, ...o.hint },
    head: { paused: null, signin: false, flash: null, ...o.head },
    door: o.door ?? null,
  };
}
function draw(C: typeof Header) {
  const target = document.createElement("div");
  const app = mount(C, { target });
  flushSync();
  return { target, app };
}
afterEach(() => {
  ui.facts = null;
  ui.chord = null;
  ui.split = null;
  connect(null);
});

describe("the header", () => {
  // one item for both lanes: from the lanes' facts until the activity
  // read arrives, then from it; it opens Activity
  it("says what runs in one item, and opens Activity", () => {
    ui.facts = facts({ header: { host: { paused: false, running: "ingest", next: null } } });
    const { target, app } = draw(Header);
    const a = target.querySelector("#hd-activity") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("#/activity");
    expect(a.dataset.state).toBe("running");
    // the word alone; what runs is its tooltip
    expect(a.textContent).toBe("1 running");
    expect(a.getAttribute("aria-label")).toContain("reading your sources");
    expect(target.querySelector(".queued")).toBeNull();
    expect(target.querySelector("#pause")?.getAttribute("title")).toBe("Pause everything: stops reading sources and writing ideas.");
    expect(target.textContent).not.toContain("Idle");
    expect(target.textContent).not.toMatch(/\b[Bb]uild/);
    expect(target.querySelector("#hd-watch")).toBeNull(); // the two lane words are gone
    unmount(app);
  });

  it("says Paused, and Resume; without the server nothing is paused", () => {
    ui.facts = facts({ header: { host: { paused: true, running: null, next: null } } });
    const { target, app } = draw(Header);
    expect(target.querySelector("#hd-activity")?.textContent).toBe("Paused");
    expect(target.querySelector("#hd-loop-down")).toBeNull();
    expect(target.querySelector("#pause")?.textContent).toBe("Resume");
    expect(target.querySelector("#pause")?.getAttribute("title")).toBe("Resume reading sources and writing ideas");
    ui.facts = facts({ header: { host: null } });
    flushSync();
    expect(target.querySelector("#hd-activity")?.textContent).toBe("Quiet");
    unmount(app);
  });

  it("says reading now with how far, or Quiet and when next, then the update on its own", () => {
    ui.facts = facts({ header: { host: { paused: false, running: "ingest", next: null, reading: "source 3 of 8 · 12 of 40 items · 5 kept so far" },
                                 update: { icon: "dot", colour: "blue", word: "Update", detail: null, title: "" } } });
    const { target, app } = draw(Header);
    const ids = [...target.querySelectorAll(".lanes .hd-st")].map((x) => x.id);
    expect(ids).toEqual(["hd-activity", "hd-update"]);
    expect(target.querySelector("#hd-activity")?.textContent).toBe("1 running");
    expect(target.querySelector("#hd-activity")?.getAttribute("aria-label")).toContain("source 3 of 8");
    ui.facts = facts({ header: { host: { paused: false, running: null, next: new Date(Date.now() + 3600e3).toISOString() } } });
    flushSync();
    expect(target.querySelector("#hd-activity")?.textContent).toBe("Quiet");
    expect(target.querySelector("#hd-activity")?.getAttribute("aria-label")).toMatch(/next: reading your sources at (\w{3} )?\d\d:\d\d/);
    expect(target.querySelector("#hd-activity")?.getAttribute("title")).toMatch(/^Nothing is running\. What Kranto is doing/);
    expect(target.querySelector(".lanes")?.textContent).not.toContain("Idle");
    unmount(app);
  });

  it("draws the activity read: its count and first run, a red dot until Activity is opened", () => {
    localStorage.removeItem(SEEN_KEY);
    put(ACT_PATH, activityOf({ running: [run({ title: "Writing the News brief", words: "Collecting Robotics' history · arXiv" }), run({ id: "afk:x", title: "Reading your sources" })] }));
    ui.facts = facts();
    const { target, app } = draw(Header);
    expect(target.querySelector("#hd-activity")?.textContent).toBe("2 running");
    put(ACT_PATH, activityOf({ recent: [run({ state: "failed", finished: "2026-10-23T01:00:00Z", error: "exit 137" })] }));
    flushSync();
    const a = target.querySelector("#hd-activity") as HTMLElement;
    expect(a.dataset.state).toBe("failed");
    expect(a.textContent).toContain("Quiet · 1 failed");
    localStorage.setItem(SEEN_KEY, "2026-10-23T02:00:00Z"); // Activity was opened since
    put(ACT_PATH, activityOf({ recent: [run({ state: "failed", finished: "2026-10-23T01:00:00Z" })] }));
    flushSync();
    expect((target.querySelector("#hd-activity") as HTMLElement).dataset.state).toBe("quiet");
    drop(ACT_PATH, true);
    unmount(app);
  });

  it("offers an update, says its step while it runs, and a rollback", () => {
    ui.facts = facts({ header: { update: { icon: "dot", colour: "blue", word: "Update", detail: "0.3.73 → 0.3.74", title: "What's new in 0.3.74:\nFaster" } } });
    const { target, app } = draw(Header);
    const pill = target.querySelector("#hd-update") as HTMLAnchorElement;
    expect(pill.getAttribute("href")).toBe("#/settings/updates");
    expect(pill.textContent).toBe("Update");                                      // no version strings in the bar (R5)
    expect(pill.getAttribute("title")).toBe("What's new in 0.3.74:\nFaster: 0.3.73 → 0.3.74");
    ui.facts = facts({ header: { update: { icon: "warn", colour: "red", word: "Update rolled back", detail: null, title: "the new version did not answer" } } });
    flushSync();
    expect(target.querySelector("#hd-update")?.textContent).toBe("Update rolled back");
    expect(target.querySelector("#hd-update .word")).toBeNull();
    ui.facts = facts();
    flushSync();
    expect(target.querySelector("#hd-update")).toBeNull();
    unmount(app);
  });

  it("presses Pause and the theme through the app", () => {
    const L = { togglePause: vi.fn(), setTheme: vi.fn(), render: vi.fn(), toast: vi.fn() };
    window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never; // a light device
    connect(L as never);
    ui.facts = facts();
    const { target, app } = draw(Header);
    (target.querySelector("#pause") as HTMLButtonElement).click();
    expect(L.togglePause).toHaveBeenCalledWith(target.querySelector("#pause"), true);
    (target.querySelector("#theme") as HTMLButtonElement).click();
    expect(L.setTheme).toHaveBeenCalledWith("dark");
    expect(L.toast).toHaveBeenCalledWith("Dark, until you switch back");
    expect(L.render).toHaveBeenCalled();
    // ◐ again, back to the device's scheme: Auto, never a fixed Light that outlives the device's
    // own switch at night (QA B18, the owner's B2)
    document.documentElement.setAttribute("data-theme", "dark");
    (target.querySelector("#theme") as HTMLButtonElement).click();
    expect(L.setTheme).toHaveBeenLastCalledWith("auto");
    expect(L.toast).toHaveBeenLastCalledWith("Auto: follows your device (light now)");
    document.documentElement.removeAttribute("data-theme");
    unmount(app);
  });
});

describe("the navigator", () => {
  it("is one tree, keys in the tooltips, the current entry marked", () => {
    ui.facts = facts();
    const { target, app } = draw(Nav);
    const on = target.querySelector(".ni.on a") as HTMLAnchorElement;
    expect(on.getAttribute("href")).toBe("#/ideas");
    expect(on.getAttribute("aria-current")).toBe("page");
    expect(on.getAttribute("title")).toBe("Ideas (g i)");
    expect(target.querySelector(".ni.on .ct")?.className).toBe("ct wait");
    expect(target.querySelectorAll(".ng").length).toBe(4);
    expect(target.querySelector("[role=tablist]")).toBeNull();
    expect(target.querySelector("kbd")).toBeNull();
    const twist = target.querySelector("button.tw") as HTMLButtonElement;
    expect(twist.getAttribute("aria-expanded")).toBe("true");
    expect(twist.getAttribute("aria-label")).toBe("Collapse local-first");
    expect(target.querySelector(".ni.sub a")?.textContent).toBe("Evidence");
    unmount(app);
  });
});

describe("the status bar", () => {
  it("says the service in a word, and the keys only while a chord or a split is held (D-6: the tokens are Spend's)", () => {
    ui.facts = facts();
    const { target, app } = draw(StatusBar);
    expect(target.querySelector(".cell.health")?.textContent).toBe("Healthy");
    expect(target.querySelector("#tokens-today")).toBeNull();
    expect(target.querySelector("#key-hint")).toBeNull();
    expect(target.textContent).not.toMatch(/\$\d/);
    ui.chord = "g";
    flushSync();
    expect(target.querySelector("#key-hint")?.textContent).toMatch(/^g then: h Home · w Watch · t Needs you/);
    ui.chord = null;
    ui.split = "split-nav";
    flushSync();
    expect(target.querySelector("#key-hint")?.textContent).toContain("enter icons");
    unmount(app);
  });

  it("says why it is not Healthy after the word, and both open that run's trace", () => {
    const f = facts(), why = { text: "The last read of your sources failed at 12:42: OpenRouter sent an empty reply", href: "#/afk/abc/trace" };
    ui.facts = { ...f, bar: { ...f.bar, word: { icon: "warn", colour: "amber", text: "Degraded" }, why } };
    const { target, app } = draw(StatusBar);
    const word = target.querySelector<HTMLAnchorElement>(".cell.health")!, line = target.querySelector<HTMLAnchorElement>("#health-why")!;
    expect(word.textContent).toBe("Degraded");
    expect(line.textContent).toBe(why.text);
    expect(line.getAttribute("href")).toBe("#/afk/abc/trace");
    expect(word.getAttribute("href")).toBe("#/afk/abc/trace");
    expect(word.title).toBe(why.text);
    expect(line.classList.contains("wide")).toBe(false); // not hidden in New or on the phone
    unmount(app);
    ui.facts = facts();
    const healthy = draw(StatusBar);
    expect(healthy.target.querySelector("#health-why")).toBe(null);
    unmount(healthy.app);
  });

  // the preview: a second Kranto on a copy of the owner's data says so first, in New
  // and on the phone (where the status bar gives way to the doors, the strip above them says it)
  it("says it is the preview and nothing is sent, first, and on the phone above the doors", () => {
    const line = "Preview: a copy of your data from 11 November. Nothing is sent.";
    const f = facts();
    ui.facts = { ...f, bar: { ...f.bar, preview: line } };
    const { target, app } = draw(StatusBar);
    const cell = target.querySelector<HTMLElement>("#bar-preview")!;
    expect(cell.textContent).toBe(line);
    expect(target.firstElementChild).toBe(cell);
    expect(cell.classList.contains("wide")).toBe(false);
    unmount(app);
    const strip = draw(PreviewStrip);
    expect(strip.target.querySelector("#preview-strip")?.textContent).toBe(line);
    expect(strip.target.querySelector("#preview-strip")?.getAttribute("role")).toBe("status");
    unmount(strip.app);
    ui.facts = facts();
    const live = draw(StatusBar), none = draw(PreviewStrip);
    expect(live.target.querySelector("#bar-preview")).toBe(null);
    expect(none.target.querySelector("#preview-strip")).toBe(null);
    unmount(live.app);
    unmount(none.app);
  });
});

describe("the palette", () => {
  it("lets go of the focus as it closes, so the next key is a key, not typing", () => {
    const proto = HTMLDialogElement.prototype as unknown as { showModal?: () => void; close: () => void };
    const had = proto.showModal;
    proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); }; // the close event comes later
    connect({ palItems: () => [{ g: "Commands", title: "Go to Ideas", score: 1, go: "#/ideas" }], api: vi.fn() } as never);
    ui.facts = facts();
    const target = document.createElement("div");
    document.body.append(target);
    const app = mount(Palette, { target });
    ui.palette = { text: "" };
    flushSync();
    const q = target.querySelector("#pal-q") as HTMLInputElement;
    expect(document.activeElement).toBe(q);
    q.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect((target.querySelector("#pal") as HTMLDialogElement).open).toBe(false);
    expect(document.activeElement).not.toBe(q);
    unmount(app);
    target.remove();
    ui.palette = null;
    if (had) proto.showModal = had;
  });

  it("opens a row with enter, runs its action with ⌘enter, runs a command, and asks the server's search after the typing stops", async () => {
    vi.useFakeTimers();
    const proto = HTMLDialogElement.prototype as unknown as { showModal?: () => void; close: () => void };
    const had = proto.showModal;
    proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    const act = vi.fn(), run = vi.fn();
    const found = { query: "plo", results: [{ kind: "observation", id: 5, title: "Plot charts" }] };
    const palItems = vi.fn((q: string, srv: unknown) => [
      { g: "Ideas", title: "Plotkeeper", score: 3, go: "#/ideas/3", act, actWord: "Pass" },
      { g: "Commands", title: "Pause", score: 1, run },
      ...(srv ? [{ g: "Evidence", title: "Plot charts", score: 1, go: "#/library/o/5" }] : []),
    ].filter((x) => !q || x.title.toLowerCase().includes(q) || x.g === "Evidence"));
    const api = vi.fn(async () => found);
    connect({ palItems, api } as never);
    ui.facts = facts();
    const target = document.createElement("div");
    document.body.append(target);
    const app = mount(Palette, { target });
    const open = (text: string) => { ui.palette = { text }; flushSync(); return target.querySelector("#pal-q") as HTMLInputElement; };
    const key = (q: HTMLInputElement, key: string, o: KeyboardEventInit = {}) => { q.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...o })); flushSync(); };
    let q = open("");
    expect([...target.querySelectorAll("#pal-list h3")].map((h) => h.textContent)).toEqual(["Ideas", "Commands"]);
    expect(target.querySelector("[aria-selected=true] .t")?.textContent).toBe("Plotkeeper"); // the first result is selected
    key(q, "Enter");
    expect(location.hash).toBe("#/ideas/3");
    ui.palette = null;
    q = open("");
    key(q, "Enter", { metaKey: true });
    expect(act).toHaveBeenCalled();
    ui.palette = null;
    q = open("");
    key(q, "ArrowDown");
    expect(target.querySelector("[aria-selected=true] .t")?.textContent).toBe("Pause");
    key(q, "Enter");
    expect(run).toHaveBeenCalled();
    ui.palette = null;
    q = open("plo");
    expect(api).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(200);
    flushSync();
    expect(api).toHaveBeenCalledWith("/api/search?q=plo");
    expect(palItems).toHaveBeenLastCalledWith("plo", found);
    expect([...target.querySelectorAll("#pal-list h3")].map((h) => h.textContent)).toContain("Evidence");
    unmount(app);
    target.remove();
    ui.palette = null;
    if (had) proto.showModal = had;
    vi.useRealTimers();
  });
});

describe("the list's head", () => {
  it("draws nothing when nothing is to be said, so its box takes no room", () => {
    ui.facts = facts();
    const { target, app } = draw(ListHead);
    const h = target.querySelector("#list-h") as HTMLElement;
    // only Svelte's anchors (comments), which :empty ignores: kranto.css pads #list-h:not(:empty)
    expect([...h.childNodes].filter((n) => n.nodeType !== Node.COMMENT_NODE)).toEqual([]);
    expect(h.matches(":empty")).toBe(true);
    unmount(app);
  });

  it("says paused, not signed in and the flash with its Undo", () => {
    const run = vi.fn();
    const signIn = vi.fn(async () => {});
    connect({ signIn } as never);
    ui.facts = facts({ head: { paused: { afk: true, host: true }, signin: true,
                               flash: { text: "Stopped round 4.", kind: "blue", undo: { until: Date.now() + 9000, run } } } });
    const { target, app } = draw(ListHead);
    const lines = target.querySelectorAll("#list-h > .flash");
    expect(lines.length).toBe(3);
    expect(lines[0]?.textContent).toBe("Paused. No source is read and no idea written until you choose Resume.");
    expect(lines[1]?.id).toBe("signin");
    expect(lines[1]?.querySelector(".grow")?.textContent).toBe("Not signed in: this browser can look, not act.");
    expect(lines[1]?.querySelector("button.tip")?.getAttribute("aria-label")).toBe("About signing in"); // its ?, the tip's words
    (target.querySelector("#signin-go") as HTMLButtonElement).click();
    expect(signIn).not.toHaveBeenCalled(); // no code yet: the field takes the cursor
    const code = target.querySelector("#signin-code") as HTMLInputElement;
    code.value = " 1234 ";
    code.dispatchEvent(new Event("input"));
    flushSync();
    (target.querySelector("#signin-go") as HTMLButtonElement).click();
    expect(signIn).toHaveBeenCalledWith("1234", target.querySelector("#signin-go"));
    expect(lines[2]?.textContent).toBe("Stopped round 4. · Undo");
    (target.querySelector("#undo") as HTMLButtonElement).click();
    expect(run).toHaveBeenCalled();
    unmount(app);
  });
});
