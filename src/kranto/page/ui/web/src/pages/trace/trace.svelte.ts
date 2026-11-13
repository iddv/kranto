// One trace in the page: its summary, its spans in tree order (a span's
// pos is its place), the folds, the selection, the filter, and the cursor the server gave.
//
// The spans arrive a page at a time (api/trace/spans, 500 a page, the first page first so the
// tree draws at once) and are kept in a plain Map with a version number, so 50,000 spans are no
// 50,000 reactive objects: what the page draws derives from `ver`. `more()` reads on from the
// cursor; the cursor also returns the shown spans that changed (the live reads use it), and
// a 422 means the trace was read again from its files: read from the top.
import type { SpanPage, SpanSummary, TraceDetail } from "../../api/types.gen";

export type Get = (path: string) => Promise<unknown>;
export type Form = "tree" | "timeline" | "log";

const PAGE = 500;
const q = (path: string, query: Record<string, string | number | null | undefined>): string =>
  path + "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)])).toString();

export class TraceStore {
  id: string;
  get: Get;
  detail = $state<TraceDetail | null>(null);
  error = $state<string | null>(null);
  /** bumped on every change of the spans: the derived views read it */
  ver = $state(0);
  done = $state(false);
  selected = $state<string | null>(null);
  form = $state<Form>("tree");
  /** the filter's spans (with their ancestors) and the ones that matched; null: no filter */
  // words: the search over what the trace holds, which "Search every payload…" can take further
  filtered = $state<{ keep: Set<string>; hits: string[]; label: string; words?: string | null } | null>(null);
  filterBusy = $state(false);
  spans = new Map<string, SpanSummary>();
  order: SpanSummary[] = [];
  /** folded spans; by default every turn and sub-agent is folded (a session reads as its turns) */
  open = new Set<string>();
  shut = new Set<string>();
  cursor: string | null = null;
  total = $state(0);
  running = $state(false);

  constructor(id: string, get: Get) {
    this.id = id;
    this.get = get;
  }

  /** the summary, then the first page, then the rest in pages of PAGE */
  async load(): Promise<void> {
    try {
      this.detail = (await this.get(q("api/trace", { trace: this.id }))) as TraceDetail;
      this.running = !!this.detail.running;
      this.error = null;
    } catch (e) {
      this.error = (e as Error).message;
      return;
    }
    await this.more();
    while (!this.done) await this.more();
  }

  /** the next page from the cursor (and the shown spans that changed since it) */
  async more(): Promise<number> {
    let p: SpanPage;
    try {
      p = (await this.get(q("api/trace/spans", { trace: this.id, after: this.cursor, limit: PAGE }))) as SpanPage;
    } catch (e) {
      const m = (e as Error).message || "";
      if (/from the top|cursor/.test(m) && this.cursor) {
        this.reset();
        return this.more();
      }
      this.error = m;
      this.done = true;
      return 0;
    }
    this.merge(p.spans);
    this.cursor = p.cursor;
    this.total = p.total;
    this.running = !!p.running;
    this.done = !p.more;
    return p.spans.length;
  }

  /** a running trace grew (the live feed said so,): the head again, then every span made
   * or changed since the cursor. One at a time: a burst of changes is one read. */
  refreshing = false;
  async refresh(): Promise<boolean> {
    if (this.refreshing || !this.done) return false;
    this.refreshing = true;
    try {
      const before = this.ver;
      try {
        this.detail = (await this.get(q("api/trace", { trace: this.id }))) as TraceDetail;
      } catch {
        /* the head stays as it was; the spans may still come */
      }
      this.done = false;
      while (!this.done) await this.more();
      this.running = !!this.detail?.running && this.running;
      return this.ver !== before;
    } finally {
      this.refreshing = false;
    }
  }

  /** the span running now (the last one in tree order that is), for the head's live line */
  current(): SpanSummary | null {
    for (let i = this.order.length - 1; i >= 0; i--) {
      const s = this.order[i]!;
      if (s.status === "running" && s.kind !== "run" && s.kind !== "stage" && s.kind !== "session") return s;
    }
    return null;
  }

