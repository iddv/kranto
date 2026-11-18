<script lang="ts">
  // Needs you's pane: with nothing selected, what Kranto is reading while the library is
  // small and the recent Claude Code sessions; a row that is not an object's own route (NEEDSELS:
  // sel=p a topic's proposals, m a message, r the review queue) is drawn here, beside any list that
  // links one. The rows that are objects (an idea, a source, a theme, an observation) open their
  // home's pane.
  import Detail from "../../ui/Detail.svelte";
  import Loading from "../../ui/Loading.svelte";
  import { longTime, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { app } from "../../lib/shell.svelte";
  import MessagePane from "./MessagePane.svelte";
  import ProposedPane from "./ProposedPane.svelte";
  import QueuePane from "./QueuePane.svelte";
  import Reading from "./Reading.svelte";
  import { termRead, todayRead, type Host } from "./needs";

  let { view }: { view: View } = $props();
  const H = $derived.by(() => {
    void view.tick;
    return (app()?.host() as Host | null | undefined) || null;
  });
  const code = $derived(view.w.object === "need" && view.w.id ? view.w.id : null);
  const k = $derived(code ? code[0] : "");
  const id = $derived(code ? code.slice(1) : "");
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return k === "m" || k === "p" ? todayRead(H) : null;
  });
  const t = $derived(c?.data || null);
  const sessions = $derived.by(() => {
    void view.tick;
    return (termRead().data?.sessions || []).slice().sort((a, b) => (b.updated || 0) - (a.updated || 0)).slice(0, 5);
  });
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}

<Detail back={view.back}>
  {#if !code}
    <div class="pane-empty"><p class="empty">Nothing selected.</p><Reading host={H} side /><section class="box"><div class="box-h"><h2>Claude Code</h2></div>{#if sessions.length}<ul class="box-b ctx">{#each sessions as x (x.tid)}<li><a href={"#"} data-act="term" onclick={(e) => { e.preventDefault(); app()?.openClaude(x.subject.kind, x.subject.id, x.title); }}>{x.title || x.subject.id}</a><span class="n">{#if x.updated}<time title={longTime(x.updated * 1000)}>{rel(x.updated)}</time>{:else}{x.words}{/if}</span></li>{/each}</ul>{:else}<div class="box-b"><p class="muted small">No sessions yet: type c on an idea, or open the console.</p></div>{/if}</section></div>
  {:else if k === "r"}
    <QueuePane {view} host={!!H} />
  {:else if !H}
    {@render gone("This comes from the server, which is not answering.")}
  {:else if !t}
    <Loading error={c?.error} />
  {:else if k === "m"}
    {@const m = t.messages.find((x) => String(x.id) === id)}
    {#if m}<MessagePane {m} />{:else}{@render gone("This message is no longer new. Every message is kept under Settings › System › Health.")}{/if}
  {:else if k === "p"}
    {@const x = t.topics.find((y) => String(y.id) === id)}
    {#if x && x.proposed}<ProposedPane {x} {view} />{:else}{@render gone("Nothing waits for you here now: the proposals were watched or retired.")}{/if}
  {:else}
    {@render gone("Nothing to show.")}
  {/if}
</Detail>
