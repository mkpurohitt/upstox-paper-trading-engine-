"use client";
import { Rocket } from "lucide-react";
import { EmptyState } from "@/components/common";

/** Replaced in Phase 4 with the broker / mode / risk-limit deploy flow. */
export function DeployPanel() {
  return <EmptyState icon={Rocket} title="Deployment" description="Broker connections and the risk engine are required to deploy." />;
}
