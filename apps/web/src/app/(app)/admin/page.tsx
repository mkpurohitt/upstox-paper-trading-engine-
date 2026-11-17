"use client";
import { Activity, BookOpen, CreditCard, FileClock, Gauge, OctagonX, Shield, ShieldCheck, Users as UsersIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { AuditViewer, Billing, GlobalKillSwitch, Health, Overview, Reviews, Users } from "@/components/admin/panels";
import { EmptyState, PageHeader } from "@/components/common";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";

const RagManager = dynamic(() => import("@/components/admin/rag-manager").then((m) => m.RagManager), { ssr: false, loading: () => <Skeleton className="h-96" /> });

const TABS = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "users", label: "Users", icon: UsersIcon },
  { id: "billing", label: "Billing", icon: CreditCard },
  { id: "knowledge", label: "Knowledge base", icon: BookOpen },
  { id: "health", label: "Health", icon: Activity },
  { id: "kill", label: "Kill switch", icon: OctagonX },
  { id: "audit", label: "Audit", icon: FileClock },
  { id: "reviews", label: "RA reviews", icon: ShieldCheck },
] as const;

function Inner() {
  const user = useAuth((s) => s.user);
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") ?? "overview";
  if (!user) return <Skeleton className="h-96" />;
  if (user.role !== "admin") {
    return <EmptyState icon={Shield} title="Admins only" description="You don't have access to the admin console." className="mx-auto mt-10 max-w-md" />;
  }
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader icon={Shield} title="Admin" description="Users, billing, knowledge base, system health, platform kill switch, audit trail and compliance reviews" />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/admin?tab=${t}`)}>
        <TabsList className="h-auto flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              <t.icon /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="overview">
          <Overview />
        </TabsContent>
        <TabsContent value="users">
          <Users />
        </TabsContent>
        <TabsContent value="billing">
          <Billing />
        </TabsContent>
        <TabsContent value="knowledge">
          <RagManager />
        </TabsContent>
        <TabsContent value="health">
          <Health />
        </TabsContent>
        <TabsContent value="kill">
          <GlobalKillSwitch />
        </TabsContent>
        <TabsContent value="audit">
          <AuditViewer />
        </TabsContent>
        <TabsContent value="reviews">
          <Reviews />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function AdminPage() {
  return (
    <React.Suspense>
      <Inner />
    </React.Suspense>
  );
}
