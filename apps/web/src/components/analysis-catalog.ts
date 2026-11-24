import {
  ArrowLeftRight,
  BarChart3,
  Binary,
  Building2,
  CandlestickChart,
  Filter,
  Globe2,
  Layers,
  type LucideIcon,
  Network,
  Scale,
  Sigma,
  Split,
} from "lucide-react";

export interface DashboardTile {
  slug: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tags: string[];
}

export const DASHBOARDS: DashboardTile[] = [
  { slug: "charts", title: "Charts", description: "Full charting terminal: 15 timeframes, 9 chart types, 32 indicators, drawing tools, multi-chart layouts, alerts and replay on live Upstox data", icon: CandlestickChart, tags: ["charts", "live", "terminal"] },
  { slug: "market-overview", title: "Market Overview", description: "Indices, sector heatmap, FII/DII flows, breadth, movers and OI gainers", icon: Globe2, tags: ["live", "breadth"] },
  { slug: "option-chain", title: "Option Chain", description: "Live chain with OI, ΔOI, IV, Greeks, PCR, max pain, IV skew and OI buildup", icon: Layers, tags: ["options", "live"] },
  { slug: "arbitrage", title: "Arbitrage Scanner", description: "Cash-futures basis, calendar spreads, NSE-BSE gaps and put-call parity breaks", icon: ArrowLeftRight, tags: ["scanner", "live"] },
  { slug: "ratio-spreads", title: "Ratio Spread Scanner", description: "1x2 / 1x3 ratio spreads filtered by premium and delta, with payoff charts", icon: Split, tags: ["options", "scanner"] },
  { slug: "straddle", title: "Straddle / Strangle", description: "Combined premium, IV vs HV, breakevens and decay tracking", icon: Binary, tags: ["options"] },
  { slug: "fly-condor", title: "Butterfly / Iron Fly / Condor", description: "Builder with payoff, Greeks and probability of profit", icon: Network, tags: ["options", "builder"] },
  { slug: "options-builder", title: "Options Strategy Builder", description: "Multi-leg payoff calculator with what-if on spot, IV and days", icon: Scale, tags: ["options", "builder"] },
  { slug: "technical", title: "Technical Dashboard", description: "Multi-timeframe chart, indicators, patterns, support/resistance", icon: CandlestickChart, tags: ["charts"] },
  { slug: "fundamental", title: "Fundamental Dashboard", description: "Financials, ratios, peer comparison and shareholding pattern", icon: Building2, tags: ["fundamentals"] },
  { slug: "quant", title: "Quantitative Dashboard", description: "Return distribution, vol regimes, correlation, beta and seasonality", icon: Sigma, tags: ["quant"] },
  { slug: "pairs", title: "Pair Trading", description: "Engle-Granger / Johansen cointegration, spread z-score, half-life, signals", icon: BarChart3, tags: ["quant", "stat-arb"] },
  { slug: "screener", title: "Screener", description: "Technical + fundamental query builder, saved screens and scheduled alerts", icon: Filter, tags: ["scanner"] },
];
