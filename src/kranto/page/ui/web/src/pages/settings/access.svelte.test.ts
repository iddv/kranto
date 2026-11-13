import { flushSync, mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Facts } from "../../lib/app";
import type { View, Where } from "../../lib/pages.svelte";
import { drop, setFetcher } from "../../lib/reads.svelte";
import { connect, ui } from "../../lib/shell.svelte";
import AccessList from "./AccessList.svelte";
import AccessPane from "./AccessPane.svelte";
import { ACCESS_API, type Tokens } from "./access";
import { answerDialog, dialogShown } from "../../ui/testing";

const TOKENS: Tokens = {
  require_token: true, default_actions: ["add_idea", "publish", "retry"],
  tokens: [{ name: "ui", file: "/t/ui.token", last_used: null }, { name: "mcp", file: "/t/mcp.token" },
           { name: "agent:rc", file: "/t/agent-rc.token", actions: ["add_idea"], note: "the fleet" }],
};
const where = (sel: string | null): Where => ({
  r: { path: ["settings", "access"], q: {}, sel }, node: "settings/access", list: ["settings", "access"],
  object: sel ? "need" : null, obj: sel ? ["need", sel] : null, id: sel, sel: !!sel, stage: false, missing: false,
});
let L: { act: ReturnType<typeof vi.fn>; api: ReturnType<typeof vi.fn>; say: ReturnType<typeof vi.fn>; tip: () => null; spy: () => void };

async function draw(C: typeof AccessList, sel: string | null) {
  const target = document.createElement("div");
  document.body.append(target);
  const view = $state<View>({ w: where(sel), back: sel ? "#/settings/access" : null, tick: 0 });
  const app = mount(C, { target, props: { view } });
  for (let i = 0; i < 3; i++) {
    await new Promise((r) => setTimeout(r, 0)); // the read arrives, then what it sets
    flushSync();
  }
  return { target, app };
}
beforeEach(() => {
  drop(ACCESS_API);
  setFetcher(async () => structuredClone(TOKENS));
  L = {
    act: vi.fn(async (_btn: unknown, fn: () => Promise<unknown>, done?: (r: unknown) => void) => { done?.(await fn()); }),
    api: vi.fn(async () => ({ tokens: TOKENS.tokens, name: "agent:new", file: "/t/agent-new.token" })),
    say: vi.fn(), tip: () => null, spy: () => {},
  };
  connect(L as never);
  ui.facts = { header: { host: { paused: false, running: null, next: null } } } as unknown as Facts;
});
afterEach(() => {
  connect(null);
  ui.facts = null;
  document.body.replaceChildren();
});

describe("Settings › Privacy & access", () => {
  it("lists the doors and the agents, each a row that opens in the pane", async () => {
    const { target, app } = await draw(AccessList, null);
    const rows = [...target.querySelectorAll("li.row")];
    expect(rows.map((r) => r.getAttribute("data-sel"))).toEqual(["etok:ui", "etok:mcp", "etok:agent:rc"]);
    expect(rows[0]?.querySelector(".r-title")?.textContent).toBe("This page");
    expect(rows[2]?.querySelector(".c-meta")?.textContent).toBe("may run 1 action · not used since Kranto started · the fleet");
    expect(target.querySelector("#add-agent")?.getAttribute("href")).toBe("#/settings/access?sel=enew-agent");
    expect(target.querySelector(".tbn")).toBeNull(); // tokens are required: no warning
    expect(target.querySelector("input, textarea, select")).toBeNull(); // never a field in the list
    unmount(app);
  });

  it("says where the tokens are kept without the server", async () => {
    ui.facts = { header: { host: null } } as unknown as Facts;
    const { target, app } = await draw(AccessList, null);
    expect(target.textContent).toContain("kranto token list shows them");
    unmount(app);
  });

  it("opens an agent's token: its file, its own list of actions, Save and Revoke", async () => {
    const { target, app } = await draw(AccessPane, "etok:agent:rc");
    expect(target.querySelector(".dback a")?.getAttribute("href")).toBe("#/settings/access");
    expect(target.querySelector(".dt")?.textContent).toBe("agent rc");
    expect([...target.querySelectorAll(".toc a")].map((a) => a.textContent)).toEqual(["Where it is", "What it may run", "Last used"]);
    const boxes = [...target.querySelectorAll<HTMLInputElement>("#agent-actions input")];
    expect(boxes.map((b) => [b.value, b.checked])).toEqual([["add_idea", true], ["publish", false], ["retry", false]]);
    boxes[1]!.click();
    flushSync();
    (target.querySelector("#save-actions") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 0));
    expect(L.api).toHaveBeenCalledWith("/api/tokens/agent%3Arc/actions", { actions: ["add_idea", "publish"] });
    expect(L.say).toHaveBeenCalledWith("agent rc may now run 2 actions.");
    expect(target.querySelector("#revoke-token")).not.toBeNull();
    unmount(app);
  });

  it("asks before Rotate, and a door has no Revoke", async () => {
    const { target, app } = await draw(AccessPane, "etok:ui");
    expect(target.querySelector("#revoke-token")).toBeNull();
    (target.querySelector("#rotate-token") as HTMLButtonElement).click();
    expect(dialogShown()?.title).toBe("Rotate this page's token?");
    answerDialog(false);
    expect(L.api).not.toHaveBeenCalled();
    unmount(app);
  });

  it("adds an agent only with a name it can have", async () => {
    const { target, app } = await draw(AccessPane, "enew-agent");
    const go = target.querySelector("#add-agent-go") as HTMLButtonElement;
    go.click();
    expect(L.act).not.toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("agent-name");
    const name = target.querySelector("#agent-name") as HTMLInputElement;
    name.value = "has space";
    name.dispatchEvent(new Event("input"));
    go.click();
    expect(L.act).not.toHaveBeenCalled();
    name.value = "helper";
    name.dispatchEvent(new Event("input"));
    go.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(L.api).toHaveBeenCalledWith(ACCESS_API, { name: "agent:helper", note: "" });
    expect(L.say.mock.calls[0]?.[0]).toMatch(/^Added agent:new\. Its token is in \/t\/agent-new\.token/);
    unmount(app);
  });
});
