import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";

import type { Property } from "@/types/property";

function currency(value: number | null | undefined): string {
  if (value == null) return "";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function percent(value: number | null | undefined): string {
  if (value == null) return "";
  return `${Math.round(value * 100)}%`;
}

function date(value: string | null | undefined): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function text(value: string | number | null | undefined): ReactNode {
  return value ?? "";
}

function readableApifyValue(value: unknown, depth = 0): string {
  if (value == null || value === "") return "";
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const shown = value.slice(0, 4).map((item) => readableApifyValue(item, depth + 1)).filter(Boolean);
    return `${shown.join(" | ")}${value.length > 4 ? ` | +${value.length - 4} more` : ""}`;
  }
  if (depth >= 2) return JSON.stringify(value);
  return Object.entries(value)
    .map(([key, item]) => `${key.replaceAll(/([A-Z])/g, " $1").replace(/^./, (char) => char.toUpperCase())}: ${readableApifyValue(item, depth + 1)}`)
    .join("; ");
}

function apifyValue(value: unknown, key?: string): ReactNode {
  if (value == null || value === "") return "";
  if (key === "lotArea" && typeof value === "object" && value !== null && "value" in value && typeof value.value === "number") {
    const unit = "unit" in value && typeof value.unit === "string" ? value.unit.toLowerCase() : "";
    const acres = unit.includes("acre") ? value.value : value.value / 43560;
    return `${acres.toLocaleString("en-US", { maximumFractionDigits: 2 })} acres`;
  }
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  return readableApifyValue(value);
}

function duration(property: Property): ReactNode {
  const years = (days: number) => days < 365 ? `${Math.round(days / 30.44)} months` : `${(days / 365.25).toFixed(1)} years`;
  if (property.distress_duration_days != null) return years(property.distress_duration_days);
  if (property.distress_duration_min_days != null && property.distress_duration_max_days != null) {
    return <span title={property.distress_start_basis ?? undefined}>{years(property.distress_duration_min_days)}–{years(property.distress_duration_max_days)} (case-year bound)</span>;
  }
  return text(null);
}

type Column = {
  label: string;
  className?: string;
  value: (property: Property) => ReactNode;
};

function sortKey(label: string): string {
  const key = label.toLowerCase().replace("%", "percent").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  if (key === "time-in-distress") return "distress-duration";
  if (key === "parcel-tax-id") return "bbl";
  return key;
}

const addressColumn: Column = {
  label: "Address",
  className: "min-w-60",
  value: (p) => (
    <span className="block">
      <a
        href={`https://www.zillow.com/homes/${encodeURIComponent(p.normalized_address)}_rb/`}
        target="_blank"
        rel="noopener noreferrer"
        title="Search this address on Zillow (opens in a new tab)"
        aria-label={`Search ${p.normalized_address} on Zillow (opens in a new tab)`}
        className="font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900"
      >
        <span className="block">{p.street_address || p.normalized_address}</span>
        {(p.city || p.state) && <span className="block">{[p.city, p.state].filter(Boolean).join(", ")}</span>}
        {p.zip_code && <span className="block">{p.zip_code}</span>}
      </a>
    </span>
  ),
};

const columns: Column[] = [
  { label: "Estimated Market Value", value: (p) => apifyValue(p.apify_data?.zestimate) },
  { label: "Minimum bid amount", value: (p) => currency(p.upset_price ?? p.judgment_amount) },
  { label: "Gross equity", value: (p) => <span className="font-semibold text-teal-700">{currency(p.gross_equity)}</span> },
  { label: "Gross equity %", value: (p) => percent(p.gross_equity_percent) },
  {
    label: "Description",
    className: "min-w-64",
    value: (p) => {
      const description = typeof p.apify_data?.description === "string" ? p.apify_data.description : "";
      return description ? (
        <span className="group relative block">
          <span className="line-clamp-2">{description}</span>
          <span
            aria-label="View full description"
            className="relative mt-1 inline-block cursor-help text-xs font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2"
          >
            View full
            <span role="tooltip" className="pointer-events-none invisible absolute bottom-full left-0 z-50 mb-2 block w-96 max-w-[min(24rem,calc(100vw-2rem))] rounded-lg bg-slate-950 p-3 text-left text-xs font-normal leading-5 text-white opacity-0 shadow-xl transition-opacity group-hover:visible group-hover:opacity-100">
              {description}
            </span>
          </span>
        </span>
      ) : text(null);
    },
  },
  { label: "Status", value: (p) => <span className="font-medium capitalize">{p.current_status.replaceAll("_", " ")}</span> },
  { label: "Sale date", value: (p) => date(p.current_sale_date) },
  { label: "Court case", value: (p) => text(p.court_case_number) },
  { label: "Plaintiff", className: "min-w-56", value: (p) => text(p.plaintiff) },
  { label: "Defendant", className: "min-w-56", value: (p) => text(p.defendant) },
  { label: "Time in distress", className: "min-w-44", value: duration },
  { label: "Notice lien amount", value: (p) => currency(p.notice_lien_amount) },
  { label: "Probability to auction", value: (p) => percent(p.sale_probability) },
  { label: "Lien risk score", value: (p) => text(p.lien_risk_score) },
  { label: "Lien risk level", value: (p) => text(p.lien_risk_level) },
  { label: "Lien risk confidence", value: (p) => percent(p.lien_risk_confidence) },
  { label: "Total lien amount", value: (p) => currency(p.total_lien_amount) },
  { label: "Valuation retrieved", value: (p) => date(p.valuation_retrieved_at) },
  { label: "Lien risk calculated", value: (p) => date(p.lien_risk_calculated_at) },
];

