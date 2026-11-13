<script lang="ts">
  import { pageUrl } from "../../lib/base";
  // Today's empty states (PLAN.md 1.5; UI-v4.md 1.4; the old page's readingLine): with no topic,
  // the mark, what will appear and when, and Add a topic, at the top of the list (main); while
  // the library is small (under 30 observations), what Kranto is reading, in the pane (side).
  import type { Setup } from "../../api/afk.gen";
  import MarkEmpty from "../../ui/MarkEmpty.svelte";
  import { plural, readingWords } from "../../lib/format";
  import { read } from "../../lib/reads.svelte";
  import type { Host } from "./needs";

  let { host, side = false }: { host: Host | null; side?: boolean } = $props();
  const n = $derived(host ? host.sources.filter((s) => s.status === "approved").length : 0);
  const t = $derived(host ? host.topics.length : 0);
  const small = $derived(!!host && side && t > 0 && host.observations < 30);
  // first run: setup done and no ingest yet is the first ingest running
  const setup = $derived(small ? read<Setup>("/api/setup", 600000).data : null);
  const busy = $derived.by(() => {
    if (!host || !small) return "";
    if (host.ingest_progress) return `Reading now: ${readingWords(host.ingest_progress)}.`;
    const ingest = (host.runs || []).find((x) => x.kind === "ingest");
    return setup && setup.done && !ingest ? "First ingest running." : ingest ? `Last ingest ${(ingest.finished_at || "").slice(0, 16).replace("T", " ")}, ${ingest.status}.` : "No ingest yet.";
  });
</script>

{#if host && !t && !side}
  <section class="box" role="status"><MarkEmpty text="No topics yet. The kranto read nothing until you say what you are interested in; after the first ingest, what they keep shows up here, the newest first."><a class="btn primary" href="#/topics/new">Add a topic</a></MarkEmpty></section>
{:else if host && small}
  <section class="box" role="status"><div class="hero"><img src={pageUrl("static/brand/icon-192.png")} alt="" width="72" height="72" /><p class="small muted">{`Kranto is reading ${plural(n, "source")} for ${plural(t, "topic")}. ${busy} Themes appear after about 30 observations (${host.observations} so far); ideas after the first map.`}</p></div></section>
{/if}
