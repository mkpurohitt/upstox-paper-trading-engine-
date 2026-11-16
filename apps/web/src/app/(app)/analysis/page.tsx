"use client";
import { motion } from "framer-motion";
import { ArrowUpRight, LineChart } from "lucide-react";
import Link from "next/link";
import { DASHBOARDS } from "@/components/analysis-catalog";
import { PageHeader } from "@/components/common";
import { Badge } from "@/components/ui/badge";

export default function AnalysisHub() {
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader icon={LineChart} title="Analysis" description="Dashboards, scanners and options tools. Every view supports CSV export and Ask-AI." />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {DASHBOARDS.map((d, i) => (
          <motion.div key={d.slug} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}>
            <Link
              href={`/analysis/${d.slug}`}
              className="group flex h-full flex-col gap-3 rounded-xl border bg-card p-4 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5"
            >
              <div className="flex items-center justify-between">
                <div className="rounded-lg bg-primary/10 p-2 text-primary">
                  <d.icon className="h-5 w-5" aria-hidden />
                </div>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold">{d.title}</h2>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{d.description}</p>
              </div>
              <div className="mt-auto flex gap-1">
                {d.tags.map((t) => (
                  <Badge key={t} variant="secondary">
                    {t}
                  </Badge>
                ))}
              </div>
            </Link>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
