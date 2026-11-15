// Post: the owner's line, "Post shows my two drafts, nothing sent, three
// accounts to connect", from the server's GET /api/post; the newest draft holds the one primary;
// earlier drafts are folded; Open is the ask's own dialog until a draft has its sheet's route.
import { afterEach, describe, expect, it } from "vitest";
import type { Facts } from "../../lib/app";
import { ui } from "../../lib/shell.svelte";
import { answering, count, draw, settle, stub, where } from "../testing.svelte";
import PostPage from "./PostPage.svelte";
import { accountHref, accountWords, connectedCount, draftFact, failedAbout, failedTitle, POST_API, sentLine, sitesWords, whereLine, type Post, type PostDraft } from "./post";
import { mount, unmount } from "svelte";
import AboutWhatDialog from "../../features/post/AboutWhatDialog.svelte";
import { aboutKey, aboutLine, WEEK } from "../../features/post/post";

afterEach(() => { ui.facts = null; });
const draft = (id: number, o: Partial<PostDraft> = {}): PostDraft => ({
  id, ref: "draft:" + id, cub: "newsletter", kind: "newsletter", word: "newsletter", title: `Draft ${id}`, fact: "Monday's issue",
  at: new Date(Date.now() - id * 3600_000).toISOString(), ticket: 10 + id, again: null, verb: "Send", line: "ready", said: null, note: null,
  link: null, account: false, ...o,
});
const POST: Post = {
  line: "Drafts wait here until you have seen them.",
  drafts: [draft(8, { title: "This week: Amazon grasps 66 objects" }), draft(9, { cub: "examplecom", kind: "blog", word: "blog post", title: "Kranto and robots", fact: "from a week of briefs", ticket: null, again: 5 })],
  sent: [],
  earlier: [draft(4, { line: "replaced by #8" }), draft(3, { line: "declined" })],
  accounts: [{ key: "newsletter", word: "Newsletter", state: "not set", account: null, platform: null },
    { key: "mastodon", word: "Mastodon", state: "not set", account: null, platform: null },
    { key: "blog", word: "Blog", state: "not set", account: null, platform: null }],
  sites: { line: "No sites chosen for short posts yet.", ticked: 0 },
  failed: [],
};

async function page(post: Post) {
  answering({ [POST_API]: post });
  stub({ host: { topics: [] } });
  ui.facts = { header: { host: { paused: false }, run: [] } } as unknown as Facts;
  const { target, done } = await draw(PostPage, where("post"));
  await settle();
  await settle();
  return { target, done };
}
const titles = (el: Element, id: string) => [...el.querySelectorAll(`[aria-labelledby=${id}] .r-title`)].map((x) => x.textContent);

