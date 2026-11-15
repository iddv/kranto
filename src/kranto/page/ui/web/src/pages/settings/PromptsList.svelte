<script lang="ts">
  // Settings › Prompts, the list: every prompt Kranto sends a model (the server's /api/prompts),
  // grouped by its step: whose text it runs (the default, your additions, your full prompt),
  // additions only, a default that changed under your version, where it runs. A process on the
  // defaults only says so in the toolbar.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import NeedHost from "../../ui/NeedHost.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { groupId, groupsOf, groupWord, promptMeta, promptsRead, promptState } from "./prompts.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host ? promptsRead() : null;
  });
  const d = $derived(c?.data || null);
</script>

{#if !host}
  <List title="Prompts" crumb="Settings"><NeedHost what="Prompts" /></List>
{:else if !d}
  <List title="Prompts" crumb="Settings"><p class="empty">{c?.error ? "Could not read the prompts: " + c.error : "Loading…"}</p></List>
{:else}
  {#snippet tools()}<span class="tbn"><Mark name="warn" colour="amber" word="Defaults only: this process ignores every customisation (KRANTO_PROMPTS=defaults)" /></span>{/snippet}
  <List title="Prompts" crumb="Settings" tools={d.defaults_only ? tools : undefined}>
    {#each groupsOf(d.prompts) as g (g)}
      {@const xs = d.prompts.filter((p) => p.group === g)}
      <Group id={groupId(g)} title={groupWord(g)} count={String(xs.length)} kind="sets">
        {#each xs as p (p.id)}<SetRow key={"prompt:" + p.id} word={p.title} summary={promptMeta(p)} state={promptState(p)} />{/each}
      </Group>
    {/each}
    {#if !d.prompts.length}<p class="empty">No prompt can be steered here.</p>{/if}
  </List>
{/if}
