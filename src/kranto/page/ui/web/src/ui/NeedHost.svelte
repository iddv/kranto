<script lang="ts">
  // A page that needs the server, on brb ui alone (the old page's needKranto()).
  let { what, verb = "need" }: { what: string; verb?: string } = $props();
</script>

<div><div class="ph"><h1>{what}</h1></div><section class="box"><div class="box-b"><p><strong>{`${what} ${verb} the server. `}</strong>This page is served by brb ui on its own, without the server. Open the server (afk serve, usually http://127.0.0.1:8765/) with brb.enabled set in kranto.yaml, and every tab is in one place.</p></div></section></div>
