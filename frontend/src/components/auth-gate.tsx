"use client";

import { ArrowLeft, ArrowRight, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SheriffSaleHunterBrand } from "@/components/brand-logo";
import { supabase } from "@/lib/supabase";

import styles from "./auth-gate.module.css";

type AuthMode = "create" | "login" | "reset";

/** Only same-site paths are followed after sign-in. */
function safeNext(next: string | undefined): string | null {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : null;
}

export function AuthGate({ initialMode = "create", next, plan }: { initialMode?: AuthMode; next?: string; plan?: string }) {
  const router = useRouter();
  const { refresh } = useAccount();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const choosePlan = plan ? `/choose-plan?plan=${encodeURIComponent(plan)}` : "/choose-plan";

  function switchMode(value: AuthMode) {
    setMode(value);
    setError(null);
    setNotice(null);
  }

  async function goOn() {
    const account = await refresh();
    router.push(account?.has_access ? safeNext(next) ?? "/dashboard" : choosePlan);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    setError(null);
    setNotice(null);
    if (!email) return setError("Enter your email address.");
    if (mode !== "reset" && password.length < 8) return setError("Use a password of at least 8 characters.");
    setBusy(true);
    try {
      const auth = supabase().auth;
      if (mode === "reset") {
        const { error: failure } = await auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
        if (failure) throw failure;
        setNotice("If an account exists for that email, a reset link is on its way.");
      } else if (mode === "create") {
        const { data, error: failure } = await auth.signUp({
          email, password,
          options: { data: { full_name: String(form.get("name") ?? "").trim() }, emailRedirectTo: `${window.location.origin}${choosePlan}` },
        });
        if (failure) throw failure;
        if (data.session) await goOn();
        else setNotice("Check your email and open the confirmation link to finish creating your account.");
      } else {
        const { error: failure } = await auth.signInWithPassword({ email, password });
        if (failure) throw failure;
        await goOn();
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link href="/" className={styles.brand}><SheriffSaleHunterBrand /></Link>
        <Link href="/" className={styles.backLink}><ArrowLeft aria-hidden="true" />Back to home</Link>
      </header>
      <section className={styles.authLayout}>
        <aside className={styles.story}>
          <Image className={styles.storyImage} src="/marketing/nj-neighborhood.jpg" alt="Residential neighborhood" fill sizes="(max-width: 800px) 100vw, 45vw" />
          <div className={styles.storyWash} />
          <div className={styles.storyContent}>
            <span className={styles.eyebrow}><i />YOUR SHERIFF SALE EXPERT</span>
            <h1>Find the opportunity<br /><em>before everyone</em><br />else does.</h1>
            <p>See the minimum bid, estimated value, sale history, and research signals in one place.</p>
            <div className={styles.storyNote}><span><LockKeyhole aria-hidden="true" /></span><div><b>Your research workspace</b><small>Less guesswork. More intelligence. Better opportunities.</small></div></div>
          </div>
        </aside>

        <section className={styles.formPanel} aria-labelledby="auth-title">
          <div className={styles.formIntro}>
            <span className={styles.formEyebrow}>WELCOME TO SHERIFF SALE HUNTER</span>
            <h2 id="auth-title">{mode === "create" ? "Create your account" : mode === "login" ? "Welcome back" : "Reset your password"}</h2>
            <p>{mode === "create" ? "Create an account, then choose a plan to open the dashboard." : mode === "login" ? "Log in to continue to your research workspace." : "Enter your email and we will send you a link to set a new password."}</p>
          </div>

          <div className={styles.modeSwitch} role="tablist" aria-label="Account access">
            <button type="button" role="tab" aria-selected={mode === "create"} onClick={() => switchMode("create")} className={mode === "create" ? styles.selected : ""}>Create account</button>
            <button type="button" role="tab" aria-selected={mode !== "create"} onClick={() => switchMode("login")} className={mode !== "create" ? styles.selected : ""}>Log in</button>
          </div>

          <form noValidate onSubmit={submit} className={styles.form}>
            {mode === "create" && <label>Full name<input autoComplete="name" name="name" type="text" placeholder="Your name" /></label>}
            <label>Email address<span className={styles.inputWrap}><Mail aria-hidden="true" /><input autoComplete="email" name="email" type="email" required placeholder="you@example.com" /></span></label>
            {mode !== "reset" && <label>Password<span className={styles.inputWrap}><LockKeyhole aria-hidden="true" /><input autoComplete={mode === "create" ? "new-password" : "current-password"} name="password" type={showPassword ? "text" : "password"} required minLength={8} placeholder="At least 8 characters" /><button type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}</button></span></label>}
            {error && <p className={styles.error} role="alert">{error}</p>}
            {notice && <p className={styles.notice} role="status">{notice}</p>}
            <button type="submit" className={styles.submit} disabled={busy}>{busy ? "Please wait…" : mode === "create" ? "Create account" : mode === "login" ? "Log in" : "Send reset link"}<ArrowRight aria-hidden="true" /></button>
          </form>
          {mode === "login" && <button type="button" className={styles.linkButton} onClick={() => switchMode("reset")}>Forgot your password?</button>}
          {mode === "reset" && <button type="button" className={styles.linkButton} onClick={() => switchMode("login")}>Back to log in</button>}

          <p className={styles.terms}>Listings, values, and sale dates should be verified with their original sources before bidding.</p>
        </section>
      </section>
    </main>
  );
}
