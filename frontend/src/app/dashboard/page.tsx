import type { Metadata } from "next";

import { RequireAccess } from "@/components/account-provider";
import PropertyDashboard from "@/components/property-dashboard";

export const metadata: Metadata = {
  title: "Live map · Sheriff Sale Hunter",
};

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams(
    Object.entries(params).flatMap(([key, value]) => (value === undefined ? [] : [[key, first(value)]])),
  ).toString();
  return (
    <RequireAccess next={`/dashboard${query ? `?${query}` : ""}`}>
    <PropertyDashboard
      // Remount when the link changes so the filters start from the URL.
      key={`${first(params.state)}|${first(params.county)}|${first(params.q)}|${first(params.spotlight)}|${first(params.view)}`}
      initialState={first(params.state) || "NJ"}
      initialCounty={first(params.county)}
      initialQuery={first(params.q)}
      initialSpotlight={first(params.spotlight) === "1"}
      initialView={first(params.view) === "analytics" ? "analytics" : first(params.view) === "list" ? "list" : "dashboard"}
    />
    </RequireAccess>
  );
}
