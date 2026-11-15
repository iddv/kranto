// An action an assistant prepared (the owner on 2026-10-29: "A
// MASSIVE full text block appears, and it duplicates when you click on Press. No idea what Press
// means"): one line wherever it shows, with the action's own button; its dialog reads it back once,
// the body as markdown, collapsed; the toast says what an assistant just prepared and goes by itself.
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import type { Facts } from "../lib/app";
import { buttonOf, dialogTitle, gone, keyFields, lineOf, longFields, PREPARED_API, preparedHere, toastLine, whyOf, type Prepared } from "../lib/prepared";
import PreparedDialog from "./PreparedDialog.svelte";
import { preparedRows } from "../pages/front/home";
import { ui } from "../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../pages/testing.svelte";
import { closeDialog, dlg } from "./dialog.svelte";
import PreparedLine from "./PreparedLine.svelte";
import PreparedToast from "./PreparedToast.svelte";
import { actPrepared, closeToast, noticePrepared, openPrepared, PTOAST, refusedPrepared, TOAST_MS, toastPrepared } from "./prepared.svelte";

const P = (o: Partial<Prepared> = {}): Prepared => ({ uuid: "p1", verb: "settings.telemetry", title: "Usage reports",
  by_words: "by Claude Code", page: "#/settings/privacy", words: null, fields: { mode: "off" }, state: "open", ...o });

// the owner's own, from live on 2026-10-29: a factory issue with a markdown body of about 20 lines
const BODY = "## What happened\nWhen an assistant prepares something, the item lands in Needs you.\n\n**Live update:** it does not.\n\n- one\n- two\n";
const ISSUE = P({ uuid: "f1", verb: "b.factory_issue", title: "File a Kranto issue", page: "#/needs", button: "File issue",
  fields: { issue: "Needs you doesn't update live when an assistant prepares something", text: BODY, labels: ["feature"], area: "ui", fingerprint: "ui/x" } });

afterEach(() => {
  ui.facts = null;
  location.hash = "";
  closeToast();
  closeDialog();
  vi.useRealTimers();
});

