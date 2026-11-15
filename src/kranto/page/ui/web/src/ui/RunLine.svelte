<script lang="ts">
  // The one line a page says of its own subject: what of it runs now ("Writing
  // the News brief · Reading what Robotics kept · 1 min · Watch ›"), else what
  // stopped for you with the one verb, else its last failure with what happened, else its quiet
  // form (or nothing). ``subject``: topic:12, kind:news.brief, feature:toot. From the one activity
  // read the top bar shares; never a key or a uuid (the read says it in words).
  import Glyph from "./Glyph.svelte";
  import type { Activity } from "../api/types.gen";
  import { ACT_PATH, lineOf } from "../lib/activity";
  import { read } from "../lib/reads.svelte";

  let { subject, quiet = null, tick = 0, id = null }: { subject: string; quiet?: string | null; tick?: number; id?: string | null } = $props();
  const r = $derived.by(() => {
    void tick;
    return read<Activity>(ACT_PATH, 5000);
  });
  const line = $derived(lineOf(r.data, subject, quiet));
  const G: Record<string, [string, string, string]> = {
    running: ["running", "blue", "Running"], waiting: ["waiting", "amber", "Waits on you"],
    failed: ["x", "red", "Failed"], quiet: ["open", "grey", "Quiet"],
  };
</script>

{#if line}
  {@const g = G[line.state] || G.quiet!}
  <p class="src-line runline" id={id} data-state={line.state}>
    <Glyph name={g[0]} colour={g[1]} word={g[2]} />
    <span>{line.words}</span>
    {#if line.watch}<span class="muted" aria-hidden="true">{" · "}</span><a class="rl-watch" href={line.watch}>{line.state === "running" ? "Watch ›" : "What happened ›"}</a>{/if}
    {#if line.stop}<span class="muted" aria-hidden="true">{" · "}</span><a class="rl-stop" href="#/activity" title="Stop it, on Activity (with Undo)">Stop</a>{/if}
    {#if line.verb}<span class="muted" aria-hidden="true">{" · "}</span><a class="rl-verb" href={line.verb.href}>{line.verb.word} ›</a>{/if}
  </p>
{/if}
