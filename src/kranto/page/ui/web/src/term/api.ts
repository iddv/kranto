// Open in Claude Code's routes (src/kranto/page/ui/routes/term.py). Relative to the page (/brb/).
import { ApiError } from "../api/client";

export interface Subject {
  /** sources: a described batch (its number), its lines Kranto could not add */
  kind: "idea" | "card" | "topic" | "brief" | "page" | "sources";
  id: string;
}

export interface Proposal {
  n: number;
  kind: string;
  title: string;
  confirm_class: boolean;
  subject: { kind: string; id: string | null };
  fields: Record<string, unknown>;
  why: string;
  status: "proposed" | "running" | "done" | "dismissed" | "failed";
  result: { say?: string; url?: string; error?: string } | null;
}

export interface Session {
  tid: string;
  subject: Subject;
  title: string;
  state: "running" | "ended" | "removed";
  reason: string | null;
  words: string;
  created?: number | null;
  updated?: number | null;
  usd: number;
  tokens: { in: number; out: number } | null;
  sandboxed: boolean | null;
  cwd: string;
  branch: string | null;
  session: string;
  net: { allowed: string[]; asked: string[] };
  proposals: Proposal[];
  /** a sources session's lists sent back (the server's batch numbers) */
  batches?: number[];
  /** what it runs on: "on your Claude API key, Sonnet 5" */
  on?: string | null;
  /** the Claude API's refusal of its last request (credit, login, usage), until a reply succeeds */
  refused?: string | null;
  ticket?: string;
}

export interface Listing {
  sessions: Session[];
  enabled: boolean;
  available: boolean;
  why: string | null;
  /** "api_key": the only token is the watcher's Claude API key, unused until the owner chooses it */
  ask?: "api_key" | null;
  /** what a session runs on, and a Find these session (its model pinned on an API key) */
  on?: string | null;
  sources_on?: string | null;
  sandboxed: boolean;
  max_sessions: number;
  running: number;
  socket: boolean;
}

export interface Outside {
  tid: string;
  cwd: string;
  session: string;
  branch: string | null;
  plain: string;
  kranto: string;
}

async function answer<T>(r: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  if (!r.ok) {
    const b = body as { error?: unknown; sessions?: Session[] } | null;
    const e = new ApiError(r.status, typeof b?.error === "string" ? b.error : `HTTP ${r.status}`);
    (e as ApiError & { sessions?: Session[] }).sessions = b?.sessions;
    throw e;
  }
  return body as T;
}

export async function list(): Promise<Listing> {
  return answer(await fetch("api/term", { cache: "no-store" }));
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return answer(
    await fetch(`api/term/${path}`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export const open = (subject: Subject, cols: number, rows: number) =>
  post<Session>("open", { subject, cols, rows });
export const end = (tid: string) => post<Session>("end", { tid });
export const net = (tid: string, host: string, allow: boolean) =>
  post<Session>("net", { tid, host, allow });
export const reply = (tid: string, n: number, confirm: boolean) =>
  post<{ proposal: Proposal }>("answer", { tid, n, confirm });
export const outside = (tid: string) => post<Outside>("outside", { tid });
/** Use the API key: term.allow_api_key on, through the console's settings writer (api/term/settings) */
export async function useApiKey(): Promise<void> {
  await post<unknown>("settings", { key: "term.allow_api_key", value: true });
}

/** The session about this subject in a listing, if any. */
export function about(l: Listing | null, s: Subject | null): Session | null {
  if (!l || !s) return null;
  return l.sessions.find((x) => x.subject?.kind === s.kind && x.subject?.id === s.id) ?? null;
}
