<script lang="ts">
  // Settings › Assistant, the list: the console (your own Claude Code or Codex,
  // docked on the right), what an assistant may do by itself (the server's ladder, for the console
  // and your own clients alike; three locks), and how to use Kranto from your own client.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { SET_ST } from "../../ui/settings";
  import { ui } from "../../lib/shell.svelte";
  import type { ConsoleState } from "../../term/console.svelte";
  import { CONSOLE_API, consoleRows, LADDER_API, ladderSummary, type Ladder } from "./assistant";

  let { view }: { view: View } = $props();
  const c = $derived.by(() => {
    void view.tick;
    return read<ConsoleState>(CONSOLE_API, 30000);
  });
  // the ladder is the server's: read where Kranto hosts the page (brb alone has none)
  const host = $derived(!!ui.facts?.header.host);
  const l = $derived.by(() => {
    void view.tick;
    return host ? read<Ladder>(LADDER_API, 30000) : { data: null, error: null, at: 0, loading: false };
  });
</script>

{#if !c.data && !l.data}
  <List title="Assistant" crumb="Settings"><Loading error={c.error || l.error} /></List>
{:else}
  <List title="Assistant" crumb="Settings">
    {#if c.data}
      <Group id="as-console" title="The console" count={String(consoleRows(c.data).length)} kind="sets">
        {#each consoleRows(c.data) as r (r.key)}<SetRow key={r.key} word={r.word} summary={r.summary} state={SET_ST.set} />{/each}
      </Group>
    {/if}
    {#if l.data}
      <Group id="as-ladder" title="What it does by itself" count={String(l.data.kinds.length)} kind="sets">
        {#each l.data.kinds as k (k.kind)}<SetRow key={"lad-" + k.kind} word={k.words} summary={ladderSummary(k)} state={k.locked ? SET_ST.dflt : k.choice === k.default ? SET_ST.dflt : SET_ST.set} />{/each}
      </Group>
    {/if}
    <Group id="as-outside" title="Your own Claude Code or Codex" count="1" kind="sets">
      <SetRow key="outside" word="Use Kranto from your own client" summary="The same tools and the same ladder, one install line" state={SET_ST.dflt} />
    </Group>
  </List>
{/if}
