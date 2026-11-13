<script lang="ts">
  // Settings › System › Activity: how long the runs' marks are kept and
  // how many at most. Was a form at the foot of Activity; the page keeps one line that links here.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { ACTIVITY_SETTINGS, activityWords, type ActivitySettings } from "./activityset";

  let { view }: { view: View; part?: string } = $props();
  const st = $derived.by(() => {
    void view.tick;
    return app()?.host() ? read<ActivitySettings>(ACTIVITY_SETTINGS, 60000) : null;
  });
</script>

{#if st}
  <List title="Activity" crumb="Settings">
    <Group id="set-activity" title="Activity" count="" kind="sets" says="what Kranto is doing: its runs' marks">
      <SetRow key="activity" word="Runs' marks are kept" summary={st.data ? activityWords(st.data) : st.error ? `Could not read it: ${st.error}` : "reading…"} state={SET_ST.set} />
    </Group>
  </List>
{/if}
