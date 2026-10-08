"use client";

import { ArrowRight, Mail } from "lucide-react";
import { FormEvent, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { API_URL, authFetch } from "@/lib/api";

import styles from "./marketing-home.module.css";

const TOPICS = [
  ["general", "General question"], ["sales", "Plans and pricing"], ["enterprise", "Enterprise data"],
  ["support", "Account or billing support"], ["data", "Data correction"],
] as const;

export function ContactPage({ initialTopic }: { initialTopic?: string }) {
  const { account } = useAccount();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const topic = TOPICS.some(([value]) => value === initialTopic) ? initialTopic : "general";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = Object.fromEntries(["name", "email", "topic", "message", "website"].map((key) => [key, String(form.get(key) ?? "")]));
    setError(null);
    if (body.message.trim().length < 10) return setError("Please write a little more so we can help (at least 10 characters).");
    setBusy(true);
    try {
      // Signed-in visitors are linked to their account; everyone else can still write.
      const response = await authFetch(`${API_URL}/api/v1/contact`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) {
        const detail = await response.json().then((data) => data?.detail).catch(() => null);
        throw new Error(typeof detail === "string" ? detail : "Your message could not be sent. Please try again.");
      }
      setSent(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Your message could not be sent. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return <div className={styles.root}>
    <SiteHeader active="contact"/>
    <main className="contact-page container">
      <span className="eyebrow">CONTACT</span>
      <h1>Talk to us.</h1>
      <p className="profile-intro">Questions about plans, enterprise data, your account, or a listing that looks wrong? Send us a message and we will reply by email, usually within one business day.</p>
      {sent ? <div className="form-notice contact-sent" role="status"><strong>Thanks, your message is on its way.</strong> We will reply to the email address you gave.</div> :
      <form className="contact-form" onSubmit={submit}>
        <div className="contact-row">
          <label>Name<input name="name" required maxLength={120} autoComplete="name" placeholder="Your name"/></label>
          <label>Email<input name="email" type="email" required maxLength={254} autoComplete="email" placeholder="you@example.com" defaultValue={account?.email ?? ""}/></label>
        </div>
        <label>Topic<select name="topic" defaultValue={topic}>{TOPICS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Message<textarea name="message" required minLength={10} maxLength={5000} rows={6} placeholder="How can we help?"/></label>
        {/* Hidden from people; bots that fill it in are ignored. */}
        <input name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" className="contact-trap"/>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="choose-plan-actions"><button type="submit" className="site-button" disabled={busy}>{busy ? "Sending…" : "Send message"}<ArrowRight/></button></div>
      </form>}
      <p className="contact-direct"><Mail size={15} aria-hidden="true"/><span>Prefer email? Write to <a href="mailto:sam@sheriffsalehunter.ai">sam@sheriffsalehunter.ai</a>.</span></p>
    </main>
    <SiteFooter/>
  </div>;
}
