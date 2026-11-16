"use client";
import { Briefcase } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Portfolio" icon={Briefcase} description="Holdings and positions across brokers" />
      <EmptyState icon={Briefcase} title="Portfolio" description="This workspace is being assembled." />
    </div>
  );
}
