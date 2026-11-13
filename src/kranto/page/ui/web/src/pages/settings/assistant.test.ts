// Settings › Assistant's words: the console's rows, a ladder row's summary with its lock,
// and the ladder saved with one kind changed.
import { describe, expect, it } from "vitest";
import { consoleRows, ladderSummary, withKind, type Ladder } from "./assistant";
import type { ConsoleState } from "../../term/console.svelte";

const state: ConsoleState = {
  settings: { open: true, harness: null, model: { claude: "claude-sonnet-5-5" }, permission: "auto", config: "own", daily_usd: null },
  harness: "claude",
  harnesses: [
    { id: "claude", name: "Claude Code", installed: true, models: [{ id: "claude-sonnet-5-5", name: "Sonnet 5.5" }], extras: true },
    { id: "codex", name: "Codex", installed: false, models: [], extras: false },
  ],
  conversations: {}, plugin: true, head: null, why: null,
};

describe("Settings › Assistant", () => {
  it("says the console's settings in one line each", () => {
    const rows = Object.fromEntries(consoleRows(state).map((r) => [r.key, r.summary]));
    expect(rows["con-open"]).toMatch(/^On/);
    expect(rows["con-harness"]).toBe("Claude Code");
    expect(rows["con-model"]).toBe("Sonnet 5.5");
    expect(rows["con-permission"]).toMatch(/auto mode/);
    expect(rows["con-config"]).toMatch(/^Your own/);
    expect(rows["con-cap"]).toBe("None");
  });

  it("says a lock and a choice that differs from the default", () => {
    expect(ladderSummary({ kind: "credential", words: "Keys", choice: "never", default: "never", locked: true, why: "pasted by you" }))
      .toBe("Never · locked: pasted by you");
    expect(ladderSummary({ kind: "spend", words: "Spending", choice: "ask", default: "do", locked: false, why: "" }))
      .toBe("Ask me in the UI (default: Do it)");
  });

  it("saves one kind, keeping the others and the verbs' exceptions", () => {
    const l: Ladder = { ladder: { kinds: { outward: "ask" }, verbs: { "topic.add": "do" } }, kinds: [], choices: [] };
    expect(withKind(l, "spend", "ask")).toEqual({ ladder: { kinds: { outward: "ask", spend: "ask" }, verbs: { "topic.add": "do" } } });
  });
});
