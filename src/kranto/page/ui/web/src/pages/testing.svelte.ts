// For a page's tests: draw a component as the seam does, with the app stubbed and
// its reads answered from a table.
import { flushSync, mount, unmount, type Component } from "svelte";
import { vi } from "vitest";
import type { View, Where } from "../lib/pages.svelte";
import { drop, setFetcher } from "../lib/reads.svelte";
import { connect } from "../lib/shell.svelte";

export function where(path: string, sel: string | null = null): Where {
  const p = path.split("/");
  return { r: { path: p, q: {}, sel }, node: path, list: p, object: sel ? "need" : null, obj: sel ? ["need", sel] : null,
           id: sel, sel: !!sel, stage: false, missing: false };
}
export interface Stub {
  act: ReturnType<typeof vi.fn>;
  api: ReturnType<typeof vi.fn>;
  say: ReturnType<typeof vi.fn>;
  render: ReturnType<typeof vi.fn>;
  togglePause: ReturnType<typeof vi.fn>;
  host: () => Record<string, unknown> | null;
  spy: () => void;
  /** the one popover: a div at the end of the body with what it was given */
  popover: ReturnType<typeof vi.fn>;
  closePop: ReturnType<typeof vi.fn>;
  toast: ReturnType<typeof vi.fn>;
  afkStale: ReturnType<typeof vi.fn>;
  afkDrop: ReturnType<typeof vi.fn>;
  loadHost: ReturnType<typeof vi.fn>;
  flash: ReturnType<typeof vi.fn>;
}
/** the app, stubbed: act() runs its function and then done(); api() answers `answer` */
export function stub(o: { host?: Record<string, unknown> | null; answer?: unknown } = {}): Stub {
  const L: Stub = {
    // the press runs whether or not there is a done (done?.(await fn()) skips fn without one)
    act: vi.fn(async (_btn: unknown, fn: () => Promise<unknown>, done?: (r: unknown) => void) => { const r = await fn(); done?.(r); }),
    api: vi.fn(async () => o.answer ?? {}),
    say: vi.fn(), render: vi.fn(), togglePause: vi.fn(),
    host: () => o.host ?? null, spy: () => {},
    popover: vi.fn((_anchor: unknown, label: string, kids: Node[] = []) => {
      for (const x of document.querySelectorAll(".pop")) x.remove(); // one at a time
      const d = document.createElement("div");
      d.className = "pop";
      d.setAttribute("aria-label", label);
      d.append(...kids);
      document.body.append(d);
      return d;
    }),
    closePop: vi.fn(), toast: vi.fn(), afkStale: vi.fn(), afkDrop: vi.fn(), loadHost: vi.fn(async () => {}), flash: vi.fn(),
  };
  connect(L as never);
  return L;
}
/** reads answered from `answers` by path (a missing path is an error) */
export function answering(answers: Record<string, unknown>): void {
  for (const k of Object.keys(answers)) drop(k);
  setFetcher(async (path) => {
    if (!(path in answers)) throw new Error("not found: " + path);
    return structuredClone(answers[path]);
  });
}
export async function draw(C: Component<{ view: View }>, w: Where, back: string | null = null, props: Record<string, unknown> = {}) {
  const target = document.createElement("div");
  document.body.append(target);
  const view = $state<View>({ w, back, tick: 0 });
  const app = mount(C, { target, props: { view, ...props } });
  for (let i = 0; i < 3; i++) {
    await new Promise((r) => setTimeout(r, 0)); // the reads arrive, then what they set
    flushSync();
  }
  return {
    target,
    done: () => {
      void unmount(app);
      target.remove();
      connect(null);
    },
  };
}
export const settle = async (): Promise<void> => {
  for (let i = 0; i < 3; i++) {
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
  }
};
/** scripts/preview/acceptance.py's COUNT rule in jsdom: the words (a run of non-space with a
 * letter or digit), the controls (links with an address, buttons, fields, summaries) and the
 * primaries (.btn.primary); printed on the test's output as "COUNT <what>: {...}" so a budget's
 * exact numbers are on record, not only its bound */
export function count(el: Element, what: string): { words: number; controls: number; primaries: number } {
  const c = {
    words: (el.textContent || "").split(/\s+/).filter((w) => /\w/.test(w)).length,
    controls: el.querySelectorAll("a[href], button, input, select, textarea, summary").length,
    primaries: el.querySelectorAll(".btn.primary").length,
  };
  (globalThis as unknown as { process: { stdout: { write: (s: string) => void } } }).process.stdout.write(`COUNT ${what}: ${JSON.stringify(c)}\n`);
  return c;
}
/** what the owner reads in an element: its text without the places a key belongs (a code span,
 * an Advanced fold, a field), as the browser smoke's OWNER_TEXT reads a page */
export function ownerText(el: Element): string {
  const c = el.cloneNode(true) as Element;
  c.querySelectorAll("code, kbd, pre, input, textarea, select, details.advanced, script, style").forEach((e) => e.remove());
  return c.textContent || "";
}
/** a setting key, as it would read in a sentence */
export const SETTING_KEY = /\b(?:connections|news|update|cubs|newsletter|shell|term|watch)\.[a-z_]+(?:\.[a-z_]+)*\b/;
