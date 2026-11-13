// The folds (<details>) the owner opened, by id: kept open when the page draws them again, or
// draws them on another page (the glance pane and the full page).
import { SvelteSet } from "svelte/reactivity";

export const OPENED = new SvelteSet<string>();
export const keepOpen = (id: string) => (e: Event): void => {
  if ((e.currentTarget as HTMLDetailsElement).open) OPENED.add(id);
  else OPENED.delete(id);
};
