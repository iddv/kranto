<script lang="ts">
  // A page's title, facts, lede and verbs: with the doors on, a declaration the
  // shell draws as the page's one head (shell/PageHead.svelte); the page draws nothing here. Without
  // them (brb alone, or a page drawn by itself in a test) the old list head: the title with its
  // muted words, one line of sub text, the primary beside the title.
  import Tip from "./Tip.svelte";
  import { ui } from "../lib/shell.svelte";
  import { declareHead, type HeadDecl } from "../lib/app/heads";

  let props: HeadDecl = $props();
  $effect(() => {
    if (!ui.headOn) return;
    return declareHead({ ...props });
  });
</script>

{#if !ui.headOn}<div class="lh"><div class="ph"><h1>{props.title}</h1>{#if props.about}<Tip id={props.about} about={props.title} />{/if}{#if props.facts}<span class="muted small">{props.facts}</span>{/if}{#if props.primary}{@const v = props.primary}{#if v.href}<a class={"btn sm" + (v.plain ? "" : " primary")} id={v.id || null} href={v.href}>{v.label}</a>{:else}<button type="button" class={"btn sm" + (v.plain ? "" : " primary")} id={v.id || null} title={v.title || null} disabled={v.disabled || null} onclick={(e) => v.run?.(e.currentTarget)}>{v.label}</button>{/if}{/if}</div>{#if props.lede}<p class="lsub" id={props.ledeId || null}>{props.lede}</p>{/if}{#if props.flash}<p class={"muted small flash-" + props.flash.kind}>{props.flash.text}</p>{/if}</div>{/if}
