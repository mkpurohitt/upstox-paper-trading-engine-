"use client";
import { Newspaper } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";

export default function Page() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="News" icon={Newspaper} description="Markets, announcements and calendars" />
      <EmptyState icon={Newspaper} title="News" description="This workspace is being assembled." />
    </div>
  );
}
