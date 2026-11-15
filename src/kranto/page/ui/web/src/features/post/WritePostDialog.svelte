<script lang="ts">
  // Write a post's question (the decision dialog): "Write a post about this idea?",
  // the facts (About, As, Then), one optional line of the owner's own (P-1, "What do
  // you think?", sent as take: the post builds on it and speaks for them only from it), Details,
  // Cancel and Write draft. As is a blog post, or a short post for Mastodon (a card only). Nothing
  // is sent from here; the draft can be edited on Post (the twelfth screen).
  import DialogFrame from "../../ui/DialogFrame.svelte";
  import { read } from "../../lib/reads.svelte";
  import { aboutLine, startWrite, type About } from "./post";

  let { about, close }: { about: About; close: () => void } = $props();
  // a card or the week may be a blog post or a short post; a brief's item a blog post
  const card = $derived(!("brief" in about));
  let as = $state<"blog" | "toot">("blog");
  let take = $state("");
  const title = $derived("week" in about ? "Write a post about this week's news?" : "card" in about ? "Write a post about this idea?" : "Write a post about this story?");
  const details = $derived("card" in about ? `card:${about.card}` : null);
  // no voice yet (skipped in Welcome): the question offers it once more, in one line
  const prose = $derived(read<{ voice?: string; samples?: unknown[] }>("/api/prose", 60000).data || null);
  const noVoice = $derived(!!prose && !(prose.voice || "").trim() && !(prose.samples || []).length);
</script>

<DialogFrame {title} okText="Write draft" {details} {close} ok={(btn) => startWrite(btn, about, as, close, take)}>
  <dl class="kv" id="write-post-facts">
    <dt>About</dt><dd id="write-post-about">{aboutLine(about)}</dd>
    <dt>As</dt>
    <dd>{#if card}<label class="inline"><input type="radio" name="write-as" value="blog" bind:group={as} /> Blog post</label>{" "}<label class="inline"><input type="radio" name="write-as" value="toot" bind:group={as} /> A short post for Mastodon</label>{:else}Blog post{/if}</dd>
    <dt><label for="write-post-take">What do you think?</label></dt>
    <dd><input id="write-post-take" class="wide" type="text" maxlength="600" placeholder="Optional: one line in your words" bind:value={take} /></dd>
    <dt>Then</dt><dd>The draft waits on Post to edit. Nothing is sent until you choose Send.</dd>
  </dl>
  {#if noVoice}<p class="muted small" id="write-post-voice"><a href="#/settings/posting/voice" onclick={close}>Set up how you write ›</a></p>{/if}
</DialogFrame>
