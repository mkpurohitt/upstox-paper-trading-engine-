"use client";
import { Area, ComposedChart, CartesianGrid, Line, ReferenceLine, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { compactNum, inr, num } from "@/lib/format";
import { axisProps, tooltipStyle } from "./theme";

export function PayoffChart({
  points,
  spot,
  breakevens = [],
  height = 300,
  showT = true,
}: {
  points: { spot: number; expiry: number; t: number }[];
  spot: number;
  breakevens?: number[];
  height?: number;
  showT?: boolean;
}) {
  const max = Math.max(...points.map((p) => p.expiry), 0);
  const min = Math.min(...points.map((p) => p.expiry), 0);
  const zero = max === min ? 0.5 : max / (max - min);
  const data = points.map((p) => ({ ...p }));
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="pnl-split" x1="0" y1="0" x2="0" y2="1">
              <stop offset={0} stopColor="hsl(var(--profit))" stopOpacity={0.35} />
              <stop offset={zero} stopColor="hsl(var(--profit))" stopOpacity={0.08} />
              <stop offset={zero} stopColor="hsl(var(--loss))" stopOpacity={0.08} />
              <stop offset={1} stopColor="hsl(var(--loss))" stopOpacity={0.35} />
            </linearGradient>
            <linearGradient id="pnl-stroke" x1="0" y1="0" x2="0" y2="1">
              <stop offset={zero} stopColor="hsl(var(--profit))" />
              <stop offset={zero} stopColor="hsl(var(--loss))" />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="spot" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v: number) => num(v, 0)} />
          <YAxis {...axisProps} width={60} tickFormatter={(v: number) => compactNum(v)} />
          <RTooltip {...tooltipStyle} labelFormatter={(v) => `Spot ${num(Number(v), 0)}`} formatter={(v: number, n: string) => [inr(v, { decimals: 0 }), n === "expiry" ? "At expiry" : "Today (T+n)"]} />
          <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.5} />
          <ReferenceLine x={spot} stroke="hsl(var(--primary))" strokeDasharray="4 3" label={{ value: "spot", fill: "hsl(var(--primary))", fontSize: 10, position: "top" }} />
          {breakevens.map((b) => (
            <ReferenceLine key={b} x={b} stroke="hsl(var(--warning))" strokeDasharray="2 3" label={{ value: num(b, 0), fill: "hsl(var(--warning))", fontSize: 10, position: "insideBottom" }} />
          ))}
          <Area type="monotone" dataKey="expiry" stroke="url(#pnl-stroke)" strokeWidth={2} fill="url(#pnl-split)" isAnimationActive={false} />
          {showT && <Line type="monotone" dataKey="t" stroke="hsl(var(--info))" strokeWidth={1.5} strokeDasharray="5 3" dot={false} isAnimationActive={false} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
