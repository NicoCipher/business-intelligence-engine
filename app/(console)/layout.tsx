import Link from "next/link";

import { NavLink } from "@/src/features/navigation/nav-link";

const navigation = [
  { href: "/overview", label: "Overview" },
  { href: "/signals", label: "Signals" },
  { href: "/problems", label: "Problems" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/reports", label: "Reports" },
  { href: "/system", label: "System health" }
];

export default function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="console-shell">
      <aside className="side-nav" aria-label="Primary navigation">
        <Link className="brand" href="/overview" aria-label="BIA Operations Console overview">
          <span className="brand-mark" aria-hidden="true">BIA</span>
          <span>
            <span className="brand-name">Operations Console</span>
            <span className="brand-caption">Evidence workstation</span>
          </span>
        </Link>
        <p className="nav-label">Intelligence operations</p>
        <nav>
          <ul className="nav-list">
            {navigation.map((item) => (
              <li key={item.href}><NavLink {...item} /></li>
            ))}
          </ul>
        </nav>
        <p className="nav-footer">Internal use only<br />Server-rendered evidence views</p>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbar-note">BIA operational intelligence</span>
          <span className="topbar-scope">Private operator workspace</span>
        </header>
        <main className="content" id="main-content">{children}</main>
      </div>
    </div>
  );
}