describe("a prepared item", () => {
  it("belongs to the page its route names, open ones only, and never to Needs you or the home", () => {
    const rows = [P(), P({ uuid: "p2", page: "#/settings/privacy?sel=x" }), P({ uuid: "p3", page: "#/topics" }), P({ uuid: "p4", state: "dismissed" }), ISSUE];
    expect(preparedHere(rows, "#/settings/privacy").map((p) => p.uuid)).toEqual(["p1", "p2"]);
    expect(preparedHere(rows, "#/topics?x=1").map((p) => p.uuid)).toEqual(["p3"]);
    expect(preparedHere(null, "#/topics")).toEqual([]);
    // their rows say every item: a line under the head as well would say it twice
    expect(preparedHere(rows, "#/needs")).toEqual([]);
    expect(preparedHere(rows, "#/home")).toEqual([]);
  });

  it("is matched where its page lands, and not on another selection (PAR)", () => {
    const land = (h: string) => h.replace(/^#\/ideas\/([^/?]+)$/, "#/ideas?sel=i$1");
    const rows = [P({ uuid: "b1", page: "#/ideas/12" }), P({ uuid: "b2", page: "#/ideas/13" })];
    expect(preparedHere(rows, "#/ideas?sel=i12", land).map((p) => p.uuid)).toEqual(["b1"]);
    expect(preparedHere(rows, "#/ideas", land).map((p) => p.uuid)).toEqual(["b1", "b2"]);
    expect(preparedHere(rows, "#/ideas/12").map((p) => p.uuid)).toEqual(["b1"]);
    expect(preparedHere(rows, "#/ideas?sel=i12").map((p) => p.uuid)).toEqual([]);
  });

  it("says itself in one line, its button in the action's own words, never its body", () => {
    expect(lineOf(ISSUE)).toBe("File a Kranto issue: Needs you doesn't update live when an assistant prepares something");
    expect(buttonOf(ISSUE)).toBe("File issue");
    expect(buttonOf(P({ title: "Add a topic" }))).toBe("Add topic");      // from an older server
    expect(lineOf(P())).toBe("Usage reports: off");
    expect(lineOf(P({ title: "Archive", fields: {}, subject_kind: "topic", subject_id: "1" }))).toBe("Archive: topic #1");
    expect(keyFields(ISSUE)).toEqual([["labels", "feature"], ["area", "ui"], ["where", "a new issue on iddv/kranto"]]);
    expect(longFields(ISSUE)).toEqual([["text", BODY]]);
    expect(lineOf(ISSUE)).not.toContain("What happened");
  });

  it("draws on its page as one line and acts only through its dialog, which shows the body once", async () => {
    const L = stub({ host: {} });
    ui.facts = { header: { host: { paused: false, running: null, next: null }, run: [] } } as unknown as Facts;
    location.hash = "#/settings/privacy";
    answering({ [PREPARED_API]: { prepared: [P({ fields: { mode: "off", text: BODY } }), P({ uuid: "p3", page: "#/topics" })] } });
    const { target, done } = await draw(PreparedLine as never, where("settings/privacy"));
    await settle();
    const lines = target.querySelectorAll(".prepared");
    expect(lines.length).toBe(1);
    expect(lines[0]!.textContent).toContain("Claude Code prepared: Usage reports: off");
    expect(lines[0]!.textContent).not.toContain("What happened");
    expect(lines[0]!.textContent).not.toMatch(/\bpress/i);
    const btn = lines[0]!.querySelector(".btn.primary") as HTMLButtonElement;
    expect(btn.textContent).toBe("Usage reports");
    btn.click();
    flushSync();
    expect(dlg.now?.props.title).toBe("Usage reports?");
    expect(L.api).not.toHaveBeenCalled();
    done();
  });

  it("the toast: one line, the action's button, Open; several merge; time out does nothing", () => {
    vi.useFakeTimers();
    const target = document.createElement("div");
    document.body.append(target);
    toastPrepared([ISSUE]);
    const { done } = { done: () => target.remove() };
    expect(toastLine(PTOAST.items)).toBe("Claude Code prepared: File a Kranto issue: Needs you doesn't update live when an assistant prepares something");
    toastPrepared([P(), P({ uuid: "p9" })]);
    expect(toastLine(PTOAST.items)).toBe("3 waiting: review");
    PTOAST.paused = true;                         // hovering: the bar stops
    vi.advanceTimersByTime(TOAST_MS + 500);
    expect(PTOAST.items.length).toBe(3);
    PTOAST.paused = false;
    vi.advanceTimersByTime(TOAST_MS + 500);
    expect(PTOAST.items).toEqual([]);             // gone; nothing was approved
    done();
  });

  it("a locked kind is offered Open only; an approval elsewhere takes it out of the toast", async () => {
    const { target, done } = await draw(PreparedToast as never, where("home"));
    toastPrepared([P({ uuid: "k1", title: "Turn usage reports on", locked: true })]);
    flushSync();
    expect(target.querySelector("#ptoast-act")).toBeNull();
    expect(target.querySelector("#ptoast-open")?.textContent).toBe("Open");
    closeToast();
    toastPrepared([ISSUE]);
    flushSync();
    expect(target.querySelector("#ptoast-act")?.textContent).toBe("File issue");
    await noticePrepared([{ seq: 2, verb: "b.factory_issue", title: "File a Kranto issue", subject: null, page: "#/needs", mark: "", by: "ui",
      by_words: "by you", prepared: "f1", run: null, at: "", resolved: "approved" }]);
    flushSync();
    expect(target.querySelector("#prepared-toast")).toBeNull();
    done();
  });
});

// C3: a build or project verb prepared before the cut comes back with available: false, a title
// ending "(no longer available)", button Dismiss and locked; Press answers 410. The page shows it
// with Dismiss only and never a red refusal
describe("a prepared item whose verb left Kranto", () => {
  const GONE = P({ uuid: "g1", verb: "b.build_start", title: "Start a build (no longer available)", page: "#/settings/privacy",
    button: "Dismiss", locked: true, available: false, fields: {} });
  /** fetch: /press answers 410, everything else 200; the requests it was given */
  function net(): string[] {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return url.endsWith("/press") ? new Response(JSON.stringify({ error: "that action is no longer available" }), { status: 410 }) : new Response("{}", { status: 200 });
    }));
    return urls;
  }
  afterEach(() => vi.unstubAllGlobals());

  it("offers Dismiss only, puts it away without a dialog, and is never toasted or the one thing", async () => {
    expect(gone(GONE)).toBe(true);
    expect(gone(P())).toBe(false);
    expect(buttonOf(GONE)).toBe("Dismiss");
    expect(buttonOf({ ...GONE, button: "Start build" })).toBe("Dismiss");
    const row = preparedRows([GONE])[0]!;
    expect(row.verb).toBe("Dismiss");
    expect(row.want).toBeUndefined();          // Needs you's and the home's one thing skip it
    toastPrepared([GONE]);
    expect(PTOAST.items).toEqual([]);

    const urls = net();
    stub({ host: {} });
    ui.facts = { header: { host: { paused: false, running: null, next: null }, run: [] } } as unknown as Facts;
    location.hash = "#/settings/privacy";
    answering({ [PREPARED_API]: { prepared: [GONE] } });
    const { target, done } = await draw(PreparedLine as never, where("settings/privacy"));
    await settle();
    const line = target.querySelector(".prepared")!;
    expect(line.textContent).toContain("Start a build (no longer available)");
    const buttons = [...line.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toEqual(["Dismiss"]);
    expect(line.querySelector(".btn.primary")).toBeNull();
    openPrepared(GONE);                           // whatever calls it (Needs you, the phone sheet)
    flushSync();
    expect(dlg.now).toBeNull();
    (line.querySelector("button") as HTMLButtonElement).click();
    await settle();
    expect(urls.every((u) => u.endsWith("/g1/dismiss"))).toBe(true);
    expect(urls.length).toBeGreaterThan(0);
    expect(target.querySelector("[data-refused]")).toBeNull();
    done();
  });

  it("a Press that meets one anyway (410) puts it away, never a refusal", async () => {
    const urls = net();
    const L = stub({ host: {} });
    expect(await actPrepared(P({ uuid: "p7" }), "approve")).toBe(true);
    expect(urls).toEqual([`${PREPARED_API}/p7/press`, `${PREPARED_API}/p7/dismiss`]);
    expect(refusedPrepared.p7).toBeUndefined();
    expect(L.say).toHaveBeenCalledWith(expect.stringContaining("put away"), "grey");
    expect(L.say).not.toHaveBeenCalledWith(expect.anything(), "red");
  });
});

