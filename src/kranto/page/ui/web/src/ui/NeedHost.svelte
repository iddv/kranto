<script lang="ts">
  // A page that needs the server's data while the server does not answer (its /api/status read
  // failed: stopped, restarting, or the page was left open after kranto down).
  let { what, verb = "need" }: { what: string; verb?: string } = $props();
</script>

<div><div class="ph"><h1>{what}</h1></div><section class="box"><div class="box-b"><p><strong>{`${what} ${verb} Kranto's server, which is not answering. `}</strong>Start it with kranto up (kranto status says whether it runs), then reload this page.</p></div></section></div>
