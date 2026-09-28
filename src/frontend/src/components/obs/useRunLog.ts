// Fetches a run's stored log (step console output + tool calls) from the API.
import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Finding, RunLog } from "../../contracts";
import { useStore } from "../../store";

const cache = new Map<string, { log: RunLog; findings: Finding[] }>();

// One request at a time: the Runs list would otherwise fire a burst on page load.
let queue: Promise<unknown> = Promise.resolve();
function fetchRun(runId: string): Promise<{ log: RunLog; findings: Finding[] }> {
  const next = queue.then(() => Promise.all([api.runLog(runId), api.run(runId)]));
  queue = next.catch(() => undefined);
  return next.then(([log, run]) => ({ log, findings: run.findings }));
}

/** Changes whenever a run or one of its steps changes status, so the fetch stays current. */
export function useRunVersion(runId: string | null): string {
  return useStore((s) => {
    const run = runId ? s.runs[runId] : undefined;
    if (!run) return "";
    return [run.summary.status, ...Object.values(run.lanes).map((l) => `${l.status}${l.attempt}`)].join("|");
  });
}

export function useRunLog(runId: string | null): { log: RunLog; findings: Finding[] } | null {
  const version = useRunVersion(runId);
  const key = runId ? `${runId}|${version}` : "";
  const [data, setData] = useState<{ key: string; value: { log: RunLog; findings: Finding[] } } | null>(null);
  const [retry, setRetry] = useState(0);
  const cached = key ? cache.get(key) : undefined;
  useEffect(() => {
    if (!runId || cache.has(key)) return;
    let cancelled = false;
    fetchRun(runId)
      .then((value) => {
        cache.set(key, value);
        if (!cancelled) setData({ key, value });
      })
      .catch(() => {
        if (!cancelled) window.setTimeout(() => setRetry((n) => n + 1), 3000);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, key, retry]);
  // keep showing the previous version of the same run while the next one loads
  return cached ?? (data && runId && data.key.startsWith(runId) ? data.value : null);
}
