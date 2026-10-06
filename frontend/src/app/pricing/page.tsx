import type { Metadata } from "next";

import { PricingPage } from "@/components/pricing-page";

export const metadata: Metadata = {
  title: "Pricing · Distressed Properties Pro",
  description: "Simple, transparent pricing for sheriff and foreclosure sale data: start free with one county, or cover a whole state or every state we track.",
};

export default function Pricing() {
  return <PricingPage />;
}
