<script lang="ts">
  // Settings › Watching, the pane. With nothing selected, the key as it is now and where keys are
  // kept. The watching model (sel=ekey): its form (KeyField, the welcome step's too).
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import Pane from "../../ui/Pane.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { groupOf, kindLine } from "../../ui/settings";
  import KeyField from "./KeyField.svelte";
  import { keyWords, SETUP_API, type Setup } from "./keys.svelte";

  let { view }: { view: View } = $props();
  const id = $derived(groupOf(view.w));
  const host = $derived(!!ui.facts?.header.host);
  const known = $derived(id === "key");
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host && (!id || known) ? read<Setup>(SETUP_API, 10000) : null;
  });
  const s = $derived(c?.data || null);
</script>

{#snippet gone(text: string)}<div class="pane-empty"><p class="empty">{text}</p></div>{/snippet}
{#snippet st(x: readonly [string, string, string])}<Mark name={x[0]} colour={x[1]} word={x[2]} />{/snippet}

<Detail back={view.back}>
  {#if id && !known}
    {@render gone("Nothing to show here.")}
  {:else if !host}
    {#if id}<NeedHost what="Keys" />{:else}{@render gone("Keys need the server, which is not answering.")}{/if}
  {:else if !s}
    <div class="pane-in"><Loading error={c?.error} /></div>
  {:else if id === "key"}
    {@const kw = keyWords(s.key, Date.now(), s.logins?.claude ?? null)}
    <Pane title="Watching model" lede={kw.line} sections={[{ id: "key", w: "Claude API, OpenRouter, an endpoint or Claude Code" }]}>
      {#snippet kind()}<Glyph name={kw.st[0]} colour={kw.st[1]} word={kw.st[2]} />{kindLine("watching", "provider and key")}{/snippet}
      {#snippet section()}<KeyField k={s.key} done={s.done} />{/snippet}
    </Pane>
  {:else}
    {@const kw = keyWords(s.key, Date.now(), s.logins?.claude ?? null)}
    {#snippet keyNow()}{@render st(kw.st)}{" " + kw.line}{/snippet}
    <Pane title="Keys" lede="Kranto watches topics with a cheap model through your key."
      sections={[{ id: "state", w: "Now" }, { id: "kept", w: "Where keys are kept" }]}>
      {#snippet kind()}<Glyph name={kw.st[0]} colour={kw.st[1]} word={kw.st[2]} />{kindLine("watching")}{/snippet}
      {#snippet section(sec)}
        {#if sec.id === "state"}
          <Kv rows={[["Watching model", keyNow]]} />
        {:else}
          <p class="small">{`The watching model's key is kept in the workspace's .env ($${s.key.env}), readable by you only. It never appears in a page, a log or kranto.yaml.`}</p>
        {/if}
      {/snippet}
    </Pane>
  {/if}
</Detail>
