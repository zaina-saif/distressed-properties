import type { Metadata } from "next";

import { FileStoragePage } from "@/components/file-storage-page";

export const metadata: Metadata = { title: "File storage · Sheriff Sale Hunter", robots: { index: false } };

export default function Files() {
  return <FileStoragePage />;
}
