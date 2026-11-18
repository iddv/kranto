<script lang="ts">
  // Watch › Sources of All topics (#/watch/sources, what Settings › Sources was:
  // data, not a setting): every source by its state, Add source, the accounts they are read with;
  // a source opens in the sheet. All topics is a choice: a topic's own sources are its page,
  // #/watch/topic/<id>/sources, where the topic switcher and these chips lead.
  import type { View } from "../../lib/pages.svelte";
  import { href } from "../../lib/router";
  import SourcesList from "../settings/SourcesList.svelte";
  import TopicChips from "./TopicChips.svelte";

  let { view }: { view: View } = $props();
</script>

<TopicChips at={view.tick} broad={view.w.r.q.status === "broad"} />
<SourcesList {view} />
