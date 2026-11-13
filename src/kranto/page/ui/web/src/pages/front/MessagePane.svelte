<script lang="ts">
  // A message (a heartbeat, a strike, an alarm) in the pane: its kind and when, its body, the
  // observations it cites. On
  // Today (a message since the last visit, sel=m<id>) it says every message is kept under
  // Settings › System › Health; on Health (health: true) the delivery section follows the body.
  import type { Snippet } from "svelte";
  import Glyph from "../../ui/Glyph.svelte";
  import { dt, longTime, rel } from "../../lib/format";
  import { href } from "../../lib/router";
  import { obsHref } from "../library/library";
  import PaneTop from "./PaneTop.svelte";
  import Sec from "./Sec.svelte";
  import { msgMark, type Message } from "./needs";

  let { m, health = false, more }: { m: Message; health?: boolean; more?: Snippet } = $props();
  const mk = $derived(msgMark(m));
  const at = $derived(dt(m.created_at));
</script>

{#snippet kind()}<Glyph name={mk[0]} colour={mk[1]} word={mk[2]} />{` message · ${m.kind}`}{/snippet}
{#snippet when()}{#if at}<time title={longTime(at * 1000)}>{rel(at)}</time>{/if}{/snippet}

<div class="pane-in" data-title={m.title}><PaneTop {kind} title={m.title} lede={at ? when : null} /><Sec id="body" title="Message"><p class="prose">{m.body}</p></Sec>{#if m.evidence_ids.length}<Sec id="evidence" title="Evidence"><p>{#each m.evidence_ids as id, k (id)}{k ? " " : ""}<a class="mono" href={obsHref(id)}>{"#" + id}</a>{/each}</p></Sec>{/if}{@render more?.()}{#if !health}<p class="muted small mt">{"Every message is kept under "}<a href={href("settings/health", { message: m.id })}>Settings › System › Health</a>.</p>{/if}</div>
