import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";

import type { Property } from "@/types/property";

// "||" so an empty value from a Docker build falls back to the default.
const titleSearchProviderUrl = process.env.NEXT_PUBLIC_TITLE_SEARCH_PROVIDER_URL || "https://www.protitleusa.com/";

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
  const months = (days: number) => `${Math.round(days / 30.44)} months`;
  if (property.distress_duration_days != null) return months(property.distress_duration_days);
  if (property.distress_duration_min_days != null && property.distress_duration_max_days != null) {
    return <span title={property.distress_start_basis ?? undefined}>{months(property.distress_duration_min_days)}–{months(property.distress_duration_max_days)} (case-year bound)</span>;
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
        className="block max-w-64 whitespace-normal break-words font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900"
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
  { label: "Probability to auction", value: (p) => percent(p.sale_probability) },
  { label: "Valuation retrieved", value: (p) => date(p.valuation_retrieved_at) },
];

const apifyColumnKeys = [
  "homeType", "lastSoldPrice", "bedrooms", "bathrooms", "livingArea", "yearBuilt",
];

function tableColumns(showOpeningBid: boolean, onLienSummaryClick: (property: Property) => void, onAdditionalDetailsClick: (property: Property) => void, onProbabilityReasonClick: (property: Property) => void, onSalePageClick: (property: Property) => void): Column[] {
  const equityColumns: Column[] = showOpeningBid
    ? [{ label: "Opening bid", value: (p: Property) => currency(p.opening_bid) }]
    : [];
  return [
    ...columns.slice(0, 4),
    ...equityColumns,
    ...columns.slice(4).map((column) => column.label === "Court case"
      ? { ...column, value: (p: Property) => p.court_case_number
          ? <button type="button" onClick={(event) => { event.stopPropagation(); onSalePageClick(p); }} className="font-semibold text-teal-700 underline hover:text-teal-900" title="View the sheriff sale page">{p.court_case_number}</button>
          : "" }
      : column.label === "Probability to auction"
      ? { ...column, value: (p: Property) => <span className="inline-flex items-center gap-1.5 whitespace-nowrap">{percent(p.sale_probability)}{p.sale_probability != null && <button type="button" onClick={(event) => { event.stopPropagation(); onProbabilityReasonClick(p); }} className="text-xs font-medium text-teal-700 underline hover:text-teal-900">Reason</button>}</span> }
      : column),
    {
      label: "Lien risk summary",
      className: "min-w-44",
      value: (property: Property) => (
        <span className="block">
          <button type="button" onClick={() => onLienSummaryClick(property)} className="block text-xs font-semibold text-teal-700 underline hover:text-teal-900">
            Liens summary
          </button>
          <a href={titleSearchProviderUrl} target="_blank" rel="noopener noreferrer" className="mt-1 block text-xs font-semibold text-teal-700 underline hover:text-teal-900">
            Order Comprehensive Title Search
          </a>
        </span>
      ),
    },
    ...apifyColumnKeys.map((key) => ({
      label: key,
      className: "min-w-40",
      value: (property: Property) => apifyValue(property.apify_data?.[key], key),
    })),
    {
      label: "Additional details",
      className: "min-w-36",
      value: (property: Property) => (
        <button type="button" onClick={() => onAdditionalDetailsClick(property)} className="text-xs font-semibold text-teal-700 underline hover:text-teal-900">
          Complaints
        </button>
      ),
    },
  ];
}

