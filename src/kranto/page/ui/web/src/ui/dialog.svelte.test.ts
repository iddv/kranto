// The one dialog closes when the page moves on (a link, Back, a key): "Decline this draft?" stayed
// open over Settings › Posting. One opened right after its own move (a page that sets the address
// and then asks) stays.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import DialogHost from "./DialogHost.svelte";
import { closeDialog, confirmThen, dlg } from "./dialog.svelte";

let host: ReturnType<typeof mount> | null = null;
afterEach(() => {
  closeDialog();
  if (host) void unmount(host);
  host = null;
  document.body.replaceChildren();
  location.hash = "";
});
const fire = () => { window.dispatchEvent(new HashChangeEvent("hashchange")); flushSync(); };

describe("the one dialog", () => {
  it("closes when the address changes to another page", () => {
    location.hash = "#/post/d/2";
    host = mount(DialogHost, { target: document.body });
    confirmThen("Decline this draft?", "It moves to Earlier drafts.", "Decline", () => {});
    expect(document.getElementById("dlg-t")?.textContent).toBe("Decline this draft?");
    location.hash = "#/settings/posting";
    fire();
    expect(dlg.now).toBeNull();
    expect(document.getElementById("dlg-t")).toBeNull();
  });

  it("stays when it was opened at the address the page just moved to", () => {
    host = mount(DialogHost, { target: document.body });
    location.hash = "#/ideas";
    confirmThen("Write a post about this idea?", "One sentence.", "Write draft", () => {});
    fire();                                   // the move's own event, after the dialog opened
    expect(document.getElementById("dlg-t")?.textContent).toBe("Write a post about this idea?");
  });
});
