"use client";
import { Sparkles } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Copilot" icon={Sparkles} description="Your AI research assistant for Indian markets" />
      <EmptyState icon={Sparkles} title="Copilot" description="This workspace is being assembled." />
    </div>
  );
}
