// An installed cub's verbs, one copy for its Settings page and its
// controls: a kind sent for real or in practice (for real is the house confirm, here only), on or
// off, Stop; and the one dialog of what it asks (openAsk: AskDialog).
import { app } from "../lib/shell.svelte";
import { confirmThen, openDialog } from "../ui/dialog.svelte";
import { FEATURES_API, type ActionDecl, type FeatureRow, type RequestSchema } from "./index";
import { askPath, type AskRef } from "./ask";
import { actPath, CUBS_API, cubPath, subjectField } from "./cub";
import AskDialog from "./cub/AskDialog.svelte";

/** the reads a cub's state shows in, read again */
export function cubFresh(): void {
  const L = app();
  L?.afkStale(CUBS_API);
  L?.afkStale(FEATURES_API);
}
/** one of the cub's verbs (POST /api/cubs/<id>/<verb>), then what it says */
export function cubPost(id: string, btn: HTMLElement | null, verb: string, body: Record<string, unknown>, said: string): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api(cubPath(id, verb), body), () => {
    cubFresh();
    L.say(said);
  });
}
/** a kind it may ask for, for real or in practice: for real takes the house confirm and says what an approval will do */
export function cubLive(id: string, title: string, kind: string, on: boolean, schemas: Record<string, RequestSchema>, btn: HTMLElement): void {
  if (!on) {
    cubPost(id, btn, "dry", { kind }, `${title}: ${kind} is practice now. Approving what it asks sends nothing.`);
    return;
  }
  const s = schemas[kind];
  const what = s ? s.title.toLowerCase() : kind;
  confirmThen(`Send for real from ${title}?`, [
    `For real: approving what it asks will ${what}, through Kranto with your connection, which ${title} never sees.`,
    s ? `At most ${s.per_day} a day. Each one still waits for your approval.` : "Each one still waits for your approval.",
    "Back to practice any time here, or with kranto cub dry.",
  ], "Send for real", () => cubPost(id, btn, "live", { kind, confirm: true }, `${title}: for real now. Your next approval does it.`));
}
/** the cub on or off (cubs.<id>.enabled): a click, with Undo */
export function cubSwitch(id: string, title: string, on: boolean, btn: HTMLElement): void {
  const L = app();
  if (!L) return;
  void L.act(btn, () => L.api(cubPath(id, on ? "enable" : "disable"), {}), () => {
    cubFresh();
    L.toast(`${title} is ${on ? "on" : "off"}.`, () => void L.act(null, () => L.api(cubPath(id, on ? "disable" : "enable"), {}), () => {
      cubFresh();
      L.toast("Undone: the previous value is back.");
    }));
  });
}
/** Stop: its process ends, what it asks you closes; Resume runs it again */
export function cubStop(id: string, title: string, btn: HTMLElement): void {
  confirmThen(`Stop ${title}?`, ["Its process ends now; it runs nothing until you resume it.", "What it asks you is closed. Its page, record and data stay."],
    "Stop", () => cubPost(id, btn, "stop", {}, `${title} is stopped.`), "danger");
}
/** one of a feature's actions (POST /api/f/<id>/act/<verb>), behind its confirm class */
export function cubAct(x: FeatureRow, ac: ActionDecl, fields: Record<string, unknown>, btn: HTMLElement | null): void {
  const L = app();
  if (!L) return;
  const go = () => L.act(btn, () => L.api(actPath(ac.kind), { fields, confirm: ac.click !== "click" || undefined }), () => {
    L.afkStale(`/api/f/${x.id}/`);
    L.afkStale(FEATURES_API);
    L.say(`${ac.title}: done.`);
  });
  if (ac.click !== "click") confirmThen(`${ac.title}?`, ac.says || `${x.title} runs ${ac.title.toLowerCase()}.`, ac.title, go);
  else void go();
}
/** an object's action: its subject in the field the subject names (newsletter_issue: issue_id) */
export function cubObjectAct(x: FeatureRow, ac: ActionDecl, o: Record<string, unknown>, extra: Record<string, unknown>, btn: HTMLElement | null): void {
  const k = subjectField(x, ac);
  cubAct(x, ac, { ...(k ? { [k]: o.id } : {}), ...extra }, btn);
}
/** what a cub asks, in its one dialog (AskDialog): an open one at once; a draft offered again is
 * asked for again first, by this click (the server files it with the same fields: no cub run) */
/** ``retime``: a scheduled post's hour, when its Change the time opens the dialog (titled "Change
 * the time", When filled with that hour) */
export function openAsk(ref: AskRef, btn: HTMLElement | null = null, retime: string | null = null): void {
  const L = app();
  if (!L) return;
  if (ref.ticket) {
    openDialog(AskDialog, { id: ref.ticket, retime });
    return;
  }
  if (!ref.again) return;
  void L.act(btn, () => L.api(askPath(ref.again!, "again"), {}), (r) => {
    L.afkDrop();
    openDialog(AskDialog, { id: (r as { id: number }).id });
  });
}
export { CUBS_API };
