"use client";

import {
  CalendarDays,
  ChartColumn,
  ChevronLeft,
  ChevronRight,
  Info,
  ListFilter,
  LogOut,
  Map as MapIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Download,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SheriffSaleHunterBrand } from "@/components/brand-logo";
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
import { SaleAnalyticsView } from "@/components/sale-analytics";
import { getProfile } from "@/lib/profile";
import { formatSaleDate, STATES } from "@/lib/states";

const ALL_STATES = "ALL";
const ALL_STATES_INFO = { code: ALL_STATES, name: "All states", view: [39.5, -96, 4] as [number, number, number] };
import { downloadPropertiesXlsx, getMapPoints, getProperties, getPropertyCoverage, type MapPoint } from "@/services/properties";
import type { Property, PropertyCoverageItem, SpotlightSummary } from "@/types/property";

const PAGE_SIZE = 24;
// The dashboard only lists properties whose sale status contains "scheduled".
const SCHEDULED = "scheduled";

type SortDirection = "asc" | "desc";

// Texas sale lists go up a few weeks before each first-Tuesday sale. Until the
// next list is posted, Texas shows its most recent sale, labelled as already held.
const RECENT_SALE = "sold_or_cancelled";

function nextFirstTuesday(from: Date): Date {
  for (let offset = 0; offset < 3; offset += 1) {
    const first = new Date(from.getFullYear(), from.getMonth() + offset, 1);
    const tuesday = new Date(first.getFullYear(), first.getMonth(), 1 + ((9 - first.getDay()) % 7));
    if (tuesday >= new Date(from.getFullYear(), from.getMonth(), from.getDate())) return tuesday;
  }
  return from;
}

const longDate = (value: Date) => value.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });

