<script lang="ts">
  // A draft as a page (#/post/d/<id>;): Post › the draft's title, then its sheet (the
  // draft folded, Send or Copy, Download, Decline, Details).
  import NeedHost from "../../ui/NeedHost.svelte";
  import Page from "../../pages/Page.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import DraftSheet from "./DraftSheet.svelte";
  import { sheetPath, type PostSheet } from "./post";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const id = $derived(view.w.r.path[2] || "");
  const s = $derived.by(() => {
    void view.tick;
    return host && id ? read<PostSheet>(sheetPath(id), 30000).data : null;
  });
  const title = $derived(s?.title || "A draft");
</script>

{#if !host}
  <div data-title="Post"><NeedHost what="Post" verb="needs" /></div>
{:else}
  <!-- the shell's crumb has Home › Post already (the door); the page adds itself -->
  <Page head={{ title, label: title, crumb: [{ to: `post/d/${id}`, w: title.length > 48 ? title.slice(0, 47) + "…" : title }] }}>
    {#snippet body()}<DraftSheet {id} tick={view.tick} titled={false} />{/snippet}
  </Page>
{/if}
