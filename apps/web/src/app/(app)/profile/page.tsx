"use client";
import { UserRound } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Profile" icon={UserRound} description="Account, security, brokers and billing" />
      <EmptyState icon={UserRound} title="Profile" description="This workspace is being assembled." />
    </div>
  );
}
