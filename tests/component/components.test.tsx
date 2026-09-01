import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NavLink } from "@/src/features/navigation/nav-link";
import { EmptyState, ExternalEvidenceLink, StateTag, TableScroll } from "@/src/features/shared/components";
import { ReportNarrative } from "@/src/features/reports/report-content";
import { CollectorOperations } from "@/src/features/system/collector-operations";
import RootError from "@/app/error";

const { pathname } = vi.hoisted(() => ({ pathname: { current: "/overview" } }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current
}));

describe("external evidence links", () => {
  it("adds safe new-tab protections", () => {
    render(<ExternalEvidenceLink href="https://example.com/proof">Open evidence</ExternalEvidenceLink>);
    const link = screen.getByRole("link", { name: "Open evidence" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("does not render unsafe URLs as links", () => {
    render(<ExternalEvidenceLink href="javascript:alert(1)">Open evidence</ExternalEvidenceLink>);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("External URL unavailable")).toBeTruthy();
  });
});

describe("operational states", () => {
  it("renders durable collector state without inventing a rate-limit cause", () => {
    render(<CollectorOperations collectors={[{
      source: "github", domain: "business", enabled: true, interval_minutes: 240, priority: 4,
      quota: { limit: 10, period_minutes: 60, used: 10, reset_at: "2026-09-02T12:00:00+00:00" },
      last_run_at: "2026-09-01T11:00:00+00:00", last_success_at: "2026-09-01T10:00:00+00:00",
      last_failure_at: "2026-09-01T11:00:00+00:00", consecutive_failures: 2,
      backoff_until: "2026-09-01T13:00:00+00:00", updated_at: "2026-09-01T11:00:00+00:00",
      last_attempt_status: "failed", timing_gate_status: "quota_exhausted", next_due_at: "2026-09-01T15:00:00+00:00"
    }]} />);
    expect(screen.getByRole("region", { name: "Collector operations table" })).toBeTruthy();
    expect(screen.getByText("Quota exhausted")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Failure cause and rate-limit classification are not stored.")).toBeTruthy();
  });

  it("renders empty state context", () => {
    render(<EmptyState title="No opportunities">Read the latest report.</EmptyState>);
    expect(screen.getByText("No opportunities")).toBeTruthy();
    expect(screen.getByText("Read the latest report.")).toBeTruthy();
  });

  it("renders zero-opportunity report diagnostics as text", () => {
    render(<ReportNarrative content={{ zero_opportunities_explanation: { summary: "Evidence did not meet persistence thresholds." }, watch_list: [{ title: "Track sparse demand" }] }} />);
    expect(screen.getByText("Evidence did not meet persistence thresholds.")).toBeTruthy();
    expect(screen.getByText("Track sparse demand")).toBeTruthy();
  });

  it("uses semantic text for status tags", () => {
    render(<StateTag tone="warning">stale</StateTag>);
    expect(screen.getByText("stale")).toBeTruthy();
  });

  it("explains unauthorized backend access without exposing credentials", () => {
    render(<RootError error={new Error("BIA_API_UNAUTHORIZED")} reset={() => undefined} />);
    expect(screen.getByText("Backend access was rejected.")).toBeTruthy();
    expect(screen.queryByText(/server-secret/i)).toBeNull();
  });
});

describe("navigation and responsive evidence regions", () => {
  it("marks the active navigation destination for assistive technology", () => {
    pathname.current = "/signals";
    render(<NavLink href="/signals" label="Signals" />);
    expect(screen.getByRole("link", { name: "Signals" }).getAttribute("aria-current")).toBe("page");
  });

  it("labels a keyboard-focusable evidence table region", () => {
    render(<TableScroll label="Observed signal evidence table"><table><tbody><tr><td>Evidence</td></tr></tbody></table></TableScroll>);
    const region = screen.getByRole("region", { name: "Observed signal evidence table" });
    expect(region.getAttribute("tabindex")).toBe("0");
  });
});
