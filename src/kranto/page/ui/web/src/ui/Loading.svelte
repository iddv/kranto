<script lang="ts">
  // A read that has not arrived: "Loading…", or what went wrong (the old page's loading()). With
  // the doors on (HIG Loading: show something at once) three skeleton rows stand
  // in for the list for two seconds, then "Still reading…"; the words stay for a screen reader.
  // A read that failed is the one Failed: its words, Try again, Tell us.
  import Failed from "./Failed.svelte";

  let { error = null, what = "Kranto", path = null }: { error?: string | null; what?: string; path?: string | null } = $props();
  let slow = $state(false);
  $effect(() => {
    const t = setTimeout(() => (slow = true), 2000);
    return () => clearTimeout(t);
  });
</script>

{#if error}<Failed {what} {error} {path} />{:else}<div class={"loading" + (slow ? " slow" : "")} role="status"><p class="empty">{slow ? "Still reading…" : "Loading…"}</p><div class="skel" aria-hidden="true"><i></i><i></i><i></i></div></div>{/if}
