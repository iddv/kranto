// Settings: seven pages, then Advanced. Watching (the key, the models, reading,
// live search, the logins sources are read with), Posting (the accounts a draft is sent with, each
// posting cub's settings), Assistant, Spend, Privacy, System, Appearance. Advanced: Prompts, and
// what a settings file switches on by hand. Every old address lands on its new page, or on the
// Overview when its page left (lib/nodes.json, settingsRedirects.test.ts).
import { SETTINGS_PAGES, type SetPage } from "./pagedefs";

/** the seven pages, in the order you set kranto up */
export const DOORS_PAGES: readonly string[] = ["watching", "posting", "assistant", "spend", "privacy", "system", "appearance"];
/** Advanced, folded under the seven: Prompts */
export const ADVANCED_PAGES: readonly string[] = ["prompts"];
export const doorsPage = (key: string): SetPage | null => SETTINGS_PAGES.find((p) => p.key === key) || null;
/** a Settings page as the doors draw it */
export const doorsSetPage = (node: string | null | undefined): SetPage | null =>
  SETTINGS_PAGES.find((p) => "settings/" + p.key === node) || null;
