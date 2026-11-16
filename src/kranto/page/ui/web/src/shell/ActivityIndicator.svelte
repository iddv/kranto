<script lang="ts">
  // The top bar's one quiet item (the owner's D-2), in place of the two lane
  // words, in both layouts and on the phone: a green dot and "Quiet · next: reading your sources
  // at 20:23"; a spinning ring, the count and the first run's words while something runs (steady
  // under reduced motion); "Paused" in amber; a red dot and "1 failed" until Activity is opened.
  // the word alone in the bar ("Quiet", "2 running", "Paused", "1 failed");
  // the rest ("next: reading your sources at 20:23") is its tooltip and Activity's.
  // It opens Activity (#/activity, g a). Drawn from api/activity, and from the lanes' own facts
  // until that read arrives (an older server has none), so it never says less than they did.
  import Mark from "./Mark.svelte";
  import type { Activity } from "../api/types.gen";
  import { ACT_PATH, indicator, seenAt, type LaneFacts } from "../lib/activity";
  import { read } from "../lib/reads.svelte";

  let { lanes, tick = 0 }: { lanes: LaneFacts; tick?: number } = $props();
  const r = $derived.by(() => {
    void tick;
    return read<Activity>(ACT_PATH, 5000);
  });
  const ind = $derived(indicator(r.data, lanes, seenAt()));
  const mark = $derived(
    ind.state === "running" ? { name: "running", colour: "blue" }
      : ind.state === "paused" ? { name: "held", colour: "amber" }
      : ind.state === "failed" ? { name: "x", colour: "red" }
      : { name: "waiting", colour: "green" },
  );
</script>

<a class="hd-st" id="hd-activity" href="#/activity" title={ind.title} data-state={ind.state} aria-label={`${ind.word}${ind.detail ? ", " + ind.detail : ""}. What Kranto is doing`}>
  <Mark name={mark.name} colour={mark.colour} word={ind.word} />
</a>

