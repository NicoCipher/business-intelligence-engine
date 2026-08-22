import { createServer } from "node:http";
import { spawn } from "node:child_process";

const json = (response, body, status = 200) => {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
};

const now = "2026-08-21T12:00:00+00:00";
const db = {
  signals: 1, opportunities: 0, entities: 4, problems: 0, problem_history: 0,
  reports: 1, change_events: 0, watchlists: 0, alert_rules: 0,
  operator_last_seen_at: null, latest_signal: now
};

const api = createServer((request, response) => {
  if (request.headers.authorization !== "Bearer e2e-key") return json(response, { detail: "Invalid API key" }, 401);
  const path = new URL(request.url, "http://127.0.0.1:8100").pathname;
  if (path === "/api/v1/health") return json(response, { status: "ok", version: "1.0.0", db });
  if (path === "/api/v1/signals/stats") return json(response, { total_signals: 1, total_opps: 0, signals_this_week: 1, latest_collection: now, by_source: { hn: 1 }, top_tags: [{ tag: "demand_signal", count: 1 }] });
  if (path === "/api/v1/signals") return json(response, { signals: [{ id: "s1", source: "hn", title: "Evidence from an external source", url: "https://example.com/evidence", domain: "business", engagement: 7, tags: ["demand_signal"], collected_at: now, processed: true }], total: 1, limit: 50, offset: 0 });
  if (path === "/api/v1/opportunities") return json(response, { opportunities: [], total: 0, limit: 20, offset: 0 });
  if (path === "/api/v1/problems") return json(response, { problems: [], total: 0, limit: 20, offset: 0 });
  if (path === "/api/v1/reports/latest" || path === "/api/v1/reports/2026-W34") return json(response, { id: "r1", week_key: "2026-W34", domain: "business", period_start: "2026-08-17", period_end: "2026-08-23", opp_count: 0, signal_count: 1, created_at: now, content: { executive_summary: "One signal was retained.", zero_opportunities_explanation: { summary: "Evidence did not meet persistence thresholds." }, watch_list: [{ title: "Track sparse demand" }] } });
  if (path === "/api/v1/reports") return json(response, { reports: [{ week_key: "2026-W34", period_start: "2026-08-17", period_end: "2026-08-23", opp_count: 0, signal_count: 1, created_at: now }], total: 1 });
  return json(response, { detail: "Not found" }, 404);
});

api.listen(8100, "127.0.0.1", () => {
  const next = spawn("npm", ["run", "dev", "--", "--port", "3100"], {
    env: { ...process.env, BIA_API_BASE_URL: "http://127.0.0.1:8100", BIA_API_KEY: "e2e-key" },
    stdio: "inherit"
  });
  const stop = () => { next.kill("SIGTERM"); api.close(); };
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
  next.on("exit", (code) => { if (code && code !== 0) process.exit(code); });
});
