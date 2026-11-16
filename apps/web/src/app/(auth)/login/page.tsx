"use client";
import type { Schemas } from "@algo/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/misc";
import { api, apiJson, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Brand, GoogleIcon } from "../auth-ui";

const schema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Password required") });
type Form = z.infer<typeof schema>;

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const setSession = useAuth((s) => s.setSession);
  const [challenge, setChallenge] = React.useState<string | null>(params.get("challenge"));
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [providers, setProviders] = React.useState<Schemas["AuthProvidersOut"] | null>(null);
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });

  React.useEffect(() => {
    unwrap(api.GET("/api/auth/providers")).then(setProviders).catch(() => undefined);
  }, []);

  const finish = (t: Schemas["TokenOut"]) => {
    setSession(t);
    toast.success(`Welcome back${t.user.full_name ? `, ${t.user.full_name.split(" ")[0]}` : ""}`);
    router.replace(next);
  };

  const onSubmit = form.handleSubmit(async (values) => {
    setBusy(true);
    try {
      const res = await unwrap(api.POST("/api/auth/login", { body: values }));
      if (res.requires_2fa && res.challenge_token) setChallenge(res.challenge_token);
      else if (res.token) finish(res.token);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  });

  const verify = async () => {
    if (!challenge) return;
    setBusy(true);
    try {
      finish(await unwrap(api.POST("/api/auth/login/2fa", { body: { challenge_token: challenge, code } })));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const demo = async () => {
    setBusy(true);
    try {
      finish(await unwrap(api.POST("/api/auth/demo")));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    try {
      const { url } = await apiJson<{ url: string }>("/api/auth/google/start");
      window.location.href = url;
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <>
      <Brand />
      <Card className="glow">
        <CardHeader>
          <CardTitle className="text-base">{challenge ? "Two-factor verification" : "Sign in"}</CardTitle>
          <CardDescription>
            {challenge ? "Enter the 6-digit code from your authenticator app (or a recovery code)." : "Research, backtest and deploy strategies on NSE, BSE & MCX."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {challenge ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void verify();
              }}
            >
              <Input autoFocus inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} aria-label="2FA code" />
              <Button type="submit" loading={busy}>
                Verify
              </Button>
              <Button type="button" variant="ghost" onClick={() => setChallenge(null)}>
                Back
              </Button>
            </form>
          ) : (
            <form className="flex flex-col gap-3" onSubmit={onSubmit} noValidate>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" autoComplete="email" {...form.register("email")} aria-invalid={!!form.formState.errors.email} />
                {form.formState.errors.email && <p className="text-2xs text-loss">{form.formState.errors.email.message}</p>}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
                {form.formState.errors.password && <p className="text-2xs text-loss">{form.formState.errors.password.message}</p>}
              </div>
              <Button type="submit" loading={busy} className="mt-1">
                Sign in
              </Button>
              <div className="my-1 flex items-center gap-3 text-2xs text-muted-foreground">
                <Separator className="flex-1" /> or <Separator className="flex-1" />
              </div>
              <Button type="button" variant="outline" onClick={google} disabled={!providers?.google} title={providers?.google ? undefined : "Google sign-in not configured"}>
                <GoogleIcon /> Continue with Google
              </Button>
              {providers?.demo_login && (
                <Button type="button" variant="secondary" onClick={demo} loading={busy}>
                  <Sparkles /> Try the demo account
                </Button>
              )}
            </form>
          )}
        </CardContent>
      </Card>
      <p className="mt-4 text-center text-xs text-muted-foreground">
        New here?{" "}
        <Link href="/signup" className="text-primary hover:underline">
          Create an account
        </Link>
      </p>
    </>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense>
      <LoginInner />
    </React.Suspense>
  );
}
