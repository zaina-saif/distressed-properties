"use client";

import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { ANNUAL_DISCOUNT, type PlanCard, plans, price } from "@/components/pricing-page";
import { type BillingInterval, startCheckout, startFreePlan } from "@/lib/account";
import { STATES } from "@/lib/states";
import { getPropertyCoverage } from "@/services/properties";
import type { PropertyCoverageItem } from "@/types/property";

import styles from "./marketing-home.module.css";

type PlanId = PlanCard["id"];

export function ChoosePlan({ initialPlan, initialInterval, cancelled }: { initialPlan?: string; initialInterval?: string; cancelled?: boolean }) {
  const router = useRouter();
  const { session, account, loading, refresh } = useAccount();
  const [plan, setPlan] = useState<PlanId>(initialPlan === "starter" || initialPlan === "pro" ? initialPlan : "free");
  const [interval, setBillingInterval] = useState<BillingInterval>(initialInterval === "year" ? "year" : "month");
  const [state, setState] = useState("");
  const [county, setCounty] = useState("");
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(cancelled ? "Checkout was cancelled. Nothing was charged." : null);

  useEffect(() => {
    if (!loading && !session) router.replace(`/get-started?next=${encodeURIComponent("/choose-plan")}&plan=${plan}`);
  }, [loading, plan, router, session]);
  useEffect(() => {
    getPropertyCoverage("scheduled").then(setCoverage).catch(() => setCoverage([]));
  }, []);

  const counties = useMemo(() => coverage.filter((item) => item.state === state && item.property_count > 0)
    .sort((a, b) => a.county.localeCompare(b.county)), [coverage, state]);
  const cards = plans(STATES.length, null);
  const paidAvailable = new Set(account?.paid_plans_available ?? []);

  async function submit() {
    setError(null);
    if (plan === "free" && (!state || !county)) return setError("Choose the state and county your Free plan covers.");
    if (plan === "starter" && !state) return setError("Choose the state your Starter plan covers.");
    setBusy(true);
    try {
      if (plan === "free") {
        await startFreePlan(state, county);
        await refresh();
        router.push("/dashboard");
      } else {
        const { url } = await startCheckout(plan, interval, plan === "starter" ? state : undefined);
        window.location.assign(url);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  const activePaid = account && ["starter", "pro"].includes(account.plan) && ["active", "trialing", "past_due"].includes(account.plan_status);
  return <div className={styles.root}>
    <SiteHeader active="pricing"/>
    <main className="choose-plan container">
      <span className="eyebrow">CHOOSE YOUR PLAN</span>
      <h1>Pick the coverage you need.</h1>
      {account?.is_developer || activePaid ? (
        <div className="choose-plan-done">
          <p>{account?.is_developer ? "You have developer access to every state and feature." : `You are on the ${account?.plan} plan.`} Change or cancel a paid plan from your account.</p>
          <div className="choose-plan-actions"><Link href="/dashboard" className="site-button">Open the dashboard<ArrowRight/></Link><Link href="/account" className="site-button button-outline">Your account</Link></div>
        </div>
      ) : <>
        <div className="billing-toggle" role="radiogroup" aria-label="Billing period">
          <button type="button" role="radio" aria-checked={interval === "month"} className={interval === "month" ? "is-selected" : ""} onClick={() => setBillingInterval("month")}>Monthly</button>
          <button type="button" role="radio" aria-checked={interval === "year"} className={interval === "year" ? "is-selected" : ""} onClick={() => setBillingInterval("year")}>Annual <span>Save {ANNUAL_DISCOUNT * 100}%</span></button>
        </div>
        <div className="plan-options" role="radiogroup" aria-label="Plan">
          {cards.map((card) => {
            const unavailable = card.id !== "free" && !paidAvailable.has(card.id);
            return <button key={card.id} type="button" role="radio" aria-checked={plan === card.id} disabled={unavailable}
              className={plan === card.id ? "plan-option is-selected" : "plan-option"} onClick={() => setPlan(card.id)}>
              <span className="plan-option-head"><strong>{card.name}</strong>{plan === card.id && <Check size={16}/>}</span>
              <span className="plan-option-price">${price(card.monthly, interval === "year")}<small>/mo</small></span>
              <span className="plan-option-coverage">{card.coverage}</span>
              {unavailable && <span className="plan-option-note">Not available for purchase yet</span>}
            </button>;
          })}
        </div>
        {plan !== "pro" && <div className="coverage-pickers">
          <label>State<select value={state} onChange={(event) => { setState(event.target.value); setCounty(""); }}>
            <option value="">Choose a state</option>{STATES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
          </select></label>
          {plan === "free" && <label>County<select value={county} disabled={!state} onChange={(event) => setCounty(event.target.value)}>
            <option value="">{state ? "Choose a county" : "Choose a state first"}</option>
            {counties.map((item) => <option key={item.county} value={item.county}>{item.county} ({item.property_count})</option>)}
          </select></label>}
          <p>{plan === "free" ? "The Free plan shows one county." : "Starter shows every county in one state."} You can change it once every 30 days.</p>
        </div>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="button" className="site-button choose-plan-submit" disabled={busy || loading} onClick={submit}>
          {busy ? "Please wait…" : plan === "free" ? "Start the Free plan" : "Continue to secure payment"}<ArrowRight/>
        </button>
        {plan !== "free" && <p className="choose-plan-note">Payment is handled by Stripe. You can cancel any time from your account.</p>}
      </>}
    </main>
    <SiteFooter/>
  </div>;
}
