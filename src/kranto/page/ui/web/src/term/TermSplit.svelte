<script lang="ts" module>
  // The focus split's width (a splitter, as the shell's): the terminal's share of
  // the window, kept per browser (kranto.termw) and set as one CSS variable (--termw), so a drag
  // never redraws the page. Bounds: 360 px, and 70% of the window.
  export const TERMW_KEY = "kranto.termw";
  export const TERMW_MIN = 360;
  export const termwMax = (): number => Math.round(innerWidth * 0.7);
  export const clampTermw = (px: number): number => Math.round(Math.max(TERMW_MIN, Math.min(termwMax(), px)));

  /** the width now: what was set, else the stylesheet's 40% */
  export function termwNow(): number {
    const v = parseFloat(document.documentElement.style.getPropertyValue("--termw"));
    return Number.isFinite(v) ? v : Math.max(TERMW_MIN, Math.round(innerWidth * 0.4));
  }
  export function setTermw(px: number | null, save: boolean): void {
    const root = document.documentElement.style;
    if (px == null) root.removeProperty("--termw");
    else root.setProperty("--termw", clampTermw(px) + "px");
    if (!save) return;
    try {
      if (px == null) localStorage.removeItem(TERMW_KEY);
      else localStorage.setItem(TERMW_KEY, String(clampTermw(px)));
    } catch {
      /* private mode: kept for this page only */
    }
  }
  /** the kept width, applied at boot */
  export function loadTermw(): void {
    let v: number | null = null;
    try {
      v = parseFloat(localStorage.getItem(TERMW_KEY) || "");
    } catch {
      v = null;
    }
    if (v && Number.isFinite(v)) setTermw(v, false);
  }
</script>

<script lang="ts">
  let held = $state(false);
  let now = $state(0);
  let drag: { off: number } | null = null;

  const at = (e: PointerEvent) => innerWidth - e.clientX;
  function down(e: PointerEvent): void {
    if (e.button) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    held = true;
    document.body.classList.add("resizing");
    drag = { off: at(e) - termwNow() }; // where in the line it was taken: no jump
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    setTermw(at(e) - drag.off, false);
    now = termwNow();
  }
  function end(e: PointerEvent): void {
    if (!drag) return;
    drag = null;
    held = false;
    document.body.classList.remove("resizing");
    setTermw(termwNow(), true);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }
  function key(e: KeyboardEvent): void {
    const step = e.shiftKey ? 64 : 16;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") setTermw(termwNow() + (e.key === "ArrowLeft" ? step : -step), true);
    else if (e.key === "Home") setTermw(TERMW_MIN, true);
    else if (e.key === "End") setTermw(termwMax(), true);
    else return;
    now = termwNow();
    e.preventDefault();
    e.stopPropagation();
  }
</script>

<!-- a focusable separator is WAI-ARIA's window splitter: a widget with a value, moved by keys -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class={"tsplit" + (held ? " drag" : "")} id="split-term" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Resize Claude Code" aria-controls="term" aria-valuemin={TERMW_MIN} aria-valuemax={termwMax()} aria-valuenow={now || termwNow()} title="Drag to resize · double-click to reset · ← → keys" onpointerdown={down} onpointermove={move} onpointerup={end} onpointercancel={end} ondblclick={() => { setTermw(null, true); now = termwNow(); }} onkeydown={key} onfocus={() => (now = termwNow())}></div>
