"use client";
import { Shield } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Admin" icon={Shield} description="Operations console" />
      <EmptyState icon={Shield} title="Admin" description="This workspace is being assembled." />
    </div>
  );
}
