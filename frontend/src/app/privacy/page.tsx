import type { Metadata } from "next";

import { PrivacyPage } from "@/components/legal-pages";

export const metadata: Metadata = { title: "Privacy Policy · Sheriff Sale Hunter" };

export default function Privacy() {
  return <PrivacyPage />;
}
