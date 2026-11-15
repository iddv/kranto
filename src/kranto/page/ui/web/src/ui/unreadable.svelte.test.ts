// One bad row never takes a page down: a read's rows that server could
// not read are taken out of its lists as it arrives and listed under the page's head, "Couldn't read
// this source · Energy Feed · error 1a2b3c4d" with Send this error; a failed answer that carries an
// error's id says the version and the id, and Send this error opens Feedback with the report shown.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connect, ui } from "../lib/shell.svelte";
import { allKept, asked, contain, drawEnds, drawStarts, errorIdOf, forget, labelOf, onPage } from "../lib/unreadable.svelte";
import Unreadables from "./Unreadables.svelte";
import Failed from "./Failed.svelte";

const mark = (what: string, id = "1a2b3c4d") => ({ what, words: `Couldn't read this ${what}`, error_id: id, exception: "TypeError" });

function draw<P extends Record<string, unknown>>(C: never, props: P) {
  const target = document.createElement("div");
  const app = mount(C, { target, props });
  flushSync();
  return { target, done: () => unmount(app) };
}

beforeEach(() => forget());
afterEach(() => {
  connect(null);
  forget();
  location.hash = "";
});

describe("contain", () => {
  it("takes the unreadable rows out of every list, at any depth, and keeps them by the read's path", () => {
    const body = {
      sources: [{ id: 1, label: "Energy Feed" }, { id: 2, label: "Bad Feed", kind: "rss", unreadable: mark("source") }, { id: 3, label: "Other" }],
      page: { source_rows: [{ id: 2, label: "Bad Feed", unreadable: mark("source") }], themes_list: [{ cluster: 4 }] },
      total: 3,
    };
    const out = contain("/api/topics/7", body);
    expect(out.sources.map((s) => s.id)).toEqual([1, 3]);
    expect(out.page.source_rows).toEqual([]);
    expect(out.page.themes_list).toEqual([{ cluster: 4 }]);
    expect(allKept().map((r) => [r.id, r.label, r.unreadable.what])).toEqual([[2, "Bad Feed", "source"], [2, "Bad Feed", "source"]]);
    // read again with every row readable: nothing kept for the path any more
    contain("/api/topics/7", { sources: [{ id: 1 }] });
    expect(allKept()).toEqual([]);
  });

  it("a row says its label, name, title or repo, else its id", () => {
    expect(labelOf({ id: 3, name: "robotics" })).toBe("robotics");
    expect(labelOf({ id: "b-12", title: "Repo Recall" })).toBe("Repo Recall");
    expect(labelOf({ id: 9 })).toBe("9");
  });

  it("the page's rows are its reads' alone, on whatever page asked for them", () => {
    contain("/api/sources", { sources: [{ id: 2, label: "Bad Feed", unreadable: mark("source") }] });
    contain("/api/ideas?embedding=ref", { ideas: [{ id: 9, title: "x", unreadable: mark("idea", "0000beef") }] });
    drawStarts();
    asked("/api/sources");
    drawEnds();
    expect(onPage("settings").map((r) => r.unreadable.what)).toEqual(["source"]);
    expect(onPage("ideas").map((r) => r.unreadable.what)).toEqual(["source"]); // ideas' read was not asked for on this draw
    drawStarts();
    drawEnds();
    expect(onPage("settings")).toEqual([]); // another page asked for nothing of it
  });

  it("finds a failed answer's error id in its words", () => {
    expect(errorIdOf("Something went wrong on Kranto's side (error 9b9c3d2e). Try again, or send this error.")).toBe("9b9c3d2e");
    expect(errorIdOf("the server answered 502")).toBeNull();
  });
});

describe("Unreadables", () => {
  it("lists each row under the head with Send this error, which opens Feedback with the report", async () => {
    const dialog = await import("./dialog.svelte");
    const open = vi.spyOn(dialog, "openDialog").mockImplementation(() => {});
    location.hash = "#/settings/sources";
    contain("/api/sources", { sources: [{ id: 2, label: "Bad Feed", unreadable: mark("source") }] });
    drawStarts();
    asked("/api/sources");
    drawEnds();
    ui.drawn++;
    const { target, done } = draw(Unreadables as never, {});
    const row = target.querySelector("#unreadable .unread") as HTMLElement;
    expect(row.textContent).toBe("Couldn't read this source · Bad Feed · error 1a2b3c4dSend this error");
    expect(row.dataset.error).toBe("1a2b3c4d");
    (row.querySelector("button") as HTMLButtonElement).click();
    expect(open).toHaveBeenCalledTimes(1);
    const props = open.mock.calls[0]![1] as { error: string; report: string };
    expect(props.report).toBe("1a2b3c4d");
    expect(props.error).toBe("Couldn't read this source (error 1a2b3c4d)");
    expect(props.error).not.toContain("Bad Feed"); // the person's names stay out of what is sent
    done();
    open.mockRestore();
  });

  it("draws nothing while every row was read", () => {
    ui.drawn++;
    const { target, done } = draw(Unreadables as never, {});
    expect(target.querySelector("#unreadable")).toBeNull();
    done();
  });
});

describe("Failed with an error's id", () => {
  it("says the id and offers Send this error in place of Tell us", async () => {
    connect({ render: () => {}, host: () => null } as never);
    const { target, done } = draw(Failed as never, { what: "the topics", error: "Something went wrong on Kranto's side (error 9b9c3d2e). Try again, or send this error." });
    expect(target.querySelector(".failed")?.getAttribute("data-error")).toBe("9b9c3d2e");
    expect(target.querySelector(".failed .ver")?.textContent).toBe(" · error 9b9c3d2e");
    expect([...target.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Try again", "Send this error"]);
    done();
  });
});
