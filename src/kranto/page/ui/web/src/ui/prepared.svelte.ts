// A prepared item's two actions, the same wherever it shows (Needs you, the home, its page's
// line, the toast): approve it (the owner's own, the page's cookie: the server's
// POST /api/prepared/<uuid>/press) or dismiss it. Its dialog reads it back once. The toast (// #490): when an assistant prepares something, one line in a corner of whichever page is open,
// with the action's own button (never for a locked kind) and Open; a bar runs down over 8 s,
// hovering pauses it, and on time out nothing happens: the item stays in Needs you.
import { afkStale, api, load } from "../lib/app/data";
import { ApiError } from "../api/client";
import { buttonOf, gone, plainTitle, PREPARED_API, type Prepared } from "../lib/prepared";
import { drop } from "../lib/reads.svelte";
import { app } from "../lib/shell.svelte";
import type { VerbLine } from "../term/reflect.svelte";
import { openDialog } from "./dialog.svelte";
import PreparedDialog from "./PreparedDialog.svelte";
import { followWrite, WEEK, type About } from "../features/post/post";

export const TOAST_MS = 8000;

/** a press's answer: the verb's own answer; a job when the work runs on (post.write) */
type PressAnswer = { ok?: boolean; answer?: { say?: string; about?: unknown; as?: unknown; job?: { state?: string; error?: string | null } } };
/** post.write's about (card:<n>, brief:<id>:<item>, week) as Write a post's question knows it */
function aboutOf(about: string): About {
  const c = /^card:(\d+)$/.exec(about), b = /^brief:(\d+):(\d+)$/.exec(about);
  if (c) return { card: Number(c[1]), title: "", sources: 0 };
  if (b) return { brief: Number(b[1]), n: Number(b[2]) - 1, title: "", sources: 0 };
  return WEEK;
}

/** a refusal's sentence by the item's uuid: it stays on the item's row (never the JSON) */
export const refusedPrepared = $state<Record<string, string>>({});

/** the toast: the items it says and how much of its time is left */
export const PTOAST = $state<{ items: Prepared[]; left: number; paused: boolean }>({ items: [], left: 0, paused: false });

/** approve or dismiss; true when it was done */
export async function actPrepared(p: Prepared, what: "approve" | "dismiss"): Promise<boolean> {
  // an item whose verb left Kranto is only ever put away; a press that meets one anyway (410:
  // the verb left since the page read it) puts it away too, never a red refusal
  if (gone(p)) what = "dismiss";
  let ok = false;
  try {
    const r = (await api(`${PREPARED_API}/${p.uuid}/${what === "approve" ? "press" : "dismiss"}`, {})) as PressAnswer | null;
    if (what === "approve") {
      // the change shows: the page reads it again, as after an assistant's verb (PAR: an
      // archived topic stayed on Watch until a reload)
      afkStale("/");
      await load();
    }
    const job = r?.answer?.job;
    if (what === "approve" && job && job.state === "running") {
      // work that runs on (Write a post): started, not done; the page follows it and says how
      // it ended, and a failure stays on Post (4, Codex 1: "Write a post: done" for none)
      app()?.say(`${plainTitle(p)}: started. ${r?.answer?.say || "It runs in the background."}`, "green");
      const a = r?.answer;
      if (a && typeof a.about === "string") void followWrite(aboutOf(a.about), String(a.as || "blog"));
    } else if (what === "approve" && job && job.state === "failed") {
      app()?.say(`${plainTitle(p)} did not work: ${job.error || "it failed"}.`, "red");
    } else app()?.say(what === "approve" ? `${plainTitle(p)}: done.` : `${plainTitle(p)}: put away; nothing happened.`, what === "approve" ? "green" : "grey");
    delete refusedPrepared[p.uuid];
    ok = true;
  } catch (e) {
    const why = (e as Error).message.replace(/\.$/, "");
    if (what === "approve" && e instanceof ApiError && e.status === 410) {
      forgetToast(p.uuid);
      return actPrepared({ ...p, available: false }, "dismiss");
    }
    if (what === "approve") refusedPrepared[p.uuid] = `${plainTitle(p)} can't be done: ${why}. Nothing happened.`;
    else app()?.say(`${plainTitle(p)}: not put away: ${why}.`, "red");
  }
  forgetToast(p.uuid);
  drop(PREPARED_API, true);
  drop("api/activity", true);
  app()?.render();
  return ok;
}

/** the dialog: the item read back once, its button the action's own words, and Cancel */
export function openPrepared(p: Prepared): void {
  if (gone(p)) {
    void actPrepared(p, "dismiss"); // nothing to read back: its one button puts it away
    return;
  }
  openDialog(PreparedDialog, { p, title: `${plainTitle(p)}?`, okText: buttonOf(p), onOk: (_b: HTMLElement, close: () => void) => {
    close();
    return actPrepared(p, "approve");
  } });
}

let timer: ReturnType<typeof setInterval> | undefined;
const STEP = 100;

/** items an assistant just prepared: into the toast (merged with what it says), its time anew */
export function toastPrepared(items: Prepared[]): void {
  const have = new Set(PTOAST.items.map((p) => p.uuid));
  const add = items.filter((p) => p.state === "open" && !gone(p) && !have.has(p.uuid));
  if (!add.length) return;
  PTOAST.items = [...add, ...PTOAST.items];
  PTOAST.left = TOAST_MS;
  if (!timer) {
    timer = setInterval(() => {
      if (PTOAST.paused) return;
      PTOAST.left = Math.max(0, PTOAST.left - STEP);
      if (!PTOAST.left) closeToast();
    }, STEP);
  }
}

/** an item approved or dismissed (here or on another page): out of the toast */
export function forgetToast(uuid: string): void {
  PTOAST.items = PTOAST.items.filter((p) => p.uuid !== uuid);
  if (!PTOAST.items.length) closeToast();
}

/** the live feed's new lines (term/reflect): an item prepared just now goes into the toast; one
 * approved or dismissed (here or on another page) out of it; Needs you, its count and the home
 * read the items and the waiting runs again at once */
export async function noticePrepared(lines: VerbLine[]): Promise<void> {
  for (const x of lines) if (x.prepared && x.resolved) forgetToast(x.prepared);
  const fresh = lines.filter((x) => x.prepared && !x.resolved).map((x) => x.prepared as string);
  if (!lines.some((x) => x.prepared)) return;
  drop(PREPARED_API, true);
  drop("api/activity", true);
  if (!fresh.length) return;
  try {
    const got = (await api(PREPARED_API)) as { prepared?: Prepared[] };
    toastPrepared((got.prepared || []).filter((p) => fresh.includes(p.uuid)));
  } catch {
    /* the toast is a convenience: the item is in Needs you whatever happens here */
  }
}

/** the toast goes; nothing happens to what it said (it stays in Needs you) */
export function closeToast(): void {
  PTOAST.items = [];
  PTOAST.left = 0;
  PTOAST.paused = false;
  clearInterval(timer);
  timer = undefined;
}
