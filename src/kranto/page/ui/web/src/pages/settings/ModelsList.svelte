<script lang="ts">
  // Settings › Watching › Models, the list: each of watching's roles (the Judge, the Reasoner),
  // what it calls now, and whether that is set or a choice not saved yet. The server's alone.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { AFK_MODELS, changed, modelName, pickOf, roleSpecs, type AfkModels, type Spec, watchingVia } from "./models.svelte";

  let { view }: { view: View; part?: string | null } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick;
    return host ? read<AfkModels>(AFK_MODELS, 30000) : null;
  });
  const xs = $derived(a?.data ? roleSpecs(a.data) : null);
  const summary = (x: Spec) => modelName(x.cat, pickOf(x));
  const state = (x: Spec) => (changed(x) ? SET_ST.changed : SET_ST.set);
</script>

<List title="Models" crumb="Settings">
  {#snippet tools()}<span class="tbn"><span class="mono">{a?.data ? "watching via " + watchingVia(a.data) : host ? "" : "the server is not answering: its models are not shown"}</span></span>{/snippet}
  {#if !host}{:else if !xs}
    <Group id="m-watch" title="Models" kind="sets">{#snippet foot()}<Loading error={a?.error} />{/snippet}</Group>
  {:else if xs.length}
    <Group id="m-watch" title="Models" count={String(xs.length)} kind="sets">{#each xs as x (x.key)}<SetRow key={"role:" + x.key} word={x.role.name} summary={summary(x)} state={state(x)} />{/each}</Group>
  {/if}
</List>
