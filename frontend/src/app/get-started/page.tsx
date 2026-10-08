import type { Metadata } from "next";

import { AuthGate } from "@/components/auth-gate";

export const metadata: Metadata = {
  title: "Get started · Sheriff Sale Hunter",
  description: "Create an account or sign in to continue to Sheriff Sale Hunter.",
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function GetStartedPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const mode = first(params.mode);
  return <AuthGate initialMode={mode === "login" || mode === "reset" ? mode : "create"} next={first(params.next)} plan={first(params.plan)} />;
}
