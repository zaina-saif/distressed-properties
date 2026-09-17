"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Database, Search, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { getWarehouseCounties, getWarehouseCoverage, getWarehouseMonthlyCoverage, getWarehouseProperties } from "@/services/properties";
import type { WarehouseCoverage, WarehouseCursor, WarehouseMonthlyCoverage, WarehouseProperty, WarehousePropertyPage } from "@/types/warehouse-valuation";

const STATES = [
  { code: "MD", name: "Maryland" }, { code: "NY", name: "New York" },
  { code: "IL", name: "Illinois" }, { code: "FL", name: "Florida" },
  { code: "OH", name: "Ohio" }, { code: "VA", name: "Virginia" },
  { code: "DC", name: "Washington, DC" },
] as const;
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const number = new Intl.NumberFormat("en-US");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function amount(value: number | null | undefined) {
  return value == null ? "—" : money.format(value);
}

function metric(value: number | null | undefined) {
  return value == null ? "—" : number.format(value);
}

function PropertyLocation({ item }: { item: WarehouseProperty }) {
  const missingNumber = item.street_address && (item.house_number_unavailable || !/^\d/.test(item.street_address.trim()));
  const addressSource = item.address_source_id === "va_dwr_public_parcel_addresses_2026"
    ? "Virginia public parcel GIS"
    : item.address_source_id;
  return <td className="px-5 py-4">
    <p className="font-semibold text-slate-950">{item.street_address || "Street address unavailable"}</p>
    {missingNumber && <p className="text-xs font-medium text-amber-700">House number unavailable</p>}
    <p className="text-xs text-slate-500">{item.city || item.county}{item.zip_code ? ` · ${item.zip_code}` : ""}</p>
    {!item.street_address && item.latitude != null && item.longitude != null && <p className="text-[11px] text-slate-500">Parcel centroid: {item.latitude.toFixed(5)}, {item.longitude.toFixed(5)}</p>}
    {addressSource && <p className="text-[11px] text-slate-400">Location details from {item.address_snapshot_year} · {addressSource}</p>}
    <p className="mt-1 break-all text-[11px] text-slate-400">{item.source_parcel_id}</p>
  </td>;
}

