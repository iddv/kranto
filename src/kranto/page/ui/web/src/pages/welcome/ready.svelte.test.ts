// Welcome: Model, First topic, Ready, then How you write.
// Ready: four lines (the first brief, the cost, the console, usage reports) and Start reading,
// which finishes setup and opens How you write while kranto reads (F-13). How you write: samples,
// four switches, Skip for now and Save how I write, both to the home.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { drop } from "../../lib/reads.svelte";
import { ui } from "../../lib/shell.svelte";
import { SETUP_API, type Setup } from "../settings/keys.svelte";
import { PRIVACY_API } from "../settings/privacy";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import Welcome from "./Welcome.svelte";
import { TOPIC, briefLine, modelWorks, newStep } from "./welcome.svelte";
import { firstLine, PROSE_API, samplesLine, splitSamples } from "./voice";

const COST = "About $5 to $8 a month for one topic with ten sources, on your own model key. No cap is set; set one in Spend.";
const S = (claude: Setup["logins"]["claude"]): Setup => ({
  done: false, done_at: null, needs_setup: true, key: { set: true, env: "ANTHROPIC_API_KEY", base_url: "https://api.anthropic.com", provider: "anthropic", choice: "anthropic", label: "Claude API", endpoint: "https://api.anthropic.com", test: null },
  logins: { claude, gh: { ok: false, detail: "the GitHub CLI is not installed (no gh on PATH)", command: "gh auth login" } }, builds_ok: false,
  budget_usd: null, cost: COST, first_brief_minutes: 5, every_hours: 3, build: { mode: null, concurrency: 1 }, topics: 1, sources: 4, scheduler: true, brb: true, builds: false,
});
const PRIVACY = { answered: false, mode: "off", why: "default", meaning: "nothing is sent", modes: [], levels: [] };
const PROSE = { voice: "", switches: { length: "medium", register: "neutral", opinions: "mine", emoji: "never" },
  switch_choices: { length: ["short", "medium", "long"], register: ["casual", "neutral", "formal"], opinions: ["mine", "suggest"], emoji: ["never", "sparingly"] },
  switch_words: {}, samples: [] };
const at = (path: string): Where => ({ ...where(path), stage: true });
const words = (el: Element | null): number => (el?.textContent || "").split(/\s+/).filter((w) => /\w/.test(w)).length;
afterEach(() => {
  drop(SETUP_API);
  drop(PROSE_API);
  ui.facts = null;
  TOPIC.t = null;
  history.replaceState(null, "", "#/");
});
function stubbed(answer: unknown = {}) {
  const L = stub({ answer, host: { budget_usd: null, topics: [{ id: 4, name: "Padel" }, { id: 7, name: "Robotics" }] } });
  Object.assign(L, { sticky: vi.fn((el: HTMLElement) => el), afkDrop: vi.fn(), afkStale: vi.fn(), loadHost: vi.fn(async () => {}) });
  ui.facts = { header: { host: { paused: false } } } as unknown as Facts;
  return L;
}

