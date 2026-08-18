"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { approveParcelCandidate, getLienCoverage, getParcelReviewCandidates, getProperties } from "@/services/properties";
import type { LienCoverageItem, ParcelReviewItem, Property } from "@/types/property";


function formatCurrency(value: number | null | undefined): string {
  if (value == null) {
    return "Pending";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}


function formatPercent(value: number | null | undefined): string {
  if (value == null) {
    return "Pending";
  }

  return `${(value * 100).toFixed(1)}%`;
}

function formatProbability(value: number | null | undefined): string {
  if (value == null) return "Pending";
  return `${Math.round(value * 100)}%`;
}


function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "Pending";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}


function valuationProviderLabel(value: string | null | undefined): string {
  if (value === "monmouth_xgboost_avm_v2") return "Monmouth AVM";
  if (value === "rentcast") return "RentCast";
  if (value === "manual_csv" || value === "manual") return "Manual review";
  return value ?? "Pending";
}

function valuationStatusLabel(value: Property["valuation_status"]): string {
  if (value === "COUNTY_MODEL_UNAVAILABLE") return "County model unavailable";
  if (value === "PARCEL_MATCH_UNDER_REVIEW") return "Parcel match under review";
  if (value === "PARCEL_MATCH_REQUIRED") return "Parcel match required";
  if (value === "MANUAL_REVIEW_REQUIRED") return "Manual review required";
  if (value === "PROPERTY_TYPE_MODEL_UNAVAILABLE") return "Commercial model unavailable";
  if (value === "LIVING_AREA_MISSING") return "Living area missing";
  if (value === "MODEL_SCORING_REQUIRED") return "Ready for model scoring";
  return "Valuation pending";
}


function formatConfidence(value: number | null | undefined): string {
  if (value == null) return "Pending";
  return `${Math.round(value * 100)}%`;
}


function riskColor(level: string | null | undefined): string {
  if (level === "VERY_HIGH") return "bg-red-100 text-red-800";
  if (level === "HIGH") return "bg-orange-100 text-orange-800";
  if (level === "MODERATE") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-700";
}


function lienPositionLabel(position: string): string {
  if (position === "PRIMARY_FORECLOSING") return "Primary / foreclosing";
  if (position === "POTENTIALLY_SENIOR") return "Potentially senior";
  if (position === "SECONDARY_JUNIOR") return "Secondary / junior";
  return "Priority unknown";
}


function lienPositionColor(position: string): string {
  if (position === "PRIMARY_FORECLOSING") {
    return "bg-blue-100 text-blue-800";
  }
  if (position === "POTENTIALLY_SENIOR") {
    return "bg-red-100 text-red-800";
  }
  if (position === "SECONDARY_JUNIOR") {
    return "bg-violet-100 text-violet-800";
  }
  return "bg-slate-100 text-slate-700";
}


function aggregateLienAmounts(property: Property): number | null {
  const amounts = (property.lien_items ?? [])
    .map((lien) => lien.amount)
    .filter((amount): amount is number => amount != null);

  if (amounts.length === 0) return null;
  return amounts.reduce((total, amount) => total + amount, 0);
}

type SortDirection = "asc" | "desc";
type SortKey =
  | "address"
  | "zip"
  | "sheriffNumber"
  | "saleDate"
  | "status"
  | "auctionProbability"
  | "marketValue"
  | "valueRange"
  | "valuationProvider"
  | "avmConfidence"
  | "valuationDate"
  | "judgment"
  | "preferredUpset"
  | "estimatedUpset"
  | "alternateUpset"
  | "grossEquity"
  | "equityPercent"
  | "lienRisk"
  | "lienRecords"
  | "maySurvive"
  | "otherClaims"
  | "knownExposure";

function sortValue(property: Property, key: SortKey): string | number | null | undefined {
  const values: Record<SortKey, string | number | null | undefined> = {
    address: property.normalized_address,
    zip: property.zip_code,
    sheriffNumber: property.sheriff_number,
    saleDate: property.current_sale_date,
    status: property.current_status,
    auctionProbability: property.sale_probability,
    marketValue: property.market_value,
    valueRange: property.market_value_low ?? property.market_value_high,
    valuationProvider: valuationProviderLabel(property.valuation_provider),
    avmConfidence: property.valuation_confidence,
    valuationDate: property.valuation_retrieved_at,
    judgment: property.judgment_amount,
    preferredUpset: property.upset_price,
    estimatedUpset: property.estimated_upset_price,
    alternateUpset: property.alternate_upset_price,
    grossEquity: property.gross_equity,
    equityPercent: property.gross_equity_percent,
    lienRisk: property.lien_risk_score,
    lienRecords: property.lien_record_count,
    maySurvive: property.potentially_surviving_lien_count,
    otherClaims: aggregateLienAmounts(property),
    knownExposure: property.known_lien_exposure,
  };
  return values[key];
}

function SortableHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey | null;
  direction: SortDirection;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  return (
    <th
      className={`px-4 py-3 align-top ${className}`}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="flex w-full items-start gap-1 text-left font-semibold hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
      >
        <span>{label}</span>
        <span aria-hidden="true" className="shrink-0 text-sm normal-case">
          {active ? (direction === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}


const CATEGORY_LABELS: Record<string, string> = {
  MORTGAGE: "Mortgage",
  LIS_PENDENS: "Lis Pendens",
  CONSTRUCTION_LIEN: "Construction Lien",
  HOA_LIEN: "HOA Lien",
  CIVIL_JUDGMENT: "Civil Judgments",
  CHILD_SUPPORT: "Child Support",
  TAX_LIEN: "Tax Liens",
  UNPAID_PROPERTY_TAX: "Unpaid Property Taxes",
  WATER_SEWER: "Water / Sewer",
  TAX_SALE_CERTIFICATE: "Tax Sale Certificates",
  UCC_1: "UCC-1 Financing Statements",
};

const CATEGORY_GROUPS = [
  { title: "County Records", categories: ["MORTGAGE", "LIS_PENDENS", "CONSTRUCTION_LIEN", "HOA_LIEN"] },
  { title: "Statewide Judgments", categories: ["CIVIL_JUDGMENT", "CHILD_SUPPORT", "TAX_LIEN"] },
  { title: "Municipal Liens", categories: ["UNPAID_PROPERTY_TAX", "WATER_SEWER", "TAX_SALE_CERTIFICATE"] },
  { title: "UCC & Business Liens", categories: ["UCC_1"] },
];

const NJ_COUNTIES = ["Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland",
  "Essex", "Gloucester", "Hudson", "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris",
  "Ocean", "Passaic", "Salem", "Somerset", "Sussex", "Union", "Warren"];

const PA_COUNTIES = ["Adams", "Allegheny", "Armstrong", "Beaver", "Bedford", "Berks", "Blair",
  "Bradford", "Bucks", "Butler", "Cambria", "Cameron", "Carbon", "Centre", "Chester", "Clarion",
  "Clearfield", "Clinton", "Columbia", "Crawford", "Cumberland", "Dauphin", "Delaware", "Elk",
  "Erie", "Fayette", "Forest", "Franklin", "Fulton", "Greene", "Huntingdon", "Indiana", "Jefferson",
  "Juniata", "Lackawanna", "Lancaster", "Lawrence", "Lebanon", "Lehigh", "Luzerne", "Lycoming",
  "McKean", "Mercer", "Mifflin", "Monroe", "Montgomery", "Montour", "Northampton", "Northumberland",
  "Perry", "Philadelphia", "Pike", "Potter", "Schuylkill", "Snyder", "Somerset", "Sullivan",
  "Susquehanna", "Tioga", "Union", "Venango", "Warren", "Washington", "Wayne", "Westmoreland",
  "Wyoming", "York"];

const NY_COUNTIES = ["Albany", "Allegany", "Bronx", "Broome", "Cattaraugus", "Cayuga",
  "Chautauqua", "Chemung", "Chenango", "Clinton", "Columbia", "Cortland", "Delaware", "Dutchess",
  "Erie", "Essex", "Franklin", "Fulton", "Genesee", "Greene", "Hamilton", "Herkimer", "Jefferson",
  "Kings", "Lewis", "Livingston", "Madison", "Monroe", "Montgomery", "Nassau", "New York",
  "Niagara", "Oneida", "Onondaga", "Ontario", "Orange", "Orleans", "Oswego", "Otsego", "Putnam",
  "Queens", "Rensselaer", "Richmond", "Rockland", "St. Lawrence", "Saratoga", "Schenectady",
  "Schoharie", "Schuyler", "Seneca", "Steuben", "Suffolk", "Sullivan", "Tioga", "Tompkins",
  "Ulster", "Warren", "Washington", "Wayne", "Westchester", "Wyoming", "Yates"];

const COUNTIES_BY_STATE: Record<string, string[]> = { NJ: NJ_COUNTIES, PA: PA_COUNTIES, NY: NY_COUNTIES };

function coverageStatusStyle(status: LienCoverageItem["status"]): string {
  if (status === "RECORDS_FOUND") return "bg-red-100 text-red-800";
  if (status === "PARTIAL" || status === "POSSIBLE_MATCH") return "bg-amber-100 text-amber-800";
  if (status === "CHECKED_NO_MATCH") return "bg-green-100 text-green-800";
  return "bg-slate-100 text-slate-700";
}


export default function PropertyDashboard() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProperty, setSelectedProperty] = useState<Property | null>(null);
  const [coverage, setCoverage] = useState<LienCoverageItem[]>([]);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [parcelReview, setParcelReview] = useState<ParcelReviewItem[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [approvingCandidate, setApprovingCandidate] = useState<number | null>(null);
  const [selectedCounties, setSelectedCounties] = useState<string[]>(["Monmouth"]);
  const [selectedStates, setSelectedStates] = useState<string[]>(["NJ"]);
  const [countyMenuOpen, setCountyMenuOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const countyMenuRef = useRef<HTMLElement>(null);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  async function loadParcelReview() {
    setReviewLoading(true);
    try {
      setParcelReview(await getParcelReviewCandidates());
      setReviewOpen(true);
    } catch (reviewError) {
      console.error(reviewError);
      setError("Unable to load parcel review candidates.");
    } finally {
      setReviewLoading(false);
    }
  }

  async function approveCandidate(propertyId: string, candidateId: number) {
    setApprovingCandidate(candidateId);
    try {
      await approveParcelCandidate(propertyId, candidateId);
      setParcelReview((items) => items.filter((item) => item.property_id !== propertyId));
    } catch (approvalError) {
      console.error(approvalError);
      setError("Unable to approve the parcel candidate.");
    } finally {
      setApprovingCandidate(null);
    }
  }

  async function showLienSources(property: Property) {
    setSelectedProperty(property);
    setCoverageLoading(true);
    try {
      setCoverage(await getLienCoverage(property.property_id));
    } catch (coverageError) {
      console.error(coverageError);
      setCoverage([]);
    } finally {
      setCoverageLoading(false);
    }
  }

  useEffect(() => {
    async function loadProperties() {
      try {
        setIsLoading(true);
        setError(null);

        const response = await getProperties({
          states: selectedStates,
          counties: selectedCounties,
          status: "scheduled",
          futureOnly: true,
          page: currentPage,
          pageSize: 50,
        });

        setProperties(response.items);
        setTotal(response.total);
      } catch (loadError) {
        console.error(loadError);

        setError(
          "Unable to load properties. Make sure the FastAPI backend is running.",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadProperties();
  }, [currentPage, refreshKey, selectedCounties, selectedStates]);

  useEffect(() => {
    if (!countyMenuOpen) return;

    function closeOnOutsidePointer(event: PointerEvent) {
      if (countyMenuRef.current && !countyMenuRef.current.contains(event.target as Node)) {
        setCountyMenuOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setCountyMenuOpen(false);
    }

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [countyMenuOpen]);

  const availableCounties = useMemo(() => selectedStates.flatMap((state) =>
    (COUNTIES_BY_STATE[state] ?? []).map((county) => ({ state, county }))), [selectedStates]);

  function toggleState(state: string) {
    setCurrentPage(1);
    setSelectedStates((current) => {
      const next = current.includes(state) ? current.filter((item) => item !== state) : [...current, state];
      const allowed = new Set(next.flatMap((item) => COUNTIES_BY_STATE[item] ?? []));
      setSelectedCounties((counties) => counties.filter((county) => allowed.has(county)));
      return next;
    });
  }

  function toggleCounty(county: string) {
    setCurrentPage(1);
    setSelectedCounties((current) => current.includes(county)
      ? current.filter((item) => item !== county)
      : [...current, county]);
  }

  const averageEquity = useMemo(() => {
    const propertiesWithEquity = properties.filter(
      (property) => property.gross_equity != null,
    );

    if (propertiesWithEquity.length === 0) {
      return null;
    }

    const totalEquity = propertiesWithEquity.reduce(
      (sum, property) => sum + (property.gross_equity ?? 0),
      0,
    );

    return totalEquity / propertiesWithEquity.length;
  }, [properties]);

  const highEquityCount = useMemo(() => {
    return properties.filter(
      (property) =>
        property.gross_equity != null &&
        property.gross_equity >= 150000,
    ).length;
  }, [properties]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(key);
    setSortDirection("asc");
  }

  const sortedProperties = useMemo(() => {
    if (!sortKey) return properties;
    return [...properties].sort((left, right) => {
      const leftValue = sortValue(left, sortKey);
      const rightValue = sortValue(right, sortKey);
      const leftMissing = leftValue == null || leftValue === "";
      const rightMissing = rightValue == null || rightValue === "";
      if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
      if (leftMissing && rightMissing) return 0;

      const comparison = typeof leftValue === "number" && typeof rightValue === "number"
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: "base" });
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [properties, sortDirection, sortKey]);

  const opportunityThresholds = useMemo(() => {
    function upperQuartile(values: number[]): number | null {
      if (values.length === 0) return null;
      const sorted = [...values].sort((left, right) => left - right);
      return sorted[Math.floor((sorted.length - 1) * 0.75)];
    }
    return {
      probability: upperQuartile(properties
        .map((property) => property.sale_probability)
        .filter((value): value is number => value != null)),
      equity: upperQuartile(properties
        .map((property) => property.gross_equity)
        .filter((value): value is number => value != null)),
    };
  }, [properties]);

  const totalPages = Math.max(1, Math.ceil(total / 50));
  const firstPropertyNumber = total === 0 ? 0 : (currentPage - 1) * 50 + 1;
  const lastPropertyNumber = Math.min(currentPage * 50, total);

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8">
          <h1 className="text-3xl font-bold text-slate-900 md:text-4xl">
            NJ, PA &amp; NY Sheriff Sale Dashboard
          </h1>

          <p className="mt-2 text-slate-600">
            Scheduled sheriff-sale properties in New Jersey, Pennsylvania, and New York
          </p>
        </header>

        <section ref={countyMenuRef} className="relative z-20 mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-semibold text-slate-700">States</span>
            {(["NJ", "PA", "NY"] as const).map((state) => <label key={state} className="flex items-center gap-2 rounded border border-slate-300 px-3 py-2 text-sm">
              <input type="checkbox" checked={selectedStates.includes(state)} onChange={() => toggleState(state)} />{state}
            </label>)}
            <span className="text-sm font-semibold text-slate-700">Counties</span>
            <button type="button" onClick={() => setCountyMenuOpen((open) => !open)}
              className="min-w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">
              {selectedCounties.length === 0 ? "All counties" : selectedCounties.length <= 3
                ? selectedCounties.join(", ") : `${selectedCounties.length} counties selected`}
            </button>
            {selectedCounties.length > 0 && <button type="button" onClick={() => {
              setCurrentPage(1);
              setSelectedCounties([]);
            }}
              className="text-sm font-semibold text-blue-700 hover:underline">Show all</button>}
          </div>
          {countyMenuOpen && <div className="absolute left-4 top-full mt-1 grid max-h-80 w-[min(42rem,calc(100vw-2rem))] grid-cols-2 gap-1 overflow-y-auto rounded-lg border border-slate-300 bg-white p-3 shadow-xl sm:grid-cols-3">
            {availableCounties.map(({state, county}) => <label key={`${state}-${county}`} className="flex cursor-pointer items-center gap-2 rounded px-2 py-2 text-sm hover:bg-slate-50">
              <input type="checkbox" checked={selectedCounties.includes(county)} onChange={() => toggleCounty(county)}
                className="h-4 w-4 rounded border-slate-300" /><span>{county} <span className="text-xs text-slate-400">{state}</span></span>
            </label>)}
          </div>}
        </section>

        <section className="mb-8 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-medium text-slate-500">
              Scheduled properties
            </p>

            <p className="mt-2 text-3xl font-bold text-slate-900">
              {isLoading ? "..." : total}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-medium text-slate-500">
              Average gross equity
            </p>

            <p className="mt-2 text-3xl font-bold text-slate-900">
              {isLoading ? "..." : formatCurrency(averageEquity)}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-medium text-slate-500">
              High-equity properties
            </p>

            <p className="mt-2 text-3xl font-bold text-slate-900">
              {isLoading ? "..." : highEquityCount}
            </p>
          </div>
        </section>

        <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Parcel identity review</h2>
              <p className="mt-1 text-sm text-slate-600">
                Confirm ambiguous MOD-IV matches to unlock authoritative property features and potential AVM scoring.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {reviewOpen && (
                <button
                  type="button"
                  onClick={() => setReviewOpen(false)}
                  aria-expanded="true"
                  aria-controls="parcel-identity-review-content"
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Collapse
                </button>
              )}
              <button type="button" onClick={() => void loadParcelReview()}
                disabled={reviewLoading}
                aria-expanded={reviewOpen}
                aria-controls="parcel-identity-review-content"
                className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50">
                {reviewLoading ? "Loading…" : reviewOpen ? "Refresh candidates" : "Review candidates"}
              </button>
            </div>
          </div>
          {reviewOpen && (
            <div id="parcel-identity-review-content" className="mt-5 space-y-4">
              {parcelReview.length === 0 ? <p className="text-sm text-slate-600">No pending candidates.</p> :
                parcelReview.map((item) => (
                  <article key={item.property_id} className="overflow-hidden rounded-lg border border-slate-300">
                    <div className="flex flex-wrap items-start justify-between gap-2 bg-slate-100 px-4 py-3">
                      <div><h3 className="font-semibold text-slate-900">{item.normalized_address}</h3>
                        <p className="text-xs text-slate-500">{item.city} {item.zip_code ?? ""}</p></div>
                      <div className="flex gap-2">{item.is_scheduled && <span className="rounded bg-green-100 px-2 py-1 text-xs font-medium text-green-800">Scheduled</span>}
                        {item.missing_valuation && <span className="rounded bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">No valuation</span>}</div>
                    </div>
                    <div className="overflow-x-auto"><table className="min-w-full text-left text-sm">
                      <thead className="bg-slate-50 text-xs uppercase text-slate-600"><tr><th className="px-4 py-2">Candidate address</th><th className="px-4 py-2">Block / lot</th><th className="px-4 py-2">Qualifier</th><th className="px-4 py-2">Match score</th><th className="px-4 py-2">Decision</th></tr></thead>
                      <tbody>{item.candidates.map((candidate) => <tr key={candidate.candidate_id} className="border-t border-slate-200">
                        <td className="px-4 py-3 font-medium text-slate-900">{candidate.property_location}</td>
                        <td className="px-4 py-3 text-slate-700">{candidate.block} / {candidate.lot}</td>
                        <td className="px-4 py-3 text-slate-700">{candidate.qualifier || "None"}</td>
                        <td className="px-4 py-3 text-slate-700">{Math.round(candidate.score * 100)}%</td>
                        <td className="px-4 py-3"><button type="button" disabled={approvingCandidate != null}
                          onClick={() => void approveCandidate(item.property_id, candidate.candidate_id)}
                          className="rounded border border-blue-700 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50">
                          {approvingCandidate === candidate.candidate_id ? "Approving…" : "Approve match"}</button></td>
                      </tr>)}</tbody></table></div>
                  </article>
                ))}
            </div>
          )}
        </section>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
            {error}
          </div>
        )}

        {selectedProperty && (
          <section className="mb-6 rounded-xl border border-slate-300 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">Lien Source Coverage</h2>
                <p className="mt-1 text-sm text-slate-600">{selectedProperty.normalized_address}</p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedProperty(null)}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
            </div>

            <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              Unchecked or unavailable sources are not zero balances. This is preliminary public-record screening, not a title search.
            </p>

            <div className="mt-5 overflow-hidden rounded-lg border border-slate-300">
              <h3 className="border-b border-slate-300 bg-slate-100 px-4 py-3 font-semibold text-slate-900">
                Foreclosure Case
              </h3>
              <dl className="grid sm:grid-cols-2 lg:grid-cols-3">
                <div className="border-b border-slate-200 p-4 sm:border-r lg:col-span-2">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Plaintiff — brought the foreclosure
                  </dt>
                  <dd className="mt-2 font-medium text-slate-900">
                    {selectedProperty.plaintiff ?? "Not provided"}
                  </dd>
                </div>
                <div className="border-b border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Court case
                  </dt>
                  <dd className="mt-2 font-medium text-slate-900">
                    {selectedProperty.court_case_number ?? "Not provided"}
                  </dd>
                </div>
                <div className="border-b border-slate-200 p-4 sm:border-r lg:col-span-2">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Defendant
                  </dt>
                  <dd className="mt-2 text-slate-900">
                    {selectedProperty.defendant ?? "Not provided"}
                  </dd>
                </div>
                <div className="border-b border-slate-200 p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Sheriff number
                  </dt>
                  <dd className="mt-2 font-medium text-slate-900">
                    {selectedProperty.sheriff_number}
                  </dd>
                </div>
                <div className="p-4 sm:border-r">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Judgment
                  </dt>
                  <dd className="mt-2 font-semibold text-slate-900">
                    {formatCurrency(selectedProperty.judgment_amount)}
                  </dd>
                </div>
                <div className="p-4 sm:border-r">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Preferred upset
                  </dt>
                  <dd className="mt-2 font-semibold text-slate-900">
                    {formatCurrency(selectedProperty.upset_price)}
                  </dd>
                </div>
                <div className="p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Source
                  </dt>
                  <dd className="mt-2">
                    {selectedProperty.foreclosure_source_url ? (
                      <a
                        href={selectedProperty.foreclosure_source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold text-blue-700 hover:underline"
                      >
                        Open CivilView sale detail
                      </a>
                    ) : (
                      <span className="text-slate-500">Not available</span>
                    )}
                  </dd>
                </div>
              </dl>
            </div>

            {(selectedProperty.lien_items?.length ?? 0) > 0 && (
              <div className="mt-5 overflow-hidden rounded-lg border border-slate-300">
                <h3 className="border-b border-slate-300 bg-slate-100 px-4 py-3 font-semibold text-slate-900">
                  Detected Claimants and Lien Positions
                </h3>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                      <tr>
                        <th className="px-4 py-3">Lienholder / claimant</th>
                        <th className="border-l border-slate-300 px-4 py-3">Type</th>
                        <th className="border-l border-slate-300 px-4 py-3">Position</th>
                        <th className="border-l border-slate-300 px-4 py-3">Amount</th>
                        <th className="border-l border-slate-300 px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedProperty.lien_items?.map((lien) => (
                        <tr key={lien.id} className="border-t border-slate-200 align-top">
                          <td className="max-w-md px-4 py-3 font-medium text-slate-900">
                            {lien.holder}
                          </td>
                          <td className="border-l border-slate-300 px-4 py-3 text-slate-700">
                            {(lien.subtype ?? lien.type).replaceAll("_", " ")}
                          </td>
                          <td className="border-l border-slate-300 px-4 py-3">
                            <span className={`rounded-full px-2 py-1 text-xs font-medium ${lienPositionColor(lien.position)}`}>
                              {lienPositionLabel(lien.position)}
                            </span>
                            <p className="mt-2 text-xs text-slate-500">
                              Confidence {Math.round(lien.position_confidence)}%
                            </p>
                          </td>
                          <td className="whitespace-nowrap border-l border-slate-300 px-4 py-3 font-medium text-slate-900">
                            {lien.amount == null ? "Amount unknown" : formatCurrency(lien.amount)}
                          </td>
                          <td className="border-l border-slate-300 px-4 py-3 text-slate-700">
                            {lien.status.replaceAll("_", " ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="border-t-2 border-slate-300 bg-slate-50">
                      <tr>
                        <td colSpan={3} className="px-4 py-3 text-right font-semibold text-slate-700">
                          Aggregated quantified claims
                        </td>
                        <td className="whitespace-nowrap border-l border-slate-300 px-4 py-3 font-bold text-slate-900">
                          {formatCurrency(aggregateLienAmounts(selectedProperty))}
                        </td>
                        <td className="border-l border-slate-300 px-4 py-3 text-xs text-slate-500">
                          Excludes unknown amounts
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}

            {coverageLoading ? (
              <p className="py-8 text-center text-slate-500">Loading source coverage...</p>
            ) : (
              <div className="mt-5 grid gap-4 lg:grid-cols-2">
                {CATEGORY_GROUPS.map((group) => (
                  <div key={group.title} className="overflow-hidden rounded-lg border border-slate-300">
                    <h3 className="border-b border-slate-300 bg-slate-100 px-4 py-3 font-semibold text-slate-900">
                      {group.title}
                    </h3>
                    <div className="divide-y divide-slate-200">
                      {group.categories.map((category) => {
                        const item = coverage.find((entry) => entry.category === category);
                        return (
                          <div key={category} className="grid gap-2 p-4 sm:grid-cols-[1fr_auto]">
                            <div>
                              <p className="font-medium text-slate-900">{CATEGORY_LABELS[category]}</p>
                              <p className="mt-1 text-xs text-slate-500">{item?.source_name ?? "Source not configured"}</p>
                              {item?.message && <p className="mt-2 text-sm text-slate-600">{item.message}</p>}
                            </div>
                            <div className="text-left sm:text-right">
                              <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-medium ${coverageStatusStyle(item?.status ?? "NOT_CHECKED")}`}>
                                {(item?.status ?? "NOT_CHECKED").replaceAll("_", " ")}
                              </span>
                              <p className="mt-2 text-sm font-medium text-slate-900">
                                {item?.record_count ?? 0} record(s)
                              </p>
                              <p className="text-xs text-slate-500">
                                {item?.quantified_amount == null ? "Amount not established" : formatCurrency(item.quantified_amount)}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                Upcoming scheduled properties
              </h2>
              <p className="mt-1 text-xs text-slate-500">Showing sale dates from today forward.</p>
            </div>
            <button
              type="button"
              onClick={() => setRefreshKey((value) => value + 1)}
              disabled={isLoading}
              className="rounded-lg border border-blue-700 bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {isLoading ? (
            <div className="p-10 text-center text-slate-500">
              Loading properties...
            </div>
          ) : properties.length === 0 ? (
            <div className="p-10 text-center text-slate-500">
              No scheduled properties were found.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-[2720px] table-fixed text-left text-sm [&_td]:!whitespace-normal [&_td]:break-words [&_th]:whitespace-normal [&_th]:break-words">
                <thead className="bg-slate-100 text-xs uppercase text-slate-600">
                  <tr>
                    <SortableHeader label="Address" sortKey="address" activeKey={sortKey} direction={sortDirection} onSort={handleSort} className="w-64" />
                    <SortableHeader label="ZIP" sortKey="zip" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Sheriff number" sortKey="sheriffNumber" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Sale date" sortKey="saleDate" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Probability to auction" sortKey="auctionProbability" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Market value" sortKey="marketValue" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Value range" sortKey="valueRange" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Valuation provider" sortKey="valuationProvider" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="AVM confidence" sortKey="avmConfidence" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Valuation date" sortKey="valuationDate" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Judgment" sortKey="judgment" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Preferred upset" sortKey="preferredUpset" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Estimated upset" sortKey="estimatedUpset" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Alternate upset" sortKey="alternateUpset" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Gross equity" sortKey="grossEquity" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Equity %" sortKey="equityPercent" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Lien risk" sortKey="lienRisk" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Lien records" sortKey="lienRecords" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="May survive" sortKey="maySurvive" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Other disclosed claims" sortKey="otherClaims" activeKey={sortKey} direction={sortDirection} onSort={handleSort} className="border-l border-slate-300" />
                    <SortableHeader label="Known exposure" sortKey="knownExposure" activeKey={sortKey} direction={sortDirection} onSort={handleSort} className="border-l border-slate-300" />
                  </tr>
                </thead>

                <tbody>
                  {sortedProperties.map((property) => {
                    const highOpportunity = property.sale_probability != null &&
                      property.gross_equity != null &&
                      opportunityThresholds.probability != null &&
                      opportunityThresholds.equity != null &&
                      property.sale_probability >= opportunityThresholds.probability &&
                      property.gross_equity >= opportunityThresholds.equity &&
                      property.gross_equity > 0;
                    return (
                    <tr
                      key={property.sheriff_sale_id}
                      className={`border-t border-slate-200 align-top ${highOpportunity
                        ? "bg-green-100 hover:bg-green-200"
                        : "hover:bg-slate-50"}`}
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-900">
                        <p>{property.normalized_address}</p>
                        <button
                          type="button"
                          onClick={() => void showLienSources(property)}
                          className="mt-2 text-xs font-semibold text-blue-700 hover:underline"
                        >
                          View lien sources
                        </button>
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {property.zip_code ?? "Pending"}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {property.sheriff_number}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatDate(property.current_sale_date)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3">
                        <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
                          {property.current_status}
                        </span>
                      </td>

                      <td className="px-4 py-3 text-slate-700">
                        <span className="font-semibold text-slate-900">
                          {formatProbability(property.sale_probability)}
                        </span>
                        {property.sale_probability_features?.confidence != null ? (
                          <p className="mt-1 text-xs text-slate-500">
                            Confidence {formatProbability(property.sale_probability_features.confidence)}
                          </p>
                        ) : null}
                        {property.sale_probability != null ? (
                          <p className="mt-1 text-xs text-slate-500" title={property.sale_probability_features?.methodology}>
                            Heuristic estimate
                          </p>
                        ) : null}
                      </td>

                      <td className="px-4 py-3 text-slate-700">
                        {property.market_value != null ? formatCurrency(property.market_value) : (
                          <div className="min-w-44">
                            <p className="font-medium text-amber-700">
                              {valuationStatusLabel(property.valuation_status)}
                            </p>
                            {property.valuation_pending_reason ? (
                              <p className="mt-1 text-xs text-slate-500">
                                {property.valuation_pending_reason}
                              </p>
                            ) : null}
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3 text-slate-700">
                        {property.market_value_low != null &&
                        property.market_value_high != null
                          ? `${formatCurrency(property.market_value_low)}–${formatCurrency(property.market_value_high)}`
                          : "Not available until valuation is resolved"}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        <span className="font-medium text-slate-900">
                          {valuationProviderLabel(property.valuation_provider)}
                        </span>
                        {property.valuation_provider === "monmouth_xgboost_avm_v2" ? (
                          <p className="mt-1 text-xs text-slate-500">
                            Statistical estimate—not an appraisal
                          </p>
                        ) : null}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatConfidence(property.valuation_confidence)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatDate(property.valuation_retrieved_at)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCurrency(property.judgment_amount)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCurrency(property.upset_price)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCurrency(property.estimated_upset_price)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCurrency(property.alternate_upset_price)}
                        {property.upset_price_conflict ? (
                          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                            Review
                          </span>
                        ) : null}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-900">
                        {formatCurrency(property.gross_equity)}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatPercent(
                          property.gross_equity_percent,
                        )}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3">
                        {property.lien_risk_score == null ? (
                          <span className="text-slate-500">Not screened</span>
                        ) : (
                          <div>
                            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${riskColor(property.lien_risk_level)}`}>
                              {property.lien_risk_score}/100 {property.lien_risk_level}
                            </span>
                            <p className="mt-1 text-xs text-slate-500">
                              Confidence {property.lien_risk_confidence ?? 0}%
                            </p>
                          </div>
                        )}
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        <span className="font-medium text-slate-900">
                          {property.lien_record_count ?? 0}
                        </span>
                        <p className="mt-1 text-xs text-slate-500">
                          {property.open_lien_count ?? 0} open/unknown
                        </p>
                      </td>

                      <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                        <span className="font-medium text-slate-900">
                          {property.potentially_surviving_lien_count ?? 0}
                        </span>
                        {(property.lien_manual_review_count ?? 0) > 0 ? (
                          <p className="mt-1 text-xs text-amber-700">
                            {property.lien_manual_review_count} need review
                          </p>
                        ) : null}
                      </td>

                      <td className="min-w-44 border-l border-slate-300 px-4 py-3 align-top text-slate-700">
                        <p className="font-semibold text-slate-900">
                          {aggregateLienAmounts(property) == null
                            ? "No additional claim amount identified"
                            : formatCurrency(aggregateLienAmounts(property))}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          Excludes foreclosure judgment
                        </p>
                        {(property.lien_items ?? []).some((lien) => lien.amount == null) && (
                          <p className="mt-1 text-xs text-amber-700">
                            Plus unknown amounts
                          </p>
                        )}
                      </td>

                      <td className="whitespace-nowrap border-l border-slate-300 px-4 py-3 align-top text-slate-700">
                        {formatCurrency(property.known_lien_exposure)}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4">
                <p className="text-sm text-slate-600">
                  Showing {firstPropertyNumber}–{lastPropertyNumber} of {total} properties
                </p>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                    disabled={currentPage === 1 || isLoading}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span className="text-sm font-medium text-slate-700">
                    Page {currentPage} of {totalPages}
                  </span>
                  <button
                    type="button"
                    onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                    disabled={currentPage >= totalPages || isLoading}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
