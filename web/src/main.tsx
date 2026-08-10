import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { render } from "preact";
import { Activity, CheckCircle2, RefreshCw, TerminalSquare, TriangleAlert } from "lucide-preact";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import "./styles.css";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

type Usage = {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  reasoning: number;
  total: number;
};

type Summary = {
  usage: Usage;
  cost_usd: number;
  events: number;
  exact_events: number;
  estimated_events: number;
  models: string[];
  projects: string[];
};

type ModelRow = Summary & { agent: string; model: string; share?: number };
type TimelineRow = Summary & { period: string; model_breakdown: ModelRow[] };
type SourceRow = {
  agent: string;
  available: boolean;
  paths: string[];
  files_scanned: number;
  records_read: number;
  events: number;
  errors: string[];
};
type Snapshot = {
  generated_at: string;
  totals: Summary;
  models: ModelRow[];
  timeline: TimelineRow[];
  sources: SourceRow[];
  warnings: string[];
};
type Options = {
  agents: { value: string; label: string }[];
  ranges: string[];
  granularities: string[];
  models: string[];
};

const EMPTY_OPTIONS: Options = { agents: [], ranges: [], granularities: [], models: [] };
const RANGE_LABELS: Record<string, string> = {
  today: "Today",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
  custom: "Custom",
};
const AGENT_LABELS: Record<string, string> = {
  claude: "Claude Code",
  codex: "Codex",
  opencode: "OpenCode",
  trae: "Trae",
  qoder: "Qoder",
  codebuddy: "CodeBuddy",
};

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [options, setOptions] = useState<Options>(EMPTY_OPTIONS);
  const [agent, setAgent] = useState("all");
  const [model, setModel] = useState("all");
  const [range, setRange] = useState("7d");
  const [granularity, setGranularity] = useState("day");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [selectedBucket, setSelectedBucket] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const baseParams = useMemo(() => {
    const params = new URLSearchParams({ range });
    if (agent !== "all") params.append("agent", agent);
    if (range === "custom" && start) params.set("start", start);
    if (range === "custom" && end) params.set("end", end);
    return params;
  }, [agent, range, start, end]);

  async function loadSnapshot(force = false) {
    if (range === "custom" && !start) return;
    setLoading(true);
    setError("");
    const params = new URLSearchParams(baseParams);
    params.set("granularity", granularity);
    if (model !== "all") params.append("model", model);
    if (force) params.set("refresh", "true");
    try {
      const response = await fetch(`/api/v1/snapshot?${params}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Unable to load usage data");
      setSnapshot(body);
      setSelectedBucket(body.timeline.length ? body.timeline.length - 1 : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load usage data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (range === "custom" && !start) return;
    const controller = new AbortController();
    fetch(`/api/v1/options?${baseParams}`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Unable to load filter options");
        setOptions(body);
        if (model !== "all" && !body.models.includes(model)) setModel("all");
      })
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(reason.message);
      });
    return () => controller.abort();
  }, [baseParams]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadSnapshot(), 180);
    return () => window.clearTimeout(timer);
  }, [agent, model, range, granularity, start, end]);

  const selected = selectedBucket === null ? null : snapshot?.timeline[selectedBucket] || null;
  const generatedAt = snapshot
    ? new Date(snapshot.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "Not scanned";

  return (
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <span class="brand-mark"><TerminalSquare size={21} /></span>
          <div><strong>Agent Usage Monitor</strong><span>Local token analytics</span></div>
        </div>
        <div class="scan-state" aria-live="polite">
          {loading ? <Activity class="spin" size={15} /> : error ? <TriangleAlert size={15} /> : <CheckCircle2 size={15} />}
          <span>{loading ? "Scanning local logs" : error ? "Scan failed" : `Updated ${generatedAt}`}</span>
        </div>
      </header>

      <section class="filter-band" aria-label="Usage filters">
        <label>Agent<select value={agent} onChange={(event) => { setAgent(event.currentTarget.value); setModel("all"); }}><option value="all">All agents</option>{options.agents.map((item) => <option value={item.value}>{item.label}</option>)}</select></label>
        <label>Model<select value={model} onChange={(event) => setModel(event.currentTarget.value)}><option value="all">All models</option>{options.models.map((item) => <option value={item}>{item}</option>)}</select></label>
        <label>Range<select value={range} onChange={(event) => setRange(event.currentTarget.value)}>{(options.ranges.length ? options.ranges : Object.keys(RANGE_LABELS)).map((item) => <option value={item}>{RANGE_LABELS[item] || item}</option>)}</select></label>
        <label>Group<select value={granularity} onChange={(event) => setGranularity(event.currentTarget.value)}>{(options.granularities.length ? options.granularities : ["hour", "day", "week", "month"]).map((item) => <option value={item}>{title(item)}</option>)}</select></label>
        {range === "custom" && <><label>Start<input type="date" value={start} onChange={(event) => setStart(event.currentTarget.value)} /></label><label>End<input type="date" value={end} onChange={(event) => setEnd(event.currentTarget.value)} /></label></>}
        <button class="icon-button" type="button" title="Scan local logs again" aria-label="Refresh usage data" disabled={loading} onClick={() => void loadSnapshot(true)}><RefreshCw size={18} /></button>
      </section>

      <main>
        {error && <div class="error-banner" role="alert"><TriangleAlert size={17} />{error}</div>}
        {snapshot && <>
          <section class="metrics" aria-label="Usage summary">
            <Metric label="Total tokens" value={formatTokens(snapshot.totals.usage.total)} accent="cyan" />
            <Metric label="Input" value={formatTokens(snapshot.totals.usage.input)} accent="green" />
            <Metric label="Output" value={formatTokens(snapshot.totals.usage.output)} accent="amber" />
            <Metric label="Models" value={String(snapshot.models.length)} accent="white" />
          </section>

          <section class="activity-section">
            <div class="section-heading"><div><h2>Token activity</h2><p>{RANGE_LABELS[range]} grouped by {granularity}</p></div><span>{snapshot.totals.events.toLocaleString()} events</span></div>
            <ActivityChart rows={snapshot.timeline} selected={selectedBucket} onSelect={setSelectedBucket} />
            <BucketDetail row={selected} />
          </section>

          <section class="data-grid">
            <div class="data-section"><div class="section-heading"><div><h2>Models</h2><p>Usage by agent and model</p></div></div><ModelTable rows={snapshot.models} /></div>
            <div class="data-section"><div class="section-heading"><div><h2>Sources</h2><p>Local log detection and parsing</p></div></div><SourceTable rows={snapshot.sources} /></div>
          </section>
        </>}
      </main>
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent: string }) {
  return <div class={`metric metric-${accent}`}><span>{label}</span><strong>{value}</strong></div>;
}

function ActivityChart({ rows, selected, onSelect }: { rows: TimelineRow[]; selected: number | null; onSelect: (index: number) => void }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 240,
      grid: { left: 8, right: 8, top: 18, bottom: 28, containLabel: true },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "#171d20",
        borderColor: "#46545a",
        textStyle: { color: "#e6edf3", fontSize: 12 },
        formatter: (items: unknown) => {
          const first = Array.isArray(items) ? items[0] as { dataIndex: number } : items as { dataIndex: number };
          const row = rows[first.dataIndex];
          if (!row) return "";
          return `<b>${escapeHtml(row.period)}</b><br/>Total&nbsp;&nbsp;${formatTokens(row.usage.total)}<br/>Input&nbsp;&nbsp;${formatTokens(row.usage.input)}<br/>Output&nbsp;&nbsp;${formatTokens(row.usage.output)}<br/>Cache&nbsp;&nbsp;${formatTokens(row.usage.cache_read + row.usage.cache_write)}<br/>Events&nbsp;&nbsp;${row.events.toLocaleString()}`;
        },
      },
      xAxis: { type: "category", data: rows.map((row) => row.period), axisTick: { show: false }, axisLine: { lineStyle: { color: "#344047" } }, axisLabel: { color: "#89969c", hideOverlap: true, fontSize: 11 } },
      yAxis: { type: "value", splitNumber: 3, axisLabel: { color: "#89969c", formatter: (value: number) => formatTokens(value) }, splitLine: { lineStyle: { color: "#273137" } } },
      series: [{ type: "bar", data: rows.map((row, index) => ({ value: row.usage.total, itemStyle: { color: index === selected ? "#f2b84b" : "#43a9b5", borderRadius: [2, 2, 0, 0] } })), barMaxWidth: 30, emphasis: { itemStyle: { color: "#70c7d0" } } }],
    });
    chart.on("click", (event) => onSelect((event as { dataIndex: number }).dataIndex));
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [rows, selected]);
  function navigate(event: KeyboardEvent) {
    if (!rows.length || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = selected ?? rows.length - 1;
    if (event.key === "Home") onSelect(0);
    else if (event.key === "End") onSelect(rows.length - 1);
    else if (event.key === "ArrowLeft") onSelect(Math.max(0, current - 1));
    else onSelect(Math.min(rows.length - 1, current + 1));
  }
  return <div class="chart" ref={element} role="img" tabIndex={0} onKeyDown={navigate} aria-label="Token usage over time. Hover or click a bar for details. Use arrow keys to move between periods." />;
}

function BucketDetail({ row }: { row: TimelineRow | null }) {
  if (!row) return <div class="bucket-empty">No activity in the selected range.</div>;
  return <div class="bucket-detail"><div class="bucket-summary"><span>Selected period</span><strong>{row.period}</strong><div>{formatTokens(row.usage.total)} tokens · {row.events.toLocaleString()} events</div></div><div class="token-breakdown"><span><i class="dot input" />Input <b>{formatTokens(row.usage.input)}</b></span><span><i class="dot output" />Output <b>{formatTokens(row.usage.output)}</b></span><span><i class="dot cache" />Cache <b>{formatTokens(row.usage.cache_read + row.usage.cache_write)}</b></span><span><i class="dot reasoning" />Reasoning <b>{formatTokens(row.usage.reasoning)}</b></span></div><div class="bucket-models">{row.model_breakdown.slice(0, 5).map((item) => <div><span>{item.model}<small>{agentLabel(item.agent)}{item.projects.length ? ` · ${item.projects.map(projectLabel).join(", ")}` : ""}</small></span><b>{formatTokens(item.usage.total)}</b></div>)}</div></div>;
}

function ModelTable({ rows }: { rows: ModelRow[] }) {
  if (!rows.length) return <div class="empty-state">No model usage matches the current filters.</div>;
  return <div class="table-scroll"><table><thead><tr><th>Model</th><th>Agent</th><th>Total</th><th>Input</th><th>Output</th><th>Cache</th><th>Events</th></tr></thead><tbody>{rows.map((row) => <tr><td class="primary-cell">{row.model}</td><td>{agentLabel(row.agent)}</td><td>{formatTokens(row.usage.total)}</td><td>{formatTokens(row.usage.input)}</td><td>{formatTokens(row.usage.output)}</td><td>{formatTokens(row.usage.cache_read + row.usage.cache_write)}</td><td>{row.events.toLocaleString()}</td></tr>)}</tbody></table></div>;
}

function SourceTable({ rows }: { rows: SourceRow[] }) {
  return <div class="table-scroll"><table><thead><tr><th>Agent</th><th>Status</th><th>Files</th><th>Records</th><th>Parsed</th></tr></thead><tbody>{rows.map((row) => { const state = row.errors.length ? "Error" : row.events ? "Collecting" : row.available ? "Detected" : "Not found"; return <tr title={row.errors[0] || row.paths.join(", ")}><td class="primary-cell">{agentLabel(row.agent)}</td><td><span class={`status status-${state.toLowerCase().replace(" ", "-")}`}>{state}</span></td><td>{row.files_scanned}</td><td>{row.records_read}</td><td>{row.events}</td></tr>; })}</tbody></table></div>;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(value >= 10_000_000_000 ? 1 : 2)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 1 : 2)}K`;
  return value.toLocaleString();
}
function title(value: string): string { return value.charAt(0).toUpperCase() + value.slice(1); }
function agentLabel(value: string): string { return AGENT_LABELS[value] || title(value); }
function projectLabel(value: string): string {
  const parts = value.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || value;
}
function escapeHtml(value: string): string { return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] || character); }

render(<App />, document.getElementById("app")!);
