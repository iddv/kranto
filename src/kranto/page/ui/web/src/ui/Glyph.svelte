<script lang="ts">
  // A row's state: an icon in a colour, its word in its label and tooltip (the old page's glyph()).
  // A Settings status word (ui/settings.ts) is drawn with its one glyph and colour whatever the
  // caller passed (UP #10: one glyph per word, everywhere); on Settings' pages the word is shown
  // beside it too (ui.area); a row's narrow state cell leaves that to the row's stw. say: the word
  // is drawn too (a row of Needs you and the home says its state in a word,).
  import Icon from "../shell/Icon.svelte";
  import { ui } from "../lib/shell.svelte";
  import { stOfWord } from "./settings";

  let { name, colour, word, say = false }: { name: string; colour: string; word: string; say?: boolean } = $props();
  const canon = $derived(stOfWord(word));
  const icon = $derived(canon ? canon[0] : name);
  const tone = $derived(canon ? canon[1] : colour);
</script>

<span class={"gl c-" + tone} role="img" title={word} aria-label={word}><Icon name={icon} cls={icon === "running" ? "spin" : ""} />{#if say || ui.area === "settings"}<span class="gl-w" aria-hidden="true">{word}</span>{/if}</span>
