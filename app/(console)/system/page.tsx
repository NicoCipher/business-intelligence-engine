import { getCollectorState, getHealth, getSignalStats } from "@/src/features/api/client";
import { connection } from "next/server";
import { PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatNumber, isStale } from "@/src/features/shared/format";
import { CollectorOperations } from "@/src/features/system/collector-operations";

export default async function SystemPage() {
  await connection();
  const [health, stats, collectorState] = await Promise.all([getHealth(), getSignalStats(), getCollectorState()]);
  const stale = isStale(health.db.latest_signal);
  return (
    <>
      <PageHeading eyebrow="Diagnostics" title="System health" description="Read-only checks derived from durable backend state. Collector timing and failure records are shown without inferring health, rate limits, or job activity that BIA does not persist." />
      <div className="section-grid">
        <div className="span-6"><Panel title="API and evidence freshness"><div className="panel-body stack"><div className="status-line"><span className={`status-dot ${health.status === "ok" ? "ok" : "danger"}`} aria-hidden="true" /><span>API response: {health.status}</span></div><div className="status-line"><span className={`status-dot ${stale ? "warn" : "ok"}`} aria-hidden="true" /><span>{stale ? "Latest signal is stale or unavailable." : "Latest signal is within the freshness threshold."}</span></div><dl className="key-value"><dt>API version</dt><dd className="mono">{health.version}</dd><dt>Latest collection evidence</dt><dd>{formatDate(stats.latest_collection)}</dd><dt>Latest signal</dt><dd>{formatDate(health.db.latest_signal)}</dd></dl></div></Panel></div>
        <div className="span-6"><Panel title="Persistent intelligence"><div className="panel-body"><dl className="key-value"><dt>Signals</dt><dd>{formatNumber(health.db.signals)}</dd><dt>Entities</dt><dd>{formatNumber(health.db.entities)}</dd><dt>Problems</dt><dd>{formatNumber(health.db.problems)}</dd><dt>Problem history events</dt><dd>{formatNumber(health.db.problem_history)}</dd><dt>Opportunities</dt><dd>{formatNumber(health.db.opportunities)}</dd><dt>Reports</dt><dd>{formatNumber(health.db.reports)}</dd></dl></div></Panel></div>
        <div className="span-7"><Panel title="Visible source footprint"><div className="panel-body">{Object.keys(stats.by_source).length === 0 ? <p className="muted">The signal-stats endpoint does not currently report a source breakdown.</p> : <div className="tag-row">{Object.entries(stats.by_source).map(([source, count]) => <StateTag key={source} tone="info">{source} · {count}</StateTag>)}</div>}<p className="quiet">This is observed signal volume, not per-collector health or scheduling state.</p></div></Panel></div>
        <div className="span-5"><Panel title="Deliberate contract limits"><div className="panel-body stack"><div className="notice">Collector failure messages, last-failure classification (including rate limit), active job state, backup freshness, restore status, disk health, and job logs are not durably exposed.</div><div className="notice info">Change events, watchlists, and alert rules are deliberately deferred until their backed operational contracts exist.</div></div></Panel></div>
        <div className="span-12"><Panel title="Collector operations"><div className="panel-body"><CollectorOperations collectors={collectorState.collectors} /><p className="quiet">Timing is derived server-side from recorded run intervals and backoff. Scheduler configuration and execution remain authoritative outside this read-only view.</p></div></Panel></div>
      </div>
    </>
  );
}
