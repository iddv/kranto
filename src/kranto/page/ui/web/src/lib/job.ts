// the server's model-backed work (the scout, an explanation) runs in the background: no request
// waits on a model (the owner's rule, 2026-10-11). The press answers with {job}; afkJob polls the
// job every 1.5 s, saying how long it has run (wait), and returns its result once done. An answer
// without a job (an older the server, a cached explanation) is the result itself.
import { app } from "./shell.svelte";

interface Job {
  state: string;
  elapsed_s?: number;
  error?: string | null;
  result?: unknown;
}
export async function afkJob(r: unknown, poll: string, wait?: ((seconds: number) => void) | null): Promise<unknown> {
  const first = (r as { job?: Job } | null)?.job;
  if (!first) return r;
  let job: Job = first;
  const t0 = Date.now() - (job.elapsed_s || 0) * 1000;
  while (job.state === "running") {
    wait?.(Math.round((Date.now() - t0) / 1000));
    await new Promise((res) => setTimeout(res, 1500));
    job = ((await app()!.api(poll)) as { job: Job }).job;
  }
  if (job.state !== "done") throw new Error(job.error || "it failed");
  return job.result;
}