export function PropertyTable({
  properties,
  onPropertyClick,
  onLienSummaryClick,
  onAdditionalDetailsClick,
  onProbabilityReasonClick,
  onStatusHistoryClick,
  onSalePageClick,
  sort,
  sortDirection,
  onSort,
}: {
  properties: Property[];
  onPropertyClick: (property: Property) => void;
  onLienSummaryClick: (property: Property) => void;
  onAdditionalDetailsClick: (property: Property) => void;
  onProbabilityReasonClick: (property: Property) => void;
  onStatusHistoryClick: (property: Property) => void;
  onSalePageClick: (property: Property) => void;
  sort: string;
  sortDirection: "asc" | "desc";
  onSort: (column: string) => void;
}) {
  const visibleColumns = tableColumns(properties.length > 0 && properties.every((property) => property.state === "IL"), onLienSummaryClick, onAdditionalDetailsClick, onProbabilityReasonClick, onSalePageClick);
  function sortIcon(column: string) {
    if (sort !== column) return <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" />;
    return sortDirection === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-teal-700" /> : <ArrowDown className="h-3.5 w-3.5 text-teal-700" />;
  }

  return (
    <>
    <MobilePropertyList properties={properties} onPropertyClick={onPropertyClick} onLienSummaryClick={onLienSummaryClick} onAdditionalDetailsClick={onAdditionalDetailsClick} onProbabilityReasonClick={onProbabilityReasonClick} onStatusHistoryClick={onStatusHistoryClick} onSalePageClick={onSalePageClick} />
    <div className="hidden min-h-0 flex-1 overflow-auto bg-white md:block">
      <table className="w-max min-w-full border-separate border-spacing-0 text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="sticky left-0 z-20 min-w-60 border-b border-r border-slate-300 bg-slate-100 px-3 py-3"><button type="button" onClick={() => onSort("address")} className="flex w-full items-start justify-between gap-2 text-left">Address{sortIcon("address")}</button></th>
            <th className="min-w-32 border-b border-r border-slate-300 bg-slate-100 px-3 py-3"><button type="button" onClick={() => onSort("county")} className="flex w-full items-start justify-between gap-2 text-left">County{sortIcon("county")}</button></th>
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
              <td className="sticky left-0 z-[1] min-w-60 max-w-72 border-b border-r border-slate-200 bg-inherit px-3 py-3 align-top whitespace-normal break-words text-slate-700">
                {addressColumn.value(property)}
              </td>
              <td className="min-w-32 border-b border-r border-slate-200 px-3 py-3 align-top text-slate-700">{property.county}</td>
              <td className="min-w-44 border-b border-r border-slate-200 bg-inherit px-3 py-3 align-top">
                <span className="inline-block rounded-full bg-teal-50 px-2 py-1 text-xs font-semibold text-teal-800">{property.sale_type ?? "Sheriff sale"}</span>
                <button type="button" onClick={() => onPropertyClick(property)} className="mt-1 block text-xs font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-900" aria-label={`View details for sheriff sale ${property.sheriff_number}`}>
                  {property.sheriff_number}
                </button>
                <button type="button" onClick={() => onPropertyClick(property)} className="mt-1 block text-xs font-medium text-slate-600 underline hover:text-slate-900">
                  More details
                </button>
              </td>
              {visibleColumns.map((column) => <td key={column.label} className={`${column.className ?? "min-w-32"} max-w-80 whitespace-normal break-words border-b border-r border-slate-200 px-3 py-3 align-top text-slate-700`}>
                {column.value(property)}
                {column.label === "Time in distress" ? (
                  <button type="button" onClick={() => onStatusHistoryClick(property)} className="mt-1 block text-xs font-medium text-teal-700 underline hover:text-teal-900">
                    View status history
                  </button>
                ) : null}
              </td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

/** Phones get one card per sale instead of the wide table, with the same actions. */
function MobilePropertyList({
  properties,
  onPropertyClick,
  onLienSummaryClick,
  onAdditionalDetailsClick,
  onProbabilityReasonClick,
  onStatusHistoryClick,
  onSalePageClick,
}: {
  properties: Property[];
  onPropertyClick: (property: Property) => void;
  onLienSummaryClick: (property: Property) => void;
  onAdditionalDetailsClick: (property: Property) => void;
  onProbabilityReasonClick: (property: Property) => void;
  onStatusHistoryClick: (property: Property) => void;
  onSalePageClick: (property: Property) => void;
}) {
  const link = "text-xs font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2";
  return (
    <ul className="space-y-3 p-3 md:hidden">
      {properties.map((p) => {
        const facts = [
          apifyValue(p.apify_data?.bedrooms) ? `${apifyValue(p.apify_data?.bedrooms)} bd` : "",
          apifyValue(p.apify_data?.bathrooms) ? `${apifyValue(p.apify_data?.bathrooms)} ba` : "",
          apifyValue(p.apify_data?.livingArea) ? `${apifyValue(p.apify_data?.livingArea)} sqft` : "",
          p.apify_data?.yearBuilt ? `Built ${p.apify_data.yearBuilt}` : "",
          typeof p.apify_data?.homeType === "string" ? p.apify_data.homeType.replaceAll("_", " ").toLowerCase() : "",
        ].filter(Boolean);
        return (
          <li key={p.sheriff_sale_id} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
            <button type="button" onClick={() => onPropertyClick(p)} className="block w-full text-left">
              <span className="block font-semibold text-slate-950">{p.street_address || p.normalized_address}</span>
              <span className="block text-xs text-slate-500">{[p.city, p.state, p.zip_code].filter(Boolean).join(", ")}{p.county ? ` · ${p.county} County` : ""}</span>
            </button>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
              <span className="rounded-full bg-teal-50 px-2 py-0.5 font-semibold text-teal-800">{p.sale_type ?? "Sheriff sale"}</span>
              {p.current_sale_date && <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">Sale {date(p.current_sale_date)}</span>}
              <span className="rounded-full bg-slate-100 px-2 py-0.5 capitalize text-slate-600">{p.current_status.replaceAll("_", " ")}</span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
              <div><dt className="text-slate-500">Est. market value</dt><dd className="font-semibold text-slate-900">{typeof p.apify_data?.zestimate === "number" ? currency(p.apify_data.zestimate) : apifyValue(p.apify_data?.zestimate) || "—"}</dd></div>
              <div><dt className="text-slate-500">Minimum bid</dt><dd className="font-semibold text-slate-900">{currency(p.upset_price ?? p.judgment_amount) || "—"}</dd></div>
              <div><dt className="text-slate-500">Gross equity</dt><dd className="font-semibold text-teal-700">{currency(p.gross_equity) || "—"}{p.gross_equity_percent != null ? ` (${percent(p.gross_equity_percent)})` : ""}</dd></div>
              <div><dt className="text-slate-500">Probability to auction</dt><dd className="font-semibold text-slate-900">{percent(p.sale_probability) || "—"}{p.sale_probability != null && <button type="button" onClick={() => onProbabilityReasonClick(p)} className={`ml-1.5 ${link}`}>Reason</button>}</dd></div>
            </dl>
            {facts.length > 0 && <p className="mt-2 text-xs text-slate-600">{facts.join(" · ")}</p>}
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 border-t border-slate-100 pt-2">
              <button type="button" onClick={() => onPropertyClick(p)} className={link}>More details</button>
              {p.court_case_number && <button type="button" onClick={() => onSalePageClick(p)} className={link}>Sale page</button>}
              <button type="button" onClick={() => onLienSummaryClick(p)} className={link}>Liens summary</button>
              <button type="button" onClick={() => onStatusHistoryClick(p)} className={link}>Status history</button>
              <button type="button" onClick={() => onAdditionalDetailsClick(p)} className={link}>Complaints</button>
              <a href={titleSearchProviderUrl} target="_blank" rel="noopener noreferrer" className={link}>Title search</a>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