const apifyColumnKeys = [
  "homeType", "lastSoldPrice", "bedrooms", "bathrooms", "livingArea", "yearBuilt",
  "daysOnZillow", "pageViewCount", "favoriteCount", "rentZestimate",
  "lotArea", "pricePerSquareFoot", "taxAssessedValue", "onMarketDate", "taxAnnualAmount",
  "parking", "dateSold", "priceChange", "priceChangedAt", "monthlyHoaFee",
  "hoa", "propertyTaxRate", "listingMortgageRates",
];

function tableColumns(showOpeningBid: boolean): Column[] {
  const equityColumns: Column[] = showOpeningBid
    ? [{ label: "Opening bid", value: (p: Property) => currency(p.opening_bid) }]
    : [];
  return [
    ...columns.slice(0, 4),
    ...equityColumns,
    ...columns.slice(4),
    ...apifyColumnKeys.map((key) => ({
      label: key,
      className: "min-w-40",
      value: (property: Property) => apifyValue(property.apify_data?.[key], key),
    })),
  ];
}

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
  const visibleColumns = tableColumns(properties.length > 0 && properties.every((property) => property.state === "IL"));
  function sortIcon(column: string) {
    if (sort !== column) return <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" />;
    return sortDirection === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-teal-700" /> : <ArrowDown className="h-3.5 w-3.5 text-teal-700" />;
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto bg-white">
      <table className="w-max min-w-full border-separate border-spacing-0 text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="sticky left-0 z-20 min-w-60 border-b border-r border-slate-300 bg-slate-100 px-3 py-3"><button type="button" onClick={() => onSort("address")} className="flex w-full items-start justify-between gap-2 text-left">Address{sortIcon("address")}</button></th>
            <th className="min-w-44 border-b border-r border-slate-300 bg-slate-100 px-3 py-3"><button type="button" onClick={() => onSort("sale-type")} className="flex w-full items-start justify-between gap-2 text-left">Distress source{sortIcon("sale-type")}</button></th>
            {visibleColumns.map((column) => {
              const key = sortKey(column.label);
              const sortable = column.label !== "zestimate" && !apifyColumnKeys.includes(column.label);
              return <th key={column.label} className={`${column.className ?? "min-w-32"} whitespace-normal border-b border-r border-slate-300 px-3 py-3 align-top`}><button type="button" disabled={!sortable} onClick={() => sortable && onSort(key)} className="flex w-full items-start justify-between gap-2 text-left disabled:cursor-default">{column.label}{sortable && sortIcon(key)}</button></th>;
            })}
          </tr>
        </thead>
        <tbody>
          {properties.map((property) => (
            <tr key={property.sheriff_sale_id} className="odd:bg-white even:bg-slate-50 hover:bg-teal-50">
              <td className="sticky left-0 z-[1] min-w-60 border-b border-r border-slate-200 bg-inherit px-3 py-3 align-top text-slate-700">
                {addressColumn.value(property)}
                <button type="button" onClick={() => onPropertyClick(property)} className="mt-1 block text-xs font-medium text-slate-600 underline hover:text-slate-900">
                  More details
                </button>
              </td>
              <td className="min-w-44 border-b border-r border-slate-200 bg-inherit px-3 py-3 align-top">
                <span className="inline-block rounded-full bg-teal-50 px-2 py-1 text-xs font-semibold text-teal-800">{property.sale_type ?? "Sheriff sale"}</span>
                <button type="button" onClick={() => onPropertyClick(property)} className="mt-1 block text-xs font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900" aria-label={`View details for sheriff sale ${property.sheriff_number}`}>
                  {property.sheriff_number}
                </button>
              </td>
              {visibleColumns.map((column) => <td key={column.label} className={`${column.className ?? "min-w-32"} max-w-80 whitespace-normal break-words border-b border-r border-slate-200 px-3 py-3 align-top text-slate-700`}>{column.value(property)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
