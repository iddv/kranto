<script lang="ts">
  // The phone's bar at the bottom with the doors on (HIG Tab bars): News · Ideas
  // · Watch · Post, one tap to a door from any depth, and ✦ the console as the fifth item. The home
  // is Kranto in the top bar; Needs you is the home's one thing and ⌘K's; Settings the gear. Links,
  // one per door, never tabs inside a page. Drawn on a phone only (base.css), in place of the
  // status bar.
  import { ui } from "../lib/shell.svelte";
  import { consoleUi, setPlace } from "../term/console.svelte";
  import { DOORS, DOOR_GLYPH } from "./doors";
  import { keyLabel } from "../lib/keys";

  const here = $derived.by(() => {
    void ui.drawn;
    return ui.facts?.door?.id ?? null;
  });
  const open = $derived(consoleUi.place === "open");
</script>

<nav id="tabbar" aria-label="Doors">{#each DOORS as [id, w, to] (id)}<a href={to} id={"tab-" + id} aria-current={here === id ? "page" : null}><span class="g" aria-hidden="true">{DOOR_GLYPH[id]}</span><span class="w">{w}</span></a>{/each}<button type="button" id="tab-console" aria-label={open ? "Close the console" : "Open the console"} aria-pressed={open ? "true" : "false"} title={`The console (${keyLabel("⌘J")})`} onclick={() => setPlace(open ? "min" : "open")}><span class="g" aria-hidden="true">✦</span><span class="w">Console</span></button></nav>
