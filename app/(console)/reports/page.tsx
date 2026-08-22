import Link from "next/link";
import { connection } from "next/server";

import { getReports } from "@/src/features/api/client";
import { EmptyState, PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatNumber } from "@/src/features/shared/format";

export default async function ReportsPage() {
  await connection();
  const result = await getReports();
  return (
    <>
      <PageHeading eyebrow="Briefings" title="Reports" description="Persisted weekly intelligence briefings. Reports communicate backend intelligence; they never create or modify it." />
      <Panel title="Available reports" action={<span className="mono quiet">{formatNumber(result.total)} returned</span>}>
        {result.reports.length === 0 ? <EmptyState title="No reports are available.">Report generation is supported by the backend but intentionally not exposed as a Phase 1 console operation.</EmptyState> : <div style={{ overflowX: "auto" }}><table className="data-table"><thead><tr><th scope="col">Period</th><th scope="col">Signals</th><th scope="col">Opportunities</th><th scope="col">Generated</th></tr></thead><tbody>{result.reports.map((report) => <tr key={report.week_key}><td className="title-cell"><Link href={`/reports/${encodeURIComponent(report.week_key)}`}>{report.week_key}</Link><span className="quiet">{report.period_start} → {report.period_end}</span></td><td>{report.signal_count}</td><td><StateTag tone={report.opp_count > 0 ? "good" : "warning"}>{report.opp_count}</StateTag></td><td className="muted">{formatDate(report.created_at)}</td></tr>)}</tbody></table></div>}
        <div className="action-row"><span className="quiet">The existing report-list contract is limited to ten results and is not domain-filterable.</span></div>
      </Panel>
    </>
  );
}
