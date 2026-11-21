import { ApiStatusBanner } from "@/components/shell/api-status";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10">
      <ApiStatusBanner className="fixed inset-x-0 top-0 z-50" />
      <div className="pointer-events-none absolute inset-0 bg-grid [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[600px] -translate-x-1/2 rounded-full bg-primary/25 blur-3xl" />
      <div className="relative w-full max-w-sm">{children}</div>
    </div>
  );
}
