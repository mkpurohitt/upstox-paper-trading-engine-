import { cn } from "@/lib/utils";

export function Sparkline({ values, className, height = 32, width = 120 }: { values: number[]; className?: string; height?: number; width?: number }) {
  if (values.length < 2) return <div className={cn("h-8", className)} />;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${height - ((v - lo) / span) * (height - 2) - 1}`).join(" ");
  const up = values[values.length - 1]! >= values[0]!;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={cn("w-full", className)} style={{ height }} preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? "hsl(var(--profit))" : "hsl(var(--loss))"} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
