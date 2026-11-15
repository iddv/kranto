import { afterEach, describe, expect, it } from "vitest";
import { createRawSnippet, flushSync, mount, unmount } from "svelte";
import { answering, draw, settle } from "../pages/testing.svelte";
import Details from "./Details.svelte";
import DialogFrame from "./DialogFrame.svelte";
import { closeDetails, DETAILS, detailsPath, openDetails } from "./details.svelte";

// the record behind a row or a dialog, in a drawer, from the read the console's
// kranto_details answers too
const REC = { sel: "card:143", kind: "idea", title: "Padel court finder", page: "#/ideas/143", tool: "kranto_details card:143",
  groups: [{ h: "What", rows: [["state", "waiting"], ["thesis", "Clubs book by phone."]] }, { h: "Where from", rows: [["theme", "#/watch/map?sel=c4"]] }] };

afterEach(() => closeDetails());

describe("the Details drawer", () => {
  it("draws the record's groups, its page and the console's call for it, and closes with Esc", async () => {
    answering({ [detailsPath("card:143")]: REC });
    const { target, done } = await draw(Details as never, {} as never);
    expect(target.querySelector("#details")).toBeNull();
    openDetails("card:143");
    flushSync();
    await settle();
    const d = target.querySelector("#details")!;
    expect(d.querySelector("h2")?.textContent).toBe("Padel court finder");
    expect([...d.querySelectorAll("h3")].map((h) => h.textContent)).toEqual(["What", "Where from"]);
    expect([...d.querySelectorAll("dt")].map((x) => x.textContent)).toEqual(["state", "thesis", "theme"]);
    expect(d.querySelector("dd a")?.getAttribute("href")).toBe("#/watch/map?sel=c4");
    expect(d.querySelector(".page a")?.getAttribute("href")).toBe("#/ideas/143");
    expect(d.querySelector(".tools code")?.textContent).toBe("kranto_details card:143");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    flushSync();
    expect(DETAILS.sel).toBeNull();
    done();
  });

  it("is a decision dialog's Details: at the foot's left, beside Cancel", async () => {
    const target = document.createElement("div");
    document.body.append(target);
    const app = mount(DialogFrame, { target, props: { title: "File a Kranto issue?", okText: "File issue", ok: () => {}, close: () => {}, details: "prep:6dbbc192",
      children: createRawSnippet(() => ({ render: () => "<p>A new issue.</p>" })) } });
    const done = () => { void unmount(app); target.remove(); };
    const foot = target.querySelector(".dlg-f")!;
    expect([...foot.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Details", "Cancel", "File issue"]);
    (foot.querySelector("#dlg-details") as HTMLButtonElement).click();
    expect(DETAILS.sel).toBe("prep:6dbbc192");
    done();
  });
});
