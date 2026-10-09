import type { Metadata } from "next";

import { TermsPage } from "@/components/legal-pages";

export const metadata: Metadata = { title: "Terms of Service · Sheriff Sale Hunter" };

export default function Terms() {
  return <TermsPage />;
}
