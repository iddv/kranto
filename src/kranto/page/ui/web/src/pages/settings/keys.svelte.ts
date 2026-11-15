// Settings › Watching and onboarding's first step (PLAN.md section 1.5): the server's /api/setup says
// whether setup is done, which provider watches and whether its key is set (never the key), its
// last answer, and Claude Code's login (Welcome's Ready); /api/setup/provider (the server's providers.detect)
// says which keys are found, so a key already set can be chosen without pasting it. The key goes in a password field that is read once when it is
// sent, cleared then and never kept (KeyField.svelte): the page only ever learns "set" and what
// the endpoint said. /api/setup is generated from the server's web/types.py (api/afk.gen.ts).
import type { ProviderSetup, SetupKey as KeyState } from "../../api/afk.gen";
import { dt, rel } from "../../lib/format";
import { app } from "../../lib/shell.svelte";
import { PRODUCT } from "../../lib/product";
import type { St } from "../../ui/settings";
export type { Login, ProviderSetup, SetupKey as KeyState, Setup } from "../../api/afk.gen";

export const SETUP_API = "/api/setup";
export const PROVIDER_API = "/api/setup/provider";

/** the watcher's providers, in the order they are offered (MP D12): three keys, then Claude
 * Code's login, which is never preselected and is shown only when the server offers it */
export type Choice = "anthropic" | "openrouter" | "openai_compat" | "claude_code";
export const CHOICES: readonly Choice[] = ["anthropic", "openrouter", "openai_compat", "claude_code"];
export const LABEL: Record<string, string> = { anthropic: "Claude API", openrouter: "OpenRouter", openai_compat: "Another service", claude_code: "Claude Code" };
/** what a choice means, said where it is chosen (OpenRouter needs no words) */
export const ABOUT: Record<Choice, string> = {
  anthropic: "An Anthropic API key, from the Claude Console. Kranto keeps the parts of its prompts that repeat cached, and is billed at Anthropic's list prices.",
  openrouter: "",
  openai_compat: "Another service that speaks OpenAI's API, with its address. The address is kept in your settings when its key passes.",
  // The server's own sentence (providers.CLAUDE_CODE_TERMS) is shown when it says one
  claude_code: "Claude Code as the watching model uses your Claude plan's usage, shared with your own Claude Code; when a usage window closes, watching pauses until it reopens. Anthropic's terms describe subscription login as meant for ordinary, individual use and ask developers building products to use API keys.",
};

/** Claude Code's state on this machine, in words (providers.detect) */
export function claudeWords(c: ProviderSetup["claude_code"]): string {
  if (!c.installed) return "Claude Code is not installed on this machine.";
  const how = [c.auth_method, c.subscription].filter(Boolean).join(", ");
  return `Claude Code ${c.version || ""}`.trim() + (c.token_in_service ? ", with Kranto's CLAUDE_CODE_OAUTH_TOKEN" : c.logged_in ? `, signed in${how ? ` (${how})` : ""}` : ", not signed in: run claude auth login");
}

/** the provider the tiers use now, as one of the choices (an endpoint at openrouter.ai is
 * OpenRouter): the server's providers.in_use says it; before 0.3.84 it is worked out here */
export function providerOf(k: KeyState): string {
  if (k.choice) return k.choice;
  const p = k.provider || "openai_compat";
  return p === "openai_compat" && /^https:\/\/openrouter\.ai\//.test(k.base_url) ? "openrouter" : p;
}

/** the choice being made, kept across draws and between Settings › Watching and the welcome step;
 * null: the provider the server has */
export const KEYPROV = $state<{ v: Choice | null }>({ v: null });

/** the watching model's state and line, for the row, the pane and onboarding: which provider,
 * and its key. ``claude``: Claude Code's login as the server read it just now (/api/setup's
 * logins.claude): when Claude Code is the model and it is missing or signed out, that wins
 * over the last stored check ("Works … signed in, 4 h ago" with Claude Code gone) */
export function keyWords(k: KeyState, now: number = Date.now(), claude: { ok?: boolean; installed?: boolean } | null = null): { st: St; line: string } {
  const t = k.test, who = LABEL[providerOf(k)] || k.provider;
  if (k.provider === "claude_code" && claude && claude.ok === false) {
    return { st: ["x", "red", "Can't be used"],
      line: claude.installed === false ? `${who}. Not installed on this machine: ${PRODUCT} reads nothing until it is. Install it, or choose another provider.`
        : `${who}. Not signed in on this machine: ${PRODUCT} reads nothing until it is. Run claude once to sign in, or choose another provider.` };
  }
  if (k.provider === "claude_code") {
    return { st: t && !t.ok ? ["warn", "amber", "Check"] : ["check", "green", "Works"],
      line: `${who}. ` + (t ? (t.ok ? `${t.detail}, ${rel(dt(t.at), now)}. Billed to your Claude plan.` : `The last check failed: ${t.detail}.`) : "Uses your Claude Code login; billed to your plan.") };
  }
  return {
    st: !k.set ? ["x", "red", "Not chosen yet"] : t && !t.ok ? ["warn", "amber", "Check"] : ["check", "green", "Works"],
    line: `${who}. ` + (!k.set ? (t && !t.ok ? `Not chosen yet. Last try: ${t.detail}.` : `Not chosen yet. ${PRODUCT} reads nothing until a model is chosen.`)
      : t ? (t.ok ? `${t.detail}, ${rel(dt(t.at), now)}. Kept in $${k.env}.` : `Set in $${k.env}, but the last key tried was refused: ${t.detail}.`)
        : `Set in $${k.env} (in the environment or .env); not tested here.`),
  };
}

/** the endpoint field while it is edited (not secret), kept across draws and between Settings ›
 * Keys and the welcome step; null: what the server has */
export const KEYBASE = $state<{ v: string | null }>({ v: null });

/** a press's button is usable again once it is done (the old page drew a fresh one) */
export function free(btn: HTMLElement): void {
  (btn as HTMLButtonElement).disabled = false;
  btn.removeAttribute("aria-busy");
}
/** Check again: the server looks at the logins again (Welcome's Ready) */
export function checkAgain(btn: HTMLElement): void {
  const L = app();
  if (!L) return;
  void L.act(btn, async () => {
    try {
      await L.api("/api/setup/check", {});
    } finally {
      L.afkDrop();
    }
  }).finally(() => free(btn));
}
