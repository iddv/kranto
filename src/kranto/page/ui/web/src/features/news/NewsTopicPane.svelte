<script lang="ts">
  // News › Topics, a topic's sheet (sel=t<id>): News on or off for it, how often and at what hour
  // (each change one write, as the row's switch is), and Brief now (it spends: it asks first).
  // With nothing chosen, what the page is for.
  import Detail from "../../ui/Detail.svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import Loading from "../../ui/Loading.svelte";
  import Pane from "../../ui/Pane.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import { ui } from "../../lib/shell.svelte";
  import { ROWS, TOPIC_SEL, briefHref, briefNow, cadenceWords, newsSet, type NewsSetting, type TopicRows } from "./news";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const sel = $derived(view.w.r.sel || "");
  const tid = $derived(sel.startsWith(TOPIC_SEL) ? Number(sel.slice(TOPIC_SEL.length)) : null);
  const rows = $derived.by(() => {
    void view.tick;
    return host && tid != null ? read<TopicRows>(ROWS, 30000) : null;
  });
  const t = $derived(rows?.data?.topics.find((x) => x.id === tid) || null);
  const HOURS = Array.from({ length: 24 }, (_, h) => h);
  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
</script>

<Detail back={view.back}>
  {#if tid == null}
    <div class="pane-empty"><p class="empty">Nothing selected.</p></div>
  {:else if !t}
    <div class="pane-in"><Loading error={rows?.error} /></div>
  {:else}
    {@const on = t.news.enabled}
    <Pane title={`News for ${t.name}`} lede={on ? `${cadenceWords(t.news)}${t.next_due ? ", the next at " + t.next_due.slice(0, 16).replace("T", " ") : ""}.` : "Off: no brief is written for this topic."}>
      {#snippet kind()}<Glyph name={on ? "check" : "dot"} colour={on ? "green" : "grey"} word={on ? "on" : "off"} />{" news · a topic"}{/snippet}
      {#snippet acts()}<button type="button" class="btn sm sw" role="switch" id="nt-switch" aria-checked={on ? "true" : "false"} onclick={(e) => newsSet(e.currentTarget, t, !on)}>{on ? "On" : "Off"}</button>{#if on}<button type="button" class="btn sm" id="nt-brief-now" disabled={t.running} title={t.running ? "A brief is being written" : "Write this topic's brief now (it spends)"} onclick={(e) => briefNow(e.currentTarget, t)}>Brief now</button>{/if}{/snippet}
      {#snippet top()}
        {#if on}
          <div class="field"><label for="nt-cadence">How often</label><select id="nt-cadence" value={t.news.cadence} onchange={(e) => newsSet(e.currentTarget, t, true, { cadence: e.currentTarget.value as NewsSetting["cadence"] })}><option value="daily">daily</option><option value="weekdays">weekdays</option><option value="weekly">weekly</option></select></div>
          {#if t.news.cadence === "weekly"}<div class="field"><label for="nt-day">On</label><select id="nt-day" value={String(t.news.weekday)} onchange={(e) => newsSet(e.currentTarget, t, true, { weekday: Number(e.currentTarget.value) })}>{#each DAYS as w, i (w)}<option value={String(i)}>{w}</option>{/each}</select></div>{/if}
          <div class="field"><label for="nt-hour">At</label><select id="nt-hour" value={String(t.news.hour)} onchange={(e) => newsSet(e.currentTarget, t, true, { hour: Number(e.currentTarget.value) })}>{#each HOURS as h (h)}<option value={String(h)}>{String(h).padStart(2, "0") + ":00"}</option>{/each}</select></div>
        {/if}
        {#if t.last}<p class="small mt">The last brief: <a href={briefHref(t.last.id)}>{`${t.last.created_at.slice(0, 10)}, ${t.last.items} item${t.last.items === 1 ? "" : "s"} (${t.last.status})`}</a></p>{/if}
        <p class="muted small mt">Every topic's defaults (the hour, how often, the model) are on Settings › News.</p>
      {/snippet}
    </Pane>
  {/if}
</Detail>
