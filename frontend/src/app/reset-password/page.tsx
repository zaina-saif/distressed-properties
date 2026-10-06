import type { Metadata } from "next";

import { ResetPassword } from "@/components/reset-password";

export const metadata: Metadata = { title: "Reset password · Distressed Properties Pro" };

export default function ResetPasswordPage() {
  return <ResetPassword />;
}
