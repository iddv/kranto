// Feedback, drawn: the sheet in the one dialog, what Include details shows, Open on GitHub's
// link, File it's confirm and the filing (the server answered here), no network, and Tell us.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DialogHost from "./DialogHost.svelte";
import { closeDialog, dlg } from "./dialog.svelte";
import { DRAFT_KEY, forgetErrors, noteError, type FeedbackStatus } from "./feedback";
import { openFeedback, tellUs } from "./sendFeedback";

const READY: FeedbackStatus = { repo: "iddv/kranto", gh: "ready", login: "someone", reachable: true, can_file: true,
  line: "File it files the issue on iddv/kranto as someone, through your gh, after you read it.", version: "0.5.10",
  places: [["/home/someone", "<home>"]], host: "example-host" };
let host: ReturnType<typeof mount> | null = null;
let posted: { title: string; body: string; kind: string }[] = [];

function serve(st: FeedbackStatus, filing: (b: { title: string; body: string; kind: string }) => [number, unknown] = () => [200, { repo: st.repo, number: 4242, url: `https://github.com/${st.repo}/issues/4242`, labels: ["bug"], dropped: ["feedback"] }]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).startsWith("api/feedback/issue") && init?.method === "POST") {
      const b = JSON.parse(String(init.body));
      posted.push(b);
      const [code, j] = filing(b);
      return new Response(JSON.stringify(j), { status: code });
    }
    if (String(url).startsWith("api/feedback/issue")) return new Response(JSON.stringify(st), { status: 200 });
    return new Response("{}", { status: 404 });
  }));
}
const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
  }
};
const q = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const text = () => document.getElementById("dlg")!.textContent || "";
function type(s: string) {
  const t = q<HTMLTextAreaElement>("#fb-text")!;
  t.value = s;
  t.dispatchEvent(new Event("input"));
  flushSync();
}

