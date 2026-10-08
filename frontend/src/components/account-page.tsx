"use client";

import { ArrowRight, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { changeCoverage, openBillingPortal } from "@/lib/account";
import { STATES } from "@/lib/states";
import { getPropertyCoverage } from "@/services/properties";
import type { PropertyCoverageItem } from "@/types/property";

import styles from "./marketing-home.module.css";

const stateName = (code: string | null) => STATES.find((s) => s.code === code)?.name ?? code ?? "";
const day = (value: string | null) => value ? new Date(value).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }) : null;

export function AccountPage({ checkoutSucceeded }: { checkoutSucceeded?: boolean }) {
  const router = useRouter();
  const { session, account, loading, refresh, signOut } = useAccount();
  const [waiting, setWaiting] = useState(Boolean(checkoutSucceeded));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [state, setState] = useState("");
  const [county, setCounty] = useState("");

  useEffect(() => {
    if (!loading && !session) router.replace(`/get-started?mode=login&next=${encodeURIComponent("/account")}`);
  }, [loading, router, session]);

  // Stripe confirms payment to our server by webhook, which can take a few seconds.
  useEffect(() => {
    if (!waiting) return;
    let tries = 0;
    const timer = window.setInterval(async () => {
      tries += 1;
      const next = await refresh();
      if (next?.has_access || tries >= 15) {
        window.clearInterval(timer);
        setWaiting(false);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh, waiting]);

  useEffect(() => {
    getPropertyCoverage("scheduled").then(setCoverage).catch(() => setCoverage([]));
  }, []);
  const counties = useMemo(() => coverage.filter((item) => item.state === state && item.property_count > 0)
    .sort((a, b) => a.county.localeCompare(b.county)), [coverage, state]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const canChange = account && ["free", "starter"].includes(account.plan) && !account.is_developer
    && (!account.coverage_change_available_at || new Date(account.coverage_change_available_at) <= new Date());
  const coverageText = !account ? "" : account.is_developer || account.plan === "pro" ? "Every state and county"
    : account.plan === "starter" ? stateName(account.coverage_state)
    : account.coverage_county ? `${account.coverage_county} County, ${stateName(account.coverage_state)}` : "Not chosen";

  return <div className={styles.root}>
    <SiteHeader active="pricing"/>
    <main className="account-page container">
      <span className="eyebrow">YOUR ACCOUNT</span>
      <h1>Account</h1>
      {waiting && <p className="form-notice" role="status">Payment received. Confirming your plan with Stripe…</p>}
      {checkoutSucceeded && !waiting && account?.has_access && <p className="form-notice" role="status">Your plan is active.</p>}
      {!account ? <p className="account-muted">{loading ? "Loading…" : "We could not load your account. Try again shortly."}</p> : <>
        <dl className="account-facts">
          <div><dt>Email</dt><dd>{account.email}</dd></div>
          <div><dt>Plan</dt><dd>{account.is_developer ? "Developer (full access)" : account.plan === "none" ? "No plan" : account.plan[0].toUpperCase() + account.plan.slice(1)}
            {!account.is_developer && account.plan !== "none" && <span className={`plan-status status-${account.plan_status}`}>{account.plan_status.replace("_", " ")}</span>}</dd></div>
          <div><dt>Coverage</dt><dd>{coverageText}</dd></div>
          {account.current_period_end && <div><dt>{account.plan_status === "canceled" ? "Ended" : "Renews"}</dt><dd>{day(account.current_period_end)}</dd></div>}
        </dl>
        {account.plan_status === "past_due" && <p className="form-error">Your last payment failed. Update your payment method in billing to keep access.</p>}
        <div className="choose-plan-actions">
          {account.has_access ? <Link href="/dashboard" className="site-button">Open the dashboard<ArrowRight/></Link>
            : <Link href="/choose-plan" className="site-button">Choose a plan<ArrowRight/></Link>}
          {account.has_billing && <button type="button" className="site-button button-outline" disabled={busy}
            onClick={() => run(async () => { window.location.assign((await openBillingPortal()).url); })}>Manage billing</button>}
          {account.has_access && account.plan === "free" && <Link href="/choose-plan?plan=starter" className="site-button button-outline">Upgrade</Link>}
          <button type="button" className="site-button button-ghost" onClick={async () => { await signOut(); router.push("/"); }}><LogOut/>Sign out</button>
        </div>
        <section className="profile-card">
          <div><h2>Investor profile</h2><p>Tell us your budget, markets and strategy so we can send you investment opportunities that fit. Optional.</p></div>
          <Link href="/profile" className="site-button button-outline">Edit profile<ArrowRight/></Link>
        </section>
        {account.has_access && ["free", "starter"].includes(account.plan) && !account.is_developer && <section className="coverage-change">
          <h2>Change your coverage</h2>
          {canChange ? <div className="coverage-pickers">
            <label>State<select value={state} onChange={(event) => { setState(event.target.value); setCounty(""); }}>
              <option value="">Choose a state</option>{STATES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
            </select></label>
            {account.plan === "free" && <label>County<select value={county} disabled={!state} onChange={(event) => setCounty(event.target.value)}>
              <option value="">{state ? "Choose a county" : "Choose a state first"}</option>
              {counties.map((item) => <option key={item.county} value={item.county}>{item.county} ({item.property_count})</option>)}
            </select></label>}
            <button type="button" className="site-button" disabled={busy || !state || (account.plan === "free" && !county)}
              onClick={() => run(async () => { await changeCoverage(state, account.plan === "free" ? county : undefined); await refresh(); })}>Save coverage</button>
          </div> : <p className="account-muted">You can change it again on {day(account.coverage_change_available_at)}.</p>}
        </section>}
        {error && <p className="form-error" role="alert">{error}</p>}
      </>}
    </main>
    <SiteFooter/>
  </div>;
}
