<script lang="ts">
  // Settings › Watching › Live search: the backend the grounded callers search
  // with, each caller's switch, and how many weeks "recent" is; each row's form is in the pane.
  import Group from "../../ui/Group.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { callersLine, SEARCH_API, searchWords, type SearchSetup } from "./search.svelte";

  let { view }: { view: View; part?: string | null } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const r = $derived.by(() => {
    void view.tick;
    return host ? read<SearchSetup>(SEARCH_API, 10000) : null;
  });
  const s = $derived(r?.data || null);
  const w = $derived(s ? searchWords(s) : null);
</script>

{#if host}
  <Group id="w-search" title="Live search" count="3" kind="sets">
    <SetRow key="search" word="Search with" summary={w ? w.line : "reading…"} state={w ? w.st : SET_ST.checking} />
    <SetRow key="search:callers" word="Who searches" summary={s ? callersLine(s.callers) : "reading…"} state={s ? SET_ST.set : SET_ST.checking} />
    <SetRow key="search:weeks" word="Recent means" summary={s ? `the last ${s.recent_weeks} weeks` : "reading…"} state={s ? (s.recent_weeks === 12 ? SET_ST.dflt : SET_ST.set) : SET_ST.checking} />
  </Group>
{/if}
