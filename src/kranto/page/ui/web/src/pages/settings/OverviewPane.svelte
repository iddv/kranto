<script lang="ts">
  // Settings › Overview, the pane: find a setting by its name (or its key), where things are
  // kept (the address; kranto paths has the rest), and Feedback (FB).
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Kv from "../../ui/Kv.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { kindLine } from "../../ui/settings";
  import { findSettings } from "./overview";
  import { openFeedback } from "../../ui/sendFeedback";

  let { view }: { view: View } = $props();
  let q = $state("");
  const found = $derived(findSettings(q).slice(0, 30));
</script>

<Detail back={view.back}>
  <Pane title="Settings" lede="Seven pages, in the order you set kranto up: watching, posting, the assistant, then money, privacy, the machine and the look." sections={[{ id: "find", w: "Find a setting" }, { id: "where", w: "Where things are" }, { id: "feedback", w: "Feedback" }]}>
    {#snippet kind()}<Glyph name="dot" colour="blue" word="Settings" />{kindLine("overview")}{/snippet}
    {#snippet section(s)}
      {#if s.id === "find"}
        <input type="search" id="find-setting" placeholder="A setting's name or its key" aria-label="Find a setting" style="width:min(100%,360px)" value={q} oninput={(e) => (q = e.currentTarget.value)} />
        {#if q.trim()}{#if found.length}<ul class="small mt" id="found">{#each found as f (f.href + f.w)}<li><a href={f.href}>{f.w}</a><span class="muted">{" · " + f.at}</span></li>{/each}</ul>{:else}<p class="muted small mt">Nothing by that name.</p>{/if}{/if}
      {:else if s.id === "feedback"}
        <p>A bug, an idea or a question goes to Kranto's GitHub as an issue, from you: filed through your own gh when it is logged in, else on GitHub's new-issue page, filled in. You read all of it first.</p>
        <button type="button" class="btn sm mt" id="set-feedback" onclick={() => openFeedback()}>Send feedback</button>
        <p class="muted small mt">Where it goes is <code>feedback.repo</code> in your settings.</p>
      {:else}
        <Kv rows={[["Address", location.host, "mono"]]} /><p class="muted small mt">On the machine, <code>kranto paths</code> lists every place Kranto keeps something: your settings, the keys' file, the tokens, the data.</p>
      {/if}
    {/snippet}
  </Pane>
</Detail>
