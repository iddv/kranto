<script lang="ts">
  // Settings › System: where Kranto runs, its updates, what
  // Activity keeps, its health and what your grades changed (reports, kept here as groups: the
  // owner's D3; #/settings/grades opens on Your grades).
  import List from "../../ui/List.svelte";
  import Parts from "../../ui/Parts.svelte";
  import type { View } from "../../lib/pages.svelte";
  import GradesList from "./GradesList.svelte";
  import HealthList from "./HealthList.svelte";
  import ServiceList from "./ServiceList.svelte";
  import UpdatesList from "./UpdatesList.svelte";
  import ActivitySetList from "./ActivitySetList.svelte";
  let { view }: { view: View } = $props();
</script>

<List title="System" crumb="Settings"><Parts {view} parts={[[ServiceList], [UpdatesList], [ActivitySetList], [HealthList], [GradesList]]} /></List>
