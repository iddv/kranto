// Post's parts: Write a post's question asks before it spends (About, As, Then;
// Details, Cancel, Write draft) and Write draft asks the server for the draft; a draft's sheet offers
// Copy and Download with no account, Send with one, and folds a long draft.
import { mount, unmount, flushSync } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { answering, count, settle, stub } from "../../pages/testing.svelte";
import { closeDialog } from "../../ui/dialog.svelte";
import DraftSheet from "./DraftSheet.svelte";
import WritePostDialog from "./WritePostDialog.svelte";
import { aboutKey, aboutLine, downloadHref, followWrite, sheetPath, WRITING, type PostSheet } from "./post";
import { TOAST } from "../../ui/toast.svelte";

afterEach(() => closeDialog());

const sheet = (o: Partial<PostSheet> = {}): PostSheet => ({
  id: 5, ref: "draft:5", cub: "newsletter", kind: "newsletter", word: "newsletter",
  title: "This week: robots learn to grasp", fact: "Monday's issue", at: new Date().toISOString(),
  ticket: 8, again: null, verb: "Send", line: "needs a newsletter account", said: null, note: null,
  link: null, account: false, group: "waiting",
  markdown: "# This week: robots learn to grasp\n\nIntro.\n\n**One**\n[a](https://ex.com/1)\n\n**Two**\n\n**Three**\n\n**Four**\n",
  filename: "This week robots learn to grasp.md", words: 12, account_of: null, ...o,
});

function show<P extends Record<string, unknown>>(C: unknown, props: P) {
  const target = document.createElement("div");
  document.body.append(target);
  const c = mount(C as never, { target, props });
  flushSync();
  return { target, done: () => { unmount(c); target.remove(); } };
}