export function EstimatedPriceView() {
  const [state, setState] = useState("NY");
  const [year, setYear] = useState(new Date().getFullYear());
  const [coverage, setCoverage] = useState<WarehouseCoverage | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [counties, setCounties] = useState<string[]>([]);
  const [county, setCounty] = useState("");
  const [countyLoading, setCountyLoading] = useState(true);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<WarehouseCursor | null>(null);
  const [history, setHistory] = useState<(WarehouseCursor | null)[]>([]);
  const [propertyPage, setPropertyPage] = useState<WarehousePropertyPage | null>(null);
  const [propertyLoading, setPropertyLoading] = useState(true);
  const [propertyError, setPropertyError] = useState<string | null>(null);
  const [monthly, setMonthly] = useState<WarehouseMonthlyCoverage | null>(null);
  const [monthlyLoading, setMonthlyLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getWarehouseCoverage(state)
      .then((result) => { if (active) setCoverage(result); })
      .catch(() => { if (active) setCoverageError("Unable to load warehouse coverage. Check the backend and warehouse connection."); })
      .finally(() => { if (active) setCoverageLoading(false); });
    return () => { active = false; };
  }, [state]);

  useEffect(() => {
    let active = true;
    getWarehouseCounties(state, year)
      .then((result) => {
        if (!active) return;
        setCounties(result);
        setCounty(result[0] ?? "");
        setCountyLoading(false);
        if (!result.length) { setPropertyLoading(false); setMonthlyLoading(false); }
      })
      .catch(() => {
        if (!active) return;
        setCounties([]);
        setCounty("");
        setCountyLoading(false);
        setPropertyError("Unable to load counties for this year.");
        setPropertyLoading(false);
        setMonthlyLoading(false);
      });
    return () => { active = false; };
  }, [state, year]);

  useEffect(() => {
    if (!county) return;
    let active = true;
    getWarehouseProperties({ state, year, county, query: search, cursor })
      .then((result) => { if (active) setPropertyPage(result); })
      .catch(() => { if (active) setPropertyError("Unable to load property snapshots for this county."); })
      .finally(() => { if (active) setPropertyLoading(false); });
    return () => { active = false; };
  }, [state, year, county, search, cursor]);

  useEffect(() => {
    if (!county) return;
    let active = true;
    getWarehouseMonthlyCoverage(state, county, year)
      .then((result) => { if (active) setMonthly(result); })
      .catch(() => { if (active) setMonthly(null); })
      .finally(() => { if (active) setMonthlyLoading(false); });
    return () => { active = false; };
  }, [state, year, county]);

  const stateName = STATES.find((item) => item.code === state)?.name ?? state;
  const missingYears = coverage?.years.filter((item) => item.year < new Date().getFullYear() && (item.sales === 0 || item.snapshots === 0)) ?? [];
  const testMetrics = coverage?.model?.metrics.test;
  const leadingFactors = Object.entries(coverage?.model?.metrics.feature_weightages ?? {})
    .sort((left, right) => right[1] - left[1]).slice(0, 5);

  function resetPropertyPaging() {
    setCursor(null);
    setHistory([]);
    setPropertyPage(null);
    setPropertyLoading(true);
    setPropertyError(null);
  }

  function chooseState(next: string) {
    if (next === state) return;
    setState(next);
    setYear(new Date().getFullYear());
    setCoverage(null);
    setCoverageLoading(true);
    setCoverageError(null);
    setCounties([]);
    setCounty("");
    setCountyLoading(true);
    setMonthly(null);
    setMonthlyLoading(true);
    setSearch("");
    setSearchInput("");
    resetPropertyPaging();
  }

  function chooseYear(next: number) {
    setYear(next);
    setCounties([]);
    setCounty("");
    setCountyLoading(true);
    setMonthly(null);
    setMonthlyLoading(true);
    resetPropertyPaging();
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
    resetPropertyPaging();
  }

  return (
    <section className="min-h-0 flex-1 overflow-y-auto bg-slate-50 px-4 py-6 sm:px-6 lg:px-8" aria-labelledby="estimated-price-heading">
      <div className="mx-auto max-w-7xl space-y-5">
        <div className="rounded-2xl bg-slate-950 px-5 py-6 text-white shadow-sm sm:px-8 sm:py-8">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-teal-300">Historical property warehouse</p>
          <h2 id="estimated-price-heading" className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">Estimated Price</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Review imported property snapshots and sale coverage by state. This view is independent of sheriff-sale listings. Model prices appear only after a state model passes evaluation and scores a current-year property.</p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Jurisdiction</p>
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Select state">
            {STATES.map((item) => <button key={item.code} type="button" onClick={() => chooseState(item.code)} aria-pressed={state === item.code}
              className={`shrink-0 rounded-xl border px-4 py-2.5 text-sm font-semibold ${state === item.code ? "border-teal-600 bg-teal-600 text-white" : "border-slate-200 text-slate-600 hover:border-teal-300 hover:text-teal-700"}`}>{item.name}</button>)}
          </div>
        </div>

        {coverageError ? <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">{coverageError}</div> : coverageLoading ? (
          <div className="h-56 animate-pulse rounded-2xl bg-slate-200" aria-label="Loading coverage" />
        ) : coverage && <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold text-slate-500">Sale records since 2020</p><p className="mt-2 text-2xl font-bold text-slate-950">{metric(coverage.total_sales)}</p></div>
            <div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold text-slate-500">Property snapshots since 2020</p><p className="mt-2 text-2xl font-bold text-slate-950">{metric(coverage.total_snapshots)}</p></div>
            <div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold text-slate-500">Latest recorded sale</p><p className="mt-2 text-xl font-bold text-slate-950">{coverage.latest_sale ?? "—"}</p></div>
            <div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold text-slate-500">State model</p><p className="mt-2 text-xl font-bold text-slate-950">{coverage.model?.status ?? "Not trained"}</p></div>
          </div>

          {(missingYears.length > 0 || coverage.future_dated_sales > 0) && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div>
              {missingYears.length > 0 && <p>Missing source records in {missingYears.map((item) => `${item.year} (${item.sales === 0 ? "sales" : ""}${item.sales === 0 && item.snapshots === 0 ? " and " : ""}${item.snapshots === 0 ? "snapshots" : ""})`).join(", ")}.</p>}
              {coverage.future_dated_sales > 0 && <p>{metric(coverage.future_dated_sales)} sale records are dated after {coverage.as_of} and are excluded from the counts below.</p>}
            </div></div>
          </div>}

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-200 px-5 py-4"><h3 className="font-bold text-slate-950">{stateName} coverage by year</h3><p className="mt-1 text-xs text-slate-500">Counts reflect imported records, not distinct properties. Current year is still in progress.{coverage.refreshed_at ? ` Refreshed ${new Date(coverage.refreshed_at).toLocaleString()}.` : " Coverage summary has not been refreshed."}</p></div>
              <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3">Year</th><th className="px-4 py-3 text-right">Sales</th><th className="px-4 py-3 text-right">Property snapshots</th><th className="px-4 py-3 text-right">Sale counties</th><th className="px-4 py-3 text-right">Snapshot counties</th><th className="px-5 py-3">Status</th></tr></thead><tbody className="divide-y divide-slate-100">
                {coverage.years.map((item) => <tr key={item.year} className="text-slate-700"><td className="px-5 py-3 font-semibold text-slate-950">{item.year}</td><td className="px-4 py-3 text-right tabular-nums">{metric(item.sales)}</td><td className="px-4 py-3 text-right tabular-nums">{metric(item.snapshots)}</td><td className="px-4 py-3 text-right tabular-nums">{item.sale_counties}</td><td className="px-4 py-3 text-right tabular-nums">{item.snapshot_counties}</td><td className="px-5 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${item.sales && item.snapshots ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>{item.sales && item.snapshots ? "Records present" : "Missing data"}</span></td></tr>)}
              </tbody></table></div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="font-bold text-slate-950">Model validation</h3>
              <p className="mt-1 text-xs text-slate-500">Most recent state-level XGBoost run; test period is held out from training.</p>
              {coverage.model ? <div className="mt-5 space-y-3 text-sm">
                <div className="flex justify-between gap-3"><span className="text-slate-500">Status</span><strong>{coverage.model.status}</strong></div>
                <div className="flex justify-between gap-3"><span className="text-slate-500">Test sale count</span><strong>{metric(coverage.model.row_counts.test)}</strong></div>
                <div className="flex justify-between gap-3"><span className="text-slate-500">Test MAE</span><strong>{amount(testMetrics?.xgboost?.mae)}</strong></div>
                <div className="flex justify-between gap-3"><span className="text-slate-500">County-median MAE</span><strong>{amount(testMetrics?.prior_county_median?.mae)}</strong></div>
                <div className="flex justify-between gap-3"><span className="text-slate-500">Within 20% of sale price</span><strong>{testMetrics?.xgboost?.within_20_percent == null ? "—" : `${testMetrics.xgboost.within_20_percent}%`}</strong></div>
                {leadingFactors.length > 0 && <div className="border-t border-slate-100 pt-3">
                  <p className="font-semibold text-slate-700">Leading predictive factors</p>
                  <div className="mt-2 space-y-1">{leadingFactors.map(([factor, weight]) => <div key={factor} className="flex justify-between gap-3 text-xs"><span className="text-slate-500">{factor.replaceAll("_", " ")}</span><span className="font-semibold text-slate-700">{weight}%</span></div>)}</div>
                  <p className="mt-2 text-[11px] text-slate-500">Validation-set permutation scores; these are not causal weights.</p>
                </div>}
                <div className="border-t border-slate-100 pt-3 text-xs text-slate-500">Model: {coverage.model.model_version} · Data as of {coverage.model.data_as_of ?? "unknown"}</div>
                <p className="text-xs text-amber-800">Initial screening model only. A price estimate is not an appraisal or verified sale equity.</p>
              </div> : <div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No state model has been trained or evaluated yet. Estimated prices cannot be verified or displayed until a validated model is available.</div>}
              <div className="mt-5 flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-500"><Database className="mt-0.5 h-4 w-4 shrink-0" />{coverage.coverage_note}</div>
            </div>
          </div>
        </>}

        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 p-5 lg:flex-row lg:items-end lg:justify-between">
            <div><h3 className="font-bold text-slate-950">Property snapshot explorer</h3><p className="mt-1 text-xs text-slate-500">Browse imported assessment/parcel records, including properties with no sheriff sale.</p></div>
            <div className="flex flex-wrap gap-2">
              <label className="text-xs font-semibold text-slate-500">Snapshot year<select value={year} onChange={(event) => chooseYear(Number(event.target.value))} className="mt-1 block rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800">{Array.from({ length: new Date().getFullYear() - 2019 }, (_, index) => new Date().getFullYear() - index).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="text-xs font-semibold text-slate-500">County/locality<select value={county} disabled={countyLoading || !counties.length} onChange={(event) => { setCounty(event.target.value); setMonthly(null); setMonthlyLoading(true); resetPropertyPaging(); }} className="mt-1 block max-w-56 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800"><option value="">{countyLoading ? "Loading…" : "No records"}</option>{counties.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            </div>
          </div>
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2"><h4 className="text-sm font-semibold text-slate-900">Monthly sale coverage{county ? ` · ${county}` : ""}</h4><p className="text-xs text-slate-500">A zero is a possible gap, not proof that a source has no sales.</p></div>
            {monthlyLoading ? <p className="mt-3 text-xs text-slate-500">Loading monthly counts…</p> : monthly ? <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-12">{monthly.months.map((item) => <div key={item.month} className={`rounded-lg border px-2 py-2 text-center ${item.sales === 0 ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700"}`}><p className="text-[11px] font-semibold">{MONTHS[item.month - 1]}</p><p className="mt-0.5 text-sm font-bold tabular-nums">{metric(item.sales)}</p></div>)}</div> : <p className="mt-3 text-xs text-slate-500">Monthly coverage unavailable.</p>}
          </div>
          <form onSubmit={submitSearch} className="flex items-center gap-2 border-b border-slate-200 px-5 py-3"><Search className="h-4 w-4 text-slate-400" /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search address or parcel ID in this county" aria-label="Search warehouse properties" className="min-w-0 flex-1 text-sm outline-none" />{searchInput && <button type="button" onClick={() => { setSearchInput(""); setSearch(""); resetPropertyPaging(); }} aria-label="Clear search" className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>}<button type="submit" className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-700">Search</button></form>
          {propertyError ? <div role="alert" className="m-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{propertyError}</div> : countyLoading || propertyLoading ? <div className="p-8 text-center text-sm text-slate-500">Loading property records…</div> : !county || !propertyPage?.items.length ? <div className="p-8 text-center text-sm text-slate-500">No snapshots match this state, year, county, and search.</div> : <>
            <div className="overflow-x-auto"><table className="w-full min-w-[1100px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3">Property</th><th className="px-4 py-3">Type / features</th><th className="px-4 py-3 text-right">Last sale</th><th className="px-4 py-3 text-right">Estimated price</th><th className="px-5 py-3">Source</th></tr></thead><tbody className="divide-y divide-slate-100">{propertyPage.items.map((item) => <tr key={`${item.source_id}-${item.source_parcel_id}`} className="align-top"><PropertyLocation item={item} /><td className="px-4 py-4 text-slate-700"><p>{item.property_type || "Type unavailable"}</p><p className="mt-1 text-xs text-slate-500">{item.living_area ? `${number.format(item.living_area)} sq ft` : "Sq ft —"} · Built {item.year_built || "—"} · {item.bedrooms ?? "—"} bd / {item.bathrooms ?? "—"} ba</p>{item.feature_snapshot_year && <p className="mt-1 text-[11px] text-slate-400">Building details: {item.feature_snapshot_year} NY assessment</p>}</td><td className="px-4 py-4 text-right"><p className="font-semibold text-slate-800">{amount(item.last_sale_price)}</p><p className="text-xs text-slate-500">{item.last_sale_date || "No matched sale"}</p></td><td className="px-4 py-4 text-right"><p className="font-bold text-teal-700">{amount(item.estimated_price)}</p><p className="text-xs text-slate-500">{item.estimate_status === "SCORED" ? item.model_version : item.estimate_status === "LOW_FEATURE_COVERAGE" ? "Insufficient property features" : item.estimate_status === "HISTORICAL_NOT_SCORED" ? "Historical snapshot not scored" : "No validated estimate"}</p></td><td className="max-w-48 break-all px-5 py-4 text-xs text-slate-500">{item.source_id}</td></tr>)}</tbody></table></div>
            <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3"><button type="button" disabled={!history.length} onClick={() => { const prior = history.at(-1) ?? null; setHistory((items) => items.slice(0, -1)); setCursor(prior); setPropertyLoading(true); }} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40"><ChevronLeft className="h-4 w-4" />Previous</button><span className="text-xs text-slate-500">Page {history.length + 1} · {propertyPage.items.length} records</span><button type="button" disabled={!propertyPage.next_cursor} onClick={() => { setHistory((items) => [...items, cursor]); setCursor(propertyPage.next_cursor); setPropertyLoading(true); }} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40">Next<ChevronRight className="h-4 w-4" /></button></div>
          </>}
        </div>
      </div>
    </section>
  );
}
