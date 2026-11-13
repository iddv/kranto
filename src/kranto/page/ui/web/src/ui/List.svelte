<script lang="ts" module>
  /** the context a Settings page sets around the lists it is made of: each one
   * draws its groups only, under the page's own title and toolbar */
  export const EMBED = Symbol("embedded list");
  /** a crumb word the head already says (its crumb, its title): not a fact */
  const SAID = new Set(["Settings", "Overview", "Desk", "Topics"]);
</script>

<script lang="ts">
  // A list (the old page's wlist() and listHead()): the title with a muted crumb and one line of
  // sub text, then the toolbar, a sibling so it stays at the top while the rows scroll, then the
  // groups. A settings page's list is this with the crumb "Settings" and never a field. label is
  // the page's name in the tab (data-title) when it is not the title (a topic's "Name · Themes").
  // Inside a Settings page made of several lists (EMBED), it is its groups only. With the doors on
  // the title, its muted words (the facts), the sub text (the lede) and the page's verbs are the
  // shell's head (ui/PageTitle.svelte): the list starts at its toolbar.
  import { getContext, type Snippet } from "svelte";
  import PageTitle from "./PageTitle.svelte";
  import type { HeadDecl } from "../lib/app/heads";
  import { ui } from "../lib/shell.svelte";

  let { title, label = null, crumb = null, sub = null, about = null, head = null, tools, children }: {
    title: string; label?: string | null; crumb?: string | null; sub?: string | null; about?: string | null;
    /** the rest of the page's head: its primary, ⋯, its line, its flash */
    head?: Partial<HeadDecl> | null; tools?: Snippet; children?: Snippet;
  } = $props();
  const embedded = !!getContext(EMBED);
  const facts = $derived(ui.headOn && crumb && SAID.has(crumb) ? null : crumb);
</script>

{#if embedded}<div class="wl-part" data-part={title}>{@render children?.()}</div>{:else}<div class="wl" data-title={label ?? title}><PageTitle {...head || {}} {title} label={label ?? title} about={about ?? head?.about ?? null} facts={facts ?? head?.facts ?? null} lede={sub ?? head?.lede ?? null} />{#if tools}<div class="tb">{@render tools()}</div>{/if}{@render children?.()}</div>{/if}
