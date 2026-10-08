import type { Metadata } from "next";

import { InvestorProfileForm } from "@/components/investor-profile-form";

export const metadata: Metadata = { title: "Investor profile · Sheriff Sale Hunter" };

export default function ProfilePage() {
  return <InvestorProfileForm />;
}
