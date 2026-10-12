import type { Metadata } from "next";

import { HowSalesWorkPage } from "@/components/how-sales-work-page";

export const metadata: Metadata = {
  title: "How Sheriff Sales Work",
  description: "How a sheriff or foreclosure sale works, step by step, from default to deed, with state-specific deposit, payment, confirmation and redemption rules.",
};

export default function HowSheriffSalesWork() {
  return <HowSalesWorkPage />;
}
