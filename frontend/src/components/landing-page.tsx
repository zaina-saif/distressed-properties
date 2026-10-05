"use client";

import { ArrowRight, CalendarDays, Clock, Landmark, MapPin, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { DistressSaleLogo } from "@/components/brand-logo";
import { PropertyPhoto } from "@/components/property-photo";
import { getLandingSummary, getProperties, type LandingSummary } from "@/services/properties";
import type { Property } from "@/types/property";

function dollars(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function compactDollars(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function ddmmyyyy(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${pad(parsed.getUTCDate())}/${pad(parsed.getUTCMonth() + 1)}/${parsed.getUTCFullYear()}`;
}

function number(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("en-US");
}

function MapStat({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <div className="flex gap-3 border-b border-slate-200 py-4 last:border-0">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700">{icon}</span>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <p className="mt-0.5 text-2xl font-bold tabular-nums text-slate-950">{value}</p>
        <p className="mt-0.5 text-sm text-slate-600">{detail}</p>
      </div>
    </div>
  );
}

function EquityCard({ property }: { property: Property }) {
  return (
    <Link
      href={`/dashboard?q=${encodeURIComponent(property.sheriff_number)}`}
      className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-gradient-to-br from-slate-100 to-slate-200">
        <PropertyPhoto property={property} />
        <span className="absolute left-3 top-3 rounded-full bg-slate-950/80 px-2.5 py-1 text-xs font-semibold text-white">{property.county} County</span>
      </div>
      <div className="p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Gross equity</p>
        <p className="text-2xl font-bold tabular-nums text-slate-950">{dollars(property.gross_equity)}</p>
        <p className="mt-2 flex items-start gap-1.5 text-sm text-slate-700">
          <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
          <span className="select-none blur-[5px]" aria-hidden="true">{property.street_address}, {property.city}</span>
          <span className="sr-only">Address hidden</span>
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 text-xs">
          <div><dt className="text-slate-500">Est. value</dt><dd className="font-semibold text-slate-900">{dollars(property.zestimate ?? property.market_value)}</dd></div>
          <div><dt className="text-slate-500">Minimum bid</dt><dd className="font-semibold text-slate-900">{dollars(property.minimum_asking_amount)}</dd></div>
          <div><dt className="text-slate-500">Sale date</dt><dd className="font-semibold text-slate-900">{ddmmyyyy(property.current_sale_date)}</dd></div>
          <div><dt className="text-slate-500">Chance of auction</dt><dd className="font-semibold text-slate-900">{property.sale_probability == null ? "—" : `${Math.round(property.sale_probability * 100)}%`}</dd></div>
        </dl>
      </div>
    </Link>
  );
}

export function LandingPage() {
  const [summary, setSummary] = useState<LandingSummary | null>(null);
  const [topEquity, setTopEquity] = useState<Property[]>([]);

  useEffect(() => {
    let active = true;
    getLandingSummary().then((result) => { if (active) setSummary(result); }).catch(() => undefined);
    getProperties({
      states: ["NJ"],
      statusContains: "scheduled",
      futureOnly: true,
      sort: "gross-equity",
      sortDirection: "desc",
      page: 1,
      pageSize: 6,
    })
      .then((result) => { if (active) setTopEquity(result.items.filter((item) => (item.gross_equity ?? 0) > 0)); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link href="/" className="flex items-center gap-3">
            <DistressSaleLogo />
            <span className="font-bold tracking-tight text-slate-950">NJ Sheriff Sale Pro</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm font-medium text-slate-600">
            <a href="#counties" className="hidden rounded-lg px-3 py-2 hover:bg-slate-100 sm:block">Counties</a>
            <Link href="/dashboard?spotlight=1" className="hidden rounded-lg px-3 py-2 hover:bg-slate-100 sm:block">Investor Spotlight</Link>
            <Link href="/dashboard" className="rounded-lg bg-teal-600 px-4 py-2 font-semibold text-white hover:bg-teal-700">Open the map</Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 lg:grid-cols-[1.15fr_1fr] lg:py-16">
          <div className="flex flex-col justify-center">
            <p className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">
              <Landmark className="h-3.5 w-3.5" />All {summary?.counties ?? 17} New Jersey counties with online sheriff sales
            </p>
            <h1 className="text-4xl font-bold leading-tight tracking-tight text-slate-950 sm:text-5xl">
              New Jersey sheriff sales, with the equity already worked out.
            </h1>
            <p className="mt-4 max-w-xl text-lg leading-7 text-slate-600">
              Every scheduled sheriff sale in one place: the minimum bid, a market value, the equity behind the debt, and the chance each sale actually goes to auction on its next date.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-5 py-3 font-semibold text-white shadow-sm hover:bg-teal-700">
                Explore the live map<ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/dashboard?spotlight=1" className="inline-flex items-center gap-2 rounded-xl bg-amber-50 px-5 py-3 font-semibold text-amber-900 ring-1 ring-inset ring-amber-200 hover:bg-amber-100">
                <Sparkles className="h-4 w-4" />Investor Spotlight
              </Link>
            </div>
            <dl className="mt-8 grid max-w-lg grid-cols-3 gap-4">
              <div><dt className="text-xs text-slate-500">Upcoming sales</dt><dd className="text-2xl font-bold tabular-nums">{number(summary?.upcoming_sales)}</dd></div>
              <div><dt className="text-xs text-slate-500">In the next 7 days</dt><dd className="text-2xl font-bold tabular-nums">{number(summary?.next_7_days)}</dd></div>
              <div><dt className="text-xs text-slate-500">Counties</dt><dd className="text-2xl font-bold tabular-nums">{number(summary?.counties)}</dd></div>
            </dl>
          </div>

          <aside className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold text-slate-950">What&apos;s on the map right now</h2>
            <p className="text-sm text-slate-500">Live from the latest county sheriff listings{summary?.last_updated ? `, updated ${ddmmyyyy(summary.last_updated)}` : ""}.</p>
            <div className="mt-2">
              <MapStat
                icon={<TrendingUp className="h-5 w-5" />}
                label="Equity behind the debt"
                value={compactDollars(summary?.equity_behind_debt)}
                detail={`Across ${number(summary?.sales_with_equity)} upcoming sales where the estimated value is above the minimum bid.`}
              />
              <MapStat
                icon={<CalendarDays className="h-5 w-5" />}
                label="Sales in the next 7 days"
                value={number(summary?.next_7_days)}
                detail="Scheduled to be offered at a sheriff sale within a week. Many are postponed on the day."
              />
              <MapStat
                icon={<Clock className="h-5 w-5" />}
                label="Added to the map this week"
                value={number(summary?.new_this_week)}
                detail={`Out of ${number(summary?.upcoming_sales)} upcoming scheduled sales across ${number(summary?.counties)} counties.`}
              />
            </div>
            <Link href="/dashboard" className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-teal-700 hover:underline">Open the map<ArrowRight className="h-4 w-4" /></Link>
          </aside>
        </section>

        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-2xl font-bold tracking-tight text-slate-950">The biggest trapped equity on the block</h2>
                <p className="mt-1 text-sm text-slate-600">Upcoming NJ sheriff sales with the widest gap between estimated value and minimum bid.</p>
              </div>
              <Link href="/dashboard?spotlight=1" className="inline-flex items-center gap-1.5 text-sm font-semibold text-teal-700 hover:underline">See the full ranking<ArrowRight className="h-4 w-4" /></Link>
            </div>
            <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {topEquity.length
                ? topEquity.map((property) => <EquityCard key={property.sheriff_sale_id} property={property} />)
                : [1, 2, 3].map((item) => <div key={item} className="h-80 animate-pulse rounded-2xl bg-slate-100" />)}
            </div>
            <p className="mt-4 text-xs text-slate-500">Gross equity is the estimated market value minus the minimum bid. It is not profit: liens, taxes, fees and competing bids are not deducted.</p>
          </div>
        </section>

        <section id="counties" className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
          <h2 className="text-2xl font-bold tracking-tight text-slate-950">Explore NJ Sheriff Sales</h2>
          <p className="mt-1 text-sm text-slate-600">Upcoming scheduled sales by county. Pick a county to open it on the map.</p>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(summary?.county_counts ?? []).map((item) => (
              <Link
                key={item.county}
                href={`/dashboard?county=${encodeURIComponent(item.county)}`}
                className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 transition hover:border-teal-400 hover:shadow-sm"
              >
                <span>
                  <span className="block font-bold text-slate-900">{item.county} County</span>
                  <span className="block text-xs text-slate-500">{compactDollars(item.equity_behind_debt)} equity behind the debt</span>
                </span>
                <span className="text-right">
                  <span className="block text-xl font-bold tabular-nums text-teal-700">{item.upcoming_sales}</span>
                  <span className="block text-[11px] text-slate-500">upcoming</span>
                </span>
              </Link>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl space-y-2 px-4 py-8 text-xs leading-5 text-slate-500 sm:px-6">
          <p className="font-semibold text-slate-700">NJ Sheriff Sale Pro</p>
          <p>Sale listings come from county sheriff portals (CivilView SalesWeb and the Ocean County sheriff). Market values come from Zillow and can be wrong. Sales are frequently postponed or cancelled; confirm every detail with the county sheriff&apos;s office.</p>
          <p>This is research information, not legal advice or a title search. Get a professional title search before bidding.</p>
        </div>
      </footer>
    </div>
  );
}
