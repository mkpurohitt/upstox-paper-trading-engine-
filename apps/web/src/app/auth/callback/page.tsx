"use client";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useAuth } from "@/lib/auth";

/** Landing page after Google OAuth: the API has set the refresh cookie; exchange it for an access token. */
export default function OAuthCallback() {
  const router = useRouter();
  const refresh = useAuth((s) => s.refresh);
  React.useEffect(() => {
    refresh().then((t) => router.replace(t ? "/" : "/login"));
  }, [refresh, router]);
  return (
    <div className="flex h-dvh items-center justify-center text-sm text-muted-foreground" role="status">
      Signing you in…
    </div>
  );
}
