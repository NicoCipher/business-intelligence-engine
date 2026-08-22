import "server-only";

import type {
  ApiHealth,
  Opportunity,
  OpportunityDetail,
  Paginated,
  Problem,
  ProblemDetail,
  ProblemHistory,
  ReportDetail,
  ReportSummary,
  Signal,
  SignalStats
} from "@/src/features/api/types";

type CachePolicy = { cache: "no-store" } | { next: { revalidate: number } };

export class BackendApiError extends Error {
  constructor(
    readonly status: number,
    readonly endpoint: string
  ) {
    super(status === 401 ? "BIA_API_UNAUTHORIZED" : `BIA_API_${status}`);
    this.name = "BackendApiError";
  }
}

function backendConfig() {
  const baseUrl = process.env.BIA_API_BASE_URL?.replace(/\/$/, "");
  const apiKey = process.env.BIA_API_KEY;

  if (!baseUrl || !apiKey) {
    throw new Error("BIA_API_CONFIGURATION_MISSING");
  }

  return { baseUrl, apiKey };
}

async function request<T>(
  path: string,
  init: RequestInit & CachePolicy
): Promise<T> {
  const { baseUrl, apiKey } = backendConfig();
  const response = await fetch(`${baseUrl}/api/v1${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${apiKey}`,
      ...init.headers
    }
  });

  if (!response.ok) {
    throw new BackendApiError(response.status, path);
  }

  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const getHealth = () => request<ApiHealth>("/health", { cache: "no-store" });

export const getSignalStats = () =>
  request<SignalStats>("/signals/stats", { next: { revalidate: 30 } });

export const getSignals = (params: {
  source?: string;
  tag?: string;
  domain?: string;
  limit?: number;
  offset?: number;
}) =>
  request<Paginated & { signals: Signal[] }>(
    `/signals${query(params)}`,
    { next: { revalidate: 60 } }
  );

export const getOpportunities = (params: {
  status?: string;
  week?: string;
  domain?: string;
  min_score?: number;
  limit?: number;
  offset?: number;
}) =>
  request<Paginated & { opportunities: Opportunity[] }>(
    `/opportunities${query(params)}`,
    { next: { revalidate: 60 } }
  );

export const getOpportunity = (id: string) =>
  request<OpportunityDetail>(`/opportunities/${encodeURIComponent(id)}`, {
    next: { revalidate: 120 }
  });

export const updateOpportunityStatus = (id: string, status: string) =>
  request<{ id: string; status: string }>(`/opportunities/${encodeURIComponent(id)}/status`, {
    method: "PATCH",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });

export const getProblems = (params: {
  domain?: string;
  lifecycle_state?: string;
  trend?: string;
  sort?: "recent" | "persistent" | "significant";
  limit?: number;
  offset?: number;
}) =>
  request<Paginated & { problems: Problem[] }>(
    `/problems${query(params)}`,
    { next: { revalidate: 60 } }
  );

export const getProblem = (id: string) =>
  request<ProblemDetail>(`/problems/${encodeURIComponent(id)}`, {
    next: { revalidate: 120 }
  });

export const getProblemHistory = (id: string, limit = 50, offset = 0) =>
  request<ProblemHistory>(
    `/problems/${encodeURIComponent(id)}/history${query({ limit, offset })}`,
    { next: { revalidate: 120 } }
  );

export const getReports = () =>
  request<{ reports: ReportSummary[]; total: number }>("/reports", {
    next: { revalidate: 300 }
  });

export const getLatestReport = () =>
  request<ReportDetail>("/reports/latest", { next: { revalidate: 300 } });

export const getReport = (weekKey: string) =>
  request<ReportDetail>(`/reports/${encodeURIComponent(weekKey)}`, {
    next: { revalidate: 300 }
  });
