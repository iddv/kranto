<script lang="ts">
  // The theme picker: a card a theme. A radio group: the arrows move, Enter or Space picks, and a
  // pick applies at once.
  import Icon from "../../shell/Icon.svelte";
  import { app } from "../../lib/shell.svelte";
  import { lookChoices, lookNow, setLook } from "../../lib/theme";
  import LookPreview from "./LookPreview.svelte";

  let { tick, base }: { tick: number; base: string | null } = $props();
  const now = $derived.by(() => {
    void tick; // a pick redraws
    return lookNow();
  });
  const all = $derived.by(() => {
    void tick;
    return lookChoices();
  });
  const at = $derived(Math.max(0, all.findIndex((x) => x[0] === now)));
  let grid = $state<HTMLElement>();

  function pickLook(id: string): void {
    setLook(id);
    app()?.render();
    grid?.querySelector<HTMLElement>(`[data-look-choice="${id}"]`)?.focus();
  }
  function lookKeys(e: KeyboardEvent): void {
    const cards = [...(e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>(".look")], i = cards.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); return; }        // the button's own click picks it
    const cols = Math.max(1, cards.filter((c) => c.offsetTop === cards[0]?.offsetTop).length);
    const to = ({ ArrowRight: i + 1, ArrowLeft: i - 1, ArrowDown: i + cols, ArrowUp: i - cols, Home: 0, End: cards.length - 1 } as Record<string, number>)[e.key];
    if (to == null) return;
    e.preventDefault(); e.stopPropagation();
    const c = cards[Math.max(0, Math.min(cards.length - 1, to))] as HTMLElement;
    for (const x of cards) x.tabIndex = x === c ? 0 : -1;
    c.focus();
  }
</script>

<!-- the cards inside take the focus: the group only hears their arrows -->
<!-- svelte-ignore a11y_interactive_supports_focus -->
<div class="looks" role="radiogroup" aria-label="Theme" onkeydown={lookKeys} bind:this={grid}>{#each all as [id, w, blurb], i (id)}<button class="look" type="button" role="radio" aria-checked={id === now ? "true" : "false"} tabindex={i === at ? 0 : -1} data-look-choice={id} title={`${w}: ${blurb}`} onclick={() => pickLook(id)}><LookPreview {id} {base} /><span class="nm"><span>{w}</span>{#if id === now}<Icon name="check" />{/if}</span></button>{/each}</div>
