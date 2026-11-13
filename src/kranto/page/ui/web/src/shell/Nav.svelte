<script lang="ts">
  // The navigator (WORKSPACE.md 1.3): one tree, never tabs, drawn from the app's
  // navTree() (lib/app/chrome.ts). A "g x" key is in the entry's tooltip,
  // the ? sheet and the palette, never beside it. An open topic or the library is not itself the
  // current entry: its first page is. Under 1180 px the tree is a drawer under the top bar (☰),
  // closed by a choice, esc, or the scrim. As icons: 56 px, one glyph an
  // entry with its count as a badge and its words in its label and tooltip; a topic is a letter
  // in a circle; the group headings are rules; Settings is one gear. ‹ at its top, enter on its
  // splitter, ⌘K, or a drag under the least width; kept in kranto.layout.
  import Icon from "./Icon.svelte";
  import type { NavRow } from "../lib/app";
  import { navIcons, navToggle, ui } from "../lib/shell.svelte";

  const t = $derived(ui.facts?.nav);
  const icons = $derived(ui.icons);
  const TOPIC = /^topics\/[^/]+$/;
  const ICONS: Record<string, string> = {
    review: "check", library: "book", ideas: "open", settings: "gear",
    // the tree's doors' addresses
    needs: "today", "ideas/review": "check", "watch/evidence": "book",
  };
  const on = (x: NavRow) => !!t && !x.fold && t.here === x.to && !(x.twist && x.open);
  const within = (x: NavRow) => !!t && !!x.twist && !!x.open && (t.here === x.to || t.here.startsWith(x.to + "/"));
  const cls = (x: NavRow) =>
    "ni" + (x.sub ? " sub" : "") + (x.deep ? " deep" : "") + (x.fold ? " ptop" : "") + (on(x) ? " on" : "") + (within(x) ? " parent-on" : "") + (/^settings\/./.test(x.to) ? " setx" : "");
  const named = (x: NavRow) => (x.to === "settings" ? "Settings" : x.w);
  const title = (x: NavRow) =>
    icons ? [named(x), x.n ? String(x.n) : null, x.key].filter(Boolean).join(" · ") : x.key ? `${x.w} (${x.key})` : null;
  const count = (x: NavRow) => "ct" + (x.hot ? " hot" : x.tone ? " " + x.tone : "");
</script>

<div class="ntog"><button type="button" id="nav-icons" aria-label={icons ? "Show the navigator's words" : "Collapse the navigator to icons"} title={icons ? "Expand the navigator" : "Collapse to icons"} aria-pressed={icons ? "true" : "false"} onclick={() => navIcons(!icons)}>{icons ? "›" : "‹"}</button></div>
{#if t}
  {#each t.rows as x, i (i)}
    {#if x.head}
      <div class="ng">{#if x.to}<a href={"#/" + x.to} aria-current={t.here === x.to ? "page" : null}>{x.head}</a>{:else}<span>{x.head}</span>{/if}{#if x.n}<span class={count(x)} title={x.to === "cubs" ? "Waiting for your approval" : null}>{String(x.n)}</span>{/if}{#if x.add}<a class="add" href={"#/" + x.add} title="Add a topic" aria-current={t.here === x.add ? "page" : null}>+ add</a>{/if}</div>
    {:else}
      <div class={cls(x)}>{#if x.twist}<button class="tw" type="button" aria-expanded={x.open ? "true" : "false"} aria-label={(x.open ? "Collapse " : "Expand ") + x.w} onclick={() => navToggle(x.twist as string, !!x.open)}>{x.open ? "▾" : "▸"}</button>{:else if !x.sub}<span class="tw"></span>{/if}<a href={"#/" + x.to} title={title(x)} aria-label={icons ? named(x) + (x.n ? `, ${x.n}` : "") : null} aria-current={on(x) ? "page" : null}>{#if !x.sub}<span class={"ic" + (TOPIC.test(x.to) ? " letter" : "")} aria-hidden="true">{#if TOPIC.test(x.to)}{(x.w.trim()[0] || "?").toUpperCase()}{:else if ICONS[x.to]}<Icon name={ICONS[x.to] as string} />{/if}</span>{/if}<span class="w">{x.w}</span>{#if x.live}<span class="live" title={x.to === "build" ? "A build is running" : "Running now"}></span>{/if}{#if x.n}<span class={count(x)}>{String(x.n)}</span>{/if}</a></div>
    {/if}
  {/each}
{/if}
