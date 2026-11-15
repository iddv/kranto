// Post: Write a post's question, and a draft's sheet with Copy and Download. The
// page reads the server's GET /api/post and /api/post/d/<id>, and asks POST /api/post/write; the
// Post page itself (SHELL's pages/post) lists the drafts and mounts the sheet.
import { openDialog } from "../../ui/dialog.svelte";
import { toast } from "../../ui/toast.svelte";
import { app } from "../../lib/shell.svelte";
import { afkDropPrefix } from "../../lib/app/data";
import WritePostDialog from "./WritePostDialog.svelte";
import AboutWhatDialog from "./AboutWhatDialog.svelte";

export type PostKind = "newsletter" | "mastodon" | "blog" | string;
export interface PostAccount {
  key: "newsletter" | "mastodon" | "blog";
  word: string;
  state: string;
  account: string | null;
  platform: string | null;
}
export interface PostDraft {
  id: number; ref: string; cub: string; kind: PostKind; word: string; title: string; fact: string;
  at: string; ticket: number | null; again: number | null; verb: string | null; line: string | null;
  said: string | null; note: string | null; link: string | null; account: boolean;
  // a short post's own: its site, the write it belongs to, how it goes
  site?: string; site_word?: string; group?: string | null; way?: "open" | "direct";
  sites?: PostSibling[];
}
/** one site of a write's short posts: its newest draft and where it stands */
export interface PostSibling { id: number; site: string; word: string; state: string }
export interface Post {
  line: string;
  drafts: PostDraft[];
  sent: PostDraft[];
  earlier: PostDraft[];
  accounts: PostAccount[];
}
/** one part of a short post or a thread (`used` is its count, the site's way) */
export interface PostPart { text: string; used?: number }
/** what else goes with the words (SOCIAL's `extras`): a muted line each; `drop` offers Remove */
export interface PostExtra { key: string; words: string; drop?: boolean }
export interface PostSheet extends PostDraft {
  group: "waiting" | "sent" | "earlier";
  markdown: string;
  filename: string;
  words: number;
  account_of: PostAccount | null;
  // the editor: the words it opens with, whether it may, the limit a part has
  edit?: { title: string | null; body?: string; parts?: PostPart[] };
  can_edit?: boolean;
  cannot_edit?: string | null;
  limit?: { max: number; unit: string } | null;
  edited?: boolean;
  // who edited it, in words: "edited by you", "edited by your assistant (mcp)", "edited"
  edited_words?: string | null;
  edited_from?: number | null;
  // what a short post was written from: the draft page's check flags a name these lack
  sources?: string | null;
  original_draft?: number;
  // SOCIAL's read fields, drawn when present: the editor uses parts, limit
  // and extras; the rest are the draft page's lines
  tier?: "send" | "open";
  parts?: PostPart[];
  extras?: PostExtra[];
  siblings?: PostSibling[];
  // Open: the site's composer with the draft filled in (a plain link; nothing is sent), or why
  // it is off (the preview, Mastodon's server not typed)
  open?: string | null;
  open_off?: string | null;
  // Post directly, when the person switched the site to it
  direct?: { word: string; ready: boolean; why: string | null } | null;
  // I posted it: the draft waits, so the person may say they posted it themselves
  posted_by_you?: boolean;
}
/** the edit route's answer (post.edit) */
export interface PostEdited { ok: boolean; id: number; ref: string; ticket: number; withdrew: boolean; say: string }
export const editPath = (id: number | string): string => `${sheetPath(id)}/edit`;

export const POST = "/api/post";
/** Settings › Posting's sites (the server's GET /api/post/sites) */
export const POSTING_API = "/api/post/sites";
/** what Write a post writes: a blog post, or short posts for the ticked sites (as=toot, the
 * toot cub's one Mastodon post, is still accepted by the server and no longer offered) */
export type WriteAs = "blog" | "short" | "toot";
/** one of the angle step's three proposals (POST /api/post/angles) */
export interface Angle { kind: string; text: string; words: string }
/** "Short posts for Bluesky, Mastodon and X" */
export function shortLine(names: string[]): string {
  if (!names.length) return "Short posts: choose your sites first";
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `Short posts for ${list}`;
}
/** a short post's words as Copy gives them: its parts, a blank line between */
export const partsText = (parts: { text: string }[]): string => parts.map((p) => p.text.trim()).join("\n\n") + "\n";
export const sheetPath = (id: number | string): string => `/api/post/d/${encodeURIComponent(String(id))}`;
export const downloadHref = (id: number | string): string => `${sheetPath(id)}.md`;
export const WRITING = "Writing the draft. It will be on Post in about a minute.";

