import type { Metadata } from "next";

import { MarketingHome } from "@/components/marketing-home";

export const metadata: Metadata = {
  title: "Distressed Properties Pro | Sheriff and Foreclosure Sales Across Multiple States",
  description: "Sheriff, court and public trustee foreclosure sales across multiple states. One intelligent platform for estimated values, potential equity, lien intelligence and auction probabilities.",
};

export default function Home() {
  return <MarketingHome />;
}
