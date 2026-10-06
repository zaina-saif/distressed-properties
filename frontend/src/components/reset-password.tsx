"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { supabase } from "@/lib/supabase";

import styles from "./marketing-home.module.css";

/** Landing page for the emailed reset link; Supabase signs the user in from the link first. */
export function ResetPassword() {
  const router = useRouter();
  const { session, loading, refresh } = useAccount();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    if (password.length < 8) return setError("Use a password of at least 8 characters.");
    if (password !== String(form.get("confirm") ?? "")) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    const { error: failure } = await supabase().auth.updateUser({ password });
    if (failure) {
      setError(failure.message);
      setBusy(false);
      return;
    }
    const account = await refresh();
    router.push(account?.has_access ? "/dashboard" : "/choose-plan");
  }

  return <div className={styles.root}>
    <SiteHeader active="pricing"/>
    <main className="account-page container">
      <span className="eyebrow">RESET PASSWORD</span>
      <h1>Set a new password</h1>
      {loading ? <p className="account-muted">Checking your reset link…</p> : !session
        ? <p className="form-error">This reset link is invalid or has expired. Request a new one from the log-in page.</p>
        : <form className="password-form" onSubmit={submit} noValidate>
          <label>New password<input name="password" type="password" autoComplete="new-password" minLength={8} required/></label>
          <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={8} required/></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" className="site-button" disabled={busy}>{busy ? "Saving…" : "Save password"}<ArrowRight/></button>
        </form>}
    </main>
    <SiteFooter/>
  </div>;
}
