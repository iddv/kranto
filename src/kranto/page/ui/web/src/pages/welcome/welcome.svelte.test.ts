import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { KEYBASE, SETUP_API, type Setup } from "../settings/keys.svelte";
import { SOURCES_API } from "../settings/sources.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import Hello from "./Hello.svelte";
import Welcome from "./Welcome.svelte";
import { afterTopics, stepAt, STEPS, stepDone, TOPIC } from "./welcome.svelte";

// The server's /api/setup on a fresh install (Setup is generated from its web/types.py)
const S: Setup = {
  done: false, done_at: null, needs_setup: true, key: { set: false, env: "OPENROUTER_API_KEY", base_url: "https://openrouter.ai/api/v1", provider: "openai_compat", choice: "openrouter", label: "OpenRouter", endpoint: "https://openrouter.ai/api/v1", test: null },
  logins: { claude: { ok: true, detail: "Signed in", command: "claude auth login" }, gh: { ok: false, detail: "Not signed in", command: "gh auth login" } }, builds_ok: false,
  budget_usd: null, cost: "About $5 to $8 a month for one topic with ten sources, on your own model key. No cap is set; set one in Spend.", first_brief_minutes: 5, every_hours: 3, build: { mode: null, concurrency: 1 }, topics: 0, sources: 0, scheduler: true, brb: true, builds: false,
};
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
const at = (path: string): Where => ({ ...where(path), stage: true });
afterEach(() => {
  ui.facts = null;
  KEYBASE.v = null;
  TOPIC.t = null;
  history.replaceState(null, "", "#/");
});
function stubbed(answer: unknown = {}) {
  const L = stub({ answer, host: { budget_usd: 10 } });
  const sticky = vi.fn((el: HTMLElement, id: string) => { el.id = id; return el; }), afkDrop = vi.fn(), loadHost = vi.fn(async () => {});
  Object.assign(L, { sticky, afkDrop, loadHost });
  return { L, afkDrop, loadHost };
}

