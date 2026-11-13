<script lang="ts">
  // Settings › System › The home: the rows Needs you and New show at most.
  // The pins, what is hidden and which cubs may add rows are Arrange on the home. One layout, New.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import Row from "../../ui/Row.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { SET_ST } from "../../ui/settings";
  import { arrangement } from "../../features/shell";

  let { view }: { view: View } = $props();
  const H = $derived(!!ui.facts?.header.host);
  const a = $derived.by(() => {
    void view.tick;
    return arrangement(H);
  });
</script>

<List title="The home" crumb="Settings">
  {#if a}
    <Group id="sys-shell" title="The home" count="2" kind="sets">
      <SetRow key="caps" word="Rows at most" summary={`Needs you ${a.needs_cap} · New ${a.new_cap} on the home`} state={a.needs_cap === 3 && a.new_cap === 4 ? SET_ST.dflt : SET_ST.set} />
      <Row title="Arrange the home" href="#/home?arrange=1" meta={a.widgets ? "move, size, add and remove its widgets; the cubs' pins" : "the pins, what is hidden, which cubs may add rows"}>{#snippet st()}<Glyph name="dot" colour="blue" word="Arrange" />{/snippet}</Row>
    </Group>
  {/if}
</List>
