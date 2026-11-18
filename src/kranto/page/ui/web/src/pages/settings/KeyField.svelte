<script lang="ts">
  // The watching model's form: one form, so a provider is chosen, tested and kept the same way on
  // Settings › Watching (its Watching model pane) and on onboarding's first step. Three choices, in the
  // order they are offered (MP D12): the Claude API (an Anthropic key), OpenRouter, another
  // OpenAI-compatible endpoint (its base URL written to llm.base_url when its key passes), then
  // Claude Code's login when the server offers it: never preselected, its terms sentence shown where
  // it is chosen (as the owner decided), no key, and the press says terms: true. The
  // press goes to the server's /api/setup/provider, which tests the key, keeps it in .env and makes
  // the choice the watcher's at once. The key is a secret the owner types: a password field, read
  // only at the press, sent once and cleared then, never kept in state or logged. A key already set
  // for the choice (in .env or the environment) can be chosen without pasting it. Tested on paste
  // too: a paste presses Test and save after a short pause, and so does a pause after
  // typing something key-length.
  import FLabel from "../../ui/FLabel.svelte";
  import { read } from "../../lib/reads.svelte";
  import { app } from "../../lib/shell.svelte";
  import { ApiError } from "../../api/client";
  import { ABOUT, CHOICES, type Choice, claudeWords, free, KEYBASE, KEYPROV, type KeyState, LABEL, PROVIDER_API, type ProviderSetup, providerOf } from "./keys.svelte";
  import { saidSaved } from "../../lib/words";

  // ``only``: Welcome's boxes draw the keys' form ("keys": the three keys, no
  // login) and the login's button ("login": Claude Code alone, no radios) apart; Settings › Watching
  // draws all four ("all")
  let { k, done, only = "all", lead = false }: { k: KeyState; done: boolean; only?: "all" | "keys" | "login"; lead?: boolean } = $props();
  let keyIn = $state<HTMLInputElement>();
  let save = $state<HTMLButtonElement>();
  let baseIn = $state<HTMLInputElement>();
  let testing = $state(false);
  const found = $derived(read<ProviderSetup>(PROVIDER_API, 10000).data);
  const now = $derived(providerOf(k));
  // Claude Code is listed only when the server offers it (or it is the watcher already)
  const choices = $derived(only === "keys" ? CHOICES.filter((c) => c !== "claude_code")
    : CHOICES.filter((c) => c !== "claude_code" || now === "claude_code" || !!found?.claude_code?.offered));
  const kept = $derived<Choice>(KEYPROV.v ?? ((CHOICES as readonly string[]).includes(now) ? (now as Choice) : "openrouter"));
  const pick = $derived<Choice>(only === "login" ? "claude_code" : only === "keys" && kept === "claude_code" ? "openrouter" : kept);
  const login = $derived(pick === "claude_code");
  // the choice's key is already set (the server found its variable): it can be chosen without a paste
  const setFor = $derived(pick !== "claude_code" && !!found?.[pick]?.key_set);
  const mine = $derived(pick === now && k.set);

  function press(btn: HTMLButtonElement): void {
    const L = app();
    if (!L || !keyIn) return;
    const v = login ? "" : keyIn.value.trim();
    if (!v && !setFor && !login) {
      // fix 11: Test and save with nothing typed said nothing
      L.say("Paste a key first.", "amber");
      keyIn.focus();
      return;
    }
    const chose = pick, was = now;
    const body: Record<string, unknown> = { provider: chose, replace: done, ...(v ? { key: v } : {}), ...(chose === "claude_code" ? { terms: true } : {}) };
    if (chose === "openai_compat") body.base_url = (baseIn?.value || "").trim();
    keyIn.value = "";
    testing = true;
    let refused = "";
    void L.act(btn, async () => {
      try {
        return await L.api(PROVIDER_API, body);
      } catch (e) {
        // the provider refused what was typed (a 4xx): the person's key, not Kranto's fault, so no
        // Tell us (10, Gemini 13: "openrouter.ai refused the key (HTTP 401) · Tell us")
        if (e instanceof ApiError && e.status < 500) {
          refused = e.message;
          return null;
        }
        throw e;
      } finally {
        L.afkDrop();
      }
    }, (x) => {
      if (!x) {
        L.say(`${refused.replace(/\.$/, "")}. Check the key, or make a new one, and try again.`, "amber");
        return;
      }
      const r = x as { test: { detail: string }; models?: { judge: string; reason: string } | null };
      KEYBASE.v = null;
      KEYPROV.v = null;
      const m = r.models && chose !== was ? ` Watching with ${LABEL[chose]}: judge ${r.models.judge}, reason ${r.models.reason}.` : "";
      L.say(saidSaved(r.test.detail, "now") + m + (v ? " The key is kept in this workspace's .env (readable by you only), never in a page or your settings." : ""));
    }).finally(() => {
      testing = false;
      free(btn);
    });
  }
  // the key is read from the field only at the press, as above: nothing here keeps, shows or logs it
  let soon: ReturnType<typeof setTimeout> | undefined;
  function testSoon(ms: number): void {
    clearTimeout(soon);
    soon = setTimeout(() => {
      if (keyIn?.isConnected && keyIn.value.trim().length >= 12 && save && !save.disabled) save.click();
    }, ms);
  }
  function typed(e: Event): void {
    if ((e as InputEvent).inputType !== "insertFromPaste") testSoon(1200);
  }
  function keydown(e: KeyboardEvent): void {
    if (e.key !== "Enter") return;
    e.preventDefault();
    save?.click();
  }
