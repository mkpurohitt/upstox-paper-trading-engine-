import React from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, BarChart3, Cable, Coins, ListChecks, Play, RefreshCw, Square, Wallet } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";

type Summary = {
  mode: string;
  capital: { starting_capital: number; current_capital: number; available_margin: number };
  positions: Array<{ id: string; strategy_id: string; instrument_key: string; quantity: number; avg_price: number; ltp: number; mtm: number; realized_pnl: number; unrealized_pnl: number }>;
  open_orders: Array<{ id: string; instrument_key: string; side: string; quantity: number; price: number; status: string }>;
  signals: Array<{ id: string; strategy_id: string; instrument_key: string; side: string; quantity: number; limit_price: number; status: string; reason: string }>;
  rms_events: Array<{ id: string; severity: string; event_type: string; message: string; created_at: string }>;
  reconciliation_events: Array<{ id: string; status: string; signal_id?: string; order_id?: string; fill_id?: string; created_at: string }>;
  pnl: { realized: number; unrealized: number; mtm: number };
};

type Strategy = { id: string; name: string; version: string; enabled: boolean; config: Record<string, unknown> };
type Tick = { instrument_key: string; ltp: number; bid?: number; ask?: number; greeks?: Record<string, number>; timestamp: string };
type BrokerConnection = {
  live_token_configured: boolean;
  sandbox_enabled: boolean;
  login_url: string;
  sandbox_apps_url?: string;
  live_token?: { saved: boolean; received_at?: string };
  sandbox_token?: { saved: boolean; received_at?: string };
};

const apiBase = import.meta.env.VITE_API_BASE_URL || import.meta.env.PUBLIC_API_BASE_URL || "http://localhost:8000";
const wsBase = import.meta.env.VITE_WS_BASE_URL || import.meta.env.PUBLIC_WS_BASE_URL || "ws://localhost:8000";

function useApi<T>(path: string, fallback: T, interval = 2500) {
  const [data, setData] = React.useState<T>(fallback);
  const [loading, setLoading] = React.useState(true);
  const load = React.useCallback(async () => {
    const response = await fetch(`${apiBase}${path}`);
    setData(await response.json());
    setLoading(false);
  }, [path]);
  React.useEffect(() => {
    load().catch(() => setLoading(false));
    const id = window.setInterval(() => load().catch(() => undefined), interval);
    return () => window.clearInterval(id);
  }, [interval, load]);
  return { data, loading, refresh: load };
}

function useMarketStream() {
  const [ticks, setTicks] = React.useState<Tick[]>([]);
  React.useEffect(() => {
    const socket = new WebSocket(`${wsBase}/ws/market-data`);
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.payload?.instrument_key) return;
      setTicks((current) => [message.payload, ...current.filter((tick) => tick.instrument_key !== message.payload.instrument_key)].slice(0, 30));
    };
    return () => socket.close();
  }, []);
  return ticks;
}

