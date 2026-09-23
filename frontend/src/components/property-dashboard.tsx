"use client";

import {
  ChevronLeft,
  ChevronRight,
  Filter,
  ListFilter,
  Map as MapIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Download,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { PropertyCard } from "@/components/property-card";
import { PropertyDetailModal } from "@/components/property-detail-modal";
import { PropertyMap } from "@/components/property-map";
import { PropertyTable } from "@/components/property-table";
import { downloadPropertiesXlsx, getNycAuctionCoverage, getProperties, getPropertyCoverage } from "@/services/properties";
import type { NycAuctionCoverage } from "@/services/properties";
import type { Property, PropertyCoverageItem } from "@/types/property";

const PAGE_SIZE = 24;
const NYC_COUNTIES = ["New York", "Bronx", "Kings", "Queens", "Richmond"];
const FLORIDA_COUNTIES = [
  "Alachua", "Baker", "Bay", "Bradford", "Brevard", "Broward", "Calhoun", "Charlotte", "Citrus", "Clay",
  "Collier", "Columbia", "DeSoto", "Dixie", "Duval", "Escambia", "Flagler", "Franklin", "Gadsden", "Gilchrist",
  "Glades", "Gulf", "Hamilton", "Hardee", "Hendry", "Hernando", "Highlands", "Hillsborough", "Holmes", "Indian River",
  "Jackson", "Jefferson", "Lafayette", "Lake", "Lee", "Leon", "Levy", "Liberty", "Madison", "Manatee",
  "Marion", "Martin", "Miami-Dade", "Monroe", "Nassau", "Okaloosa", "Okeechobee", "Orange", "Osceola", "Palm Beach",
  "Pasco", "Pinellas", "Polk", "Putnam", "Santa Rosa", "Sarasota", "Seminole", "St. Johns", "St. Lucie", "Sumter",
  "Suwannee", "Taylor", "Union", "Volusia", "Wakulla", "Walton", "Washington",
];

type SortDirection = "asc" | "desc";

function DistressSaleLogo() {
  return (
    <div className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-[14px] bg-slate-950 text-white shadow-[0_6px_18px_rgba(15,23,42,0.22)] ring-1 ring-slate-900/10">
      <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
        <path d="M9 23.5 24 11l15 12.5" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13.5 21.5V37h21V21.5" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinejoin="round" />
        <path d="m26 18-4 7h5l-4 8" fill="none" stroke="#2dd4bf" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M31.5 13.5 37 19" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <span className="absolute bottom-1.5 right-1.5 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-slate-950" />
    </div>
  );
}

export default function PropertyDashboard() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [nycCoverage, setNycCoverage] = useState<NycAuctionCoverage | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProperty, setSelectedProperty] = useState<Property | null>(null);
  const [selectedState, setSelectedState] = useState("");
  const [selectedCounty, setSelectedCounty] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [upcomingOnly, setUpcomingOnly] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState("scheduled-containing");
  const [highEquityOnly, setHighEquityOnly] = useState(false);
  const [sort, setSort] = useState("gross-equity");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [refreshKey, setRefreshKey] = useState(0);
  const [mobileView, setMobileView] = useState<"map" | "list">("list");
  const [desktopView, setDesktopView] = useState<"dashboard" | "list">("dashboard");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    getPropertyCoverage().then(setCoverage).catch(() => setCoverage([]));
    getNycAuctionCoverage().then(setNycCoverage).catch(() => setNycCoverage(null));
  }, [refreshKey]);

  useEffect(() => {
    let active = true;
    getProperties({
      states: selectedState ? [selectedState] : undefined,
      counties: selectedCounty === "__NYC__" ? NYC_COUNTIES : selectedCounty ? [selectedCounty] : undefined,
      query: searchQuery || undefined,
      status: selectedStatus && selectedStatus !== "scheduled-containing" ? selectedStatus : undefined,
      statusContains: selectedStatus === "scheduled-containing" ? "scheduled" : undefined,
      futureOnly: upcomingOnly,
      minEquity: highEquityOnly ? 150000 : undefined,
      sort,
      sortDirection,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((response) => {
        if (!active) return;
        setProperties(response.items);
        setTotal(response.total);
      })
      .catch(() => {
        if (!active) return;
        setProperties([]);
        setTotal(0);
        setError("Unable to load sheriff-sale properties. Make sure the FastAPI backend and database are available.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [desktopView, highEquityOnly, page, refreshKey, searchQuery, selectedCounty, selectedState, selectedStatus, sort, sortDirection, upcomingOnly]);

  const states = useMemo(() => {
    const values = new Set(coverage.map((item) => item.state));
    if (values.size === 0) ["NJ", "NY", "PA"].forEach((state) => values.add(state));
    return Array.from(values).sort();
  }, [coverage]);

  const counties = useMemo(() => {
    if (selectedState === "FL") {
      const counts = new Map(coverage.filter((item) => item.state === "FL").map((item) => [item.county.toLowerCase(), item.property_count]));
      return FLORIDA_COUNTIES.map((county) => ({ state: "FL", county, property_count: counts.get(county.toLowerCase()) ?? 0 }));
    }
    return coverage
      .filter((item) => !selectedState || item.state === selectedState)
      .sort((left, right) => left.county.localeCompare(right.county));
  }, [coverage, selectedState]);

  const sortedProperties = properties;
  const floridaCountyCounts = useMemo(() => {
    const counts = new Map(
      coverage.filter((item) => item.state === "FL").map((item) => [item.county.toLowerCase(), item.property_count]),
    );
    return FLORIDA_COUNTIES
      .map((county) => ({ county, count: counts.get(county.toLowerCase()) ?? 0 }))
      .filter(({ count }) => count > 0);
  }, [coverage]);

  const selectedStateCountyCounts = useMemo(() => {
    if (!selectedState || selectedState === "FL") return [];
    return coverage
      .filter((item) => item.state === selectedState && item.property_count > 0)
      .map((item) => ({ county: item.county, count: item.property_count }))
      .sort((left, right) => left.county.localeCompare(right.county));
  }, [coverage, selectedState]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const averageEquity = useMemo(() => {
    const values = properties.map((property) => property.gross_equity).filter((value): value is number => value != null);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }, [properties]);
  const mappedCount = properties.filter((property) => property.latitude != null && property.longitude != null).length;

  const chooseProperty = useCallback((property: Property) => setSelectedProperty(property), []);
  const chooseCounty = useCallback((state: string, county: string) => {
    setSelectedState(state);
    setSelectedCounty(county);
    setPage(1);
  }, []);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearchQuery(searchInput.trim());
  }

  function resetFilters() {
    setSelectedState("");
    setSelectedCounty("");
    setSearchInput("");
    setSearchQuery("");
    setUpcomingOnly(false);
    setSelectedStatus("scheduled-containing");
    setHighEquityOnly(false);
    setSort("gross-equity");
    setSortDirection("desc");
    setPage(1);
  }

  async function exportProperties() {
    setExporting(true);
    try {
      const blob = await downloadPropertiesXlsx({
        states: selectedState ? [selectedState] : undefined,
        counties: selectedCounty === "__NYC__" ? NYC_COUNTIES : selectedCounty ? [selectedCounty] : undefined,
        query: searchQuery || undefined,
        status: selectedStatus && selectedStatus !== "scheduled-containing" ? selectedStatus : undefined,
        statusContains: selectedStatus === "scheduled-containing" ? "scheduled" : undefined,
        futureOnly: upcomingOnly,
        minEquity: highEquityOnly ? 150000 : undefined,
        sort,
        sortDirection,
        page,
        pageSize: PAGE_SIZE,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "sheriff-properties.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Unable to export sheriff-sale properties.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-slate-100 text-slate-900">
      <header className="z-30 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <DistressSaleLogo />
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold leading-tight tracking-tight text-slate-950">Sheriff Sale Pro</h1>
              <span className="hidden rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-[0.16em] text-amber-700 ring-1 ring-inset ring-amber-200 md:inline">Distress sales</span>
            </div>
            <p className="hidden text-[11px] font-medium tracking-wide text-slate-500 sm:block">Distressed property intelligence</p>
          </div>
        </div>
        <nav className="flex items-center gap-1 rounded-xl bg-slate-100 p-1" aria-label="Property views">
          <button
            type="button"
            onClick={() => { setLoading(true); setError(null); setDesktopView("dashboard"); }}
            className={`hidden items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold sm:flex ${desktopView === "dashboard" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
            aria-current={desktopView === "dashboard" ? "page" : undefined}
          >
            <MapIcon className="h-4 w-4" />Dashboard
          </button>
          <button
            type="button"
            onClick={() => { setLoading(true); setError(null); setDesktopView("list"); setMobileView("list"); setSort("gross-equity"); setSortDirection("desc"); setPage(1); }}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold ${desktopView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
            aria-current={desktopView === "list" ? "page" : undefined}
          >
            <ListFilter className="h-4 w-4" />List View
          </button>
          <button type="button" onClick={() => setRefreshKey((key) => key + 1)} className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50" aria-label="Refresh properties"><RefreshCw className="h-4 w-4" /></button>
        </nav>
      </header>

      <section className="z-20 shrink-0 border-b border-slate-200 bg-white px-4 py-3 shadow-sm sm:px-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <form onSubmit={submitSearch} className="flex min-w-0 flex-1 items-center rounded-xl border-2 border-slate-200 bg-white px-3 focus-within:border-teal-500">
            <Search className="h-5 w-5 shrink-0 text-slate-400" />
            <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search address, city, ZIP, sale ID, case, plaintiff…" className="min-w-0 flex-1 px-3 py-2.5 text-sm outline-none" />
            {searchInput && <button type="button" onClick={() => { setSearchInput(""); if (searchQuery) { setSearchQuery(""); setPage(1); } }} className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>}
            <button className="ml-1 rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-700">Search</button>
          </form>

          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="State"
              value={selectedState}
              onChange={(event) => { setSelectedState(event.target.value); setSelectedCounty(""); setPage(1); }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-teal-500"
            >
              <option value="">All states</option>
              {states.map((state) => <option key={state} value={state}>{state}</option>)}
            </select>
            <select
              aria-label="County"
              value={selectedCounty}
              onChange={(event) => { setSelectedCounty(event.target.value); setPage(1); }}
              className="max-w-48 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-teal-500"
            >
              <option value="">All counties</option>
              {selectedState === "NY" && <option value="__NYC__">NYC — all five boroughs</option>}
              {counties.map((item) => <option key={`${item.state}-${item.county}`} value={item.county}>{item.county}, {item.state} ({item.property_count})</option>)}
            </select>
            <select
              aria-label="Status"
              value={selectedStatus}
              onChange={(event) => { setSelectedStatus(event.target.value); setPage(1); }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-teal-500"
            >
              <option value="scheduled-containing">Status contains scheduled</option>
              <option value="">All statuses</option>
              <option value="scheduled">Scheduled (confirmed)</option>
              <option value="scheduled_unverified">Scheduled (unverified)</option>
              <option value="adjourned">Adjourned</option>
              <option value="cancelled">Cancelled</option>
              <option value="sold">Sold</option>
              <option value="date_passed_unverified">Date passed (unverified)</option>
            </select>
            <button type="button" onClick={resetFilters} className="flex items-center gap-1.5 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" />Clear</button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
          <Filter className="h-4 w-4 shrink-0 text-slate-400" />
          <button type="button" onClick={() => { setUpcomingOnly((value) => !value); setPage(1); }} className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold ${upcomingOnly ? "border-teal-600 bg-teal-50 text-teal-700" : "border-slate-200 text-slate-600"}`}>Upcoming sale dates</button>
          <button type="button" onClick={() => { setHighEquityOnly((value) => !value); setPage(1); }} className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold ${highEquityOnly ? "border-teal-600 bg-teal-50 text-teal-700" : "border-slate-200 text-slate-600"}`}>$150k+ equity</button>
          {searchQuery && <span className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600">Search: “{searchQuery}”</span>}
        </div>
        {selectedState === "NY" && nycCoverage && (
          <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">NYC court foreclosure and tax-lien auctions:</span>
              {nycCoverage.boroughs.map((item) => (
                <button key={item.county} type="button" onClick={() => { setSelectedCounty(item.county); setPage(1); }}
                  className="rounded-full border border-sky-200 bg-white px-2 py-0.5 hover:border-sky-500">
                  {item.county} {item.upcoming}
                </button>
              ))}
              <button type="button" onClick={() => { setSelectedCounty("__NYC__"); setPage(1); }} className="font-semibold underline">Show all five</button>
            </div>
            <p className="mt-1 text-sky-800">{nycCoverage.coverage_note} <a href={nycCoverage.source_url} target="_blank" rel="noreferrer" className="underline">Source</a>{nycCoverage.last_checked_at ? ` · Checked ${new Date(nycCoverage.last_checked_at).toLocaleDateString()}` : ""}</p>
          </div>
        )}
        {selectedState && (
          <section className="mt-3 rounded-lg border border-teal-200 bg-teal-50/60 px-3 py-3" aria-label={`${selectedState} county record counts`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-bold text-teal-950">{selectedState} county coverage</h2>
              <span className="text-xs text-teal-800">Counties with available listings</span>
            </div>
            <div className="mt-2 grid max-h-48 grid-cols-2 gap-x-4 gap-y-1 overflow-y-auto pr-1 sm:grid-cols-3 lg:grid-cols-5">
              {(selectedState === "FL" ? floridaCountyCounts : selectedStateCountyCounts).map(({ county, count }) => (
                <button key={county} type="button" onClick={() => { setSelectedCounty(county); setPage(1); }} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-white">
                  <span className={count === 0 ? "text-slate-500" : "font-medium text-slate-800"}>{county}</span>
                  <span className={`tabular-nums ${count === 0 ? "text-slate-400" : "font-bold text-teal-700"}`}>{count}</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </section>

      <div className={`shrink-0 border-b border-slate-200 bg-white px-4 py-2 ${desktopView === "list" ? "hidden" : "lg:hidden"}`}>
        <div className="grid grid-cols-2 rounded-lg bg-slate-100 p-1">
          <button onClick={() => setMobileView("map")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "map" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><MapIcon className="h-4 w-4" />Map</button>
          <button onClick={() => setMobileView("list")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><ListFilter className="h-4 w-4" />List</button>
        </div>
      </div>

      <div className={`grid min-h-0 flex-1 overflow-hidden ${desktopView === "dashboard" ? "lg:grid-cols-2" : "grid-cols-1"}`}>
        <div className={`${desktopView === "list" ? "hidden" : mobileView === "map" ? "block h-full" : "hidden"} min-h-0 overflow-hidden border-r border-slate-200 lg:h-auto ${desktopView === "dashboard" ? "lg:block" : "lg:hidden"}`}>
          {desktopView === "dashboard" && (
            <PropertyMap properties={properties} selectedPropertyId={selectedProperty?.property_id} onPropertyClick={chooseProperty} onCountySelect={chooseCounty} visibilityKey={mobileView} />
          )}
        </div>

        <section className={`${desktopView === "list" || mobileView === "list" ? "flex" : "hidden"} min-h-0 flex-col overflow-hidden bg-slate-50 lg:flex`}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
            <div>
              <h2 className="font-bold text-slate-950">{loading ? "Loading properties…" : `${total.toLocaleString()} properties found`}</h2>
              <p className="text-xs text-slate-500">{mappedCount} mapped on this page{averageEquity != null ? ` · ${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(averageEquity)} avg. equity` : ""}</p>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-500">
              <SlidersHorizontal className="h-4 w-4" />
              <select value={["sale-date", "estimated-market-value", "gross-equity", "address"].includes(sort) ? sort : ""} onChange={(event) => { const next = event.target.value; setSort(next); setSortDirection(next === "sale-date" || next === "address" ? "asc" : "desc"); setPage(1); }} className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700">
                {!(["sale-date", "estimated-market-value", "gross-equity", "address"].includes(sort)) && <option value="">Custom column</option>}
                <option value="sale-date">Sale date</option>
                <option value="estimated-market-value">Highest value</option>
                <option value="gross-equity">Highest equity</option>
                <option value="address">Address</option>
              </select>
            </label>
            {desktopView === "list" && <button type="button" onClick={exportProperties} disabled={exporting || loading} className="flex items-center gap-2 rounded-lg border border-teal-600 px-3 py-2 text-sm font-semibold text-teal-700 hover:bg-teal-50 disabled:cursor-wait disabled:opacity-50"><Download className="h-4 w-4" />{exporting ? "Preparing Excel…" : "Download Excel"}</button>}
          </div>

          {error ? (
            <div className="m-4 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">{error}</div>
          ) : loading ? (
            <div className="grid gap-4 overflow-hidden p-4">
              {[1, 2, 3].map((item) => <div key={item} className="h-48 animate-pulse rounded-xl bg-slate-200" />)}
            </div>
          ) : sortedProperties.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-8 text-center">
              <div><ListFilter className="mx-auto h-10 w-10 text-slate-300" /><h3 className="mt-3 font-semibold text-slate-900">No matching properties</h3><p className="mt-1 text-sm text-slate-500">Try clearing a filter or searching a broader location.</p></div>
            </div>
          ) : desktopView === "list" ? (
            <PropertyTable properties={sortedProperties} onPropertyClick={chooseProperty} sort={sort} sortDirection={sortDirection} onSort={(column) => { setSortDirection(sort === column && sortDirection === "asc" ? "desc" : "asc"); setSort(column); setPage(1); }} />
          ) : (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
              {sortedProperties.map((property) => <PropertyCard key={property.sheriff_sale_id} property={property} selected={selectedProperty?.sheriff_sale_id === property.sheriff_sale_id} onClick={() => chooseProperty(property)} />)}
            </div>
          )}

          <footer className="flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-4 py-3">
            <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40"><ChevronLeft className="h-4 w-4" />Previous</button>
            <span className="text-xs text-slate-500">Page <strong className="text-slate-800">{page}</strong> of {totalPages}</span>
            <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40">Next<ChevronRight className="h-4 w-4" /></button>
          </footer>
        </section>
      </div>

      {selectedProperty && <PropertyDetailModal key={selectedProperty.property_id} property={selectedProperty} onClose={() => setSelectedProperty(null)} />}
    </main>
  );
}