function wholeDollars(value: number | null | undefined): string {
  return value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

export default function PropertyDashboard({
  initialState = "NJ",
  initialCounty = "",
  initialQuery = "",
  initialSpotlight = false,
  initialView = "dashboard",
}: {
  initialState?: string;
  initialCounty?: string;
  initialQuery?: string;
  initialSpotlight?: boolean;
  initialView?: "dashboard" | "list" | "analytics";
}) {
  const [properties, setProperties] = useState<Property[]>([]);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [coverageLoaded, setCoverageLoaded] = useState(false);
  const [recentCoverage, setRecentCoverage] = useState<PropertyCoverageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [nextSaleDate, setNextSaleDate] = useState<string | null>(null);
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
  const { account, signOut } = useAccount();
  // Optional profile prompt: shown until a profile exists or the user dismisses it.
  const [profilePrompt, setProfilePrompt] = useState(false);
  useEffect(() => {
    let dismissed = false;
    try { dismissed = window.localStorage.getItem("profile-prompt-dismissed") === "1"; } catch { /* storage unavailable */ }
    if (dismissed) return;
    let active = true;
    getProfile().then((profile) => { if (active) setProfilePrompt(!profile.exists); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  const dismissProfilePrompt = () => {
    setProfilePrompt(false);
    try { window.localStorage.setItem("profile-prompt-dismissed", "1"); } catch { /* storage unavailable */ }
  };
  // Free covers one county and Starter one state; the API enforces the same limits.
  const allowedStates = useMemo(
    () => account && !account.is_developer && account.plan !== "pro" && account.coverage_state
      ? STATES.filter((item) => item.code === account.coverage_state)
      : STATES,
    [account],
  );
  const lockedCounty = account && !account.is_developer && account.plan === "free" ? account.coverage_county : null;
  // "All states" for plans that cover more than one state; counties repeat across
  // states (Lake County is in OH, IL and FL), so it has no county filter.
  const canShowAll = allowedStates.length > 1;
  const [selectedState, setSelectedState] = useState(
    canShowAll && initialState.toUpperCase() === ALL_STATES ? ALL_STATES
      : allowedStates.some((item) => item.code === initialState.toUpperCase()) ? initialState.toUpperCase() : allowedStates[0]?.code ?? "NJ",
  );
  const allStates = selectedState === ALL_STATES;
  const stateFilter = useMemo(() => (allStates ? undefined : [selectedState]), [allStates, selectedState]);
  const stateInfo = allStates ? ALL_STATES_INFO : STATES.find((item) => item.code === selectedState) ?? STATES[0];
  const [selectedCounty, setSelectedCounty] = useState(lockedCounty ?? initialCounty);
  const [searchInput, setSearchInput] = useState(initialQuery);
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [sort, setSort] = useState("gross-equity");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [refreshKey, setRefreshKey] = useState(0);
  const [mobileView, setMobileView] = useState<"map" | "list">("list");
  const [desktopView, setDesktopView] = useState<"dashboard" | "list" | "analytics">(initialView);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    getPropertyCoverage(SCHEDULED).then(setCoverage).catch(() => setCoverage([])).finally(() => setCoverageLoaded(true));
  }, [refreshKey]);
  const showRecentSale = selectedState === "TX" && coverageLoaded
    && !coverage.some((item) => item.state === "TX" && item.property_count > 0);
  const statusFilter = showRecentSale ? RECENT_SALE : SCHEDULED;
  useEffect(() => {
    if (showRecentSale) getPropertyCoverage(RECENT_SALE).then(setRecentCoverage).catch(() => setRecentCoverage([]));
  }, [refreshKey, showRecentSale]);

  // Always-visible spotlight totals: one small request, independent of the list view.
  useEffect(() => {
    let active = true;
    getProperties({
      states: stateFilter,
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
  }, [refreshKey, selectedCounty, stateFilter]);

  useEffect(() => {
    // Wait for coverage so Texas does not flash "no properties" before its fallback.
    if (selectedState === "TX" && !coverageLoaded) return;
    let active = true;
    getProperties({
      states: stateFilter,
      counties: selectedCounty ? [selectedCounty] : undefined,
      query: searchQuery || undefined,
      statusContains: statusFilter,
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
        setNextSaleDate(response.next_sale_date ?? null);
      })
      .catch(() => {
        if (!active) return;
        setProperties([]);
        setTotal(0);
        setNextSaleDate(null);
        setError("Unable to load sheriff-sale properties. Make sure the FastAPI backend and database are available.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [coverageLoaded, desktopView, page, refreshKey, searchQuery, selectedCounty, selectedState, sort, sortDirection, spotlight, stateFilter, statusFilter]);

  // Every matching property goes on the map, not just the list's current page.
  const [mapPoints, setMapPoints] = useState<{ total: number; points: MapPoint[] }>({ total: 0, points: [] });
  useEffect(() => {
    if (selectedState === "TX" && !coverageLoaded) return;
    let active = true;
    getMapPoints({
      states: stateFilter,
      counties: selectedCounty ? [selectedCounty] : undefined,
      query: searchQuery || undefined,
      statusContains: statusFilter,
      investorSpotlight: spotlight || undefined,
    })
      .then((response) => { if (active) setMapPoints(response); })
      .catch(() => { if (active) setMapPoints({ total: 0, points: [] }); });
    return () => { active = false; };
  }, [coverageLoaded, refreshKey, searchQuery, selectedCounty, selectedState, spotlight, stateFilter, statusFilter]);

  const counties = useMemo(
    () => (showRecentSale ? recentCoverage : coverage)
      .filter((item) => item.state === selectedState && (!lockedCounty || item.county === lockedCounty))
      .sort((left, right) => left.county.localeCompare(right.county)),
    [coverage, lockedCounty, recentCoverage, selectedState, showRecentSale],
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
  const recentSaleDate = useMemo(() => {
    const dates = properties.map((property) => property.current_sale_date).filter((value): value is string => Boolean(value)).sort();
    return dates.length ? new Date(dates[dates.length - 1]) : null;
  }, [properties]);

  const chooseProperty = useCallback((property: Property) => setSelectedProperty(property), []);
  const focusProperty = useCallback((property: Property) => {
    setFocusedProperty(property);
    setMobileView("list");
    // On phones the page scrolls, so bring the opened listing into view.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      requestAnimationFrame(() => document.getElementById("property-results")?.scrollIntoView());
    }
  }, []);
  // A point off the list's current page loads its listing before it opens.
  const openMapPoint = useCallback((point: MapPoint) => {
    const loaded = properties.find((property) => property.sheriff_sale_id === point.sheriff_sale_id);
    if (loaded) {
      focusProperty(loaded);
      return;
    }
    getProperties({ saleIds: [point.sheriff_sale_id], page: 1, pageSize: 1 })
      .then((response) => { if (response.items[0]) focusProperty(response.items[0]); })
      .catch(() => setError("Unable to open that property."));
  }, [focusProperty, properties]);
  const chooseCounty = useCallback((state: string, county: string) => {
    if (lockedCounty && county !== lockedCounty) return;
    // From "All states", a county on the map opens its state.
    if (state !== selectedState) {
      if (selectedState !== ALL_STATES || !allowedStates.some((item) => item.code === state)) return;
      setSelectedState(state);
    }
    setSelectedCounty(county);
    setPage(1);
  }, [allowedStates, lockedCounty, selectedState]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearchQuery(searchInput.trim());
  }

  function resetFilters() {
    setFocusedProperty(null);
    setSpotlight(false);
    setSelectedCounty(lockedCounty ?? "");
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
        states: stateFilter,
        counties: selectedCounty ? [selectedCounty] : undefined,
        query: searchQuery || undefined,
        statusContains: statusFilter,
        investorSpotlight: spotlight || undefined,
        sort: spotlight ? "investor-spotlight" : sort,
        sortDirection: spotlight ? "desc" : sortDirection,
        page,
        pageSize: PAGE_SIZE,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${allStates ? "all-states" : selectedState.toLowerCase()}-sheriff-properties.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Unable to export sheriff-sale properties.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col bg-slate-100 text-slate-900 lg:h-screen lg:min-h-0 lg:overflow-hidden">
      <header className="z-30 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-2.5 sm:px-6">
        <div className="flex w-full items-center gap-3 sm:w-auto">
          <Link href="/" className="flex items-center gap-3" aria-label="Sheriff Sale Hunter home">
            <SheriffSaleHunterBrand />
          </Link>
          <div className="ml-auto flex items-center gap-1 sm:hidden">
            <Link href="/account" className="rounded-md p-2 text-slate-600 hover:bg-slate-100" aria-label={account?.is_developer ? "Developer account" : "Account"}><UserRound className="h-5 w-5" /></Link>
            <button type="button" onClick={async () => { await signOut(); window.location.assign("/"); }} className="rounded-md p-2 text-slate-500 hover:bg-slate-100" aria-label="Sign out"><LogOut className="h-5 w-5" /></button>
          </div>
        </div>

        <button
          type="button"
          onClick={() => { setSpotlight((value) => !value); setFocusedProperty(null); setPage(1); }}
          aria-pressed={spotlight}
          className={`flex flex-col rounded-xl px-3 py-2 sm:py-1.5 text-left ring-1 ring-inset transition ${spotlight ? "bg-amber-500 text-white ring-amber-500 shadow-sm" : "bg-amber-50 text-amber-900 ring-amber-200 hover:bg-amber-100"}`}
        >
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 shrink-0" />
            <span className="leading-tight">
              <span className="block text-sm font-bold"><span className="hidden sm:inline">Investor </span>Spotlight</span>
              <span className={`hidden text-[10px] font-medium sm:block ${spotlight ? "text-amber-50" : "text-amber-700"}`}>(Top 10: highest equity, better auction odds)</span>
            </span>
          </span>
        </button>

        <div className="max-sm:contents sm:ml-auto sm:flex sm:flex-col sm:items-end sm:gap-1.5">
          <nav className="max-sm:ml-auto flex items-center gap-1 rounded-xl bg-slate-100 p-1" aria-label="Property views">
            <button
              type="button"
              onClick={() => { setLoading(true); setError(null); setDesktopView("dashboard"); }}
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-semibold sm:px-3 ${desktopView === "dashboard" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-current={desktopView === "dashboard" ? "page" : undefined}
            >
              <MapIcon className="h-4 w-4" /><span className="hidden sm:inline">Dashboard</span><span className="sm:hidden">Browse</span>
            </button>
            <button
              type="button"
              onClick={() => { setLoading(true); setError(null); setDesktopView("list"); setMobileView("list"); setSort("gross-equity"); setSortDirection("desc"); setPage(1); }}
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-semibold sm:px-3 ${desktopView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-current={desktopView === "list" ? "page" : undefined}
            >
              <ListFilter className="h-4 w-4" /><span className="hidden sm:inline">List View</span><span className="sm:hidden">Data</span>
            </button>
            <button
              type="button"
              onClick={() => setDesktopView("analytics")}
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-semibold sm:px-3 ${desktopView === "analytics" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-current={desktopView === "analytics" ? "page" : undefined}
            >
              <ChartColumn className="h-4 w-4" /><span className="hidden sm:inline">Analytics</span><span className="sm:hidden">Stats</span>
            </button>
            <button type="button" onClick={() => setRefreshKey((key) => key + 1)} className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50" aria-label="Refresh properties"><RefreshCw className="h-4 w-4" /></button>
          </nav>
          <div className="flex w-full flex-wrap items-center justify-end gap-1.5 sm:w-auto">
            <form onSubmit={submitSearch} className="flex w-full min-w-0 items-center rounded-md border border-slate-300 bg-white pl-2 focus-within:border-teal-500 sm:w-64" role="search">
              <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search address, city, ZIP, case, plaintiff…" className="min-w-0 flex-1 px-1.5 py-2 text-base outline-none sm:py-1 sm:text-xs" />
              {searchInput && <button type="button" onClick={() => { setSearchInput(""); if (searchQuery) { setSearchQuery(""); setPage(1); } }} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Clear search text"><X className="h-3.5 w-3.5" /></button>}
              <button className="self-stretch rounded-r-md bg-teal-600 px-3 py-1 text-sm sm:px-2.5 sm:text-xs font-semibold text-white hover:bg-teal-700">Search</button>
            </form>
            <select
              aria-label="State"
              value={selectedState}
              onChange={(event) => { setSelectedState(event.target.value); setSelectedCounty(""); setFocusedProperty(null); setPage(1); }}
              className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-1.5 py-2 text-base outline-none focus:border-teal-500 sm:w-32 sm:flex-none sm:py-1 sm:text-xs"
            >
              {canShowAll && <option value={ALL_STATES}>All states</option>}
              {allowedStates.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
            </select>
            <select
              aria-label="County"
              value={selectedCounty}
              disabled={allStates}
              title={allStates ? "Choose a state to filter by county" : undefined}
              onChange={(event) => { setSelectedCounty(event.target.value); setPage(1); }}
              className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-1.5 py-2 text-base outline-none focus:border-teal-500 sm:w-32 sm:flex-none sm:py-1 sm:text-xs"
            >
              {!lockedCounty && <option value="">All counties</option>}
              {counties.map((item) => <option key={item.county} value={item.county}>{item.county} ({item.property_count})</option>)}
            </select>
            <button type="button" onClick={resetFilters} className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100"><X className="h-3 w-3" />Clear</button>
            <Link href="/account" className="hidden items-center gap-1 rounded-md sm:flex px-1.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100" title={account?.email}><UserRound className="h-3.5 w-3.5" />{account?.is_developer ? "Developer" : "Account"}</Link>
            <button type="button" onClick={async () => { await signOut(); window.location.assign("/"); }} className="hidden items-center gap-1 rounded-md sm:flex px-1.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100"><LogOut className="h-3.5 w-3.5" />Sign out</button>
          </div>
  
        </div>
      </header>

      <section className="z-20 shrink-0 space-y-2 border-b empty:hidden border-slate-200 bg-white px-4 py-2 shadow-sm sm:px-6">
        {profilePrompt && (
          <div className="flex items-center gap-x-3 gap-y-1 rounded-lg border border-teal-200 bg-teal-50 sm:flex-wrap px-3 py-1.5 text-xs text-teal-900">
            <UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span><span className="font-semibold">Get opportunities that fit you.</span><span className="hidden sm:inline"> Add your budget, states and strategy so we can send targeted investment opportunities. Optional, about a minute.</span></span>
            <Link href="/profile" className="shrink-0 font-semibold underline">Set up my profile</Link>
            <button type="button" onClick={dismissProfilePrompt} className="ml-auto rounded p-0.5 text-teal-700 hover:bg-teal-100" aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}
        {spotlight && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            <Sparkles className="h-3.5 w-3.5" />
            <span className="font-semibold">Investor Spotlight:</span>
            {spotlightSummary && (
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="rounded-full bg-white px-2 py-0.5 font-bold ring-1 ring-amber-200">Top {spotlightSummary.count.toLocaleString()}{selectedCounty ? ` in ${selectedCounty}` : ""}</span>
                <span className="rounded-full bg-white px-2 py-0.5 ring-1 ring-amber-200">Total gross equity <span className="font-bold">{wholeDollars(spotlightSummary.total_gross_equity)}</span></span>
                <span className="rounded-full bg-white px-2 py-0.5 ring-1 ring-amber-200">Avg. gross equity <span className="font-bold">{wholeDollars(spotlightSummary.average_gross_equity)}</span></span>
              </span>
            )}
            <span className="hidden text-amber-800 sm:inline">The upcoming sales with the highest gross equity (Zestimate minus minimum bid), from those with better-than-typical odds of going to auction in their state.</span>
            <button type="button" onClick={() => setSpotlight(false)} className="ml-auto font-semibold underline">Exit spotlight</button>
          </div>
        )}
        {showRecentSale && (
          <div className="flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs leading-5 text-sky-950" role="status">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>
              <span className="font-semibold">Texas counties have not posted their {longDate(nextFirstTuesday(new Date()))} sale lists yet.</span>{" "}
              Showing the most recent Texas sale{recentSaleDate ? ` (${recentSaleDate.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })})` : ""} for reference. These properties have already been offered at auction<span className="hidden sm:inline"> and the county sites do not say which sold; unsold ones can be offered again later. New listings appear here automatically once they are posted</span>.
            </span>
          </div>
        )}
        {searchQuery && <span className="inline-block whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">Search: “{searchQuery}”</span>}
        {countyCounts.length > 0 && !allStates && (
          <section className="hidden w-full rounded-lg border border-teal-200 bg-teal-50/60 px-3 py-2 sm:block" aria-label={`${selectedState} county record counts`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xs font-bold text-teal-950">{selectedState} county coverage</h2>
              <span className="hidden text-xs text-teal-800 sm:inline">Counties with available listings · click to filter</span>
            </div>
            <div className="mt-1 flex w-full flex-nowrap content-start overflow-x-auto text-xs leading-6 sm:flex-wrap">
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

      {desktopView === "analytics" ? <SaleAnalyticsView state={allStates ? undefined : selectedState} county={selectedCounty} stateName={stateInfo.name} /> : <>
      <div className={`sticky top-0 z-30 shrink-0 border-b border-slate-200 bg-white px-4 py-2 ${desktopView === "list" ? "hidden" : "lg:hidden"}`}>
        <div className="grid grid-cols-2 rounded-lg bg-slate-100 p-1">
          <button onClick={() => setMobileView("map")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "map" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><MapIcon className="h-4 w-4" />Map</button>
          <button onClick={() => setMobileView("list")} className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-semibold ${mobileView === "list" ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`}><ListFilter className="h-4 w-4" />List</button>
        </div>
      </div>

      <div className={`grid flex-1 grid-cols-1 lg:min-h-0 lg:overflow-hidden ${desktopView === "dashboard" ? "lg:grid-cols-[minmax(0,2fr)_minmax(22rem,1fr)]" : ""}`}>
        <div className={`${desktopView === "list" ? "hidden" : mobileView === "map" ? "block h-[75dvh]" : "hidden"} min-h-0 overflow-hidden border-r border-slate-200 lg:h-auto ${desktopView === "dashboard" ? "lg:block" : "lg:hidden"}`}>
          {desktopView === "dashboard" && (
            <PropertyMap points={mapPoints.points} total={mapPoints.total} selectedPropertyId={focusedProperty?.property_id ?? selectedProperty?.property_id} onPropertyClick={openMapPoint} onCountySelect={chooseCounty} visibilityKey={mobileView} defaultView={stateInfo.view} />
          )}
        </div>

        <section id="property-results" className={`${desktopView === "list" || mobileView === "list" ? "flex" : "hidden"} scroll-mt-16 flex-col bg-slate-50 lg:flex lg:min-h-0 lg:overflow-hidden`}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 sm:gap-3 sm:py-3">
            <div>
              <h2 className="font-bold text-slate-950">{loading ? "Loading properties…" : `${total.toLocaleString()} properties found`}</h2>
              {!loading && nextSaleDate && (
                <p className="mt-0.5 flex items-center gap-1.5 text-sm text-slate-700">
                  <CalendarDays className="h-4 w-4 text-teal-600" aria-hidden="true" />
                  Next scheduled sale: <span className="font-semibold text-teal-800">{formatSaleDate(nextSaleDate)}</span>
                </p>
              )}
              <p className="text-xs text-slate-500">{mapPoints.points.length.toLocaleString()} on the map{averageEquity != null ? ` · ${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(averageEquity)} avg. equity` : ""}</p>
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
            {desktopView === "list" && <button type="button" onClick={exportProperties} disabled={exporting || loading} className="flex items-center gap-2 rounded-lg border border-teal-600 px-3 py-2 text-sm font-semibold text-teal-700 hover:bg-teal-50 disabled:cursor-wait disabled:opacity-50"><Download className="h-4 w-4" /><span className="hidden sm:inline">{exporting ? "Preparing Excel…" : "Download Excel"}</span><span className="sm:hidden">{exporting ? "…" : "Excel"}</span></button>}
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
            <div className="space-y-3 p-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
              {sortedProperties.map((property) => <PropertyCard key={property.sheriff_sale_id} property={property} selected={selectedProperty?.sheriff_sale_id === property.sheriff_sale_id} onClick={() => focusProperty(property)} />)}
            </div>
          )}

          <footer className="sticky bottom-0 z-20 flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-4 py-3">
            <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40"><ChevronLeft className="h-4 w-4" /><span className="hidden sm:inline">Previous</span></button>
            <span className="text-center text-xs text-slate-500"><span className="hidden sm:inline">Showing <strong className="text-slate-800">{total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)}</strong> of <strong className="text-slate-800">{total.toLocaleString()}</strong> rows · </span>Page <strong className="text-slate-800">{page}</strong> of {totalPages}</span>
            <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} className="flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40"><span className="hidden sm:inline">Next</span><ChevronRight className="h-4 w-4" /></button>
          </footer>
        </section>
      </div>
      </>}

      {selectedProperty && <PropertyDetailModal key={selectedProperty.property_id} property={selectedProperty} onClose={() => setSelectedProperty(null)} onSalePageClick={setSalePageProperty} />}
      {salePageProperty && <SheriffSalePageModal key={salePageProperty.sheriff_sale_id} property={salePageProperty} onClose={() => setSalePageProperty(null)} />}
      {selectedLienSummaryProperty && <PropertyLienSummaryModal key={selectedLienSummaryProperty.property_id} property={selectedLienSummaryProperty} onClose={() => setSelectedLienSummaryProperty(null)} />}
      {selectedComplaintsProperty && <PropertyComplaintsModal key={selectedComplaintsProperty.property_id} property={selectedComplaintsProperty} onClose={() => setSelectedComplaintsProperty(null)} />}
      {selectedHistoryProperty && <PropertyStatusHistoryModal key={selectedHistoryProperty.property_id} property={selectedHistoryProperty} onClose={() => setSelectedHistoryProperty(null)} />}
      {selectedProbabilityReasonProperty && <SaleProbabilityReasonModal key={selectedProbabilityReasonProperty.property_id} property={selectedProbabilityReasonProperty} onClose={() => setSelectedProbabilityReasonProperty(null)} />}
    </main>
  );
}
