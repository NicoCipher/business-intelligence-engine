import { getSignals } from "@/src/features/api/client";
import { connection } from "next/server";
import { EmptyState, ExternalEvidenceLink, PageControls, PageHeading, Panel, StateTag } from "@/src/features/shared/components";
import { formatDate, formatNumber } from "@/src/features/shared/format";
import { boundedInteger, singleValue, type SearchParams } from "@/src/features/shared/search-params";

type Props = { searchParams: Promise<SearchParams> };

export default async function SignalsPage({ searchParams }: Props) {
  await connection();
  const params = await searchParams;
  const source = singleValue(params.source);
  const tag = singleValue(params.tag);
  const domain = singleValue(params.domain);
  const offset = boundedInteger(singleValue(params.offset), 0, 1_000_000);
  const limit = 50;
  const result = await getSignals({ source, tag, domain, offset, limit });

  return (
    <>
      <PageHeading eyebrow="Raw evidence" title="Signals" description="Immutable observations collected before interpretation. Titles and tags are untrusted external text and are rendered as text only." />
      <Panel title="Observed signal feed" action={<span className="mono quiet">{formatNumber(result.total)} retained</span>}>
        <form className="filter-bar" method="get" aria-label="Filter signals">
          <label className="field">Source<input name="source" defaultValue={source} placeholder="e.g. hn" /></label>
          <label className="field">Tag<input name="tag" defaultValue={tag} placeholder="e.g. demand_signal" /></label>
          <label className="field">Domain<input name="domain" defaultValue={domain} placeholder="e.g. business" /></label>
          <button type="submit">Apply filters</button>
        </form>
        {result.signals.length === 0 ? <EmptyState title="No signals match these filters.">Unknown filter values return no results under the existing backend contract.</EmptyState> : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead><tr><th scope="col">Evidence</th><th scope="col">Source</th><th scope="col">Engagement</th><th scope="col">Observed</th><th scope="col">State</th></tr></thead>
              <tbody>{result.signals.map((signal) => (
                <tr key={signal.id}>
                  <td className="title-cell"><ExternalEvidenceLink href={signal.url}>{signal.title}</ExternalEvidenceLink><span className="tag-row">{signal.tags.map((item) => <StateTag key={item}>{item}</StateTag>)}</span></td>
                  <td><StateTag tone="info">{signal.source}</StateTag><div className="quiet" style={{ marginTop: ".35rem" }}>{signal.domain}</div></td>
                  <td className="mono">{formatNumber(signal.engagement)}</td>
                  <td className="muted">{formatDate(signal.collected_at)}</td>
                  <td><StateTag tone={signal.processed ? "good" : "warning"}>{signal.processed ? "processed" : "pending"}</StateTag></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="action-row"><span className="quiet">Showing server-paginated evidence. Raw content is not exposed by the current API.</span><PageControls path="/signals" offset={offset} limit={limit} total={result.total} query={{ source, tag, domain }} /></div>
      </Panel>
    </>
  );
}
