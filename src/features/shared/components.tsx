import Link from "next/link";

import { safeExternalUrl } from "@/src/features/shared/format";

export function PageHeading({
  eyebrow,
  title,
  description,
  children
}: Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}>) {
  return (
    <header className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lede">{description}</p>
      </div>
      {children}
    </header>
  );
}

export function Panel({ title, action, children }: Readonly<{
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}>) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function StateTag({ children, tone = "default" }: Readonly<{
  children: React.ReactNode;
  tone?: "default" | "good" | "warning" | "danger" | "info";
}>) {
  return <span className={`tag${tone === "default" ? "" : ` ${tone}`}`}>{children}</span>;
}

export function ExternalEvidenceLink({ href, children }: Readonly<{ href: string; children: React.ReactNode }>) {
  const safeUrl = safeExternalUrl(href);
  if (!safeUrl) return <span className="quiet">External URL unavailable</span>;
  return <a href={safeUrl} target="_blank" rel="noopener noreferrer">{children}</a>;
}

export function EmptyState({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return <div className="empty"><strong>{title}</strong><span>{children}</span></div>;
}

export function TableScroll({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      <p className="table-scroll-hint" aria-hidden="true">Scroll horizontally to view all columns.</p>
      {children}
    </div>
  );
}

export function PageControls({
  path,
  offset,
  limit,
  total,
  query
}: Readonly<{
  path: string;
  offset: number;
  limit: number;
  total: number;
  query: Record<string, string | undefined>;
}>) {
  const toHref = (nextOffset: number) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
    params.set("offset", String(nextOffset));
    return `${path}?${params.toString()}`;
  };
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + limit, total);

  return (
    <div className="pagination" aria-label="Pagination">
      <span>{start}–{end} of {total}</span>
      {offset > 0 ? <Link className="button-link" href={toHref(Math.max(0, offset - limit))}>Previous</Link> : null}
      {offset + limit < total ? <Link className="button-link" href={toHref(offset + limit)}>Next</Link> : null}
    </div>
  );
}
