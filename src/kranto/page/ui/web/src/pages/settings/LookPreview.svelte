<script lang="ts">
  // A theme's miniature, drawn by looks.css on the base in use: a header strip, the sidebar with
  // its highlight, badge and dot, a card with a button, a pill and a link. vars, for a custom
  // theme being picked, are its worked-out colours.
  let { id, base, vars = null }: { id: string; base: string | null; vars?: Record<string, string> | null } = $props();
  const style = $derived(vars ? Object.entries(vars).map(([k, v]) => `${k}: ${v}`).join("; ") : null);
</script>

<span class="pv" data-look={id} data-theme={base} aria-hidden="true" {style}><span class="pv-hd"></span><span class="pv-sd"><i class="pv-on"></i><i></i><i class="pv-bd"></i><i class="pv-dt"></i></span><span class="pv-mn"><span class="pv-card"><i></i><i class="pv-s"></i><span class="pv-row"><i class="pv-b"></i><i class="pv-p"></i><i class="pv-l"></i></span></span></span></span>
