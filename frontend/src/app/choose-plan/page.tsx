import type { Metadata } from "next";

import { ChoosePlan } from "@/components/choose-plan";

export const metadata: Metadata = { title: "Choose a plan · Sheriff Sale Hunter" };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ChoosePlanPage({ searchParams }: { searchParams: Promise<{ [key: string]: string | string[] | undefined }> }) {
  const params = await searchParams;
  return <ChoosePlan initialPlan={first(params.plan)} initialInterval={first(params.interval)} cancelled={first(params.checkout) === "cancelled"} />;
}