describe("Write a post", () => {
  it("names what it is about and where the draft goes", () => {
    expect(aboutKey({ card: 143, title: "x", sources: 3 })).toBe("card:143");
    expect(aboutKey({ brief: 41, n: 0, title: "x", sources: 1 })).toBe("brief:41:1");
    expect(aboutLine({ card: 143, title: "Court booking", sources: 3 })).toBe("card #143, with its 3 sources linked");
    expect(aboutLine({ brief: 41, n: 0, title: "Courts got busier", sources: 1 })).toBe("the news item “Courts got busier”, with its source linked");
  });

  const POSTING = { sites: [
    { id: "bluesky", name: "Bluesky", ways: ["open", "direct"], ticked: true, direct: false, can_direct: true, account: null, account_state: "not set", connection: "bluesky_post", needs: null, instance: null, limit: 300, unit: "characters", disclose: false },
    { id: "x", name: "X", ways: ["open"], ticked: true, direct: false, can_direct: false, account: null, account_state: "not set", connection: null, needs: null, instance: null, limit: 280, unit: "characters, a link counts 23", disclose: false }],
    not_offered: [], disclosure: "Drafted with Kranto.", blog: { state: "not set", account: null, post_url: null } };
  const ANGLES = { angles: [{ kind: "claim", text: "Grasping is solved.", words: "a claim" }, { kind: "prediction", text: "Warehouses hire fewer pickers by 2028.", words: "a prediction" },
    { kind: "question", text: "Who owns the gripper data?", words: "a question" }] };
  const answers = (L: ReturnType<typeof stub>) => L.api.mockImplementation(async (path: string) => path === "/api/post/angles" ? ANGLES : {});

  it("asks once, with three angles to pick, then writes short posts for the ticked sites", async () => {
    const L = stub();
    answers(L);
    answering({ "/api/prose": { voice: "Tone: plain.", samples: [] }, "/api/post/sites": POSTING });
    const close = vi.fn();
    const { target, done } = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close });
    await settle();
    expect(target.querySelector("#dlg-t")?.textContent).toBe("Write a post about this idea?");
    expect(target.querySelector("#write-post-about")?.textContent).toBe("card #143, with its 3 sources linked");
    expect(target.querySelector('label[for="write-post-angle"]')?.textContent).toBe("Why does this interest you? One sentence.");
    expect(L.api).toHaveBeenCalledWith("/api/post/angles", { about: "card:143", as: "blog" });
    const props = [...target.querySelectorAll("#write-post-angles [data-angle]")];
    // each proposal is readable before it is chosen: its sentence is the button
    expect(props.map((b) => b.textContent)).toEqual(ANGLES.angles.map((a) => a.text));
    expect(props.map((b) => b.getAttribute("aria-label")?.split(":")[0])).toEqual(["A claim", "A prediction", "A question"]);
    expect([...target.querySelectorAll(".dlg-f button")].map((b) => b.textContent)).toEqual(["Details", "Cancel", "Write draft"]);
    expect(target.textContent).not.toMatch(/copy and open/i);
    const short = target.querySelector<HTMLInputElement>('input[value="short"]')!;
    expect(short.parentElement?.textContent?.trim()).toBe("Short posts for Bluesky and X");
    expect(target.querySelector('input[value="toot"]')).toBeNull();
    short.click();
    flushSync();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/angles", { about: "card:143", as: "short" });
    target.querySelector<HTMLButtonElement>('[data-angle="prediction"]')!.click();
    flushSync();
    expect(target.querySelector<HTMLInputElement>("#write-post-angle")!.value).toBe("Warehouses hire fewer pickers by 2028.");
    target.querySelector<HTMLButtonElement>("#dlg-ok")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "card:143", as: "short", angle: "Warehouses hire fewer pickers by 2028." });
    expect(L.say).toHaveBeenCalledWith(WRITING);
    expect(close).toHaveBeenCalled();
    done();
  });

  it("fits the card's budget with three proposals and four sites ticked (COUNT card: 220 words, 18 controls)", async () => {
    const L = stub();
    L.api.mockImplementation(async (path: string) => path === "/api/post/angles" ? { angles: [
      { kind: "claim", text: "Robot grasping just crossed the line from demo to warehouse product.", words: "a claim" },
      { kind: "prediction", text: "Within two years most new warehouses will buy picking arms instead of hiring pickers.", words: "a prediction" },
      { kind: "question", text: "Who owns the grasp data these robots learn from: the warehouse or the vendor?", words: "a question" }] } : {});
    const four = { ...POSTING, sites: ["Bluesky", "Mastodon", "X", "Threads"].map((n, i) => ({ ...POSTING.sites[i ? 1 : 0]!, id: n.toLowerCase(), name: n })) };
    answering({ "/api/prose": { voice: "", samples: [] }, "/api/post/sites": four });
    const { target, done } = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close: () => {} });
    await settle();
    expect(target.querySelectorAll("[data-angle]").length).toBe(3);
    const c = count(target, "write a post's dialog, three proposals, four sites, no voice yet");
    // the angle step's three readable proposals and Skip: COUNT card is now 220 words, 18
    // controls with the card's sheet (about 120 words and 6 controls)
    expect(c.words, JSON.stringify(c)).toBeLessThanOrEqual(95);
    expect(c.controls, JSON.stringify(c)).toBeLessThanOrEqual(11);
    expect(c.primaries).toBe(1);
    done();
  });

  it("Skip sends no angle; a typed sentence is sent as the angle", async () => {
    const L = stub();
    answers(L);
    answering({ "/api/prose": { voice: "Tone: plain.", samples: [] }, "/api/post/sites": POSTING });
    const { target, done } = show(WritePostDialog, { about: { brief: 41, n: 0, title: "Courts got busier", sources: 1 }, close: () => {} });
    await settle();
    target.querySelector<HTMLButtonElement>('[data-angle="claim"]')!.click();
    target.querySelector<HTMLButtonElement>("#write-post-skip")!.click();
    flushSync();
    expect(target.querySelector<HTMLInputElement>("#write-post-angle")!.value).toBe("");
    target.querySelector<HTMLButtonElement>("#dlg-ok")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "brief:41:1", as: "blog" });
    const box = target.querySelector<HTMLInputElement>("#write-post-angle")!;
    box.value = "  I think   courts will   stay busy. ";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    target.querySelector<HTMLButtonElement>("#dlg-ok")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "brief:41:1", as: "blog", angle: "I think courts will stay busy." });
    done();
  });

  it("says why no angles came, and offers short posts only once sites are chosen", async () => {
    const L = stub();
    L.api.mockImplementation(async (path: string) => { if (path === "/api/post/angles") throw new Error("No angles were proposed: no model key is set."); return {}; });
    answering({ "/api/prose": { voice: "", samples: [] }, "/api/post/sites": { ...POSTING, sites: POSTING.sites.map((x) => ({ ...x, ticked: false })) } });
    const { target, done } = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close: () => {} });
    await settle();
    expect(target.querySelector("#write-post-angles-why")?.textContent).toBe("No angles were proposed: no model key is set.");
    const short = target.querySelector<HTMLInputElement>('input[value="short"]')!;
    expect(short.disabled).toBe(true);
    expect(short.parentElement?.querySelector("a")?.getAttribute("href")).toBe("#/settings/posting");
    expect(short.parentElement?.textContent?.trim()).toBe("Short posts: choose your sites first");
    // no voice yet (skipped in Welcome): the question offers it once more
    expect(target.querySelector("#write-post-voice")?.textContent).toBe("Set up how you write ›");
    expect(target.querySelector("#write-post-voice a")?.getAttribute("href")).toBe("#/settings/posting/voice");
    done();
  });

  // 4: why none was written takes the place of "Writing the draft" (a red line, not a toast
  // beside it), and Post reads again, where the failed write stays
  it("follows the job: a draft on Post, or why none was written, in a red line", async () => {
    const L = stub();
    const wait = async () => {};
    const about = { card: 143, title: "Court booking", sources: 3 };
    const seen: string[] = [];
    const done = await followWrite(about, "blog", { wait, read: async (p) => { seen.push(p); return seen.length < 2 ? { state: "running" } : { state: "done" }; } });
    expect(done).toBe("done");
    expect(seen[0]).toBe("/api/post/write?about=card%3A143&as=blog");
    expect(L.say).toHaveBeenCalledWith("The draft is on Post.");
    const why = "No draft was written: the model did not answer. Check the model key on Settings › Watching, then choose Write a post again.";
    expect(await followWrite(about, "blog", { wait, read: async () => ({ state: "failed", error: why }) })).toBe(why);
    expect(L.say).toHaveBeenLastCalledWith(why, "red");
    expect(TOAST.text).not.toBe(why);
    expect(await followWrite(about, "blog", { wait, read: async () => null, tries: 2 })).toBeNull();
  });

  it("offers this week's news as a blog post only", () => {
    stub();
    const { target, done } = show(WritePostDialog, { about: { week: true, title: "this week's news", sources: 0 }, close: () => {} });
    expect(target.querySelector("#dlg-t")?.textContent).toBe("Write a post about this week's news?");
    expect(target.querySelector('input[name="write-as"]')).toBeNull();
    expect(target.querySelector(".dlg-f #dlg-details")).toBeNull();
    done();
  });
});

