// Activity's two keys, on Settings › System: how long the runs' marks are kept, and how
// many at most (the oldest go first, at compaction). One read, one write: /api/settings/activity.
export const ACTIVITY_SETTINGS = "/api/settings/activity";
export interface ActivitySettings {
  keep_days: number;
  max_rows: number;
  rows: number;
}
export const activityWords = (s: Pick<ActivitySettings, "keep_days" | "max_rows">): string =>
  `${s.keep_days} days, at most ${s.max_rows.toLocaleString("en-GB")} marks`;