describe("Post", () => {
  it("shows the two drafts, nothing sent and three accounts to connect", async () => {
    const { target, done } = await page(POST);
    expect(titles(target, "post-drafts")).toEqual(["This week: Amazon grasps 66 objects", "Kranto and robots"]);
    expect([...target.querySelectorAll("[aria-labelledby=post-drafts] .gl-w")].map((x) => x.textContent)).toEqual(["newsletter", "blog post"]);
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);                 // the newest draft's Open
    expect(target.querySelector("[aria-labelledby=post-drafts] .btn.primary")?.textContent).toBe("Open");
    expect(target.querySelector("[aria-labelledby=post-sent]")?.textContent).toContain("Nothing sent yet.");
    // the accounts are one line and one control, whatever the number of sites
    const acc = target.querySelector("[aria-labelledby=post-accounts]")!;
    expect([...acc.querySelectorAll(".r-title")].map((x) => x.textContent)).toEqual(["Where posts go"]);
    expect([...acc.querySelectorAll(".btn")].map((x) => [x.textContent, x.getAttribute("href")])).toEqual([["Sites", "#/settings/posting"]]);
    expect(acc.textContent).toContain("No sites chosen for short posts yet. Blog: not set. Newsletter: not set.");
    expect(acc.textContent).toContain("optional: every draft can be copied without one");
    // earlier drafts are there, folded
    expect(target.querySelector("[aria-labelledby=post-earlier]")?.classList.contains("folded")).toBe(true);
    expect(target.textContent).not.toMatch(/\bCubs?\b|\bticket\b/i);
    done();
  });

  // SHELL left Post's own Write a post to the P2, which did not build it
  it("has a plain Write a post in its head, asking about what: this week's news or an idea", async () => {
    const { target, done } = await page(POST);
    const b = target.querySelector("#post-write") as HTMLButtonElement | null;
    expect(b?.textContent?.trim()).toBe("Write a post");
    expect(b?.classList.contains("primary")).toBe(false);
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    expect(aboutKey(WEEK)).toBe("week");
    expect(aboutLine(WEEK)).toBe("this week's news, every brief of the last seven days");
    done();
    const host = document.createElement("div");
    document.body.append(host);
    const dlg = mount(AboutWhatDialog, { target: host, props: { close: () => {} } });
    await settle();
    expect(host.querySelector("#dlg-t")?.textContent).toBe("Write a post about what?");
    expect([...host.querySelectorAll("#about-what label")].map((l) => l.textContent?.trim())).toEqual(["This week's news", "An idea: pick one on Ideas"]);
    (host.querySelector("input[value=idea]") as HTMLInputElement).click();
    (host.querySelector("#dlg-ok") as HTMLButtonElement).click();
    await settle();
    expect(location.hash).toBe("#/ideas");
    unmount(dlg);
    host.remove();
  });

  it("says where a sent post went, and what an account is", () => {
    expect(sentLine(draft(1, { note: "Sent to 312 on Resend" }))).toBe("Sent to 312 on Resend");
    expect(sentLine(draft(1))).toBe("Sent");
    expect(accountWords({ key: "mastodon", word: "Mastodon", state: "connected", account: "@octo-owner@hachyderm.io", platform: null })).toBe("connected as @octo-owner@hachyderm.io");
    expect(accountWords({ key: "newsletter", word: "Newsletter", state: "not set", account: null, platform: null })).toBe("not set");
    expect(accountHref({ key: "newsletter", word: "Newsletter", state: "not set", account: null, platform: null })).toBe("#/settings/posting?sel=enl");
    expect(accountHref({ key: "blog", word: "Blog", state: "not set", account: null, platform: null })).toBe("#/settings/connections/sanity");
    // 7 (Codex 4): Post's Mastodon is the account Kranto posts from, never the read-only one
    expect(accountHref({ key: "mastodon", word: "Mastodon", state: "not set", account: null, platform: null })).toBe("#/settings/connections/mastodon_post");
  });

  // 4 (Codex 1, 13; Gemini 5): a write that failed stays on Post with why, Try again and
  // Dismiss; 17 (Codex 22): Accounts counts the connected ones ("Accounts 3" with none)
  it("keeps a failed write with its reason, Try again and Dismiss; Accounts counts the connected", async () => {
    const failed = [{ about: "card:160", as: "blog", at: new Date().toISOString(), title: "Fixed-task canary", fix: "settings/watching",
      error: "No draft was written: no model key is set. Add one on Settings › Watching, then choose Write a post again." }];
    const { target, done } = await page({ ...POST, failed });
    const box = target.querySelector("[aria-labelledby=post-failed]")!;
    expect(box.querySelector(".r-title")?.textContent).toBe("Write a blog post about Fixed-task canary: no draft");
    expect(box.textContent).toContain("no model key is set");
    expect([...box.querySelectorAll(".btn")].map((x) => x.textContent)).toEqual(["Settings › Watching", "Try again", "Dismiss"]);
    expect(box.querySelector("a.btn")?.getAttribute("href")).toBe("#/settings/watching");
    done();
    expect(failedAbout(failed[0]!)).toEqual({ card: 160, title: "Fixed-task canary", sources: 0 });
    expect(failedTitle({ as: "toot", title: null })).toBe("Write a short post about this: no draft");
    expect(failedTitle({ as: "short", title: "Robots" })).toBe("Write short posts about Robots: no draft");
    expect(connectedCount(POST.accounts)).toBe(0);
  });
});

describe("Post with short posts", () => {
  const sites = [{ id: 21, site: "bluesky", word: "Bluesky", state: "sent" }, { id: 22, site: "mastodon", word: "Mastodon", state: "waiting" },
    { id: 23, site: "x", word: "X", state: "waiting" }, { id: 24, site: "threads", word: "Threads", state: "waiting" }];
  const short = draft(22, { cub: "social", kind: "short", word: "short posts", title: "Robots learn to grasp", fact: "from #143", site: "mastodon",
    site_word: "Mastodon", write: "wabc", way: "open", sites, verb: "I posted it" });

  it("draws one row a write, naming its sites with a tick on those sent, and one Open", async () => {
    const { target, done } = await page({ ...POST, drafts: [short], sent: [draft(21, { cub: "social", kind: "short", site: "bluesky", site_word: "Bluesky", note: "posted by you", ticket: null })],
      sites: { line: "Bluesky, Mastodon, X and Threads open in the site, with the draft filled in.", ticked: 4 } });
    const rows = target.querySelectorAll("[aria-labelledby=post-drafts] li.row");
    expect(rows.length).toBe(1);
    expect(rows[0]!.querySelector(".c-meta")?.textContent).toBe("from #143 · Bluesky ✓ · Mastodon · X · Threads");
    expect(rows[0]!.querySelectorAll("[data-act=post-open]").length).toBe(1);
    expect(target.querySelector("[aria-labelledby=post-sent] .c-meta")?.textContent).toBe("Posted to Bluesky · posted by you");
    expect(target.querySelector("[aria-labelledby=post-accounts]")?.textContent).toContain("Bluesky, Mastodon, X and Threads open in the site");
    expect(target.textContent).not.toMatch(/copy and open/i);
    // Post's budget with one write of four sites waiting: 173 words, 12 controls
    const c = count(target, "post, one write of four sites waiting");
    expect(c.words, JSON.stringify(c)).toBeLessThanOrEqual(173);
    expect(c.controls, JSON.stringify(c)).toBeLessThanOrEqual(12);
    expect(c.primaries, JSON.stringify(c)).toBeLessThanOrEqual(2);
    done();
    expect(sitesWords(short)).toBe("Bluesky ✓ · Mastodon · X · Threads");
    expect(draftFact(draft(1))).toBe("Monday's issue");
    expect(whereLine({ ...POST, sites: { line: "X opens in the site.", ticked: 1 } })).toBe("X opens in the site. Blog: not set. Newsletter: not set.");
  });
});
