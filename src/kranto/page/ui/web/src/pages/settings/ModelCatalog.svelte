<script lang="ts">
  // The models a role may call, as one table wherever a model is chosen (C10: a
  // table, numbers and names in columns): its name, its API id and its router name.
  import type { CatModel } from "./models.svelte";

  let { cat }: { cat: readonly CatModel[] } = $props();
</script>

<div class="tw"><table><thead><tr><th>Model</th><th>Name on the API</th><th>Name on the router</th></tr></thead><tbody>{#each cat as c (c.id)}<tr title={c.note}><td>{c.name}</td><td class="mono">{c.id}</td><td class="mono">{c.router}</td></tr>{/each}</tbody></table></div>
