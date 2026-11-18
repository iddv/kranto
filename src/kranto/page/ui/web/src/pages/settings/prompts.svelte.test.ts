import { answerDialog, dialogShown } from "../../ui/testing";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { drop, peek } from "../../lib/reads.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import PromptsList from "./PromptsList.svelte";
import PromptsPane from "./PromptsPane.svelte";
import {
  diffLines, hiSegs, PDRAFT, PPREV, promptMeta, PROMPTS_API, THREE, versionLine, versionMeta, VNOTE, VOPEN,
  type Prompt, type PromptRow, type Prompts, type VersionView,
} from "./prompts.svelte";

const ROW: PromptRow = { repo: "kranto", id: "card", title: "Idea card", group: "Ideas", where: "after the map", editable: "full", subject: "idea",
  customised: true, override: true, additions: false, default_changed: false };
const REG: Prompts = {
  defaults_only: false, store: "/h/prompts",
  prompts: [
    { ...ROW, id: "judge", title: "Judge", group: "Watching", where: "each item read", customised: false, override: false },
    ROW,
    { ...ROW, id: "verify", title: "Citation check", group: "Ideas", where: "after each card", editable: "additions-only", customised: false, override: false },
  ],
};
const CARD: Prompt = {
  ...ROW, purpose: "Writes an idea card from a theme.", step: "card", file: "prompts/card.md", version: "cee86866d485", n: 2, house_rules: false,
  placeholders: [{ token: "<<theme>>", description: "the theme", required: true }, { token: "<<lessons>>", description: "the lessons", required: false }],
  notes: ["One note."], slots: [], sections: ["dedupe"], headings: { additions: "## The owner's additions" },
  default: "Default <<theme>>", template: "Mine <<theme>> and <<lessons>>", additions_text: "", active: "Mine <<theme>> and <<lessons>>",
  diff: "--- default\n+++ yours\n@@ -1 +1 @@\n-Default <<theme>>\n+Mine <<theme>> and <<lessons>>",
  versions: [{ n: 1, at: "2026-10-01T10:00:00Z", action: "template", note: "first", has_template: true, additions_chars: 0 },
             { n: 2, at: "2026-10-02T10:00:00Z", action: "additions", active: true, additions_chars: 12, has_template: true }],
};
const V1: VersionView = { n: 1, text: "Mine <<theme>>", hash: "abc123", active_n: 2, same_as_active: false, diff: "@@ -1 +1 @@\n-x\n+y", restorable: true, why_not: null,
  template_kind: "override", additions: "" };
const DETAIL = `${PROMPTS_API}/card`;

afterEach(() => {
  for (const o of [PDRAFT, VOPEN, VNOTE, PPREV, THREE] as Record<string, unknown>[]) for (const k of Object.keys(o)) delete o[k];
  drop(PROMPTS_API);
  ui.facts = null;
  vi.restoreAllMocks();
});
/** the app stubbed with its toast and the preview's items, the server hosting the page */
function stubbed(answers: Record<string, unknown> = {}) {
  const L = stub({ host: { topics: [] } });
  L.api.mockImplementation(async (path: string) => answers[path] ?? {});
  const toast = vi.fn();
  const previewSubjects = vi.fn(() => [["3", "#3 Card three"], ["4", "#4 Card four"]]);
  Object.assign(L, { toast, previewSubjects });
  ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
  return { L, toast, previewSubjects };
}
const type = async (el: Element | null, value: string, ev = "input"): Promise<void> => {
  (el as HTMLInputElement).value = value;
  el?.dispatchEvent(new Event(ev, { bubbles: true }));
  await settle();
};

