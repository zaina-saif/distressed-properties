"use client";

import {
  ChevronLeft,
  ChevronRight,
  Filter,
  Gavel,
  ListFilter,
  Map as MapIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { PropertyCard } from "@/components/property-card";
import { PropertyDetailModal } from "@/components/property-detail-modal";
import { PropertyMap } from "@/components/property-map";
import { getProperties, getPropertyCoverage } from "@/services/properties";
import type { Property, PropertyCoverageItem } from "@/types/property";

const PAGE_SIZE = 24;

type SortOption = "sale-date" | "value-desc" | "equity-desc" | "address";

export default function PropertyDashboard() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProperty, setSelectedProperty] = useState<Property | null>(null);
  const [selectedState, setSelectedState] = useState("");
  const [selectedCounty, setSelectedCounty] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [upcomingOnly, setUpcomingOnly] = useState(true);
  const [highEquityOnly, setHighEquityOnly] = useState(false);
  const [sort, setSort] = useState<SortOption>("sale-date");
  const [refreshKey, setRefreshKey] = useState(0);
  const [mobileView, setMobileView] = useState<"map" | "list">("list");

  useEffect(() => {
    getPropertyCoverage().then(setCoverage).catch(() => setCoverage([]));
  }, []);

  useEffect(() => {
    let active = true;
    getProperties({
      states: selectedState ? [selectedState] : undefined,
      counties: selectedCounty ? [selectedCounty] : undefined,
      query: searchQuery || undefined,
      status: upcomingOnly ? "scheduled" : undefined,
      futureOnly: upcomingOnly,
      minEquity: highEquityOnly ? 150000 : undefined,
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
  }, [highEquityOnly, page, refreshKey, searchQuery, selectedCounty, selectedState, upcomingOnly]);

  const states = useMemo(() => {
    const values = new Set(coverage.map((item) => item.state));
    if (values.size === 0) ["NJ", "NY", "PA"].forEach((state) => values.add(state));
    return Array.from(values).sort();
  }, [coverage]);

  const counties = useMemo(() => coverage
    .filter((item) => !selectedState || item.state === selectedState)
    .sort((left, right) => left.county.localeCompare(right.county)), [coverage, selectedState]);

  const sortedProperties = useMemo(() => [...properties].sort((left, right) => {
    if (sort === "value-desc") return (right.market_value ?? -Infinity) - (left.market_value ?? -Infinity);
    if (sort === "equity-desc") return (right.gross_equity ?? -Infinity) - (left.gross_equity ?? -Infinity);
    if (sort === "address") return left.normalized_address.localeCompare(right.normalized_address);
    const leftDate = left.current_sale_date ? new Date(left.current_sale_date).getTime() : Infinity;
    const rightDate = right.current_sale_date ? new Date(right.current_sale_date).getTime() : Infinity;
    return leftDate - rightDate;
  }), [properties, sort]);

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
    setUpcomingOnly(true);
    setHighEquityOnly(false);
    setPage(1);
  }

  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-slate-100 text-slate-900">
      <header className="z-30 flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-600 text-white shadow-sm"><Gavel className="h-5 w-5" /></div>
          <div>
            <h1 className="font-bold leading-tight text-slate-950">Sheriff Sale Pro</h1>
            <p className="hidden text-xs text-slate-500 sm:block">Distressed property intelligence</p>
          </div>
        </div>
        <nav className="flex items-center gap-2">
          <span className="hidden rounded-lg bg-teal-50 px-3 py-2 text-sm font-semibold text-teal-700 sm:inline">Dashboard</span>
          <button type="button" onClick={() => setRefreshKey((key) => key + 1)} className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50" aria-label="Refresh properties"><RefreshCw className="h-4 w-4" /></button>
        </nav>
      </header>

      <section className="z-20 shrink-0 border-b border-slate-200 bg-white px-4 py-3 shadow-sm sm:px-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <form onSubmit={submitSearch} className="flex min-w-0 flex-1 items-center rounded-xl border-2 border-slate-200 bg-white px-3 focus-within:border-teal-500">
            <Search className="h-5 w-5 shrink-0 text-slate-400" />
            <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search address, city, ZIP, sheriff number, case, plaintiff…" className="min-w-0 flex-1 px-3 py-2.5 text-sm outline-none" />
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
              {counties.map((item) => <option key={`${item.state}-${item.county}`} value={item.county}>{item.county}, {item.state} ({item.property_count})</option>)}
            </select>
            <button type="button" onClick={resetFilters} className="flex items-center gap-1.5 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" />Clear</button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
          <Filter className="h-4 w-4 shrink-0 text-slate-400" />
          <button type="button" onClick={() => { setUpcomingOnly((value) => !value); setPage(1); }} className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold ${upcomingOnly ? "border-teal-600 bg-teal-50 text-teal-700" : "border-slate-200 text-slate-600"}`}>Upcoming scheduled</button>
          <button type="button" onClick={() => { setHighEquityOnly((value) => !value); setPage(1); }} className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold ${highEquityOnly ? "border-teal-600 bg-teal-50 text-teal-700" : "border-slate-200 text-slate-600"}`}>$150k+ equity</button>
          {searchQuery && <span className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600">Search: “{searchQuery}”</span>}
        </div>
      </section>

      <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
        <div className="grid grid-cols-2 rounded-lg bg-slate-100 p-1">
          <button onClick={() => setMobileView("map")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "map" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><MapIcon className="h-4 w-4" />Map</button>
          <button onClick={() => setMobileView("list")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><ListFilter className="h-4 w-4" />List</button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 overflow-hidden lg:grid-cols-2">
        <div className={`${mobileView === "map" ? "block h-full" : "hidden"} min-h-0 overflow-hidden border-r border-slate-200 lg:block lg:h-auto`}>
          <PropertyMap properties={properties} selectedPropertyId={selectedProperty?.property_id} onPropertyClick={chooseProperty} onCountySelect={chooseCounty} />
        </div>

        <section className={`${mobileView === "list" ? "flex" : "hidden"} min-h-0 flex-col overflow-hidden bg-slate-50 lg:flex`}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
            <div>
              <h2 className="font-bold text-slate-950">{loading ? "Loading properties…" : `${total.toLocaleString()} properties found`}</h2>
              <p className="text-xs text-slate-500">{mappedCount} mapped on this page{averageEquity != null ? ` · ${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(averageEquity)} avg. equity` : ""}</p>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-500">
              <SlidersHorizontal className="h-4 w-4" />
              <select value={sort} onChange={(event) => setSort(event.target.value as SortOption)} className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700">
                <option value="sale-date">Sale date</option>
                <option value="value-desc">Highest value</option>
                <option value="equity-desc">Highest equity</option>
                <option value="address">Address</option>
              </select>
            </label>
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
