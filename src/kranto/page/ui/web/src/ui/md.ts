// A small Markdown (a README as the world will see it): paragraphs, lists, fenced code, inline
// code, bold. Parsed into blocks of text runs, drawn by Md.svelte as text, never as HTML. A
// backtick in a regex is \x60: a quote there sends the tests' string scanner out of step.

export type Run = { t: "text" | "code" | "strong" | "em"; s: string } | { t: "link"; s: string; href: string };
export type Block = { k: "p"; runs: Run[] } | { k: "h"; runs: Run[] } | { k: "pre"; s: string } | { k: "ul" | "ol"; items: Run[][] };

// a link, only when asked (a widget's note,): to a Kranto route or https://, which
// the server has already narrowed to the cub's own hosts; anything else stays its words as written
const LINK = /\[([^\]\n]{1,200})\]\((#\/[A-Za-z0-9_/?=&.%-]{1,300}|https:\/\/[^)\s]{1,400})\)/;

// a link's words and its target, whatever the target (a draft's own "/blog/…" and "http://")
const ANY_LINK = /^\[([^\]\n]{1,200})\]\(([^)\s]{1,400})\)$/;

export function inline(s: string, links = false): Run[] {
  // *italics* too (13, Codex 19, Gemini 10: a draft's "*Why:*" showed its stars)
  const out: Run[] = [], re = links ? /(\x60[^\x60\n]+\x60|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*|\[[^\]\n]{1,200}\]\([^)\s]{1,400}\))/g : /(\x60[^\x60\n]+\x60|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/g;
  let i = 0, m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > i) out.push({ t: "text", s: s.slice(i, m.index) });
    const l = m[0][0] === "[" ? LINK.exec(m[0]) : null;
    // a link whose target is not one a page may open shows its words, never its brackets
    const words = m[0][0] === "[" && !l ? ANY_LINK.exec(m[0])?.[1] ?? m[0] : null;
    out.push(m[0][0] === "\x60" ? { t: "code", s: m[0].slice(1, -1) } : m[0][0] === "[" ? (l ? { t: "link", s: l[1]!, href: l[2]! } : { t: "text", s: words! })
      : m[0].startsWith("**") ? { t: "strong", s: m[0].slice(2, -2) } : { t: "em", s: m[0].slice(1, -1) });
    i = m.index + m[0].length;
  }
  if (i < s.length) out.push({ t: "text", s: s.slice(i) });
  return out;
}
export function blocks(text: string, links = false): Block[] {
  const inline_ = (s: string) => inline(s, links);
  const lines = String(text || "").split("\n"), li = /^\s*([-*]|\d+\.) /, fence = /^\s*\x60\x60\x60/, head = /^#{1,6}\s+/, out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i]!;
    if (!l.trim()) { i++; continue; }
    if (fence.test(l)) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !fence.test(lines[i]!)) buf.push(lines[i++]!);
      i++;
      out.push({ k: "pre", s: buf.join("\n") });
      continue;
    }
    // a heading is its own block (a factory issue's "## What happened"), drawn as a small title
    if (head.test(l)) {
      out.push({ k: "h", runs: inline_(l.replace(head, "")) });
      i++;
      continue;
    }
    // a table: one row a line, its cells joined, the |---| line dropped (What Kranto sends' field
    // list showed its pipes: 13, Gemini 10)
    if (/^\s*\|.*\|\s*$/.test(l)) {
      const items: Run[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]!)) {
        const cells = lines[i++]!.trim().slice(1, -1).split("|").map((c) => c.trim());
        if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;
        items.push(inline_(cells.filter(Boolean).join(" · ")));
      }
      out.push({ k: "ul", items });
      continue;
    }
    if (li.test(l)) {
      const items: Run[][] = [], ol = /^\s*\d+\. /.test(l);
      while (i < lines.length && li.test(lines[i]!)) items.push(inline_(lines[i++]!.replace(li, "")));
      out.push({ k: ol ? "ol" : "ul", items });
      continue;
    }
    const buf: string[] = [];
    while (i < lines.length && lines[i]!.trim() && !fence.test(lines[i]!) && !li.test(lines[i]!) && !head.test(lines[i]!) && !/^\s*\|.*\|\s*$/.test(lines[i]!)) buf.push(lines[i++]!);
    out.push({ k: "p", runs: inline_(buf.join("\n")) });
  }
  return out;
}
