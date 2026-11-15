<script lang="ts">
  // The command palette (⌘K, UI-v4.md 2.4): one input; results grouped Ideas · Evidence · Sources
  // · Topics · Commands, the group with the best match first and its first result selected. The
  // ideas, topics and commands come from the app's palItems; the evidence and the sources from
  // the server's /api/search (words and meaning), asked a moment after the typing stops, ranking
  // half a step under the page's own match so the groups shown do not jump. enter opens; ⌘enter
  // runs the row's primary action; esc closes, typed text or not.
  import { palGroups, palKey, type PalItem } from "../lib/palette";
  import { app, ui } from "../lib/shell.svelte";

  let d = $state<HTMLDialogElement>();
  let input = $state<HTMLInputElement>();
  let q = $state("");
  let sel = $state<string | null>(null);
  let srv = $state.raw<{ query: string; results: unknown[] } | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  const host = $derived(!!ui.facts?.header.host);
  // with the doors on (HIG Searching: show the scope): chips narrow the results,
  // and the box says what it searches on the door it was opened from
  const doors = $derived(ui.drawn >= 0 && document.body.classList.contains("doors"));
  const SCOPES: Record<string, string[]> = { All: [], Ideas: ["Ideas"], Evidence: ["Evidence", "Topics"], Sources: ["Sources"], Settings: ["Settings", "Go to"] };
  let scope = $state("All");
  const PLACE: Record<string, string> = { watch: "Search evidence, sources, topics, or a command", ideas: "Search ideas, or a command",
    settings: "Search settings by name or key, or a command" };
  const place = $derived((doors && PLACE[ui.facts?.door?.id || ""]) || "Search ideas, evidence, sources, topics, or a command");
  const all = $derived(ui.palette === null ? [] : palGroups(app()?.palItems(q, srv) || [], q));
  const groups = $derived(!doors || scope === "All" ? all : all.filter(([g]) => (SCOPES[scope] || []).includes(g)));
  const flat = $derived(groups.flatMap((g) => g[1]));
  const cur = $derived(flat.some((x) => palKey(x) === sel) ? sel : flat.length ? palKey(flat[0] as PalItem) : null);
  const waiting = $derived(host && q.trim().length >= 2 && !(srv && srv.query === q.trim()));
  const curId = $derived.by(() => {
    const i = flat.findIndex((x) => palKey(x) === cur);
    return i >= 0 ? "pal-" + i : "";
  });

  $effect(() => {
    if (ui.palette === null || !d || d.open) return;
    q = ui.palette.text;
    scope = "All";
    sel = null;
    srv = null;
    d.showModal();
    input?.focus();
    ask();
  });
  $effect(() => {
    if (!curId || !d?.open) return;
    const el = document.getElementById(curId);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  });

  function ask(): void {
    clearTimeout(timer);
    const want = q.trim();
    if (!host || want.length < 2) return;
    timer = setTimeout(() => {
      app()
        ?.api("/api/search?q=" + encodeURIComponent(want))
        .then((r) => {
          // the answer is for what was asked, whatever it echoes (an older server echoes none)
          const res = (r as { results?: unknown } | null)?.results;
          if (ui.palette !== null && q.trim() === want) srv = { query: want, results: Array.isArray(res) ? res : [] };
        })
        .catch(() => {
          if (ui.palette !== null && q.trim() === want) srv = { query: want, results: [] };
        });
    }, 180);
  }
  // closed now, and its field lets go of the focus now too: the dialog's close event (which
  // removes the field) comes a moment later, and a key pressed before it would read as typing
  function shut(): void {
    input?.blur();
    d?.close();
  }
  function choose(x: PalItem, primary: boolean): void {
    shut();
    if (primary && x.act) x.act();
    else if (x.go) location.hash = x.go;
    else if (x.run) x.run();
  }
  function keys(e: KeyboardEvent): void {
    const at = flat.findIndex((x) => palKey(x) === cur);
    const move = (n: number) => {
      if (!flat.length) return;
      sel = palKey(flat[(at + n + flat.length) % flat.length] as PalItem);
      e.preventDefault();
    };
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) move(1);
    else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) move(-1);
    else if (e.key === "Enter" && at >= 0) {
      e.preventDefault();
      choose(flat[at] as PalItem, e.metaKey || e.ctrlKey);
    } else if (e.key === "Escape") {
      e.preventDefault();
      shut();
    }
  }
  // the close event comes a moment later: ⌘K pressed again before it arrives has opened a new
  // palette, which the old close must not clear
  function closed(): void {
    if (d?.open) return;
    ui.palette = null;
    clearTimeout(timer);
  }
</script>

<!-- a click on the backdrop closes it; the keys are the input's (a combobox) -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<dialog id="pal" class="pal" aria-label="Search and commands" bind:this={d} onclose={closed} onclick={(e) => { if (e.target === d) shut(); }}>{#if ui.palette !== null}<input type="text" id="pal-q" placeholder={place} aria-label="Search and commands" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={curId} bind:this={input} bind:value={q} oninput={() => { sel = null; ask(); }} onkeydown={keys} />{#if doors}<div class="pal-scope" role="group" aria-label="Search in">{#each Object.keys(SCOPES) as s (s)}<button type="button" class="chip" aria-pressed={scope === s ? "true" : "false"} onclick={() => { scope = s; sel = null; input?.focus(); }}>{s}</button>{/each}</div>{/if}<ul id="pal-list" role="listbox" aria-label="Results">{#each groups as [g, xs] (g)}<li role="presentation"><h3>{g}</h3><ul role="group" aria-label={g}>{#each xs as x, i (i)}<!-- svelte-ignore a11y_click_events_have_key_events --><li role="option" id={"pal-" + flat.indexOf(x)} aria-selected={palKey(x) === cur ? "true" : "false"} class={palKey(x) === cur ? "sel" : null} onclick={(e) => choose(x, e.metaKey || e.ctrlKey)} onmousemove={() => { if (cur !== palKey(x)) sel = palKey(x); }}><span class="t">{x.title}</span>{#if x.detail}<span class="w">{x.detail}</span>{/if}{#if x.keys || (x.act && palKey(x) === cur)}<span class="k">{#if x.keys}{#each x.keys.split(" ") as k, i (i)}{i ? " " : ""}<kbd>{k}</kbd>{/each}{:else}<kbd>⌘enter</kbd>{" " + x.actWord}{/if}</span>{/if}</li>{/each}</ul></li>{/each}{#if !flat.length}<li class="empty">{waiting ? "Searching…" : `Nothing matches "${q.trim()}".`}</li>{/if}{#if waiting && flat.length}<li class="muted small pal-wait">Searching evidence and sources…</li>{/if}</ul><div class="pal-f"><kbd>↑</kbd> <kbd>↓</kbd> move · <kbd>enter</kbd> open · <kbd>⌘enter</kbd> the row's action · <kbd>esc</kbd> close</div>{/if}</dialog>
