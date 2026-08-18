import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NJ Sheriff Sale Dashboard",
  description: "Analyze scheduled New Jersey sheriff-sale properties.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
