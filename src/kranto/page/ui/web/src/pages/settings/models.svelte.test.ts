import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import ModelsList from "./ModelsList.svelte";
import ModelsPane from "./ModelsPane.svelte";
import { AFK_MODELS, CATALOG, lastCall, PICK, roleSpecs, type AfkModels, watchingVia } from "./models.svelte";

const A: AfkModels = { routed: true, base_url: "https://openrouter.invalid/api/v1", config: "/h/kranto.yaml",
                       roles: [{ role: "judge", name: "Judge", model: "anthropic/claude-haiku-5.5", gate: 0.3 }, { role: "reasoner", name: "Reasoner", model: "anthropic/claude-opus-5.5" }] };
const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => {
  for (const k of Object.keys(PICK)) delete PICK[k];
  ui.facts = null;
  ui.area = "";
});

describe("Settings › Watching › Models (watching's roles alone)", () => {
  it("works out every role of watching under the router's names, the catalog's models offered", () => {
    const xs = roleSpecs(A);
    expect(xs.map((x) => [x.key, x.group, x.current])).toEqual([["afk:judge", "Watching", "anthropic/claude-haiku-5.5"], ["afk:reasoner", "Watching", "anthropic/claude-opus-5.5"]]);
    expect(xs[0]!.opts.map((o) => o[0])).toEqual(CATALOG.map((m) => m.router));
    expect(roleSpecs({ ...A, routed: false, roles: [{ role: "judge", name: "Judge", model: "claude-haiku-5-5" }] })[0]!.opts.map((o) => o[0])).toEqual(CATALOG.map((m) => m.id));
    // a model the catalog does not name is offered too, first
    expect(roleSpecs({ ...A, roles: [{ role: "judge", name: "Judge", model: "x/other" }] })[0]!.opts[0]).toEqual(["x/other", "x/other"]);
    expect(xs[0]!.endpoint).toBe("https://openrouter.invalid/api/v1, your model key");
  });

  it("lists the roles, a choice not saved marked", async () => {
    stub();
    hosted();
    answering({ [AFK_MODELS]: A });
    PICK["afk:reasoner"] = "anthropic/claude-sonnet-5.5";
    ui.area = "settings";
    const { target, done } = await draw(ModelsList, where("settings/models"));
    expect([...target.querySelectorAll("section.grp h2")].map((h) => h.textContent)).toEqual(["Models"]);
    expect([...target.querySelectorAll(".r-title")].map((t) => t.textContent)).toEqual(["Judge", "Reasoner"]);
    const r = target.querySelector('[data-sel="erole:afk:reasoner"]');
    expect(r?.querySelector(".c-meta")?.textContent).toBe("Sonnet 5.5");
    expect(r?.querySelector(".stw")?.textContent).toBe("Changed, not saved");
    expect(target.querySelector(".tbn")?.textContent).toBe("watching via https://openrouter.invalid/api/v1");
    done();
  });

  it("says the provider the watcher really uses, not the OpenAI-style endpoint left in the config", async () => {
    const C: AfkModels = { routed: false, base_url: "https://api.anthropic.com", config: "/h/kranto.yaml", provider: "anthropic", label: "Claude API",
                           endpoint: "https://api.anthropic.com", last_call: { provider: "anthropic", model: "claude-haiku-5-5", at: "2026-10-17T15:00:00Z" },
                           roles: [{ role: "judge", name: "Judge", model: "claude-haiku-5-5", gate: 0.03 }] };
    expect(watchingVia(C)).toBe("Claude API (https://api.anthropic.com)");
    expect(watchingVia({ ...C, provider: "claude_code", label: "Claude Code", endpoint: null })).toBe("Claude Code");
    expect(watchingVia(A)).toBe("https://openrouter.invalid/api/v1");
    expect(lastCall(C.last_call!, Date.parse("2026-10-17T15:10:00Z"))).toMatch(/^anthropic, claude-haiku-5-5, 10 min/);
    stub();
    hosted();
    answering({ [AFK_MODELS]: C });
    const { target, done } = await draw(ModelsList, where("settings/models"));
    const tools = target.querySelector(".tbn")?.textContent || "";
    expect(tools).toContain("watching via Claude API (https://api.anthropic.com)");
    expect(tools).not.toContain("openrouter");
    done();
  });

  it("says without the server that its models are not shown", async () => {
    stub();
    answering({});
    const l = await draw(ModelsList, where("settings/models"));
    expect(l.target.querySelector(".tbn")?.textContent).toBe("the server is not hosting this page: its models are not shown");
    l.done();
    stub();
    const p = await draw(ModelsPane, where("settings/models", "erole:afk:judge"));
    expect(p.target.querySelector(".pane-empty p")?.textContent).toBe("Watching's models are the server's, which is not hosting this page.");
    p.done();
  });

  it("writes nothing until Save, then saves the role's choice", async () => {
    const L = stub();
    hosted();
    answering({ [AFK_MODELS]: A });
    const { target, done } = await draw(ModelsPane, where("settings/models", "erole:afk:reasoner"));
    const save = target.querySelector("#save-afk\\:reasoner") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    const sel = target.querySelector("#model-afk\\:reasoner") as HTMLSelectElement;
    sel.value = "anthropic/claude-haiku-5.5";
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(L.api).not.toHaveBeenCalled();
    expect(target.querySelector(".pill")?.textContent).toBe("changed: from the next call");
    save.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(AFK_MODELS, { role: "reasoner", model: "anthropic/claude-haiku-5.5" });
    expect(L.toast).toHaveBeenCalledWith("Saved: Reasoner uses Haiku 5.5. Applies at once.", expect.any(Function));
    expect(PICK["afk:reasoner"]).toBeUndefined();
    done();
  });

  it("refuses a judge's gate out of range, before anything is written", async () => {
    const L = stub();
    hosted();
    answering({ [AFK_MODELS]: A, "/api/learning": { policies: [] } });
    const { target, done } = await draw(ModelsPane, where("settings/models", "erole:afk:judge"));
    const gate = target.querySelector("#gate-afk\\:judge") as HTMLInputElement;
    gate.value = "1.5";
    gate.dispatchEvent(new Event("input", { bubbles: true }));
    await settle();
    let thrown = "";
    L.act.mockImplementationOnce(async (_b: unknown, fn: () => Promise<unknown>) => { try { await fn(); } catch (e) { thrown = (e as Error).message; } });
    (target.querySelector("#save-afk\\:judge") as HTMLButtonElement).click();
    await settle();
    expect(thrown).toBe("The gate is a signal above 0 and at most 1.");
    expect(L.api).not.toHaveBeenCalled();
    done();
  });
});
