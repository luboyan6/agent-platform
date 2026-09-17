import { redirect } from "next/navigation";

import { getServerSideUser } from "@/core/auth/server";

export const dynamic = "force-dynamic";

export default async function RootPage() {
  const result = await getServerSideUser();

  if (result.tag === "authenticated") {
    redirect("/workspace");
  }

  if (result.tag === "needs_setup" || result.tag === "system_setup_required") {
    redirect("/setup");
  }

  if (result.tag === "config_error") {
    throw new Error(result.message);
  }

  redirect("/login");
}
