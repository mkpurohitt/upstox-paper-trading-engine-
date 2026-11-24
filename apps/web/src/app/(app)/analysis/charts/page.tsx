"use client";
import dynamic from "next/dynamic";
import { Suspense } from "react";
import { Skeleton } from "@/components/ui/misc";

// lightweight-charts needs the browser: render the terminal on the client only
const ChartsTerminal = dynamic(() => import("@/components/charts/terminal/terminal").then((m) => m.ChartsTerminal), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full" />,
});

export default function ChartsPage() {
  return (
    <div className="-mx-3 -mt-4 h-[calc(100dvh-3.5rem-4.5rem)] sm:-mx-6 md:mx-0 md:mt-0 md:h-[calc(100dvh-3.5rem-2.75rem)]">
      <h1 className="sr-only">Charts</h1>
      <Suspense fallback={<Skeleton className="h-full w-full" />}>
        <ChartsTerminal />
      </Suspense>
    </div>
  );
}
