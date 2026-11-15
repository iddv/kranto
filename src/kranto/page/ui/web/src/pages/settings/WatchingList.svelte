<script lang="ts">
  // Settings › Watching: the provider and its key, the Judge's and
  // the Reasoner's models, how sources are read, live search, and the logins some sources
  // are read with (the sites Settings › Accounts had; posting accounts are Posting's).
  import List from "../../ui/List.svelte";
  import Parts from "../../ui/Parts.svelte";
  import type { View } from "../../lib/pages.svelte";
  import KeysList from "./KeysList.svelte";
  import ModelsList from "./ModelsList.svelte";
  import WatchReadList from "./WatchReadList.svelte";
  import SearchList from "./SearchList.svelte";
  import ConnectionsList from "./ConnectionsList.svelte";
  import { ui } from "../../lib/shell.svelte";
  let { view }: { view: View } = $props();
</script>

<List title="Watching" crumb="Settings"><Parts {view} parts={ui.facts?.header.host ? [[KeysList, "key"], [ModelsList, "afk"], [WatchReadList], [SearchList], [ConnectionsList, "reading"]] : [[KeysList, "key"], [ModelsList, "afk"], [WatchReadList], [SearchList]]} /></List>
