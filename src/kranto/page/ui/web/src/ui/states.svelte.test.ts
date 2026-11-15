// The states and the reading page: one Empty (a sentence, at most one
// link), one Failed (the words, Try again, Tell us), and a thing you read as a page (its outline,
// its body, its sections and its evidence, the head declared to the shell).
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { connect, ui } from "../lib/shell.svelte";
import { peek, put, read } from "../lib/reads.svelte";
import Empty from "./Empty.svelte";
import Failed from "./Failed.svelte";
import Page from "../pages/Page.svelte";

afterEach(() => {
  connect(null);
  ui.headOn = false;
  ui.head = null;
});
function draw<P extends Record<string, unknown>>(C: never, props: P) {
  const target = document.createElement("div");
  const app = mount(C, { target, props });
  flushSync();
  return { target, done: () => unmount(app) };
}

describe("the states", () => {
  it("Empty says one sentence and at most one link; in a group it is a row's place", () => {
    const a = draw(Empty as never, { text: "No post yet.", link: { href: "#/cub/toot?sel=form:draft", w: "Draft a post" } });
    expect(a.target.querySelector("p.state-empty")?.textContent).toBe("No post yet. Draft a post");
    expect(a.target.querySelectorAll("a")).toHaveLength(1);
    a.done();
    const b = draw(Empty as never, { text: "Nothing sent yet.", li: true });
    expect(b.target.querySelector("li.gempty")?.textContent).toBe("Nothing sent yet.");
    b.done();
  });

  it("Failed says what could not be read, Try again reads it again, Tell us is there", () => {
    const render = vi.fn();
    connect({ render } as never);
    put("/api/x", null);
    const r = read("/api/x"); // cached
    expect(r).toBeTruthy();
    const { target, done } = draw(Failed as never, { what: "the issues", error: "the server answered 502", path: "/api/x" });
    expect(target.querySelector(".failed .why")?.textContent).toBe("Could not read the issues: the server answered 502");
    expect([...target.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Try again", "Tell us"]);
    (target.querySelector("button") as HTMLButtonElement).click();
    expect(render).toHaveBeenCalledTimes(1);
    expect(peek("/api/x")).not.toBeNull(); // a read that did not fail stays
    done();
  });
});

describe("a page you read", () => {
  it("draws its outline, body, sections and evidence; with the doors on its head is the shell's", () => {
    ui.headOn = true;
    const { target, done } = draw(Page as never, {
      head: { title: "This week: Kodama raises $7M", crumb: [{ to: "cubs", w: "Cubs" }, { to: "cub/newsletter", w: "Newsletter" }], facts: "issue of 20 Oct · 9 items", primary: { label: "Confirm", run: () => {} } },
      sections: [{ id: "items", w: "Items", n: 9 }, { id: "about", w: "About" }],
    });
    expect([...target.querySelectorAll(".page-toc a")].map((a) => a.textContent)).toEqual(["Items9", "About"]);
    expect(target.querySelector("#s-about h2")?.textContent).toBe("About");
    expect(target.querySelector(".lh")).toBeNull(); // the head is declared, not drawn here
    expect(ui.head?.title).toBe("This week: Kodama raises $7M");
    expect(ui.head?.crumb?.map((c) => c.w)).toEqual(["Cubs", "Newsletter"]);
    done();
    expect(ui.head).toBeNull(); // it goes with its page
  });
});
