<script lang="ts">
  // A read that failed: one red line in the list's place, its words, Try again
  // (the read asked again) and Tell us (Feedback, prefilled with the words). Never the raw error in
  // an empty state; the page's head still draws above it. Phrasing content only: it may stand in a
  // row's meta as well as in a list's place. An answer Kranto's error handler wrote (  // B3) carries its error's id in its words: then the line says the version and the id, and Tell
  // us is Send this error (the error's report goes with it, shown first).
  import Icon from "../shell/Icon.svelte";
  import { retry } from "../lib/reads.svelte";
  import { app } from "../lib/shell.svelte";
  import { host } from "../lib/app/data";
  import { errorIdOf } from "../lib/unreadable.svelte";
  import { sendError, tellUs } from "./sendFeedback";

  let { what, error, path = null }: { what: string; error: string; path?: string | null } = $props();
  const text = $derived(`Could not read ${what}: ${error}`);
  const eid = $derived(errorIdOf(error));
  const version = $derived(host()?.version || null);
  function again(): void {
    retry(path);
    app()?.render();
  }
</script>

<span class="flash red failed" role="status" data-error={eid}><Icon name="x" /><span class="why grow">{text}{#if eid}<span class="muted ver">{" · "}{version ? `Kranto ${version} · ` : ""}error {eid}</span>{/if}</span><span class="acts"><button type="button" class="btn sm" onclick={again}>Try again</button>{#if eid}<button type="button" class="btn sm quiet" onclick={() => sendError(eid, `Could not read ${what}`)}>Send this error</button>{:else}<button type="button" class="btn sm quiet" onclick={() => tellUs(text)}>Tell us</button>{/if}</span></span>
