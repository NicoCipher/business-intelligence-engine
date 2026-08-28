import Link from "next/link";

import { BackendApiError, getHealth, getLatestReport, getSignalStats, getSignals, getUnseenChanges } from "@/src/features/api/client";
import { acknowledgeCurrentChanges } from "@/src/features/changes/actions";
import { EmptyState, ExternalEvidenceLink, Panel, StateTag, TableScroll } from "@/src/features/shared/components";
import { formatDate, formatNumber, isStale } from "@/src/features/shared/format";

function latestReportText(content: unknown) {
  if (typeof content === "string" && content.trim()) return content;
  if (content && typeof content === "object") {
    const summary = (content as Record<string, unknown>).summary;
    if (typeof summary === "string") return summary;
  }
  return "The latest report records no qualified opportunity. Review the report’s watch-list evidence for near-misses.";
}

export async function OperatingState() {
  const health = await getHealth();
  const stale = isStale(health.db.latest_signal);
  const evidenceFresh = health.status === "ok" && !stale;

  return (
    <Panel title="Verified health" action={<StateTag tone={evidenceFresh ? "good" : "warning"}>{evidenceFresh ? "API + evidence fresh" : "Freshness needs review"}</StateTag>}>
      <div className="panel-body">
        <div className="status-line">
          <span className={`status-dot ${evidenceFresh ? "ok" : "warn"}`} aria-hidden="true" />
          <span>{evidenceFresh ? "API reachable; the latest signal is within the freshness threshold." : "API is reachable, but the latest signal is stale or unavailable."}</span>
        </div>
        <div className="divider" />
        <dl className="key-value">
          <dt>API version</dt><dd className="mono">{health.version}</dd>
          <dt>Latest observed signal</dt><dd>{formatDate(health.db.latest_signal)}</dd>
          <dt>Last operator checkpoint</dt><dd>{formatDate(health.db.operator_last_seen_at)}</dd>
        </dl>
        <p className="contract-scope">Collector, scheduler, pipeline, backup, restore, and disk health are unknown under the current API.</p>
      </div>
    </Panel>
  );
}

export async function AttentionQueue() {
  const [health, stats] = await Promise.all([getHealth(), getSignalStats()]);
  const stale = isStale(stats.latest_collection);
  const hasNoOpportunities = health.db.opportunities === 0;

  return (
    <Panel title="Requires attention">
      <div className="panel-body stack">
        {stale ? <div className="notice danger"><strong>Evidence freshness needs review.</strong><span>No signal collection has been recorded in the last 36 hours. Collector failures and run history are not exposed.</span><Link className="notice-action" href="/system">Review verified system health</Link></div> : null}
        {hasNoOpportunities ? <div className="notice"><strong>No opportunities are persisted.</strong><span>This is not a system failure. The latest report may explain evidence that did not meet persistence thresholds.</span><Link className="notice-action" href="/reports">Review latest report</Link></div> : null}
        {!stale && !hasNoOpportunities ? <div className="notice info">No attention items are derivable from the currently exposed backend contract.</div> : null}
      </div>
    </Panel>
  );
}

export async function ChangeVisibility() {
  const unseen = await getUnseenChanges(5);
  const hasUnseen = unseen.total_unseen > 0;
  const moreBeyondPreview = unseen.total_unseen - unseen.changes.length;

  return (
    <Panel title="What changed since last looked" action={<StateTag tone={hasUnseen ? "warning" : "good"}>{hasUnseen ? `${formatNumber(unseen.total_unseen)} unseen` : "Up to date"}</StateTag>}>
      <div className="panel-body change-status">
        <p className="muted">{unseen.since ? `Last reviewed ${formatDate(unseen.since)}.` : "This checkpoint has never been acknowledged — every change below is unseen."}</p>
        {!hasUnseen ? (
          <p>No Problem or Opportunity changes have been recorded since your last review.</p>
        ) : (
          <TableScroll label="Unseen change events table">
            <table className="data-table">
              <thead><tr><th scope="col">Change</th><th scope="col">Significance</th><th scope="col">Detected</th></tr></thead>
              <tbody>{unseen.changes.map((change) => (
                <tr key={change.id}>
                  <td className="title-cell">
                    <Link href={`/${change.entity_ref_type === "problem" ? "problems" : "opportunities"}/${encodeURIComponent(change.entity_ref_id)}`}>{change.entity_title ?? change.entity_ref_id}</Link>
                    <span className="muted">{change.event_type.replaceAll("_", " ")}{change.new_value ? ` → ${change.new_value}` : ""}</span>
                  </td>
                  <td><StateTag tone={change.significance === "high" ? "warning" : "default"}>{change.significance}</StateTag></td>
                  <td className="muted">{formatDate(change.detected_at)}</td>
                </tr>
              ))}</tbody>
            </table>
          </TableScroll>
        )}
        {hasUnseen && moreBeyondPreview > 0 ? <p className="muted">And {formatNumber(moreBeyondPreview)} more.</p> : null}
        {hasUnseen ? (
          <form action={acknowledgeCurrentChanges}>
            <input type="hidden" name="snapshotAt" value={unseen.snapshot_at} />
            <button type="submit">Mark reviewed through {formatDate(unseen.snapshot_at)}</button>
            <span className="quiet"> Marks every change through this snapshot as reviewed, not only the {unseen.changes.length} shown above.</span>
          </form>
        ) : null}
      </div>
    </Panel>
  );
}

