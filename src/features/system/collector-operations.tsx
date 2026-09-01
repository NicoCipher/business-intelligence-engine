import type { CollectorState } from "@/src/features/api/types";
import { StateTag, TableScroll } from "@/src/features/shared/components";
import { formatDate, formatNumber } from "@/src/features/shared/format";

function timingTone(status: CollectorState["timing_gate_status"]) {
  if (status === "backing_off") return "danger";
  if (status === "disabled" || status === "quota_exhausted") return "warning";
  if (status === "not_yet_run" || status === "interval_elapsed") return "info";
  return "default";
}

function timingLabel(collector: CollectorState) {
  switch (collector.timing_gate_status) {
    case "disabled": return "Disabled";
    case "backing_off": return "Backing off";
    case "quota_exhausted": return "Quota exhausted";
    case "not_yet_run": return "Not yet run";
    case "interval_elapsed": return "Interval elapsed";
    case "interval_waiting": return "Waiting for interval";
    default: return "Unknown timing";
  }
}

function attemptTone(status: CollectorState["last_attempt_status"]) {
  if (status === "failed") return "danger";
  if (status === "succeeded") return "good";
  if (status === "not_yet_run") return "info";
  return "warning";
}

function attemptLabel(status: CollectorState["last_attempt_status"]) {
  return {
    succeeded: "Succeeded",
    failed: "Failed",
    not_yet_run: "Not yet run",
    unknown: "Unknown"
  }[status];
}

function quotaLabel(collector: CollectorState) {
  if (collector.quota.limit === 0) return "Unlimited";
  return `${formatNumber(collector.quota.used)} / ${formatNumber(collector.quota.limit)}`;
}

export function CollectorOperations({ collectors }: Readonly<{ collectors: CollectorState[] }>) {
  if (collectors.length === 0) {
    return <p className="muted">No durable collector state is recorded.</p>;
  }

  return (
    <TableScroll label="Collector operations table">
      <table className="data-table">
        <thead>
          <tr><th>Collector</th><th>Timing gate</th><th>Last attempt</th><th>Next due</th><th>Quota</th><th>Failure evidence</th></tr>
        </thead>
        <tbody>
          {collectors.map((collector) => (
            <tr key={`${collector.source}:${collector.domain}`}>
              <td><div className="title-cell"><strong>{collector.source}</strong><span className="quiet">Domain: {collector.domain} · every {collector.interval_minutes} min · priority {collector.priority}</span></div></td>
              <td><StateTag tone={timingTone(collector.timing_gate_status)}>{timingLabel(collector)}</StateTag></td>
              <td><div className="stack-tight"><StateTag tone={attemptTone(collector.last_attempt_status)}>{attemptLabel(collector.last_attempt_status)}</StateTag><span className="quiet">{formatDate(collector.last_run_at)}</span></div></td>
              <td><div className="stack-tight"><span>{formatDate(collector.next_due_at)}</span>{collector.backoff_until ? <span className="quiet">Backoff until {formatDate(collector.backoff_until)}</span> : null}</div></td>
              <td><div className="stack-tight"><span>{quotaLabel(collector)}</span>{collector.quota.limit > 0 ? <span className="quiet">Resets {formatDate(collector.quota.reset_at)}</span> : null}</div></td>
              <td><div className="stack-tight"><span>{collector.consecutive_failures === 0 ? "No consecutive failures" : `${collector.consecutive_failures} consecutive failure${collector.consecutive_failures === 1 ? "" : "s"}`}</span><span className="quiet">Last failure: {formatDate(collector.last_failure_at)}</span>{collector.last_attempt_status === "failed" ? <span className="quiet">Failure cause and rate-limit classification are not stored.</span> : null}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
