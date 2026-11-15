// The console's first start. The first time Claude Code opens Kranto's own folder it
// asks whether to trust it ("Is this a project you created or one you trust?"), and an assistant
// not signed in asks for a sign-in. While such a prompt stands, a starter's sentence typed into it
// would answer the prompt, not ask Kranto. So the page says one line above the starters and holds
// the sentence until the prompt is gone. Kranto never answers it and never writes Claude Code's
// configuration to skip it (decision D1): it is the person's consent, in the person's own words.

export const TRUST_LINE = "Claude Code asks once whether to trust Kranto's own folder. Answer it here, then ask.";
export const SIGN_IN_LINE = "Claude Code asks you to sign in once. Sign in here, then ask.";

const TRUST = [
  /do you trust the files in this folder/i,
  /is this a project you created or one you trust/i,
  /yes, (?:i trust this folder|proceed)/i,
];
const SIGN_IN = [/select login method/i, /claude account with subscription/i, /paste code here if prompted/i];

/** The line to show while the screen holds the assistant's own first-run prompt, else null. */
export function firstRunPrompt(screen: string): string | null {
  if (TRUST.some((r) => r.test(screen))) return TRUST_LINE;
  if (SIGN_IN.some((r) => r.test(screen))) return SIGN_IN_LINE;
  return null;
}

/** A starter's sentence waiting to be sent: held while a first-run prompt stands, sent once the
 *  screen has gone quiet without one. ``send`` is the socket's input. */
export class Held {
  text: string | null = null;
  prompt: string | null = null;
  constructor(private send: (s: string) => void) {}

  /** a starter was clicked while the session starts or a prompt stands */
  hold(text: string): void {
    this.text = text;
  }

  /** the visible screen changed: what it now says about a first-run prompt */
  screen(text: string): string | null {
    this.prompt = firstRunPrompt(text);
    return this.prompt;
  }

  /** the screen went quiet: send the sentence unless a prompt stands. True when it was sent. */
  quiet(): boolean {
    if (!this.text || this.prompt) return false;
    this.send(this.text + "\r");
    this.text = null;
    return true;
  }

  /** a click while the session runs: sent now, or held behind the prompt */
  ask(text: string): boolean {
    if (this.prompt) {
      this.text = text;
      return false;
    }
    this.send(text + "\r");
    return true;
  }
}

/** Whether what the terminal sends is its own answer to the program's query (a cursor position,
 *  device attributes, a colour, the keyboard protocol), not the person typing. Claude Code asks
 *  these as it starts; xterm answers through onData, which read as typing hid the starters and
 *  the first-run line on the preview (the walk). */
export function isReply(d: string): boolean {
  // CSI answers end in R (cursor position), c (attributes), n (status), t (window), u (keyboard
  // flags), y (a mode's state); OSC and DCS answers; focus in and out. A key (an arrow: ESC [ A,
  // Enter, a letter) is typing.
  return /^(?:\x1b\[[?>=]?[\d;$]*[Rcntuy]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1bP[^\x1b]*\x1b\\|\x1b\[[IO])+$/.test(d)
    && !/^\x1b\[[A-D]$/.test(d);
}

/** The terminal's visible rows as text (xterm's active buffer from the viewport down). */
export function visibleText(term: { rows: number; buffer: { active: { viewportY: number; getLine(y: number): { translateToString(trim?: boolean): string } | undefined } } }): string {
  const b = term.buffer.active, out: string[] = [];
  for (let y = b.viewportY; y < b.viewportY + term.rows; y++) out.push(b.getLine(y)?.translateToString(true) ?? "");
  return out.join("\n");
}
