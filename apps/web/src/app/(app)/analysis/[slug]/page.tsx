"use client";
import { Construction } from "lucide-react";
import { useParams } from "next/navigation";
import { DASHBOARDS } from "@/components/analysis-catalog";
import { EmptyState } from "@/components/common";
import { DashboardHeader } from "@/components/dashboard";

/** Fallback for dashboards that do not have a dedicated route. */
export default function DashboardFallback() {
  const { slug } = useParams<{ slug: string }>();
  const d = DASHBOARDS.find((x) => x.slug === slug);
  return (
    <div className="mx-auto max-w-7xl">
      <DashboardHeader title={d?.title ?? "Dashboard"} description={d?.description} icon={d?.icon} />
      <EmptyState icon={Construction} title="Unknown dashboard" description="Pick a dashboard from the Analysis hub." />
    </div>
  );
}
