// A refused press says a sentence, never the answer's JSON (the owner's Needs you showed
// {"ok":false,"state":"open","answer":{"error":"fingerprint is …"}} in a red banner).
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../lib/app";
import { refusalText } from "../lib/app/data";
import { PREPARED_API, type Prepared } from "../lib/prepared";
import { ui } from "../lib/shell.svelte";
import { answering, draw, settle, stub, where } from "../pages/testing.svelte";
import { answerDialog } from "./testing";
import PreparedLine from "./PreparedLine.svelte";

const OWNERS = { ok: false, state: "open", answer: { error: "fingerprint is <stage>/<error class>, e.g. build/401-auth" } };

afterEach(() => {
  ui.facts = null;
  location.hash = "";
  vi.unstubAllGlobals();
});

describe("a refusal's words", () => {
  it("are the answer's error, a nested answer's, or its say; never the JSON", () => {
    expect(refusalText({ error: "no such build" }, "", 404)).toBe("no such build");
    expect(refusalText(OWNERS, JSON.stringify(OWNERS), 400)).toBe("fingerprint is <stage>/<error class>, e.g. build/401-auth");
    expect(refusalText({ ok: false, answer: { say: "Publish did not happen: held" } }, "", 409)).toBe("Publish did not happen: held");
    expect(refusalText({ ok: false }, '{"ok":false}', 400)).toBe("Kranto refused this without saying why (HTTP 400).");
    expect(refusalText(null, "[1, 2]", 500)).toBe("Kranto refused this without saying why (HTTP 500).");
    expect(refusalText(null, "Bad gateway", 502)).toBe("Bad gateway");
  });
});

describe("a prepared action that is refused", () => {
  it("stays on the line with a sentence and what fixes it", async () => {
    stub({ host: {} });
    ui.facts = { header: { host: { paused: false, running: null, next: null }, run: [] } } as unknown as Facts;
    location.hash = "#/topics";
    const P: Prepared = { uuid: "p9", verb: "b.factory_issue", title: "File a Kranto issue", by_words: "by Claude Code",
      page: "#/topics", words: null, fields: {}, state: "open" };
    answering({ [PREPARED_API]: { prepared: [P] } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(OWNERS), { status: 400 })));
    const { target, done } = await draw(PreparedLine as never, where("topics"));
    await settle();
    (target.querySelector(".prepared .btn.primary") as HTMLButtonElement).click();
    await answerDialog(true);
    await settle();
    const line = target.querySelector("[data-refused='p9']");
    expect(line?.textContent).toContain("File a Kranto issue can't be done: fingerprint is <stage>/<error class>, e.g. build/401-auth. Nothing happened.");
    expect(line?.textContent).toContain("Open the console");
    expect(target.textContent).not.toContain('{"ok"');
    done();
  });
});
