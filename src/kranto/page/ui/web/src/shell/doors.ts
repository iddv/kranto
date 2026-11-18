// The doors: News, Ideas, Watch and Post, in the order of a day (read the
// news, look at the ideas, tune what is watched, post). The top bar draws them on a wide screen,
// the phone's bar at the bottom with ✦ (the console) as its fifth item. [door id, word, address];
// the id is lib/app/chrome.ts's doorId, which lights the current one. Watch opens #/topics, which
// lands on the last topic you looked at.
export const DOORS: readonly (readonly [string, string, string])[] = [
  ["news", "News", "#/news"],
  ["ideas", "Ideas", "#/ideas"],
  ["watch", "Watch", "#/topics"],
  ["post", "Post", "#/post"],
];
/** the phone's glyph for each door */
export const DOOR_GLYPH: Record<string, string> = { news: "▤", ideas: "◆", watch: "◉", post: "✎" };
