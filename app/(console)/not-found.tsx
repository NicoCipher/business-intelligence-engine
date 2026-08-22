import Link from "next/link";

export default function ConsoleNotFound() {
  return <section className="panel"><div className="empty"><strong>That operational record was not found.</strong><span>The backend returned no record for this route. <Link href="/overview">Return to overview</Link>.</span></div></section>;
}