describe("a draft's sheet", () => {
  it("with no account: Copy is the primary, Download saves <title>.md, Connect an account to send", async () => {
    stub();
    answering({ [sheetPath(5)]: sheet() });
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { target, done } = show(DraftSheet, { id: 5 });
    await settle();
    expect(target.querySelector("#draft-title")?.textContent).toBe("This week: robots learn to grasp");
    expect(target.querySelector("#draft-send")).toBeNull();
    expect(target.querySelector("#draft-copy")?.className).toContain("primary");
    const dl = target.querySelector<HTMLAnchorElement>("#draft-download")!;
    expect(dl.getAttribute("href")).toBe(downloadHref(5));
    expect(dl.getAttribute("download")).toBe("This week robots learn to grasp.md");
    expect(target.querySelector("#draft-connect")?.textContent).toBe("Connect an account to send");
    expect(target.querySelector("#draft-show-all")?.textContent).toBe("Show all 12 words");
    // the draft is drawn without its "# Title" line (the head has it); Copy keeps it
    expect(target.querySelector("#draft-text")?.textContent).not.toContain("robots learn to grasp");
    expect(target.querySelector("#draft-text")?.textContent).toContain("Intro.");
    target.querySelector<HTMLButtonElement>("#draft-copy")!.click();
    await settle();
    expect(writeText).toHaveBeenCalledWith(sheet().markdown);
    expect(target.querySelector("#draft-copy")?.textContent).toBe("Copied");
    done();
  });

  it("with an account: Send is the primary; an earlier draft offers Copy and Download only", async () => {
    stub();
    answering({ [sheetPath(5)]: sheet({ account: true }), [sheetPath(4)]: sheet({ id: 4, group: "earlier", ticket: null, said: "Replaced by a newer issue (16 Nov)" }) });
    const one = show(DraftSheet, { id: 5 });
    await settle();
    expect(one.target.querySelector("#draft-send")?.textContent).toBe("Send");
    expect(one.target.querySelector("#draft-copy")?.className).not.toContain("primary");
    one.done();
    const two = show(DraftSheet, { id: 4 });
    await settle();
    expect(two.target.querySelector("#draft-send")).toBeNull();
    expect(two.target.querySelector("#draft-decline")).toBeNull();
    expect(two.target.querySelector("#draft-facts")?.textContent).toContain("Replaced by a newer issue");
    expect(two.target.querySelector("#draft-edit")).toBeNull();
    two.done();
  });
});

const CHECK = { score: 70, verdict: "1 thing reads like AI: fix them", flags: [{ start: 7, end: 12, text: "delve", rule: "words.floor", words: "reads like a model", fix: "say dig into", scope: "span" }] };

