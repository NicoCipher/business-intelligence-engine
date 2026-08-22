import Link from "next/link";
import { connection } from "next/server";

import { getOpportunities } from "@/src/features/api/client";
import { EmptyState, PageControls, PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatNumber, formatScore } from "@/src/features/shared/format";
import { boundedInteger, singleValue, type SearchParams } from "@/src/features/shared/search-params";

type Props = { searchParams: Promise<SearchParams> };

function tierTone(tier: string) {
  if (tier === "gold") return "good" as const;
  if (tier === "silver") return "info" as const;
  return "default" as const;
}

export default async function OpportunitiesPage({ searchParams }: Props) {
  await connection();
  const params = await searchParams;
  const status = singleValue(params.status);
  const week = singleValue(params.week);
  const domain = singleValue(params.domain);
  const rawScore = singleValue(params.min_score);
  const scoreValue = Number(rawScore);
  const minScore = Number.isFinite(scoreValue) && scoreValue >= 0 && scoreValue <= 10 ? scoreValue : undefined;
  const offset = boundedInteger(singleValue(params.offset), 0, 1_000_000);
  const limit = 20;
  const result = await getOpportunities({ status, week, domain, min_score: minScore, offset, limit });

  return (
    <>
      <PageHeading eyebrow="Commercial assessments" title="Opportunities" description="Dated, evidence-backed assessments linked to canonical Problems. Review status is curator metadata; it does not rewrite the underlying intelligence." />
      <Panel title="Opportunity register" action={<span className="mono quiet">{formatNumber(result.total)} assessments</span>}>
        <form className="filter-bar" method="get" aria-label="Filter opportunities">
          <label className="field">Status<input name="status" defaultValue={status} placeholder="e.g. validated" /></label>
          <label className="field">Week<input name="week" defaultValue={week} placeholder="e.g. 2026-W33" /></label>
          <label className="field">Domain<input name="domain" defaultValue={domain} placeholder="e.g. business" /></label>
          <label className="field">Minimum score<input name="min_score" inputMode="decimal" defaultValue={rawScore} placeholder="0–10" /></label>
          <button type="submit">Apply filters</button>
        </form>
        {result.opportunities.length === 0 ? <EmptyState title="No Opportunities match this view.">The backend currently has no persisted opportunities in the local operational database. Use Reports to inspect diagnostic near-misses.</EmptyState> : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th scope="col">Assessment</th><th scope="col">Score</th><th scope="col">Evidence</th><th scope="col">Review</th><th scope="col">Created</th></tr></thead>
              <tbody>{result.opportunities.map((opportunity) => (
                <tr key={opportunity.id}>
                  <td className="title-cell"><Link href={`/opportunities/${encodeURIComponent(opportunity.id)}`}>{opportunity.title}</Link><p>{opportunity.description}</p><span className="quiet mono">{opportunity.domain} · {opportunity.week_key}</span></td>
                  <td><StateTag tone={tierTone(opportunity.tier)}>{formatScore(opportunity.composite_score)} · {opportunity.tier}</StateTag></td>
                  <td>{opportunity.evidence_count}</td>
                  <td><StateTag>{opportunity.status}</StateTag></td>
                  <td className="muted">{formatDate(opportunity.created_at)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="action-row"><span className="quiet">Scores are emitted by the backend and retain domain-specific tier thresholds.</span><PageControls path="/opportunities" offset={offset} limit={limit} total={result.total} query={{ status, week, domain, min_score: rawScore }} /></div>
      </Panel>
    </>
  );
}