describe("first run", () => {
  it("opens the splash, whose one button is Set up Kranto", async () => {
    stub();
    const { target, done } = await draw(Hello, at("hello"));
    expect(target.querySelector("[data-title]")?.getAttribute("data-title")).toBe("Welcome");
    expect(target.querySelector(".splash h1")?.textContent).toBe("Kranto");
    const go = target.querySelector("#set-up") as HTMLAnchorElement;
    expect(go.textContent).toBe("Set up Kranto");
    expect(go.getAttribute("href")).toBe("#/welcome");
    done();
  });

  it("names the four steps by the route, and needs the server", async () => {
    expect(STEPS.map((s) => s[1])).toEqual(["Model", "First topic", "Ready", "How you write"]);
    expect([stepAt(undefined), stepAt("topics"), stepAt("finish"), stepAt("voice"), stepAt("building"), stepAt("publishing"), stepAt("nope")]).toEqual([0, 1, 2, 3, 0, 0, 0]);
    expect(afterTopics()).toBe("welcome/finish");
    expect([0, 1, 2].map((i) => stepDone(i, { key: { set: true }, topics: 1, done: false }))).toEqual([true, true, false]);
    expect(stepDone(0, null)).toBe(false);
    stubbed();
    hosted();
    answering({ [SETUP_API]: { ...S, key: { ...S.key, set: true }, topics: 1 }, "/api/topics": { topics: [] }, [SOURCES_API]: { sources: [] } });
    const { target, done } = await draw(Welcome, at("welcome/topics"));
    const line = target.querySelector(".steps-line") as HTMLElement;
    expect(line.textContent).toBe("Welcome · Model · Step 2 of 4: First topic · Ready · How you write");
    expect([...line.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual(["#/welcome", "#/welcome/finish", "#/welcome/voice"]);
    expect(line.querySelectorAll(".i.done").length).toBe(1); // the key is set; Ready is not done
    expect(line.textContent).not.toMatch(/Building|Publishing/);
    done();
    stub();
    ui.facts = null;
    const none = await draw(Welcome, at("welcome"));
    expect(none.target.querySelector("strong")?.textContent).toBe("Setup needs Kranto's server, which is not answering. ");
    none.done();
  });

  it("ticks only a step whose state is set, and offers no Scout that can only fail", async () => {
    stubbed();
    hosted();
    answering({ [SETUP_API]: S, "/api/topics": { topics: [] }, [SOURCES_API]: { sources: [] } });
    let v = await draw(Welcome, at("welcome/topics"));
    expect(v.target.querySelectorAll(".steps-line .i.done").length).toBe(0);
    expect((v.target.querySelector("#scout") as HTMLButtonElement).disabled).toBe(true);
    expect(v.target.querySelector("#scout-needs-key")?.textContent).toBe("Finding places needs a model from step 1 ›");
    v.done();
    stubbed();
    hosted();
    answering({ [SETUP_API]: { ...S, key: { ...S.key, set: true } }, "/api/topics": { topics: [] }, [SOURCES_API]: { sources: [] } });
    v = await draw(Welcome, at("welcome/topics"));
    expect((v.target.querySelector("#scout") as HTMLButtonElement).disabled).toBe(false);
    expect(v.target.querySelectorAll(".steps-line .i.done").length).toBe(1);
    v.done();
  });

  it("step 1 on a machine without Claude Code: the login's box says it was not found, once, and never 'Found'", async () => {
    stubbed({ test: { detail: "Works" } });
    hosted();
    // The server offers the login wherever it could be chosen (offered: true), whatever is here
    answering({ [SETUP_API]: S, "/api/setup/provider": { claude_code: { installed: false, logged_in: false, offered: true, version: null, auth_method: null, subscription: null, token_in_service: false } } });
    const { target, done } = await draw(Welcome, at("welcome"));
    await settle();
    const box = target.querySelector("#way-login")?.textContent || "";
    expect(box).not.toContain("Found on this machine");
    expect(box.split("Not found on this machine").length - 1).toBe(1);
    expect(box).not.toContain("not installed on this machine");
    expect(target.querySelector("#way-login #key-save")).toBeNull();
    done();
  });

  it("step 1 with Claude Code installed but signed out: never 'Found on this machine, signed in'", async () => {
    stubbed({ test: { detail: "Works" } });
    hosted();
    answering({ [SETUP_API]: S, "/api/setup/provider": { claude_code: { installed: true, logged_in: false, offered: true, version: "2.1", auth_method: null, subscription: null, token_in_service: false } } });
    const { target, done } = await draw(Welcome, at("welcome"));
    await settle();
    const box = target.querySelector("#way-login")?.textContent || "";
    expect(box).not.toContain("Found on this machine");
    expect(box).toContain("not signed in");
    done();
  });

  it("step 1: the ways in as boxes, the login last (F-3 unanswered) and never preselected, one primary", async () => {
    const { L } = stubbed({ test: { detail: "Works" } });
    hosted();
    answering({ [SETUP_API]: S, "/api/setup/provider": { claude_code: { installed: true, logged_in: true, offered: true, version: "2.1", auth_method: "claude.ai", subscription: "max", token_in_service: false } } });
    const { target, done } = await draw(Welcome, at("welcome"));
    await settle();
    expect(target.querySelector(".ph h1")?.textContent).toBe("Which model reads for you?");
    expect(target.querySelector(".ph-meta")?.textContent).toBe("Kranto reads nothing until a model is chosen. Choose one way in.");
    expect([...target.querySelectorAll(".box.way h2")].map((h) => h.textContent)).toEqual(["A model key", "Your Claude Code login"]);
    expect(target.querySelector("#way-login")?.textContent).toContain("Anthropic's terms describe a subscription login as meant for your own, individual use.");
    expect([...target.querySelectorAll(".btn.primary")].map((b) => b.id)).toEqual(["way-key-open"]);
    expect(target.querySelector("#way-login #key-save")?.textContent).toBe("Use my Claude Code login");
    expect(target.querySelector("#usage-reports")).toBeNull();               // the question is Ready's
    const go = target.querySelector("#continue") as HTMLAnchorElement;
    expect(go.getAttribute("href")).toBe("#/welcome/topics");
    expect(go.getAttribute("aria-disabled")).toBe("true");
    expect(target.querySelector(".wizard-foot .muted")?.textContent).toBe("Continue needs a model that works.");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    go.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    // the login: one press, its terms said
    (target.querySelector("#way-login #key-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "claude_code", replace: false, terms: true });
    // Paste a key opens the keys' form: three keys, no login among them
    (target.querySelector("#way-key-open") as HTMLButtonElement).click();
    await settle();
    expect([...target.querySelectorAll("#way-key input[name=watch-provider]")].map((r) => (r as HTMLInputElement).value)).toEqual(["anthropic", "openrouter", "openai_compat"]);
    const key = target.querySelector("#way-key #model-key") as HTMLInputElement;
    expect(key.type).toBe("password");
    // nothing typed: it says so (fix 11)
    (target.querySelector("#way-key #key-save") as HTMLButtonElement).click();
    expect(L.say).toHaveBeenCalledWith("Paste a key first.", "amber");
    key.value = "a-key-of-some-length";
    (target.querySelector("#way-key #key-save") as HTMLButtonElement).click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/setup/provider", { provider: "openrouter", key: "a-key-of-some-length", replace: false });
    expect(key.value).toBe("");
    done();
  });

  it("step 1 lets Continue through once the key is set", async () => {
    stubbed();
    hosted();
    answering({ [SETUP_API]: { ...S, key: { ...S.key, set: true } } });
    const { target, done } = await draw(Welcome, at("welcome"));
    const go = target.querySelector("#continue") as HTMLAnchorElement;
    expect(go.hasAttribute("aria-disabled")).toBe(false);
    expect(target.querySelector(".wizard-foot .muted")).toBeNull();
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    go.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false);
    done();
  });
});
