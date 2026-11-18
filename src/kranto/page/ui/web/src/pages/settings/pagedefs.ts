// Settings' pages (the owner's D1;): what you set up, in the order
// you set it up. The navigator, the Overview and each page's pane with nothing selected read this table.
export interface SetPage {
  /** the route under settings/ */
  key: string;
  title: string;
  lede: string;
  /** its groups, in order, as the list draws them */
  groups: string[];
}

export const SETTINGS_PAGES: readonly SetPage[] = [
  { key: "watching", title: "Watching", lede: "Where watching's model calls go and with which key, the Judge's and the Reasoner's models, how sources are read, live search, and the logins some sources are read with.", groups: ["Provider and key", "Models", "Reading", "Live search", "Logins for sources"] },
  // open-source wave 2: the accounts a draft can be sent with, and each posting
  // cub's own settings (the weekly issue, its topics, practice), one page
  { key: "posting", title: "Posting", lede: "The sites you post to, how each one posts, your blog and your newsletter.", groups: ["Sites you post to", "Your blog and newsletter"] },
  { key: "sources", title: "Sources", lede: "Every source Kranto reads, Add source (a kind, or Describe what to add), and the accounts some sources are read with.", groups: ["Sources by state", "Accounts"] },
  { key: "prompts", title: "Prompts", lede: "Every prompt Kranto sends a model that you can see and steer.", groups: ["Prompts by step"] },
  { key: "spend", title: "Spend", lede: "What was spent this month, by topic, and every cap in one list.", groups: ["By topic", "Caps"] },
  { key: "privacy", title: "Privacy & access", lede: "Usage reports, and who may act on Kranto.", groups: ["Usage reports", "Who may act"] },
  { key: "system", title: "System", lede: "Where Kranto runs, its updates, what Activity keeps, its health and what your grades changed.", groups: ["Service", "Updates", "Activity", "Health", "Your grades"] },
  { key: "assistant", title: "Assistant", lede: "The console docked on the right (your own Claude Code or Codex), what an assistant may do by itself, and how to use Kranto from your own client.", groups: ["The console", "What it does by itself", "Your own Claude Code or Codex"] },
  { key: "appearance", title: "Appearance", lede: "Light or dark, and the theme, in this browser.", groups: ["Theme", "Custom theme"] },
];
export const setPage = (node: string | null | undefined): SetPage | null => SETTINGS_PAGES.find((p) => "settings/" + p.key === node) || null;
