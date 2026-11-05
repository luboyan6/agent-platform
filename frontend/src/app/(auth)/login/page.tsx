"use client";

import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useContext, useState } from "react";

import { AuthBackground } from "@/components/auth/auth-background";
import { AuthBrand } from "@/components/auth/auth-brand";
import { RememberSessionOption } from "@/components/auth/remember-session-option";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthDisabledContext, useAuth } from "@/core/auth/AuthProvider";
import { isValidEmail } from "@/core/auth/email";
import { resolveAuthNextPath } from "@/core/auth/next-path";
import {
  loadRememberLoginPreference,
  saveRememberLoginPreference,
} from "@/core/auth/remember-login";
import {
  canCreateRegularAccount,
  fetchSetupStatus,
  type SetupStatusResponse,
} from "@/core/auth/setup";
import { parseAuthError } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();
  const { t } = useI18n();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLogin, setIsLogin] = useState(true);
  const [ssoProviders, setSsoProviders] = useState<
    { id: string; display_name: string; type: string }[]
  >([]);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(
    null,
  );
  const [setupStatusPhase, setSetupStatusPhase] = useState<
    "checking" | "ready" | "unavailable"
  >("checking");
  const [setupStatusAttempt, setSetupStatusAttempt] = useState(0);

  // Extract error from query params (e.g., ?error=sso_failed)
  const errorParam = searchParams.get("error");
  // Direct auth-page entry with a suspended session: the layout hands the
  // SSR account_disabled verdict down through context — the only place the
  // reason is known before a (deliberately generic) login attempt.
  const ssrDisabled = useContext(AuthDisabledContext);
  const [error, setError] = useState(
    errorParam
      ? (t.login.errors[errorParam as keyof typeof t.login.errors] ??
          t.login.authFailed)
      : ssrDisabled
        ? t.login.errors.account_disabled
        : "",
  );
  // Soft hint shown after a failed login when SSO is configured: an SSO-only
  // account has no local password, so the backend returns a generic
  // "incorrect email or password" (deliberately, to avoid account enumeration).
  // Nudge the user toward the SSO buttons without confirming the account exists.
  const [showSsoHint, setShowSsoHint] = useState(false);
  const [loading, setLoading] = useState(false);

  // Get next parameter for validated redirect
  const nextParam = searchParams.get("next");
  const redirectPath = resolveAuthNextPath(nextParam);
  const regularSignupAllowed = canCreateRegularAccount({
    // A failed probe must not expose registration while the system's setup
    // state is unknown. Existing users can still sign in normally.
    checked: setupStatusPhase === "ready",
    status: setupStatus,
  });
  const systemNeedsAdminSetup = setupStatus?.needs_setup === true;
  const showSetupStatusUnavailable =
    setupStatusPhase === "unavailable" ||
    (setupStatusAttempt > 0 && setupStatusPhase === "checking");

  // Redirect if already authenticated. Replace, so Back does not return to a
  // sign-in page that immediately redirects again.
  useEffect(() => {
    if (isAuthenticated) {
      router.replace(redirectPath);
    }
  }, [isAuthenticated, redirectPath, router]);

  useEffect(() => {
    const preference = loadRememberLoginPreference();
    setRememberMe(preference.rememberMe);
    if (preference.email) {
      setEmail(preference.email);
    }
  }, []);

  // Fetch setup state independently so retrying a slow Gateway does not also
  // refetch unrelated auth-provider configuration.
  useEffect(() => {
    let cancelled = false;
    setSetupStatusPhase("checking");

    void fetchSetupStatus()
      .then((data) => {
        if (cancelled) return;
        setSetupStatus(data);
        setSetupStatusPhase("ready");
        if (data.needs_setup) {
          setIsLogin(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSetupStatus(null);
          setSetupStatusPhase("unavailable");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [setupStatusAttempt]);

  // SSO providers are static for the page lifetime and should not be coupled to
  // setup-status retries.
  useEffect(() => {
    let cancelled = false;

    void fetch("/api/v1/auth/providers")
      .then((r) => r.json())
      .then(
        (data: {
          providers: { id: string; display_name: string; type: string }[];
        }) => {
          if (!cancelled) {
            setSsoProviders(data.providers ?? []);
          }
        },
      )
      .catch(() => {
        // Ignore errors; no SSO providers shown
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setShowSsoHint(false);

    if (!isLogin && !regularSignupAllowed) {
      setError(t.login.adminSetupRequiredDescription);
      return;
    }

    // The form is `noValidate`, so the browser no longer rejects addresses
    // its `type="email"` rule dislikes (e.g. a non-ASCII local part, which
    // the backend accepts — #7488). Apply the permissive JS check instead.
    const address = email.trim();
    if (!isValidEmail(address)) {
      setError(t.login.errors.invalid_email);
      return;
    }

    if (password.length < (isLogin ? 6 : 8)) {
      setError(
        isLogin
          ? t.login.errors.password_too_short
          : t.login.errors.registration_password_too_short,
      );
      return;
    }

    setLoading(true);
    try {
      const endpoint = isLogin
        ? "/api/v1/auth/login/local"
        : "/api/v1/auth/register";
      const body = isLogin
        ? new URLSearchParams({
            password,
            remember_me: String(rememberMe),
            username: address,
          })
        : JSON.stringify({ email: address, password, remember_me: rememberMe });

      const headers: HeadersInit = isLogin
        ? { "Content-Type": "application/x-www-form-urlencoded" }
        : { "Content-Type": "application/json" };

      const res = await fetch(endpoint, {
        method: "POST",
        headers,
        body,
        credentials: "include", // Important: include HttpOnly cookie
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        // account_disabled is the one code with user-facing copy of its own
        // (#4063 gap 3): the backend message is not localized. Login-only:
        // sign-up keeps the backend message verbatim so a suspended
        // account's email cannot be probed through the register surface.
        setError(
          isLogin && authError.code === "account_disabled"
            ? t.login.errors.account_disabled
            : authError.message,
        );
        // On a failed login with SSO configured, surface a hint pointing at the
        // SSO buttons — the "wrong password" may really mean "this is an SSO account".
        if (isLogin && ssoProviders.length > 0) {
          setShowSsoHint(true);
        }
        return;
      }

      saveRememberLoginPreference({ email: address, rememberMe });

      // Both login and register set a cookie — redirect to workspace
      router.push(redirectPath);
    } catch {
      setError(t.login.networkError);
    } finally {
      setLoading(false);
    }
  };

  // A signed-in session is already on its way to the requested page.
  if (isAuthenticated) {
    return (
      <div className="bg-background flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground text-sm">{t.login.pleaseWait}</p>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-x-hidden overflow-y-auto px-4 py-12">
      <AuthBackground />

      <div className="relative w-full max-w-md">
        {/* Luminous Glow Halo behind Card */}
        <div
          aria-hidden="true"
          className="absolute -inset-1.5 rounded-[2.5rem] bg-gradient-to-r from-violet-600/20 via-indigo-500/15 to-cyan-500/20 opacity-75 blur-2xl dark:opacity-45"
        />

        {/* Elevated Glassmorphic Card */}
        <div className="relative space-y-6 rounded-[2rem] border border-white/60 bg-white/80 p-7 shadow-2xl shadow-indigo-500/10 backdrop-blur-2xl transition-all sm:p-9 dark:border-white/10 dark:bg-zinc-950/75 dark:shadow-purple-950/30">
          {/* Subtle top ambient light line */}
          <div
            aria-hidden="true"
            className="absolute top-0 right-10 left-10 h-px bg-gradient-to-r from-transparent via-violet-500/40 to-transparent"
          />

          {/* Brand Header */}
          <AuthBrand
            appName={t.pages.appName}
            subtitle={
              isLogin ? t.login.signInTitle : t.login.createAccountTitle
            }
          />

          {/* Segmented Auth Mode Switcher */}
          {regularSignupAllowed && (
            <div
              role="tablist"
              aria-label="Auth Mode"
              className="grid grid-cols-2 rounded-2xl border border-slate-200/70 bg-slate-100/80 p-1 dark:border-zinc-800/80 dark:bg-zinc-900/80"
            >
              <button
                type="button"
                role="tab"
                aria-selected={isLogin}
                onClick={() => {
                  setIsLogin(true);
                  setError("");
                  setShowSsoHint(false);
                }}
                className={`relative cursor-pointer rounded-xl py-2 text-sm font-medium transition-all duration-200 ${
                  isLogin
                    ? "text-foreground bg-white font-semibold shadow-xs dark:bg-zinc-800"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.login.signIn}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={!isLogin}
                onClick={() => {
                  setIsLogin(false);
                  setError("");
                  setShowSsoHint(false);
                }}
                className={`relative cursor-pointer rounded-xl py-2 text-sm font-medium transition-all duration-200 ${
                  !isLogin
                    ? "text-foreground bg-white font-semibold shadow-xs dark:bg-zinc-800"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.login.createAccount}
              </button>
            </div>
          )}

          {/* Service unavailable alert */}
          {showSetupStatusUnavailable && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-50/80 p-4 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
            >
              <AlertTriangle
                className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400"
                aria-hidden="true"
              />
              <div className="flex-1">
                <p className="font-medium">{t.login.serviceUnavailableTitle}</p>
                <p className="mt-1 text-xs leading-relaxed text-amber-800/80 dark:text-amber-200/80">
                  {t.login.serviceUnavailableDescription}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-3 h-8 cursor-pointer rounded-xl border-amber-500/40 bg-white/50 text-xs font-medium hover:bg-amber-100 dark:bg-zinc-900/50 dark:hover:bg-amber-900/40"
                  disabled={setupStatusPhase === "checking"}
                  onClick={() => {
                    setSetupStatusPhase("checking");
                    setSetupStatusAttempt((attempt) => attempt + 1);
                  }}
                >
                  {setupStatusPhase === "checking" ? (
                    <span className="flex items-center gap-1.5">
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin"
                        aria-hidden="true"
                      />
                      {t.login.pleaseWait}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                      {t.login.retry}
                    </span>
                  )}
                </Button>
              </div>
            </div>
          )}

          {/* Admin setup required notification */}
          {systemNeedsAdminSetup && (
            <div className="flex items-start gap-3 rounded-2xl border border-blue-500/30 bg-blue-50/80 p-4 text-sm text-blue-900 dark:bg-blue-950/30 dark:text-blue-200">
              <ShieldCheck
                className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400"
                aria-hidden="true"
              />
              <div className="flex-1">
                <p className="font-medium">{t.login.adminSetupRequiredTitle}</p>
                <p className="mt-1 text-xs leading-relaxed text-blue-800/80 dark:text-blue-200/80">
                  {t.login.adminSetupRequiredDescription}
                </p>
                <Link
                  href="/setup"
                  className="mt-2.5 inline-flex items-center gap-1.5 text-xs font-semibold text-blue-600 hover:text-blue-500 hover:underline dark:text-blue-400"
                >
                  {t.login.createAdminAccount}
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </Link>
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            {/* Email Field */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="text-muted-foreground/90 text-xs font-medium tracking-wider uppercase"
              >
                {t.login.email}
              </label>
              <div className="relative">
                <Mail
                  aria-hidden="true"
                  className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
                />
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={t.login.emailPlaceholder}
                  required
                  autoComplete="email"
                  className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
                />
              </div>
            </div>

            {/* Password Field */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="password"
                  className="text-muted-foreground/90 text-xs font-medium tracking-wider uppercase"
                >
                  {t.login.password}
                </label>
                {!isLogin && (
                  <span className="text-muted-foreground text-[11px]">
                    {password.length >= 8 ? (
                      <span className="inline-flex items-center gap-0.5 font-medium text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />≥
                        8 chars
                      </span>
                    ) : (
                      <span>Min 8 chars</span>
                    )}
                  </span>
                )}
              </div>
              <div className="relative">
                <Lock
                  aria-hidden="true"
                  className="text-muted-foreground/60 peer-focus:text-primary pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 transition-colors"
                />
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t.login.passwordPlaceholder}
                  required
                  minLength={isLogin ? 6 : 8}
                  autoComplete={isLogin ? "current-password" : "new-password"}
                  className="peer focus-visible:ring-primary/20 focus-visible:border-primary h-11 rounded-xl border-slate-200/80 bg-slate-50/70 pr-11 pl-10 text-sm transition-all dark:border-zinc-800 dark:bg-zinc-900/60"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="text-muted-foreground/60 hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer rounded-lg p-1 transition-colors hover:bg-slate-200/50 dark:hover:bg-zinc-800/50"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>

            {/* Remember Me Option */}
            <div className="pt-0.5">
              <RememberSessionOption
                checked={rememberMe}
                onCheckedChange={setRememberMe}
              />
            </div>

            {/* Error Message Alert */}
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
                  <span>{t.login.pleaseWait}</span>
                </span>
              ) : isLogin ? (
                <span className="flex items-center justify-center gap-2">
                  <span>{t.login.signIn}</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  <span>{t.login.createAccount}</span>
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </span>
              )}
            </Button>
          </form>

          {/* SSO Providers */}
          {ssoProviders.length > 0 && (
            <div className="space-y-3 pt-1">
              {isLogin && (
                <div className="relative my-2">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t border-slate-200/80 dark:border-zinc-800" />
                  </div>
                  <div className="relative flex justify-center text-xs tracking-wider uppercase">
                    <span className="text-muted-foreground rounded-full border border-slate-200/60 bg-white/90 px-3 py-0.5 text-[11px] font-medium backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-950/90">
                      {t.login.orContinueWith}
                    </span>
                  </div>
                </div>
              )}
              {showSsoHint && (
                <p className="text-muted-foreground rounded-xl border border-slate-200/60 bg-slate-100/60 p-2.5 text-center text-xs leading-relaxed dark:border-zinc-800 dark:bg-zinc-900/60">
                  {t.login.ssoHint}
                </p>
              )}
              <div className="grid gap-2">
                {ssoProviders.map((provider) => (
                  <Button
                    key={provider.id}
                    type="button"
                    variant="outline"
                    className="h-11 w-full cursor-pointer rounded-xl border-slate-200/80 text-sm font-medium transition-all hover:bg-slate-100/80 dark:border-zinc-800 dark:hover:bg-zinc-900/80"
                    disabled={loading}
                    onClick={() => {
                      window.location.href = `/api/v1/auth/oauth/${provider.id}?next=${encodeURIComponent(redirectPath)}&remember_me=${String(rememberMe)}`;
                    }}
                  >
                    <KeyRound
                      className="text-muted-foreground mr-2 h-4 w-4"
                      aria-hidden="true"
                    />
                    {t.login.continueWith(provider.display_name)}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {/* Bottom Switch Link */}
          {regularSignupAllowed && (
            <div className="border-t border-slate-200/60 pt-2 text-center text-sm dark:border-zinc-800/70">
              <button
                type="button"
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError("");
                  setShowSsoHint(false);
                }}
                className="text-primary hover:text-primary/80 cursor-pointer font-medium transition-colors hover:underline"
              >
                {isLogin ? t.login.noAccountSignUp : t.login.haveAccountSignIn}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
