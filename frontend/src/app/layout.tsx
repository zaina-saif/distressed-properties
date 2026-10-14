import type { Metadata } from "next";
import { DM_Sans, Manrope } from "next/font/google";
import "leaflet/dist/leaflet.css";
import "./globals.css";

import { AccountProvider } from "@/components/account-provider";

const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });

export const metadata: Metadata = {
  title: "Sheriff Sale Hunter",
  description: "Sheriff and foreclosure sale intelligence for investors across multiple states.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${dmSans.variable} ${manrope.variable} h-full antialiased`} suppressHydrationWarning>
      <body className="min-h-full flex flex-col"><AccountProvider>{children}</AccountProvider></body>
    </html>
  );
}
