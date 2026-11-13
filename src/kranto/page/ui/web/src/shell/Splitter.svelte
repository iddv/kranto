<script lang="ts">
  // A splitter: the navigator and the detail pane are as wide as you drag
  // them: a pointer, the keys (← → 16 px, ⇧ 64, Home the least, End the most, esc back to the
  // pane), a double-click resets. The widths are kept per browser (kranto.layout; theme.js
  // applies them before the first paint and clamps them to the window). A splitter never
  // redraws the page: it sets two CSS variables and localStorage, so a flash keeps its clock and
  // a pane its scroll, selection and open folds. The navigator snaps to icons under 120 px and
  // opens again past 150 (no flicker between).
  import { colNow, frame, iconsNow, LAYOUT, navIcons, splitAria, splitBounds, splitReset, splitTo, ui, type LayoutState } from "../lib/shell.svelte";

  let { col }: { col: "nav" | "detail" } = $props();
  const sign = $derived(col === "nav" ? 1 : -1); // ← makes the navigator narrower, the detail pane wider
  const aria = $derived(ui.aria[col] || { min: 0, max: 0, now: 0 });
  let drag: { l: LayoutState | null; off: number } | null = null;
  let held = $state(false);

  const at = (e: PointerEvent) => (col === "nav" ? e.clientX : innerWidth - e.clientX);
  function down(e: PointerEvent): void {
    if (e.button) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    held = true;
    document.body.classList.add("resizing");
    drag = { l: null, off: at(e) - colNow(col) }; // where in the line it was taken: no jump
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    const px = at(e) - drag.off;
    if (col === "nav" && innerWidth >= 1180 && (iconsNow() ? px < 150 : px < 120)) {
      if (!iconsNow()) {
        drag.l = { ...LAYOUT.read(), icons: true };
        delete drag.l.nav;
        LAYOUT.apply(drag.l);
        splitAria();
        frame();
      }
      return;
    }
    const was = iconsNow();
    drag.l = splitTo(col, px, false);
    if (col === "nav" && was !== iconsNow()) frame();
  }
  function end(e: PointerEvent): void {
    if (!drag) return;
    if (drag.l) LAYOUT.save(drag.l);
    drag = null;
    held = false;
    document.body.classList.remove("resizing");
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }
  function key(e: KeyboardEvent): void {
    const [lo, hi] = splitBounds(col);
    const now = colNow(col);
    const step = e.shiftKey ? 64 : 16;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") splitTo(col, now + (e.key === "ArrowRight" ? step : -step) * sign, true);
    else if (e.key === "Home") splitTo(col, lo, true);
    else if (e.key === "End") splitTo(col, hi, true);
    else if (e.key === "Enter" && col === "nav") navIcons(!iconsNow());
    else if (e.key === "Escape")
      ((col === "nav" ? document.querySelector("#nav [aria-current=page]") || document.getElementById("nav") : document.getElementById("dscroll")) as HTMLElement | null)?.focus();
    else return;
    e.preventDefault();
    e.stopPropagation();
  }
</script>

<!-- a focusable separator is WAI-ARIA's window splitter: a widget with a value, moved by keys -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class={"split" + (held ? " drag" : "")} id={"split-" + col} data-col={col} role="separator" tabindex="0" aria-orientation="vertical" aria-label={col === "nav" ? "Resize the navigator" : "Resize the detail pane"} aria-controls={col} aria-valuemin={aria.min} aria-valuemax={aria.max} aria-valuenow={aria.now} title="Drag to resize · double-click to reset · ← → keys" onpointerdown={down} onpointermove={move} onpointerup={end} onpointercancel={end} ondblclick={() => splitReset(col)} onkeydown={key} onfocus={() => { splitAria(); ui.split = "split-" + col; }} onblur={() => (ui.split = null)}></div>