describe("Settings › Prompts (the server's alone)", () => {
  it("says a prompt's row, a version and a diff in words", () => {
    expect(promptMeta(ROW)).toBe("your full prompt · after the map");
    expect(promptMeta({ ...ROW, override: false, additions: true, editable: "additions-only", default_changed: true })).toBe("your additions · additions only · the default changed since you edited it · after the map");
    expect(versionMeta({ n: 3, action: "restore", note: "ok", active: true, same_as: 1, chars: 1, additions_chars: 4, has_template: true }))
      .toBe("“ok” · in use · same as v1 · 1 character · additions 4 characters · full prompt");
    expect(versionLine(V1)).toBe("v1: your full prompt and no additions · hash abc123 · differs from the version in use (v2)");
    expect(versionLine({ ...V1, template_kind: "default", same_as_active: true })).toBe("v1: the default text and no additions · hash abc123 · the same text as the version in use (v2)");
    expect(hiSegs("a <<theme>> b $X", [{ token: "<<theme>>", description: "the theme", required: true }])).toEqual([
      { text: "a ", ph: false, title: null }, { text: "<<theme>>", ph: true, title: "the theme" }, { text: " b $X", ph: false, title: null }]);
    expect(diffLines("+++ b\n+x\n-y\n@@ 1")).toEqual([{ cls: null, text: "+++ b\n" }, { cls: "add", text: "+x\n" }, { cls: "del", text: "-y\n" }, { cls: "hunk", text: "@@ 1\n" }]);
  });

  it("lists the prompts by their step, no house rules", async () => {
    stubbed();
    answering({ [PROMPTS_API]: REG });
    const { target, done } = await draw(PromptsList, where("settings/prompts"));
    expect([...target.querySelectorAll(".grp h2")].map((h) => [h.id, h.textContent])).toEqual([["p-watching", "Watching"], ["p-ideas", "Ideas"]]);
    expect(target.querySelector('[data-sel="ehouse"]')).toBeNull();
    const card = target.querySelector('[data-sel="eprompt:card"]');
    expect(card?.querySelector(".c-meta")?.textContent).toBe("your full prompt · after the map");
    expect(card?.querySelector(".gl")?.getAttribute("title")).toBe("Set");
    expect(target.querySelector('[data-sel="eprompt:verify"] .c-meta')?.textContent).toBe("the default · additions only · after each card");
    expect(target.querySelector(".tbn")).toBeNull();
    expect(target.querySelector("input, textarea, select")).toBeNull();
    expect(target.textContent).not.toMatch(/licen[cs]e|House rules|\bBuild\b/);
    done();
  });

  it("says the defaults only, a read that failed, and that it needs the server", async () => {
    stubbed();
    answering({ [PROMPTS_API]: { ...REG, defaults_only: true } });
    const { target, done } = await draw(PromptsList, where("settings/prompts"));
    expect(target.querySelector(".tbn")?.textContent).toBe("Defaults only: this process ignores every customisation (KRANTO_PROMPTS=defaults)");
    done();
    stubbed();
    drop(PROMPTS_API);
    answering({});
    const bad = await draw(PromptsList, where("settings/prompts"));
    expect(bad.target.querySelector(".empty")?.textContent).toBe("Could not read the prompts: not found: /api/prompts");
    bad.done();
    stub();
    ui.facts = null;
    const off = await draw(PromptsPane, where("settings/prompts"));
    expect(off.target.querySelector(".pane-empty p")?.textContent).toBe("Prompts are the server's, which is not answering.");
    off.done();
  });

  it("says what is customised with nothing selected", async () => {
    stubbed();
    answering({ [PROMPTS_API]: { ...REG, prompts: [...REG.prompts, { ...ROW, id: "x", title: "Moved", default_changed: true }] } });
    const { target, done } = await draw(PromptsPane, where("settings/prompts"));
    expect(target.querySelector(".dt")?.textContent).toBe("Prompts you can see and steer");
    expect(target.querySelector(".dk")?.textContent).toBe(" settings · prompts");
    expect(target.querySelector(".dk .gl")?.getAttribute("title")).toBe("Needs you");
    expect([...target.querySelectorAll("#s-now dd")].map((x) => x.textContent)).toEqual(["Idea card, Moved", "Moved", "4", "/h/prompts"]);
    done();
  });

  it("draws a prompt: about, placeholders, the full prompt and its diff, the prompt now", async () => {
    stubbed();
    answering({ [DETAIL]: CARD });
    const { target, done } = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    expect(target.querySelector(".dt")?.textContent).toBe("Idea card");
    expect(target.querySelector(".dk")?.textContent).toBe(" prompt · Ideas");
    expect(target.querySelector(".acts .muted")?.textContent).toBe("version cee86866d485");
    expect([...target.querySelectorAll(".sec h3")].map((h) => h.textContent)).toEqual(["About", "Placeholders2", "Your additions", "Edit the full prompt", "The prompt now", "Versions2", "Preview"]);
    expect([...target.querySelectorAll("#s-about dd")].map((x) => x.textContent)).toEqual(["after the map", "card", "an idea card", "additions, or the full prompt", "prompts/card.md", "cee86866d485 (yours, v2)"]);
    expect([...target.querySelectorAll("#s-placeholders li")].map((x) => x.textContent)).toEqual(["<<theme>> the theme", "<<lessons>> the lessons (may go)"]);
    expect(target.querySelector("#s-placeholders p.mt")?.textContent).toBe("Filled in by the code when it runs. A full prompt must keep the 1 required one and its <!-- section: dedupe --> part.");
    expect((target.querySelector("#prompt-tpl") as HTMLTextAreaElement).value).toBe("Mine <<theme>> and <<lessons>>");
    expect([...target.querySelectorAll("#s-full pre.diff span")].map((s) => s.className)).toEqual(["", "", "hunk", "del", "add"]);
    const marks = [...target.querySelectorAll("#s-active pre mark.ph")];
    expect(marks.map((m) => [m.textContent, m.getAttribute("title")])).toEqual([["<<theme>>", "the theme"], ["<<lessons>>", "the lessons"]]);
    expect(target.querySelector("#s-active pre")?.textContent).toBe("Mine <<theme>> and <<lessons>>");
    expect(target.querySelector(".note")).toBeNull();
    done();
  });

  it("saves additions and the full prompt from their drafts, and resets", async () => {
    const after = { ...CARD, n: 3, additions: true, additions_text: "Be strict." };
    const { L } = stubbed({ [DETAIL]: after, [DETAIL + "/reset"]: { ...CARD, n: 4, customised: false, override: false } });
    answering({ [DETAIL]: CARD, [PROMPTS_API]: REG });
    const { target, done } = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    await type(target.querySelector("#prompt-add"), "Be strict.");
    expect(PDRAFT["card:add"]).toBe("Be strict.");
    expect(L.api).not.toHaveBeenCalled();
    (target.querySelector("#save-additions") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(DETAIL, { additions: "Be strict." });
    expect(L.say).toHaveBeenLastCalledWith("Saved: Idea card, version 3. Your additions apply from its next call.");
    expect("card:add" in PDRAFT).toBe(false);
    expect(peek(DETAIL)?.data).toEqual(after);
    expect(target.querySelector("#s-additions .btn.quiet")?.textContent).toBe("Clear them");
    await type(target.querySelector("#prompt-tpl"), "New <<theme>>");
    (target.querySelector("#save-template") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(DETAIL, { template: "New <<theme>>" });
    expect(L.say).toHaveBeenLastCalledWith("Saved: Idea card, version 3. Your full prompt applies from its next call.");
    (target.querySelector("#reset-prompt") as HTMLButtonElement).click();
    expect(dialogShown()).toEqual({ title: "Idea card back to the default?", text: "Your additions and your full prompt stay listed as versions." });
    answerDialog(false);
    expect(L.api).not.toHaveBeenCalledWith(DETAIL + "/reset", { what: "all" });
    (target.querySelector("#reset-prompt") as HTMLButtonElement).click();
    answerDialog(true);
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(DETAIL + "/reset", { what: "all" });
    expect(L.say).toHaveBeenLastCalledWith("Saved: Idea card, version 4. Back to the default.");
    expect(target.querySelector("#reset-prompt")).toBeNull();
    done();
  });

  it("says a checker takes additions only, and a default that changed", async () => {
    stubbed();
    answering({ [`${PROMPTS_API}/verify`]: { ...CARD, id: "verify", title: "Citation check", editable: "additions-only", customised: false, override: false, template: null, diff: null,
      checker_note: "additions only: this step's rules can't be relaxed", placeholders: [], versions: [], subject: "none" },
    [DETAIL]: { ...CARD, default_changed: true, notice: "the default changed since you edited this", three_way: { diff_default: "-old\n+new" }, defaults_only: true } });
    const one = await draw(PromptsPane, where("settings/prompts", "eprompt:verify"));
    expect(one.target.querySelector(".note.c-grey")?.textContent).toBe("Additions only: this step's rules can't be relaxed. You can add to it; you cannot replace it.");
    expect(one.target.querySelector("#prompt-tpl")).toBeNull();
    expect(one.target.querySelector("#s-placeholders p")?.textContent).toBe("None: the context follows it.");
    expect(one.target.querySelector("#s-preview p")?.textContent).toBe("This prompt takes no single item: the preview shows it with every placeholder described.");
    expect([...one.target.querySelectorAll("#s-about dd")][2]?.textContent).toBe("no single item");
    one.done();
    stubbed();
    const two = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    const amber = two.target.querySelectorAll(".note.c-amber");
    expect(amber[0]?.querySelector("strong")?.textContent).toBe("The default changed since you edited this. ");
    const fold = amber[0]?.querySelector("details") as HTMLDetailsElement;
    expect(fold.id).toBe("three-card");
    expect([...fold.querySelectorAll("span")].map((s) => s.className)).toEqual(["del", "add"]);
    expect(amber[1]?.textContent).toBe("This process runs on the defaults (KRANTO_PROMPTS=defaults): what you save here does not apply to it.");
    expect(two.target.querySelector(".dk .gl")?.getAttribute("title")).toBe("Needs you");
    two.done();
  });

  it("opens a version in place, uses it again (undoable), and keeps its note", async () => {
    const restoredTo = { ...CARD, n: 3 };
    const { L, toast } = stubbed({ [DETAIL + "/restore"]: restoredTo, [DETAIL + "/versions/1/note"]: CARD });
    answering({ [DETAIL]: CARD, [DETAIL + "/versions/1"]: V1 });
    const { target, done } = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    const rows = [...target.querySelectorAll("#s-versions li.row")];
    expect(rows.map((r) => [r.querySelector(".c-num")?.textContent, r.querySelector(".r-title")?.textContent, r.querySelector(".gl")?.getAttribute("title")])).toEqual([
      ["v2", "additions saved", "In use"], ["v1", "full prompt saved", "Kept"]]);
    expect(rows[0]?.querySelector(".c-meta")?.textContent).toBe("in use · additions 12 characters · full prompt");
    (rows[1] as HTMLElement).click();
    await settle();
    expect(VOPEN[DETAIL]).toBe(1);
    const open = target.querySelector("#version-open");
    expect(open?.previousElementSibling?.hasAttribute("data-cur")).toBe(true);
    expect(open?.querySelector(".vbody p.mt")?.textContent).toBe("v1: your full prompt and no additions · hash abc123 · differs from the version in use (v2)");
    expect([...(open?.querySelectorAll("h4") || [])].map((h) => h.textContent)).toEqual(["Against the version in use (v2)", "The prompt v1 gives"]);
    expect(open?.querySelector("pre.prompt mark.ph")?.textContent).toBe("<<theme>>");
    const note = open?.querySelector("#version-note") as HTMLInputElement;
    expect(note.value).toBe("first");
    await type(note, "keep this");
    (target.querySelector("#save-version-note") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(DETAIL + "/versions/1/note", { note: "keep this" });
    expect(toast).toHaveBeenLastCalledWith("Note kept on v1.");
    (target.querySelector("#use-version") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(DETAIL + "/restore", { version: 1 });
    expect(toast.mock.calls.at(-1)?.[0]).toBe("Now using v1 again, saved as v3 (same as v1).");
    expect(VOPEN[DETAIL]).toBeNull();
    const undo = toast.mock.calls.at(-1)?.[1] as () => void;
    undo();
    await settle();
    expect(L.api).toHaveBeenLastCalledWith(DETAIL + "/restore", { version: 2 });
    expect(toast).toHaveBeenLastCalledWith("Back to v2, saved as v3.");
    done();
  });

  it("says a version that can't be restored", async () => {
    stubbed();
    answering({ [DETAIL]: CARD, [DETAIL + "/versions/1"]: { ...V1, restorable: false, why_not: "can't restore: a checker" } });
    VOPEN[DETAIL] = 1;
    const one = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    expect(one.target.querySelector("#use-version")).toBeNull();
    expect(one.target.querySelector("#version-open .note.c-amber")?.textContent).toBe("Can't restore: a checker.");
    one.done();
  });

  it("previews against a real item; no model is called", async () => {
    const { L, previewSubjects } = stubbed({ [PROMPTS_API + "/preview"]: { id: "card", text: "Sent <<theme>>", chars: 1234, custom: true, filled: ["theme"], redactions: [{ kind: "token", count: 2 }] } });
    answering({ [DETAIL]: CARD });
    const { target, done } = await draw(PromptsPane, where("settings/prompts", "eprompt:card"));
    expect(previewSubjects).toHaveBeenCalled();
    expect(target.querySelector("#s-preview p")?.textContent).toBe("Against a real idea card: exactly what would be sent, secrets removed. No model is called.");
    const sel = target.querySelector("#preview-subject") as HTMLSelectElement;
    expect([...sel.options].map((o) => [o.value, o.textContent, o.selected])).toEqual([["3", "#3 Card three", true], ["4", "#4 Card four", false]]);
    await type(sel, "4", "change");
    (target.querySelector("#preview-prompt") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(PROMPTS_API + "/preview", { id: "card", subject: "4" });
    expect(target.querySelector("#s-preview p.mt")?.textContent).toBe("1,234 characters · your version · filled: theme · removed: 2 token");
    expect(target.querySelector("#s-preview pre mark.ph")?.textContent).toBe("<<theme>>");
    expect((target.querySelector("#preview-prompt") as HTMLButtonElement).disabled).toBe(false);
    L.api.mockImplementation(async () => { throw new Error("no such card"); });
    (target.querySelector("#preview-prompt") as HTMLButtonElement).click();
    await settle();
    expect(target.querySelector("#s-preview .note.c-red")?.textContent).toBe("The preview failed: no such card");
    done();
  });

  it("says what is not here, and a prompt that could not be read", async () => {
    stubbed();
    answering({ [PROMPTS_API]: REG });
    const gone = await draw(PromptsPane, where("settings/prompts", "eother"));
    expect(gone.target.querySelector(".pane-empty")?.textContent).toBe("Nothing to show here.");
    gone.done();
    stubbed();
    answering({});
    const bad = await draw(PromptsPane, where("settings/prompts", "eprompt:nope"));
    expect(bad.target.querySelector(".pane-empty")?.textContent).toBe("Could not read this prompt: not found: /api/prompts/nope");
    bad.done();
  });
});
