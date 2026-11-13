<script lang="ts">
  // The list's head: the page-wide lines at the list's top. Paused; not
  // signed in (OI: the page reads, but every press is refused until this browser has the
  // session cookie; the code `kranto open` prints works here too); the flash (a press's answer,
  // 8 s, or while its Undo is offered; a red one offers Tell us: Feedback, prefilled with it). Svelte keeps a half-typed code and a focused ? in place.
  // Above them, only when the server answers another API version than this page was built for
  // (lib/hostapi.ts): one line asking to update both.
  import Icon from "./Icon.svelte";
  import Tip from "../ui/Tip.svelte";
  import { tellUs } from "../ui/sendFeedback";
  import type { HeadFacts } from "../lib/app";
  import { hostApiLine } from "../lib/hostapi";
  import { app, ui } from "../lib/shell.svelte";

  const hd = $derived(ui.facts?.head);
  // the app reads /api/status and draws; the facts are new after every draw
  const apiLine = $derived.by(() => (ui.facts ? hostApiLine(app()?.host?.() as Record<string, unknown> | null) : null));
  // with the doors on, the sign-in line is said once: on the first page this tab opened, until
  // dismissed (HIG Alerts: a nonintrusive label, not a banner on every page). The
  // page stores nothing, so a new tab says it again; a refused press says so in its own flash.
  const doors = $derived(ui.drawn >= 0 && document.body.classList.contains("doors"));
  let first: string | null = null; // the first page drawn, after its redirects
  let dismissed = $state(false);
  const gone = $derived.by(() => {
    if (ui.drawn < 0 || !ui.facts) return false;
    const page = location.hash.split("?")[0] || ""; // a sheet opened on it is the same page
    first ??= page;
    return dismissed || page !== first;
  });
  function dismiss(): void {
    dismissed = true;
  }
  let code = $state("");
  let input = $state<HTMLInputElement>();

  function pausedText(_p: NonNullable<HeadFacts["paused"]>): string {
    return "No source is read and no idea written until you choose Resume.";
  }
  function send(btn: HTMLElement): void {
    if (!code.trim()) {
      input?.focus();
      return;
    }
    void app()?.signIn(code.trim(), btn);
  }
</script>

<div id="list-h">{#if apiLine}<div class="flash amber" role="status" id="host-api"><Icon name="warn" /><div>{apiLine}</div></div>{/if}{#if hd?.paused && !hd.flash?.text.startsWith("Paused")}<div class="flash amber" role="status"><Icon name="held" /><div><strong>Paused.</strong>{" " + pausedText(hd.paused)}</div></div>{/if}{#if hd?.signin && !(doors && gone)}<div class="flash amber line" role="status" id="signin"><Icon name="warn" /><div class="grow"><strong>Not signed in:</strong> this browser can look, not act.</div><input id="signin-code" type="text" autocomplete="off" spellcheck="false" placeholder="code from kranto open" aria-label="Sign-in code" style="max-width:16em" bind:value={code} bind:this={input} onkeydown={(e) => { if (e.key === "Enter") send(e.currentTarget.nextElementSibling as HTMLElement); }} /><button type="button" class="btn sm primary" id="signin-go" onclick={(e) => send(e.currentTarget)}>Sign in</button><Tip id="signin" about="signing in" />{#if doors}<button type="button" class="linkish" id="signin-x" aria-label="Dismiss the sign-in line for this session" title="Dismiss for this session" onclick={dismiss}>✕</button>{/if}</div>{/if}{#if hd?.flash && !ui.sheet}{@const f = hd.flash}<div class={"flash " + f.kind} role="status"><Icon name={f.kind === "red" ? "x" : f.kind === "amber" ? "warn" : "check"} /><div class="grow">{f.text}{#if f.undo}{@const u = f.undo}{" · "}<button type="button" class="linkish" id="undo" onclick={(e) => u.run(e.currentTarget)}>Undo</button>{/if}{#if f.kind === "red"}{" · "}<button type="button" class="linkish" id="flash-tell" title="Send feedback about this, with these words in it" onclick={() => tellUs(f.text)}>Tell us</button>{/if}</div></div>{/if}</div>
