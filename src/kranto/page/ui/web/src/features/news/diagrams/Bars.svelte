<script lang="ts">
  // The article's figures that share a unit, as bars: drawn when two or more do;
  // each bar's value and label written beside it, so no meaning rests on its length alone.
  import type { ArticleBody } from "../news";

  let { numbers }: { numbers: ArticleBody["numbers"] } = $props();
  const num = (v: string): number => Number(String(v).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/)?.[0] ?? NaN);
  /** the unit two or more figures share, the most common first */
  const unit = $derived.by(() => {
    const by = new Map<string, number>();
    for (const x of numbers) if (!isNaN(num(x.value))) by.set(x.unit, (by.get(x.unit) || 0) + 1);
    return [...by.entries()].filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  });
  const rows = $derived(unit == null ? [] : numbers.filter((x) => x.unit === unit && !isNaN(num(x.value))));
  const top = $derived(Math.max(...rows.map((x) => Math.abs(num(x.value))), 1));
  const W = 640;
  const ROW = 28;
</script>

{#if rows.length >= 2}
  <figure class="bars">
    <svg viewBox={`0 0 ${W} ${rows.length * ROW + 8}`} role="img" aria-label={rows.map((x) => `${x.label}: ${x.value} ${x.unit}`).join("; ")}>
      {#each rows as x, i (x.label + i)}
        <text x="0" y={i * ROW + 18} class="l">{x.label.length > 34 ? x.label.slice(0, 33) + "…" : x.label}</text>
        <rect x="250" y={i * ROW + 6} height="16" width={Math.max(2, (Math.abs(num(x.value)) / top) * 300)} rx="3" class="b" />
        <text x={258 + (Math.abs(num(x.value)) / top) * 300} y={i * ROW + 18} class="v">{`${x.value}${x.unit && x.unit !== "%" ? " " : ""}${x.unit}`}</text>
      {/each}
    </svg>
    <figcaption class="muted small">{`The figures in ${unit || "the same unit"}, from the cited lines; drawn by the page.`}</figcaption>
  </figure>
{/if}

<style>
  svg { width: 100%; height: auto; display: block; }
  .l { fill: var(--ink2); font: 13px var(--sans); }
  .v { fill: var(--ink); font: 12px var(--mono); }
  .b { fill: var(--blue); }
  figure { margin: 12px 0; }
</style>
