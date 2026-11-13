<script lang="ts">
  // A declarative card (MR-RESEARCH row 5): a feature's manifest says which
  // of an object's fields is the title, which are its lines and which are labelled fields of a
  // kind (text, date, money, link, number, list), and which holds its cites (origin): drawn as a
  // fenced "where it came from" line, each cite labelled ([obs 9301], [brief 41]) and an
  // observation's a link to it. A key may be a dotted path (thesis.catalyst). A feature ships no
  // code into the page for it, so a cub has cards too. Text is drawn as text, never as HTML.
  import type { CardSchema } from "../features/index";
  import { at, citesOf } from "../features/cub";
  import { href } from "../lib/router";

  let { schema, object }: { schema: CardSchema; object: Record<string, unknown> } = $props();
  const text = (v: unknown): string => (v == null ? "" : typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
  function shown(kind: string, v: unknown): string {
    if (v == null || v === "") return "";
    if (kind === "money" && typeof v === "number") return `$${v.toFixed(2)}`;
    if (kind === "date") return text(v).slice(0, 10);
    if (kind === "list" && Array.isArray(v)) return `${v.length}`;
    return text(v);
  }
  const fields = $derived(schema.fields.filter((f) => shown(f.kind, at(object, f.key)) !== "" && f.kind !== "list"));
  const cites = $derived(schema.origin ? citesOf(at(object, schema.origin)) : []);
</script>

<div class="card-d">
  <h4 class="card-t">{text(at(object, schema.title))}</h4>
  {#each schema.lines as k (k)}{#if text(at(object, k))}<p class={"card-l card-" + k.replace(/\./g, "-")}>{text(at(object, k))}</p>{/if}{/each}
  {#if fields.length}<dl class="kv small">{#each fields as f (f.key)}<dt>{f.label}</dt><dd>{#if f.kind === "link" && /^https?:/i.test(text(at(object, f.key)))}<a href={text(at(object, f.key))} rel="noopener noreferrer" target="_blank">{text(at(object, f.key))}</a>{:else}{shown(f.kind, at(object, f.key))}{/if}</dd>{/each}</dl>{/if}
  {#if cites.length}<p class="fence small"><span class="lab">where it came from</span>{#each cites as c, i (i)}{i ? " · " : ""}{#if c.obs}<a href={href("library/o/" + c.obs)}>{`[${c.label}]`}</a>{:else if c.url}<a href={c.url} rel="noopener noreferrer" target="_blank">{`[${c.label}]`}</a>{:else if c.brief != null}<a href={href("news/b/" + c.brief)}>{`[${c.label}]`}</a>{:else}{`[${c.label}]`}{/if}{c.title ? " " + c.title : ""}{c.date ? " " + c.date.slice(0, 10) : ""}{/each}</p>{/if}
</div>

<style>
  .fence { margin-top: 10px; padding: 8px 12px; border-left: 3px solid var(--border); background: var(--subtle); color: var(--muted); border-radius: 0 6px 6px 0; }
  .fence .lab { display: block; font: 600 10.5px var(--mono); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 4px; }
</style>
