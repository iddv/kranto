// Settings › Assistant: the console's settings (the page's
// loop.yaml ask:, api/term/console) and what an assistant may do by itself (the server's ladder,
// /api/settings/assistant). Plain data and words, so the tests read them without a page.
import type { ConsoleSettings, ConsoleState } from "../../term/console.svelte";

export const CONSOLE_API = "api/term/console";
export const LADDER_API = "/api/settings/assistant";

export interface LadderKind {
  kind: string;
  words: string;
  choice: "do" | "ask" | "never";
  default: "do" | "ask" | "never";
  locked: boolean;
  why: string;
}
export interface Ladder {
  ladder: { kinds: Record<string, string>; verbs: Record<string, string> };
  kinds: LadderKind[];
  choices: { choice: string; words: string }[];
}

export const CHOICE_WORDS: Record<string, string> = { do: "Do it", ask: "Ask me in the UI", never: "Never" };
export const PERMISSION_WORDS: Record<ConsoleSettings["permission"], string> = {
  auto: "Decides by itself (Claude Code's auto mode); Kranto's own tools follow the ladder below",
  ask: "Asks you before edits and commands",
  "accept-edits": "Edits by itself, asks before commands",
};
export const CONFIG_WORDS: Record<ConsoleSettings["config"], string> = {
  own: "Your own: your login, settings, plugins, MCP servers and CLAUDE.md, as in your terminal",
  kranto: "Kranto's only: Kranto's plugin and settings, Kranto's Claude token",
};
export const GLOBAL_API = "/api/assistant/global";
/** what adding Kranto to your own client changes (the server shows it before anything is written) */
export interface GlobalPlan {
  harness: "claude" | "codex";
  steps: string[];
  files: { path: string; state: string }[];
  missing: string[];
  says: string;
  done?: boolean;
}
/** the confirm's lines: the commands it runs and the files it writes, as they will be */
export function globalLines(p: GlobalPlan): string[] {
  return [p.says, ...p.steps.map((s) => "$ " + s),
    ...p.files.filter((f) => f.state !== "same").map((f) => `${f.state === "new" ? "writes" : "updates"} ${f.path}`)];
}
export const HARNESS_NAME: Record<string, string> = { claude: "Claude Code", codex: "Codex" };

export const OUTSIDE_LINES = [
  "claude plugin marketplace add iddv/kranto && claude plugin install Kranto@Kranto",
  "codex mcp add kranto -- kranto mcp --compact",
  "claude mcp add kranto -- kranto mcp",
];

/** the console rows' one-line summaries */
export function consoleRows(s: ConsoleState): { key: string; word: string; summary: string }[] {
  const st = s.settings;
  const h = s.harness ? s.harnesses.find((x) => x.id === s.harness) : null;
  const model = h ? st.model[h.id] : "";
  const modelName = h && model ? h.models.find((m) => m.id === model)?.name || model : "its own default";
  return [
    { key: "con-open", word: "Open when Kranto opens", summary: st.open ? "On: the console is open on the right" : "Off: it waits on the rail" },
    { key: "con-harness", word: "Assistant", summary: h ? h.name + (h.extras ? "" : " (fewer extras: no status line, spend not reported)") : "None installed on Kranto's PATH" },
    { key: "con-model", word: "Model", summary: modelName },
    { key: "con-permission", word: "Before edits and commands", summary: PERMISSION_WORDS[st.permission] },
    { key: "con-config", word: "Whose configuration", summary: CONFIG_WORDS[st.config] },
    { key: "con-cap", word: "Spend cap a day", summary: st.daily_usd ? `$${st.daily_usd.toFixed(2)}: the console ends when it is reached` : "None" },
  ];
}

/** a ladder row's one-line summary: its choice, and the lock's reason */
export function ladderSummary(k: LadderKind): string {
  return CHOICE_WORDS[k.choice] + (k.locked ? ` · locked: ${k.why}` : k.choice !== k.default ? ` (default: ${CHOICE_WORDS[k.default]})` : "");
}

/** the ladder as it is saved with one kind's choice changed */
export function withKind(l: Ladder, kind: string, choice: string): { ladder: { kinds: Record<string, string>; verbs: Record<string, string> } } {
  return { ladder: { kinds: { ...l.ladder.kinds, [kind]: choice }, verbs: { ...l.ladder.verbs } } };
}
