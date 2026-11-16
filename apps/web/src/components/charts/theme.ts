"use client";
/** Resolve design tokens to concrete colours for canvas/SVG chart libraries. */
export function cssHsl(name: string, alpha = 1): string {
  if (typeof window === "undefined") return "#888";
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  if (!v) return "#888";
  return alpha === 1 ? `hsl(${v})` : `hsl(${v} / ${alpha})`;
}

export function chartPalette() {
  return {
    bg: cssHsl("card"),
    text: cssHsl("muted-foreground"),
    grid: cssHsl("border", 0.6),
    profit: cssHsl("profit"),
    loss: cssHsl("loss"),
    primary: cssHsl("primary"),
    info: cssHsl("info"),
    warning: cssHsl("warning"),
    fg: cssHsl("foreground"),
  };
}

/** Categorical series palette (validated for contrast on both themes). */
export const SERIES = ["#7c6cf5", "#3d9bf5", "#f5a524", "#23c483", "#ea4b8b", "#14b8a6", "#a78bfa", "#f97316"];

export const tooltipStyle = {
  contentStyle: {
    background: "hsl(var(--popover))",
    border: "1px solid hsl(var(--border))",
    borderRadius: 8,
    fontSize: 12,
    color: "hsl(var(--popover-foreground))",
  },
  labelStyle: { color: "hsl(var(--muted-foreground))" },
  itemStyle: { padding: 0 },
} as const;

export const axisProps = {
  stroke: "hsl(var(--muted-foreground))",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;
