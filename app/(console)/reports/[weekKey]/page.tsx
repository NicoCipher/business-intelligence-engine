import { notFound } from "next/navigation";
import { connection } from "next/server";

import { BackendApiError, getReport } from "@/src/features/api/client";
import { ReportNarrative } from "@/src/features/reports/report-content";
import { PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate } from "@/src/features/shared/format";

type Props = { params: Promise<{ weekKey: string }> };

export default async function ReportDetailPage({ params }: Props) {
  await connection();
  const { weekKey } = await params;
  let report;
  try {
    report = await getReport(weekKey);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) notFound();
    throw error;
  }
  return (
    <>
      <PageHeading eyebrow="Weekly briefing" title={report.week_key} description={`${report.period_start} to ${report.period_end}. Report narrative is backend-produced text and rendered without HTML.`} />
      <div className="detail-grid">
        <Panel title="Intelligence briefing"><div className="panel-body"><ReportNarrative content={report.content} /></div></Panel>
        <div className="stack">
          <Panel title="Report metadata"><div className="panel-body"><dl className="key-value"><dt>Domain</dt><dd><StateTag>{report.domain}</StateTag></dd><dt>Generated</dt><dd>{formatDate(report.created_at)}</dd><dt>Signals</dt><dd>{report.signal_count}</dd><dt>Opportunities</dt><dd><StateTag tone={report.opp_count > 0 ? "good" : "warning"}>{report.opp_count}</StateTag></dd></dl></div></Panel>
          <Panel title="Contract note"><div className="panel-body"><p className="muted">Reports are stored per week and domain, but the current retrieval endpoint accepts only the week key. This is safe for the single active domain today and must be corrected before a multi-domain report UI is exposed.</p></div></Panel>
        </div>
      </div>
    </>
  );
}
