import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";

import { AccountProvider } from "@/components/account-provider";

export const metadata: Metadata = {
  title: "Distressed Properties Pro",
  description: "Sheriff and foreclosure sale intelligence for investors across multiple states.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;550;600;650;700;750&family=Manrope:wght@400;500;550;600;650;700;750;800&display=swap" />
      </head>
      <body className="min-h-full flex flex-col"><AccountProvider>{children}</AccountProvider></body>
    </html>
  );
}
