// Settings › Posting's sites: the server's GET /api/post/sites (every site Kranto offers, with the
// person's choices, and the ones it does not offer, with why) and POST /api/post/sites (the
// choices: sites ticked, Post directly per site, Mastodon's server, the disclosure line per
// site). Plain data and words, so the tests read them without a page.
import { afkDropPrefix } from "../../lib/app/data";
import { app } from "../../lib/shell.svelte";
import type { Posting, PostingSite } from "../../api/afk.gen";

export type { Posting, PostingSite };
export const POSTING_API = "/api/post/sites";

/** a ticked site's line: how it posts, in a few words, and the account when Kranto posts there */
export function siteLine(s: PostingSite): string {
  const open = s.ways.includes("open") ? (s.needs === "instance" && !s.instance ? "type your server to open it" : `opens ${s.name} with the draft ready`) : "";
  if (!s.direct) return open;
  const who = s.account ? `as ${s.account}` : "connect an account";
  return [open, `Kranto posts after your yes, ${who}`].filter(Boolean).join(" · ");
}

/** one change of the person's choices; the page reads Posting and Post again after it */
export function savePosting(btn: HTMLElement | null, body: Record<string, unknown>, said?: string): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api(POSTING_API, body), () => {
    afkDropPrefix("/api/post");
    L.afkDrop();
    if (said) L.say(said);
  });
}