/** what a post is about: an idea card, a brief's item (n from 0, as the item's page counts), or
 * this week's news (Post's own Write a post) */
export type About = { card: number; title: string; sources: number } | { brief: number; n: number; title: string; sources: number }
  | { week: true; title: string; sources: number };
/** this week's news, as Post's head asks it (post.write's ``about: week``) */
export const WEEK: About = { week: true, title: "this week's news", sources: 0 };

export function aboutKey(a: About): string {
  return "card" in a ? `card:${a.card}` : "week" in a ? "week" : `brief:${a.brief}:${a.n + 1}`;
}

/** Post's head: "Write a post" asks about what first (AboutWhatDialog) */
export function writeAny(): void {
  openDialog(AboutWhatDialog, {});
}

/** the question's About line: "card #143, with its 3 sources linked" */
export function aboutLine(a: About): string {
  if ("week" in a) return "this week's news, every brief of the last seven days";
  // a card by its number: its title is the sheet's, just behind the question (D4's 180 words)
  const what = "card" in a ? `card #${a.card}` : `the news item “${a.title}”`;
  if (!a.sources) return what;
  return `${what}, with ${a.sources === 1 ? "its source" : `its ${a.sources} sources`} linked`;
}

/** Write a post: the decision dialog, which asks before it spends */
export function writePost(a: About): void {
  openDialog(WritePostDialog, { about: a });
}

/** Write draft: the job starts, the toast says where the draft will be; then the page follows
 * the job and says how it ended (a draft on Post, or why none was written) */
export function startWrite(btn: HTMLElement | null, a: About, as: WriteAs, done?: () => void, angle = ""): void {
  const L = app();
  if (!L) return;
  // the angle: one sentence, the owner's own or a proposal they picked; none is sent when empty
  const line = angle.trim().replace(/\s+/g, " ").slice(0, 600);
  void L.act(btn, async () => {
    try {
      return await L.api("/api/post/write", { about: aboutKey(a), as, ...(line ? { angle: line } : {}) });
    } finally {
      afkDropPrefix("/api/post"); // a refusal (no model key) is kept on Post: read it again
    }
  }, () => {
    L.say(WRITING);
    done?.();
    void followWrite(a, as);
  });
}

/** a failed write's Try again: the same question, asked again */
export function retryWrite(btn: HTMLElement | null, a: About, as: string): void {
  startWrite(btn, a, as === "toot" ? "toot" : as === "short" ? "short" : "blog");
}
/** a failed write's Dismiss: its line on Post goes; nothing else changes */
export function dismissWrite(btn: HTMLElement | null, about: string, as: string): void {
  const L = app();
  if (!L) return;
  void L.act(btn, async () => {
    await L.api("/api/post/write/dismiss", { about, as });
    afkDropPrefix("/api/post");
  });
}

type Job = { state?: string; error?: string | null };
const pause = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
async function jobOf(path: string): Promise<Job | null> {
  try {
    const r = await fetch(path, { cache: "no-store" });
    return r.ok ? ((await r.json()) as Job) : null;
  } catch {
    return null;
  }
}

/** the Write draft job, read every few seconds until it ends (two minutes at most): done says
 * the draft is on Post; failed says the server's words for why (the model did not answer, …) */
export async function followWrite(a: About, as: string, o: { wait?: (ms: number) => Promise<void>; read?: (path: string) => Promise<Job | null>; tries?: number } = {}): Promise<string | null> {
  const wait = o.wait || pause, read = o.read || jobOf;
  const path = `/api/post/write?about=${encodeURIComponent(aboutKey(a))}&as=${encodeURIComponent(as)}`;
  for (let i = 0; i < (o.tries ?? 40); i++) {
    await wait(3000);
    const job = await read(path);
    if (!job || job.state === "running") continue;
    const L = app();
    if (job.state === "failed") {
      const why = job.error || "No draft was written.";
      // in the place of "Writing the draft" (4: both stood at once), and kept on Post with
      // Try again until dismissed (a reload lost it)
      if (L) {
        afkDropPrefix("/api/post");
        L.say(why, "red");
      } else toast(why, null, "red");
      return why;
    }
    L?.afkDrop();
    L?.say("The draft is on Post.");
    return "done";
  }
  return null;
}

/** Copy: the draft's markdown on the clipboard; no account, no model, no network beyond Kranto */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
