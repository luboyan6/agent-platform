"use client";

import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthBackground } from "@/components/auth/auth-background";
import { AuthBrand } from "@/components/auth/auth-brand";
import { RememberSessionOption } from "@/components/auth/remember-session-option";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getCsrfHeaders } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { isValidEmail } from "@/core/auth/email";
import { loadRememberLoginPreference } from "@/core/auth/remember-login";
import {
  fetchSetupStatus,
  isSystemAlreadyInitializedError,
} from "@/core/auth/setup";
import { parseAuthError } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";

type SetupMode = "loading" | "init_admin" | "change_password" | "unavailable";

export default function SetupPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const [mode, setMode] = useState<SetupMode>("loading");
  const [setupStatusAttempt, setSetupStatusAttempt] = useState(0);

  // --- Shared state ---
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [rememberMe, setRememberMe] = useState(
    () => loadRememberLoginPreference().rememberMe,
  );

  // --- Change-password mode only ---
  const [currentPassword, setCurrentPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);

  useEffect(() => {
    let cancelled = false;

    if (isAuthenticated && user?.needs_setup) {
      setMode("change_password");
    } else if (!isAuthenticated) {
      // Check if the system has no users yet. A slow Gateway must not leave the
      // setup page in an infinite loading state or silently redirect away.
      setMode("loading");
      void fetchSetupStatus()
        .then((data: { needs_setup?: boolean }) => {
          if (cancelled) return;
          if (data.needs_setup) {
            setMode("init_admin");
          } else {
            // System already set up and user is not logged in — go to login
            router.replace("/login");
          }
        })
        .catch(() => {
          if (!cancelled) setMode("unavailable");
        });
    } else {
      // Authenticated but needs_setup is false — already set up
      router.replace("/workspace");
    }

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, user, router, setupStatusAttempt]);

  // ── Init-admin handler ─────────────────────────────────────────────
  const handleInitAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // `noValidate` + JS check: the browser's `type="email"` rule would reject
    // addresses the backend accepts, e.g. a non-ASCII local part (#7488).
    const address = email.trim();
    if (!isValidEmail(address)) {
      setError("Please enter a valid email address");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/initialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: address,
          password: newPassword,
          remember_me: rememberMe,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        if (isSystemAlreadyInitializedError(data)) {
          router.replace("/login");
          return;
        }
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
      }

      router.push("/workspace");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // ── Change-password handler ────────────────────────────────────────
  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // The address field also carries the account's existing email here, so
    // the same permissive check applies (#7488).
    const address = email.trim();
    if (!isValidEmail(address)) {
      setError("Please enter a valid email address");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    if (!currentPassword) {
      setError("Please enter your current password");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/change-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getCsrfHeaders(),
        },
        credentials: "include",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          new_email: address,
          remember_me: rememberMe,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
      }

      router.push("/workspace");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (mode === "loading") {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
        <AuthBackground />
        <div className="flex flex-col items-center gap-3 text-center">
          <Loader2 className="text-primary h-8 w-8 animate-spin" />
          <p className="text-muted-foreground text-sm font-medium">Loading…</p>
        </div>
      </div>
    );
  }

  if (mode === "unavailable") {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-x-hidden overflow-y-auto px-4 py-12">
        <AuthBackground />
        <div className="relative w-full max-w-md">
          <div
            aria-hidden="true"
            className="absolute -inset-1.5 rounded-[2.5rem] bg-gradient-to-r from-amber-500/20 via-orange-500/15 to-red-500/20 opacity-75 blur-2xl dark:opacity-45"
          />
          <div className="relative space-y-6 rounded-[2rem] border border-white/60 bg-white/80 p-7 text-center shadow-2xl backdrop-blur-2xl transition-all sm:p-9 dark:border-white/10 dark:bg-zinc-950/75">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">
                {t.login.serviceUnavailableTitle}
              </h1>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
                {t.login.serviceUnavailableDescription}
              </p>
            </div>
            <div className="flex justify-center gap-3 pt-2">
              <Button
                type="button"
                className="cursor-pointer rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 font-semibold text-white shadow-md shadow-indigo-500/20"
                onClick={() => {
                  setMode("loading");
                  setSetupStatusAttempt((attempt) => attempt + 1);
                }}
              >
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                {t.login.retry}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="cursor-pointer rounded-xl"
                onClick={() => router.replace("/login")}
              >
                {t.login.signIn}
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Admin initialization form ──────────────────────────────────────
  if (mode === "init_admin") {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-x-hidden overflow-y-auto px-4 py-12">
        <AuthBackground />

        <div className="relative w-full max-w-md">
          {/* Luminous Glow Halo */}
          <div
            aria-hidden="true"
            className="absolute -inset-1.5 rounded-[2.5rem] bg-gradient-to-r from-violet-600/20 via-indigo-500/15 to-cyan-500/20 opacity-75 blur-2xl dark:opacity-45"
          />

          {/* Elevated Glassmorphic Card */}
          <div className="relative space-y-6 rounded-[2rem] border border-white/60 bg-white/80 p-7 shadow-2xl shadow-indigo-500/10 backdrop-blur-2xl transition-all sm:p-9 dark:border-white/10 dark:bg-zinc-950/75 dark:shadow-purple-950/30">
            <div
              aria-hidden="true"
              className="absolute top-0 right-10 left-10 h-px bg-gradient-to-r from-transparent via-violet-500/40 to-transparent"
            />

            <AuthBrand
              appName={t.pages.appName}
              subtitle="Create admin account"
            />

            <div className="rounded-xl border border-blue-500/20 bg-blue-50/70 p-3 text-xs text-blue-900 dark:bg-blue-950/30 dark:text-blue-200">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck className="h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" />
                <span>Initial Administrator Setup</span>
              </div>
              <p className="mt-1 text-blue-800/80 dark:text-blue-200/80">
                Set up the administrator account to get started with{" "}
                {t.pages.appName}.
              </p>
            </div>

            <form onSubmit={handleInitAdmin} noValidate className="space-y-4">
              {/* Email */}
              <div className="space-y-1.5">
                <label
                  htmlFor="email"
                  className="text-muted-foreground/90 text-xs font-medium tracking-wider uppercase"
                >
                  Email
                </label>
                <div className="relative">
                  <Mail
                    aria-hidden="true"
                    className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
                  />
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
                  />
                </div>
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <label
                  htmlFor="password"
                  className="text-muted-foreground/90 text-xs font-medium tracking-wider uppercase"
                >
                  Password
                </label>
                <div className="relative">
                  <Lock
                    aria-hidden="true"
                    className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
                  />
                  <Input
                    id="password"
                    type={showNewPassword ? "text" : "password"}
                    placeholder="Password (min. 8 characters)"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowNewPassword((prev) => !prev)}
                    aria-label={
                      showNewPassword ? "Hide password" : "Show password"
                    }
                    className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
                  >
                    {showNewPassword ? (
                      <EyeOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
              </div>

              {/* Confirm Password */}
              <div className="space-y-1.5">
                <label
                  htmlFor="confirmPassword"
                  className="text-muted-foreground/90 text-xs font-medium tracking-wider uppercase"
                >
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock
                    aria-hidden="true"
                    className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
                  />
                  <Input
                    id="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="Confirm password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowConfirmPassword((prev) => !prev)}
                    aria-label={
                      showConfirmPassword ? "Hide password" : "Show password"
                    }
                    className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
              </div>

              {/* Remember Me */}
              <div className="pt-0.5">
                <RememberSessionOption
                  checked={rememberMe}
                  onCheckedChange={setRememberMe}
                />
              </div>

              {/* Error Alert */}
              {error && (
                <div
                  role="alert"
                  className="border-destructive/20 bg-destructive/10 text-destructive flex items-start gap-2.5 rounded-xl border p-3 text-sm dark:text-red-400"
                >
                  <AlertCircle
                    className="text-destructive mt-0.5 h-4 w-4 shrink-0 dark:text-red-400"
                    aria-hidden="true"
                  />
                  <p className="flex-1 leading-snug">{error}</p>
                </div>
              )}

              {/* Submit Button */}
              <Button
                type="submit"
                disabled={loading}
                className="h-11 w-full cursor-pointer rounded-xl bg-gradient-to-r from-violet-600 via-indigo-600 to-indigo-600 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 transition-all duration-200 hover:from-violet-500 hover:to-indigo-500 hover:shadow-lg hover:shadow-indigo-500/30 active:scale-[0.99]"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                    <span>Creating account…</span>
                  </span>
                ) : (
                  <span className="flex items-center justify-center gap-2">
                    <span>Create Admin Account</span>
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </span>
                )}
              </Button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // ── Change-password form (needs_setup after login) ─────────────────
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-x-hidden overflow-y-auto px-4 py-12">
      <AuthBackground />

      <div className="relative w-full max-w-md">
        {/* Luminous Glow Halo */}
        <div
          aria-hidden="true"
          className="absolute -inset-1.5 rounded-[2.5rem] bg-gradient-to-r from-violet-600/20 via-indigo-500/15 to-cyan-500/20 opacity-75 blur-2xl dark:opacity-45"
        />

        {/* Elevated Glassmorphic Card */}
        <div className="relative space-y-6 rounded-[2rem] border border-white/60 bg-white/80 p-7 shadow-2xl shadow-indigo-500/10 backdrop-blur-2xl transition-all sm:p-9 dark:border-white/10 dark:bg-zinc-950/75 dark:shadow-purple-950/30">
          <div
            aria-hidden="true"
            className="absolute top-0 right-10 left-10 h-px bg-gradient-to-r from-transparent via-violet-500/40 to-transparent"
          />

          <AuthBrand
            appName={t.pages.appName}
            subtitle="Complete admin account setup"
          />

          <p className="text-muted-foreground text-center text-xs">
            Set your real email and a new password.
          </p>

          <form
            onSubmit={handleChangePassword}
            noValidate
            className="space-y-4"
          >
            {/* Email */}
            <div className="relative">
              <Mail
                aria-hidden="true"
                className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
              />
              <Input
                type="email"
                placeholder="Your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
              />
            </div>

            {/* Current Password */}
            <div className="relative">
              <KeyRound
                aria-hidden="true"
                className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
              />
              <Input
                type={showCurrentPassword ? "text" : "password"}
                placeholder="Current password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowCurrentPassword((prev) => !prev)}
                aria-label={
                  showCurrentPassword ? "Hide password" : "Show password"
                }
                className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
              >
                {showCurrentPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            </div>

            {/* New Password */}
            <div className="relative">
              <Lock
                aria-hidden="true"
                className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
              />
              <Input
                type={showNewPassword ? "text" : "password"}
                placeholder="New password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowNewPassword((prev) => !prev)}
                aria-label={showNewPassword ? "Hide password" : "Show password"}
                className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
              >
                {showNewPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            </div>

            {/* Confirm New Password */}
            <div className="relative">
              <Lock
                aria-hidden="true"
                className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
              />
              <Input
                type={showConfirmPassword ? "text" : "password"}
                placeholder="Confirm new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
              />
              <button
                type="button"
                tabIndex={-1}
                onClick={() => setShowConfirmPassword((prev) => !prev)}
                aria-label={
                  showConfirmPassword ? "Hide password" : "Show password"
                }
                className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
              >
                {showConfirmPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            </div>

            {/* Remember Me */}
            <div className="pt-0.5">
              <RememberSessionOption
                checked={rememberMe}
                onCheckedChange={setRememberMe}
              />
            </div>

            {/* Error Alert */}
            {error && (
              <div
                role="alert"
                className="border-destructive/20 bg-destructive/10 text-destructive flex items-start gap-2.5 rounded-xl border p-3 text-sm dark:text-red-400"
              >
                <AlertCircle
                  className="text-destructive mt-0.5 h-4 w-4 shrink-0 dark:text-red-400"
                  aria-hidden="true"
                />
                <p className="flex-1 leading-snug">{error}</p>
              </div>
            )}

            {/* Submit Button */}
            <Button
              type="submit"
              disabled={loading}
              className="h-11 w-full cursor-pointer rounded-xl bg-gradient-to-r from-violet-600 via-indigo-600 to-indigo-600 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 transition-all duration-200 hover:from-violet-500 hover:to-indigo-500 hover:shadow-lg hover:shadow-indigo-500/30 active:scale-[0.99]"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2
                    className="h-4 w-4 animate-spin"
                    aria-hidden="true"
                  />
                  <span>Setting up…</span>
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  <span>Complete Setup</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </span>
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
