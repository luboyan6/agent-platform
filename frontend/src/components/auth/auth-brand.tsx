"use client";

import { Sparkles } from "lucide-react";
import React from "react";

interface AuthBrandProps {
  appName: string;
  subtitle: string;
}

export function AuthBrand({ appName, subtitle }: AuthBrandProps) {
  return (
    <div className="flex flex-col items-center text-center">
      {/* Brand Icon with Radiant Backlight */}
      <div className="group relative mb-3.5 flex items-center justify-center">
        {/* Soft Ambient Halo */}
        <div
          aria-hidden="true"
          className="absolute -inset-2 rounded-2xl bg-gradient-to-tr from-violet-600 via-indigo-500 to-cyan-400 opacity-60 blur-lg transition-all duration-500 group-hover:opacity-85 group-hover:blur-xl dark:opacity-50"
        />

        {/* Squircle Badge */}
        <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-tr from-violet-600 via-indigo-600 to-indigo-500 text-white shadow-xl ring-1 shadow-indigo-500/25 ring-white/30 dark:ring-white/20">
          {/* Deer / Intelligent Agent Emblem */}
          <svg
            className="h-7 w-7 text-white drop-shadow-sm transition-transform duration-300 group-hover:scale-105"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {/* Elegant Antler / Flow Geometry */}
            <path d="M12 21V11" />
            <path d="M12 11C12 7.5 9.5 5 6.5 4" />
            <path d="M12 11C12 7.5 14.5 5 17.5 4" />
            <path d="M8 8.5C6 9 4.5 11 4.5 13" />
            <path d="M16 8.5C18 9 19.5 11 19.5 13" />
            <path d="M9.5 5.5C8 3.5 5.5 2.5 3.5 3" />
            <path d="M14.5 5.5C16 3.5 18.5 2.5 20.5 3" />
            <circle cx="12" cy="11" r="1.5" fill="currentColor" />
          </svg>

          {/* Tiny Sparkle Accent */}
          <Sparkles
            aria-hidden="true"
            className="absolute -top-1 -right-1 h-3.5 w-3.5 animate-pulse text-cyan-300"
          />
        </div>
      </div>

      {/* App Name */}
      <h1 className="text-foreground font-serif text-3xl font-bold tracking-tight">
        {appName}
      </h1>

      {/* Subtitle */}
      <p className="text-muted-foreground mt-1.5 text-sm font-normal">
        {subtitle}
      </p>
    </div>
  );
}
