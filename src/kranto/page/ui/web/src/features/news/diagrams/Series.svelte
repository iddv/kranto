<script lang="ts">
  // A monthly series the article copied from the server's own counts, checked
  // against them before it is stored: a line, each month's count written at its point.
  import type { ArticleBody } from "../news";

  let { series }: { series: NonNullable<ArticleBody["series"]> } = $props();
  const W = 640;
  const H = 160;
  const pad = 32;
  const pts = $derived(series.points);
  const top = $derived(Math.max(...pts.map((p) => p.y), 1));
  const x = (i: number): number => (pts.length === 1 ? W / 2 : pad + (i * (W - 2 * pad)) / (pts.length - 1));
  const y = (v: number): number => H - 28 - (v / top) * (H - 56);
  const path = $derived(pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" "));
</script>

<figure class="series">
  <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${series.name}: ${pts.map((p) => `${p.x} ${p.y}`).join(", ")}`}>
    <path d={path} class="ln" />
    {#each pts as p, i (p.x)}
      <circle cx={x(i)} cy={y(p.y)} r="3.5" class="pt" />
      <text x={x(i)} y={y(p.y) - 8} text-anchor="middle" class="v">{String(p.y)}</text>
      <text x={x(i)} y={H - 8} text-anchor="middle" class="m">{p.x.slice(2)}</text>
    {/each}
  </svg>
  <figcaption class="muted small">{`${series.name}${series.unit ? " (" + series.unit + ")" : ""}: monthly counts Kranto keeps; drawn by the page.`}</figcaption>
</figure>

<style>
  svg { width: 100%; height: auto; display: block; }
  .ln { fill: none; stroke: var(--blue); stroke-width: 2; }
  .pt { fill: var(--blue); }
  .v { fill: var(--ink); font: 11px var(--mono); }
  .m { fill: var(--muted); font: 11px var(--mono); }
  figure { margin: 12px 0; }
</style>
