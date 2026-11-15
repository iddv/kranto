/** The attribute the browser smoke reads to know the built bundle ran on the page. */
export const MARK = "data-ui";

export function markLoaded(root: HTMLElement): void {
  root.setAttribute(MARK, "svelte");
}
