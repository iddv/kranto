// The console's three starters: in an empty console (no conversation yet, or a
// new one), above the prompt, three questions the owner can click. A click starts the session if
// none runs, types the sentence and sends it. They are words on a button, not new tools: the
// Kranto skill already knows the reads, and post.write writes a draft that waits on Post.
//
// The sentence sent names what "this" is (a card's number, a brief's address): the console's
// status line knows the page, but the model is never told it, so the words carry it.

export interface Starter {
  /** the button's words */
  label: string;
  /** the one muted line: what comes back */
  says: string;
  /** the sentence typed and sent */
  text: string;
}

export interface StarterPlace {
  /** the page's route (location.hash without "#/"), its path parts */
  path: string[];
  /** the selection in the address (sel=), when there is one */
  sel?: string | null;
  /** the owner's topics, by id */
  topics: { id: number | string; name: string }[];
  /** the topic with the newest brief (the home's read), when known */
  newest?: string | null;
}

/** a card's number from Ideas' address (#/ideas/143, #/ideas/card:143, ?sel=icard:143, ?sel=c143) */
function cardOf(p: StarterPlace): number | null {
  const [a, b] = p.path;
  if (a === "ideas" && b) {
    const m = /^(?:card:)?(\d+)$/.exec(decodeURIComponent(b));
    if (m) return Number(m[1]);
  }
  if (a === "ideas" && p.sel) {
    const m = /^(?:i?card:|c)(\d+)$/.exec(p.sel);
    if (m) return Number(m[1]);
  }
  return null;
}

/** the topic the page is about (a topic's pages under Watch), else the newest brief's */
function topicOf(p: StarterPlace): string | null {
  const [a, b, c] = p.path;
  const id = a === "watch" && b === "topic" ? c : a === "topics" && b && b !== "new" ? b : null;
  const here = id != null ? p.topics.find((t) => String(t.id) === id) : undefined;
  return here?.name || p.newest || p.topics[0]?.name || null;
}

/** the topic of the newest brief of any day (``/api/home``'s ``briefs.newest``), else today's
 *  first: never the first topic in the list while a brief exists */
export function newestTopic(briefs: { newest?: { name: string } | null; topics?: { topic: { name: string } }[] } | null | undefined): string | null {
  return briefs?.newest?.name ?? briefs?.topics?.[0]?.topic.name ?? null;
}

export function starters(p: StarterPlace): Starter[] {
  const topic = topicOf(p);
  const card = cardOf(p);
  const [a, b, c, d] = p.path;
  const brief = a === "news" && b === "b" && c ? `#/news/b/${c}` : a === "news" && b === "i" && c && d != null ? `#/news/i/${c}/${d}` : null;
  const post: Starter = card != null
    ? { label: "Write a post about this", says: "a draft on Post; nothing is sent", text: `Write a post about idea card #${card}.` }
    : brief
      ? { label: "Write a post about this", says: "a draft on Post; nothing is sent", text: `Write a post about the news at ${brief}.` }
      : { label: "Write a post about this week's news", says: "a draft on Post; nothing is sent", text: "Write a post about this week's news." };
  return [
    topic
      ? { label: `What is new in ${topic}?`, says: "the newest from your library, with links", text: `What is new in ${topic}?` }
      : { label: "What is new in my topics?", says: "the newest from your library, with links", text: "What is new in my topics?" },
    { label: "Which idea should I look at?", says: "one card from Ideas, and why", text: "Which idea should I look at?" },
    post,
  ];
}
