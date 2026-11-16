// Settings › Posting › How you write: the voice card, the four switches, the
// samples, one primary (Save, which sends only what changed), the advanced parts folded.
import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import VoicePage from "./VoicePage.svelte";
import { PROSE, listDiff, linesOf, type Prose } from "./voice";

afterEach(() => { ui.facts = null; });
const prose = (): Prose => ({
  voice: "Tone: plain.", switches: { length: "medium", register: "neutral", opinions: "mine", emoji: "never", hashtags: "site", links: "post", grade: 8 },
  switch_choices: { length: ["short", "medium", "long"], register: ["casual", "neutral", "formal"], opinions: ["mine", "suggest"], emoji: ["never", "sparingly"], hashtags: ["never", "site"], links: ["post", "reply"], grade: [3, 16] },
  switch_words: {}, strictness: "light",
  rules: [{ id: "words.floor", group: "words", words: "a word that reads like a model", fix: "say it plainly", on: true }],
  guides: [{ name: "floor", title: "The floor", from: "kranto", always: true }, { name: "plain", title: "Plain words", from: "kranto", always: false }],
  sites: [{ site: "blog", guides: ["floor", "plain"], default: true, limits: {}, disclosure: "" }],
  disclosure_line: "Drafted from my notes; edited and sent by me.", take: true,
  never: ["delve"], keep: [], always: [],
  samples: [{ id: "s1", site: "mastodon", words: 42, start: "Courts were full again" }],
});

describe("How you write", () => {
  it("draws the voice, the four switches and the samples with one primary and the rest folded; Save sends what changed", async () => {
    const L = stub();
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [PROSE]: prose() });
    const { target, done } = await draw(VoicePage, where("settings/posting/voice"));
    await settle();
    expect(target.querySelector("h1")?.textContent).toBe("How you write");
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    expect((target.querySelector("#voice-card") as HTMLTextAreaElement).value).toBe("Tone: plain.");
    expect([...target.querySelectorAll("#voice-switches select")].map((s) => s.id)).toEqual(["voice-sw-length", "voice-sw-register", "voice-sw-opinions", "voice-sw-emoji"]);
    expect(target.querySelector("#voice-samples")?.textContent).toContain("Mastodon · 42 words · Courts were full again");
    expect((target.querySelector("#voice-advanced") as HTMLDetailsElement).open).toBe(false);
    const len = target.querySelector("#voice-sw-length") as HTMLSelectElement;
    len.value = "short";
    len.dispatchEvent(new Event("change", { bubbles: true }));
    const never = target.querySelector("#voice-list-never") as HTMLTextAreaElement;
    never.value = "delve\ngame-changer";
    never.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.querySelector("#voice-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/prose/voice", { switches: { length: "short" }, never_add: ["game-changer"] });
    done();
  });

  it("lets me choose each writer's model (none chosen for me) and save it with Save", async () => {
    const L = stub();
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [PROSE]: { ...prose(), writer_models: { social: null, blog: null, newsletter: null, toot: null }, writer_providers: ["openrouter", "openai_compat", "anthropic", "claude_code", "openai"], writer_key: { set: false } } });
    const { target, done } = await draw(VoicePage, where("settings/posting/voice"));
    await settle();
    const pick = target.querySelector("#voice-writer-social") as HTMLSelectElement;
    expect(pick.value).toBe("");                                          // Kranto's own: no default chosen
    expect(pick.selectedOptions[0]?.textContent).toBe("Kranto's writing model");
    expect([...target.querySelectorAll("#voice-writers select")].length).toBe(4);
    expect(target.querySelector("#voice-writer-model-social")).toBeNull();
    pick.value = "openai";
    pick.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    const model = target.querySelector("#voice-writer-model-social") as HTMLInputElement;
    model.value = "gpt-x";
    model.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.querySelector("#voice-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/prose/voice", { writer_model: { social: { provider: "openai", model: "gpt-x" } } });
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    expect([...target.querySelectorAll("#voice-switches select")].length).toBe(4);
    done();
  });

  it("sends the OpenAI key once, empties the box, and never shows it", async () => {
    const L = stub();
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [PROSE]: { ...prose(), writer_key: { set: false }, writer_providers: ["openai"], writer_models: {} } });
    const { target, done } = await draw(VoicePage, where("settings/posting/voice"));
    await settle();
    expect(target.querySelector("#voice-key-state")?.textContent).toContain("not set");
    const box = target.querySelector("#voice-key") as HTMLInputElement;
    expect(box.type).toBe("password");
    const key = ["sk", "page", "x".repeat(20)].join("-");
    box.value = key;
    (target.querySelector("#voice-key-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/prose/writer-key", { key });
    expect(box.value).toBe("");
    expect(target.textContent).not.toContain(key);
    done();
  });

  it("gives each site its own disclosure words, out of Advanced", async () => {
    const L = stub();
    ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
    answering({ [PROSE]: { ...prose(), disclosure_default: "Drafted with Kranto.",
      sites: [{ site: "blog", guides: ["floor"], default: true, limits: {}, disclosure: "" }, { site: "bluesky", guides: ["floor"], default: true, limits: {}, disclosure: "" }] } });
    const { target, done } = await draw(VoicePage, where("settings/posting/voice"));
    await settle();
    const sky = target.querySelector("#voice-disclose-bluesky") as HTMLInputElement;
    expect(sky.placeholder).toBe("Drafted with Kranto.");
    expect(sky.closest("#voice-advanced")).toBeNull();
    sky.value = "Written with help; sent by me.";
    sky.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    (target.querySelector("#voice-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/prose/voice", { disclosure: { bluesky: "Written with help; sent by me." } });
    done();
  });

  it("diffs a list as typed", () => {
    expect(linesOf(" a \n\nb\na")).toEqual(["a", "b"]);
    expect(listDiff(["a", "b"], ["b", "c"])).toEqual({ add: ["c"], remove: ["a"] });
  });
});
