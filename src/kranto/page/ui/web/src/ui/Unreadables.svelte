<script lang="ts">
  // The rows this page's lists could not read (lib/unreadable): the rest of
  // the list draws as always, and each of these is one line under the page's head, "Couldn't read
  // this source · Energy Feed · error 1a2b3c4d", with Send this error (Feedback, with the error's
  // report shown before anything is sent). Nothing at all while every row was read.
  import Icon from "../shell/Icon.svelte";
  import { parse } from "../lib/router";
  import { ui } from "../lib/shell.svelte";
  import { onPage } from "../lib/unreadable.svelte";
  import { sendError } from "./sendFeedback";

  const rows = $derived.by(() => {
    void ui.drawn;
    return onPage(parse().path[0] || "");
  });
</script>

{#if rows.length}
  <div class="unreadable" id="unreadable" role="status" aria-label="Rows Kranto couldn't read">
    {#each rows as r (r.unreadable.what + ":" + String(r.id))}
      <div class="flash amber failed unread" data-error={r.unreadable.error_id} data-what={r.unreadable.what}><Icon name="warn" /><span class="why grow"><strong>{r.unreadable.words}</strong>{#if r.label}{" · "}{r.label}{/if}<span class="muted">{" · error "}{r.unreadable.error_id}</span></span><span class="acts"><button type="button" class="btn sm quiet" onclick={() => sendError(r.unreadable.error_id, r.unreadable.words)}>Send this error</button></span></div>
    {/each}
  </div>
{/if}
