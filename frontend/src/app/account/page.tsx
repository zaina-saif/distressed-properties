import type { Metadata } from "next";

import { AccountPage } from "@/components/account-page";

export const metadata: Metadata = { title: "Account · Distressed Properties Pro" };

export default async function Account({ searchParams }: { searchParams: Promise<{ [key: string]: string | string[] | undefined }> }) {
  const params = await searchParams;
  return <AccountPage checkoutSucceeded={params.checkout === "success"} />;
}
