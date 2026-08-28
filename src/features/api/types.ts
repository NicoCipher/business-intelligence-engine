export type ApiHealth = {
  status: string;
  version: string;
  db: {
    signals: number;
    opportunities: number;
    entities: number;
    problems: number;
    problem_history: number;
    reports: number;
    change_events: number;
    watchlists: number;
    alert_rules: number;
    operator_last_seen_at: string | null;
    latest_signal: string | null;
  };
};

export type Signal = {
  id: string;
  source: string;
  title: string;
  url: string;
  domain: string;
  engagement: number;
  tags: string[];
  collected_at: string;
  processed: boolean;
};

export type SignalStats = {
  total_signals: number;
  total_opps: number;
  signals_this_week: number;
  latest_collection: string | null;
  by_source: Record<string, number>;
  top_tags: Array<{ tag: string; count: number }>;
};

export type Paginated = {
  total: number;
  limit: number;
  offset: number;
};

export type Opportunity = {
  id: string;
  title: string;
  description: string;
  composite_score: number;
  tier: string;
  status: string;
  week_key: string;
  domain: string;
  evidence_count: number;
  scores: Record<string, unknown>;
  created_at: string;
};

export type OpportunityDetail = Opportunity & {
  signal_ids: string[];
  evidence: Array<{
    id: string;
    source: string;
    title: string;
    url: string;
    engagement: number;
    tags: string[];
    collected_at: string;
  }>;
};

export type Problem = {
  id: string;
  title: string;
  domain: string;
  lifecycle_state: string;
  trend: string;
  weeks_seen: number;
  first_seen: string;
  last_seen: string;
};

export type ProblemDetail = Problem & {
  entity_ids: string[];
  history_count: number;
  linked_opportunities: Array<{
    id: string;
    title: string;
    composite_score: number;
    tier: string;
    status: string;
    week_key: string;
  }>;
};

export type ProblemHistory = {
  problem_id: string;
  history: Array<{
    id: string;
    event_type: string;
    occurred_at: string;
    week_key: string;
    opportunity_id: string;
    metadata: Record<string, unknown>;
  }>;
  total: number;
  limit: number;
  offset: number;
};

export type ChangeEvent = {
  id: string;
  domain: string;
  event_type: string;
  entity_ref_type: "problem" | "opportunity";
  entity_ref_id: string;
  entity_title: string | null;
  previous_value: string;
  new_value: string;
  significance: "normal" | "high";
  detected_at: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type UnseenChanges = {
  changes: ChangeEvent[];
  total_unseen: number;
  since: string | null;
  snapshot_at: string;
  limit: number;
  offset: number;
};

export type AckResponse = {
  last_seen_at: string;
};

export type ReportSummary = {
  week_key: string;
  period_start: string;
  period_end: string;
  opp_count: number;
  signal_count: number;
  created_at: string;
};

export type ReportDetail = ReportSummary & {
  id: string;
  domain: string;
  content: ReportContent;
};

export type ReportContent = {
  executive_summary?: string;
  closing_synthesis?: string;
  zero_opportunities_explanation?: unknown;
  watch_list?: unknown[];
  trend_analysis?: unknown[];
  comparison_to_last_period?: unknown;
  opportunities?: unknown[];
  summary?: Record<string, unknown>;
  signal_breakdown?: Record<string, unknown>;
  top_tags?: Array<{ tag?: string; count?: number }>;
};
