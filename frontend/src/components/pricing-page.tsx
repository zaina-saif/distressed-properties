"use client";

import { ArrowUpRight, Check, Database } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { STATES } from "@/lib/states";
import { getStateSummary } from "@/services/properties";

import styles from "./marketing-home.module.css";

export const ANNUAL_DISCOUNT = 0.1;

export type PlanCard = { id: "free" | "starter" | "pro"; name: string; monthly: number; tagline: string; coverage: string; features: string[]; cta: string; popular?: boolean };

export function plans(stateCount: number, countyCount: number | null): PlanCard[] {
  const everywhere = countyCount ? `All ${countyCount} counties across ${stateCount} states` : `Every county across ${stateCount} states`;
  return [
    {
      id: "free", name: "Free", monthly: 0, tagline: "Get to know one market.", coverage: "One county of your choice", cta: "Start free",
      features: ["Interactive sale map and list", "Search and filters by county, city or address", "Minimum bid, estimated value and gross equity",
        "Sale status and postponement history", "Property photos and source links", "10 full property reports a month"],
    },
    {
      id: "starter", name: "Starter", monthly: 19.99, tagline: "Work a whole state.", coverage: "Every county in one state", cta: "Choose Starter",
      features: ["Everything in Free", "Unlimited property reports", "Probability each sale reaches auction, with the reasons",
        "Preliminary lien pre-screening", "Investor Spotlight ranking by expected equity", "Change your state every 30 days"],
    },
    {
      id: "pro", name: "Pro", monthly: 49.99, tagline: "See every opportunity we track.", coverage: everywhere, cta: "Choose Pro", popular: true,
      features: ["Everything in Starter", "Every state and county as soon as we add it", "Excel export of any filtered list",
        "Compare opportunities across states on one map", "Priority support"],
    },
  ];
}

const FAQ = [
  { q: "When will I be charged?", a: "Starter and Pro are billed through Stripe when you subscribe, then at the start of each month or year. The Free plan never needs a card." },
  { q: "How does annual billing work?", a: `Pay for a year up front and save ${ANNUAL_DISCOUNT * 100}% compared with paying monthly. The price shown is the monthly equivalent.` },
  { q: "Can I cancel or change plans?", a: "Yes. You can change or cancel at any time, and your plan stays active until the end of the period you have paid for." },
  { q: "Which areas do you cover?", a: `Sheriff, clerk and court-officer foreclosure sales in ${STATES.map((s) => s.name).join(", ")}. We only list counties whose official sale listings we can collect, and we add more as new sources come online.` },
  { q: "How current is the data?", a: "Listings come from official county, clerk and court sources and are refreshed regularly. Each listing keeps its source link and status history, and sales can still be postponed or cancelled on the day, so always confirm with the source before bidding." },
  { q: "Is the lien screening a title search?", a: "No. Lien results are a pre-screening aid with an estimated priority and confidence. They are not legal advice or a guaranteed lien status. Get a professional title search before you bid." },
];

/** The yearly charge, in dollars to the cent; it must match the yearly Stripe price. */
export function yearlyTotal(monthly: number) {
  return Math.round(monthly * 12 * (1 - ANNUAL_DISCOUNT) * 100) / 100;
}

export function price(monthly: number, annual: boolean) {
  const value = annual ? yearlyTotal(monthly) / 12 : monthly;
  return value % 1 ? value.toFixed(2) : String(value);
}

export function PricingPage() {
  const [annual, setAnnual] = useState(false);
  const [countyCount, setCountyCount] = useState<number | null>(null);
  useEffect(() => {
    let active = true;
    const covered = new Set(STATES.map((s) => s.code));
    getStateSummary()
      .then((rows) => { if (active) setCountyCount(rows.filter((row) => covered.has(row.state)).reduce((sum, row) => sum + row.counties, 0)); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  return <div className={styles.root}>
    <SiteHeader active="pricing"/>
    <main>
      <section className="pricing-hero container">
        <span className="eyebrow">PRICING</span>
        <h1>Simple, transparent pricing.</h1>
        <p>Start free with one county. Upgrade to work a whole state, or every county we cover{countyCount ? ` (${countyCount} today)` : ""} across {STATES.length} states.</p>
        <div className="billing-toggle" role="radiogroup" aria-label="Billing period">
          <button type="button" role="radio" aria-checked={!annual} className={!annual ? "is-selected" : ""} onClick={() => setAnnual(false)}>Monthly</button>
          <button type="button" role="radio" aria-checked={annual} className={annual ? "is-selected" : ""} onClick={() => setAnnual(true)}>Annual <span>Save {ANNUAL_DISCOUNT * 100}%</span></button>
        </div>
      </section>

      <section className="pricing-grid container" aria-label="Plans">
        {plans(STATES.length, countyCount).map((plan) => <article key={plan.name} className={plan.popular ? "plan-card is-popular" : "plan-card"}>
          {plan.popular && <span className="plan-badge">Most popular</span>}
          <h2>{plan.name}</h2>
          <p className="plan-tagline">{plan.tagline}</p>
          <div className="plan-price"><strong>${price(plan.monthly, annual)}</strong><span>/mo</span></div>
          <p className="plan-billing">{plan.monthly === 0 ? "Free forever" : annual ? `$${yearlyTotal(plan.monthly).toFixed(2)} billed yearly` : "Billed monthly"}</p>
          <p className="plan-coverage">{plan.coverage}</p>
          <Link href={`/choose-plan?plan=${plan.id}&interval=${annual ? "year" : "month"}`} className={plan.popular ? "site-button plan-cta" : "site-button button-outline plan-cta"}>{plan.cta}<ArrowUpRight/></Link>
          <ul>{plan.features.map((feature) => <li key={feature}><Check size={15} aria-hidden="true"/>{feature}</li>)}</ul>
        </article>)}
      </section>

      <section className="enterprise container">
        <div className="enterprise-icon"><Database size={22}/></div>
        <div><span className="eyebrow">ENTERPRISE</span><h2>The whole feed, as data.</h2><p>For lenders, funds and brokerages that want every listing, status change and valuation delivered to their own systems. Priced per engagement.</p></div>
        <Link href="/#contact" className="site-button lime-button">Talk to us<ArrowUpRight/></Link>
      </section>

      <section className="pricing-faq container" aria-labelledby="faq-title">
        <h2 id="faq-title">Frequently asked questions</h2>
        {FAQ.map((item) => <details key={item.q}><summary>{item.q}</summary><p>{item.a}</p></details>)}
      </section>
    </main>
    <SiteFooter/>
  </div>;
}
