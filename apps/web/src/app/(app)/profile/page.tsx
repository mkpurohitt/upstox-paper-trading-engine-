"use client";
import { KeyRound, Link2, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { PageHeader } from "@/components/common";
import { BrokerConnections } from "@/components/profile/broker-connections";
import { SessionsCard, TwoFactorCard } from "@/components/profile/security";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function Inner() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") ?? "brokers";
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader icon={UserRound} title="Profile" description="Account, security and broker connections" />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/profile?tab=${t}`)}>
        <TabsList>
          <TabsTrigger value="brokers">
            <Link2 /> Brokers
          </TabsTrigger>
          <TabsTrigger value="security">
            <KeyRound /> Security
          </TabsTrigger>
        </TabsList>
        <TabsContent value="brokers">
          <BrokerConnections />
        </TabsContent>
        <TabsContent value="security" className="flex flex-col gap-3">
          <TwoFactorCard />
          <SessionsCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <React.Suspense>
      <Inner />
    </React.Suspense>
  );
}
