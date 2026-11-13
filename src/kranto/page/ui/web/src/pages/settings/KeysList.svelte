<script lang="ts">
  // Settings › Watching, the list: the model key and its provider, a setting group whose form is in
  // the pane (sel=ekey). Without the server, it says so.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { keyWords, SETUP_API, type Setup } from "./keys.svelte";

  // part: "key" on Settings › Watching (the provider and its key)
  let { view }: { view: View; part?: string | null } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host ? read<Setup>(SETUP_API, 10000) : null;
  });
  const s = $derived(c?.data || null);
</script>

{#if !host}
  <List title="Keys" crumb="Settings"><NeedHost what="Keys" /></List>
{:else if !s}
  <List title="Keys" crumb="Settings"><Loading error={c?.error} /></List>
{:else}
  {@const kw = keyWords(s.key)}
  <List title="Keys" crumb="Settings">
    <Group id="k-key" title="Provider and key" count="1" kind="sets">
      <SetRow key="key" word="Provider and key" summary={kw.line} state={kw.st} />
    </Group>
  </List>
{/if}
