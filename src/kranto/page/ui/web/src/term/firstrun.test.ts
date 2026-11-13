// on the preview the console's first start showed Claude Code's "Is this a project
// you created or one you trust?" and a starter's sentence would have been typed into it. The
// screen's prompt is recognised, a line says what it is, and the sentence waits until it is gone.
import { describe, expect, it } from "vitest";
import { firstRunPrompt, Held, isReply, SIGN_IN_LINE, TRUST_LINE, visibleText } from "./firstrun";

// Claude Code's trust screen as the preview's console drew it (the words, not the box drawing)
const TRUST_SCREEN = [
  " Do you trust the files in this folder?",
  "",
  " /home/user/kranto-preview/home",
  "",
  " Is this a project you created or one you trust? (Like your own code, a well-known open source",
  " project, or work from your team). If not, take a moment to review what's in this folder first.",
  "",
  " ❯ 1. Yes, proceed",
  "   2. No, exit",
].join("\n");
const PROMPT_SCREEN = " ✻ Welcome to Claude Code!\n\n > \n  ? for shortcuts";

function fakeTerm(screen: string) {
  const lines = screen.split("\n");
  return { rows: lines.length, buffer: { active: { viewportY: 0, getLine: (y: number) => ({ translateToString: () => lines[y] ?? "" }) } } };
}

describe("the console's first start", () => {
  it("knows the trust prompt and the sign-in, and nothing else", () => {
    expect(firstRunPrompt(TRUST_SCREEN)).toBe(TRUST_LINE);
    expect(firstRunPrompt(" Select login method:\n ❯ 1. Claude account with subscription")).toBe(SIGN_IN_LINE);
    expect(firstRunPrompt(PROMPT_SCREEN)).toBeNull();
    expect(TRUST_LINE).toBe("Claude Code asks once whether to trust Kranto's own folder. Answer it here, then ask.");
  });

  // the walk on the preview: Claude Code asks the terminal where its cursor is and what it is as
  // it starts; xterm's answers came through onData, read as typing, and hid the line and the starters
  it("tells the terminal's own answers from typing", () => {
    for (const reply of ["\x1b[12;1R", "\x1b[?1;2c", "\x1b[>0;276;0c", "\x1b[0n", "\x1b[?0u", "\x1b[?2026;2$y",
      "\x1b]11;rgb:0d0d/1111/1717\x1b\\", "\x1b]10;rgb:e6e6/eded/f3f3\x07", "\x1b[I", "\x1b[O", "\x1b[12;1R\x1b[?1;2c"]) {
      expect(isReply(reply), JSON.stringify(reply)).toBe(true);
    }
    for (const typed of ["a", "\r", "1", "\x1b[A", "\x1b[B", "\x1b", "What is new in Padel?\r", "\x1b[200~pasted\x1b[201~"]) {
      expect(isReply(typed), JSON.stringify(typed)).toBe(false);
    }
  });

  it("reads the terminal's visible rows", () => {
    expect(visibleText(fakeTerm(TRUST_SCREEN))).toContain("Is this a project you created");
  });

  it("sends nothing while the prompt stands, and the sentence once it is gone", () => {
    const sent: string[] = [];
    const h = new Held((s) => sent.push(s));
    // a starter clicked while the session starts: held
    h.hold("What is new in Padel?");
    expect(h.screen(visibleText(fakeTerm(TRUST_SCREEN)))).toBe(TRUST_LINE);
    expect(h.quiet()).toBe(false);
    // a click while it runs, behind the prompt: held too, never typed into the prompt
    expect(h.ask("Which idea should I look at?")).toBe(false);
    expect(sent).toEqual([]);
    // the person answered it: the assistant waits at its prompt, the sentence goes
    expect(h.screen(PROMPT_SCREEN)).toBeNull();
    expect(h.quiet()).toBe(true);
    expect(sent).toEqual(["Which idea should I look at?\r"]);
    expect(h.ask("What is new in Padel?")).toBe(true);
    expect(sent).toHaveLength(2);
  });
});
