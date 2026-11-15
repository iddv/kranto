// The typed client: every read of the page's own server is typed from the Python side
// (types.gen.ts). A renamed field fails `npm run check`.
import type { Routes } from "./types.gen";
import { contain } from "../lib/unreadable.svelte";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function answer<T>(r: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  if (!r.ok) {
    const error = (body as { error?: unknown } | null)?.error;
    throw new ApiError(r.status, typeof error === "string" ? error : `HTTP ${r.status}`);
  }
  return body as T;
}

/** GET one of the paths in `Routes`, with an optional query. */
export async function get<P extends keyof Routes>(
  path: P,
  query?: Record<string, string>,
): Promise<Routes[P]> {
  const q = query ? `?${new URLSearchParams(query)}` : "";
  return contain(`${path}${q}`, await answer<Routes[P]>(await fetch(`${path}${q}`, { cache: "no-store" })));
}
