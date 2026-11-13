<script lang="ts">
  // A route the app does not have: the list pane says so, with the way home (QA B11: "Go to Today",
  // a place retired with the doors).
  import MarkEmpty from "../ui/MarkEmpty.svelte";
  import type { View } from "../lib/pages.svelte";

  let { view }: { view: View } = $props();
</script>

<div data-title="Not found"><section class="box"><MarkEmpty text={`There is no page at #/${view.w.r.path.join("/")}. It may have moved in this version.`}><a class="btn" href="#/">Go home</a></MarkEmpty></section></div>