describe("editing a draft", () => {
  it("shows PROSE's flags on a waiting draft, opens the draft's own words, and saves them as post.edit", async () => {
    const L = stub();
    L.api.mockImplementation(async (path: string) => path === "/api/prose/check" ? CHECK : path.endsWith("/edit") ? { ok: true, id: 6, ref: "draft:6", ticket: 9, withdrew: true, say: "Saved. The send that waited for your yes was withdrawn." } : {});
    answering({ [sheetPath(5)]: sheet({ can_edit: true, edit: { title: "This week: robots learn to grasp", body: "Intro. delve\n\n**One**" }, original_draft: 5 }) });
    const { target, done } = show(DraftSheet, { id: 5 });
    await settle();
    await settle();                                       // the sheet's read, then the check's
    expect(target.querySelector("#draft-flags .pf-line")?.textContent).toBe("1 thing reads like AI");
    expect(target.querySelector("#draft-flags .pf-mark")?.textContent).toBe("delve");
    expect(target.querySelector("#draft-flags .pf-fixes")?.textContent).toContain("say dig into");
    expect(target.querySelector("#draft-flags-fix")).toBeNull();                 // Fix is the editor's
    target.querySelector<HTMLButtonElement>("#draft-edit")!.click();
    flushSync();
    const body = target.querySelector<HTMLTextAreaElement>("#draft-edit-body")!;
    expect(body.value).toBe("Intro. delve\n\n**One**");
    expect(target.querySelector<HTMLInputElement>("#draft-edit-title")!.value).toBe("This week: robots learn to grasp");
    expect([...target.querySelectorAll(".draft-editor .btn.primary")].map((b) => b.textContent)).toEqual(["Save"]);
    body.value = "My intro.\n\n**One**";
    body.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    target.querySelector<HTMLButtonElement>("#draft-save")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/d/5/edit", { title: "This week: robots learn to grasp", body: "My intro.\n\n**One**" });
    expect(L.api).toHaveBeenCalledWith("/api/prose/learn", { draft: "Intro. delve\n\n**One**", sent: "My intro.\n\n**One**" });
    expect(L.say).toHaveBeenCalledWith("Saved. The send that waited for your yes was withdrawn.");
    expect(location.hash).toBe("#/post/d/6");
    done();
  });

  it("a short post is one box with its count, red past the limit, and Save waits", async () => {
    stub().api.mockImplementation(async (path: string) => path === "/api/prose/check" ? { ...CHECK, flags: [], verdict: "Reads natural" } : {});
    answering({ [sheetPath(7)]: sheet({ id: 7, kind: "mastodon", word: "short post", can_edit: true, edit: { title: null, parts: [{ text: "A toot." }] }, limit: { max: 10, unit: "characters" } }) });
    const { target, done } = show(DraftSheet, { id: 7 });
    await settle();
    await settle();                                       // the sheet's read, then the check's
    expect(target.querySelector("#draft-flags .pf-line")?.textContent).toBe("Reads natural");
    target.querySelector<HTMLButtonElement>("#draft-edit")!.click();
    flushSync();
    expect(target.querySelector("#draft-edit-title")).toBeNull();
    expect(target.querySelector("#draft-edit-count-0")?.textContent).toBe("7 of 10 characters");
    const part = target.querySelector<HTMLTextAreaElement>("#draft-edit-part-0")!;
    part.value = "A much longer toot.";
    part.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(target.querySelector("#draft-edit-count-0")?.className).toContain("over");
    expect(target.querySelector<HTMLButtonElement>("#draft-save")!.disabled).toBe(true);
    target.querySelector<HTMLButtonElement>("#draft-cancel")!.click();
    flushSync();
    expect(target.querySelector("#draft-editor")).toBeNull();
    done();
  });
});

