"use client";

import {
  ChevronLeft,
  ChevronRight,
  ListFilter,
  Map as MapIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Download,
  X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { DistressedPropertiesBrand } from "@/components/brand-logo";
import { PropertyCard } from "@/components/property-card";
import { PropertyDetailModal } from "@/components/property-detail-modal";
import { PropertyFocusPanel } from "@/components/property-focus-panel";
import { PropertyLienSummaryModal } from "@/components/property-lien-summary-modal";
import { PropertyComplaintsModal } from "@/components/property-complaints-modal";
import { PropertyStatusHistoryModal } from "@/components/property-status-history-modal";
import { SaleProbabilityReasonModal } from "@/components/sale-probability-reason-modal";
import { SheriffSalePageModal } from "@/components/sheriff-sale-page-modal";
import { PropertyMap } from "@/components/property-map";
import { PropertyTable } from "@/components/property-table";
import { downloadPropertiesXlsx, getProperties, getPropertyCoverage } from "@/services/properties";
import type { Property, PropertyCoverageItem, SpotlightSummary } from "@/types/property";

const PAGE_SIZE = 24;
// States with sheriff-sale listings; every request is pinned to the selected one.
const STATES: { code: string; name: string; view: [number, number, number] }[] = [
  { code: "NJ", name: "New Jersey", view: [40.1, -74.6, 8] },
  { code: "PA", name: "Pennsylvania", view: [40.9, -77.6, 7] },
];
// The dashboard only lists properties whose sale status contains "scheduled".
const SCHEDULED = "scheduled";

type SortDirection = "asc" | "desc";

function wholeDollars(value: number | null | undefined): string {
  return value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

export default function PropertyDashboard({
  initialState = "NJ",
  initialCounty = "",
  initialQuery = "",
  initialSpotlight = false,
}: {
  initialState?: string;
  initialCounty?: string;
  initialQuery?: string;
  initialSpotlight?: boolean;
}) {
  const [properties, setProperties] = useState<Property[]>([]);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProperty, setSelectedProperty] = useState<Property | null>(null);
  // Picked on the map; shown in the right panel instead of the list.
  const [focusedProperty, setFocusedProperty] = useState<Property | null>(null);
  const [salePageProperty, setSalePageProperty] = useState<Property | null>(null);
  const [spotlight, setSpotlight] = useState(initialSpotlight);
  const [spotlightSummary, setSpotlightSummary] = useState<SpotlightSummary | null>(null);
  const [selectedHistoryProperty, setSelectedHistoryProperty] = useState<Property | null>(null);
  const [selectedLienSummaryProperty, setSelectedLienSummaryProperty] = useState<Property | null>(null);
  const [selectedComplaintsProperty, setSelectedComplaintsProperty] = useState<Property | null>(null);
  const [selectedProbabilityReasonProperty, setSelectedProbabilityReasonProperty] = useState<Property | null>(null);
  const [selectedState, setSelectedState] = useState(
    STATES.some((item) => item.code === initialState.toUpperCase()) ? initialState.toUpperCase() : "NJ",
  );
  const stateInfo = STATES.find((item) => item.code === selectedState) ?? STATES[0];
  const [selectedCounty, setSelectedCounty] = useState(initialCounty);
  const [searchInput, setSearchInput] = useState(initialQuery);
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [sort, setSort] = useState("gross-equity");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [refreshKey, setRefreshKey] = useState(0);
  const [mobileView, setMobileView] = useState<"map" | "list">("list");
  const [desktopView, setDesktopView] = useState<"dashboard" | "list">("dashboard");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    getPropertyCoverage(SCHEDULED).then(setCoverage).catch(() => setCoverage([]));
  }, [refreshKey]);

  // Always-visible spotlight totals: one small request, independent of the list view.
  useEffect(() => {
    let active = true;
    getProperties({
      states: [selectedState],
      counties: selectedCounty ? [selectedCounty] : undefined,
      investorSpotlight: true,
      sort: "investor-spotlight",
      sortDirection: "desc",
      page: 1,
      pageSize: 1,
    })
      .then((response) => { if (active) setSpotlightSummary(response.spotlight_summary ?? null); })
      .catch(() => { if (active) setSpotlightSummary(null); });
    return () => { active = false; };
  }, [refreshKey, selectedCounty, selectedState]);

  useEffect(() => {
    let active = true;
    getProperties({
      states: [selectedState],
      counties: selectedCounty ? [selectedCounty] : undefined,
      query: searchQuery || undefined,
      statusContains: SCHEDULED,
      investorSpotlight: spotlight || undefined,
      sort: spotlight ? "investor-spotlight" : sort,
      sortDirection: spotlight ? "desc" : sortDirection,
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
  }, [desktopView, page, refreshKey, searchQuery, selectedCounty, selectedState, sort, sortDirection, spotlight]);

  const counties = useMemo(
    () => coverage
      .filter((item) => item.state === selectedState)
      .sort((left, right) => left.county.localeCompare(right.county)),
    [coverage, selectedState],
  );

  const sortedProperties = properties;
  const countyCounts = useMemo(
    () => counties
      .filter((item) => item.property_count > 0)
      .map((item) => ({ county: item.county, count: item.property_count })),
    [counties],
  );

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const averageEquity = useMemo(() => {
    const values = properties.map((property) => property.gross_equity).filter((value): value is number => value != null);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }, [properties]);
  const mappedCount = properties.filter((property) => property.latitude != null && property.longitude != null).length;

  const chooseProperty = useCallback((property: Property) => setSelectedProperty(property), []);
  const focusProperty = useCallback((property: Property) => {
    setFocusedProperty(property);
    setMobileView("list");
  }, []);
  const chooseCounty = useCallback((state: string, county: string) => {
    if (state !== selectedState) return;
    setSelectedCounty(county);
    setPage(1);
  }, [selectedState]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearchQuery(searchInput.trim());
  }

  function resetFilters() {
    setFocusedProperty(null);
    setSpotlight(false);
    setSelectedCounty("");
    setSearchInput("");
    setSearchQuery("");
    setSort("gross-equity");
    setSortDirection("desc");
    setPage(1);
  }

  async function exportProperties() {
    setExporting(true);
    try {
      const blob = await downloadPropertiesXlsx({
        states: [selectedState],
        counties: selectedCounty ? [selectedCounty] : undefined,
        query: searchQuery || undefined,
        statusContains: SCHEDULED,
        investorSpotlight: spotlight || undefined,
        sort: spotlight ? "investor-spotlight" : sort,
        sortDirection: spotlight ? "desc" : sortDirection,
        page,
        pageSize: PAGE_SIZE,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${selectedState.toLowerCase()}-sheriff-properties.xlsx`;
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
      <header className="z-30 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3" aria-label="Distressed Properties Pro home">
            <DistressedPropertiesBrand />
          </Link>
        </div>

        <button
          type="button"
          onClick={() => { setSpotlight((value) => !value); setFocusedProperty(null); setPage(1); }}
          aria-pressed={spotlight}
          className={`flex flex-col rounded-xl px-3 py-1.5 text-left ring-1 ring-inset transition ${spotlight ? "bg-amber-500 text-white ring-amber-500 shadow-sm" : "bg-amber-50 text-amber-900 ring-amber-200 hover:bg-amber-100"}`}
        >
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 shrink-0" />
            <span className="leading-tight">
              <span className="block text-sm font-bold">Investor Spotlight</span>
              <span className={`block text-[10px] font-medium ${spotlight ? "text-amber-50" : "text-amber-700"}`}>(Highest equity / High probability to auction)</span>
            </span>
          </span>
        </button>

        <div className="ml-auto flex flex-col items-end gap-1.5">
          <nav className="flex items-center gap-1 rounded-xl bg-slate-100 p-1" aria-label="Property views">
            <button
              type="button"
              onClick={() => { setLoading(true); setError(null); setDesktopView("dashboard"); }}
              className={`hidden items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold sm:flex ${desktopView === "dashboard" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-current={desktopView === "dashboard" ? "page" : undefined}
            >
              <MapIcon className="h-4 w-4" />Dashboard
            </button>
            <button
              type="button"
              onClick={() => { setLoading(true); setError(null); setDesktopView("list"); setMobileView("list"); setSort("gross-equity"); setSortDirection("desc"); setPage(1); }}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold ${desktopView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-current={desktopView === "list" ? "page" : undefined}
            >
              <ListFilter className="h-4 w-4" />List View
            </button>
            <button type="button" onClick={() => setRefreshKey((key) => key + 1)} className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50" aria-label="Refresh properties"><RefreshCw className="h-4 w-4" /></button>
          </nav>
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <form onSubmit={submitSearch} className="flex w-full min-w-0 items-center rounded-md border border-slate-300 bg-white pl-2 focus-within:border-teal-500 sm:w-64">
              <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search address, city, ZIP, case, plaintiff…" className="min-w-0 flex-1 px-1.5 py-1 text-xs outline-none" />
              {searchInput && <button type="button" onClick={() => { setSearchInput(""); if (searchQuery) { setSearchQuery(""); setPage(1); } }} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Clear search text"><X className="h-3.5 w-3.5" /></button>}
              <button className="rounded-r-md bg-teal-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-teal-700">Search</button>
            </form>
            <select
              aria-label="State"
              value={selectedState}
              onChange={(event) => { setSelectedState(event.target.value); setSelectedCounty(""); setFocusedProperty(null); setPage(1); }}
              className="w-32 rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs outline-none focus:border-teal-500"
            >
              {STATES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
            </select>
            <select
              aria-label="County"
              value={selectedCounty}
              onChange={(event) => { setSelectedCounty(event.target.value); setPage(1); }}
              className="w-32 rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs outline-none focus:border-teal-500"
            >
              <option value="">All counties</option>
              {counties.map((item) => <option key={item.county} value={item.county}>{item.county} ({item.property_count})</option>)}
            </select>
            <button type="button" onClick={resetFilters} className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100"><X className="h-3 w-3" />Clear</button>
          </div>
  
        </div>
      </header>

      <section className="z-20 shrink-0 space-y-2 border-b border-slate-200 bg-white px-4 py-2 shadow-sm sm:px-6">
        {spotlight && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            <Sparkles className="h-3.5 w-3.5" />
            <span className="font-semibold">Investor Spotlight:</span>
            {spotlightSummary && (
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="rounded-full bg-white px-2 py-0.5 font-bold ring-1 ring-amber-200">{spotlightSummary.count.toLocaleString()} properties{selectedCounty ? ` in ${selectedCounty}` : ""}</span>
                <span className="rounded-full bg-white px-2 py-0.5 ring-1 ring-amber-200">Total gross equity <span className="font-bold">{wholeDollars(spotlightSummary.total_gross_equity)}</span></span>
                <span className="rounded-full bg-white px-2 py-0.5 ring-1 ring-amber-200">Avg. gross equity <span className="font-bold">{wholeDollars(spotlightSummary.average_gross_equity)}</span></span>
              </span>
            )}
            <span className="text-amber-800">Upcoming scheduled sales ranked by expected equity: gross equity (Zestimate minus minimum bid) × probability to auction at the next sale date.</span>
            <button type="button" onClick={() => setSpotlight(false)} className="ml-auto font-semibold underline">Exit spotlight</button>
          </div>
        )}
        {searchQuery && <span className="inline-block whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">Search: “{searchQuery}”</span>}
        {countyCounts.length > 0 && (
          <section className="w-full rounded-lg border border-teal-200 bg-teal-50/60 px-3 py-2" aria-label={`${selectedState} county record counts`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xs font-bold text-teal-950">{selectedState} county coverage</h2>
              <span className="text-xs text-teal-800">Counties with available listings · click to filter</span>
            </div>
            <div className="mt-1 flex w-full flex-wrap content-start text-xs leading-6">
              {countyCounts.map(({ county, count }, index, items) => (
                <span key={county} className="flex shrink-0 items-center">
                  <button type="button" onClick={() => { setSelectedCounty(county); setPage(1); }} className={`flex items-center gap-1 rounded px-2 py-0.5 text-left hover:bg-white ${selectedCounty === county ? "bg-white ring-1 ring-teal-300" : ""}`}>
                    <span className={count === 0 ? "font-bold text-slate-500" : "font-bold text-slate-900"}>{county}</span>
                    <span className={`tabular-nums ${count === 0 ? "text-slate-400" : "font-bold text-teal-700"}`}>{count}</span>
                  </button>
                  {index < items.length - 1 && <span className="text-slate-300" aria-hidden="true">|</span>}
                </span>
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

      <div className={`grid min-h-0 flex-1 overflow-hidden ${desktopView === "dashboard" ? "lg:grid-cols-[minmax(0,2fr)_minmax(22rem,1fr)]" : "grid-cols-1"}`}>
        <div className={`${desktopView === "list" ? "hidden" : mobileView === "map" ? "block h-full" : "hidden"} min-h-0 overflow-hidden border-r border-slate-200 lg:h-auto ${desktopView === "dashboard" ? "lg:block" : "lg:hidden"}`}>
          {desktopView === "dashboard" && (
            <PropertyMap properties={properties} selectedPropertyId={focusedProperty?.property_id ?? selectedProperty?.property_id} onPropertyClick={focusProperty} onCountySelect={chooseCounty} visibilityKey={mobileView} defaultView={stateInfo.view} />
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

          {focusedProperty && desktopView === "dashboard" ? (
            <PropertyFocusPanel property={focusedProperty} onBack={() => setFocusedProperty(null)} onOpenDetails={() => setSelectedProperty(focusedProperty)} onSalePageClick={() => setSalePageProperty(focusedProperty)} onProbabilityReasonClick={() => setSelectedProbabilityReasonProperty(focusedProperty)} />
          ) : error ? (
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
            <PropertyTable properties={sortedProperties} onPropertyClick={chooseProperty} onLienSummaryClick={setSelectedLienSummaryProperty} onAdditionalDetailsClick={setSelectedComplaintsProperty} onProbabilityReasonClick={setSelectedProbabilityReasonProperty} onStatusHistoryClick={setSelectedHistoryProperty} onSalePageClick={setSalePageProperty} sort={sort} sortDirection={sortDirection} onSort={(column) => { setSortDirection(sort === column && sortDirection === "asc" ? "desc" : "asc"); setSort(column); setPage(1); }} />
          ) : (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
              {sortedProperties.map((property) => <PropertyCard key={property.sheriff_sale_id} property={property} selected={selectedProperty?.sheriff_sale_id === property.sheriff_sale_id} onClick={() => focusProperty(property)} />)}
            </div>
          )}

          <footer className="flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-4 py-3">
            <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40"><ChevronLeft className="h-4 w-4" />Previous</button>
            <span className="text-xs text-slate-500">Showing <strong className="text-slate-800">{total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)}</strong> of <strong className="text-slate-800">{total.toLocaleString()}</strong> rows · Page <strong className="text-slate-800">{page}</strong> of {totalPages}</span>
            <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40">Next<ChevronRight className="h-4 w-4" /></button>
          </footer>
        </section>
      </div>

      {selectedProperty && <PropertyDetailModal key={selectedProperty.property_id} property={selectedProperty} onClose={() => setSelectedProperty(null)} onSalePageClick={setSalePageProperty} />}
      {salePageProperty && <SheriffSalePageModal key={salePageProperty.sheriff_sale_id} property={salePageProperty} onClose={() => setSalePageProperty(null)} />}
      {selectedLienSummaryProperty && <PropertyLienSummaryModal key={selectedLienSummaryProperty.property_id} property={selectedLienSummaryProperty} onClose={() => setSelectedLienSummaryProperty(null)} />}
      {selectedComplaintsProperty && <PropertyComplaintsModal key={selectedComplaintsProperty.property_id} property={selectedComplaintsProperty} onClose={() => setSelectedComplaintsProperty(null)} />}
      {selectedHistoryProperty && <PropertyStatusHistoryModal key={selectedHistoryProperty.property_id} property={selectedHistoryProperty} onClose={() => setSelectedHistoryProperty(null)} />}
      {selectedProbabilityReasonProperty && <SaleProbabilityReasonModal key={selectedProbabilityReasonProperty.property_id} property={selectedProbabilityReasonProperty} onClose={() => setSelectedProbabilityReasonProperty(null)} />}
    </main>
  );
}
