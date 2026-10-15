import type { Metadata } from "next";

import { UserManagementPage } from "@/components/user-management-page";

export const metadata: Metadata = { title: "Users · Sheriff Sale Hunter", robots: { index: false } };

export default function Users() {
  return <UserManagementPage />;
}
