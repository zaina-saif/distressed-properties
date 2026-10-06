import type { Metadata } from "next";

import { LandingPage } from "@/components/landing-page";

export const metadata: Metadata = {
  title: "Live NJ sale data · Distressed Properties Pro",
  description: "Browse live New Jersey sheriff-sale listings, upcoming sale dates, and equity signals.",
};

export default function MarketDataPage() {
  return <LandingPage />;
}
