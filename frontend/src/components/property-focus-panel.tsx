import { ArrowLeft, Bath, BedDouble, CalendarDays, ExternalLink, Gavel, MapPin, Maximize2, Ruler } from "lucide-react";
import type { ReactNode } from "react";

import { PropertyPhoto } from "@/components/property-photo";
import { googleMapsUrl, zillowListingUrl } from "@/lib/zillow";
import type { Property } from "@/types/property";

function currency(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function date(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}

function Metric({ label, value, tone = "text-slate-950", action }: { label: string; value: string; tone?: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 flex items-baseline gap-2 text-base font-bold tabular-nums ${tone}`}>{value}{action}</p>
    </div>
  );
}

/** The property picked on the map, shown in place of the list in the right panel. */
export function PropertyFocusPanel({
  property,
  onBack,
  onOpenDetails,
  onSalePageClick,
  onProbabilityReasonClick,
}: {
  property: Property;
  onBack: () => void;
  onOpenDetails: () => void;
  onSalePageClick: () => void;
  onProbabilityReasonClick: () => void;
}) {
  const zillowUrl = zillowListingUrl(property);
  const equity = property.gross_equity;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <button type="button" onClick={onBack} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100">
          <ArrowLeft className="h-4 w-4" />Back to list
        </button>
      </div>

      <div className="relative aspect-[4/3] w-full overflow-hidden bg-gradient-to-br from-slate-100 to-slate-200">
        <PropertyPhoto key={property.property_id} property={property} showMissingText />
        <span className="absolute left-3 top-3 rounded-full bg-white/95 px-2.5 py-1 text-xs font-semibold capitalize text-amber-800 shadow">
          {property.current_status.replaceAll("_", " ")}
        </span>
      </div>

      <div className="space-y-4 p-4">
        <div className="flex items-start gap-1.5 text-slate-800">
          <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">{property.street_address}</p>
            <p className="text-sm text-slate-500">{property.city}, {property.state} {property.zip_code ?? ""} · {property.county} County</p>
            <div className="mt-1.5 flex flex-nowrap items-center gap-1.5 overflow-x-auto">
              {zillowUrl && (
                <a href={zillowUrl} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold leading-4 ring-1 ring-inset bg-blue-50 text-blue-700 ring-blue-200 hover:bg-blue-100">
                  Zillow<ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              )}
              <a href={googleMapsUrl(property)} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold leading-4 ring-1 ring-inset bg-emerald-50 text-emerald-700 ring-emerald-200 hover:bg-emerald-100">
                Google Maps<ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
              <button type="button" onClick={onOpenDetails} className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold leading-4 ring-1 ring-inset bg-teal-50 text-teal-700 ring-teal-200 hover:bg-teal-100">
                Full Details<Maximize2 className="h-3 w-3" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Metric label="Est. market value" value={currency(property.zestimate ?? property.market_value)} />
          <Metric
            label={`Minimum bid${property.minimum_bid_basis === "judgment" ? " · judgment" : property.minimum_bid_basis === "notice_estimate" ? " · notice estimate" : property.minimum_bid_basis === "approx_upset" ? " · approx. upset" : ""}`}
            value={currency(property.minimum_asking_amount)}
          />
          <Metric label="Gross equity" value={currency(equity)} tone={equity == null ? "text-slate-950" : equity >= 0 ? "text-teal-700" : "text-red-700"} />
          <Metric label="Gross equity %" value={percent(property.gross_equity_percent)} />
          <Metric label="Probability to auction" value={percent(property.sale_probability)} action={property.sale_probability != null && (
            <button type="button" onClick={onProbabilityReasonClick} className="text-xs font-medium text-teal-700 underline hover:text-teal-900">Reason</button>
          )} />
          <Metric label="Sale date" value={date(property.current_sale_date)} />
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
          {property.bedrooms != null && <span className="flex items-center gap-1"><BedDouble className="h-4 w-4" />{property.bedrooms} beds</span>}
          {property.bathrooms != null && <span className="flex items-center gap-1"><Bath className="h-4 w-4" />{property.bathrooms} baths</span>}
          {property.square_feet != null && <span className="flex items-center gap-1"><Ruler className="h-4 w-4" />{property.square_feet.toLocaleString()} sqft</span>}
          <span className="flex items-center gap-1"><Gavel className="h-4 w-4" />{property.sheriff_number}</span>
          {property.court_case_number && (
            <button type="button" onClick={onSalePageClick} className="font-medium text-teal-700 underline hover:text-teal-900" title="View the sheriff sale page">
              Case {property.court_case_number}
            </button>
          )}
          <span className="flex items-center gap-1"><CalendarDays className="h-4 w-4" />{date(property.current_sale_date)}</span>
        </div>

        <p className="text-[11px] leading-relaxed text-slate-500">
          Gross equity is the estimated market value minus the minimum bid. It is not auction equity and excludes liens,
          taxes and fees. Photo and value from Zillow.
        </p>
      </div>
    </div>
  );
}
