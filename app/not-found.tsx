import Link from "next/link";

export default function NotFound() {
  return (
    <main className="content">
      <p className="eyebrow">Not found</p>
      <h1>The requested BIA record is unavailable.</h1>
      <p className="lede">It may have an invalid identifier or is no longer exposed by the current backend contract.</p>
      <p><Link className="button-link" href="/overview">Return to overview</Link></p>
    </main>
  );
}
