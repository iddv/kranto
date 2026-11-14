<script lang="ts">
  import { pageUrl } from "../../lib/base";
  // First-run setup (#/welcome, PLAN.md section 1.5;): the mark and
  // the steps line, then the step the route names: Model (welcome: the ways in), First topic
  // (welcome/topics: Add topic), Ready (welcome/finish: the first brief, the cost, the console,
  // usage reports, Start reading) and How you write (welcome/voice: the screen Start reading
  // opens, while kranto reads; skippable). A stage route: drawn without the panes.
  import NeedHost from "../../ui/NeedHost.svelte";
  import Icon from "../../shell/Icon.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { ui } from "../../lib/shell.svelte";
  import AddTopic from "./AddTopic.svelte";
  import FinishStep from "./FinishStep.svelte";
  import HowYouWrite from "./HowYouWrite.svelte";
  import KeysStep from "./KeysStep.svelte";
  import { read } from "../../lib/reads.svelte";
  import { SETUP_API, type Setup } from "../settings/keys.svelte";
  import { stepAt, stepDone, stepsNow } from "./welcome.svelte";

  let { view }: { view: View } = $props();
  const host = $derived(!!ui.facts?.header.host);
  const steps = $derived.by(() => {
    void view.tick;
    return stepsNow();
  });
  const at = $derived(stepAt(view.w.r.path[1]));
  const key = $derived(steps[at]?.[0] ?? "");
  const setup = $derived.by(() => {
    void view.tick;
    return host ? read<Setup>(SETUP_API, 15000).data : null;
  });
</script>

<div data-title="Welcome">
  {#if !host}
    <NeedHost what="Setup" verb="needs" />
  {:else}
    <div class="welcome-head narrow"><p class="crumb steps-line">{"Welcome · "}{#each steps as [k, w], i (k)}{i ? " · " : ""}{#if i === at}<strong>{`Step ${i + 1} of ${steps.length}: ${w}`}</strong>{:else}<a href={"#/welcome" + (k ? "/" + k : "")}>{w}{#if stepDone(i, setup)}<Icon name="check" cls="done" />{/if}</a>{/if}{/each}</p></div>
    {#if key === "topics"}<AddTopic {view} mode="welcome" />{:else if key === "finish"}<FinishStep {view} />{:else if key === "voice"}<HowYouWrite {view} />{:else}<KeysStep {view} />{/if}
  {/if}
</div>
