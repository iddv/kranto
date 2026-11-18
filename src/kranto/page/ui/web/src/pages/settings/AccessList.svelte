<script lang="ts">
  // Settings › Privacy & access, the list: the doors (this page, kranto mcp, the command line) and the
  // named agents, each a row with what it may run and when it was last used.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Loading from "../../ui/Loading.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import Mark from "../../shell/Mark.svelte";
  import { plural, rel } from "../../lib/format";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST, selHref } from "../../ui/settings";
  import { ACCESS_API, isAgent, tokWord, type Token, type Tokens } from "./access";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return host ? read<Tokens>(ACCESS_API, 15000) : null;
  });
  const d = $derived(c?.data || null);
  const doors = $derived(d ? d.tokens.filter((t) => !isAgent(t)) : []);
  const agents = $derived(d ? d.tokens.filter(isAgent) : []);
  const summary = (t: Token) =>
    [isAgent(t) ? (t.actions ? `may run ${plural(t.actions.length, "action")}` : "may run what kranto mcp may") : "a door",
     t.last_used ? "used " + rel(t.last_used) : "not used since Kranto started", t.note].filter(Boolean).join(" · ");
</script>

{#if !host}
  <List title="Access" crumb="Settings"><p class="empty">The tokens are kept by the server, which is not answering: kranto token list shows them.</p></List>
{:else if !d}
  <List title="Access" crumb="Settings"><Loading error={c?.error} /></List>
{:else}
  <List title="Access" crumb="Settings">
    {#snippet tools()}{#if !d.require_token}<span class="tbn"><Mark name="warn" colour="amber" word="api.require_token is off: a request says who it is" /></span>{/if}<span class="grow"></span><a class="btn sm primary" id="add-agent" href={selHref(view.w, "enew-agent")}>Add an agent</a>{/snippet}
    <Group id="ac-doors" title="Doors" count={String(doors.length)} kind="sets">{#each doors as t (t.name)}<SetRow key={"tok:" + t.name} word={tokWord(t)} summary={summary(t)} state={SET_ST.ok} />{/each}</Group>
    <Group id="ac-agents" title="Agents" count={String(agents.length)} kind="sets">{#each agents as t (t.name)}<SetRow key={"tok:" + t.name} word={tokWord(t)} summary={summary(t)} state={SET_ST.ok} />{/each}{#snippet foot()}{#if !agents.length}<p class="empty">No agent tokens. Add an agent.</p>{/if}{/snippet}</Group>
  </List>
{/if}
