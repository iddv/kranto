<script lang="ts">
  // PROSE's flags: what reads like AI, underlined in the text with its plain
  // fix, and one line, "Reads natural" or "2 things read like AI", with Fix them when fix is
  // given (the editor's: revise puts the new words in the box, kept only on Save). Read-only on a
  // draft's page; the editor hosts it under its box and checks again as the owner types.
  import { checkProse, lineOf, reviseProse, spans, type ProseCheck } from "./prose";

  // parts: a thread's posts (the text is them joined), so the site's limit is each post's
  let { text, site, fix = null, id = "prose-flags", sources = null, parts = null }: { text: string; site: string; fix?: ((text: string, say: string) => void) | null; id?: string; sources?: string | null; parts?: string[] | null } = $props();
  let got = $state<ProseCheck | null>(null);
  let fixing = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  $effect(() => {
    const t = text, s = site, src = sources, ps = parts ? [...parts] : null;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void checkProse(t, s, src, ps).then((c) => { if (t === text) got = c; }), fix ? 500 : 0);
    return () => { if (timer) clearTimeout(timer); };
  });
  const marks = $derived(got ? spans(text, got.flags) : []);
  const whole = $derived(got ? got.flags.filter((f) => f.scope === "text") : []);
  async function fixThem(): Promise<void> {
    if (!got || !fix) return;
    fixing = true;
    const r = await reviseProse(text, site, got.flags);
    fixing = false;
    if (r) fix(r.text, r.flags.length ? `${lineOf({ ...r, flags: r.flags })} still.` : "Fixed: it reads natural now.");
  }
</script>

{#if got}
  <div class="prose-flags" {id} data-flags={String(got.flags.length)}>
    <p class="pf-line small"><span class={got.flags.length ? "pf-warn" : "pf-ok"}>{lineOf(got)}</span>{#if got.flags.length && fix}{" "}<button type="button" class="btn sm" id={id + "-fix"} disabled={fixing} onclick={() => void fixThem()}>{fixing ? "Fixing…" : "Fix them"}</button>{/if}</p>
    {#if got.flags.length}
      <div class="pf-text small" aria-label="The text, with what reads like AI underlined">{#each marks as m, i (i)}{#if m.f}<mark class="pf-mark" title={m.f.fix} data-rule={m.f.rule}>{m.t}</mark>{:else}{m.t}{/if}{/each}</div>
      <ul class="pf-fixes small">{#each got.flags.filter((f) => f.scope !== "text").slice(0, 6) as f, i (i)}<li><q>{f.text.length > 60 ? f.text.slice(0, 59) + "…" : f.text}</q>{" · "}{#if f.rule.startsWith("salt.")}{f.words}{" · "}{/if}{f.fix}</li>{/each}{#each whole as f, i (i)}<li>{f.words}{" · "}{f.fix}</li>{/each}</ul>
    {/if}
  </div>
{/if}

<style>
  .pf-line { margin: 6px 0; }
  .pf-ok { color: var(--green, var(--ink2)); }
  .pf-warn { color: var(--amber, var(--ink)); }
  .pf-text { white-space: pre-wrap; max-height: 9em; overflow: auto; border-left: 2px solid var(--border); padding-left: 8px; color: var(--ink2); }
  .pf-mark { background: none; color: inherit; text-decoration: underline wavy var(--amber); text-underline-offset: 3px; }
  .pf-fixes { margin: 4px 0; padding-left: 18px; color: var(--ink2); }
</style>
