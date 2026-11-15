// The one head every page starts with, drawn by the shell (shell/PageHead.svelte)
// from a declaration: the page says its title, facts, lede, one primary, its other verbs, its line
// and its flash (ui/PageTitle.svelte, or List's props); the door says the crumb, the glyph, the gear
// and the subnav (this table and chrome.ts's DOOR_NAV). A page never draws a head of its own.
import type { MenuItem } from "./types";
import { ui } from "../shell.svelte";

/** a verb in the head: the one primary, or Stop (a link when it has an address) */
export interface HeadVerb {
  label: string;
  /** a plain button: the page's one primary is elsewhere (Needs you's one thing, R3) */
  plain?: boolean;
  id?: string | null;
  title?: string | null;
  run?: ((btn: HTMLElement) => void) | null;
  href?: string | null;
  disabled?: boolean;
}
/** a tag on the facts line or beside the title: a mode (dry · paper · live · reads only · off) or a trust word */
export interface HeadTag {
  w: string;
  cls: string;
  title?: string | null;
}
/** the head's one flash (off › dry or paper › paused › waiting › a notice) */
export interface HeadFlash {
  kind: "amber" | "blue" | "red";
  text: string;
  link?: { href: string; w: string } | null;
}
/** what a page says of itself; everything but the title is optional */
export interface HeadDecl {
  title: string;
  /** the tab's title (data-title) when it is not the title */
  label?: string | null;
  /** a tip id beside the title (the ? sheet), for a page whose meaning is not in its words */
  about?: string | null;
  /** one muted line under the title, in words */
  facts?: string | null;
  /** the mode tag first on the facts line */
  tags?: HeadTag[] | null;
  /** the trust tag beside the title (a feature's or a cub's) */
  trust?: HeadTag | null;
  glyph?: string | null;
  wash?: string | null;
  lede?: string | null;
  ledeId?: string | null;
  primary?: HeadVerb | null;
  stop?: HeadVerb | null;
  more?: MenuItem[] | null;
  /** the gear's address: Settings › this feature (a door's default when absent) */
  gear?: string | null;
  /** ACT's RunLine subject for the page's subject (kind:ingest, topic:13, feature:toot) */
  line?: string | null;
  lineId?: string | null;
  flash?: HeadFlash | null;
  /** a page outside the doors (Cubs, a cub, Settings › <Feature>): its crumb after Home, and its subnav */
  crumb?: { to: string; w: string }[] | null;
  sub?: { to: string; w: string; n?: number | null; tone?: string; on: boolean; title?: string | null }[] | null;
  /** an object's page (pages/Page.svelte): its outline is in the subnav's slot, so the door's words are not drawn */
  outline?: boolean;
}

/** each door's glyph, its wash, its gear (Settings › the door's page) and its line */
export const DOOR_HEADS: Record<string, { glyph: string; wash: string; gear: string | null; line?: string }> = {
  watch: { glyph: "◉", wash: "blue", gear: "settings/watching", line: "kind:ingest" },
  ideas: { glyph: "◆", wash: "violet", gear: "settings/watching", line: "kind:ideas" },
  news: { glyph: "▤", wash: "blue", gear: "settings/news", line: "kind:news.brief" },
  needs: { glyph: "!", wash: "amber", gear: null },
  activity: { glyph: "⟳", wash: "blue", gear: "settings/system" },
  settings: { glyph: "⚙", wash: "grey", gear: null },
};

let n = 0;
/** a page's declaration, until the page goes (the function it returns); the latest one wins */
export function declareHead(d: HeadDecl): () => void {
  const mine = ++n;
  ui.head = { ...d, n: mine };
  return () => {
    if (ui.head && ui.head.n === mine) ui.head = null;
  };
}
