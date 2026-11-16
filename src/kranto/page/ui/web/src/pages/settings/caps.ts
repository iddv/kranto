// Settings › Spend › Caps: every spend cap in one list, each
// with its own field, Save and Undo, all the server's (POST /api/settings/spend). Empty is no cap
// everywhere (spend is uncapped by default).
import type { Effect } from "../../lib/words";
import type { WatchCaps } from "./spend.svelte";

export interface CapDef {
  key: string;
  word: string;
  /** The server's body key */
  field: string;
  effect: Effect;
  hint: string;
  get: (w: WatchCaps | null) => number | null | undefined;
}

export const CAP_DEFS: CapDef[] = [
  { key: "watch", word: "Watching a month", field: "monthly_usd", effect: "now", get: (w) => w?.monthly_usd,
    hint: "Model calls for ingest, the map and idea cards stop when it is reached; a warning shows at 80%." },
  { key: "x", word: "X a month", field: "x_monthly_usd", effect: "now", get: (w) => w?.x?.monthly_usd,
    hint: "X bills your developer account per post read. Reached, X sources wait until the first of next month; the Developer Console's own spending limit stops X itself." },
  { key: "search", word: "Live search a month", field: "search_monthly_usd", effect: "now", get: (w) => w?.search?.monthly_usd,
    hint: "Paid web searches (Exa with a key, Brave, Tavily, Anthropic's tool) pause for the month at this; Exa's free mode and Hacker News, GitHub and arXiv are free and keep answering. Paused, a caller says its results are from model memory." },
  { key: "dive", word: "Deep dives a day", field: "deep_dive_daily_usd", effect: "now", get: (w) => w?.deep_dive.daily_usd,
    hint: "Deep dives stop for the day at this, within watching's monthly cap." },
];
export const capDef = (k: string): CapDef | null => CAP_DEFS.find((d) => d.key === k) || null;

/** a selection from before (sel=ecaps:watch …) to the cap it meant first */
export const OLD_CAP: Record<string, string> = { "caps:watch": "watch" };
