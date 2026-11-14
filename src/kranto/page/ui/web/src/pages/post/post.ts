// Post: one page, #/post, from the server's one read GET /api/post (web/post_api.py,
// the P1): the drafts that wait (a draft's ask has no time limit), what was sent, the three
// accounts, and the earlier drafts. Plain data and words, so the tests read them without a page.
import { href, matchRoute } from "../../lib/router";
import { afkDropPrefix } from "../../lib/app/data";
import { app } from "../../lib/shell.svelte";
import type { Post, PostAccount, PostDraft, PostFailed } from "../../api/afk.gen";
import type { About } from "../../features/post/post";

export type { Post, PostAccount, PostDraft, PostFailed };
export const POST_API = "/api/post";

/** where a draft opens: its sheet (#/post/d/<id>, the P2 adds the route), else the cub's page
 * with the draft's object selected, as today */
export function draftHref(d: Pick<PostDraft, "id" | "cub" | "ref">): string {
  if (matchRoute(["post", "d", String(d.id)])) return href(`post/d/${d.id}`);
  return href("cub/" + d.cub, { sel: "o" + d.ref });
}
/** whether a draft opens in the page's sheet route (else the ask's own dialog opens it) */
export const hasSheet = (): boolean => !!matchRoute(["post", "d", "1"]);

/** a sent post's line: the platform's own words, else what happened, else "Sent"; a short post
 * says where it went first ("Posted to Bluesky · posted by you") */
export function sentLine(d: PostDraft): string {
  const said = d.note || d.said || "Sent";
  // its numbers, where its site gives them, before the address (which the row may cut)
  const counted = d.reach && d.reach.words ? [d.reach.words] : [];
  return d.site_word ? [`Posted to ${d.site_word}`, ...counted, said].join(" · ") : [...counted, said].join(" · ");
}
/** a scheduled post's line: "Monday 16 Nov, 09:00 · Bluesky" (the person's own time) */
export function dueLine(d: Pick<PostDraft, "due_words" | "site_word">): string {
  return [d.due_words ? `Goes ${d.due_words}` : "Scheduled", d.site_word || ""].filter(Boolean).join(" · ");
}
/** a scheduled post's hour in the row's narrow age slot, which a phone keeps, on the person's
 * own clock: "09:00" today, "Tue" within the week, else "17 Nov" (the row's line says it all) */
export function dueShort(due: string | null | undefined, now: Date = new Date()): string {
  const t = due ? new Date(due) : null;
  if (!t || Number.isNaN(t.getTime())) return "";
  if (t.toDateString() === now.toDateString()) return `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  if (t.getTime() - now.getTime() < 6 * 86400_000) return t.toLocaleDateString("en-GB", { weekday: "short" });
  return t.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
/** Cancel a scheduled post: nothing is sent, and the draft waits on Post again */
export function cancelHour(btn: HTMLElement | null, id: number): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api(`/api/post/d/${id}/cancel`, {}), (r) => {
    afkDropPrefix("/api/post");
    L.afkDrop();
    L.say((r as { say?: string } | null)?.say || "Cancelled: nothing is sent.");
  });
}
/** a write's short posts as plain words, a tick on those sent: "Bluesky ✓ · Mastodon · X" */
export function sitesWords(d: Pick<PostDraft, "sites">): string {
  return (d.sites || []).map((x) => x.word + (x.state === "sent" ? " ✓" : "")).join(" · ");
}
/** Post's one line about where posts go: the server's sites line, then the blog and the
 * newsletter in a few words */
export function whereLine(p: Pick<Post, "sites" | "accounts">): string {
  const acct = (k: string) => (p.accounts || []).find((a) => a.key === k);
  const blog = acct("blog"), nl = acct("newsletter");
  const bits = [p.sites?.line || "No sites chosen for short posts yet."];
  bits.push(`Blog: ${blog && blog.state === "connected" ? "connected" : "not set"}.`);
  bits.push(`Newsletter: ${nl && nl.state === "connected" ? "connected" : "not set"}.`);
  return bits.join(" ");
}

/** an account's state in words: "connected as …", "needs signing in again", "not set" */
export function accountWords(a: PostAccount): string {
  if (a.state === "connected") return a.account ? `connected as ${a.account}` : a.platform ? `connected on ${a.platform}` : "connected";
  if (a.state === "needs_login") return "needs signing in again";
  return "not set";
}
/** where an account is connected or changed: the newsletter platform's sheet on Settings ›
 * Posting, a posting account's own sign-in page */
export function accountHref(a: PostAccount): string {
  if (a.key === "newsletter") return href("settings/posting", { sel: "enl" });
  // Mastodon here is the account Kranto posts from (mastodon_post), never the read-only one that
  // watches a timeline (7, Codex 4)
  return href("settings/connections/" + (a.key === "blog" ? "sanity" : a.key === "mastodon" ? "mastodon_post" : a.key));
}

/** a failed Write a post's line: "Write a blog post about ‹title› failed", its reason under it */
export function failedTitle(f: Pick<PostFailed, "as" | "title">): string {
  const what = f.as === "toot" ? "a short post" : f.as === "short" ? "short posts" : "a blog post";
  return `Write ${what} about ${f.title || "this"}: no draft`;
}
/** what a failed write was about, as Write a post's question knows it (Try again asks the same) */
export function failedAbout(f: Pick<PostFailed, "about" | "title">): About {
  const m = /^card:(\d+)$/.exec(f.about), b = /^brief:(\d+):(\d+)$/.exec(f.about);
  if (m) return { card: Number(m[1]), title: f.title || "", sources: 0 };
  if (b) return { brief: Number(b[1]), n: Number(b[2]) - 1, title: f.title || "", sources: 0 };
  return { week: true, title: "this week's news", sources: 0 };
}
/** the accounts connected (the group's count: "Accounts 3" with none connected read as three) */
export const connectedCount = (accounts: PostAccount[]): number => accounts.filter((a) => a.state === "connected").length;
/** the waiting draft a ticket asks to send, when its account is not connected: then the home's
 * one thing and Needs you say Open (its page, with Copy and Download), never Send ( *  they offered Send for a draft whose page said "Connect an account to send"); null otherwise */
export function unsendable(p: Pick<Post, "drafts"> | null | undefined, ticket: number | null | undefined): PostDraft | null {
  if (ticket == null || !p) return null;
  const d = (p.drafts || []).find((x) => x.ticket === ticket);
  return d && d.account === false ? d : null;
}
/** "Monday's issue", "from #143": the fact the read gives, else none (its kind is the row's mark;
 * the cub's name, "by examplecom", is never a fact: G4) */
export function draftFact(d: PostDraft): string {
  const sites = sitesWords(d);
  return [d.fact || "", sites].filter(Boolean).join(" · ");
}
