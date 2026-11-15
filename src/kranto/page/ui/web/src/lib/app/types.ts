// The facts the shell's chrome draws (frame() reads them from chromeFacts after every draw), and
// the shapes the app's verbs share with the pages.
/** the header's update pill: "Update 0.1.0 → 0.2.0", the step while it runs, or the rollback */
export interface UpdateFacts {
  icon: string;
  colour: string;
  word: string;
  /** the muted words after it (the versions, the step), if any */
  detail: string | null;
  title: string;
}
export interface HeaderFacts {
  /** the server's half, when it hosts the page */
  host: { paused: boolean; running: string | null; next: string | null; reading?: string | null } | null;
  update: UpdateFacts | null;
  /** what Pause stops, in words */
  pauses: string;
  theme: { name: string; dark: boolean };
}
export interface NavRow {
  head?: string;
  to: string;
  w: string;
  add?: string | null;
  key?: string | null;
  n?: number | string | null;
  tone?: string;
  hot?: boolean;
  live?: boolean;
  sub?: boolean;
  /** a page under a sub entry (a topic's Sources, Evidence and Map in the classic tree) */
  deep?: boolean;
  fold?: boolean;
  twist?: string;
  open?: boolean;
}
export interface NavFacts {
  here: string;
  rows: NavRow[];
  topic: string | null;
}
export interface BarFacts {
  word: { icon: string; colour: string; text: string };
  /** why the word is not Healthy, one line in plain words (the server's health.py,), and where
   * a click goes (the run's trace, else Health); null when Healthy */
  why: { text: string; href: string } | null;
  used: { text: string; title: string } | null;
  cells: string[];
  size: string | null;
  /** the preview's sentence (the server's /api/status `preview.line`,): "Preview: a copy of
   * your data from 11 November. Nothing is sent."; null on every other install */
  preview: string | null;
}
export interface HintFacts {
  rows: boolean;
  grade: boolean;
  tick: boolean;
  term: boolean;
  review: boolean;
  sections: boolean;
}
export interface Undo {
  until: number;
  run(btn: HTMLElement): void;
  timer?: ReturnType<typeof setTimeout>;
}
export interface HeadFacts {
  paused: { afk: boolean; host: boolean } | null;
  /** not signed in: the sign-in line shows */
  signin: boolean;
  flash: { text: string; kind: string; undo: Undo | null } | null;
}
/** a door's head with the doors on: the crumb's word and the subnav, each word
 * with the count of what waits there and whether it is the page drawn */
export interface DoorFacts {
  id: string;
  word: string;
  /** sub: the page is the scope's (Watch's Sources, Evidence and Map: a topic's, or All topics') */
  items: { to: string; w: string; n: number | null; tone: string; title?: string | null; on: boolean; sub?: boolean }[];
  /** Watch's scope (WT): the topic its pages are for, or All topics; page is the scoped page
   * open (null: none, "" the topic itself); the crumb's switcher lists topics */
  /** the classic frame: the crumb only (its tree is the subnav) */
  crumbOnly?: boolean;
  /** the classic frame: the head draws no crumb (the tree says where you are) but Watch's switcher */
  classic?: boolean;
  scope?: { topic: string | null; name: string; all: boolean; page: "" | "sources" | "evidence" | "map" | null; to: string | null; on: boolean; topics: { id: string; name: string }[] } | null;
}
export interface Facts {
  header: HeaderFacts;
  nav: NavFacts;
  bar: BarFacts;
  hint: HintFacts;
  head: HeadFacts;
  /** the door this page is in, with the doors on; null elsewhere (the home, a cub, a stage) */
  door: DoorFacts | null;
  /** the same door in either layout (classic: true in the navigator's frame), for the page's head
   * (shell/PageHead.svelte); null outside the doors */
  place?: DoorFacts | null;
}
/** one item of a menu (⋯): its label, its id (data-menu) and what it runs */
export interface MenuItem {
  label: string;
  id?: string | null;
  key?: string | null;
  group?: string;
  why?: string | null;
  title?: string | null;
  /** a second line under the label, in words: what the verb reaches ("everywhere: all 4 topics") */
  note?: string | null;
  /** the registry verb it runs, drawn as data-verb (PAR: the page's control says its verb) */
  verb?: string | null;
  run: (anchor: HTMLElement) => void;
}
