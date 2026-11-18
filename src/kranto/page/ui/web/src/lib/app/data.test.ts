// The data and the action (data.ts): the claims test_workspace_shell, test_header_lanes,
// test_topics_ui, test_unified_ui and test_update_ui read off the old source.
import { afterEach, describe, expect, it, vi } from "vitest";
import { parse } from "../router";
import { chromeFacts } from "./chrome";
import { act, api, hostForm, loadHost, signIn, togglePause, updApply, updCancel, updRollback } from "./data";
import { frame, hostStatus, unframe } from "./testing";
import { answerDialog, dialogShown } from "../../ui/testing";

afterEach(() => {
  vi.restoreAllMocks();
  unframe();
});
const flash = () => chromeFacts(parse())?.head.flash || null;

describe("an action", () => {
  it("makes its button busy, and gives the button back before done", async () => {
    const net = await frame();
    const btn = document.createElement("button");
    let during: [boolean, string | null] | null = null;
    let atDone: boolean | null = null;
    await act(btn, async () => {
      during = [btn.disabled, btn.getAttribute("aria-busy")];
      return 7;
    }, (r) => {
      atDone = btn.disabled;
      expect(r).toBe(7);
    });
    expect(during).toEqual([true, "true"]);
    expect(atDone).toBe(false);
    expect(btn.hasAttribute("aria-busy")).toBe(false);
    expect(net.calls.some(([u]) => u === "api/kranto")).toBe(false); // there is no snapshot to read
  });

  it("says a failure in red and gives the button back", async () => {
    await frame();
    const btn = document.createElement("button");
    await act(btn, async () => {
      throw new Error("Not now.");
    });
    expect(btn.disabled).toBe(false);
    expect(flash()).toMatchObject({ text: "Not now.", kind: "red" });
  });

  it("posts JSON to the page's API and shows the sign-in line after a 401", async () => {
    const net = await frame({ who: { origin: "ann", require_token: true } });
    net.answer["api/x"] = new Response(JSON.stringify({ error: "Sign in first." }), { status: 401 });
    await expect(api("api/x", { a: 1 })).rejects.toThrow("Sign in first.");
    expect(net.calls.at(-1)?.[1]).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" }, body: '{"a":1}' });
    expect(chromeFacts(parse())?.head.signin).toBe(true);
  });

  it("signs in with the code kranto open printed, then says it can act", async () => {
    const net = await frame({ who: { origin: null, require_token: true } });
    net.answer["/auth/code"] = { ok: true };
    net.answer["/api/whoami"] = { origin: "ann", require_token: true };
    await signIn("1234", document.createElement("button"));
    expect(net.calls.find(([u]) => u === "/auth/code")?.[1]?.body).toBe('{"code":"1234"}');
    expect(chromeFacts(parse())?.head).toMatchObject({ signin: false, flash: { text: "Signed in: this browser can act now." } });
  });
});

describe("the server's forms", () => {
  it("asks for JSON, and fails on a half that did not change", async () => {
    const net = await frame();
    net.answer["/pause"] = new Response(JSON.stringify({ ok: false, error: "watching did not pause" }), { status: 502 });
    await expect(hostForm("/pause", { reason: "x" })).rejects.toThrow("watching did not pause");
    const [, init] = net.calls.at(-1)!;
    expect(init).toMatchObject({ method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" }, body: "reason=x" });
    net.answer["/resume"] = { ok: true };
    await expect(hostForm("/resume")).resolves.toBe(null);
  });

  it("asks before Pause, then says Paused only when watching reads back paused", async () => {
    const net = await frame();
    await togglePause(null, true);
    expect(dialogShown()).toEqual({ title: "Pause everything?", text: "This stops reading sources and writing ideas. Resume starts them again." });
    answerDialog(false);
    expect(net.calls.some(([u]) => u === "/pause")).toBe(false); // nothing changed before the answer
    net.answer["/pause"] = { ok: true };
    net.answer["/api/status"] = hostStatus({ paused: "by hand" });
    await togglePause(null, true);
    await answerDialog(true);
    expect(flash()?.text).toBe("Paused: this stops reading sources and writing ideas.");
    expect(flash()?.kind).not.toBe("red");
    // the form answered, but watching did not pause
    net.answer["/api/status"] = hostStatus();
    await togglePause(null, true);
    await answerDialog(true);
    expect(flash()).toMatchObject({ text: "Not paused: watching did not change.", kind: "red" });
  });

  it("says Pause is the server's without it, and posts nothing", async () => {
    const net = await frame({ host: null });
    await togglePause(null, true);
    await answerDialog(true);
    expect(net.calls.some(([u]) => u === "/pause")).toBe(false);
    expect(flash()).toMatchObject({ text: "Pause is the server's, which is not answering.", kind: "red" });
  });
});

describe("an update", () => {
  const upd = (o: object) => hostStatus({ update: { ...hostStatus().update, ...o } });

  it("restarts, rolls back after asking, and lets a waiting one go, each saying so", async () => {
    const net = await frame();
    net.answer["/api/update"] = { to: "0.3.75", when: "now" };
    await updApply(null, { when: "now" });
    expect(net.calls.find(([u]) => u === "/api/update")?.[1]?.body).toBe('{"when":"now"}');
    expect(flash()?.text).toBe("Updating to 0.3.75. Kranto restarts by itself; this page reloads when the new version answers.");
    updRollback(null, "0.3.73");
    expect(dialogShown()).toEqual({ title: "Roll back to 0.3.73?", text: "Kranto restarts on it; the data stays as it is." });
    answerDialog(false);
    expect(net.calls.some(([u]) => u === "/api/update/rollback")).toBe(false);
    net.answer["/api/update/cancel"] = {};
    await updCancel(null);
    expect(flash()?.text).toBe("The update is cancelled; nothing was changed.");
  });

  it("keeps the last status while Kranto restarts, and reloads the page when the new version answers", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const net = await frame({ host: upd({ state: "installing", to: "0.3.75" }) });
      await loadHost(); // an update runs: /api/status every 5 s
      net.answer["/api/status"] = new Response("", { status: 502 });
      await loadHost();
      expect(chromeFacts(parse())?.header.update?.word).toBe("Updating"); // the last read is kept
      const reload = vi.fn();
      vi.stubGlobal("location", { ...location, reload, hash: location.hash });
      net.answer["/api/status"] = upd({ state: "installing" });
      (net.answer["/api/status"] as { version: string }).version = "0.3.75";
      await loadHost();
      expect(reload).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
