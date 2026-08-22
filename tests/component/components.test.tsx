import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState, ExternalEvidenceLink, StateTag } from "@/src/features/shared/components";
import { ReportNarrative } from "@/src/features/reports/report-content";
import RootError from "@/app/error";

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
