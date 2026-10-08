import type { Metadata } from "next";

import { ContactPage } from "@/components/contact-page";

export const metadata: Metadata = {
  title: "Contact · Sheriff Sale Hunter",
  description: "Questions about plans, enterprise data, your account or a listing? Send Sheriff Sale Hunter a message.",
};

export default async function Contact({ searchParams }: { searchParams: Promise<{ [key: string]: string | string[] | undefined }> }) {
  const topic = (await searchParams).topic;
  return <ContactPage initialTopic={Array.isArray(topic) ? topic[0] : topic} />;
}
