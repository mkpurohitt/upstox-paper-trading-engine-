"use client";
import { LineChart } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Analysis" icon={LineChart} description="Dashboards, scanners and options tools" />
      <EmptyState icon={LineChart} title="Analysis" description="This workspace is being assembled." />
    </div>
  );
}
