<script lang="ts">
  // Settings › Appearance, the list: the theme (its name, light or dark) and the custom theme.
  // One layout (New); a stored `shell.layout: classic` reads as New and is kept as it is.
  import Group from "../../ui/Group.svelte";
  import List from "../../ui/List.svelte";
  import SetRow from "../../ui/SetRow.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { customNow, lookName, lookNow, themeNow } from "../../lib/theme";
  import { SET_ST } from "../../ui/settings";

  let { view }: { view: View } = $props();
  const now = $derived.by(() => {
    void view.tick; // a pick redraws
    return { t: themeNow(), lk: lookNow(), cust: !!customNow() };
  });
</script>

<List title="Appearance" crumb="Settings">
  <Group id="a-theme" title="Appearance" count="2" kind="sets">
    <SetRow key="theme" word="Theme" summary={`${lookName(now.lk)} · ${now.t === "auto" ? "auto: follows this device" : now.t}`} state={now.t === "auto" && now.lk === "kranto" ? SET_ST.dflt : SET_ST.set} />
    <SetRow key="custom" word="Custom theme" summary={!now.cust ? "five colours of your own" : now.lk === "custom" ? "in use" : "made, not in use"} state={now.cust ? SET_ST.set : SET_ST.dflt} />
  </Group>
</List>
