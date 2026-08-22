"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavLinkProps = {
  href: string;
  label: string;
};

export function NavLink({ href, label }: Readonly<NavLinkProps>) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link className={`nav-link${active ? " active" : ""}`} href={href} aria-current={active ? "page" : undefined}>
      {label}
    </Link>
  );
}
