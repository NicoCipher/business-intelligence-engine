import { Suspense } from "react";
import { connection } from "next/server";

import { AttentionQueue, ChangeVisibility, IntelligenceSnapshot, LatestReportPanel, OperatingState, RecentSignalsPanel } from "@/src/features/overview/overview-sections";
import { PageHeading } from "@/src/features/shared/components";

function PanelSkeleton() {
  return <div className="panel skeleton" aria-busy="true" aria-label="Loading operational data" />;
}

export default async function OverviewPage() {
  await connection();
  return (
    <>
      <PageHeading eyebrow="System overview" title="BIA operations" description="A factual view of current intelligence availability, evidence freshness, and conditions requiring operator attention." />
      <div className="section-grid">
        <div className="span-6"><Suspense fallback={<PanelSkeleton />}><OperatingState /></Suspense></div>
        <div className="span-6"><Suspense fallback={<PanelSkeleton />}><AttentionQueue /></Suspense></div>
        <div className="span-12"><ChangeVisibility /></div>
        <div className="span-5"><Suspense fallback={<PanelSkeleton />}><IntelligenceSnapshot /></Suspense></div>
        <div className="span-7"><Suspense fallback={<PanelSkeleton />}><LatestReportPanel /></Suspense></div>
        <div className="span-12"><Suspense fallback={<PanelSkeleton />}><RecentSignalsPanel /></Suspense></div>
      </div>
    </>
  );
}
