// Post's parts: Write a post's question asks before it spends (About, As, Then;
// Details, Cancel, Write draft) and Write draft asks the server for the draft; a draft's sheet offers
// Copy and Download with no account, Send with one, and folds a long draft.
import { mount, unmount, flushSync } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { answering, settle, stub } from "../../pages/testing.svelte";
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

  it("asks once, then writes the draft as a blog post or a short post", async () => {
    const L = stub();
    const close = vi.fn();
    const { target, done } = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close });
    expect(target.querySelector("#dlg-t")?.textContent).toBe("Write a post about this idea?");
    expect(target.querySelector("#write-post-about")?.textContent).toBe("card #143, with its 3 sources linked");
    expect(target.textContent).toContain("The draft waits on Post to edit. Nothing is sent until you choose Send.");
    expect([...target.querySelectorAll(".dlg-f button")].map((b) => b.textContent)).toEqual(["Details", "Cancel", "Write draft"]);
    // the dialog's own words stay short (the design's 35, plus "What do you think?" and "to edit";
    // with the card's sheet, acceptance.py's COUNT card holds 190 words and 14 controls)
    expect((target.querySelector(".dlg-b")?.textContent || "").split(/\s+/).filter(Boolean).length).toBeLessThanOrEqual(48);
    target.querySelector<HTMLInputElement>('input[value="toot"]')!.click();
    flushSync();
    target.querySelector<HTMLButtonElement>("#dlg-ok")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "card:143", as: "toot" });
    expect(L.say).toHaveBeenCalledWith(WRITING);
    expect(close).toHaveBeenCalled();
    done();
  });

  it("offers How you write once more when no voice is set", async () => {
    stub();
    answering({ "/api/prose": { voice: "", samples: [] } });
    const { target, done } = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close: () => {} });
    await settle();
    expect(target.querySelector("#write-post-voice")?.textContent).toBe("Set up how you write ›");
    expect(target.querySelector("#write-post-voice a")?.getAttribute("href")).toBe("#/settings/posting/voice");
    done();
    answering({ "/api/prose": { voice: "Tone: plain.", samples: [] } });
    const set = show(WritePostDialog, { about: { card: 143, title: "Court booking", sources: 3 }, close: () => {} });
    await settle();
    expect(set.target.querySelector("#write-post-voice")).toBeNull();
    set.done();
  });

  it("sends the owner's own line as take when they write one", async () => {
    const L = stub();
    const { target, done } = show(WritePostDialog, { about: { brief: 41, n: 0, title: "Courts got busier", sources: 1 }, close: () => {} });
    const take = target.querySelector<HTMLInputElement>("#write-post-take")!;
    take.value = "  I think   courts will   stay busy. ";
    take.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    target.querySelector<HTMLButtonElement>("#dlg-ok")!.click();
    await settle();
    expect(L.api).toHaveBeenCalledWith("/api/post/write", { about: "brief:41:1", as: "blog", take: "I think courts will stay busy." });
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

  it("offers a news item as a blog post only", () => {
    stub();
    const { target, done } = show(WritePostDialog, { about: { brief: 41, n: 0, title: "Courts got busier", sources: 1 }, close: () => {} });
    expect(target.querySelector("#dlg-t")?.textContent).toBe("Write a post about this story?");
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