describe("Welcome", () => {
  it("names the four steps, and Ready says four lines in at most 131 words", async () => {
    stubbed();
    answering({ [SETUP_API]: S({ ok: true, installed: true, detail: "signed in", command: "claude auth login" }), [PRIVACY_API]: PRIVACY });
    const { target, done } = await draw(Welcome, at("welcome/finish"));
    await settle();
    expect(target.querySelector(".steps-line")?.textContent).toBe("Welcome · Model · First topic · Step 3 of 4: Ready · How you write");
    expect(target.querySelector(".ph h1")?.textContent).toBe("Ready");
    expect(target.querySelector("#ready-brief")?.textContent).toBe("The first brief In about 5 minutes.");
    expect(target.querySelector("#usage-line")?.textContent).toBe("Off. Nothing leaves this machine unless you turn them on.");
    expect(target.textContent).not.toMatch(/\bbuild|repositor/i);
    // the choices are folded under What they hold; the visible words fit the budget
    const shown = [...target.querySelectorAll(".narrow > .ph, .ready-lines li")].map((li) => {
      const c = li.cloneNode(true) as Element;
      c.querySelectorAll("details > :not(summary)").forEach((x) => x.remove());
      return words(c);
    }).reduce((a, b) => a + b, 0);
    expect(shown).toBeLessThanOrEqual(131);
    done();
  });

  it("says Claude Code is ready and what it will ask, or not installed (Kranto works without it) with the line to fix it", async () => {
    stubbed();
    answering({ [SETUP_API]: S({ ok: true, installed: true, detail: "signed in", command: "claude auth login" }), [PRIVACY_API]: PRIVACY });
    const a = await draw(Welcome, at("welcome/finish"));
    await settle();
    expect(a.target.querySelector("#claude-state")?.textContent).toBe("Claude Code is ready. It asks once whether to trust Kranto's folder; that is expected.");
    expect(a.target.querySelector("#cost-line")?.textContent).toBe(COST);
    expect(a.target.querySelector("#usage-reports")).not.toBeNull();
    a.done();
    drop(SETUP_API);
    stubbed();
    answering({ [SETUP_API]: S({ ok: false, installed: false, detail: "Claude Code is not installed (no claude on PATH)", command: "claude auth login" }), [PRIVACY_API]: PRIVACY });
    const b = await draw(Welcome, at("welcome/finish"));
    await settle();
    expect(b.target.querySelector("#claude-state")?.textContent).toContain("Not installed; Kranto works without it.");
    expect(b.target.querySelector("#ready-claude code")?.textContent).toBe("curl -fsSL https://claude.ai/install.sh | bash");
    b.done();
    drop(SETUP_API);
    const L = stubbed();
    answering({ [SETUP_API]: S({ ok: false, installed: true, detail: "not signed in", command: "claude auth login" }), [PRIVACY_API]: PRIVACY });
    const c = await draw(Welcome, at("welcome/finish"));
    await settle();
    expect(c.target.querySelector("#claude-state")?.textContent).toContain("Installed, not signed in; Kranto works without it.");
    (c.target.querySelector("#check-again") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/check", {});
    c.done();
  });

  it("Start reading needs no answer about usage reports, finishes setup, and opens How you write", async () => {
    const L = stubbed({ done: true, ingest: "started" });
    answering({ [SETUP_API]: S({ ok: true, installed: true, detail: "signed in", command: "claude auth login" }), [PRIVACY_API]: PRIVACY });
    TOPIC.t = { ...newStep(), id: 4, name: "Padel" };
    const { target, done } = await draw(Welcome, at("welcome/finish"));
    await settle();
    const go = target.querySelector("#finish") as HTMLButtonElement;
    expect(go.textContent).toBe("Start reading");
    expect(go.disabled).toBe(false);
    go.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/finish", {});
    expect(location.hash).toBe("#/welcome/voice");
    expect(L.say).toHaveBeenCalledWith("Kranto is reading. The first brief comes in a few minutes; the home shows the first hour.");
    done();
  });

  it("How you write: the read on top, samples and four switches, one primary; Skip goes home, Save saves", async () => {
    const L = stubbed({ ok: true, say: "Saved." });
    answering({ [PROSE_API]: PROSE, "/api/home": { first: { topic: { id: 4, name: "Padel" }, rows: [], read: { source_index: 2, sources: 5, kept: 4, judged: 19, started_at: null }, brief_minutes: 3, early_kept: 8 } } });
    const { target, done } = await draw(Welcome, at("welcome/voice"));
    await settle();
    expect(target.querySelector("#voice-reading")?.textContent).toBe("Kranto is reading · source 2 of 5 · 4 kept of 19 read · the first brief in about 3 minutes");
    expect([...target.querySelectorAll(".voice-switches select")].map((s) => s.id)).toEqual(["voice-length", "voice-register", "voice-opinions", "voice-emoji"]);
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    expect(target.querySelector("#voice-skip")?.getAttribute("href")).toBe("#/home");
    expect(words(target.querySelector("#how-you-write"))).toBeLessThanOrEqual(150);
    const ta = target.querySelector("#voice-samples") as HTMLTextAreaElement;
    ta.value = "The first thing I wrote, long enough to count.\n---\nThe second thing I wrote, long enough too.";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    const sel = target.querySelector("#voice-length") as HTMLSelectElement;
    sel.value = "short";
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    (target.querySelector("#voice-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/prose/voice", {
      samples_add: [{ text: "The first thing I wrote, long enough to count.", site: null }, { text: "The second thing I wrote, long enough too.", site: null }],
      switches: { length: "short" } });
    expect(location.hash).toBe("#/home");
    done();
  });

  it("splits samples on a dashed line and says the first read in words", () => {
    expect(splitSamples("a short one\n---\nthis one is long enough to keep")).toEqual(["this one is long enough to keep"]);
    expect(firstLine(null)).toBe("");
    expect(firstLine({ topic: { id: 1, name: "x" }, read: { source_index: 1, sources: 5, kept: 9, judged: 30, started_at: null }, brief_minutes: null, early_kept: 8 }))
      .toBe("Kranto is reading · source 1 of 5 · 9 kept of 30 read · the first brief is being written");
    expect(firstLine({ topic: { id: 1, name: "x" }, read: null, brief_minutes: 5 })).toBe("Kranto is reading · the first brief in about 5 minutes");
  });
});

// Codex, Gemini: Ready promised "The first brief in about 5 minutes" with no topic and no model
describe("Ready's first brief", () => {
  it("promises a time only when a brief can come; else it says what is still missing", async () => {
    stubbed();
    const cc = { ok: false, installed: false, detail: "Claude Code is not installed (no claude on PATH)", command: "claude auth login" };
    const base = S(cc);
    answering({ [SETUP_API]: { ...base, topics: 0, key: { ...base.key, provider: "claude_code", choice: "claude_code" } }, [PRIVACY_API]: PRIVACY });
    const { target, done } = await draw(Welcome, at("welcome/finish"));
    await settle();
    const line = target.querySelector("#ready-brief")!.textContent || "";
    expect(line).not.toMatch(/minutes/);
    expect(line).toContain("Claude Code, which reads for you, is not installed on this machine");
    expect(line).toContain("a topic to watch (step 2)");
    expect(target.querySelector("#ready-brief a")?.getAttribute("href")).toBe("#/welcome");
    expect(target.querySelector("#claude-state")?.textContent).not.toContain("works without it");
    done();
  });

  it("words each case", () => {
    const ok = { set: true, provider: "anthropic", test: null };
    expect(briefLine({ topics: 1, scheduler: true, key: ok, first_brief_minutes: 5 }).text).toBe("In about 5 minutes.");
    expect(briefLine({ topics: 0, scheduler: true, key: ok }).text).toBe("No brief yet. Still missing: a topic to watch (step 2).");
    expect(briefLine({ topics: 0, scheduler: true, key: ok }).href).toBe("#/welcome/topics");
    expect(briefLine({ topics: 1, scheduler: true, key: { set: false, provider: "openrouter" } }).text).toBe("No brief yet. Still missing: a model that works (step 1).");
    expect(briefLine({ topics: 1, scheduler: false, key: ok }).text).toMatch(/^When you choose Run now/);
    expect(modelWorks({ key: { ...ok, test: { ok: false } } })).toBe(false);
    expect(modelWorks({ key: { set: true, provider: "claude_code" }, logins: { claude: { ok: false, installed: true } } })).toBe(false);
    expect(modelWorks({ key: ok })).toBe(true);
  });
});

describe("How you write's samples line", () => {
  it("says the samples left out and why", () => {
    const long = "A sample long enough to be kept as one.";
    expect(samplesLine("")).toBe("Three to five is best.");
    expect(samplesLine(`${long}\n---\nshort\n---\n${long}`)).toBe("2 of 3 to 5 pasted. 1 left out: under 20 characters.");
    expect(samplesLine(Array(6).fill(long).join("\n---\n"))).toBe("5 of 3 to 5 pasted. 1 left out: five at most.");
  });
});
