<script lang="ts">
  // A state: always an icon and a colour, and usually a word (the old page's mark()).
  import Icon from "./Icon.svelte";

  let { name, colour, word = null }: { name: string; colour: string; word?: string | null } = $props();
</script>

<span class={"st c-" + colour}><Icon {name} cls={name === "running" ? "spin" : ""} />{#if word}<span>{word}</span>{/if}</span>