export async function IntelligenceSnapshot() {
  const stats = await getSignalStats();
  return (
    <Panel title="Recent intelligence context" action={<Link className="button-link" href="/signals">Inspect signals</Link>}>
      <div className="panel-body">
        <div className="metrics">
          <div className="metric"><span className="metric-value">{formatNumber(stats.signals_this_week)}</span><span className="metric-label">Signals in last 7 days</span></div>
          <div className="metric"><span className="metric-value">{formatNumber(stats.total_signals)}</span><span className="metric-label">Signals retained</span></div>
          <div className="metric"><span className="metric-value">{Object.keys(stats.by_source).length}</span><span className="metric-label">Sources with evidence</span></div>
          <div className="metric"><span className="metric-value">{formatNumber(stats.total_opps)}</span><span className="metric-label">Opportunities persisted</span></div>
        </div>
        <div className="divider" />
        <div className="tag-row" aria-label="Top signal tags">
          {stats.top_tags.length > 0 ? stats.top_tags.map((tag) => <StateTag key={tag.tag}>{tag.tag} · {tag.count}</StateTag>) : <span className="quiet">No tags in the recent collection window.</span>}
        </div>
      </div>
    </Panel>
  );
}

export async function LatestReportPanel() {
  let report;
  try {
    report = await getLatestReport();
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      return <Panel title="Latest report"><EmptyState title="No report has been generated yet.">Report generation is a backend operation and is intentionally not exposed in Phase 1.</EmptyState></Panel>;
    }
    throw error;
  }
  const hasNoOpportunities = report.opp_count === 0;
  const reportMessage = hasNoOpportunities
    ? latestReportText(report.content.zero_opportunities_explanation)
    : typeof report.content.executive_summary === "string"
      ? report.content.executive_summary
      : "A report was generated without an executive summary.";

  return (
    <Panel title="Latest report" action={<Link className="button-link" href={`/reports/${encodeURIComponent(report.week_key)}`}>Open report</Link>}>
      <div className="panel-body">
        <div className="status-line"><StateTag tone={hasNoOpportunities ? "warning" : "good"}>{report.week_key}</StateTag><span className="muted">Generated {formatDate(report.created_at)}</span></div>
        <p className="muted">{reportMessage}</p>
        <div className="tag-row"><StateTag>{report.signal_count} signals</StateTag><StateTag>{report.opp_count} opportunities</StateTag><StateTag>{report.domain}</StateTag></div>
      </div>
    </Panel>
  );
}

export async function RecentSignalsPanel() {
  const response = await getSignals({ limit: 5, offset: 0 });
  return (
    <Panel title="Recently observed signals" action={<Link className="button-link" href="/signals">View all</Link>}>
      {response.signals.length === 0 ? <EmptyState title="No signals retained.">Collection has not produced any inspectable evidence.</EmptyState> : (
        <TableScroll label="Recently observed signals table">
          <table className="data-table">
            <thead><tr><th scope="col">Signal</th><th scope="col">Source</th><th scope="col">Observed</th></tr></thead>
            <tbody>{response.signals.map((signal) => (
              <tr key={signal.id}>
                <td className="title-cell"><ExternalEvidenceLink href={signal.url}>{signal.title}</ExternalEvidenceLink><span className="tag-row">{signal.tags.slice(0, 2).map((tag) => <StateTag key={tag}>{tag}</StateTag>)}</span></td>
                <td><StateTag>{signal.source}</StateTag></td>
                <td className="muted">{formatDate(signal.collected_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableScroll>
      )}
    </Panel>
  );
}
