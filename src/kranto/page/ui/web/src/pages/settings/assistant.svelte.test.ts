// Settings › Assistant, drawn (the owner's answers of 2026-10-25). Q2: switching whose
// configuration offers to restart the console now (it resumes the conversation); the panel's ⋯
// names the outside MCP servers. Q6: "Add Kranto to my own Claude Code…" shows the exact change
// first and writes only on Add. Before, the page said "⋯ › End this session, then open it
// again" and named the command line.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answerDialog, dialogShown } from "../../ui/testing";
import { answering, draw, settle, stub, where } from "../testing.svelte";
import { consoleUi, type ConsoleState } from "../../term/console.svelte";
import AssistantPane from "./AssistantPane.svelte";
import { CONSOLE_API, GLOBAL_API } from "./assistant";

const STATE: ConsoleState = {
  settings: { open: true, harness: "claude", model: {}, permission: "auto", config: "kranto", daily_usd: null },
  harness: "claude",
  harnesses: [{ id: "claude", name: "Claude Code", installed: true, models: [], extras: true },
    { id: "codex", name: "Codex", installed: true, models: [], extras: false }],
  conversations: {}, plugin: true, head: null, why: null, outside: ["github", "postgres"],
};
const PLAN = { harness: "claude", steps: ["claude plugin marketplace add iddv/kranto", "claude plugin install Kranto@Kranto"],
  files: [], missing: [], says: "This changes your own configuration, outside Kranto's folder. Nothing is changed until you click Add." };

function fetching(answers: Record<string, unknown>) {
  const sent: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (init?.method === "POST") sent.push({ url, body });
    const key = Object.keys(answers).find((k) => url.startsWith(k));
    return new Response(JSON.stringify(key ? answers[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  }));
  return sent;
}

afterEach(() => {
  vi.unstubAllGlobals();
  ui.facts = null;
});

describe("Settings › Assistant", () => {
  it("offers Restart the console now after a change it takes at its start", async () => {
    stub({});
    answering({ [CONSOLE_API]: STATE });
    const sent = fetching({ "api/term/console/settings": { ...STATE, settings: { ...STATE.settings, config: "own" }, restart: true } });
    const { target, done } = await draw(AssistantPane, where("settings/assistant", "econ-config"));
    await settle();
    expect(target.querySelector("#console-restart")).toBeNull();
    const own = [...target.querySelectorAll<HTMLInputElement>("input[name=cfg]")][0]!;
    own.click();
    await settle();
    await settle();
    expect(sent).toEqual([{ url: "api/term/console/settings", body: { config: "own" } }]);
    const press = target.querySelector<HTMLButtonElement>("#console-restart");
    expect(press?.textContent).toBe("Restart the console now");
    expect(target.textContent).toContain("your conversation is resumed");
    const before = consoleUi.restart.n;
    press!.click();
    await settle();
    expect(consoleUi.restart.n).toBe(before + 1);                 // the panel ends and resumes
    expect(target.querySelector("#console-restart")).toBeNull();
    expect(target.textContent).toContain("the same conversation");
    done();
  });

  it("names the outside MCP servers your own configuration loads", async () => {
    stub({});
    answering({ [CONSOLE_API]: { ...STATE, settings: { ...STATE.settings, config: "own" } } });
    fetching({});
    const { target, done } = await draw(AssistantPane, where("settings/assistant", "econ-config"));
    await settle();
    expect(target.textContent).toContain("(now: github, postgres)");
    done();
  });

  it("adds Kranto to your own Claude Code only after the change is shown and Add is pressed", async () => {
    stub({ host: {} });
    ui.facts = { header: { host: { paused: false, running: null, next: null }, run: [] } } as unknown as Facts;
    answering({ [CONSOLE_API]: STATE });
    const sent = fetching({ [GLOBAL_API]: PLAN });
    const { target, done } = await draw(AssistantPane, where("settings/assistant", "eoutside"));
    await settle();
    target.querySelector<HTMLButtonElement>("#add-global-claude")!.click();
    await settle();
    await settle();
    const d = dialogShown();
    expect(d?.title).toBe("Add Kranto to your own Claude Code?");
    expect(d?.text).toContain("$ claude plugin install Kranto@Kranto");
    expect(d?.text).toContain("Nothing is changed until you click Add");
    expect(sent).toEqual([]);                                      // shown: nothing written
    await answerDialog(true);
    await settle();
    expect(sent).toEqual([{ url: GLOBAL_API, body: { harness: "claude" } }]);
    done();
  });
});
