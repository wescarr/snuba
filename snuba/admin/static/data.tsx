import RuntimeConfig from "./runtime_config";
import AuditLog from "./runtime_config/auditlog";
import ClickhouseQueries from "./clickhouse_queries";
import TracingQueries from "./tracing";
import RateLimits from "./ratelimits";

function Placeholder(props: any) {
  return null;
}

const NAV_ITEMS = [
  { id: "overview", display: "Overview", component: Placeholder },
  { id: "config", display: "Runtime config", component: RuntimeConfig },
  {
    id: "clickhouse",
    display: "ClickHouse🏚️",
    component: ClickhouseQueries,
  },
  {
    id: "tracing",
    display: "Tracing 🔎",
    component: TracingQueries,
  },
  {
    id: "auditlog",
    display: "Audit log",
    component: AuditLog,
  },
  {
    id: "ratelimits",
    display: "Rate Limits 📉",
    component: RateLimits,
  },
];

export { NAV_ITEMS };
