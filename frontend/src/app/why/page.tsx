import type { Metadata } from "next";

import { WhyPage } from "@/components/why-page";

export const metadata: Metadata = {
  title: "Why Sheriff Sale Hunter",
  description: "Consolidated, enriched sheriff and foreclosure sale data with equity rankings, probability to auction and lien pre-screening, built for wholesalers, investors and realtors.",
};

export default function Why() {
  return <WhyPage />;
}
