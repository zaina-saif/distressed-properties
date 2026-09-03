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
import { useEffect, useState } from "react";

import { getLienCoverage } from "@/services/properties";
import type { LienCoverageItem, Property } from "@/types/property";

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

function date(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function valuationProviderLabel(value: string | null | undefined): string {
  if (value === "realie") return "Realie AVM";
  if (value === "monmouth_xgboost_avm_v2") return "Monmouth AVM";
  if (value === "monroe_kiz_xgboost_avm_v1") return "Monroe experimental AVM";
  if (value === "rentcast") return "RentCast";
  if (value === "manual_csv" || value === "manual") return "Manual review";
  return value ?? "Valuation pending";
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2.5 last:border-0">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-right text-sm font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

export function PropertyDetailModal({
  property,
  onClose,
}: {
  property: Property;
  onClose: () => void;
}) {
  const [coverage, setCoverage] = useState<LienCoverageItem[]>([]);
  const [coverageLoading, setCoverageLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getLienCoverage(property.property_id)
      .then((items) => { if (active) setCoverage(items); })
      .catch(() => { if (active) setCoverage([]); })
      .finally(() => { if (active) setCoverageLoading(false); });
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
              <p className="mt-1 text-xs text-slate-500">{valuationProviderLabel(property.valuation_provider ?? property.valuation_status)}</p>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Gross equity</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{currency(property.gross_equity)}</p>
              <p className="mt-1 text-xs text-slate-500">{percent(property.gross_equity_percent)} of estimated value</p>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Preferred upset</p>
              <p className="mt-2 text-2xl font-bold text-slate-950">{currency(property.upset_price)}</p>
              <p className="mt-1 text-xs text-slate-500">Judgment: {currency(property.judgment_amount)}</p>
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
                <Fact label="Property type" value={property.property_type ?? "Unavailable"} />
                <Fact label="Bedrooms" value={property.bedrooms ?? "Unavailable"} />
                <Fact label="Bathrooms" value={property.bathrooms ?? "Unavailable"} />
                <Fact label="Square feet" value={property.square_feet?.toLocaleString() ?? "Unavailable"} />
                <Fact label="Acreage" value={property.acreage ?? "Unavailable"} />
                <Fact label="Year built" value={property.year_built ?? "Unavailable"} />
                <Fact label="Parcel ID" value={property.pams_pin ?? "Unavailable"} />
              </dl>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                {property.bedrooms != null && <span className="flex items-center gap-1"><BedDouble className="h-3.5 w-3.5" />{property.bedrooms} beds</span>}
                {property.bathrooms != null && <span className="flex items-center gap-1"><Bath className="h-3.5 w-3.5" />{property.bathrooms} baths</span>}
                {property.square_feet != null && <span className="flex items-center gap-1"><Ruler className="h-3.5 w-3.5" />{property.square_feet.toLocaleString()} sqft</span>}
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 p-4">
              <h3 className="mb-3 flex items-center gap-2 font-bold text-slate-900"><Gavel className="h-4 w-4 text-teal-600" />Sheriff sale</h3>
              <dl>
                <Fact label="Status" value={property.current_status} />
                <Fact label="Sale date" value={date(property.current_sale_date)} />
                <Fact label="Sheriff number" value={property.sheriff_number} />
                <Fact label="Court case" value={property.court_case_number ?? "Unavailable"} />
                <Fact label="Plaintiff" value={property.plaintiff ?? "Unavailable"} />
                <Fact label="Defendant" value={property.defendant ?? "Unavailable"} />
              </dl>
              {property.foreclosure_source_url && (
                <a href={property.foreclosure_source_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-teal-700 hover:underline">
                  Open source record <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}
            </section>

            <section className="rounded-xl border border-slate-200 p-4">
              <h3 className="mb-3 flex items-center gap-2 font-bold text-slate-900"><ShieldAlert className="h-4 w-4 text-teal-600" />Lien screening</h3>
              <dl>
                <Fact label="Known exposure" value={currency(property.known_lien_exposure)} />
                <Fact label="Lien risk" value={property.lien_risk_level ?? "Unavailable"} />
                <Fact label="Records found" value={property.lien_record_count ?? 0} />
                <Fact label="May survive sale" value={property.potentially_surviving_lien_count ?? 0} />
              </dl>
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
                        <span className="text-slate-700">{item.source_name}</span>
                        <span className="rounded bg-slate-100 px-2 py-1 font-medium text-slate-600">{item.status.replaceAll("_", " ")}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <p className="mt-4 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">This is preliminary public-record screening, not a title search.</p>
            </section>
          </div>

          <div className="mt-5 flex flex-wrap gap-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <span className="flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />Valuation retrieved: {date(property.valuation_retrieved_at)}</span>
            <span>AVM confidence: {percent(property.valuation_confidence)}</span>
            <span>Coordinate source: {property.coordinate_source?.replaceAll("_", " ") ?? "Unavailable"}</span>
          </div>
        </div>
      </article>
    </div>
  );
}
