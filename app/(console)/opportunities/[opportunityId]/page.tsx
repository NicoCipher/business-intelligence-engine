import { Fragment } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { BackendApiError, getOpportunity } from "@/src/features/api/client";
import { reviewOpportunityStatus } from "@/src/features/opportunities/actions";
import { ExternalEvidenceLink, PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatScore } from "@/src/features/shared/format";

type Props = { params: Promise<{ opportunityId: string }>; searchParams: Promise<{ status?: string }> };

function numericScores(scores: Record<string, unknown>) {
  return Object.entries(scores).filter(([, value]) => typeof value === "number");
}

export default async function OpportunityDetailPage({ params, searchParams }: Props) {
  await connection();
  const { opportunityId } = await params;
  const { status } = await searchParams;
  let opportunity;
  try {
    opportunity = await getOpportunity(opportunityId);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) notFound();
    throw error;
  }
  const scores = numericScores(opportunity.scores);

  return (
    <>
      <PageHeading eyebrow="Opportunity detail" title={opportunity.title} description={opportunity.description} />
      {status === "updated" ? <p className="notice info" role="status">Review status updated. The underlying opportunity evidence was not modified.</p> : null}
      <div className="detail-grid">
        <div className="stack">
          <Panel title={`Evidence · ${opportunity.evidence.length} signals`}>
            {opportunity.evidence.length === 0 ? <div className="panel-body"><p className="muted">No evidence signals are currently returned for this assessment.</p></div> : <div style={{ overflowX: "auto" }}><table className="data-table"><thead><tr><th scope="col">Signal</th><th scope="col">Source</th><th scope="col">Engagement</th><th scope="col">Observed</th></tr></thead><tbody>{opportunity.evidence.map((signal) => <tr key={signal.id}><td className="title-cell"><ExternalEvidenceLink href={signal.url}>{signal.title}</ExternalEvidenceLink><span className="tag-row">{signal.tags.map((tag) => <StateTag key={tag}>{tag}</StateTag>)}</span></td><td><StateTag tone="info">{signal.source}</StateTag></td><td className="mono">{signal.engagement}</td><td className="muted">{formatDate(signal.collected_at)}</td></tr>)}</tbody></table></div>}
          </Panel>
          <Panel title="Score components">
            <div className="panel-body"><dl className="key-value"><dt>Composite</dt><dd><StateTag tone="good">{formatScore(opportunity.composite_score)} · {opportunity.tier}</StateTag></dd>{scores.length > 0 ? scores.map(([name, value]) => <Fragment key={name}><dt>{name.replaceAll("_", " ")}</dt><dd>{formatScore(value as number)}</dd></Fragment>) : <><dt>Breakdown</dt><dd className="muted">No numeric dimensions are present in the response.</dd></>}</dl></div>
          </Panel>
        </div>
        <div className="stack">
          <Panel title="Assessment metadata">
            <div className="panel-body"><dl className="key-value"><dt>Domain</dt><dd>{opportunity.domain}</dd><dt>Week</dt><dd>{opportunity.week_key}</dd><dt>Created</dt><dd>{formatDate(opportunity.created_at)}</dd><dt>Evidence count</dt><dd>{opportunity.evidence_count}</dd><dt>Review status</dt><dd><StateTag>{opportunity.status}</StateTag></dd></dl></div>
          </Panel>
          <Panel title="Review status">
            <form className="panel-body stack" action={reviewOpportunityStatus}>
              <input type="hidden" name="id" value={opportunity.id} />
              <label className="field">Set status<select name="status" defaultValue={opportunity.status === "new" ? "validated" : opportunity.status}><option value="validated">Validated</option><option value="dismissed">Dismissed</option><option value="archived">Archived</option></select></label>
              <button type="submit">Save review status</button>
              <span className="quiet">This protected server action uses the backend credential only on the server.</span>
            </form>
          </Panel>
          <Panel title="Traceability"><div className="panel-body"><p className="muted">Signal identifiers</p><div className="tag-row">{opportunity.signal_ids.map((id) => <StateTag key={id}>{id}</StateTag>)}</div><p><Link className="button-link" href="/signals">Browse all signals</Link></p></div></Panel>
        </div>
      </div>
    </>
  );
}
