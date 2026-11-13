// Untrusted text drawn safely. A trace shows what a session read and ran:
// READMEs, web pages, issues, command output, any of which may try to talk to whoever reads
// it. Every string is drawn as text (Svelte's {expression}, never HTML: CONVENTIONS.md), and
// first passes through here: ANSI colour codes are dropped, never interpreted; other control
// characters show as their picture (␛ for ESC); the bidi overrides and isolates that could
// reorder what the owner reads (U+202A to U+202E, U+2066 to U+2069) show as their code point.
// Images and links stay their source text (ui/md.ts has neither).

const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
const BIDI = /[‪-‮⁦-⁩]/g;
// C0 controls but tab and newline, DEL, and the C1 controls
const CONTROL = /[\x00-\x08\x0b-\x1f\x7f\x80-\x9f]/g;

export function safeText(s: string | null | undefined): string {
  return String(s ?? "")
    .replace(ANSI, "")
    .replace(BIDI, (c) => `<U+${c.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}>`)
    .replace(CONTROL, (c) => {
      const n = c.charCodeAt(0);
      return n < 0x20 ? String.fromCharCode(0x2400 + n) : n === 0x7f ? "␡" : "�";
    });
}

/** a URL in a trace, as the inspector offers it: its host first, opened only on a press (never
 * a live link in the text) and only for http and https */
export function safeUrl(s: string): { host: string; href: string } | null {
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? { host: u.host, href: u.href } : null;
  } catch {
    return null;
  }
}
