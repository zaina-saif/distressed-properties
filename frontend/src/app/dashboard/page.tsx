import type { Metadata } from "next";

import PropertyDashboard from "@/components/property-dashboard";

export const metadata: Metadata = {
  title: "Live map · Distressed Properties Pro",
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
  return (
    <PropertyDashboard
      // Remount when the link changes so the filters start from the URL.
      key={`${first(params.state)}|${first(params.county)}|${first(params.q)}|${first(params.spotlight)}`}
      initialState={first(params.state) || "NJ"}
      initialCounty={first(params.county)}
      initialQuery={first(params.q)}
      initialSpotlight={first(params.spotlight) === "1"}
    />
  );
}
