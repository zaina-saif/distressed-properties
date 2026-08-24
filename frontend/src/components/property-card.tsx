import {
  Bath,
  BedDouble,
  CalendarDays,
  Gavel,
  Home,
  MapPin,
  Ruler,
} from "lucide-react";

import type { Property } from "@/types/property";

function currency(value: number | null | undefined): string {
  if (value == null) return "Pending";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function date(value: string | null | undefined): string {
  if (!value) return "Date pending";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export function PropertyCard({
  property,
  selected,
  onClick,
}: {
  property: Property;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full overflow-hidden rounded-xl border bg-white text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
        selected ? "border-teal-600 ring-2 ring-teal-100" : "border-slate-200"
      }`}
    >
      <div className="flex min-h-36">
        <div className="flex w-32 shrink-0 items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 sm:w-40">
          <Home className="h-10 w-10 text-slate-400" aria-hidden="true" />
        </div>

        <div className="min-w-0 flex-1 p-4">
          <div className="mb-2 flex items-start justify-between gap-3">
            <div>
              <p className="text-xl font-bold text-slate-950">
                {currency(property.market_value)}
              </p>
              <p className="mt-0.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Estimated value
              </p>
            </div>
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold capitalize text-amber-800">
              {property.current_status}
            </span>
          </div>

          <div className="flex items-start gap-1.5 text-sm text-slate-700">
            <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" aria-hidden="true" />
            <span>
              {property.street_address}
              <br />
              {property.city}, {property.state} {property.zip_code ?? ""}
            </span>
          </div>

          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
            {property.bedrooms != null && (
              <span className="flex items-center gap-1"><BedDouble className="h-3.5 w-3.5" />{property.bedrooms} beds</span>
            )}
            {property.bathrooms != null && (
              <span className="flex items-center gap-1"><Bath className="h-3.5 w-3.5" />{property.bathrooms} baths</span>
            )}
            {property.square_feet != null && (
              <span className="flex items-center gap-1"><Ruler className="h-3.5 w-3.5" />{property.square_feet.toLocaleString()} sqft</span>
            )}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-3 text-sm">
            <div>
              <p className="text-xs text-slate-500">Est. gross equity</p>
              <p className="font-semibold text-teal-700">{currency(property.gross_equity)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Preferred upset</p>
              <p className="font-semibold text-slate-900">{currency(property.upset_price)}</p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <span className="flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />{date(property.current_sale_date)}</span>
            <span className="flex items-center gap-1"><Gavel className="h-3.5 w-3.5" />{property.sheriff_number}</span>
          </div>
        </div>
      </div>
    </button>
  );
}
