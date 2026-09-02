import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";

import type { Property } from "@/types/property";

function currency(value: number | null | undefined): string {
  if (value == null) return "Pending";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function percent(value: number | null | undefined): string {
  if (value == null) return "Pending";
  return `${Math.round(value * 100)}%`;
}

function date(value: string | null | undefined): string {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function text(value: string | number | null | undefined): ReactNode {
  return value == null || value === "" ? <span className="text-slate-400">Pending</span> : value;
}

function lienSummary(property: Property): ReactNode {
  if (!property.lien_items?.length) return <span className="text-slate-400">None identified</span>;
  return (
    <div className="space-y-1">
      {property.lien_items.map((lien) => (
        <div key={lien.id} className="border-b border-slate-100 pb-1 last:border-0">
          <span className="font-medium text-slate-800">{lien.holder}</span>
          <span className="block text-xs text-slate-500">{lien.type} · {lien.position} · {currency(lien.amount)}</span>
        </div>
      ))}
    </div>
  );
}

function hasLakefrontAddressSignal(property: Property): boolean {
  const address = `${property.street_address} ${property.normalized_address}`.toUpperCase();
  return /\b(?:LAKEFRONT|LAKE\s+FRONT|LAKESHORE|LAKE\s+SHORE|LAKESIDE)\b/.test(address);
}

type Column = {
  label: string;
  className?: string;
  value: (property: Property) => ReactNode;
};

function sortKey(label: string): string {
  return label.toLowerCase().replace("%", "percent").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const columns: Column[] = [
  { label: "Address", className: "min-w-60", value: (p) => <span className="font-semibold text-slate-900">{p.normalized_address}</span> },
  { label: "Street address", className: "min-w-48", value: (p) => text(p.street_address) },
  { label: "City", value: (p) => text(p.city) },
  { label: "County", value: (p) => text(p.county) },
  { label: "State", value: (p) => text(p.state) },
  { label: "ZIP", value: (p) => text(p.zip_code) },
  {
    label: "Lakefront",
    value: (p) => (
      <span title="Address-text screening signal only; parcel shoreline contact has not been verified.">
        {hasLakefrontAddressSignal(p) ? "Yes" : "No"}
      </span>
    ),
  },
  { label: "Court case", value: (p) => text(p.court_case_number) },
  { label: "Status", value: (p) => <span className="font-medium capitalize">{p.current_status}</span> },
  { label: "Sale date", value: (p) => date(p.current_sale_date) },
  { label: "Plaintiff", className: "min-w-56", value: (p) => text(p.plaintiff) },
  { label: "Defendant", className: "min-w-56", value: (p) => text(p.defendant) },
  { label: "Estimated market value", value: (p) => currency(p.market_value) },
  { label: "Value range low", value: (p) => currency(p.market_value_low) },
  { label: "Value range high", value: (p) => currency(p.market_value_high) },
  { label: "Valuation provider", value: (p) => text(p.valuation_provider) },
  { label: "Valuation confidence", value: (p) => percent(p.valuation_confidence) },
  { label: "Valuation status", value: (p) => text(p.valuation_status) },
  { label: "Valuation note", className: "min-w-64", value: (p) => text(p.valuation_pending_reason) },
  { label: "Upset price", value: (p) => currency(p.upset_price) },
  { label: "Judgment amount", value: (p) => currency(p.judgment_amount) },
  { label: "Gross equity", value: (p) => <span className="font-semibold text-teal-700">{currency(p.gross_equity)}</span> },
  { label: "Gross equity %", value: (p) => percent(p.gross_equity_percent) },
  { label: "Probability to auction", value: (p) => percent(p.sale_probability) },
  { label: "Overall risk score", value: (p) => text(p.risk_score) },
  { label: "Overall risk level", value: (p) => text(p.risk_level) },
  { label: "Lien risk score", value: (p) => text(p.lien_risk_score) },
  { label: "Lien risk level", value: (p) => text(p.lien_risk_level) },
  { label: "Lien risk confidence", value: (p) => percent(p.lien_risk_confidence) },
  { label: "Total lien amount", value: (p) => currency(p.total_lien_amount) },
  { label: "Known lien exposure", value: (p) => currency(p.known_lien_exposure) },
  { label: "Lien records", value: (p) => text(p.lien_record_count) },
  { label: "Open liens", value: (p) => text(p.open_lien_count) },
  { label: "Potentially surviving liens", value: (p) => text(p.potentially_surviving_lien_count) },
  { label: "Lien manual review", value: (p) => text(p.lien_manual_review_count) },
  { label: "Lienholders and claims", className: "min-w-72", value: lienSummary },
  { label: "Property type", value: (p) => text(p.property_type) },
  { label: "Bedrooms", value: (p) => text(p.bedrooms) },
  { label: "Bathrooms", value: (p) => text(p.bathrooms) },
  { label: "Square feet", value: (p) => p.square_feet == null ? text(null) : p.square_feet.toLocaleString() },
  { label: "Acreage", value: (p) => text(p.acreage) },
  { label: "Year built", value: (p) => text(p.year_built) },
  { label: "PAMS PIN", value: (p) => text(p.pams_pin) },
  { label: "Block", value: (p) => text(p.block) },
  { label: "Lot", value: (p) => text(p.lot) },
  { label: "Qualifier", value: (p) => text(p.qualifier) },
  { label: "Parcel match confidence", value: (p) => percent(p.parcel_match_confidence == null ? null : p.parcel_match_confidence / 100) },
  { label: "Latitude", value: (p) => text(p.latitude) },
  { label: "Longitude", value: (p) => text(p.longitude) },
  { label: "Coordinate source", value: (p) => text(p.coordinate_source) },
  { label: "Valuation retrieved", value: (p) => date(p.valuation_retrieved_at) },
  { label: "Lien risk calculated", value: (p) => date(p.lien_risk_calculated_at) },
  {
    label: "Foreclosure source",
    value: (p) => p.foreclosure_source_url ? <a href={p.foreclosure_source_url} target="_blank" rel="noreferrer" className="font-medium text-teal-700 underline">Open source</a> : text(null),
  },
];

export function PropertyTable({
  properties,
  onPropertyClick,
  sort,
  sortDirection,
  onSort,
}: {
  properties: Property[];
  onPropertyClick: (property: Property) => void;
  sort: string;
  sortDirection: "asc" | "desc";
  onSort: (column: string) => void;
}) {
  function sortIcon(column: string) {
    if (sort !== column) return <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" />;
    return sortDirection === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-teal-700" /> : <ArrowDown className="h-3.5 w-3.5 text-teal-700" />;
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto bg-white">
      <table className="w-max min-w-full border-separate border-spacing-0 text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="sticky left-0 z-20 min-w-36 border-b border-r border-slate-300 bg-slate-100 px-3 py-3"><button type="button" onClick={() => onSort("sheriff-number")} className="flex w-full items-start justify-between gap-2 text-left">Sheriff number{sortIcon("sheriff-number")}</button></th>
            {columns.map((column) => { const key = sortKey(column.label); return <th key={column.label} className={`${column.className ?? "min-w-32"} whitespace-normal border-b border-r border-slate-300 px-3 py-3 align-top`}><button type="button" onClick={() => onSort(key)} className="flex w-full items-start justify-between gap-2 text-left">{column.label}{sortIcon(key)}</button></th>; })}
          </tr>
        </thead>
        <tbody>
          {properties.map((property) => (
            <tr key={property.sheriff_sale_id} className="odd:bg-white even:bg-slate-50 hover:bg-teal-50">
              <td className="sticky left-0 z-[1] border-b border-r border-slate-200 bg-inherit px-3 py-3 align-top">
                <button type="button" onClick={() => onPropertyClick(property)} className="font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900" aria-label={`View details for sheriff sale ${property.sheriff_number}`}>
                  {property.sheriff_number}
                </button>
              </td>
              {columns.map((column) => <td key={column.label} className={`${column.className ?? "min-w-32"} max-w-80 whitespace-normal break-words border-b border-r border-slate-200 px-3 py-3 align-top text-slate-700`}>{column.value(property)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
