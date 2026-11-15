// Settings › Privacy & access: usage reports. The mode and why, what each mode means,
// today's report as it stands, every report sent (the exact bytes), and the notice with the
// field list. The server's /api/settings/telemetry holds it all; POST {mode} is the one setter the
// wizard, Welcome and this page share. Nothing is sent before the person answers; with basic or
// detailed, one report a day goes to the controller's relay (or the endpoint the person set).
export const PRIVACY_API = "/api/settings/telemetry";
export const PRIVACY_REPORT = "/api/settings/telemetry/report";
export const PRIVACY_PAGE = "/api/settings/telemetry/page";

export type Mode = "off" | "local" | "basic" | "detailed";
export interface Sent {
  day: string;
  at: string;
  status: number;
  bytes: number;
  gzip_bytes: number;
  endpoint: string;
  tier: string;
}
/** one batch of error reports sent (the server telemetry/errors.py) */
export interface ErrorBatch {
  id: string;
  at: string;
  status: number;
  bytes: number;
  gzip_bytes: number;
  endpoint: string;
  tier: string;
  reports: number;
}
export interface Privacy {
  mode: Mode;
  why: "DO_NOT_TRACK" | "KRANTO_TELEMETRY" | "config" | "default";
  meaning: string;
  answered: boolean;
  answered_at: string | null;
  endpoint: string | null;
  sending: boolean;
  why_not: string | null;
  last_sent: Sent | null;
  next: string | null;
  bytes_today: number;
  modes: { mode: Mode; meaning: string }[];
  summary: string;
  sent: Sent[];
  remind: boolean;
  /** error reports (absent from a server older than them) */
  errors?: { waiting: number; sent: number; last_sent: ErrorBatch | null };
  error_batches?: ErrorBatch[];
  /** the public field page */
  docs?: string;
}
export interface Report {
  day: string;
  resource?: Record<string, string | number | boolean>;
  report?: Record<string, string | number | boolean> | null;
  errors?: Record<string, string | number>[] | null;
  bytes?: number;
  sent?: string | null;
}

export const DOCS = "https://github.com/iddv/kranto/blob/main/docs/privacy/what-kranto-sends.md";

/** the choices as the question offers them: none is chosen for the person */
export const CHOICES: [Mode, string][] = [
  ["basic", "Basic: the daily report and error reports, with no identifier"],
  ["detailed", "Detailed: also a random id you can reset, and how Kranto's assistant tools are used (verbs called, sessions' length, slash commands), hour by hour"],
  ["off", "Nothing: count nothing, send nothing"],
];

/** the one line about error reports: they follow the choice */
export function errorsLine(p: Privacy): string {
  if (!p.sending) return "Error reports follow your choice: none is kept or sent.";
  const e = p.errors;
  if (!e) return "Error reports go within minutes of an error.";
  const last = e.last_sent ? ` Last batch ${e.last_sent.at}: ${e.last_sent.reports} ${e.last_sent.reports === 1 ? "report" : "reports"}, HTTP ${e.last_sent.status}.` : " None sent yet.";
  return `${e.waiting} waiting; they go within minutes of an error.` + last;
}
export const MODE_WORDS: Record<Mode, string> = { off: "Off", local: "Local only", basic: "Basic", detailed: "Detailed" };

/** the one line the list and the pane say about sending */
export function sendingLine(p: Privacy): string {
  if (p.why === "DO_NOT_TRACK") return "DO_NOT_TRACK is set in the service's environment: nothing is counted or sent, whatever is chosen here.";
  if (p.why === "KRANTO_TELEMETRY") return `KRANTO_TELEMETRY sets ${p.mode} in the service's environment; this page cannot change it.`;
  if (!p.answered) return "Not answered yet: Kranto counts on this machine only and sends nothing until you choose.";
  if (p.sending) return (p.last_sent ? `Last sent ${p.last_sent.day}, ${p.last_sent.bytes} bytes, HTTP ${p.last_sent.status}.` : `Nothing sent yet; the first report goes ${p.next || "tomorrow"} UTC.`) + (p.endpoint ? ` Reports go to ${p.endpoint}.` : "");
  return `Nothing is sent: ${p.why_not || p.meaning}.`;
}

/** a report's fields as rows, sorted (what the person reads before and after it is sent) */
export function fieldRows(r: Record<string, string | number | boolean> | null | undefined): [string, string][] {
  return Object.entries(r || {}).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, String(v)]);
}
