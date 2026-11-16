import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import KeysList from "./KeysList.svelte";
import KeysPane from "./KeysPane.svelte";
import { KEYBASE, KEYPROV, keyWords, PROVIDER_API, providerOf, SETUP_API, type ProviderSetup, type Setup } from "./keys.svelte";

const NOW = Date.parse("2026-10-16T12:00:00Z");
// The server's /api/setup (Setup is generated from its web/types.py)
const BASE = "https://openrouter.ai/api/v1";
const S: Setup = {
  done: true, done_at: "2026-10-01T10:00:00Z", needs_setup: false,
  key: { set: true, env: "OPENROUTER_API_KEY", base_url: BASE, provider: "openai_compat", choice: "openrouter", label: "OpenRouter", endpoint: BASE, test: { ok: true, detail: "Works", base_url: BASE, at: "2026-10-16T11:00:00Z" } },
  logins: { claude: { ok: true, detail: "Signed in", command: "claude auth login" }, gh: { ok: false, detail: "Not signed in", command: "gh auth login" } }, builds_ok: false,
  build: { mode: "auto", concurrency: 1 }, topics: 1, sources: 3, scheduler: true, budget_usd: 10, cost: "About $5 to $8 a month for one topic with ten sources, on your own model key. Watching stops for the month at your cap of $10.00 (Spend).", first_brief_minutes: 5, every_hours: 3, brb: true, builds: true,
};
const refused = { ok: false, detail: "401", base_url: BASE, at: "2026-10-16T11:00:00Z" };
// The server's /api/setup/provider (providers.detect): an Anthropic key found in .env
const P: ProviderSetup = {
  current: { provider: "openai_compat", choice: "openrouter", label: "OpenRouter", endpoint: BASE, key_env: "OPENROUTER_API_KEY",
             models: { judge: "anthropic/claude-haiku-5.5", reason: "anthropic/claude-sonnet-5.5" }, tiers: { judge: "openai_compat", reason: "openai_compat" }, key_set: true },
  choices: ["anthropic", "openrouter", "openai_compat"],
  anthropic: { key_set: true, env: "ANTHROPIC_API_KEY", label: "Claude API" },
  openrouter: { key_set: true, env: "OPENROUTER_API_KEY", label: "OpenRouter" },
  openai_compat: { key_set: false, env: "OPENROUTER_API_KEY", label: "another endpoint", base_url: null },
  claude_code: { installed: true, version: "2.1.300", logged_in: true, auth_method: "claude.ai", subscription: "max", token_in_service: false, offered: true, label: "Claude Code", terms: "TERMS: what using your Claude plan means." },
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => {
  ui.facts = null;
  KEYBASE.v = null;
  KEYPROV.v = null;
  vi.useRealTimers();
});
/** the old module with its sticky details and its cached reads' drop */
function stubbed(answer: unknown = {}) {
  const L = stub({ answer });
  const sticky = vi.fn((el: HTMLElement, id: string) => { el.id = id; return el; }), afkDrop = vi.fn();
  Object.assign(L, { sticky, afkDrop });
  return { L, afkDrop };
}

