// Settings › Privacy & access (OI): who may act on Kranto. Every write needs a token: this page's (its
// session), kranto mcp's, the command line's, and named agents, each with its own. Values never
// reach the page: each lives in its own file at mode 600, which the agent reads. From the server's
// /api/tokens; `kranto token` does the same.
export const ACCESS_API = "/api/tokens";

export interface Token {
  name: string;
  file: string;
  last_used?: number | null;
  note?: string | null;
  actions?: string[] | null;
}
export interface Tokens {
  tokens: Token[];
  require_token: boolean;
  default_actions?: string[];
}

export const DOOR_WORD: Record<string, string> = { ui: "This page", mcp: "kranto mcp", cli: "The command line" };
export const DOOR_MAY: Record<string, string> = {
  ui: "Everything, the confirm class after its dialog. A browser gets it with the one-time link kranto open prints.",
  mcp: "What kranto mcp offers: every action; the confirm class only with confirm: true. mcp.actions: false in your settings makes it read only.",
  cli: "Everything (kranto update's hold, your own scripts). Kranto command itself acts on the files and says cli in the history.",
};
export const isAgent = (t: Token): boolean => t.name.startsWith("agent:");
export const tokWord = (t: Token): string => (isAgent(t) ? "agent " + t.name.slice(6) : DOOR_WORD[t.name] || t.name);
/** an agent's name: letters, digits, _ . - (the server says the same) */
export const AGENT_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$/;