beforeEach(() => {
  localStorage.clear();
  forgetErrors();
  posted = [];
  location.hash = "#/topics/7/ideas";
  host = mount(DialogHost, { target: document.body });
});
afterEach(() => {
  closeDialog();
  if (host) void unmount(host);
  host = null;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe("Feedback", () => {
  it("opens the sheet: the kind, one box, Include details showing exactly what it adds", async () => {
    serve(READY);
    noteError("Not graded: the card is gone");
    openFeedback();
    await settle();
    expect(text()).toContain("What happened, or what would you like?");
    expect([...document.querySelectorAll("#fb-kind [role=radio]")].map((b) => b.textContent)).toEqual(["Bug", "Idea", "Question"]);
    expect(q<HTMLInputElement>("#fb-include")!.checked).toBe(true);
    const d = q("#fb-details")!.textContent!;
    expect(d).toContain("- page: `#/topics/:id/ideas`");
    expect(d).toContain("- layout: the page alone");
    expect(d).toContain("- browser: ");
    expect(d).toContain("Not graded: the card is gone");
    expect(text()).toContain("It goes to iddv/kranto, labelled feedback and bug.");
    q<HTMLInputElement>("#fb-include")!.click();
    flushSync();
    expect(q("#fb-details")).toBeNull();
  });

  it("Open on GitHub is GitHub's new-issue page for the repository with the title, the body and the labels", async () => {
    serve({ ...READY, gh: "missing", can_file: false, login: null, line: "gh is not installed here, so Open on GitHub opens GitHub's new-issue page." });
    openFeedback();
    await settle();
    expect(q("#fb-file")).toBeNull();
    type("the brief's Run now did nothing");
    const a = q<HTMLAnchorElement>("a#fb-open")!;
    const u = new URL(a.href);
    expect(u.origin + u.pathname).toBe("https://github.com/iddv/kranto/issues/new");
    expect(u.searchParams.get("title")).toBe("Bug: the brief's Run now did nothing");
    expect(u.searchParams.get("labels")).toBe("feedback,bug");
    expect(u.searchParams.get("body")).toContain("the brief's Run now did nothing\n\n**Kind:** Bug");
    expect(u.searchParams.get("body")).toContain("- page: `#/topics/:id/ideas`");
    expect(a.target).toBe("_blank");
    expect(a.rel).toContain("noopener");
    a.addEventListener("click", (e) => e.preventDefault());
    a.click();
    flushSync();
    expect(text()).toContain("click Submit new issue there");
    expect(JSON.parse(localStorage.getItem(DRAFT_KEY)!).text).toBe("the brief's Run now did nothing");
  });

  it("File it confirms the exact issue, files it as the login and links to it; the draft is cleared", async () => {
    serve(READY);
    openFeedback();
    await settle();
    type("the brief's Run now did nothing");
    q<HTMLButtonElement>("#fb-file")!.click();
    await settle();
    expect(text()).toContain("File this issue on iddv/kranto?");
    expect(text()).toContain("Filed as someone, through your gh");
    expect(q("#fb-c-title")!.textContent).toBe("Bug: the brief's Run now did nothing");
    const body = q("#fb-c-body")!.textContent!;
    expect(body).toContain("**Kind:** Bug");
    expect(body).toContain("### Details Kranto added");
    expect(posted).toEqual([]);
    q<HTMLButtonElement>("#fb-c-ok")!.click();
    await settle();
    expect(posted).toEqual([{ kind: "bug", title: "Bug: the brief's Run now did nothing", body }]);
    expect(text()).toContain("Filed #4242 on iddv/kranto.");
    expect(q<HTMLAnchorElement>("#fb-filed a")!.href).toBe("https://github.com/iddv/kranto/issues/4242");
    expect(text()).toContain("the label feedback is not on the repository yet");
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("files nothing the server's scrub would change: the confirm shows its version", async () => {
    serve(READY, (b) => (b.body.includes("[secret]") ? [200, { repo: "iddv/kranto", number: 7, url: "https://github.com/iddv/kranto/issues/7", labels: [], dropped: [] }]
      : [409, { error: "Kranto found more to remove before filing", title: b.title, body: b.body.replace("odd-line", "[secret]") }]));
    openFeedback();
    await settle();
    type("it broke on odd-line");
    q<HTMLButtonElement>("#fb-file")!.click();
    await settle();
    q<HTMLButtonElement>("#fb-c-ok")!.click();
    await settle();
    expect(q("#fb-note")!.textContent).toContain("Kranto found more to remove before filing");
    expect(q("#fb-c-body")!.textContent).toContain("it broke on [secret]");
    q<HTMLButtonElement>("#fb-c-ok")!.click();
    await settle();
    expect(posted.length).toBe(2);
    expect(text()).toContain("Filed #7 on iddv/kranto.");
  });

  it("with no network says GitHub can't be reached, sends nothing and keeps the draft", async () => {
    serve({ ...READY, reachable: false, can_file: false, line: "GitHub can't be reached from this machine right now." });
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ kind: "idea", text: "more themes", include: true }));
    openFeedback();
    await settle();
    expect(q("#fb-offline")!.textContent).toContain("GitHub can't be reached from here right now. Your draft is kept");
    expect(q<HTMLTextAreaElement>("#fb-text")!.value).toBe("more themes");
    expect(q("a#fb-open")).toBeNull();
    expect(q<HTMLButtonElement>("button#fb-open")!.disabled).toBe(true);
    closeDialog();
    expect(JSON.parse(localStorage.getItem(DRAFT_KEY)!).text).toBe("more themes");
  });

  it("an error's Tell us opens the sheet prefilled with the error", async () => {
    serve(READY);
    tellUs("Run now failed: the brief did not answer");
    await settle();
    expect(dlg.now).not.toBeNull();
    expect(q<HTMLTextAreaElement>("#fb-text")!.value).toBe("Something went wrong: Run now failed: the brief did not answer\n\nWhat I was doing: ");
    expect(q("#fb-kind [aria-checked=true]")!.textContent).toBe("Bug");
  });
});
