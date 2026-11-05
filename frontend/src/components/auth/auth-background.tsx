"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function AuthBackground() {
  const { theme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const currentTheme = mounted
    ? theme === "system"
      ? resolvedTheme
      : theme
    : "dark";
  const isDark = currentTheme === "dark";

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden select-none"
    >
      {/* Base background with subtle theme gradient */}
      <div className="absolute inset-0 bg-slate-50/90 transition-colors duration-700 dark:bg-[#07090f]" />

      {/* Aurora Ambient Glow Blob 1: Top-left Violet / Indigo */}
      <div
        className="absolute -top-[15%] -left-[10%] h-[65vw] max-h-[750px] w-[65vw] max-w-[750px] animate-pulse rounded-full opacity-60 blur-[110px] transition-all duration-1000 md:blur-[150px] dark:opacity-45"
        style={{
          background: isDark
            ? "radial-gradient(circle, rgba(124, 58, 237, 0.4) 0%, rgba(79, 70, 229, 0.2) 50%, transparent 75%)"
            : "radial-gradient(circle, rgba(167, 139, 250, 0.45) 0%, rgba(199, 210, 254, 0.35) 50%, transparent 75%)",
          animationDuration: "10s",
        }}
      />

      {/* Aurora Ambient Glow Blob 2: Bottom-right Cyan / Sky */}
      <div
        className="absolute -right-[10%] -bottom-[15%] h-[60vw] max-h-[700px] w-[60vw] max-w-[700px] animate-pulse rounded-full opacity-50 blur-[110px] transition-all duration-1000 md:blur-[150px] dark:opacity-35"
        style={{
          background: isDark
            ? "radial-gradient(circle, rgba(6, 182, 212, 0.35) 0%, rgba(14, 165, 233, 0.18) 50%, transparent 75%)"
            : "radial-gradient(circle, rgba(56, 189, 248, 0.4) 0%, rgba(186, 230, 253, 0.3) 50%, transparent 75%)",
          animationDuration: "14s",
          animationDelay: "3s",
        }}
      />

      {/* Aurora Ambient Glow Blob 3: Center Accent Magenta / Purple */}
      <div
        className="absolute top-1/2 left-1/2 h-[45vw] max-h-[550px] w-[45vw] max-w-[550px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-40 blur-[100px] transition-all duration-1000 md:blur-[140px] dark:opacity-25"
        style={{
          background: isDark
            ? "radial-gradient(circle, rgba(217, 70, 239, 0.28) 0%, rgba(139, 92, 246, 0.12) 60%, transparent 80%)"
            : "radial-gradient(circle, rgba(244, 114, 182, 0.3) 0%, rgba(221, 214, 254, 0.2) 60%, transparent 80%)",
        }}
      />

      {/* Refined Dot Matrix Pattern with Radial Fade */}
      <div
        className="absolute inset-0 opacity-[0.035] dark:opacity-[0.08]"
        style={{
          backgroundImage: isDark
            ? `radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.9) 1px, transparent 0)`
            : `radial-gradient(circle at 1px 1px, rgba(15, 23, 42, 0.9) 1px, transparent 0)`,
          backgroundSize: "24px 24px",
          maskImage:
            "radial-gradient(ellipse 65% 65% at 50% 50%, #000 20%, transparent 85%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 65% 65% at 50% 50%, #000 20%, transparent 85%)",
        }}
      />

      {/* Decorative Light Rays / Beams */}
      <div
        className="absolute inset-0 opacity-20 mix-blend-overlay dark:opacity-15"
        style={{
          backgroundImage:
            "linear-gradient(115deg, transparent 30%, rgba(255,255,255,0.15) 45%, transparent 60%)",
          backgroundSize: "200% 200%",
        }}
      />
    </div>
  );
}
