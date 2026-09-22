"use client";

import { SettingsIcon } from "lucide-react";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

import { useSettingsDialog } from "./settings";

function NavMenuButtonContent({
  isSidebarOpen,
  label,
}: {
  isSidebarOpen: boolean;
  label: string;
}) {
  return isSidebarOpen ? (
    <div className="text-muted-foreground flex w-full items-center gap-2 text-left text-sm">
      <SettingsIcon className="size-4" />
      <span>{label}</span>
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="text-muted-foreground size-4" />
    </div>
  );
}

export function WorkspaceNavMenu() {
  const { openSettings } = useSettingsDialog();
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();

  return (
    <SidebarMenu className="w-full">
      <SidebarMenuItem>
        <SidebarMenuButton
          size="lg"
          onClick={() => {
            openSettings("appearance");
          }}
          tooltip={isSidebarOpen ? undefined : t.common.settings}
        >
          <NavMenuButtonContent
            isSidebarOpen={isSidebarOpen}
            label={t.common.settings}
          />
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
