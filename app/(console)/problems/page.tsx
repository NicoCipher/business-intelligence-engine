import Link from "next/link";
import { connection } from "next/server";

import { getProblems } from "@/src/features/api/client";
import { EmptyState, PageControls, PageHeading, Panel, StateTag, TableScroll } from "@/src/features/shared/components";
import { formatDate, formatNumber } from "@/src/features/shared/format";
import { boundedInteger, singleValue, type SearchParams } from "@/src/features/shared/search-params";

type Props = { searchParams: Promise<SearchParams> };

const sorts = new Set(["recent", "persistent", "significant"]);

function toneForTrend(trend: string) {
  if (trend === "growing") return "good" as const;
  if (trend === "declining") return "warning" as const;
  return "default" as const;
}

export default async function ProblemsPage({ searchParams }: Props) {
  await connection();
  const params = await searchParams;
  const domain = singleValue(params.domain);
  const lifecycleState = singleValue(params.lifecycle_state);
  const trend = singleValue(params.trend);
  const sortCandidate = singleValue(params.sort);
  const sort = sortCandidate && sorts.has(sortCandidate) ? sortCandidate as "recent" | "persistent" | "significant" : "recent";
  const offset = boundedInteger(singleValue(params.offset), 0, 1_000_000);
  const limit = 20;
  const result = await getProblems({ domain, lifecycle_state: lifecycleState, trend, sort, offset, limit });

  return (
    <>
      <PageHeading eyebrow="Canonical intelligence" title="Problems" description="Persistent market-pain identities. Current lifecycle and trend fields summarize status; the append-only history remains the evidence of evolution." />
      <Panel title="Problem register" action={<span className="mono quiet">{formatNumber(result.total)} canonical records</span>}>
        <form className="filter-bar" method="get" aria-label="Filter problems">
          <label className="field">Domain<input name="domain" defaultValue={domain} placeholder="e.g. business" /></label>
          <label className="field">Lifecycle<input name="lifecycle_state" defaultValue={lifecycleState} placeholder="e.g. active" /></label>
          <label className="field">Trend<input name="trend" defaultValue={trend} placeholder="e.g. growing" /></label>
          <label className="field">Sort<select name="sort" defaultValue={sort}><option value="recent">Most recent</option><option value="persistent">Most persistent</option><option value="significant">Most significant</option></select></label>
          <button type="submit">Apply filters</button>
        </form>
        {result.problems.length === 0 ? <EmptyState title="No canonical Problems match this view.">A Problem is created only after the backend’s detection and canonicalization conditions are met.</EmptyState> : (
          <TableScroll label="Problem register table">
            <table className="data-table">
              <thead><tr><th scope="col">Problem</th><th scope="col">Lifecycle</th><th scope="col">Trend</th><th scope="col">Evidence cadence</th><th scope="col">Last seen</th></tr></thead>
              <tbody>{result.problems.map((problem) => (
                <tr key={problem.id}>
                  <td className="title-cell"><Link href={`/problems/${encodeURIComponent(problem.id)}`}>{problem.title}</Link><span className="quiet mono">{problem.domain}</span></td>
                  <td><StateTag tone={problem.lifecycle_state === "active" ? "good" : "default"}>{problem.lifecycle_state}</StateTag></td>
                  <td><StateTag tone={toneForTrend(problem.trend)}>{problem.trend}</StateTag></td>
                  <td>{problem.weeks_seen} weeks</td>
                  <td className="muted">{formatDate(problem.last_seen)}</td>
                </tr>
              ))}</tbody>
            </table>
          </TableScroll>
        )}
        <div className="action-row"><span className="quiet">Significance is derived from the best linked Opportunity; Problems are intentionally not scored directly.</span><PageControls path="/problems" offset={offset} limit={limit} total={result.total} query={{ domain, lifecycle_state: lifecycleState, trend, sort }} /></div>
      </Panel>
    </>
  );
}
