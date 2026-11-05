"use client";

import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AuthBackground } from "@/components/auth/auth-background";
import { resolveAuthNextPath } from "@/core/auth/next-path";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading",
  );
  const calledRef = useRef(false);

  const doAuthCheck = useCallback(async () => {
    if (calledRef.current) return;
    calledRef.current = true;

    const next = resolveAuthNextPath(searchParams.get("next"));

    try {
      const res = await fetch("/api/v1/auth/me", { credentials: "include" });

      if (res.ok) {
        setStatus("success");
        // Small delay so the user sees the success message
        setTimeout(() => router.replace(next), 300);
      } else {
        setStatus("error");
        setTimeout(() => router.replace("/login?error=sso_failed"), 1500);
      }
    } catch {
      setStatus("error");
      setTimeout(() => router.replace("/login?error=sso_failed"), 1500);
    }
  }, [searchParams, router]);

  useEffect(() => {
    void doAuthCheck();
  }, [doAuthCheck]);

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <AuthBackground />
      <div className="relative w-full max-w-sm">
        <div
          aria-hidden="true"
          className="absolute -inset-1 rounded-3xl bg-gradient-to-r from-violet-600/20 via-indigo-500/15 to-cyan-500/20 opacity-75 blur-xl dark:opacity-45"
        />
        <div className="relative space-y-4 rounded-3xl border border-white/60 bg-white/80 p-8 text-center shadow-2xl backdrop-blur-2xl dark:border-white/10 dark:bg-zinc-950/75">
          {status === "loading" && (
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="text-primary h-8 w-8 animate-spin" />
              <p className="text-muted-foreground text-sm font-medium">
                Signing you in...
              </p>
            </div>
          )}
          {status === "success" && (
            <div className="flex flex-col items-center gap-3">
              <CheckCircle2 className="h-8 w-8 text-emerald-500" />
              <p className="text-foreground text-sm font-medium">
                Redirecting...
              </p>
            </div>
          )}
          {status === "error" && (
            <div className="flex flex-col items-center gap-3">
              <AlertCircle className="text-destructive h-8 w-8" />
              <p className="text-muted-foreground text-sm font-medium">
                Authentication failed. Redirecting to login...
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
