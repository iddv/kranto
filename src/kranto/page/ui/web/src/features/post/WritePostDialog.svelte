<script lang="ts">
  // Write a post's question (the decision dialog): "Write a post about this idea?",
  // the facts (About, As, Then), the angle step (one box, "Why does this interest you? One
  // sentence.", with three proposals from POST /api/post/angles beside it: where it leads, a bet
  // and a scene; one press fills the box, Skip empties it and no angle is sent), Details,
  // Cancel and Write draft (the drafts wait on Post; nothing is sent from here). As is a blog post, or short posts for the sites ticked on Settings ›
  // Posting (a card or a news item; this week's news is a blog post). Nothing is sent from here;
  // the drafts wait on Post.
  import DialogFrame from "../../ui/DialogFrame.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { aboutKey, aboutLine, POSTING_API, shortLine, startWrite, type About, type Angle, type WriteAs } from "./post";
  import type { Posting } from "../../api/afk.gen";

  let { about, close }: { about: About; close: () => void } = $props();
  // a card or a news item may be short posts; the week a blog post only
  const canShort = $derived(!("week" in about));
  let as = $state<WriteAs>("blog");
  let angle = $state("");
  const title = $derived("week" in about ? "Write a post about this week's news?" : "card" in about ? "Write a post about this idea?" : "Write a post about this story?");
  const details = $derived("card" in about ? `card:${about.card}` : null);
  // no voice yet (skipped in Welcome): the question offers it once more, in one line
  const prose = $derived(read<{ voice?: string; samples?: unknown[] }>("/api/prose", 60000).data || null);
  const noVoice = $derived(!!prose && !(prose.voice || "").trim() && !(prose.samples || []).length);
  const posting = $derived(canShort ? read<Posting>(POSTING_API, 60000).data || null : null);
  const ticked = $derived((posting?.sites || []).filter((s) => s.ticked).map((s) => s.name));
  // the angle step: three proposals for what this is, as this kind of post
  let angles = $state<Angle[]>([]);
  let anglesWhy = $state("");
  let asked = "";
  $effect(() => {
    const key = `${aboutKey(about)}|${as}`;
    if ("week" in about || key === asked) return;
    asked = key;
    void propose(aboutKey(about), as);
  });
  // a proposal's button is its sentence, readable before it is chosen; a press fills the box,
  // where it is changed (counted: about 92 words, 11 controls with three proposals)
  // round 3's kinds, and round 2's (a stored draft or an older server may still name them)
  const kindWord = (k: string): string => ({ end: "Where it leads", bet: "A bet", scene: "A scene", claim: "A claim", prediction: "A prediction", question: "A question" } as Record<string, string>)[k] || k;
  async function propose(k: string, a: WriteAs): Promise<void> {
    const L = app();
    if (!L) return;
    anglesWhy = "";
    try {
      const r = (await L.api("/api/post/angles", { about: k, as: a })) as { angles?: Angle[] } | null;
      angles = Array.isArray(r?.angles) ? r.angles.slice(0, 3) : [];
    } catch (e) {
      angles = [];
      anglesWhy = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<DialogFrame {title} okText="Write draft" {details} {close} ok={(btn) => startWrite(btn, about, as, close, angle)}>
  <dl class="kv wp-kv" id="write-post-facts">
    <dt>About</dt><dd id="write-post-about">{aboutLine(about)}</dd>
    <dt>As</dt>
    <dd>{#if canShort}<label class="inline wp-as"><input type="radio" name="write-as" value="blog" bind:group={as} /> Blog post</label>{" "}{#if ticked.length}<label class="inline wp-as"><input type="radio" name="write-as" value="short" bind:group={as} /> {shortLine(ticked)}</label>{:else}<label class="inline wp-as muted"><input type="radio" name="write-as" value="short" disabled /> <a href="#/settings/posting" onclick={close}>Short posts: choose your sites first</a></label>{/if}{:else}Blog post{/if}</dd>
    <!-- the angle's question sits above its box at every width: a long label beside it made the
         dialog wider than a phone (390 px: 570 px of content in 358) -->
    <dt class="wp-full"><label for="write-post-angle">Why does this interest you? One sentence.</label></dt>
    <dd class="wp-full">
      <input id="write-post-angle" class="wide" type="text" maxlength="600" bind:value={angle} />
      {#if angles.length}<span class="small" id="write-post-angles">{#each angles as a (a.kind)}<button type="button" class="linkish small angle" data-angle={a.kind} aria-label={`${kindWord(a.kind)}: ${a.text}`} onclick={() => (angle = a.text)}>{a.text}</button><br />{/each}<button type="button" class="linkish small" id="write-post-skip" onclick={() => (angle = "")}>Skip</button></span>{:else if anglesWhy}<span class="muted small" id="write-post-angles-why">{anglesWhy}</span>{#if anglesWhy.includes("Settings › Watching")}{" "}<a class="small" id="write-post-angles-fix" href="#/settings/watching" onclick={close}>Settings › Watching ›</a>{/if}{/if}
    </dd>
  </dl>
  {#if noVoice}<p class="muted small" id="write-post-voice"><a href="#/settings/posting/voice" onclick={close}>Set up how you write ›</a></p>{/if}
</DialogFrame>

<style>
  /* the dialog fits a phone: every row's content may shrink, the angle's box is the row's width */
  .wp-kv { min-width: 0; }
  .wp-kv :global(dd) { min-width: 0; margin: 0; }
  .wp-kv .wp-full { grid-column: 1 / -1; }
  .wp-kv dt.wp-full { margin-top: 6px; color: var(--ink2, var(--muted)); }
  .wp-kv #write-post-angle { width: 100%; max-width: 100%; box-sizing: border-box; min-width: 0; }
  /* a radio and its words stay together; the words wrap beside the circle, never under it */
  .wp-kv .wp-as { display: flex; flex-wrap: nowrap; align-items: flex-start; gap: 6px; }
  .wp-kv .wp-as input { flex: none; margin-top: 3px; }
  #write-post-angles { display: block; overflow-wrap: anywhere; }
  #write-post-angles .angle { white-space: normal; text-align: left; }
  @media (max-width: 640px) {
    /* on a phone each label sits above its field */
    .wp-kv { grid-template-columns: minmax(0, 1fr); gap: 2px 0; }
    .wp-kv dt { margin-top: 6px; }
  }
</style>
