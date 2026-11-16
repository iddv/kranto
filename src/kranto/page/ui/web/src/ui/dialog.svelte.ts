// The one dialog (#dlg,): every confirm, form and sheet a page opens is a component drawn
// in it, one at a time (DialogHost.svelte). openDialog shows it modal with the cursor on its
// autofocus (Cancel, or the field it names); esc, Cancel and the main button's own close() end
// it, and what it drew goes with it. nodeDialog is one whose body is nodes (the app's dialog()).
import { flushSync, type Component } from "svelte";
import NodeDialog from "./NodeDialog.svelte";

/** what a dialog's component gets besides its own props */
export interface DialogProps {
  close: () => void;
}
interface Shown {
  comp: Component<DialogProps & Record<string, unknown>>;
  props: Record<string, unknown>;
  wide: boolean;
  n: number;
  /** the address it opened at: going to another page closes it (it stayed open over the next
   * page, "Decline this draft?" over Settings) */
  at: string;
}
export const dlg = $state<{ now: Shown | null }>({ now: null });
let n = 0;
const box = (): HTMLDialogElement | null => document.getElementById("dlg") as HTMLDialogElement | null;

/** comp in the dialog with props (wide: the ? sheet, a charter's text) */
export function openDialog<P extends Record<string, unknown>>(comp: Component<P & DialogProps>, props: P, o: { wide?: boolean } = {}): void {
  dlg.now = { comp: comp as unknown as Shown["comp"], props, wide: !!o.wide, n: ++n, at: location.hash };
  flushSync(); // drawn now: its fields can be read and focused at once
  const d = box();
  if (!d || d.open) return;
  if (typeof d.showModal === "function") d.showModal();
  else d.setAttribute("open", "");
}
export function closeDialog(): void {
  const d = box();
  if (d && typeof d.close === "function" && d.open) d.close();
  else d?.removeAttribute("open");
  dlg.now = null;
}
/** The page changed (a link, Back, a key): a dialog opened on another page closes, so it never
 * stands over a page it was not about; one opened just after its own move stays, and a change of
 * selection on the same page (?sel=) keeps it. The shell's own route change closes it too, from
 * its second page on; this holds from the first. */
const pageOf = (h: string): string => h.split("?")[0]!.replace(/\/$/, "");
export function moved(): void {
  if (dlg.now && pageOf(dlg.now.at) !== pageOf(location.hash)) closeDialog();
}
/** esc closed it (the browser's own close): what it drew goes, unless another dialog opened since */
export function closed(): void {
  if (!box()?.open) dlg.now = null;
}
/** the house's confirm (C3; never the browser's own confirm box): a title that asks, one
 * or two sentences, Cancel first, then the verb; the verb closes the dialog and runs `run` */
export function confirmThen(title: string, body: string | string[], verb: string, run: () => unknown, okClass = "primary"): void {
  const ps = ([] as string[]).concat(body).map((t) => {
    const p = document.createElement("p");
    p.textContent = t;
    return p;
  });
  nodeDialog(title, ps, verb, (_ok, close) => {
    close();
    return run();
  }, okClass);
}

/** a dialog whose body is nodes (the app's dialog()): the title, the body, Cancel and the main
 * button, whose press gets that button and close */
export function nodeDialog(title: string, body: Node | Node[], okText: string, onOk: (ok: HTMLElement, close: () => void) => unknown, okClass?: string, o: { wide?: boolean } = {}): void {
  // a part left out (null, false: `cond ? node : null`) draws nothing
  const nodes = ([body] as unknown[]).flat(Infinity as 1).filter((x) => x != null && x !== false) as Node[];
  openDialog(NodeDialog, { title, body: nodes, okText, onOk, okClass: okClass || "" }, o);
}
