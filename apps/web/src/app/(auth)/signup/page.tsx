"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/misc";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Brand } from "../auth-ui";

const schema = z.object({
  full_name: z.string().min(2, "Tell us your name").max(200),
  email: z.string().email("Enter a valid email"),
  password: z
    .string()
    .min(8, "At least 8 characters")
    .regex(/[A-Za-z]/, "Include a letter")
    .regex(/[0-9]/, "Include a number"),
  accept_terms: z.literal(true, { errorMap: () => ({ message: "Required" }) }),
  accept_privacy: z.literal(true, { errorMap: () => ({ message: "Required" }) }),
  marketing_opt_in: z.boolean(),
});
type Form = z.infer<typeof schema>;

export default function SignupPage() {
  const router = useRouter();
  const setSession = useAuth((s) => s.setSession);
  const form = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", email: "", password: "", marketing_opt_in: false } as Partial<Form>,
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const t = await unwrap(api.POST("/api/auth/register", { body: values }));
      setSession(t);
      toast.success("Account created — you're on the Free plan with paper trading enabled");
      router.replace("/");
    } catch (e) {
      toast.error((e as Error).message);
    }
  });

  return (
    <>
      <Brand />
      <Card className="glow">
        <CardHeader>
          <CardTitle className="text-base">Create your account</CardTitle>
          <CardDescription>Paper trading is on by default. Live trading requires 2FA and a connected broker.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3" onSubmit={onSubmit} noValidate>
            {(
              [
                ["full_name", "Full name", "text", "name"],
                ["email", "Email", "email", "email"],
                ["password", "Password", "password", "new-password"],
              ] as const
            ).map(([name, label, type, ac]) => (
              <div key={name} className="flex flex-col gap-1.5">
                <Label htmlFor={name}>{label}</Label>
                <Input id={name} type={type} autoComplete={ac} {...form.register(name)} aria-invalid={!!errors[name]} />
                {errors[name] && <p className="text-2xs text-loss">{errors[name]?.message}</p>}
              </div>
            ))}
            {(
              [
                ["accept_terms", <>I accept the Terms of Use and the <b>risk disclosure on derivatives</b>.</>],
                ["accept_privacy", <>I consent to processing of my data per the Privacy Notice (DPDP Act, 2023). Data is stored in India.</>],
                ["marketing_opt_in", <>Send me product updates (optional).</>],
              ] as const
            ).map(([name, text]) => (
              <Controller
                key={name}
                control={form.control}
                name={name}
                render={({ field }) => (
                  <label className="flex items-start gap-2 text-xs text-muted-foreground">
                    <Checkbox checked={!!field.value} onCheckedChange={(v) => field.onChange(v === true)} className="mt-0.5" />
                    <span>
                      {text}
                      {errors[name] && <span className="ml-1 text-loss">({errors[name]?.message})</span>}
                    </span>
                  </label>
                )}
              />
            ))}
            <Button type="submit" loading={isSubmitting} className="mt-1">
              Create account
            </Button>
          </form>
        </CardContent>
      </Card>
      <p className="mt-4 text-center text-xs text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}
