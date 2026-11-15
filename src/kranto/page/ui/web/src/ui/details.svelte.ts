// The Details drawer's state: which object's record is open. A row's,
// the one thing's or a dialog's "Details" sets it; ui/Details.svelte draws the record from
// /brb/api/details, the read the console's kranto_details answers too.

export const DETAILS_API = "api/details";

export interface DetailsRecord {
  sel: string;
  kind: string;
  title: string;
  page: string | null;
  groups: { h: string; rows: [string, string][] }[];
  tool: string;
}

export const DETAILS = $state<{ sel: string | null }>({ sel: null });

export function openDetails(sel: string): void {
  DETAILS.sel = sel;
}

export function closeDetails(): void {
  DETAILS.sel = null;
}

export const detailsPath = (sel: string): string => `${DETAILS_API}?sel=${encodeURIComponent(sel)}`;
