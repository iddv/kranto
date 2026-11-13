// Check for updates, wherever it is pressed (the owner, 2026-10-22: "we should add the check for
// updates button as well"): ⌘K, the version in the status bar, Settings' Overview and Updates. One
// press asks the server's POST /api/update/check; the answer is said in words where it was pressed,
// with its next step: the latest, a release ready (Restart to update), or why the check failed and
// what to do about it.
import { put } from "../../lib/reads.svelte";
import { app } from "../../lib/shell.svelte";
import { UPD_API, type UpdateState } from "./updates";

export interface CheckAnswer {
  tone: "green" | "blue" | "red";
  text: string;
  /** the next step: a link, or Restart to update (Kranto updates itself after the build) */
  next: { word: string; href?: string; restart?: boolean } | null;
}

type Host = { version?: string; update?: { installed?: string | null } | null } | null;

/** the version Kranto shows ("0.5.10"), or null without the server (nothing to update from here) */
export function versionNow(): string | null {
  const H = (app()?.host() || null) as Host;
  return (H && (H.update?.installed || H.version)) || null;
}

// " for iddv/kranto's releases" (written without a quote mark, which the words guard would read as a string)
const REPO_RELEASES = new RegExp(" for [\\w.-]+/[\\w.-]+\\u0027s releases");
/** GitHub's words without the repo's name: "GitHub answered 404 (a private repo needs a GitHub login)" */
export const tidyError = (e: string | null | undefined): string =>
  String(e || "no reason given").replace(REPO_RELEASES, "").trim();

/** the next step after a failed check: a login GitHub can see the repo with, or the Updates page */
function nextAfter(error: string): CheckAnswer["next"] {
  if (/\b40[14]\b|private repo|not logged in|GitHub login/i.test(error))
    return { word: "Run gh auth login on the machine Kranto runs on, then check again", href: "#/settings/updates" };
  return { word: "Settings › System › Updates", href: "#/settings/updates" };
}

/** what the check answered, in words */
export function answerOf(r: UpdateState): CheckAnswer {
  const have = r.installed?.version || versionNow() || "";
  // the preview never updates: it says so, at once (10: "Checking…" hung there)
  const off = (r as UpdateState & { off?: boolean }).off;
  if (!r.ok && off) return { tone: "blue", text: r.error || "Updates are off here", next: null };
  if (!r.ok) {
    const why = tidyError(r.error);
    return { tone: "red", text: `Can't check for updates: ${why}`, next: nextAfter(why) };
  }
  if (!r.available) return { tone: "green", text: `You're on the latest, ${have} (checked just now)`, next: null };
  const staged = !!r.staged && r.staged.version === r.available;
  if (!r.can_apply)
    return { tone: "blue", text: `${r.available} is ready · this Kranto updates from the command line: kranto update`, next: { word: "How to update", href: "#/settings/updates" } };
  if (!staged)
    return { tone: "blue", text: `${r.available} is available · ${r.stage_error ? "not downloaded: " + r.stage_error : "downloading it"}`, next: { word: "Settings › System › Updates", href: "#/settings/updates" } };
  return { tone: "blue", text: `${r.available} is ready · Restart to update`, next: { word: "Restart to update", restart: true } };
}

/** one check, now: the refreshed view kept for Settings › Updates and the header re-read */
export async function checkNow(): Promise<CheckAnswer> {
  const L = app();
  if (!L) return { tone: "red", text: "Can't check for updates: the page is not ready", next: null };
  try {
    const r = (await L.api(UPD_API + "/check", {})) as UpdateState;
    put(UPD_API, r);
    await L.loadHost();
    L.render();
    return answerOf(r);
  } catch (e) {
    const why = tidyError((e as Error).message);
    return { tone: "red", text: `Can't check for updates: ${why}`, next: nextAfter(why) };
  }
}