</script>

<div class="field">{#if only !== "login"}<div class="inline"><FLabel forId="model-key" text={login ? "Login" : mine ? "Replace the key" : "Key"} tipId="keys.model" /><span role="radiogroup" aria-label="Watching model" class="small radios" style="margin-left:1.5em">{#each choices as c (c)}<label style="margin-right:1em"><input type="radio" name="watch-provider" id={"watch-" + c} value={c} checked={pick === c} onchange={() => { KEYPROV.v = c; }} />{" " + LABEL[c] + (c === now ? " (now)" : "")}</label>{/each}</span></div>{/if}
  {#if login && only === "login"}{#if found?.claude_code}<p class="muted small" id="watch-claude">{claudeWords(found.claude_code)}</p>{/if}{:else if login}<p class="small" id="watch-about">{found?.claude_code?.terms || ABOUT.claude_code}</p>{#if found?.claude_code}<p class="muted small" id="watch-claude">{claudeWords(found.claude_code)}</p>{/if}{:else if ABOUT[pick]}<p class="muted small" id="watch-about">{ABOUT[pick]}</p>{/if}
  {#if pick === "openai_compat"}<div class="field mt"><FLabel forId="model-base" text="Its address" hint="The service's address (one that speaks OpenAI's API). It is kept in your settings when its key passes." /><input id="model-base" style="width:min(100%,460px)" value={KEYBASE.v == null ? k.base_url : KEYBASE.v} bind:this={baseIn} oninput={(e) => { KEYBASE.v = e.currentTarget.value; }} /></div>{/if}
  <div class="inline">{#if login}<button class={"btn" + ((only === "login" ? lead : !mine) ? " primary" : "")} id="key-save" bind:this={save} onclick={(e) => press(e.currentTarget)}>{testing ? "Testing…" : mine ? "Check my Claude Code login" : "Use my Claude Code login"}</button><input id="model-key" type="hidden" bind:this={keyIn} />{:else}<input id="model-key" type="password" autocomplete="off" spellcheck="false" aria-label="Model key" style="width:min(100%,460px)"
  placeholder={mine ? "set: paste a new key to replace it" : setFor ? "found in .env or the environment: click to use it, or paste another" : "paste your key"} bind:this={keyIn} onkeydown={keydown} onpaste={() => testSoon(300)}
  oninput={typed} /><button class={"btn" + (mine ? "" : " primary")} id="key-save" bind:this={save} onclick={(e) => press(e.currentTarget)}>{testing ? "Testing…" : mine ? "Test and replace" : setFor && pick !== now ? "Test and use" : "Test and save"}</button>{/if}</div></div>
