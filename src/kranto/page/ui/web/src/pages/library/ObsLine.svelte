<script lang="ts">
  // An observation as one line (the old page's obsLine): a hot mark when its signal is 0.3 or more
  // (the number is on its sheet:), the summary's first sentence, #id and kind, the source (a
  // link; Mute is on the observation's and the source's sheets), the age and ▲ ▼ (ui/Grade.svelte;
  // grade: the server's grade and the row's place in its list, none on Today's). Its title opens it
  // in the pane. A topic's Evidence and Overview and Today's topics draw these rows too.
  import Glyph from "../../ui/Glyph.svelte";
  import Grade from "../../ui/Grade.svelte";
  import Row from "../../ui/Row.svelte";
  import { ago, dt, firstSentence } from "../../lib/format";
  import { n2, obsHref, words, type ObsRow } from "./library";

  let { o, isNew = false, mute = false, tick = false, grade = null }: {
    o: ObsRow; isNew?: boolean; mute?: boolean; tick?: boolean; grade?: { current: unknown; position?: number | null } | null;
  } = $props();
</script>

{#snippet cluster()}{#if grade}<Grade target="observation" id={o.id} current={grade.current} what={"#" + o.id} context={grade.position != null ? { position: grade.position } : undefined} />{/if}{/snippet}

<Row title={firstSentence(o.summary) || o.title || "#" + o.id} href={obsHref(o.id)} meta={`#${o.id} ${words(o.kind)}`} hot={o.signal >= 0.3} asideText age={ago(dt(o.created_at))} {isNew} grade={cluster}>
  {#snippet st()}<Glyph name="dot" colour={isNew ? "blue" : "grey"} word={isNew ? "New since your last visit" : "Seen"} />{/snippet}
  {#snippet num()}{#if o.signal >= 0.3}<span class="hotmark" title={`signal ${n2(o.signal)}`} aria-label={`signal ${n2(o.signal)}`}>●</span>{/if}{/snippet}
  {#snippet aside()}{#if o.source_id}<a class="src" href={"#/settings/sources/" + o.source_id} title={(o.source_label || "") + ": this source's page"}>{o.source_label || "source"}</a>{:else}<span>{o.source_label || "imported"}</span>{/if}{/snippet}
</Row>
