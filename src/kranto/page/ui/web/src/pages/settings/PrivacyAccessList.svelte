<script lang="ts">
  // Settings › Privacy & access: usage reports (as Privacy had them) and who may act (as Access had it).
  import List from "../../ui/List.svelte";
  import Parts from "../../ui/Parts.svelte";
  import type { View } from "../../lib/pages.svelte";
  import AccessList from "./AccessList.svelte";
  import PrivacyList from "./PrivacyList.svelte";
  let { view }: { view: View } = $props();
</script>

<List title="Privacy & access" crumb="Settings"><Parts {view} parts={[[PrivacyList], [AccessList]]} /></List>
