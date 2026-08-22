import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { BackendApiError, getProblem, getProblemHistory } from "@/src/features/api/client";
import { PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatScore } from "@/src/features/shared/format";

type Props = { params: Promise<{ problemId: string }> };

export default async function ProblemDetailPage({ params }: Props) {
  await connection();
  const { problemId } = await params;
  let problem;
  let history;
  try {
    [problem, history] = await Promise.all([getProblem(problemId), getProblemHistory(problemId)]);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <>
      <PageHeading eyebrow="Problem detail" title={problem.title} description="Canonical identity and historical evidence. The current contract exposes entity identifiers, but not Entity or Relationship detail records." />
      <div className="detail-grid">
        <div className="stack">
          <Panel title="Current state">
            <div className="panel-body"><dl className="key-value">
              <dt>Domain</dt><dd><StateTag>{problem.domain}</StateTag></dd>
              <dt>Lifecycle</dt><dd><StateTag tone={problem.lifecycle_state === "active" ? "good" : "default"}>{problem.lifecycle_state}</StateTag></dd>
              <dt>Trend</dt><dd><StateTag>{problem.trend}</StateTag></dd>
              <dt>Evidence cadence</dt><dd>{problem.weeks_seen} weeks</dd>
              <dt>First seen</dt><dd>{formatDate(problem.first_seen)}</dd>
              <dt>Last seen</dt><dd>{formatDate(problem.last_seen)}</dd>
            </dl></div>
          </Panel>
          <Panel title={`History · ${history.total} events`}>
            <div className="panel-body">
              {history.history.length === 0 ? <p className="muted">No history events have been retained for this Problem.</p> : <ol className="timeline">{history.history.map((event) => <li key={event.id}><div className="timeline-event">{event.event_type}</div><div className="timeline-meta">{formatDate(event.occurred_at)} · {event.week_key}{event.opportunity_id ? ` · opportunity ${event.opportunity_id}` : ""}</div></li>)}</ol>}
            </div>
          </Panel>
        </div>
        <div className="stack">
          <Panel title={`Linked opportunities · ${problem.linked_opportunities.length}`}>
            <div className="panel-body stack">
              {problem.linked_opportunities.length === 0 ? <p className="muted" style={{ margin: 0 }}>No linked opportunity is currently exposed.</p> : problem.linked_opportunities.map((opportunity) => <div key={opportunity.id}><Link href={`/opportunities/${encodeURIComponent(opportunity.id)}`}>{opportunity.title}</Link><div className="tag-row" style={{ marginTop: ".35rem" }}><StateTag tone="good">{formatScore(opportunity.composite_score)}</StateTag><StateTag>{opportunity.tier}</StateTag><StateTag>{opportunity.status}</StateTag></div></div>)}
            </div>
          </Panel>
          <Panel title={`Entity references · ${problem.entity_ids.length}`}>
            <div className="panel-body"><p className="muted">Entity IDs are shown for provenance only. Graph inspection awaits a backend Entity/Relationship API.</p><div className="tag-row">{problem.entity_ids.map((id) => <StateTag key={id}>{id}</StateTag>)}</div></div>
          </Panel>
        </div>
      </div>
    </>
  );
}
