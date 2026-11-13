// Feedback's doors (FB): the header's Feedback, ⌘K's Send feedback, Settings › Overview, the help
// page (#/?feedback=1) and every red line's Tell us open the one sheet (Feedback.svelte) in the
// dialog. What the page knows goes in here: the names the details must not carry, the layout,
// the address the sheet was opened on (before the dialog), and the update state the server keeps.
import { openDialog } from "./dialog.svelte";
import Feedback from "./Feedback.svelte";
import FeedbackConfirm from "./FeedbackConfirm.svelte";
import type { Draft, Facts, FeedbackStatus, Issue, Names } from "./feedback";
import { seenErrors } from "./feedback";
import { host } from "../lib/app/data";
import { frameNew } from "../features/shell";
import { errorIdOf } from "../lib/unreadable.svelte";
import { peek } from "../lib/reads.svelte";
import { IDEAS_API } from "../pages/ideas/cards";

/** the names of what the person keeps in Kranto, as far as this page has read them: the topics, and
 * the idea cards' titles (the cards' read, if it was made; never asked from here) */
export function namesNow(): Names {
  const H = host();
  const titles: string[] = [];
  const cards = peek<unknown>(IDEAS_API)?.data;
  const rows = (Array.isArray(cards) ? cards : (cards as { ideas?: unknown[] } | null | undefined)?.ideas || []) as { title?: string }[];
  for (const c of rows) if (c && c.title) titles.push(c.title);
  return { topics: (H ? H.topics : []).map((t) => t.name), titles };
}

/** the facts the details are made of; the version and the update state come later (reads) */
export function factsNow(hash: string = location.hash): Facts {
  const H = host();
  const layout = !H ? "the page alone" : frameNew(true) ? "New" : "Classic";
  return { version: "", layout: layout + (innerWidth < 720 ? ", a phone-sized window" : ""), hash, ua: navigator.userAgent, update: null, errors: [...seenErrors()] };
}

/** the sheet; error: a red line's words, said in the draft (Tell us); report: the id of an error
 * Kranto kept (RCA B3), whose report goes with it, shown in the sheet first */
let REPORT: string | null = null; // the error the open sheet sends: kept through its confirm's Back
export function openFeedback(o: { error?: string; report?: string | null } = {}): void {
  REPORT = o.report || null;
  openDialog(Feedback, { error: o.error || null, report: REPORT, hash: location.hash, back: null }, { wide: true });
}
export const tellUs = (error: string): void => openFeedback({ error, report: errorIdOf(error) });
/** Send this error: Feedback with the error's report (its id, its kind, Kranto's own code lines, the
 * version, the OS, the doctor's summary), from a "Couldn't read" row, an error page or a Fix row */
export const sendError = (id: string, words: string): void => openFeedback({ error: `${words} (error ${id})`, report: id });

/** the sheet again after its confirm (Back, or the result) */
export function backToSheet(hash: string, after: { filed?: { number: number; url: string; repo: string; dropped: string[] } | null; error?: string | null } = {}): void {
  if (after.filed) REPORT = null; // filed: the next one is a new sheet
  openDialog(Feedback, { error: null, report: REPORT, hash, back: after }, { wide: true });
}
/** File it's confirm: exactly the issue, the repository and who files it */
export function confirmFiling(st: FeedbackStatus, d: Draft, x: Issue, hash: string, note: string | null = null): void {
  openDialog(FeedbackConfirm, { st, draft: d, issue: x, hash, note }, { wide: true });
}
