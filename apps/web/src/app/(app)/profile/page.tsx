"use client";
import { Bell, CreditCard, KeyRound, Link2, Palette, ShieldCheck, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { PageHeader } from "@/components/common";
import { AccountDetails, KycCard, SubscriptionPanel } from "@/components/profile/account";
import { BrokerConnections } from "@/components/profile/broker-connections";
import { AppearancePrefs, NotificationPrefs, PrivacyPanel } from "@/components/profile/preferences";
import { SessionsCard, TwoFactorCard } from "@/components/profile/security";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { id: "account", label: "Account", icon: UserRound },
  { id: "subscription", label: "Subscription", icon: CreditCard },
  { id: "brokers", label: "Brokers", icon: Link2 },
  { id: "security", label: "Security", icon: KeyRound },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "privacy", label: "Privacy & data", icon: ShieldCheck },
] as const;

function Inner() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") ?? "account";
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader icon={UserRound} title="Profile" description="Account, subscription, brokers, security, notifications and privacy" />
      <Tabs value={tab} onValueChange={(t) => router.replace(`/profile?tab=${t}`)}>
        <TabsList className="h-auto flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              <t.icon /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="account" className="flex flex-col gap-3">
          <AccountDetails />
          <KycCard />
        </TabsContent>
        <TabsContent value="subscription">
          <SubscriptionPanel />
        </TabsContent>
        <TabsContent value="brokers">
          <BrokerConnections />
        </TabsContent>
        <TabsContent value="security" className="flex flex-col gap-3">
          <TwoFactorCard />
          <SessionsCard />
        </TabsContent>
        <TabsContent value="notifications">
          <NotificationPrefs />
        </TabsContent>
        <TabsContent value="appearance">
          <AppearancePrefs />
        </TabsContent>
        <TabsContent value="privacy">
          <PrivacyPanel />
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
