<script lang="ts" generics="T">
  // A windowed list: rows of one height, only those in view (and a few either
  // side) in the DOM, so 50,000 rows scroll as 60. The box scrolls; a spacer gives it the whole
  // height. `scrollTo(i)` brings row i into view (the selection a key moved to); `follow` keeps
  // the last row in view while it is on and the reader has not scrolled up (a running trace).
  import type { Snippet } from "svelte";

  let {
    items,
    height = 30,
    row,
    label,
    follow = false,
    onscrolled,
  }: {
    items: T[];
    height?: number;
    row: Snippet<[T, number]>;
    label: string;
    follow?: boolean;
    onscrolled?: (atEnd: boolean) => void;
  } = $props();

  const OVER = 8;
  let box: HTMLDivElement | undefined = $state();
  let top = $state(0);
  let view = $state(600);

  const first = $derived(Math.max(0, Math.floor(top / height) - OVER));
  const last = $derived(Math.min(items.length, Math.ceil((top + view) / height) + OVER));
  const shown = $derived(items.slice(first, last));

  function scrolled(): void {
    if (!box) return;
    top = box.scrollTop;
    view = box.clientHeight || view;
    onscrolled?.(box.scrollTop + box.clientHeight >= box.scrollHeight - height);
  }

  /** bring row i into view (the least scroll that shows it) */
  export function scrollTo(i: number): void {
    if (!box || i < 0) return;
    const y = i * height;
    if (y < box.scrollTop) box.scrollTop = y;
    else if (y + height > box.scrollTop + box.clientHeight) box.scrollTop = y + height - box.clientHeight;
    scrolled();
  }

  $effect(() => {
    if (!box) return;
    view = box.clientHeight || 600;
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => scrolled()) : null;
    ro?.observe(box);
    return () => ro?.disconnect();
  });
  $effect(() => {
    void items.length;
    if (follow && box) {
      box.scrollTop = box.scrollHeight;
      scrolled();
    }
  });
</script>

<div class="virt" bind:this={box} onscroll={scrolled} role="tree" aria-label={label} tabindex="-1">
  <div class="spacer" style:height={items.length * height + "px"}>
    <div class="win" style:transform={`translateY(${first * height}px)`}>
      {#each shown as it, k (first + k)}
        {@render row(it, first + k)}
      {/each}
    </div>
  </div>
</div>

<style>
  .virt {
    overflow: auto;
    height: 100%;
    min-height: 0;
    contain: strict;
  }
  .spacer {
    position: relative;
  }
  .win {
    position: absolute;
    inset: 0 0 auto 0;
  }
</style>
