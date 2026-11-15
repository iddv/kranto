<script lang="ts">
  // A reason in the one popover (Reject, Pass): its chips, each with its letter (a–f press it),
  // or a few words of your own, then enter: at most REASON_MAX characters (17, Codex 14: 5,000
  // made the page 46,000 px wide), and the words a page shows wrap.
  let { title, chips, pick }: { title: string; chips: string[]; pick: (why: string) => void } = $props();
  const REASON_MAX = 200;
  let words = $state("");
</script>

<div class="pop-h">{title}</div><div class="chips">{#each chips as c, n (c)}<button class="chip" type="button" data-chip={c} onclick={() => pick(c)}><kbd>{"abcdef"[n]}</kbd>{" " + c}</button>{/each}</div><input type="text" aria-label="Or in your own words" placeholder="or in your own words, then enter" style="width:100%" maxlength={REASON_MAX} bind:value={words} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); pick(words.trim().slice(0, REASON_MAX)); } }} />
