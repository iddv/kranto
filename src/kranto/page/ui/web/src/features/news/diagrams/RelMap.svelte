<script lang="ts">
  // Who is involved, as a map: the article's entities on an ellipse, coloured by
  // kind (and the kind written), each link labelled with its verb; every node and link cites a line.
  import type { ArticleBody } from "../news";

  let { entities, relations }: { entities: ArticleBody["entities"]; relations: ArticleBody["relations"] } = $props();
  const W = 640;
  const H = 300;
  const at = $derived(new Map(entities.map((e, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, entities.length) - Math.PI / 2;
    return [e.name, { x: W / 2 + 230 * Math.cos(a), y: H / 2 + 110 * Math.sin(a) }];
  })));
  const tone: Record<string, string> = { model: "blue", benchmark: "violet", project: "green", paper: "amber", company: "red", lab: "green", product: "blue" };
  const short = (s: string): string => (s.length > 22 ? s.slice(0, 21) + "…" : s);
</script>

<figure class="relmap">
  <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={relations.map((r) => `${r.from} ${r.kind} ${r.to}`).join("; ")}>
    {#each relations as r, i (r.from + r.to + i)}
      {@const a = at.get(r.from)}
      {@const b = at.get(r.to)}
      {#if a && b}
        <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} class="edge" />
        <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} text-anchor="middle" class="verb">{r.kind}</text>
      {/if}
    {/each}
    {#each entities as e (e.name)}
      {@const p = at.get(e.name)!}
      <g class={"node " + (tone[e.kind] || "grey")}>
        <rect x={p.x - 78} y={p.y - 17} width="156" height="34" rx="8" />
        <text x={p.x} y={p.y - 1} text-anchor="middle" class="n"><title>{e.name}</title>{short(e.name)}</text>
        <text x={p.x} y={p.y + 11} text-anchor="middle" class="k">{e.kind}</text>
      </g>
    {/each}
  </svg>
  <figcaption class="muted small">Who is involved and how, each link a cited line; drawn by the page.</figcaption>
</figure>

<style>
  svg { width: 100%; height: auto; display: block; }
  .edge { stroke: var(--line2); stroke-width: 1.5; }
  .verb { fill: var(--muted); font: 11px var(--sans); }
  .node rect { fill: var(--box); stroke: var(--border-2); stroke-width: 1.5; }
  .node.blue rect { stroke: var(--blue); }
  .node.violet rect { stroke: var(--violet); }
  .node.green rect { stroke: var(--green); }
  .node.amber rect { stroke: var(--amber); }
  .node.red rect { stroke: var(--red); }
  .n { fill: var(--ink); font: 12px var(--sans); }
  .k { fill: var(--muted); font: 10px var(--mono); }
  figure { margin: 12px 0; }
</style>
