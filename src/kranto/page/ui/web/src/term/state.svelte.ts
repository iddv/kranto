// Which subject Open in Claude Code's panel is open for (App.svelte draws it in #term; the app's
// `c` key and buttons open it). Closing the panel leaves the session running.
import type { Subject } from "./api";

export const termUi: { subject: Subject | null; title: string; n: number; enabled: boolean; why: string | null } =
  $state({ subject: null, title: "", n: 0, enabled: false, why: null });

/** Whether Open in Claude Code is on (term.enabled; automatic by default): read once at boot.
 * While it is off, `c` and its buttons say how to turn it on (`why`, api/term's own words). */
export async function loadTermStatus(): Promise<boolean> {
  try {
    const r = await fetch("api/term", { cache: "no-store" });
    const j = r.ok ? ((await r.json()) as { enabled?: boolean; why?: string | null }) : null;
    termUi.enabled = !!j?.enabled;
    termUi.why = j?.enabled ? null : j?.why || null;
  } catch {
    termUi.enabled = false;
    termUi.why = null;
  }
  return termUi.enabled;
}

export function openTerm(kind: Subject["kind"], id: string, title = ""): void {
  if (termUi.subject?.kind !== kind || termUi.subject?.id !== id) termUi.n++;
  termUi.subject = { kind, id };
  termUi.title = title;
}

export function closeTerm(): boolean {
  if (!termUi.subject) return false;
  termUi.subject = null;
  return true;
}

/** Whether a key event comes from inside the terminal: it belongs to the terminal then. */
export function inTerminal(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest("#term .screen");
}
