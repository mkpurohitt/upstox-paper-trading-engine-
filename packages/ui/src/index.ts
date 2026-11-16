import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class names, resolving conflicts (shadcn/ui convention). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** 8px spacing scale used across the product. */
export const space = { 1: 8, 2: 16, 3: 24, 4: 32, 5: 40, 6: 48 } as const;

export const PNL = {
  positive: "text-profit",
  negative: "text-loss",
  neutral: "text-muted-foreground",
} as const;

export function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return PNL.neutral;
  return value > 0 ? PNL.positive : PNL.negative;
}
