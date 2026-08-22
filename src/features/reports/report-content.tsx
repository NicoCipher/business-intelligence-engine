import { StateTag } from "@/src/features/shared/components";
import type { ReportContent } from "@/src/features/api/types";

function text(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function listLabel(value: unknown, index: number) {
  const item = record(value);
  if (!item) return `Evidence item ${index + 1}`;
  return text(item.title) ?? text(item.theme) ?? text(item.name) ?? text(item.reason) ?? `Evidence item ${index + 1}`;
}

export function ReportNarrative({ content }: Readonly<{ content: ReportContent }>) {
  const executive = text(content.executive_summary);
  const closing = text(content.closing_synthesis);
  const zeroExplanation = text(content.zero_opportunities_explanation) ?? text(record(content.zero_opportunities_explanation)?.summary);
  const watchList = Array.isArray(content.watch_list) ? content.watch_list : [];
  const trends = Array.isArray(content.trend_analysis) ? content.trend_analysis : [];
  const summary = record(content.summary);

  return (
    <div className="stack">
      {executive ? <section className="notice info"><strong>Executive summary</strong><br />{executive}</section> : null}
      {zeroExplanation ? <section className="notice"><strong>No qualified opportunity</strong><br />{zeroExplanation}</section> : null}
      {summary ? <section><h2>Report scope</h2><div className="tag-row" style={{ marginTop: ".65rem" }}>{Object.entries(summary).filter(([, value]) => typeof value === "string" || typeof value === "number").map(([key, value]) => <StateTag key={key}>{key.replaceAll("_", " ")} · {String(value)}</StateTag>)}</div></section> : null}
      {watchList.length > 0 ? <section><h2>Diagnostic watch list</h2><ol className="timeline" style={{ marginTop: ".75rem" }}>{watchList.map((item, index) => <li key={`${listLabel(item, index)}-${index}`}><div className="timeline-event">{listLabel(item, index)}</div></li>)}</ol></section> : null}
      {trends.length > 0 ? <section><h2>Trend analysis</h2><ol className="timeline" style={{ marginTop: ".75rem" }}>{trends.map((item, index) => <li key={`${listLabel(item, index)}-${index}`}><div className="timeline-event">{listLabel(item, index)}</div></li>)}</ol></section> : null}
      {closing ? <section className="notice info"><strong>Closing synthesis</strong><br />{closing}</section> : null}
    </div>
  );
}
