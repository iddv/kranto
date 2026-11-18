// Settings › Posting's sites: "Settings › Posting lists the sites I post to, one line each, and one
// Add a site. No wall of logos." (POSTING-7, with four sites ticked), Post directly per site, Mastodon's
// server, and Add a site's sheet with what is not possible today and why.
import { afterEach, describe, expect, it } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import type { Facts } from "../../lib/app";
import type { Where } from "../../lib/pages.svelte";
import { ui } from "../../lib/shell.svelte";
import { answering, count, draw, settle, stub, where } from "../testing.svelte";
import PostingList from "./PostingList.svelte";
import AddSiteDialog from "./AddSiteDialog.svelte";
import { NEWSLETTER_API } from "./newsletter";
import { POSTING_API, siteLine, waitingLine, type Posting, type PostingSite } from "./posting";

const hosted = () => { ui.facts = { header: { host: { paused: false } } } as unknown as Facts; };
afterEach(() => { ui.facts = null; });
const at = (): Where => ({ ...where("settings/posting", null), r: { path: ["settings", "posting"], q: {}, sel: null } });
const site = (id: string, name: string, o: Partial<PostingSite> = {}): PostingSite => ({
  id, name, ways: ["open"], ticked: true, direct: false, can_direct: false, account: null, account_state: "not set", connection: null,
  needs: null, instance: null, limit: 300, unit: "characters", disclose: false, waiting_direct: 0, ...o });
const POSTING: Posting = {
  sites: [site("bluesky", "Bluesky", { ways: ["open", "direct"], can_direct: true, connection: "bluesky_post" }),
    site("mastodon", "Mastodon", { ways: ["open", "direct"], can_direct: true, connection: "mastodon_post", needs: "instance" }),
    site("x", "X"), site("threads", "Threads")],
  not_offered: [{ id: "linkedin", name: "LinkedIn", why: "LinkedIn has no documented link that fills in a post's text, and posting directly needs your own LinkedIn app", later: "Posting directly with your own LinkedIn app comes in the next release" },
    { id: "substack", name: "Substack", why: "Substack has no link that fills in a post or a Note, and no way for an app to post", later: null }],
  disclosure: "Drafted with Kranto.", blog: { state: "connected", account: "proj/production", post_url: "https://example.org/blog" },
};
const NL = { platform: null, name: null, unnamed: "your newsletter platform", platforms: [], connection: null, from_address: null, audience: null,
  audiences: false, ready: false, missing: ["No newsletter platform is connected: Connect a provider"] };

