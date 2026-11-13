// Open in Claude Code's terminal socket (src/kranto/page/term/asgi.py): binary frames out are the
// terminal's bytes; text frames in are {"t":"in","d"} and {"t":"resize","cols","rows"};
// text frames out are {"t":"exit","code"} and {"t":"dropped"} (this viewer fell behind: open
// again for a fresh ticket and the screen from the ring).

import { PAGE, pageUrl } from "../lib/base";

export type SocketEvent =
  | { kind: "data"; bytes: Uint8Array }
  | { kind: "exit"; code: number | null }
  | { kind: "dropped" }
  | { kind: "closed"; reason: string };

/** The socket's URL for a session and its one-time ticket, under the page's own prefix
 * (``/brb/term/ws/…`` while the document is drawn at ``/``). */
export function socketUrl(tid: string, ticket: string, here: Location = location, base: string = PAGE): string {
  const u = new URL(pageUrl(`term/ws/${encodeURIComponent(tid)}`, base), here.href.replace(/#.*$/, ""));
  u.protocol = here.protocol === "https:" ? "wss:" : "ws:";
  u.search = `ticket=${encodeURIComponent(ticket)}`;
  return u.toString();
}

export class TermSocket {
  private ws: WebSocket | null = null;
  private ended = false;

  constructor(
    private url: string,
    private on: (e: SocketEvent) => void,
    private make: (url: string) => WebSocket = (u) => new WebSocket(u),
  ) {}

  open(): void {
    const ws = this.make(this.url);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (m) => {
      if (typeof m.data === "string") {
        let f: { t?: string; code?: number | null };
        try {
          f = JSON.parse(m.data);
        } catch {
          return;
        }
        if (f.t === "exit") {
          this.ended = true;
          this.on({ kind: "exit", code: f.code ?? null });
        } else if (f.t === "dropped") {
          this.ended = true;
          this.on({ kind: "dropped" });
        }
        return;
      }
      this.on({ kind: "data", bytes: new Uint8Array(m.data as ArrayBuffer) });
    };
    ws.onclose = (c) => {
      if (!this.ended) this.on({ kind: "closed", reason: c.reason || `closed (${c.code})` });
      this.ended = true;
    };
    this.ws = ws;
  }

  get open_(): boolean {
    return !!this.ws && this.ws.readyState === 1;
  }

  input(d: string): void {
    if (this.open_) this.ws!.send(JSON.stringify({ t: "in", d }));
  }

  resize(cols: number, rows: number): void {
    if (this.open_) this.ws!.send(JSON.stringify({ t: "resize", cols, rows }));
  }

  close(): void {
    this.ended = true;
    this.ws?.close();
    this.ws = null;
  }
}
