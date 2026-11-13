// What a cub asks you, as the server's core says it (SEND; the owner, 2026-10-29: "Not sure what
// 'ticket #1 is expired' means, I just wanted to post the newsletter"). A row is one line: the
// draft's title, where it stands ("ready", "needs a newsletter account", "practice: nothing is
// sent") and the action's own button ("Send", "Post toot"). Its button opens one plain dialog
// (AskDialog). A row whose ask ran out of time or was practiced offers the same draft again: the
// click asks the server for a fresh one (POST /api/tickets/<id>/again; no cub run, no model call),
// then opens its dialog. Nothing here is the cub's prose: the server builds every word from the
// ask's typed fields and its own rows (core/asks.py).

export const ASKS_API = "/api/asks";
export const askPath = (id: number, what = ""): string => `/api/tickets/${id}${what ? "/" + what : ""}`;

/** a row's ask: the open one to approve, or the one whose draft is offered again */
export interface AskRef { cub: string; ticket: number | null; again: number | null }

/** a row of GET /api/asks (and a cub's Needs you rows, which the server builds the same way) */
export interface AskRow {
  id: string;
  cub: string;
  title: string;
  meta: string;
  at: string;
  ticket: number | null;
  again: number | null;
  verb: string;
  ask: { line: string; said: string | null; open: boolean };
}

/** the account the dialog connects in place: the newsletter's choice of platform, or one provider */
export interface AskNeeds { connect: string; line: string; words: string; button: string }

/** GET /api/tickets/<id>/ask */
export interface AskView {
  id: number;
  cub: string;
  kind: string;
  state: string;
  said: string | null;
  readback: [string, string][];
  because: Record<string, unknown>;
  history: { state: string; door: string | null; note: string | null; created_at: string }[];
  created_at: string;
  expires_at: string;
  run_uuid: string | null;
  ask: {
    verb: string;
    button: string;
    noun: string;
    title: string;
    to: string | null;
    body: string;
    needs: AskNeeds | null;
    schedule: boolean;
    when: string | null;
    open: boolean;
    said: string | null;
    again: boolean;
    practice: { on: boolean; words: string; switch: { cub: string; kind: string; words: string } | null } | null;
    /** a kind with no plain words of its own (another cub's): its read-back, shown in full */
    facts: [string, string][];
    question: string;
  };
}

/** the line a confirm's answer leaves in the dialog, in the owner's words: practice never looks
 * like a send */
export function outcomeLine(state: string, note: string | null | undefined): { text: string; tone: "green" | "grey" | "amber" | "red" } {
  const n = String(note || "");
  if (state === "dry") return { text: "Nothing was sent (practice).", tone: "grey" };
  if (state === "done") return n.startsWith("scheduled") ? { text: "Scheduled. " + cap(n.replace(/^scheduled:\s*/, "")), tone: "green" } : { text: "Sent.", tone: "green" };
  if (state === "refused") return { text: "Not sent: " + n.replace(/^refused:\s*/, "") + ".", tone: "amber" };
  if (state === "unknown") return { text: "Not sure it went out: " + n.replace(/^unknown:\s*/, "") + ".", tone: "red" };
  return { text: cap(state) + ".", tone: "grey" };
}

const cap = (s: string): string => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

/** a time the owner picks for Schedule (a datetime-local's value, read as UTC) as the server's */
export const whenOf = (local: string): string | null => (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local) ? local + "Z" : null);
