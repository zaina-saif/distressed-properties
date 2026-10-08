import type { Metadata } from "next";

import { LandingPage } from "@/components/landing-page";

export const metadata: Metadata = {
  title: "Live NJ sale data · Sheriff Sale Hunter",
  description: "Browse live New Jersey sheriff-sale listings, upcoming sale dates, and equity signals.",
};

export default function MarketDataPage() {
  return <LandingPage />;
}