describe("a prepared Pass, Write a post or Later (16, Codex 12)", () => {
  it("reads as the page says it, never target_id, value, about or as", () => {
    const pass = P({ verb: "feedback.add", title: "Grade", page: "#/ideas", subject_name: "Padel court finder", fields: { target: "idea", target_id: "153", value: "not_useful" } });
    expect(lineOf(pass)).toBe("Pass: Padel court finder");
    expect(keyFields(pass)).toEqual([["where", "shows on #/ideas"]]);
    const write = P({ verb: "post.write", title: "Write a post", page: "#/post", fields: { about: "card:160", as: "blog" } });
    expect(lineOf(write)).toBe("Write a blog post: about card #160");
    expect(keyFields(write).map(([k]) => k)).toEqual(["where"]);
    const later = P({ verb: "idea.later", title: "Later", subject_id: "144", fields: { days: 3 } });
    expect(lineOf(later)).toBe("Later: card #144, back in 3 days");
  });
});

describe("an assistant's new words for a draft and its voice card", () => {
  it("reads the draft's new words back as words, never [object Object], and names what it changes", () => {
    const edit = P({ verb: "post.edit", title: "Save", subject_id: "7", page: "#/post/d/7",
      fields: { parts: [{ text: "Words my assistant chose." }, { text: "A second part." }] } });
    expect(lineOf(edit)).toBe("New words for a draft: draft #7");
    expect(longFields(edit)).toEqual([["parts", "Words my assistant chose.\n\nA second part."]]);
    expect(JSON.stringify(keyFields(edit))).not.toContain("object Object");
    const one = P({ verb: "post.edit", title: "Save", subject_id: "7", fields: { parts: [{ text: "Short." }] } });
    expect(keyFields(one)).toContainEqual(["parts", "Short."]);
  });
});

// a voice card prepared together with Salt (the second outside try: the dialog showed the voice
// card only, so approving it changed Salt unsaid); the server says each change in words
const VOICE = P({ uuid: "v1", verb: "prose.voice", title: "Save", page: "#/settings/posting", button: "Save",
  says: "Change your voice card, set Salt to salty and set the disclosure line on Bluesky.",
  fields: { voice: "Short, dry, first person.", switches: { salt: "salty" }, disclosure: { bluesky: "Drafted with help." } },
  changes: [{ label: "Voice card", value: "Short, dry, first person.", long: false }, { label: "Salt", value: "salty", long: false },
    { label: "Disclosure line on Bluesky", value: "Drafted with help.", long: false }] });

describe("a prepared change of several fields", () => {
  it("says in one plain sentence what will change, with no field names or API words", () => {
    expect(lineOf(VOICE)).toBe("Change your voice card, set Salt to salty and set the disclosure line on Bluesky");
    expect(lineOf(VOICE)).not.toMatch(/switches|disclosure:|samples_add|\[|\]/);
    expect(whyOf(VOICE, "Save")).toBe("Nothing happens until you choose Save.");
    expect(dialogTitle(VOICE)).toBe("Change your voice card, set Salt to salty and set the disclosure line on Bluesky?");
  });

  it("lists every field it will change, with its new value, in its Save dialog", () => {
    expect(keyFields(VOICE)).toEqual([["Voice card", "Short, dry, first person."], ["Salt", "salty"],
      ["Disclosure line on Bluesky", "Drafted with help."], ["where", "shows on #/settings/posting"]]);
    const target = document.createElement("div");
    document.body.append(target);
    const app = mount(PreparedDialog, { target, props: { p: VOICE, title: dialogTitle(VOICE), okText: "Save", onOk: () => {}, close: () => {} } });
    flushSync();
    const text = target.textContent || "";
    for (const c of VOICE.changes!) {
      expect(text).toContain(c.label);
      expect(text).toContain(c.value);
    }
    void unmount(app);
    target.remove();
  });

  it("a long new value is drawn as its own text, not dropped", () => {
    const long = "A voice card of many words. ".repeat(10).trim();
    const p = { ...VOICE, changes: [{ label: "Voice card", value: long, long: true }, { label: "Salt", value: "salty" }] };
    expect(keyFields(p).map(([k]) => k)).toEqual(["Salt", "where"]);
    expect(longFields(p)).toEqual([["Voice card", long]]);
  });
});

