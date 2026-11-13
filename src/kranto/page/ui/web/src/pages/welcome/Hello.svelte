<script lang="ts">
  // Before setup, the front door (#/hello; UI-v4.md 1.4, 2.5): the mark, the wordmark, one line,
  // one button. A fresh install opens here (boot sends it); a stage route, drawn without the
  // panes.
  import type { View } from "../../lib/pages.svelte";

  let { view: _view }: { view: View } = $props();
  const line = "Watches the topics you choose, keeps what is worth remembering, tells you each day what happened, and writes idea cards from it. On this machine.";
</script>

<div data-title="Welcome"><section class="splash"><img src="static/brand/mark.svg" alt="" width="120" height="120" /><h1>Kranto</h1><p>{line}</p><a class="btn primary" id="set-up" href="#/welcome">Set up Kranto</a></section></div>