describe("Settings › Posting › Sites you post to", () => {
  it("lists the ticked sites, one line each, with one control where there is a choice, and one Add a site", async () => {
    const L = stub();
    hosted();
    answering({ [POSTING_API]: POSTING, [NEWSLETTER_API]: NL });
    const { target, done } = await draw(PostingList, at());
    await settle();
    const rows = [...target.querySelectorAll("[aria-labelledby=post-sites] li.row")];
    expect(rows.map((r) => r.querySelector(".r-title")?.textContent)).toEqual(["Bluesky", "Mastodon", "X", "Threads"]);
    expect(rows[0]!.querySelector(".c-meta")?.textContent).toBe("opens Bluesky with the draft ready");
    expect(rows[1]!.querySelector(".c-meta")?.textContent).toBe("type your server to open it");
    expect(rows[1]!.querySelector("#posting-server")).not.toBeNull();
    expect(rows[2]!.querySelector("input, button, a.btn")).toBeNull();          // X opens in the site, nothing to choose
    expect(target.querySelector("#posting-add")?.textContent).toBe("Add a site");
    expect(target.textContent).toContain("short posts link to https://example.org/blog");
    expect(target.textContent).not.toMatch(/copy and open|\bcubs?\b|\bticket\b/i);
    // POSTING-7's budget with four sites ticked: 80 words, 7 controls
    const c = count(target, "settings/posting, four sites ticked");
    expect(c.words, JSON.stringify(c)).toBeLessThanOrEqual(80);
    expect(c.controls, JSON.stringify(c)).toBeLessThanOrEqual(7);
    expect(c.primaries, JSON.stringify(c)).toBeLessThanOrEqual(1);
    // Post directly, saved at once
    const direct = rows[0]!.querySelector<HTMLInputElement>("[data-act=post-direct]")!;
    direct.checked = true;
    direct.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    expect(L.api).toHaveBeenCalledWith(POSTING_API, { direct: { bluesky: true } });
    done();
  });

  it("draws LinkedIn, which has no Open, as posted directly: Connect and no switch", async () => {
    stub();
    hosted();
    const li = site("linkedin", "LinkedIn", { ways: ["direct"], can_direct: true, direct: true, connection: "linkedin_post", limit: 3000 });
    answering({ [POSTING_API]: { ...POSTING, sites: [li] }, [NEWSLETTER_API]: NL });
    const { target, done } = await draw(PostingList, at());
    await settle();
    const row = target.querySelector("[aria-labelledby=post-sites] li.row")!;
    expect(row.querySelector(".c-meta")?.textContent).toBe("Kranto posts after your yes, connect an account");
    expect(row.querySelector("[data-act=post-direct]")).toBeNull();
    expect(row.querySelector("[data-act=post-connect]")?.getAttribute("href")).toBe("#/settings/connections/linkedin_post");
    done();
  });

  it("says how a site posts", () => {
    expect(siteLine(site("bluesky", "Bluesky", { direct: true, account: "@me.bsky.social" }))).toBe("opens Bluesky with the draft ready · Kranto posts after your yes, as @me.bsky.social");
    expect(siteLine(site("bluesky", "Bluesky", { direct: true }))).toBe("opens Bluesky with the draft ready · Kranto posts after your yes, connect an account");
    expect(siteLine(site("mastodon", "Mastodon", { needs: "instance", instance: "mastodon.social" }))).toBe("opens Mastodon with the draft ready");
  });

  it("says on the switch when drafts written while Post directly was on still wait to be posted by Kranto", () => {
    expect(waitingLine(site("bluesky", "Bluesky", { can_direct: true, waiting_direct: 1 }))).toBe("1 draft still waits to be posted by Kranto");
    expect(waitingLine(site("bluesky", "Bluesky", { can_direct: true, waiting_direct: 2 }))).toBe("2 drafts still wait to be posted by Kranto");
    expect(waitingLine(site("bluesky", "Bluesky", { can_direct: true, direct: true, waiting_direct: 1 }))).toBe("");
    expect(waitingLine(site("bluesky", "Bluesky", { can_direct: true }))).toBe("");
  });

  it("Add a site lists the others with Add or Remove, the disclosure line, and what is not possible today with why", async () => {
    const L = stub();
    answering({ [POSTING_API]: { ...POSTING, sites: POSTING.sites.map((s) => ({ ...s, ticked: s.id === "x" })) } });
    const host = document.createElement("div");
    document.body.append(host);
    const dlg = mount(AddSiteDialog, { target: host, props: { close: () => {} } });
    await settle();
    flushSync();
    const items = [...host.querySelectorAll("#add-site-list li")];
    expect(items.map((li) => li.querySelector("b")?.textContent)).toEqual(["Bluesky", "Mastodon", "X", "Threads"]);
    expect(items.map((li) => li.querySelector("[data-act=site-toggle]")?.textContent)).toEqual(["Add", "Add", "Remove", "Add"]);
    expect(items[2]!.textContent).toContain("End with “Drafted with Kranto.”");
    expect(items[2]!.querySelector<HTMLInputElement>("[data-act=site-disclose]")!.checked).toBe(false);
    expect(host.querySelector("#add-site-gone-h")?.textContent).toBe("Not possible today");
    const gone = host.querySelector("#add-site-gone")!.textContent || "";
    expect(gone).toContain("Substack has no link that fills in a post or a Note");
    expect(gone).toContain("Posting directly with your own LinkedIn app comes in the next release");
    expect(host.textContent).not.toMatch(/copy and open/i);
    items[0]!.querySelector<HTMLButtonElement>("[data-act=site-toggle]")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith(POSTING_API, { sites: ["x", "bluesky"] });
    unmount(dlg);
    host.remove();
  });
});
