import type { Metadata } from "next";

import { MarketingHome } from "@/components/marketing-home";

export const metadata: Metadata = {
  title: "Distressed Properties Pro | Sheriff and Foreclosure Sales Across Seven States",
  description: "Sheriff and foreclosure sales in New Jersey, Pennsylvania, Ohio, Florida, Illinois, South Carolina and Delaware. One intelligent platform for estimated values, potential equity, lien intelligence and auction probabilities.",
};

export default function Home() {
  return <MarketingHome />;
}
