// A component in the one popover (ui/popover.ts: one at a time, esc, a click
// elsewhere or a route change closes it): mounted into it, unmounted when it closes. cls: its
// kind (menu, filters); a menu gets role="menu".
import { flushSync, mount, unmount, type Component } from "svelte";
import { app } from "../lib/shell.svelte";

export function popWith<P extends Record<string, unknown>>(anchor: HTMLElement, label: string, comp: Component<P>, props: P, cls = ""): HTMLElement | null {
  const L = app();
  if (!L) return null;
  let inst: Record<string, unknown> | null = null;
  const el = L.popover(anchor, label, [], { onclose: () => { if (inst) void unmount(inst); inst = null; } });
  for (const c of cls.split(" ").filter(Boolean)) el.classList.add(c);
  if (cls.split(" ").includes("menu")) el.setAttribute("role", "menu");
  inst = mount(comp, { target: el, props });
  flushSync();
  return el;
}
export const closePop = (refocus?: boolean): void => app()?.closePop(refocus);
