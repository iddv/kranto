// The app: the one service object the shell and the pages reach through app() (main.ts
// connects it, lib/shell.svelte.ts holds it, the tests stub it). Its parts: the data and the press
// (data.ts), where a route draws and the draw (route.ts), the rows and the keys (rows.ts), the
// chrome's facts (chrome.ts), the palette's items (commands.ts), and the one popover, menu, dialog
// and toast (../../ui).
export { act, afkDrop, afkDropPrefix, afkStale, api, flash, flashUndo, host, hostForm, loadHost, loadWho, say, signIn, togglePause, updApply, updCancel, updRollback } from "./data";
export { boot, closeSheet, hasView, keySheet, onHash, openClaude, pageKey, pageKeys, paneSelHref, refresh, render, runPageKey, topicAt, typing } from "./route";
export { closeKey, initFrame, keyFirst, rowKey, rowNow, rowsNow, spy, spyJump, stepping } from "./rows";
export { chromeFacts } from "./chrome";
export { palItems, previewSubjects } from "./commands";
export { closePop, menu, popover } from "../../ui/popover";
export { toast } from "../../ui/toast.svelte";
export { nodeDialog as dialog } from "../../ui/dialog.svelte";
export { setTheme } from "../theme";
export type { BarFacts, DoorFacts, Facts, HeadFacts, HeaderFacts, HintFacts, MenuItem, NavFacts, NavRow, Undo, UpdateFacts } from "./types";

export type App = typeof import("./index");
