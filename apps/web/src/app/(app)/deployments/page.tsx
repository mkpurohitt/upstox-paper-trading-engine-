"use client";
import { Radio } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Live strategies" icon={Radio} description="Running deployments, live P&L and controls" />
      <EmptyState icon={Radio} title="Live strategies" description="This workspace is being assembled." />
    </div>
  );
}
