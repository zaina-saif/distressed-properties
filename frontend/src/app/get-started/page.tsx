import type { Metadata } from "next";

import { AuthGate } from "@/components/auth-gate";

export const metadata: Metadata = {
  title: "Get started · Distressed Properties Pro",
  description: "Create an account or sign in to continue to Distressed Properties Pro.",
};

export default function GetStartedPage() {
  return <AuthGate />;
}
