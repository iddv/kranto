<script lang="ts">
  // The story's timeline: the article's own dated events, drawn by the page, never a
  // model's picture. Evenly spaced (a span may run from 2023 to today), each date written, today's
  // dot violet. Across the page on a wide screen; down the page on the phone (the list below it).
  import type { TimePoint } from "../news";

  let { points, today = "", label = "The story so far" }: { points: TimePoint[]; today?: string; label?: string } = $props();
  const W = 640;
  const H = 128;
  const pad = 40;
  const xs = $derived(points.map((_, i) => (points.length === 1 ? W / 2 : pad + (i * (W - 2 * pad)) / (points.length - 1))));
  const short = (s: string, n: number): string => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const day = (d: string): string => {
    const t = new Date(d.length <= 10 ? d + "T12:00:00" : d);
    return isNaN(t.getTime()) ? d : t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
  };
  // an event's label at most one gap wide (they alternate above and below), about 7 px a letter
  const per = $derived(points.length < 2 ? 40 : Math.max(10, Math.min(48, Math.floor((W - 2 * pad) / (points.length - 1) / 7.5))));
</script>

<div class="tl" role="img" aria-label={`${label}: ${points.map((p) => `${p.date} ${p.event || ""}`).join("; ")}`}>
  <svg class="tl-wide" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
    <line x1={pad} x2={W - pad} y1="64" y2="64" class="rail" />
    {#each points as p, i (p.date + i)}
      <circle cx={xs[i]} cy="64" r="6" class={p.date === today ? "dot now" : "dot"} />
      <text x={xs[i]} y="92" class="d" text-anchor="middle">{day(p.date)}</text>
      {#if p.event}<text x={xs[i]! + (points.length > 1 && i === 0 ? -6 : points.length > 1 && i === points.length - 1 ? 6 : 0)} y={i % 2 ? 112 : 40} class="e" text-anchor={points.length > 1 && i === 0 ? "start" : points.length > 1 && i === points.length - 1 ? "end" : "middle"}><title>{p.event}</title>{short(p.event, per)}</text>{/if}
    {/each}
  </svg>
  <ol class="tl-narrow" aria-hidden="true">
    {#each points as p, i (p.date + i)}<li class={p.date === today ? "now" : ""}><span class="d">{day(p.date)}</span>{#if p.event}<span class="e">{p.event}</span>{/if}</li>{/each}
  </ol>
</div>

<style>
  .tl { margin: 12px 0; }
  svg { width: 100%; height: auto; display: block; }
  .rail { stroke: var(--line2); stroke-width: 2; }
  .dot { fill: var(--blue); stroke: var(--box); stroke-width: 2; }
  .dot.now { fill: var(--violet); }
  .d { fill: var(--muted); font: 12px var(--mono); }
  .e { fill: var(--ink); font: 13px var(--sans); }
  .tl-narrow { display: none; list-style: none; margin: 0; padding: 0 0 0 20px; border-left: 2px solid var(--line2); }
  .tl-narrow li { position: relative; padding: 0 0 12px 8px; display: flex; flex-direction: column; }
  .tl-narrow li::before { content: ""; position: absolute; left: calc(-1 * 20px - 7px); top: 4px; width: 12px; height: 12px; border-radius: 50%; background: var(--blue); }
  .tl-narrow li.now::before { background: var(--violet); }
  .tl-narrow .d { color: var(--muted); font: 12px var(--mono); }
  .tl-narrow .e { color: var(--ink); }
  @media (max-width: 640px) {
    .tl-wide { display: none; }
    .tl-narrow { display: block; }
  }
</style>
