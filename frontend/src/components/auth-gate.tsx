"use client";

import { ArrowLeft, ArrowRight, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { DistressedPropertiesBrand } from "@/components/brand-logo";

import styles from "./auth-gate.module.css";

type AuthMode = "create" | "login";

export function AuthGate() {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("create");
  const [showPassword, setShowPassword] = useState(false);

  function continueToPlatform(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    router.push("/dashboard");
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link href="/" className={styles.brand}><DistressedPropertiesBrand /></Link>
        <Link href="/" className={styles.backLink}><ArrowLeft aria-hidden="true" />Back to home</Link>
      </header>
      <section className={styles.authLayout}>
        <aside className={styles.story}>
          <Image className={styles.storyImage} src="/marketing/nj-neighborhood.jpg" alt="New Jersey residential neighborhood" fill sizes="(max-width: 800px) 100vw, 45vw" />
          <div className={styles.storyWash} />
          <div className={styles.storyContent}>
            <span className={styles.eyebrow}><i />YOUR DISTRESSED PROPERTY EXPERT</span>
            <h1>Find the opportunity<br /><em>before everyone</em><br />else does.</h1>
            <p>See the minimum bid, estimated value, sale history, and research signals in one place.</p>
            <div className={styles.storyNote}><span><LockKeyhole aria-hidden="true" /></span><div><b>Your research workspace</b><small>Less guesswork. More intelligence. Better opportunities.</small></div></div>
          </div>
        </aside>

        <section className={styles.formPanel} aria-labelledby="auth-title">
          <div className={styles.formIntro}>
            <span className={styles.formEyebrow}>WELCOME TO DISTRESSED PROPERTIES PRO</span>
            <h2 id="auth-title">{mode === "create" ? "Create your account" : "Welcome back"}</h2>
            <p>{mode === "create" ? "No login is needed to view the dashboard during development. Choose Create account and continue to open it." : "Sign-in will be set up for launch. For now, you can open the dashboard without logging in."}</p>
          </div>

          <div className={styles.modeSwitch} role="tablist" aria-label="Account access">
            <button type="button" role="tab" aria-selected={mode === "create"} onClick={() => setMode("create")} className={mode === "create" ? styles.selected : ""}>Create account</button>
            <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")} className={mode === "login" ? styles.selected : ""}>Log in</button>
          </div>

          <form noValidate onSubmit={continueToPlatform} className={styles.form}>
            {mode === "create" && <label>Full name<input autoComplete="name" name="name" type="text" placeholder="Your name (optional for preview)" /></label>}
            <label>Email address<span className={styles.inputWrap}><Mail aria-hidden="true" /><input autoComplete="email" name="email" type="email" placeholder="you@example.com (optional for preview)" /></span></label>
            <label>Password<span className={styles.inputWrap}><LockKeyhole aria-hidden="true" /><input autoComplete={mode === "create" ? "new-password" : "current-password"} name="password" type={showPassword ? "text" : "password"} placeholder="Optional for preview" /><button type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}</button></span></label>
            <button type="submit" className={styles.submit}>{mode === "create" ? "Create account and continue" : "Log in and continue"}<ArrowRight aria-hidden="true" /></button>
          </form>

          <p className={styles.previewNote}><strong>Developer preview:</strong> no account or login is required right now. The buttons open the dashboard directly. We’ll connect account creation and secure sign-in when the product launches.</p>
          <p className={styles.terms}>Listings, values, and sale dates should be verified with their original sources before bidding.</p>
        </section>
      </section>
    </main>
  );
}