  reset(): void {
    this.spans.clear();
    this.order = [];
    this.cursor = null;
    this.done = false;
    this.ver++;
  }

  merge(rows: SpanSummary[]): void {
    if (!rows.length) return;
    let resort = false;
    for (const s of rows) {
      const was = this.spans.get(s.id);
      this.spans.set(s.id, s);
      if (!was || was.pos !== s.pos) resort = true;
      else this.order[s.pos] = s;
    }
    if (resort) this.order = [...this.spans.values()].sort((a, b) => a.pos - b.pos);
    this.ver++;
  }

  // -- the tree's folds ---------------------------------------------------------------------
  folded(s: SpanSummary): boolean {
    if (!s.children) return false;
    if (this.open.has(s.id)) return false;
    if (this.shut.has(s.id)) return true;
    return s.kind === "turn" || s.kind === "subagent" || s.kind === "tool";
  }
  toggle(id: string, to?: boolean): void {
    const s = this.spans.get(id);
    if (!s) return;
    const fold = to ?? !this.folded(s);
    if (fold) {
      this.open.delete(id);
      this.shut.add(id);
    } else {
      this.shut.delete(id);
      this.open.add(id);
    }
    this.ver++;
  }
  /** every ancestor of a span unfolded, so it shows */
  reveal(id: string): void {
    let s = this.spans.get(id), hops = 0;
    while (s && s.parent && hops++ < 64) {
      const p = this.spans.get(s.parent);
      if (!p) break;
      this.shut.delete(p.id);
      this.open.add(p.id);
      s = p;
    }
    this.ver++;
  }

  /** the rows the tree shows: the spans in order, a folded span's descendants left out, or the
   * filter's spans */
  rows(): SpanSummary[] {
    void this.ver;
    if (this.filtered) return this.order.filter((s) => this.filtered!.keep.has(s.id));
    if (this.form === "log") return this.order;
    const out: SpanSummary[] = [];
    let below = Infinity;
    for (const s of this.order) {
      if (s.depth > below) continue;
      below = Infinity;
      out.push(s);
      if (this.folded(s)) below = s.depth;
    }
    return out;
  }

  // -- the filters (served by the index's columns) --------------------------------------------
  // payloads: the second step, every payload the trace's files hold (api/trace/search's scan)
  async filter(spec: string | null, words: string | null, payloads = false): Promise<void> {
    if (!spec && !words) {
      this.filtered = null;
      this.ver++;
      return;
    }
    this.filterBusy = true;
    try {
      const p = (await this.get(q("api/trace/spans", { trace: this.id, filter: spec, q: words, payloads: payloads && words ? 1 : null }))) as SpanPage;
      this.merge(p.spans);
      const label = [spec, words ? `"${words}"` : null, payloads && words ? "in every payload" : null].filter(Boolean).join(" · ");
      this.filtered = { keep: new Set(p.spans.map((s) => s.id)), hits: p.matches || [], label, words: words && !payloads ? words : null };
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.filterBusy = false;
      this.ver++;
    }
  }

  // -- moving -------------------------------------------------------------------------------
  /** the next (or previous) span after the selection that `test` likes, among the rows shown or,
   * for an error or a tool, in the whole trace (unfolding to it) */
  next(test: (s: SpanSummary) => boolean, back = false, all = false): string | null {
    const list = all ? this.order : this.rows();
    if (!list.length) return null;
    const at = this.selected ? list.findIndex((s) => s.id === this.selected) : -1;
    for (let k = 1; k <= list.length; k++) {
      const i = back ? (at - k + list.length * 2) % list.length : (at + k) % list.length;
      const s = list[i]!;
      if (test(s)) {
        if (all) this.reveal(s.id);
        return s.id;
      }
    }
    return null;
  }

  /** the failing span: the trace's failure point, else its first error */
  failing(): string | null {
    const f = this.detail?.failed_at;
    if (f) return f;
    return this.order.find((s) => s.status === "error" && s.kind !== "run" && s.kind !== "stage")?.id || null;
  }
}
