import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

export function sentimentColor(score: number): string {
  if (score > 0.2) return "var(--positive)";
  if (score < -0.2) return "var(--negative)";
  return "var(--neutral-sentiment)";
}

export function sentimentLabel(score: number): string {
  if (score > 0.2) return "Positive";
  if (score < -0.2) return "Negative";
  return "Neutral";
}

export function entityTypeColor(type: string): string {
  switch (type.toUpperCase()) {
    case "PER": return "var(--entity-per)";
    case "ORG": return "var(--entity-org)";
    case "LOC": return "var(--entity-loc)";
    default: return "var(--entity-misc)";
  }
}