describe("Settings › Watching", () => {
  it("words the model key", () => {
    expect(keyWords(S.key, NOW)).toEqual({ st: ["check", "green", "Works"], line: "OpenRouter. Works, 1 h ago. Kept in $OPENROUTER_API_KEY." });
    expect(keyWords({ ...S.key, set: false, test: null }).line).toBe("OpenRouter. Not chosen yet. Kranto reads nothing until a model is chosen.");
    expect(keyWords({ ...S.key, set: false, test: refused }).line).toBe("OpenRouter. Not chosen yet. Last try: 401.");
    expect(keyWords({ ...S.key, test: refused })).toEqual({ st: ["warn", "amber", "Check"], line: "OpenRouter. Set in $OPENROUTER_API_KEY, but the last key tried was refused: 401." });
    expect(keyWords({ ...S.key, test: null }).line).toBe("OpenRouter. Set in $OPENROUTER_API_KEY (in the environment or .env); not tested here.");
    expect(keyWords({ ...S.key, provider: "anthropic", choice: "anthropic", env: "ANTHROPIC_API_KEY", test: null }).line).toBe("Claude API. Set in $ANTHROPIC_API_KEY (in the environment or .env); not tested here.");
    // The server's choice is the answer: the Claude API, though llm.base_url is still OpenRouter's
    expect(providerOf({ ...S.key, provider: "anthropic", choice: "anthropic" })).toBe("anthropic");
    // a server before 0.3.84 sends no choice: worked out from the provider and the URL
    expect(providerOf({ ...S.key, choice: "", base_url: "http://127.0.0.1:4000/v1" })).toBe("openai_compat");
    expect(providerOf({ ...S.key, choice: "" })).toBe("openrouter");
  });

  it("lists the provider and its key, no logins (they left with builds), and needs the server", async () => {
    stub();
    hosted();
    answering({ [SETUP_API]: S });
    const { target, done } = await draw(KeysList, where("settings/keys"));
    expect(target.querySelector(".lh h1")?.textContent).toBe("Keys");
    const rows = [...target.querySelectorAll("li.row")];
    expect(rows.map((r) => r.getAttribute("data-sel"))).toEqual(["ekey"]);
    expect(rows[0]?.querySelector(".c-meta")?.textContent).toMatch(/^OpenRouter\. Works, /);
    expect(target.querySelector("input, textarea, select")).toBeNull();
    done();
    stub();
    ui.facts = null;
    const none = await draw(KeysList, where("settings/keys"));
    expect(none.target.querySelector("strong")?.textContent).toBe("Keys need the server. ");
    none.done();
  });

  it("says what is set now, and where keys are kept", async () => {
    stubbed();
    hosted();
    answering({ [SETUP_API]: S });
    const { target, done } = await draw(KeysPane, where("settings/keys"));
    expect(target.querySelector(".dk")?.textContent).toBe(" settings · watching");
    expect([...target.querySelectorAll("#s-state dt")].map((x) => x.textContent)[0]).toBe("Watching model");
    expect([...target.querySelectorAll("#s-state dd")].map((x) => x.textContent)).toEqual([expect.stringMatching(/^Works OpenRouter\. Works, .* Kept in \$OPENROUTER_API_KEY\.$/)]);
    expect(target.querySelector("#s-kept p")?.textContent).toContain("($OPENROUTER_API_KEY)");
    done();
    stub();
    ui.facts = null;
    const none = await draw(KeysPane, where("settings/keys"));
    expect(none.target.querySelector(".empty")?.textContent).toBe("Keys need the server, which is not hosting this page.");
    none.done();
    stub();
    hosted();
    const other = await draw(KeysPane, where("settings/keys", "enope"), "#/settings/keys");
    expect(other.target.querySelector(".empty")?.textContent).toBe("Nothing to show here.");
    other.done();
  });

  it("tests and keeps a key once, clears the field and keeps nothing of it", async () => {
    const { L, afkDrop } = stubbed({ test: { detail: "Works" } });
    hosted();
    answering({ [SETUP_API]: S });
    const { target, done } = await draw(KeysPane, where("settings/keys", "ekey"), "#/settings/keys");
    expect(target.querySelector(".dt")?.textContent).toBe("Watching model");
    const key = target.querySelector("#model-key") as HTMLInputElement, save = target.querySelector("#key-save") as HTMLButtonElement;
    expect(key.type).toBe("password");
    expect(key.autocomplete).toBe("off");
    expect(save.textContent).toBe("Test and replace");
    // OpenRouter is chosen now (an endpoint at openrouter.ai), and has no endpoint field
    expect((target.querySelector("#watch-openrouter") as HTMLInputElement).checked).toBe(true);
    expect(target.querySelector("#watch-openrouter")?.parentElement?.textContent).toBe(" OpenRouter (now)");
    expect(target.querySelector("#model-base")).toBeNull();
    save.click();
    expect(L.api).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(key);
    (target.querySelector("#watch-openai_compat") as HTMLInputElement).click();
    await settle();
    expect(KEYPROV.v).toBe("openai_compat");
    const base = target.querySelector("#model-base") as HTMLInputElement;
    expect(base.value).toBe("https://openrouter.ai/api/v1");
    base.value = "https://example.test/v1";
    base.dispatchEvent(new Event("input", { bubbles: true }));
    expect(KEYBASE.v).toBe("https://example.test/v1");
    key.value = "  a-pasted-value  ";
    save.click();
    expect(key.value).toBe("");
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "openai_compat", key: "a-pasted-value", base_url: "https://example.test/v1", replace: true });
    expect(afkDrop).toHaveBeenCalled();
    expect(L.say).toHaveBeenCalledWith("Saved: Works. Applies at once. The key is kept in this workspace's .env (readable by you only), never in a page or your settings.");
    expect(KEYPROV.v).toBeNull();
    expect(KEYBASE.v).toBeNull();
    expect(save.disabled).toBe(false);
    expect(save.textContent).toBe("Test and replace");
    // nothing on the page holds it: no field, no attribute, no text
    expect(new XMLSerializer().serializeToString(target)).not.toContain("a-pasted-value");
    done();
  });

  it("presses Test and save on a paste, and after a pause in typing something key-length", async () => {
    const { L } = stubbed({ test: { detail: "Works" } });
    hosted();
    answering({ [SETUP_API]: { ...S, done: false, key: { ...S.key, set: false, test: null } } });
    const { target, done } = await draw(KeysPane, where("settings/keys", "ekey"), "#/settings/keys");
    const key = target.querySelector("#model-key") as HTMLInputElement, save = target.querySelector("#key-save") as HTMLButtonElement;
    expect(save.className).toBe("btn primary");
    expect(save.textContent).toBe("Test and save");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    key.value = "short";
    key.dispatchEvent(new Event("paste", { bubbles: true }));
    vi.advanceTimersByTime(400);
    expect(L.api).not.toHaveBeenCalled();
    key.value = "aaaa-bbbb-cccc-dddd";
    key.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
    vi.advanceTimersByTime(1000);
    expect(L.api).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "openrouter", key: "aaaa-bbbb-cccc-dddd", replace: false });
    expect(key.value).toBe("");
    vi.useRealTimers();
    await settle();
    // enter is the same press
    key.value = "aaaa-bbbb-cccc-dddd";
    key.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(L.api).toHaveBeenCalledTimes(2);
    done();
  });

  it("chooses the Claude API with a key found in .env, without pasting it, and says what it means", async () => {
    const { L } = stubbed({ test: { detail: "the Claude API accepted the key: claude-haiku-5-5 and claude-sonnet-5-5 are offered" },
      models: { judge: "claude-haiku-5-5", reason: "claude-sonnet-5-5" } });
    hosted();
    answering({ [SETUP_API]: S, [PROVIDER_API]: P });
    const { target, done } = await draw(KeysPane, where("settings/keys", "ekey"), "#/settings/keys");
    (target.querySelector("#watch-anthropic") as HTMLInputElement).click();
    await settle();
    // B: what the key means, with no word of builds where a stranger chooses it
    expect(target.querySelector("#watch-about")?.textContent).toContain("billed at Anthropic's list prices");
    expect(target.querySelector("#watch-about")?.textContent).not.toMatch(/\bbuild/i);
    const save = target.querySelector("#key-save") as HTMLButtonElement;
    expect(save.textContent).toBe("Test and use");
    expect((target.querySelector("#model-key") as HTMLInputElement).placeholder).toBe("found in .env or the environment: click to use it, or paste another");
    save.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "anthropic", replace: true });
    expect(L.say).toHaveBeenCalledWith("Saved: the Claude API accepted the key: claude-haiku-5-5 and claude-sonnet-5-5 are offered. Applies at once. Watching with Claude API: judge claude-haiku-5-5, reason claude-sonnet-5-5.");
    done();
  });

  it("offers Claude Code's login last, never chosen, with its terms where it is chosen and no key", async () => {
    const { L } = stubbed({ test: { detail: "Claude Code 2.1.300, signed in (claude.ai, max)" }, models: { judge: "claude-haiku-5-5", reason: "claude-sonnet-5-5" } });
    hosted();
    answering({ [SETUP_API]: S, [PROVIDER_API]: P });
    const { target, done } = await draw(KeysPane, where("settings/keys", "ekey"), "#/settings/keys");
    const radios = [...target.querySelectorAll("input[name=watch-provider]")] as HTMLInputElement[];
    expect(radios.map((r) => r.value)).toEqual(["anthropic", "openrouter", "openai_compat", "claude_code"]);
    expect(radios.find((r) => r.checked)?.value).toBe("openrouter");
    (target.querySelector("#watch-claude_code") as HTMLInputElement).click();
    await settle();
    expect(target.querySelector("#watch-about")?.textContent).toBe("TERMS: what using your Claude plan means.");
    expect(target.querySelector("#watch-claude")?.textContent).toBe("Claude Code 2.1.300, signed in (claude.ai, max)");
    expect(target.querySelector("input[type=password]")).toBeNull();
    expect(target.querySelector(".lbl label")?.textContent).toBe("Login");
    const save = target.querySelector("#key-save") as HTMLButtonElement;
    expect(save.textContent).toBe("Use my Claude Code login");
    save.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "claude_code", replace: true, terms: true });
    expect(L.say).toHaveBeenCalledWith("Saved: Claude Code 2.1.300, signed in (claude.ai, max). Applies at once. Watching with Claude Code: judge claude-haiku-5-5, reason claude-sonnet-5-5.");
    done();
  });

  it("does not list Claude Code when the server does not offer it", async () => {
    stubbed();
    hosted();
    answering({ [SETUP_API]: S, [PROVIDER_API]: { ...P, claude_code: { ...P.claude_code, offered: false } } });
    const { target, done } = await draw(KeysPane, where("settings/keys", "ekey"), "#/settings/keys");
    expect([...target.querySelectorAll("input[name=watch-provider]")].map((r) => (r as HTMLInputElement).value)).toEqual(["anthropic", "openrouter", "openai_compat"]);
    done();
  });

  it("words Claude Code as the watcher: billed to the plan", () => {
    expect(keyWords({ ...S.key, provider: "claude_code", choice: "claude_code", env: "", test: null }).line).toBe("Claude Code. Uses your Claude Code login; billed to your plan.");
    // Claude Code gone since its last check: the login read just now wins over "Works"
    const ok = { ...S.key, provider: "claude_code", choice: "claude_code", env: "", test: { ok: true, detail: "Claude Code 2.1, signed in", base_url: "claude_code", at: new Date(NOW - 4 * 3600e3).toISOString() } };
    expect(keyWords(ok, NOW).st[2]).toBe("Works");
    expect(keyWords(ok, NOW, { ok: false, installed: false })).toEqual({ st: ["x", "red", "Can't be used"], line: "Claude Code. Not installed on this machine: Kranto reads nothing until it is. Install it, or choose another provider." });
    expect(keyWords(ok, NOW, { ok: false, installed: true }).line).toMatch(/Not signed in on this machine/);
  });

  it("has no logins pane: an old selection of them shows nothing", async () => {
    stubbed();
    hosted();
    answering({ [SETUP_API]: S });
    const { target, done } = await draw(KeysPane, where("settings/keys", "elogins"), "#/settings/keys");
    expect(target.querySelector(".pane-empty p")?.textContent).toBe("Nothing to show here.");
    done();
  });
});
