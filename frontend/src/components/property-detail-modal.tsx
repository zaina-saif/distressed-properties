"use client";

import {
  Bath,
  BedDouble,
  CalendarDays,
  ExternalLink,
  Gavel,
  Landmark,
  MapPin,
  Ruler,
  ShieldAlert,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { saleTypeNote } from "@/lib/sale-notes";
import { getLienCoverage, getLiens, getProfessionalTitleSearch } from "@/services/properties";
import type { LienCoverageItem, LienItem, ProfessionalTitleSearch, Property } from "@/types/property";

function currency(value: number | null | undefined): string {
  if (value == null) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function percent(value: number | null | undefined): string {
  if (value == null) return "Unavailable";
  return `${Math.round(value * 100)}%`;
}

/** dd/mm/yyyy, read in UTC so date-only values do not shift a day. */
function ddmmyyyy(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${pad(parsed.getUTCDate())}/${pad(parsed.getUTCMonth() + 1)}/${parsed.getUTCFullYear()}`;
}

function date(value: string | null | undefined): string {
  return ddmmyyyy(value) ?? "Unavailable";
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2.5 last:border-0">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-right text-sm font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

function readable(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const zillowDetailKeys = [
  "daysOnZillow", "pageViewCount", "favoriteCount", "rentZestimate",
  "lotArea", "pricePerSquareFoot", "taxAssessedValue", "onMarketDate",
  "taxAnnualAmount", "parking", "garageSpaces", "dateSold", "priceChange", "priceChangedAt",
  "monthlyHoaFee", "hoa", "propertyTaxRate", "listingMortgageRates",
];

const ZILLOW_DATE_KEYS = new Set(["onMarketDate", "dateSold", "priceChangedAt"]);

function parkingInfo(value: unknown): { hasGarage: boolean; spaces: number | null } | null {
  if (typeof value !== "object" || value === null) return null;
  const parking = value as { hasGarage?: boolean; hasAttachedGarage?: boolean; totalSpaces?: number; features?: unknown[] };
  const featureGarage = Array.isArray(parking.features) && parking.features.some((feature) => /garage/i.test(String(feature)));
  const hasGarage = Boolean(parking.hasGarage || parking.hasAttachedGarage || featureGarage);
  return { hasGarage, spaces: typeof parking.totalSpaces === "number" && parking.totalSpaces > 0 ? parking.totalSpaces : null };
}

function readableZillowValue(key: string, value: unknown, data?: Record<string, unknown> | null): string {
  if (key === "parking") {
    const parking = parkingInfo(value);
    return parking ? (parking.hasGarage ? "Garage" : "No garage") : "Unavailable";
  }
  if (key === "garageSpaces") {
    const parking = parkingInfo(data?.parking);
    return parking?.hasGarage ? (parking.spaces != null ? String(parking.spaces) : "Not stated") : "";
  }
  if (ZILLOW_DATE_KEYS.has(key)) return ddmmyyyy(value as string) ?? "Unavailable";
  if (key === "lotArea" && typeof value === "object" && value !== null && "value" in value && typeof value.value === "number") {
    const unit = "unit" in value && typeof value.unit === "string" ? value.unit.toLowerCase() : "";
    const acres = unit.includes("acre") ? value.value : value.value / 43560;
    return `${acres.toLocaleString("en-US", { maximumFractionDigits: 2 })} acres`;
  }
  return readable(value) || "Unavailable";
}

function zillowLabel(key: string): string {
  if (key === "garageSpaces") return "Garage spaces";
  if (key === "zpid") return "Zillow ID";
  return key.replaceAll(/([A-Z])/g, " $1").replace(/^./, (character) => character.toUpperCase());
}

const MONEY_KEYS = new Set(["price", "value", "taxPaid", "pricePerSquareFoot"]);
const HIDDEN_TABLE_KEYS = new Set(["propertyUrl", "link"]);

function titleCase(value: string): string {
  return value.toLowerCase().replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

/** Flatten nested values a reader would want as their own columns. */
function tableRow(row: Record<string, unknown>): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    if (HIDDEN_TABLE_KEYS.has(key)) continue;
    if (key === "coordinates" && typeof value === "object" && value !== null) {
      const coordinates = value as { latitude?: unknown; longitude?: unknown };
      flat.latitude = coordinates.latitude;
      flat.longitude = coordinates.longitude;
      continue;
    }
    flat[key] = value;
  }
  return flat;
}

function tableCell(key: string, value: unknown): ReactNode {
  if (value == null || value === "") return "";
  if (key === "date" || key.endsWith("Date") || key.endsWith("At")) return ddmmyyyy(value as string) ?? readable(value);
  if (key === "year" || key === "zpid") return String(value);
  if (key === "latitude" || key === "longitude") return String(value);
  if (key === "mainImage") {
    // Zillow-hosted photos only; Street View links carry Zillow's own Google key.
    return typeof value === "string" && value.startsWith("https://photos.zillowstatic.com/")
      // eslint-disable-next-line @next/next/no-img-element -- remote Zillow photo, shown as-is
      ? <img src={value} alt="" loading="lazy" className="h-14 w-20 rounded object-cover" />
      : "No photo";
  }
  if (key === "address" && typeof value === "object") {
    const address = value as { street?: string; city?: string; state?: string; zipCode?: string };
    return [address.street, address.city, [address.state, address.zipCode].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  }
  if (typeof value === "number" && MONEY_KEYS.has(key)) return currency(value);
  if (typeof value === "number" && key.endsWith("Rate")) return `${(value * 100).toFixed(1)}%`;
  if (key === "livingArea" && typeof value === "number") return `${value.toLocaleString("en-US")} sqft`;
  if (key === "distance" && typeof value === "number") return `${value} mi`;
  if ((key === "homeType" || key === "homeStatus" || key === "event") && typeof value === "string") return titleCase(value);
  return readable(value);
}

function propertyFactValue(primary: unknown, zillowValue: unknown, key?: string): string | number {
  if (primary !== null && primary !== undefined && primary !== "") {
    return typeof primary === "number" ? primary.toLocaleString("en-US") : String(primary);
  }
  return readableZillowValue(key ?? "", zillowValue);
}

function ApifyTable({ title, value }: { title: string; value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return null;
  const rows = value
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null && !Array.isArray(item))
    .map(tableRow);
  if (rows.length === 0) return null;
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <section className="mt-5 rounded-xl border border-slate-200 p-4">
      <h3 className="mb-3 font-bold text-slate-900">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-left text-xs">
          <thead><tr className="border-b border-slate-200 bg-slate-50">{keys.map((key) => <th key={key} className="whitespace-nowrap px-3 py-2 font-semibold text-slate-600">{zillowLabel(key)}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index} className="border-b border-slate-100 last:border-0">{keys.map((key) => <td key={key} className="max-w-72 px-3 py-2 align-top text-slate-700">{tableCell(key, row[key])}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

export function PropertyDetailModal({
  property,
  onClose,
  onSalePageClick,
}: {
  property: Property;
  onClose: () => void;
  onSalePageClick: (property: Property) => void;
}) {
  const [coverage, setCoverage] = useState<LienCoverageItem[]>([]);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [liens, setLiens] = useState<LienItem[]>([]);
  const [titleSearch, setTitleSearch] = useState<ProfessionalTitleSearch | null>(null);

  useEffect(() => {
    let active = true;
    getLienCoverage(property.property_id)
      .then((items) => { if (active) setCoverage(items); })
      .catch(() => { if (active) setCoverage([]); })
      .finally(() => { if (active) setCoverageLoading(false); });
    getProfessionalTitleSearch(property.property_id)
      .then((provider) => { if (active) setTitleSearch(provider); })
      .catch(() => { if (active) setTitleSearch(null); });
    getLiens(property.property_id)
      .then((items) => { if (active) setLiens(items); })
      .catch(() => { if (active) setLiens([]); });
    return () => { active = false; };
  }, [property.property_id]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-slate-950/55 p-3 sm:p-6" onMouseDown={onClose}>
      <article
        role="dialog"
        aria-modal="true"
        aria-labelledby="property-detail-title"
        className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-7">
          <div>
            <div className="flex items-start gap-2">
              <MapPin className="mt-1 h-5 w-5 shrink-0 text-teal-600" />
              <div>
                <h2 id="property-detail-title" className="text-xl font-bold text-slate-950">{property.street_address}</h2>
                <p className="text-sm text-slate-600">{property.city}, {property.state} {property.zip_code ?? ""}</p>
              </div>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 text-slate-500 hover:bg-slate-100" aria-label="Close property details">
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="overflow-y-auto p-5 sm:p-7">
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-teal-200 bg-teal-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Estimated value</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{currency(property.market_value)}</p>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Gross equity</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{currency(property.gross_equity)}</p>
              <p className="mt-1 text-xs text-slate-500">{percent(property.gross_equity_percent)} of estimated value</p>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Minimum Bid / Upset amount</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{currency(property.minimum_asking_amount ?? property.upset_price ?? property.judgment_amount)}</p>
              <p className="mt-1 text-xs text-slate-500">
                {property.minimum_bid_basis === "approx_upset" ? "Upset amount from the sheriff's listing"
                  : property.minimum_bid_basis === "judgment" ? "No upset amount published; judgment amount shown"
                  : property.minimum_bid_basis === "notice_estimate" ? "Upset estimate from the sale notice"
                  : property.upset_price != null ? "Upset amount" : "Judgment amount"}
              </p>
              <p className="mt-1 text-xs text-slate-500">Judgment: {currency(property.judgment_amount)}{property.judgment_amount_as_of_date ? ` (as of ${date(property.judgment_amount_as_of_date)}; not current payoff)` : ""}</p>
              {property.judgment_source_url && <a href={property.judgment_source_url} target="_blank" rel="noreferrer" className="text-xs font-medium text-teal-700 underline">View judgment source</a>}
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Sale probability</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{percent(property.sale_probability)}</p>
              <p className="mt-1 text-xs text-slate-500">Model output when available</p>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <section className="rounded-xl border border-slate-200 p-4">
              <h3 className="mb-3 flex items-center gap-2 font-bold text-slate-900"><Landmark className="h-4 w-4 text-teal-600" />Property facts</h3>
              <dl>
                <Fact label="Property type" value={propertyFactValue(property.property_type, property.apify_data?.homeType, "homeType")} />
                <Fact label="Bedrooms" value={propertyFactValue(property.bedrooms, property.apify_data?.bedrooms, "bedrooms")} />
                <Fact label="Bathrooms" value={propertyFactValue(property.bathrooms, property.apify_data?.bathrooms, "bathrooms")} />
                <Fact label="Square feet" value={propertyFactValue(property.square_feet, property.apify_data?.livingArea, "livingArea")} />
                <Fact label="Acreage" value={propertyFactValue(property.acreage, property.apify_data?.lotArea, "lotArea")} />
                <Fact label="Year built" value={propertyFactValue(property.year_built, property.apify_data?.yearBuilt, "yearBuilt")} />
                <Fact label="Parcel ID" value={property.pams_pin ?? "Unavailable"} />
              </dl>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                {property.bedrooms != null && <span className="flex items-center gap-1"><BedDouble className="h-3.5 w-3.5" />{property.bedrooms} beds</span>}
                {property.bathrooms != null && <span className="flex items-center gap-1"><Bath className="h-3.5 w-3.5" />{property.bathrooms} baths</span>}
                {property.square_feet != null && <span className="flex items-center gap-1"><Ruler className="h-3.5 w-3.5" />{property.square_feet.toLocaleString()} sqft</span>}
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 p-4">
              <h3 className="mb-3 flex items-center gap-2 font-bold text-slate-900"><Gavel className="h-4 w-4 text-teal-600" />{property.sale_type ?? "Sheriff sale"}</h3>
              {saleTypeNote(property) && <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">{saleTypeNote(property)}</p>}
              <dl>
                <Fact label="Status" value={property.current_status.replaceAll("_", " ")} />
                <Fact label="Sale date" value={date(property.current_sale_date)} />
                <Fact label={saleTypeNote(property) ? "Minimum bid" : "Upset price"} value={currency(property.upset_price)} />
                <Fact label={property.sale_type === "Sheriff sale" ? "Sheriff number" : "Auction ID"} value={property.sheriff_number} />
                <Fact label="Court case" value={property.court_case_number
                  ? <button type="button" onClick={() => onSalePageClick(property)} className="text-teal-700 underline hover:text-teal-900" title="View the sheriff sale page">{property.court_case_number}</button>
                  : "Unavailable"} />
                <Fact label="Parcel / tax ID" value={property.bbl ?? "Unavailable"} />
                <Fact label="Plaintiff" value={property.plaintiff ?? "Unavailable"} />
                <Fact label="Defendant" value={property.defendant ?? "Unavailable"} />
                {property.notice_lien_amount != null && <Fact label="Approx. lien amount (notice)" value={currency(property.notice_lien_amount)} />}
              </dl>
              {property.notice_details && <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700">{property.notice_details}</p>}
              {property.state === "NJ" ? (
                <button type="button" onClick={() => onSalePageClick(property)} className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-teal-700 hover:underline">
                  View sheriff sale page <ExternalLink className="h-3.5 w-3.5" />
                </button>
              ) : property.foreclosure_source_url && (
                <a href={property.foreclosure_source_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-teal-700 hover:underline">
                  Open source record <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}
              <div className="mt-4 border-t border-slate-100 pt-3">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Sheriff status history</h4>
                {property.status_history?.length ? (
                  <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200">
                    <div className="grid grid-cols-[1fr_auto] gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      <span>Status</span><span>Date</span>
                    </div>
                    {property.status_history.map((entry, index) => (
                      <div key={`${entry.observed_at}-${entry.status}-${index}`} className="grid grid-cols-[1fr_auto] gap-3 border-b border-slate-100 px-3 py-2 text-xs last:border-0">
                        <span className="font-medium capitalize text-slate-800">{(entry.raw_status || entry.status).replaceAll("_", " ")}</span>
                        <span className="text-right text-slate-500">{date(entry.event_date || entry.sale_date || entry.observed_at)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="text-xs text-slate-500">No sheriff status history recorded.</p>}
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 p-4">
              <h3 className="mb-3 flex items-center gap-2 font-bold text-slate-900"><ShieldAlert className="h-4 w-4 text-teal-600" />Lien screening</h3>
              <dl>
                <Fact label="Known exposure" value={currency(property.known_lien_exposure)} />
                <Fact label="Lien risk" value={property.lien_risk_level ?? "Unavailable"} />
                <Fact label="Records found" value={property.lien_record_count ?? 0} />
                <Fact label="May survive sale" value={property.potentially_surviving_lien_count ?? 0} />
              </dl>
              {liens.length > 0 && (
                <div className="mt-4 overflow-x-auto border-t border-slate-100 pt-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Public-record documents</p>
                  <table className="w-full min-w-[42rem] text-left text-xs">
                    <thead><tr className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-500"><th className="px-2 py-2">Type</th><th className="px-2 py-2">Creditor / debtor</th><th className="px-2 py-2">Amount</th><th className="px-2 py-2">Recorded</th><th className="px-2 py-2">Status</th><th className="px-2 py-2">Confidence</th><th className="px-2 py-2">Source</th></tr></thead>
                    <tbody>{liens.map((lien) => <tr key={lien.id} className="border-b border-slate-100 align-top last:border-0">
                      <td className="px-2 py-2 font-semibold text-slate-800">{lien.lien_type.replaceAll("_", " ")}{lien.requires_manual_review && <span className="ml-1 text-amber-700" title="Manual review required">*</span>}</td>
                      <td className="max-w-48 px-2 py-2 text-slate-700">{lien.creditor_name || "Unknown creditor"}<br /><span className="text-slate-500">{lien.debtor_name || "Unknown debtor"}</span></td>
                      <td className="px-2 py-2 text-slate-700">{currency(lien.current_amount ?? lien.original_amount)}</td>
                      <td className="px-2 py-2 text-slate-700">{date(lien.recording_date)}</td>
                      <td className="px-2 py-2 text-slate-700">{lien.status.replaceAll("_", " ")}</td>
                      <td className="px-2 py-2 text-slate-700">{lien.match_confidence}%</td>
                      <td className="px-2 py-2">{lien.source_url ? <a href={lien.source_url} target="_blank" rel="noopener noreferrer" className="text-teal-700 underline">{lien.source_name.replaceAll("_", " ")}</a> : lien.source_name.replaceAll("_", " ")}</td>
                    </tr>)}</tbody>
                  </table>
                  <p className="mt-2 text-[11px] text-slate-500">* Manual review required. A returned document does not by itself establish that it matches this property or remains active.</p>
                </div>
              )}
              <div className="mt-4 border-t border-slate-100 pt-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Source coverage</p>
                {coverageLoading ? (
                  <p className="text-sm text-slate-500">Loading coverage…</p>
                ) : coverage.length === 0 ? (
                  <p className="text-sm text-slate-500">No source coverage has been recorded.</p>
                ) : (
                  <div className="max-h-40 space-y-2 overflow-y-auto">
                    {coverage.map((item) => (
                      <div key={`${item.category}-${item.source_name}`} className="flex items-center justify-between gap-3 text-xs">
                        <span className="text-slate-700">{item.source_name}<span className="ml-1 text-[10px] text-slate-400">{date(item.checked_at)}</span></span>
                        <span className="rounded bg-slate-100 px-2 py-1 font-medium text-slate-600">{item.status.replaceAll("_", " ")}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <p className="mt-4 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">This is preliminary public-record screening, not a title search.</p>
              {titleSearch && (
                <div className="mt-4 rounded-xl border border-teal-200 bg-teal-50 p-4">
                  <h4 className="font-bold text-slate-900">Comprehensive Title Search</h4>
                  <p className="mt-2 text-xs leading-5 text-slate-700">
                    For additional due diligence before bidding, consider obtaining a professional title search from an independent title-search provider. A professional search may identify recorded interests, liens, judgments, ownership issues, easements, municipal charges, and other matters that may not appear in this preliminary analysis.
                  </p>
                  <a
                    href={titleSearch.provider_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-teal-700 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-800"
                  >
                    Order Comprehensive Title Search <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  <p className="mt-2 text-[11px] text-slate-600">
                    Provided by independent third-party provider: {titleSearch.provider_name}
                  </p>
                </div>
              )}
            </section>
          </div>

          <div className="mt-5 flex flex-wrap gap-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <span className="flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />Valuation retrieved: {date(property.valuation_retrieved_at)}</span>
            <span>Coordinate source: {property.coordinate_source?.replaceAll("_", " ") ?? "Unavailable"}</span>
          </div>

          {typeof property.apify_data?.description === "string" && property.apify_data.description && (
            <section className="mt-5 rounded-xl border border-slate-200 p-4">
              <h3 className="mb-2 font-bold text-slate-900">Description</h3>
              <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{property.apify_data.description}</p>
            </section>
          )}

          <section className="mt-5 rounded-xl border border-slate-200 p-4">
            <h3 className="mb-3 font-bold text-slate-900">Listing Details</h3>
            <dl className="grid gap-x-6 sm:grid-cols-2">
              {zillowDetailKeys
                .filter((key) => key !== "garageSpaces" || parkingInfo(property.apify_data?.parking)?.hasGarage)
                .map((key) => (
                  <Fact key={key} label={zillowLabel(key)} value={readableZillowValue(key, property.apify_data?.[key], property.apify_data)} />
                ))}
            </dl>
          </section>

          <ApifyTable title="Listing price history" value={property.apify_data?.listingPriceHistory} />
          <ApifyTable title="Listing tax history" value={property.apify_data?.listingTaxHistory} />
          <ApifyTable title="Nearby properties" value={property.apify_data?.nearbyProperties} />
          <ApifyTable title="Nearby schools" value={property.apify_data?.nearbySchools} />
        </div>
      </article>
    </div>
  );
}
