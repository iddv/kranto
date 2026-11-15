// For the tests: the house dialog a press opened (ui/dialog.svelte.ts), read and answered the way
// a person would: its title and words, then its main button or Cancel.
import { closeDialog, dlg } from "./dialog.svelte";

/** the open dialog's title and its body's words, or null with none open */
export function dialogShown(): { title: string; text: string } | null {
  const d = dlg.now;
  if (!d) return null;
  const body = (d.props.body as Node[] | undefined) || [];
  return { title: String(d.props.title || ""), text: body.map((n) => n.textContent || "").join(" ") };
}

/** press the open dialog's main button (yes) or Cancel (no); what the press returned */
export function answerDialog(yes: boolean): unknown {
  const d = dlg.now;
  if (!d) throw new Error("no dialog is open");
  if (!yes) {
    closeDialog();
    return undefined;
  }
  return (d.props.onOk as (ok: HTMLElement, close: () => void) => unknown)(document.createElement("button"), closeDialog);
}