function App() {
  const summary = useApi<Summary>("/dashboard/summary", emptySummary);
  const strategies = useApi<Strategy[]>("/strategies", []);
  const broker = useApi<BrokerConnection>("/broker/connect", { live_token_configured: false, sandbox_enabled: false, login_url: "" }, 10000);
  const ticks = useMarketStream();
  const chartData = React.useMemo(() => ticks.slice().reverse().map((tick, index) => ({ index, ltp: tick.ltp })), [ticks]);
  const [capitalDraft, setCapitalDraft] = React.useState("");

  React.useEffect(() => {
    setCapitalDraft(String(summary.data.capital.starting_capital || ""));
  }, [summary.data.capital.starting_capital]);

  async function runStrategy(id: string) {
    await fetch(`${apiBase}/strategies/run/${id}`, { method: "POST" });
    await summary.refresh();
  }

  async function stopStrategy(id: string) {
    await fetch(`${apiBase}/strategies/stop/${id}`, { method: "POST" });
    await summary.refresh();
  }

  async function updateCapital(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await fetch(`${apiBase}/capital`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starting_capital: Number(form.get("capital")) }),
    });
    await summary.refresh();
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>Upstox Paper Trading</h1>
          <p>Live data, sandbox execution, strategy RMS, P&L, and audit trail.</p>
        </div>
        <div className="topActions">
          <button onClick={() => broker.data.login_url && (window.location.href = broker.data.login_url)} title="Connect Upstox">
            <Cable size={18} /> {broker.data.live_token_configured ? "Live Connected" : "Live Login"}
          </button>
          <button onClick={() => broker.data.sandbox_apps_url && window.open(broker.data.sandbox_apps_url, "_blank")} title="Open Upstox sandbox apps">
            <Cable size={18} /> {broker.data.sandbox_enabled ? "Sandbox Token OK" : "Sandbox Token"}
          </button>
          <button className="iconButton" onClick={() => summary.refresh()} title="Refresh dashboard">
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      <section className="metrics">
        <Metric icon={<Wallet />} label="Capital" value={money(summary.data.capital.current_capital)} sub={`Available ${money(summary.data.capital.available_margin)}`} />
        <Metric icon={<Coins />} label="P&L" value={money(summary.data.pnl.mtm)} sub={`R ${money(summary.data.pnl.realized)} / U ${money(summary.data.pnl.unrealized)}`} />
        <Metric icon={<Cable />} label="Mode" value={summary.data.mode.toUpperCase()} sub={ticks.length ? "market stream active" : "waiting for ticks"} />
        <Metric icon={<AlertTriangle />} label="RMS Events" value={String(summary.data.rms_events.length)} sub="latest visible below" />
      </section>

      <section className="workspace">
        <div className="panel marketPanel">
          <div className="panelHead">
            <h2><Activity size={18} /> Market Data</h2>
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <XAxis dataKey="index" hide />
                <YAxis domain={["auto", "auto"]} width={58} />
                <Tooltip />
                <Line type="monotone" dataKey="ltp" stroke="#0f766e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <table>
            <thead><tr><th>Instrument</th><th>LTP</th><th>Bid</th><th>Ask</th><th>Delta</th></tr></thead>
            <tbody>
              {ticks.map((tick) => (
                <tr key={tick.instrument_key}>
                  <td>{tick.instrument_key}</td><td>{tick.ltp}</td><td>{tick.bid ?? "-"}</td><td>{tick.ask ?? "-"}</td><td>{tick.greeks?.delta ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panelHead">
            <h2><Play size={18} /> Strategies</h2>
          </div>
          <div className="strategyList">
            {strategies.data.map((strategy) => (
              <div className="rowCard" key={strategy.id}>
                <div>
                  <strong>{strategy.name}</strong>
                  <span>{strategy.version} | {String(strategy.config.instrument_key ?? "configured universe")}</span>
                </div>
                <div className="actions">
                  <button title="Run strategy" onClick={() => runStrategy(strategy.id)}><Play size={16} /></button>
                  <button title="Stop strategy" onClick={() => stopStrategy(strategy.id)}><Square size={16} /></button>
                </div>
              </div>
            ))}
          </div>
          <form className="capitalForm" onSubmit={updateCapital}>
            <label htmlFor="capital">Virtual capital</label>
            <input id="capital" name="capital" type="number" value={capitalDraft} onChange={(event) => setCapitalDraft(event.target.value)} />
            <button type="submit"><Wallet size={16} /> Update</button>
          </form>
        </div>
      </section>

      <section className="tables">
        <TablePanel title="Positions" icon={<BarChart3 size={18} />} headers={["Instrument", "Qty", "Avg", "LTP", "MTM"]} rows={summary.data.positions.map((p) => [p.instrument_key, p.quantity, p.avg_price, p.ltp, money(p.mtm)])} />
        <TablePanel title="Orders" icon={<ListChecks size={18} />} headers={["Instrument", "Side", "Qty", "Price", "Status"]} rows={summary.data.open_orders.map((o) => [o.instrument_key, o.side, o.quantity, o.price, o.status])} />
        <TablePanel title="Signals" icon={<Activity size={18} />} headers={["Strategy", "Instrument", "Side", "Qty", "Status"]} rows={summary.data.signals.map((s) => [s.strategy_id, s.instrument_key, s.side, s.quantity, s.status])} />
        <TablePanel title="RMS" icon={<AlertTriangle size={18} />} headers={["Severity", "Type", "Message"]} rows={summary.data.rms_events.map((e) => [e.severity, e.event_type, e.message])} />
        <TablePanel title="Reconciliation" icon={<Cable size={18} />} headers={["Status", "Signal", "Order", "Fill"]} rows={summary.data.reconciliation_events.map((e) => [e.status, e.signal_id ?? "-", e.order_id ?? "-", e.fill_id ?? "-"])} />
      </section>
    </main>
  );
}

function Metric(props: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return <div className="metric"><div className="metricIcon">{props.icon}</div><div><span>{props.label}</span><strong>{props.value}</strong><small>{props.sub}</small></div></div>;
}

function TablePanel(props: { title: string; icon: React.ReactNode; headers: string[]; rows: Array<Array<string | number>> }) {
  return (
    <div className="panel">
      <div className="panelHead"><h2>{props.icon}{props.title}</h2></div>
      <table>
        <thead><tr>{props.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>{props.rows.length ? props.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>) : <tr><td colSpan={props.headers.length}>No records yet</td></tr>}</tbody>
      </table>
    </div>
  );
}

function money(value: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value || 0);
}

const emptySummary: Summary = {
  mode: "paper",
  capital: { starting_capital: 0, current_capital: 0, available_margin: 0 },
  positions: [],
  open_orders: [],
  signals: [],
  rms_events: [],
  reconciliation_events: [],
  pnl: { realized: 0, unrealized: 0, mtm: 0 },
};

createRoot(document.getElementById("root")!).render(<App />);
