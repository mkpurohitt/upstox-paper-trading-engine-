import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-3 text-center">
      <p className="text-5xl font-semibold tracking-tight text-muted-foreground">404</p>
      <p className="text-sm text-muted-foreground">This page does not exist.</p>
      <Link href="/" className="text-sm text-primary hover:underline">
        Back to Copilot
      </Link>
    </div>
  );
}
