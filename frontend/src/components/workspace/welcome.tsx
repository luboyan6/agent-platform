"use client";

import { CalendarDaysIcon, RocketIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

function formatSystemDate(date: Date, locale = "zh-CN"): string {
  try {
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const weekdaysZh = [
      "星期日",
      "星期一",
      "星期二",
      "星期三",
      "星期四",
      "星期五",
      "星期六",
    ];
    if (locale.startsWith("zh")) {
      const weekday = weekdaysZh[date.getDay()];
      return `${year}年${month}月${day}日 ${weekday}`;
    }
    return new Intl.DateTimeFormat(locale, {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(date);
  } catch {
    return date.toLocaleDateString();
  }
}

function WelcomeDescription({ children }: { children: string }) {
  return (
    <p className="max-w-full text-wrap break-words whitespace-pre-line">
      {children}
    </p>
  );
}

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t, locale } = useI18n();
  const searchParams = useSearchParams();
  const isUltra = useMemo(() => mode === "ultra", [mode]);
  const colors = useMemo(() => {
    if (isUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isUltra]);

  const [currentDate, setCurrentDate] = useState(() =>
    formatSystemDate(new Date(), locale),
  );

  useEffect(() => {
    setCurrentDate(formatSystemDate(new Date(), locale));
  }, [locale]);

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-full flex-col items-center justify-center gap-2 px-4 py-4 text-center sm:px-8",
        className,
      )}
    >
      <div className="max-w-full text-2xl font-bold">
        {searchParams.get("mode") === "skill" ? (
          `✨ ${t.welcome.createYourOwnSkill} ✨`
        ) : (
          <div className="flex max-w-full flex-wrap items-center justify-center gap-2">
            <div className="text-primary inline-flex items-center justify-center">
              {isUltra ? (
                <RocketIcon
                  className="size-6 text-amber-500"
                  aria-hidden="true"
                />
              ) : (
                <CalendarDaysIcon
                  className="text-primary size-6"
                  aria-hidden="true"
                />
              )}
            </div>
            <span suppressHydrationWarning className="inline-flex items-center">
              <AuroraText colors={colors}>{currentDate}</AuroraText>
            </span>
          </div>
        )}
      </div>
      {searchParams.get("mode") === "skill" ? (
        <div className="text-muted-foreground max-w-full text-sm">
          <WelcomeDescription>
            {t.welcome.createYourOwnSkillDescription}
          </WelcomeDescription>
        </div>
      ) : (
        <div className="text-muted-foreground max-w-full text-sm">
          <WelcomeDescription>{t.welcome.description}</WelcomeDescription>
        </div>
      )}
    </div>
  );
}
