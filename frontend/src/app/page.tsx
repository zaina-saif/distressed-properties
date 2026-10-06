import type { Metadata } from "next";

import { MarketingHome } from "@/components/marketing-home";

export const metadata: Metadata = {
  title: "Distressed Properties Pro | Your Next NJ Property Opportunity",
  description: "Every NJ sheriff sale. One intelligent platform. Discover estimated values, potential equity, lien intelligence and auction probabilities.",
};

export default function Home() {
  return <MarketingHome />;
}
