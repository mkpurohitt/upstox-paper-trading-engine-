"use client";
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import * as React from "react";
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { UnderlyingExpiry } from "@/components/analysis/pickers";
import { axisProps, tooltipStyle } from "@/components/charts/theme";
import { Disclaimer, Stat } from "@/components/common";
import { DashboardHeader, Field } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { apiJson } from "@/lib/api";
import { inr, istTime, num, shortDate } from "@/lib/format";

interface Resp {
  underlying: string;
  expiry: string;
  spot: number;
  lot_size: number;
  type: "straddle" | "strangle";
  call_strike: number;
  put_strike: number;
  call_symbol: string;
  put_symbol: string;
  call_premium: number;
  put_premium: number;
  combined_premium: number;
  breakevens: number[];
  breakeven_pct: number;
  iv: number | null;
  hv20: number | null;
  iv_hv_ratio: number | null;
  theta_per_day: number;
  theta_per_lot: number;
  days_to_expiry: number;
  intraday: { ts: string; ce: number; pe: number; combined: number }[];
  hv_series: { ts: string; hv: number }[];
  decay: { day: number; premium: number }[];
}

export default function StraddlePage() {
  const [underlying, setUnderlying] = React.useState("NIFTY");
  const [expiry, setExpiry] = React.useState<string | undefined>(undefined);
  const [otm, setOtm] = React.useState("0");
  const q = useQuery({
    queryKey: ["straddle", underlying, expiry, otm],
    queryFn: () => apiJson<Resp>(`/api/analysis/straddle?underlying=${underlying}&otm_steps=${otm}${expiry ? `&expiry=${expiry}` : ""}`),
    refetchInterval: 10_000,
  });
  const d = q.data;
  const intraday = React.useMemo(() => (d?.intraday ?? []).map((p) => ({ ...p, t: istTime(p.ts, true) })), [d]);
  const hv = React.useMemo(() => (d?.hv_series ?? []).map((p) => ({ ...p, t: shortDate(p.ts), iv: d?.iv ?? null })), [d]);
  return (
    <div className="mx-auto max-w-[1440px]">
      <DashboardHeader
        icon={Activity}
        title="Straddle / Strangle Dashboard"
        description="ATM straddle or OTM strangle premium, breakevens, IV vs realised volatility and time decay"
        onRefresh={() => void q.refetch()}
        refreshing={q.isFetching}
        filters={
          <>
            <UnderlyingExpiry underlying={underlying} setUnderlying={setUnderlying} expiry={expiry} setExpiry={setExpiry} />
            <Field label="Structure">
              <Select
                value={otm}
                onValueChange={setOtm}
                options={[{ value: "0", label: "ATM straddle" }, ...[1, 2, 3, 5, 8].map((n) => ({ value: String(n), label: `Strangle ±${n} strikes` }))]}
              />
            </Field>
          </>
        }
        csv={d ? { filename: `${underlying}-${d.type}-intraday`, rows: () => d.intraday } : undefined}
        ask={
          d
            ? {
                question: `Is the ${underlying} ${d.type} cheap or expensive right now? Compare IV with realised volatility and the implied move.`,
                context: () => ({ ...d, intraday: d.intraday.slice(-20), hv_series: d.hv_series.slice(-10) }),
              }
            : undefined
        }
      />
      {!d ? (
        <Skeleton className="h-[600px]" />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Stat label="Spot" value={num(d.spot)} />
            <Stat label={d.type === "straddle" ? "Strike" : "Strikes"} value={d.type === "straddle" ? num(d.call_strike, 0) : `${num(d.put_strike, 0)}/${num(d.call_strike, 0)}`} />
            <Stat label="Combined premium" value={num(d.combined_premium)} hint={`CE ${num(d.call_premium)} + PE ${num(d.put_premium)}`} />
            <Stat label="Per lot" value={inr(d.combined_premium * d.lot_size, { decimals: 0 })} hint={`lot ${d.lot_size}`} />
            <Stat label="Breakevens" value={`${num(d.breakevens[0], 0)}–${num(d.breakevens[1], 0)}`} hint={`±${num(d.breakeven_pct)}% move`} />
            <Stat label="ATM IV / HV20" value={`${num(d.iv, 1)} / ${num(d.hv20, 1)}`} hint={d.iv_hv_ratio ? `IV/HV ${num(d.iv_hv_ratio)}×` : undefined} tone={(d.iv_hv_ratio ?? 1) > 1.15 ? "warning" : "default"} />
            <Stat label="Theta / day" value={num(d.theta_per_day)} hint={`${inr(d.theta_per_lot, { decimals: 0 })} per lot`} tone="loss" />
            <Stat label="Days to expiry" value={num(d.days_to_expiry, 1)} hint={shortDate(d.expiry)} />
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Intraday premium (last sessions)</CardTitle>
                <CardDescription>
                  {d.call_symbol.replace("NFO:", "")} + {d.put_symbol.replace("NFO:", "")}
                </CardDescription>
              </CardHeader>
              <CardContent className="h-80">
                <ResponsiveContainer>
                  <LineChart data={intraday} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="t" {...axisProps} minTickGap={60} />
                    <YAxis {...axisProps} width={48} domain={["auto", "auto"]} />
                    <RTooltip {...tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line dataKey="combined" name="Combined" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line dataKey="ce" name="Call" stroke="hsl(var(--loss))" strokeWidth={1.2} dot={false} isAnimationActive={false} />
                    <Line dataKey="pe" name="Put" stroke="hsl(var(--profit))" strokeWidth={1.2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Theoretical time decay</CardTitle>
                <CardDescription>Premium at the current spot and IV as time passes{d.days_to_expiry < 3 ? " (hourly near expiry)" : ""}</CardDescription>
              </CardHeader>
              <CardContent className="h-80">
                <ResponsiveContainer>
                  <AreaChart data={d.decay} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="day" {...axisProps} tickFormatter={(v: number) => (d.days_to_expiry < 3 ? `+${Math.round(v * 24)}h` : `D+${v}`)} />
                    <YAxis {...axisProps} width={44} />
                    <RTooltip {...tooltipStyle} labelFormatter={(v) => (d.days_to_expiry < 3 ? `+${Math.round(Number(v) * 24)} hours` : `Day +${v}`)} />
                    <Area dataKey="premium" stroke="hsl(var(--warning))" fill="hsl(var(--warning) / 0.15)" strokeWidth={2} isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Realised volatility (HV20) vs current ATM IV</CardTitle>
              <CardDescription>IV above realised means option sellers are being paid a premium for risk; below means options are cheap relative to recent movement.</CardDescription>
            </CardHeader>
            <CardContent className="h-64">
              <ResponsiveContainer>
                <LineChart data={hv} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" {...axisProps} minTickGap={40} />
                  <YAxis {...axisProps} width={40} unit="%" domain={["auto", "auto"]} />
                  <RTooltip {...tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line dataKey="hv" name="HV20" stroke="hsl(var(--info))" strokeWidth={2} dot={false} isAnimationActive={false} />
                  {d.iv ? <ReferenceLine y={d.iv} stroke="hsl(var(--primary))" strokeDasharray="5 3" label={{ value: `ATM IV ${num(d.iv, 1)}%`, fill: "hsl(var(--primary))", fontSize: 10, position: "insideTopRight" }} /> : null}
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Disclaimer kind="options" />
        </div>
      )}
    </div>
  );
}
