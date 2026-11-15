<script lang="ts">
  // The article's figure in small, beside its item on Today: the timeline's dots
  // and its first and last dates, 150 by 64; the words beside it say what it is.
  import type { TimePoint } from "../news";

  let { points }: { points: TimePoint[] } = $props();
  const W = 150;
  const x = (i: number): number => (points.length < 2 ? W / 2 : 10 + (i * (W - 20)) / (points.length - 1));
  const md = (d: string): string => {
    const t = new Date(d.length <= 10 ? d + "T12:00:00" : d);
    return isNaN(t.getTime()) ? d.slice(5) : t.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  };
</script>

{#if points.length}
  <svg class="thumb" width="150" height="64" viewBox="0 0 150 64" aria-hidden="true">
    <line x1="10" x2={W - 10} y1="28" y2="28" class="rail" />
    {#each points as p, i (p.date + i)}<circle cx={x(i)} cy="28" r="4" class={i === points.length - 1 ? "dot last" : "dot"} />{/each}
    <text x="10" y="52" class="d">{md(points[0]!.date)}</text>
    {#if points.length > 1}<text x={W - 10} y="52" text-anchor="end" class="d">{md(points[points.length - 1]!.date)}</text>{/if}
  </svg>
{/if}

<style>
  .thumb { flex: none; border: 1px solid var(--border); border-radius: 6px; background: var(--box); }
  .rail { stroke: var(--line2); stroke-width: 2; }
  .dot { fill: var(--blue); }
  .dot.last { fill: var(--violet); }
  .d { fill: var(--muted); font: 10px var(--mono); }
</style>