describe("a short post's draft page", () => {
  const short = (o: Partial<PostSheet> = {}): PostSheet => sheet({
    id: 22, ref: "draft:22", cub: "social", kind: "short", word: "short posts", title: "Robots learn to grasp", fact: "from #143",
    ticket: 30, verb: "I posted it", line: "ready", account: true, site: "bluesky", site_word: "Bluesky", way: "open",
    markdown: "Grasping is solved.\n\nhttps://example.com/post\n", words: 4, tier: "open",
    parts: [{ text: "Grasping is solved.\n\nhttps://example.com/post", used: 44 }], limit: { max: 300, unit: "characters" },
    extras: [{ key: "link", words: "Links to your blog post: https://example.com/post. Publish it before you post this.", drop: false }],
    siblings: [{ id: 22, site: "bluesky", word: "Bluesky", state: "waiting" }, { id: 23, site: "mastodon", word: "Mastodon", state: "sent" }, { id: 24, site: "x", word: "X", state: "waiting" }],
    open: "https://bsky.app/intent/compose?text=Grasping", open_off: null, direct: null, posted_by_you: true, ...o,
  });

  it("opens the site first, with the draft filled in, then asks I posted it; Copy gives the post's words", async () => {
    const L = stub();
    L.api.mockImplementation(async (path: string) => path.endsWith("/posted") ? { ok: true, say: "Recorded: posted by you. Nothing was sent by Kranto." } : { flags: [], verdict: "Reads natural" });
    answering({ [sheetPath(22)]: short() });
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { target, done } = show(DraftSheet, { id: 22 });
    await settle();
    const open = target.querySelector<HTMLAnchorElement>("#draft-open")!;
    expect(open.textContent).toBe("Open in Bluesky");
    expect(open.className).toContain("primary");
    expect(open.getAttribute("href")).toBe("https://bsky.app/intent/compose?text=Grasping");
    expect(open.getAttribute("target")).toBe("_blank");
    expect(open.getAttribute("rel")).toBe("noopener noreferrer");
    expect(target.querySelectorAll(".btn.primary").length).toBe(1);
    expect(target.querySelector("#draft-copy")?.className).not.toContain("primary");
    expect(target.querySelector("#draft-connect")).toBeNull();
    expect(target.querySelector("#draft-direct")).toBeNull();
    // the siblings are links to their own pages; this one is named, not linked
    const sib = target.querySelector("#draft-siblings")!;
    expect(sib.textContent).toBe("Bluesky · Mastodon ✓ · X");
    expect([...sib.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual(["#/post/d/23", "#/post/d/24"]);
    expect(target.querySelector("#draft-count-0")?.textContent).toBe("44 of 300 characters");
    expect(target.querySelector(".draft-extra")?.textContent).toContain("Links to your blog post");
    expect(target.textContent).not.toMatch(/copy and open/i);
    target.querySelector<HTMLButtonElement>("#draft-copy")!.click();
    await settle();
    expect(writeText).toHaveBeenCalledWith("Grasping is solved.\n\nhttps://example.com/post\n");
    open.addEventListener("click", (e) => e.preventDefault());
    open.click();
    flushSync();
    target.querySelector<HTMLButtonElement>("#draft-posted-yes")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/d/22/posted", {});
    expect(L.say).toHaveBeenCalledWith("Recorded: posted by you. Nothing was sent by Kranto.");
    done();
  });

  it("on the preview Open is off and says so; Not yet hides I posted it; a thread counts each post, red past the limit", async () => {
    stub().api.mockImplementation(async () => ({ flags: [], verdict: "Reads natural" }));
    answering({ [sheetPath(22)]: short({ open: null, open_off: "This is the preview: nothing is posted.",
      parts: [{ text: "One.", used: 4 }, { text: "Two is too long.", used: 320 }] }) });
    const { target, done } = show(DraftSheet, { id: 22 });
    await settle();
    const open = target.querySelector<HTMLButtonElement>("#draft-open")!;
    expect(open.disabled).toBe(true);
    expect(target.querySelector("#draft-open-off")?.textContent).toBe("This is the preview: nothing is posted.");
    expect([...target.querySelectorAll(".draft-part > p.muted:first-child")].map((x) => x.textContent)).toEqual(["1 of 2", "2 of 2"]);
    expect(target.querySelector("#draft-count-0")?.className).not.toContain("over");
    expect(target.querySelector("#draft-count-1")?.className).toContain("over");
    target.querySelector<HTMLButtonElement>("#draft-posted-no")!.click();
    flushSync();
    expect(target.querySelector("#draft-posted")).toBeNull();
    done();
  });

  it("Post directly is beside Open, off with why until the account is connected", async () => {
    stub().api.mockImplementation(async () => ({ flags: [], verdict: "Reads natural" }));
    answering({ [sheetPath(22)]: short({ tier: "send", way: "direct", direct: { word: "Post to Bluesky", ready: false, why: "Connect Bluesky (posting) on Settings › Posting to post it from here" } }) });
    const { target, done } = show(DraftSheet, { id: 22 });
    await settle();
    expect(target.querySelector("#draft-open")?.className).toContain("primary");
    const direct = target.querySelector<HTMLButtonElement>("#draft-direct")!;
    expect(direct.textContent).toBe("Post to Bluesky");
    expect(direct.className).not.toContain("primary");
    expect(direct.disabled).toBe(true);
    expect(target.querySelector("#draft-direct-why")?.textContent).toContain("Connect Bluesky (posting)");
    done();
  });
});
