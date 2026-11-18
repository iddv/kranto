// The activity read's shapes for the tests (api/activity, types.gen.ts's Activity): one run, and
// a read made of what a test names.
import type { Activity, ActivityFail, ActivityIncident, ActivityRun } from "../api/types.gen";

export function run(o: Partial<ActivityRun> = {}): ActivityRun {
  return {
    id: "afk:0f9e8d7c6b5a49382716a5b4c3d2e1f0", uuid: "0f9e8d7c6b5a49382716a5b4c3d2e1f0", kind: "news.brief",
    title: "Writing the News brief", words: null, state: "running",
    trigger: { origin: "schedule", by: null, at: "2026-10-23T01:00:00Z" }, subject: null, feature: "news",
    started: "2026-10-23T01:00:00Z", finished: null, elapsed_s: 72, usd: 0, calls: 0, tokens: null, progress: null,
    trace: "#/afk/0f9e8d7c6b5a49382716a5b4c3d2e1f0/trace", stoppable: true, stopping: false, needs: null,
    error: null, why: null, verb: null, ...o,
  };
}

export function fail(o: Partial<ActivityFail> = {}): ActivityFail {
  return { id: "fail:update", kind: "update", title: "The update check", since: "2026-10-19T08:00:00Z", last: "2026-10-22T08:00:00Z",
    tries: 3, error: "GitHub answered 401", verb: "Try again", trace: "#/afk/u3/trace", runs: [], ...o };
}

/** a real install's incident of 2026-10-25: the OpenRouter key expired, reading and idea cards stopped */
export function incident(o: Partial<ActivityIncident> = {}): ActivityIncident {
  return { id: "auth:openrouter", provider: "openrouter", name: "OpenRouter", cause: "expired", blocking: true,
    title: "Your OpenRouter key is refused (expired)",
    words: "Your OpenRouter key was refused (expired) at 08:15 on 25 Oct: reading your sources and idea cards stop until it is renewed in Settings › Watching.",
    since: "2026-10-25T08:15:00Z", last: "2026-10-27T17:00:00Z", tries: 22,
    kinds: [{ kind: "ingest", title: "Reading your sources", noun: "reading your sources", since: "2026-10-25T08:15:00Z", tries: 20 },
      { kind: "ideas", title: "Writing idea cards", noun: "idea cards", since: "2026-10-25T09:00:00Z", tries: 2 }],
    error: "HTTP 401 from https://openrouter.ai/api/v1: API key expired.", verb: "Renew the key",
    href: "#/settings/watching?sel=ekey", trace: "#/afk/i1/trace", ...o };
}

export function activityOf(o: Partial<Activity> = {}): Activity {
  return {
    seq: 1, running: [], waiting: [], next: [], recent: [], folded: [], failing: [], incidents: [],
    counts: { running: (o.running || []).length, waiting: (o.waiting || []).length, failed_recent: 0, failing: (o.failing || []).length, building: 0 },
    quiet: "Nothing is running.", scheduler: true, paused: false, afk_error: null, now: "2026-10-23T02:00:00Z", ...o,
  };
}
