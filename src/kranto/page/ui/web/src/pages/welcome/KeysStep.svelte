<script lang="ts">
  // Onboarding's first step (#/welcome; mock `welcome`): "Which model reads for
  // you?", the ways in as boxes, each with one button, in WAYS' order. A model key opens Settings ›
  // Watching's own form (KeyField, the three keys), so a key is tested and kept the same way in both
  // places; Your Claude Code login is one deliberate press with Anthropic's terms sentence in view
  // (as the owner decided), never preselected; found or not, it says how. The first way's button is the
  // page's one primary until a model is chosen; then Continue is. The usage question is Ready's.
  import Loading from "../../ui/Loading.svelte";
  import Mark from "../../shell/Mark.svelte";
  import type { View } from "../../lib/pages.svelte";
  import { read } from "../../lib/reads.svelte";
  import KeyField from "../settings/KeyField.svelte";
  import { keyWords, PROVIDER_API, SETUP_API, type ProviderSetup, type Setup } from "../settings/keys.svelte";
  import { CONSOLE_INSTALL, WAYS } from "./welcome.svelte";
  import { Product } from "../../lib/product";

  let { view }: { view: View } = $props();
  const c = $derived.by(() => {
    void view.tick; // each draw may find the read stale
    return read<Setup>(SETUP_API, 10000);
  });
  const s = $derived(c.data);
  const found = $derived(read<ProviderSetup>(PROVIDER_API, 10000).data);
  const cc = $derived(found?.claude_code || null);
  // "Found on this machine, signed in" only when it is: the server offers the login wherever it
  // could be chosen, which says nothing about this machine
  const offered = $derived(!!cc?.offered && !!cc?.installed && (!!cc?.logged_in || !!cc?.token_in_service));
  let pasting = $state(false);
  function onward(e: MouseEvent): void {
    if (!s?.key.set) e.preventDefault();
  }
  const TERMS = "Anthropic's terms describe a subscription login as meant for your own, individual use.";
</script>

{#snippet keyBox(first: boolean)}
  <section class="box way" id="way-key"><div class="box-h"><h2>A model key</h2></div><div class="box-b">
    <p>From Anthropic, OpenRouter or another service, which bills you at its own prices (Spend shows what it costs). The key is tested before it is kept; the test is free.</p>
    {#if pasting}<KeyField k={s!.key} done={s!.done} only="keys" />{:else}<button type="button" class={"btn" + (first && !s?.key.set ? " primary" : "")} id="way-key-open" onclick={() => (pasting = true)}>Paste a key</button>{/if}
  </div></section>
{/snippet}
{#snippet loginBox(first: boolean)}
  <section class="box way" id="way-login"><div class="box-h"><h2>Your Claude Code login</h2></div><div class="box-b">
    {#if offered}<p>Found on this machine, signed in. No key to paste. It uses your Claude plan, shared with your own Claude Code; the first read takes longer this way. {TERMS}</p>
      <KeyField k={s!.key} done={s!.done} only="login" lead={first && !s?.key.set} />
    {:else}<p>{cc && cc.installed ? "Claude Code is on this machine but not signed in: run claude once to sign in, then reload this page." : "Not found on this machine. With Claude Code installed and signed in, it can read for you with no key:"}</p>{#if !cc || !cc.installed}<pre class="small"><code>{CONSOLE_INSTALL}</code></pre>{/if}<p class="muted small">{TERMS}</p>{/if}
  </div></section>
{/snippet}

{#if !s}
  <Loading error={c.error} />
{:else}
  {@const k = s.key}
  {@const kw = keyWords(k)}
  <div class="narrow"><div class="ph"><h1>Which model reads for you?</h1></div><p class="ph-meta">{`${Product} reads nothing until a model is chosen. Choose one way in.`}</p>
    {#if k.set}<p class="way-now" id="way-now"><Mark name={kw.st[0]} colour={kw.st[1]} word={kw.st[2]} />{" " + kw.line}</p>{/if}
    {#each WAYS as w, i (w)}{#if w === "login"}{@render loginBox(i === 0 && offered)}{:else}{@render keyBox(i === 0 || (WAYS[0] === "login" && !offered))}{/if}{/each}
    <div class="inline wizard-foot"><span class="grow"></span>{#if !k.set}<span class="muted small">Continue needs a model that works.</span>{/if}<a class={"btn" + (k.set ? " primary" : "")} id="continue" href="#/welcome/topics" aria-disabled={k.set ? null : "true"} onclick={onward}>Continue</a></div>
  </div>
{/if}
