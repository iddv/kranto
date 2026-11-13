<script lang="ts">
  // The one empty state: one sentence that says what will appear and when, and at
  // most one link. In a group (li: inside its rows) it is muted in the group; in a list's place a
  // line; the mark only when a whole door is empty on arrival (no topic yet, no idea yet).
  import MarkEmpty from "./MarkEmpty.svelte";

  let { text, link = null, kranto = false, li = false }: { text: string; link?: { href: string; w: string } | null; kranto?: boolean; li?: boolean } = $props();
</script>

{#if kranto}<MarkEmpty {text}>{#if link}<a class="btn sm" href={link.href}>{link.w}</a>{/if}</MarkEmpty>
{:else if li}<li class="gempty state-empty"><span class="muted">{text}</span>{#if link}{" "}<a href={link.href}>{link.w}</a>{/if}</li>
{:else}<p class="state-empty"><span class="muted">{text}</span>{#if link}{" "}<a href={link.href}>{link.w}</a>{/if}</p>{/if}
